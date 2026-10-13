"""Map phase: turn one source document into a list of SlugUpdates
(WeKnora mapOneDocument + wiki_ingest_cite.go).

  Pass 0    candidate entities/concepts (falls back to single-shot extraction)
  dedup     merge candidates into existing pages that describe the same thing
  summary   the document's summary page          } run in parallel
  Pass 1..N chunk citations per candidate slug    }
  reconcile retract the doc's contribution from pages it used to feed"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from . import prompts
from .config import Config
from .dedup import deduplicate
from .links import slugify
from .llm import LLM, LLMError, split_summary_line
from .models import (PAGE_CONCEPT, PAGE_ENTITY, PAGE_SUMMARY, UPDATE_RETRACT,
                     UPDATE_RETRACT_STALE, Chunk, DocResult, ExtractedItem,
                     SlugUpdate, SourceDoc, WikiPage)
from .state import WikiState

log = logging.getLogger(__name__)

MIN_TEXT_CHARS = 10
CITATION_BATCH_CHARS = 12000
CITATION_CONCURRENCY = 4
_IMAGE_MARKUP_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)|<img[^>]*>", re.I)


def summary_slug_for(doc_id: str) -> str:
    stem = doc_id[:-3] if doc_id.lower().endswith(".md") else doc_id
    return f"summary/{slugify(stem)}"


def _normalize_item_slug(item: ExtractedItem, kind: str) -> None:
    base = item.slug.split("/", 1)[1] if "/" in item.slug else item.slug
    base = slugify(base.replace("/", "-")) or slugify(item.name)
    item.slug = f"{kind}/{base}" if base else ""


def _parse_items(result: dict, key: str, kind: str) -> List[ExtractedItem]:
    items = []
    for raw in result.get(key) or []:
        if not isinstance(raw, dict):
            continue
        it = ExtractedItem.from_json(raw)
        _normalize_item_slug(it, kind)
        if it.slug and it.name:
            items.append(it)
    return items


@dataclass
class MapContext:
    cfg: Config
    llm: LLM
    state: WikiState
    dedup_pool: List[WikiPage]


def _extract_candidates(mc: MapContext, content: str, old_slugs: Set[str]) -> Tuple[List[ExtractedItem], List[ExtractedItem], bool]:
    prev = "\n".join(f"- {s}" for s in sorted(old_slugs) if s.startswith(("entity/", "concept/")))
    data = {
        "Content": content,
        "Language": mc.cfg.language,
        "PreviousSlugs": prev or "(none — this is a new document)",
        "Granularity": mc.cfg.granularity,
        "GranularityGuidance": prompts.GRANULARITY_GUIDANCE.get(
            mc.cfg.granularity, prompts.WIKI_GRANULARITY_GUIDANCE_STANDARD),
    }
    fallback = False
    try:
        result = mc.llm.generate_json(prompts.WIKI_CANDIDATE_SLUG_PROMPT, data, "extract_candidates",
                                      mc.cfg.extraction_instructions, "wiki_extraction")
    except LLMError as err:
        log.warning("pass 0 failed (%s); falling back to single-shot extraction", err)
        fallback = True
        result = mc.llm.generate_json(prompts.WIKI_KNOWLEDGE_EXTRACT_PROMPT, data, "extract_legacy",
                                      mc.cfg.extraction_instructions, "wiki_extraction")
    entities = _parse_items(result, "entities", PAGE_ENTITY)
    concepts = _parse_items(result, "concepts", PAGE_CONCEPT)
    entities, concepts = deduplicate(mc.llm, mc.dedup_pool, entities, concepts)
    return entities, concepts, fallback


def _citation_batches(chunks: List[Chunk]) -> List[List[Chunk]]:
    batches: List[List[Chunk]] = []
    cur: List[Chunk] = []
    size = 0
    for c in chunks:
        if not c.content.strip():
            continue
        if cur and size + len(c.content) > CITATION_BATCH_CHARS:
            batches.append(cur)
            cur, size = [], 0
        cur.append(c)
        size += len(c.content)
    if cur:
        batches.append(cur)
    return batches


def _render_candidates(entities: List[ExtractedItem], concepts: List[ExtractedItem]) -> str:
    lines = []
    for kind, items in ((PAGE_ENTITY, entities), (PAGE_CONCEPT, concepts)):
        for it in items:
            aliases = f' aliases="{", ".join(it.aliases)}"' if it.aliases else ""
            lines.append(f'- slug: {it.slug}, type: {kind}, name: "{it.name}"{aliases}, description: {it.description}')
    return "\n".join(lines) + "\n" if lines else ""


def _classify_citations(mc: MapContext, candidates_xml: str, chunks: List[Chunk]) -> Tuple[Dict[str, List[str]], List[dict]]:
    batches = _citation_batches(chunks)
    if not batches or not candidates_xml.strip():
        return {}, []
    order = {c.id: c.index for c in chunks}

    def run(batch: List[Chunk]) -> Tuple[Dict[str, Set[str]], List[dict]]:
        handles = {f"c{i:03d}": c.id for i, c in enumerate(batch)}
        chunks_xml = "".join(f'<c id="c{i:03d}" index="{c.index}">\n{c.content}\n</c>\n' for i, c in enumerate(batch))
        try:
            parsed = mc.llm.generate_json(prompts.WIKI_CHUNK_CITATION_PROMPT, {
                "CandidateSlugs": candidates_xml, "ChunksXML": chunks_xml, "Language": mc.cfg.language,
            }, "classify_citations")
        except LLMError as err:
            log.warning("citation batch failed: %s", err)
            return {}, []
        cites: Dict[str, Set[str]] = {}
        for slug, hs in (parsed.get("citations") or {}).items():
            ids = {handles[h] for h in hs or [] if h in handles}
            if slug and ids:
                cites.setdefault(slug.strip(), set()).update(ids)
        new = []
        for ns in parsed.get("new_slugs") or []:
            if isinstance(ns, dict) and ns.get("slug") and ns.get("name"):
                ns["source_chunks"] = [handles[h] for h in ns.get("source_chunks") or [] if h in handles]
                new.append(ns)
        return cites, new

    merged: Dict[str, Set[str]] = {}
    new_slugs: List[dict] = []
    with ThreadPoolExecutor(CITATION_CONCURRENCY) as ex:
        for cites, new in ex.map(run, batches):
            for slug, ids in cites.items():
                merged.setdefault(slug, set()).update(ids)
            new_slugs.extend(new)
    return {s: sorted(ids, key=lambda i: order.get(i, 0)) for s, ids in merged.items()}, new_slugs


def _merge_citations(entities: List[ExtractedItem], concepts: List[ExtractedItem],
                     citations: Dict[str, List[str]], new_slugs: List[dict]) -> int:
    """mergeCitationsIntoItems. Mutates the lists; returns # uncited items."""
    uncited = 0
    for it in entities + concepts:
        it.source_chunks = citations.get(it.slug, [])
        uncited += not it.source_chunks
    existing = {it.slug for it in entities + concepts}
    merged: Dict[str, Tuple[ExtractedItem, str]] = {}
    for ns in new_slugs:
        kind = str(ns.get("type") or "").strip().lower()
        if kind not in (PAGE_ENTITY, PAGE_CONCEPT):
            kind = PAGE_CONCEPT if str(ns["slug"]).startswith("concept/") else PAGE_ENTITY
        it = ExtractedItem.from_json(ns)
        _normalize_item_slug(it, kind)
        if not it.slug or it.slug in existing:
            continue
        if it.slug in merged:
            dst = merged[it.slug][0]
            dst.source_chunks += [c for c in it.source_chunks if c not in dst.source_chunks]
        else:
            merged[it.slug] = (it, kind)
    for it, kind in merged.values():
        (concepts if kind == PAGE_CONCEPT else entities).append(it)
    return uncited


