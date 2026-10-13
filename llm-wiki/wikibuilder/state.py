"""Persistent build state (stands in for WeKnora's Postgres tables).

state.json holds the canonical wiki model: every page plus what we know
about every ingested document. The rendered wiki/ folder is derived from it,
so it can be re-rendered in a new format without any LLM calls."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .models import PAGE_INDEX, DocRecord, WikiPage

STATE_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class WikiState:
    def __init__(self, path: Path):
        self.path = path
        self.docs: Dict[str, DocRecord] = {}
        self.pages: Dict[str, WikiPage] = {}
        self.index_intro: str = ""
        # Files written by the last render, so stale ones can be removed
        # without touching anything else in the wiki directory.
        self.rendered_files: List[str] = []
        self.lock = threading.RLock()

    @classmethod
    def load(cls, state_dir: Path) -> "WikiState":
        st = cls(state_dir / "state.json")
        if st.path.exists():
            data = json.loads(st.path.read_text(encoding="utf-8"))
            st.docs = {k: DocRecord(**v) for k, v in data.get("docs", {}).items()}
            st.pages = {k: WikiPage.from_dict(v) for k, v in data.get("pages", {}).items()}
            st.index_intro = data.get("index_intro", "")
            st.rendered_files = data.get("rendered_files", [])
        return st

    def save(self) -> None:
        with self.lock:
            data = {
                "version": STATE_VERSION,
                "docs": {k: asdict(v) for k, v in sorted(self.docs.items())},
                "pages": {k: v.to_dict() for k, v in sorted(self.pages.items())},
                "index_intro": self.index_intro,
                "rendered_files": self.rendered_files,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)

    # --- queries -------------------------------------------------------

    def get_page(self, slug: str) -> Optional[WikiPage]:
        with self.lock:
            return self.pages.get(slug)

    def put_page(self, page: WikiPage) -> None:
        with self.lock:
            ts = now_iso()
            if not page.created_at:
                page.created_at = ts
            page.updated_at = ts
            page.version += 1
            self.pages[page.slug] = page

    def delete_page(self, slug: str) -> None:
        with self.lock:
            self.pages.pop(slug, None)

    def pages_by_source(self, doc_id: str) -> List[WikiPage]:
        with self.lock:
            return [p for p in self.pages.values() if doc_id in p.source_refs and p.page_type != PAGE_INDEX]

    def content_pages(self, types: Optional[List[str]] = None) -> List[WikiPage]:
        with self.lock:
            return [p for p in self.pages.values() if types is None or p.page_type in types]

    def category_paths(self) -> List[List[str]]:
        with self.lock:
            seen = {tuple(p.category) for p in self.pages.values() if p.category}
        return [list(t) for t in sorted(seen)]
