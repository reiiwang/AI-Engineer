"""Core data types. These are the canonical, format-independent wiki model;
wiki_format.py decides how a WikiPage is written to disk."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

PAGE_ENTITY = "entity"
PAGE_CONCEPT = "concept"
PAGE_SUMMARY = "summary"
PAGE_INDEX = "index"

# SlugUpdate.type values besides the page types above.
UPDATE_RETRACT = "retract"  # doc re-ingested and still mentions the page
UPDATE_RETRACT_STALE = "retractStale"  # doc re-ingested and no longer mentions it


@dataclass
class Chunk:
    id: str  # "<doc_id>#c0003", stable for a given document version
    index: int
    content: str


@dataclass
class SourceDoc:
    id: str  # path relative to raw_dir, POSIX separators
    title: str
    content: str  # body without frontmatter
    hash: str
    chunks: List[Chunk]


@dataclass
class DocRecord:
    """What the state remembers about an ingested source document."""

    id: str
    hash: str
    title: str
    summary_slug: str = ""
    summary_line: str = ""
    summary_body: str = ""
    ingested_at: str = ""


@dataclass
class ExtractedItem:
    name: str = ""
    slug: str = ""
    aliases: List[str] = field(default_factory=list)
    description: str = ""
    details: str = ""
    source_chunks: List[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, d: Dict[str, Any]) -> "ExtractedItem":
        aliases = d.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        return cls(
            name=str(d.get("name") or "").strip(),
            slug=str(d.get("slug") or "").strip(),
            aliases=[str(a).strip() for a in aliases if str(a).strip()],
            description=str(d.get("description") or "").strip(),
            details=str(d.get("details") or "").strip(),
            source_chunks=[str(c) for c in (d.get("source_chunks") or [])],
        )


@dataclass
class SlugUpdate:
    slug: str
    type: str
    doc_id: str
    doc_title: str
    item: ExtractedItem = field(default_factory=ExtractedItem)
    summary_line: str = ""
    summary_body: str = ""
    doc_summary: str = ""
    retract_doc_content: str = ""


@dataclass
class WikiPage:
    slug: str
    title: str = ""
    page_type: str = ""
    content: str = ""
    summary: str = ""
    aliases: List[str] = field(default_factory=list)
    source_refs: List[str] = field(default_factory=list)  # doc ids
    chunk_refs: List[str] = field(default_factory=list)  # chunk ids
    category: List[str] = field(default_factory=list)  # taxonomy path
    created_at: str = ""
    updated_at: str = ""
    version: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WikiPage":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class DocResult:
    """Output of the map phase for one document."""

    doc: SourceDoc
    summary_line: str
    summary_body: str
    page_slugs: List[str]
    titles: Dict[str, str]  # slug -> title, for cross-linking


@dataclass
class Op:
    kind: str  # "ingest" | "retract"
    doc_id: str
    doc: Optional[SourceDoc] = None
    # retract only: snapshot taken when the document was removed
    doc_title: str = ""
    doc_summary: str = ""
    page_slugs: List[str] = field(default_factory=list)