def map_document(mc: MapContext, doc: SourceDoc) -> Tuple[Optional[DocResult], List[SlugUpdate]]:
    content = doc.content[: mc.cfg.max_content_chars]
    if len(_IMAGE_MARKUP_RE.sub("", content).strip()) < MIN_TEXT_CHARS:
        log.warning("%s: insufficient text content, skipping", doc.id)
        return None, []

    old_slugs = {p.slug for p in mc.state.pages_by_source(doc.id)}
    entities, concepts, fallback = _extract_candidates(mc, content, old_slugs)

    slug_listing = ""
    for it in entities + concepts:
        aliases = f" (Aliases: {', '.join(it.aliases)})" if it.aliases else ""
        slug_listing += f"- [[{it.slug}]] = {it.name}{aliases}\n"

    with ThreadPoolExecutor(2) as ex:
        summary_f = ex.submit(mc.llm.generate, prompts.WIKI_SUMMARY_PROMPT, {
            "Content": content, "Language": mc.cfg.language, "ExtractedSlugs": slug_listing,
        }, "summary", mc.cfg.content_instructions, "wiki_content")
        if fallback:
            citations, new_slugs = {}, []
        else:
            citations, new_slugs = _classify_citations(mc, _render_candidates(entities, concepts), doc.chunks)
        summary_raw = summary_f.result()  # a summary failure fails the document

    uncited = _merge_citations(entities, concepts, citations, new_slugs)

    sum_line, sum_body = split_summary_line(summary_raw)
    sum_body = sum_body or summary_raw
    sum_line = sum_line or doc.title
    doc_summary = sum_body.strip() or sum_line
    summary_slug = summary_slug_for(doc.id)

    updates = [SlugUpdate(slug=summary_slug, type=PAGE_SUMMARY, doc_id=doc.id, doc_title=doc.title,
                          summary_line=sum_line, summary_body=sum_body)]
    titles = {summary_slug: doc.title}
    for kind, items in ((PAGE_ENTITY, entities), (PAGE_CONCEPT, concepts)):
        for it in items:
            updates.append(SlugUpdate(slug=it.slug, type=kind, doc_id=doc.id, doc_title=doc.title,
                                      item=it, doc_summary=doc_summary))
            titles[it.slug] = it.name

    # Reconcile against the pages this document fed last time:
    #   still mentioned -> retract the prior version + add the new one
    #   no longer mentioned -> retractStale (strip its contribution)
    prior = mc.state.docs.get(doc.id)
    prior_contribution = prior.summary_body if prior else ""
    for old in sorted(old_slugs):
        if old.startswith("summary/"):
            continue
        if old in titles:
            updates.append(SlugUpdate(slug=old, type=UPDATE_RETRACT, doc_id=doc.id, doc_title=doc.title,
                                      retract_doc_content=prior_contribution))
        else:
            updates.append(SlugUpdate(slug=old, type=UPDATE_RETRACT_STALE, doc_id=doc.id, doc_title=doc.title,
                                      retract_doc_content=content))

    log.info("mapped %s: candidates=%d chunks=%d uncited=%d new=%d updates=%d fallback=%s",
             doc.id, len(entities) + len(concepts), len(doc.chunks), uncited, len(new_slugs), len(updates), fallback)
    return DocResult(doc=doc, summary_line=sum_line, summary_body=sum_body,
                     page_slugs=list(titles), titles=titles), updates
