"""Finalize: KB-global convergence that runs once after all batches
(WeKnora ProcessWikiFinalize): index introduction, dead-link cleanup and
cross-link injection."""
from __future__ import annotations

import logging
from typing import List, Set, Tuple

from . import prompts
from .config import Config
from .links import linkify, out_links, strip_dead_links
from .llm import LLM, LLMError
from .models import PAGE_SUMMARY
from .state import WikiState

log = logging.getLogger(__name__)

INDEX_INTRO_SUMMARY_CAP = 200

# (action, doc title, one-line doc summary); action is "added" or "removed"
Change = Tuple[str, str, str]


def _clip_intro(text: str) -> str:
    text = text.strip()
    idx = text.find("\n## ")
    return text[:idx].strip() if idx >= 0 else text


def rebuild_index_intro(cfg: Config, llm: LLM, state: WikiState, changes: List[Change]) -> None:
    existing = _clip_intro(state.index_intro)
    if not existing:
        summaries = sorted(state.content_pages([PAGE_SUMMARY]), key=lambda p: p.updated_at, reverse=True)
        shown = summaries[:INDEX_INTRO_SUMMARY_CAP]
        framing = (f"(showing {len(shown)} most recent of {len(summaries)} total documents)\n\n"
                   if len(summaries) > len(shown) else "")
        docs = "".join(f"<document>\n<title>{p.title}</title>\n<summary>{p.summary}</summary>\n</document>\n\n"
                       for p in shown) or "(no documents yet)"
        try:
            intro = llm.generate(prompts.WIKI_INDEX_INTRO_PROMPT, {
                "DocumentSummaries": framing + docs, "Language": cfg.language,
            }, "index_intro", cfg.content_instructions, "wiki_content")
        except LLMError as err:
            # Leave the intro unset so the next run retries the first-time
            # generation (render falls back to a default heading meanwhile).
            log.warning("index intro generation failed: %s", err)
            intro = ""
    elif changes:
        desc = "".join(
            f"<document_{action}>\n<title>{title}</title>\n<summary>{summary}</summary>\n</document_{action}>\n\n"
            for action, title, summary in changes)
        try:
            intro = llm.generate(prompts.WIKI_INDEX_INTRO_UPDATE_PROMPT, {
                "ExistingIntro": existing, "ChangeDescription": desc, "DocumentSummaries": "",
                "Language": cfg.language,
            }, "index_intro_update", cfg.content_instructions, "wiki_content")
        except LLMError as err:
            log.warning("index intro update failed: %s", err)
            intro = existing
    else:
        intro = existing
    state.index_intro = _clip_intro(intro)


def clean_dead_links(state: WikiState) -> int:
    """Strip [[slug|text]] links whose target page does not exist. Runs over
    every page (WeKnora limits it to affected pages; a full pass is cheap
    here and keeps the whole wiki free of broken links)."""
    live = set(state.pages)
    fixed = 0
    for page in list(state.pages.values()):
        new, changed = strip_dead_links(page.content, live, page.slug)
        if changed:
            page.content = new
            fixed += 1
    return fixed


def inject_cross_links(state: WikiState, affected: Set[str], fresh_refs: List[Tuple[str, str]]) -> int:
    updated = 0
    for slug in sorted(affected):
        page = state.get_page(slug)
        if not page:
            continue
        refs = []
        for out in out_links(page.content):
            target = state.get_page(out)
            if target and target.title and out != slug:
                refs.append((out, target.title))
        refs += [(s, t) for s, t in fresh_refs if s != slug and s in state.pages]
        new, changed = linkify(page.content, refs, slug)
        if changed:
            page.content = new
            updated += 1
    return updated


def finalize(cfg: Config, llm: LLM, state: WikiState, changes: List[Change],
             affected: Set[str], fresh_refs: List[Tuple[str, str]]) -> None:
    if not state.content_pages([PAGE_SUMMARY]):
        state.index_intro = ""  # nothing to introduce (all docs failed or removed)
    elif changes or not state.index_intro:
        rebuild_index_intro(cfg, llm, state, changes)
    dead = clean_dead_links(state)
    linked = inject_cross_links(state, affected, fresh_refs)
    log.info("finalize: dead-link fixes=%d, cross-linked pages=%d", dead, linked)
