"""Reduce phase: apply every SlugUpdate for one slug to its page
(WeKnora reduceSlugUpdates), plus the batch taxonomy plan
(wiki_ingest_taxonomy.go)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from . import prompts
from .config import Config
from .links import SlugHandles, out_links, strip_chunk_citations
from .llm import LLM, LLMError, split_summary_line
from .models import (PAGE_CONCEPT, PAGE_ENTITY, PAGE_SUMMARY, UPDATE_RETRACT,
                     UPDATE_RETRACT_STALE, SlugUpdate, WikiPage)
from .state import WikiState

log = logging.getLogger(__name__)

TAXONOMY_CHUNK = 60
TAXONOMY_MAX_FOLDERS = 150
CATEGORY_MAX_DEPTH = 2
_TYPE_LABELS = {"entity", "entities", "concept", "concepts", "summary", "summaries", "index"}


@dataclass
class ReduceContext:
    cfg: Config
    llm: LLM
    state: WikiState
    chunk_content: Dict[str, str]  # chunk id -> text, for this batch's docs
    planned_category: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class ReduceResult:
    changed: bool = False
    deleted: bool = False
    addition_failed: bool = False


def _doc_block(title: str, tag: str, body: str) -> str:
    return f"<document>\n<title>{title}</title>\n<{tag}>\n{body}\n</{tag}>\n</document>\n"


def reduce_slug(rc: ReduceContext, slug: str, updates: List[SlugUpdate]) -> ReduceResult:
    st = rc.state
    page = st.get_page(slug)
    exists = page is not None
    summary_upd = next((u for u in updates if u.type == PAGE_SUMMARY), None)
    retracts = [u for u in updates if u.type in (UPDATE_RETRACT, UPDATE_RETRACT_STALE)]
    additions = [u for u in updates if u.type in (PAGE_ENTITY, PAGE_CONCEPT)]

    if not exists:
        if not (summary_upd or additions):
            return ReduceResult()
        page = WikiPage(slug=slug)
    else:
        page = WikiPage.from_dict(page.to_dict())  # work on a copy

    if summary_upd:
        page.title = f"{summary_upd.doc_title} - Summary"
        page.content = summary_upd.summary_body
        page.summary = summary_upd.summary_line
        page.page_type = PAGE_SUMMARY
        page.source_refs = [summary_upd.doc_id]
        page.chunk_refs = []
        st.put_page(page)
        return ReduceResult(changed=True)

    deleted_content = remaining_content = ""
    if retracts:
        deleted_content = "\n".join(_doc_block(r.doc_title, "content", r.retract_doc_content) for r in retracts)
        retract_ids = {r.doc_id for r in retracts}
        for ref in page.source_refs:
            if ref in retract_ids:
                continue
            rec = st.docs.get(ref)
            body = rec.summary_body if rec and rec.summary_body else "(summary not available)"
            remaining_content += _doc_block(rec.title if rec else ref, "content", body) + "\n"
        remaining_content = remaining_content or "(no remaining sources)"
        page.source_refs = [r for r in page.source_refs if r not in retract_ids]
        page.chunk_refs = [c for c in page.chunk_refs if c.split("#", 1)[0] not in retract_ids]

    new_content = ""
    shared_ctx: Dict[str, str] = {}
    for add in additions:
        cited = "\n\n".join(rc.chunk_content[c] for c in add.item.source_chunks
                            if rc.chunk_content.get(c, "").strip())
        if add.doc_summary.strip():
            shared_ctx[add.doc_id] = f"<document>\n<title>{add.doc_title}</title>\n<context>\n{add.doc_summary.strip()}\n</context>\n</document>\n"
        body = cited or add.item.details
        new_content += _doc_block(add.doc_title, "content", f"**{add.item.name}**: {add.item.description}\n\n{body}") + "\n"
        for a in add.item.aliases:
            if a not in page.aliases:
                page.aliases.append(a)
        if add.doc_id not in page.source_refs:
            page.source_refs.append(add.doc_id)
        page.title = page.title or add.item.name
        page.page_type = page.page_type or add.type

    if not (additions or retracts):
        return ReduceResult()

    # Everything this page sourced was retracted: drop it (mirrors WeKnora's
    # delete path, which removes pages left with no source refs).
    if not additions and not page.source_refs:
        st.delete_page(slug)
        return ReduceResult(deleted=True)

    handles = SlugHandles()
    links = [s for s in out_links(page.content) if s != slug]
    known = set(links)
    available = ""
    for s in links:
        h = handles.handle(s)
        target = st.get_page(s)
        if target and target.title:
            available += f"- {h} ({target.title})\n"
    existing = handles.encode(strip_chunk_citations(page.content), known)
    if not exists or not existing.strip():
        existing = "(New page)"

    data = {
        "HasAdditions": "1" if additions else "",
        "HasRetractions": "1" if retracts else "",
        "PageSlug": slug,
        "PageTitle": page.title or slug,
        "PageType": page.page_type or "wiki page",
        "PageAliases": ", ".join(page.aliases),
        "ExistingContent": existing,
        "SharedSourceContexts": "".join(shared_ctx[k] for k in sorted(shared_ctx)),
        "NewContent": new_content,
        "DeletedContent": deleted_content,
        "RemainingSourcesContent": remaining_content,
        "AvailableSlugs": available,
        "Language": rc.cfg.language,
    }
    try:
        out = rc.llm.generate(prompts.WIKI_PAGE_MODIFY_USER_PROMPT, data, f"page_modify:{slug}",
                              rc.cfg.content_instructions, "wiki_content")
    except LLMError as err:
        log.warning("page update failed for %s: %s", slug, err)
        return ReduceResult(addition_failed=bool(additions))
    if not out.strip():
        return ReduceResult(addition_failed=bool(additions))

    out = handles.decode(out)
    summary, body = split_summary_line(out)
    page.content = body or out
    if summary:
        page.summary = summary
    for add in additions:
        page.chunk_refs += [c for c in add.item.source_chunks if c not in page.chunk_refs]
    if not page.category and slug in rc.planned_category:
        page.category = rc.planned_category[slug]
    st.put_page(page)
    return ReduceResult(changed=True)


# --- taxonomy -------------------------------------------------------------

def clean_category(path: List[str]) -> List[str]:
    """CleanWikiCategoryPath: split on '/', drop blanks and type labels, dedupe, cap depth."""
    out: List[str] = []
    for part in path or []:
        for label in str(part).split("/"):
            label = label.strip()
            if label and label.lower() not in _TYPE_LABELS and label not in out:
                out.append(label)
                if len(out) >= CATEGORY_MAX_DEPTH:
                    return out
    return out


def _format_tree(paths: List[List[str]]) -> str:
    tree: Dict = {}
    for p in paths:
        node = tree
        for label in p:
            node = node.setdefault(label, {})
    lines: List[str] = []

    def walk(node: Dict, depth: int) -> None:
        for k in sorted(node):
            lines.append("  " * depth + k)
            walk(node[k], depth + 1)
    walk(tree, 0)
    return "\n".join(lines)


def plan_taxonomy(rc: ReduceContext, slug_updates: Dict[str, List[SlugUpdate]]) -> Dict[str, List[str]]:
    items: List[Tuple[str, str, str, str]] = []
    for slug in sorted(slug_updates):
        page = rc.state.get_page(slug)
        if page and page.category:
            continue  # already filed; planning only applies to unfiled pages
        u = next((u for u in slug_updates[slug] if u.type in (PAGE_ENTITY, PAGE_CONCEPT)), None)
        if u:
            items.append((slug, u.item.name or slug, u.type, u.item.description[:120]))
    if not items:
        return {}

    existing = rc.state.category_paths()[:TAXONOMY_MAX_FOLDERS]
    result: Dict[str, List[str]] = {}
    for start in range(0, len(items), TAXONOMY_CHUNK):
        chunk = items[start:start + TAXONOMY_CHUNK]
        tree = _format_tree(existing) or "(none yet — this knowledge base has no folders, design a fresh directory)"
        block = "".join(f"- slug: {s} | title: {t} | type: {k} | about: {a}\n" for s, t, k, a in chunk)
        try:
            parsed = rc.llm.generate_json(prompts.WIKI_TAXONOMY_PLAN_PROMPT, {
                "ExistingTaxonomy": tree, "Items": block, "Language": rc.cfg.language,
            }, "taxonomy")
        except LLMError as err:
            log.warning("taxonomy plan failed (%d items): %s", len(chunk), err)
            continue
        for a in parsed.get("assignments") or []:
            if not isinstance(a, dict) or not a.get("slug"):
                continue
            path = clean_category(a.get("path") or [])
            result[str(a["slug"]).strip()] = path
            if path and path not in existing:
                existing.append(path)  # feed forward so later chunks converge
    return result
