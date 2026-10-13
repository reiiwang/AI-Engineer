"""Incremental build driver, following WeKnora's document lifecycle:

  removed doc  -> drop its source ref from every page (deleting pages left
                  with no sources), then queue a retract op so the LLM strips
                  its exclusive facts from pages that survive
  new doc      -> ingest op
  changed doc  -> ingest op; map emits retract + re-add for pages it still
                  feeds and retractStale for pages it no longer mentions

Ops are processed in batches of `docs_per_batch` (WeKnora: 5); each batch
runs map -> identity remap -> taxonomy -> reduce and is saved to state.
Finalize (index intro, dead links, cross-links) runs once at the end."""
from __future__ import annotations

import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .chunker import file_hash, load_document, scan_documents
from .config import Config
from .dedup import normalize_title
from .extract import MapContext, map_document, summary_slug_for
from .finalize import Change, finalize
from .links import remap_links
from .llm import LLM
from .models import (PAGE_CONCEPT, PAGE_ENTITY, PAGE_SUMMARY, UPDATE_RETRACT,
                     DocRecord, DocResult, Op, SlugUpdate, WikiPage)
from .reduce import ReduceContext, plan_taxonomy, reduce_slug
from .state import WikiState, now_iso
from .wiki_format import render_all

log = logging.getLogger(__name__)


@dataclass
class BuildPlan:
    added: List[str] = field(default_factory=list)
    changed: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    unchanged: List[str] = field(default_factory=list)

    def empty(self) -> bool:
        return not (self.added or self.changed or self.removed)


def make_plan(cfg: Config, state: WikiState) -> Tuple[BuildPlan, Dict[str, Path]]:
    found = scan_documents(cfg.raw_dir, cfg.include)
    plan = BuildPlan()
    for doc_id, path in found.items():
        rec = state.docs.get(doc_id)
        if rec is None:
            plan.added.append(doc_id)
        elif rec.hash != file_hash(path):
            plan.changed.append(doc_id)
        else:
            plan.unchanged.append(doc_id)
    plan.removed = sorted(set(state.docs) - set(found))
    return plan, found


def remove_document(state: WikiState, doc_id: str) -> Tuple[Op, Change]:
    """cleanupWikiOnKnowledgeDelete."""
    rec = state.docs.pop(doc_id)
    pages = state.pages_by_source(doc_id)
    summary = next((p.summary for p in pages if p.page_type == PAGE_SUMMARY and p.summary), "")
    slugs = [p.slug for p in pages]
    for page in pages:
        page.source_refs = [r for r in page.source_refs if r != doc_id]
        page.chunk_refs = [c for c in page.chunk_refs if c.split("#", 1)[0] != doc_id]
        if not page.source_refs:
            state.delete_page(page.slug)
    op = Op(kind="retract", doc_id=doc_id, doc_title=rec.title, doc_summary=summary, page_slugs=slugs)
    return op, ("removed", rec.title, summary)


def _remap_by_identity(state: WikiState, slug_updates: Dict[str, List[SlugUpdate]],
                       results: List[DocResult]) -> None:
    """remapSlugUpdatesByIdentity: documents mapped in parallel may romanize the
    same name into different slugs; collapse them onto one slug, preferring
    one that already exists as a page."""
    by_identity: Dict[str, List[str]] = {}
    for slug, ups in slug_updates.items():
        add = next((u for u in ups if u.type in (PAGE_ENTITY, PAGE_CONCEPT)), None)
        if add and add.item.name:
            by_identity.setdefault(normalize_title(add.item.name), []).append(slug)
    mapping: Dict[str, str] = {}
    for slugs in by_identity.values():
        if len(slugs) < 2:
            continue
        existing = sorted(s for s in slugs if s in state.pages)
        canonical = existing[0] if existing else sorted(slugs)[0]
        for s in slugs:
            if s != canonical:
                mapping[s] = canonical
    if not mapping:
        return
    for src, dst in mapping.items():
        log.info("identity remap %s -> %s", src, dst)
        for u in slug_updates.pop(src):
            u.slug = dst
            if u.type in (PAGE_ENTITY, PAGE_CONCEPT):
                u.item.slug = dst
            slug_updates[dst].append(u)
    for ups in slug_updates.values():
        for u in ups:
            if u.type == PAGE_SUMMARY:
                u.summary_body = remap_links(u.summary_body, mapping)
    for r in results:
        r.titles = {mapping.get(s, s): t for s, t in r.titles.items()}
        r.page_slugs = list(r.titles)


