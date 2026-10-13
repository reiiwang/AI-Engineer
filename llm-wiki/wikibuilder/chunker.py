"""Load markdown source documents and split them into chunks.

WeKnora gets chunks from its docreader service; here we do a heading-aware
markdown split that never cuts through a fenced code block. Chunks are the
unit of citation: every entity/concept page records which chunks it was
written from."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

from .models import Chunk, SourceDoc

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)
_HEADING_RE = re.compile(r"^#{1,6}\s+\S")
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def split_frontmatter(text: str) -> Tuple[Dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), text[m.end():]


def _blocks(body: str) -> List[str]:
    """Split into paragraph-level blocks; headings start their own block and
    fenced code blocks are kept whole."""
    blocks: List[str] = []
    cur: List[str] = []
    fence = ""

    def flush() -> None:
        if cur and "".join(cur).strip():
            blocks.append("\n".join(cur).strip("\n"))
        cur.clear()

    for line in body.splitlines():
        m = _FENCE_RE.match(line)
        if fence:
            cur.append(line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = ""
            continue
        if m:
            fence = m.group(1)
            cur.append(line)
            continue
        if not line.strip():
            flush()
        elif _HEADING_RE.match(line):
            flush()
            cur.append(line)
            flush()
        else:
            cur.append(line)
    flush()
    return blocks


def _hard_split(block: str, size: int) -> List[str]:
    """Greedy split of an oversized block, cutting at the last newline or
    space before the limit (or mid-token if there is none)."""
    parts: List[str] = []
    rest = block
    while len(rest) > size:
        cut = max(rest.rfind("\n", 0, size), rest.rfind(" ", 0, size))
        if cut <= size // 2:
            cut = size
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest.strip():
        parts.append(rest)
    return parts


def chunk_markdown(doc_id: str, body: str, chunk_size: int) -> List[Chunk]:
    pieces: List[str] = []
    cur: List[str] = []
    cur_len = 0
    min_len = chunk_size // 3

    for block in _blocks(body):
        is_heading = bool(_HEADING_RE.match(block))
        if len(block) > chunk_size:
            # Keep pending headings attached to the oversized block they introduce.
            if cur and all(_HEADING_RE.match(b) for b in cur):
                block = "\n\n".join(cur + [block])
            elif cur:
                pieces.append("\n\n".join(cur))
            cur, cur_len = [], 0
            pieces.extend(_hard_split(block, chunk_size))
            continue
        # A heading opens a new chunk once the current one has some substance,
        # so sections stay together whenever they fit.
        if cur and (cur_len + len(block) > chunk_size or (is_heading and cur_len >= min_len)):
            pieces.append("\n\n".join(cur))
            cur, cur_len = [], 0
        cur.append(block)
        cur_len += len(block) + 2
    if cur:
        pieces.append("\n\n".join(cur))

    return [Chunk(id=f"{doc_id}#c{i:04d}", index=i, content=p) for i, p in enumerate(pieces)]


def _doc_title(meta: Dict, body: str, path: Path) -> str:
    if meta.get("title"):
        return str(meta["title"]).strip()
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def load_document(raw_dir: Path, path: Path, chunk_size: int) -> SourceDoc:
    text = path.read_text(encoding="utf-8")
    meta, body = split_frontmatter(text)
    doc_id = path.relative_to(raw_dir).as_posix()
    return SourceDoc(
        id=doc_id,
        title=_doc_title(meta, body, path),
        content=body.strip(),
        hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        chunks=chunk_markdown(doc_id, body, chunk_size),
    )


def scan_documents(raw_dir: Path, patterns: List[str]) -> Dict[str, Path]:
    found: Dict[str, Path] = {}
    for pattern in patterns:
        for p in sorted(raw_dir.glob(pattern)):
            if p.is_file() and not any(part.startswith(".") for part in p.relative_to(raw_dir).parts):
                found[p.relative_to(raw_dir).as_posix()] = p
    return found


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
