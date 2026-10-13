"""Merge newly extracted items into existing pages that describe the same
thing (WeKnora wiki_ingest_dedup.go + deduplicateExtractedBatch).

1. Similarity pre-filter: character-bigram / slug-token Jaccard picks a
   short candidate list per item (stands in for pg_trgm FindSimilarPages).
2. Exact normalized-title matches merge deterministically.
3. The LLM decides the remaining semantic matches; every proposed merge is
   validated against the item's own candidate list."""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Set, Tuple
from xml.sax.saxutils import escape

from . import prompts
from .llm import LLM, LLMError
from .models import PAGE_CONCEPT, PAGE_ENTITY, ExtractedItem, WikiPage

log = logging.getLogger(__name__)

CANDIDATE_TOP_K = 5
CANDIDATE_SCORE_FLOOR = 0.08


def normalize_title(title: str) -> str:
    return "".join(ch.lower() for ch in title.strip() if not ch.isspace())


def _grams(s: str) -> Set[str]:
    s = "".join(ch for ch in s.lower() if ch.isalnum())
    if not s:
        return set()
    if len(s) == 1:
        return {s}
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _slug_tokens(slug: str) -> Set[str]:
    base = slug.split("/", 1)[-1].lower()
    return {t for t in re.split(r"[-_.\s]+", base) if t}


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _page_type_of(slug: str) -> str:
    return slug.split("/", 1)[0]


def _score(item: ExtractedItem, page: WikiPage) -> float:
    best = _jaccard(_slug_tokens(item.slug), _slug_tokens(page.slug))
    item_grams = [_grams(s) for s in [item.name, *item.aliases] if s]
    page_grams = [_grams(s) for s in [page.title, *page.aliases] if s]
    for a in item_grams:
        for b in page_grams:
            best = max(best, _jaccard(a, b))
    return best


def _candidates(item: ExtractedItem, pool: List[WikiPage]) -> List[WikiPage]:
    scored = sorted(((_score(item, p), p.slug, p) for p in pool if p.slug != item.slug),
                    key=lambda t: (-t[0], t[1]))
    return [p for s, _, p in scored[:CANDIDATE_TOP_K] if s >= CANDIDATE_SCORE_FLOOR]


def _exact_target(item: ExtractedItem, item_type: str, pool: List[WikiPage]) -> str:
    """exactIdentityTarget: same-type title match wins, else cross-type."""
    norm = normalize_title(item.name)
    if not norm:
        return ""
    same = [p.slug for p in pool if normalize_title(p.title) == norm and p.page_type == item_type]
    other = [p.slug for p in pool if normalize_title(p.title) == norm and p.page_type != item_type]
    for slug in sorted(same) + sorted(other):
        if slug != item.slug:
            return slug
    return ""


def _render_group(item: ExtractedItem, item_type: str, cands: List[WikiPage]) -> str:
    lines = [f'  <item slug="{item.slug}" type="{item_type}">', f"    <name>{escape(item.name)}</name>"]
    lines += [f"    <alias>{escape(a)}</alias>" for a in item.aliases if a]
    lines.append("    <candidates>")
    for p in cands:
        lines.append(f'      <page slug="{p.slug}" type="{p.page_type}">')
        lines.append(f"        <name>{escape(p.title)}</name>")
        lines += [f"        <alias>{escape(a)}</alias>" for a in p.aliases if a]
        lines.append("      </page>")
    lines += ["    </candidates>", "  </item>"]
    return "\n".join(lines) + "\n"


def _apply_merge(item: ExtractedItem, target: WikiPage) -> None:
    if item.name and normalize_title(item.name) != normalize_title(target.title) and item.name not in item.aliases:
        item.aliases.append(item.name)
    item.slug = target.slug


def deduplicate(llm: LLM, pool: List[WikiPage], entities: List[ExtractedItem],
                concepts: List[ExtractedItem]) -> Tuple[List[ExtractedItem], List[ExtractedItem]]:
    pool = [p for p in pool if p.page_type in (PAGE_ENTITY, PAGE_CONCEPT)]
    if not pool or not (entities or concepts):
        return _collapse(entities), _collapse(concepts)
    by_slug = {p.slug: p for p in pool}

    typed = [(it, PAGE_ENTITY) for it in entities] + [(it, PAGE_CONCEPT) for it in concepts]
    own_cands: Dict[str, Set[str]] = {}
    groups: List[str] = []
    for item, item_type in typed:
        if not item.slug or item.slug in by_slug:
            continue  # re-ingest of an existing page, not a merge
        exact = _exact_target(item, item_type, pool)
        if exact:
            log.info("dedup exact %s -> %s", item.slug, exact)
            _apply_merge(item, by_slug[exact])
            continue
        cands = _candidates(item, pool)
        if cands:
            own_cands[item.slug] = {p.slug for p in cands}
            groups.append(_render_group(item, item_type, cands))

    if groups:
        try:
            result = llm.generate_json(prompts.WIKI_DEDUPLICATION_PROMPT,
                                       {"Candidates": "".join(groups)}, "dedup")
            merges = result.get("merges") or {}
        except LLMError as err:
            log.warning("dedup LLM call failed: %s", err)
            merges = {}
        for item, item_type in typed:
            dst = merges.get(item.slug)
            if not dst or item.slug not in own_cands:
                continue
            if dst not in own_cands[item.slug]:
                log.warning("dedup rejected %s -> %s (not a candidate of this item)", item.slug, dst)
                continue
            if _page_type_of(dst) != item_type:
                log.warning("dedup rejected %s -> %s (type mismatch)", item.slug, dst)
                continue
            log.info("dedup merge %s -> %s", item.slug, dst)
            _apply_merge(item, by_slug[dst])

    return _collapse(entities), _collapse(concepts)


def _collapse(items: List[ExtractedItem]) -> List[ExtractedItem]:
    """Items that ended up on the same slug become one item."""
    out: Dict[str, ExtractedItem] = {}
    for it in items:
        if not it.slug or not it.name:
            continue
        if it.slug not in out:
            out[it.slug] = it
            continue
        dst = out[it.slug]
        for a in [it.name, *it.aliases]:
            if a and a != dst.name and a not in dst.aliases:
                dst.aliases.append(a)
        dst.source_chunks += [c for c in it.source_chunks if c not in dst.source_chunks]
    return list(out.values())