def process_batch(cfg: Config, llm: LLM, state: WikiState, ops: List[Op]) -> Tuple[List[DocResult], Set[str], List[Tuple[str, str]], List[str]]:
    """Returns (doc results, changed slugs, fresh (slug, title) refs, failed doc ids)."""
    mc = MapContext(cfg=cfg, llm=llm, state=state,
                    dedup_pool=state.content_pages([PAGE_ENTITY, PAGE_CONCEPT]))
    slug_updates: Dict[str, List[SlugUpdate]] = {}
    results: List[DocResult] = []
    failed: List[str] = []

    for op in ops:
        if op.kind == "retract":
            for slug in op.page_slugs:
                slug_updates.setdefault(slug, []).append(SlugUpdate(
                    slug=slug, type=UPDATE_RETRACT, doc_id=op.doc_id, doc_title=op.doc_title,
                    retract_doc_content=op.doc_summary))

    ingest = [op for op in ops if op.kind == "ingest"]

    def run(op: Op) -> Tuple[Op, Optional[DocResult], List[SlugUpdate], Optional[Exception]]:
        try:
            res, ups = map_document(mc, op.doc)
            return op, res, ups, None
        except Exception as err:  # noqa: BLE001 - one bad doc must not sink the batch
            return op, None, [], err

    with ThreadPoolExecutor(max(1, cfg.map_parallel)) as ex:
        for op, res, ups, err in ex.map(run, ingest):
            if err is not None:
                log.error("map failed for %s: %s", op.doc_id, err)
                failed.append(op.doc_id)
                continue
            if res is None:
                continue
            results.append(res)
            for u in ups:
                slug_updates.setdefault(u.slug, []).append(u)

    _remap_by_identity(state, slug_updates, results)

    chunk_content = {c.id: c.content for r in results for c in r.doc.chunks}
    rc = ReduceContext(cfg=cfg, llm=llm, state=state, chunk_content=chunk_content)
    rc.planned_category = plan_taxonomy(rc, slug_updates)

    changed: Set[str] = set()
    failed_additions: Set[str] = set()
    with ThreadPoolExecutor(max(1, cfg.reduce_parallel)) as ex:
        futures = {slug: ex.submit(reduce_slug, rc, slug, ups) for slug, ups in slug_updates.items()}
        for slug, fut in futures.items():
            try:
                r = fut.result()
            except Exception as err:  # noqa: BLE001
                log.error("reduce failed for %s: %s", slug, err)
                failed_additions.add(slug)
                continue
            if r.changed or r.deleted:
                changed.add(slug)
            if r.addition_failed:
                failed_additions.add(slug)

    ts = now_iso()
    for r in results:
        state.docs[r.doc.id] = DocRecord(
            id=r.doc.id, hash=r.doc.hash, title=r.doc.title, summary_slug=summary_slug_for(r.doc.id),
            summary_line=r.summary_line, summary_body=r.summary_body, ingested_at=ts)

    fresh = [(s, t) for r in results for s, t in r.titles.items()
             if s in changed and s not in failed_additions and t]
    return results, changed, fresh, failed


def render_wiki(cfg: Config, state: WikiState) -> int:
    files = render_all(state.pages, state.index_intro, cfg.format)
    wiki = cfg.wiki_dir
    wiki.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        dest = wiki / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.read_text(encoding="utf-8") != text:
            dest.write_text(text, encoding="utf-8")
    # Remove only files a previous render wrote and this one did not.
    for rel in set(state.rendered_files) - set(files):
        stale = wiki / rel
        if stale.is_file():
            stale.unlink()
            parent = stale.parent
            while parent != wiki and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
    state.rendered_files = sorted(files)
    return len(files)


def build(cfg: Config, *, rebuild: bool = False, dry_run: bool = False,
          render_only: bool = False) -> None:
    if rebuild and not dry_run:
        old = WikiState.load(cfg.state_dir)
        if cfg.state_dir.exists():
            shutil.rmtree(cfg.state_dir)
        state = WikiState(cfg.state_dir / "state.json")
        state.rendered_files = old.rendered_files  # so the re-render cleans them up
    else:
        state = WikiState.load(cfg.state_dir)

    if render_only:
        n = render_wiki(cfg, state)
        state.save()
        log.info("rendered %d files into %s", n, cfg.wiki_dir)
        return

    if not cfg.raw_dir.is_dir():
        raise SystemExit(f"raw_dir does not exist: {cfg.raw_dir}")
    plan, paths = make_plan(cfg, state)
    log.info("plan: %d added, %d changed, %d removed, %d unchanged",
             len(plan.added), len(plan.changed), len(plan.removed), len(plan.unchanged))
    for label, ids in (("+", plan.added), ("~", plan.changed), ("-", plan.removed)):
        for doc_id in ids:
            log.info("  %s %s", label, doc_id)
    if dry_run:
        return
    # Nothing changed. (A missing intro with existing docs means the last run
    # died before finalize, so fall through and finish it.)
    if plan.empty() and (state.index_intro or not state.docs):
        render_wiki(cfg, state)
        state.save()
        log.info("wiki is up to date")
        return

    llm = LLM(cfg.llm, cfg.state_dir / "llm_calls.jsonl" if cfg.log_llm_calls else None)
    ops: List[Op] = []
    changes: List[Change] = []
    affected: Set[str] = set()
    for doc_id in plan.removed:
        op, change = remove_document(state, doc_id)
        ops.append(op)
        changes.append(change)
        affected.update(s for s in op.page_slugs if s in state.pages)
    state.save()
    for doc_id in plan.added + plan.changed:
        ops.append(Op(kind="ingest", doc_id=doc_id, doc=load_document(cfg.raw_dir, paths[doc_id], cfg.chunk_size)))

    fresh: List[Tuple[str, str]] = []
    failed: List[str] = []
    size = max(1, cfg.docs_per_batch)
    for i in range(0, len(ops), size):
        batch = ops[i:i + size]
        log.info("batch %d/%d (%d ops)", i // size + 1, (len(ops) + size - 1) // size, len(batch))
        results, changed, batch_fresh, batch_failed = process_batch(cfg, llm, state, batch)
        affected |= changed
        fresh += batch_fresh
        failed += batch_failed
        changes += [("added", r.doc.title, r.summary_line) for r in results]
        state.save()

    finalize(cfg, llm, state, changes, {s for s in affected if s in state.pages}, fresh)
    n = render_wiki(cfg, state)
    state.save()
    log.info("done: %d pages, %d files written to %s, %d LLM calls",
             len(state.pages), n, cfg.wiki_dir, llm.calls)
    if failed:
        log.warning("%d document(s) failed and will be retried on the next run: %s",
                    len(failed), ", ".join(failed))
