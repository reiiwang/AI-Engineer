"""[[slug|text]] wiki-link utilities: parsing, dead-link stripping, request-local
slug handles, and automatic cross-link injection (WeKnora wiki_linkify.go)."""
from __future__ import annotations

import re
import unicodedata
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

WIKI_LINK_RE = re.compile(r"\[\[([^\[\]|]+?)(?:\|([^\[\]]*?))?\]\]")
_CHUNK_CITATION_RE = re.compile(r"\s?\[c\d{3,}\]")


def slugify(s: str) -> str:
    """wiki_ingest.go slugify: lowercase, keep a-z0-9-/ and CJK."""
    out = []
    for ch in s.strip().lower():
        if ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch in "-/":
            out.append(ch)
        elif ch in " _":
            out.append("-")
        elif "一" <= ch <= "鿿":
            out.append(ch)
    slug = re.sub(r"-{2,}", "-", "".join(out)).strip("-")
    slug = re.sub(r"-*/-*", "/", slug)
    return slug[:200]


def normalize_slug(slug: str) -> str:
    return slug.strip().strip("/")


def out_links(content: str) -> List[str]:
    seen: List[str] = []
    for m in WIKI_LINK_RE.finditer(content or ""):
        slug = normalize_slug(m.group(1))
        if slug and slug not in seen:
            seen.append(slug)
    return seen


def rewrite_links(content: str, fn: Callable[[str, str], Optional[str]]) -> Tuple[str, bool]:
    """Call fn(slug, text) for every [[...]] link. Returning a slug rewrites the
    link target; returning None replaces the link with its display text."""
    changed = False

    def sub(m: "re.Match[str]") -> str:
        nonlocal changed
        slug = normalize_slug(m.group(1))
        text = m.group(2)
        new = fn(slug, text or "")
        if new is None:
            changed = True
            return text if text else slug.rsplit("/", 1)[-1]
        if new != slug:
            changed = True
            return f"[[{new}|{text}]]" if text is not None else f"[[{new}]]"
        return m.group(0)

    return WIKI_LINK_RE.sub(sub, content or ""), changed


def strip_dead_links(content: str, live: Set[str], self_slug: str = "") -> Tuple[str, bool]:
    return rewrite_links(content, lambda s, _t: s if s in live and s != self_slug else None)


def remap_links(content: str, mapping: Dict[str, str]) -> str:
    return rewrite_links(content, lambda s, _t: mapping.get(s, s))[0]


def strip_chunk_citations(content: str) -> str:
    """stripWikiInlineChunkCitations: drop legacy inline [c003] handles."""
    return _CHUNK_CITATION_RE.sub("", content or "")


class SlugHandles:
    """wiki_slug_handles.go: hide real slugs behind ref-N handles so the editor
    model never has to retype (and mangle) them."""

    def __init__(self) -> None:
        self.by_slug: Dict[str, str] = {}
        self.by_handle: Dict[str, str] = {}

    def handle(self, slug: str) -> str:
        if slug not in self.by_slug:
            h = f"ref-{len(self.by_slug) + 1}"
            self.by_slug[slug] = h
            self.by_handle[h] = slug
        return self.by_slug[slug]

    def encode(self, content: str, known: Set[str]) -> str:
        return rewrite_links(content, lambda s, _t: self.handle(s) if s in known else s)[0]

    def decode(self, content: str) -> str:
        if not self.by_handle:
            return content
        return rewrite_links(content, lambda s, _t: self.by_handle.get(s, s))[0]


# --- cross-link injection ------------------------------------------------

_FENCE_BLOCK_RE = re.compile(r"^(`{3,}|~{3,})[^\n]*\n.*?^\1[ \t]*$", re.S | re.M)
_FORBIDDEN_RES = [
    re.compile(r"`+[^`\n]*`+"),                    # inline code
    WIKI_LINK_RE,                                   # existing wiki links
    re.compile(r"!?\[[^\]\n]*\]\([^)\n]*\)"),      # markdown links / images
    re.compile(r"!?\[[^\]\n]*\]\[[^\]\n]*\]"),     # reference-style links
    re.compile(r"^\s{0,3}\[[^\]\n]+\]:.*$", re.M),  # reference definitions
    re.compile(r"<https?://[^>\s]+>"),              # autolinks
    re.compile(r"https?://\S+"),                    # bare URLs
    re.compile(r"^#{1,6}\s.*$", re.M),              # headings (don't link titles)
]


def _forbidden_spans(s: str) -> List[Tuple[int, int]]:
    spans = [m.span() for m in _FENCE_BLOCK_RE.finditer(s)]
    for rx in _FORBIDDEN_RES:
        spans.extend(m.span() for m in rx.finditer(s))
    return sorted(spans)


def _is_ascii_word(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum() or ch == "_")


def _overlaps(spans: Iterable[Tuple[int, int]], start: int, end: int) -> bool:
    return any(start < e and end > s for s, e in spans)


def _single_han(s: str) -> bool:
    return len(s) == 1 and unicodedata.name(s, "").startswith("CJK UNIFIED")


def linkify(content: str, refs: List[Tuple[str, str]], self_slug: str) -> Tuple[str, bool]:
    """linkifyContent: wrap the FIRST safe occurrence of each ref's text as
    [[slug|text]]. refs are (slug, match_text). Longer texts win; slugs already
    linked anywhere in the content are skipped."""
    if not content or not refs:
        return content, False
    cand = [(s, t) for s, t in refs if s and t and s != self_slug and not _single_han(t)]
    cand.sort(key=lambda r: len(r[1]), reverse=True)
    used = set(out_links(content))
    spans = _forbidden_spans(content)
    changed = False

    for slug, text in cand:
        if slug in used:
            continue
        needs_boundary = _is_ascii_word(text[0]) or _is_ascii_word(text[-1])
        start = 0
        while True:
            pos = content.find(text, start)
            if pos < 0:
                break
            end = pos + len(text)
            ok = not _overlaps(spans, pos, end)
            if ok and needs_boundary:
                ok = not (pos > 0 and _is_ascii_word(content[pos - 1])) and \
                    not (end < len(content) and _is_ascii_word(content[end]))
            if not ok:
                start = pos + 1
                continue
            repl = f"[[{slug}|{text}]]"
            content = content[:pos] + repl + content[end:]
            delta = len(repl) - len(text)
            spans = sorted([(s + delta, e + delta) if s >= pos else (s, e) for s, e in spans]
                           + [(pos, pos + len(repl))])
            used.add(slug)
            changed = True
            break
    return content, changed
