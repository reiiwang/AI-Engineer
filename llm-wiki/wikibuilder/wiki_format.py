"""Output format: how the canonical wiki model is written to disk.

THIS IS THE FILE TO EDIT WHEN THE GOLDEN WIKI FORMAT CHANGES. The pipeline
never writes files itself; it only hands WikiPage objects (models.py) to the
functions below. After editing, re-render without any LLM calls:

    python build_wiki.py --render-only

Extension points, in the order you are most likely to need them:

  page_path()     where each page lives (directory layout, file names)
  frontmatter()   which frontmatter keys exist, their names and values
  render_link()   link syntax: [[slug|text]] wikilinks or relative markdown links
  render_body()   page body (heading, extra sections such as a Sources list)
  render_index()  the index / table-of-contents page

Options from the `format:` section of config.yaml arrive as ctx.options.
"""
from __future__ import annotations

import os
import posixpath
from dataclasses import dataclass
from typing import Any, Dict, List

import yaml

from .links import WIKI_LINK_RE, normalize_slug, out_links
from .models import PAGE_CONCEPT, PAGE_ENTITY, PAGE_SUMMARY, WikiPage

DEFAULT_OPTIONS: Dict[str, Any] = {
    "link_style": "wikilink",  # "wikilink" -> [[entity/x|X]], "markdown" -> [X](../entity/x.md)
    "link_text": "display",    # "display": text the LLM wrote; "title": the target page's title
    "link_base_url": "",       # markdown only: "" -> relative path, else base_url + "/" + page path
    "ensure_h1": True,          # prepend "# <title>" when the body has no H1
    "sources_section": False,   # append a "## Sources" list to every page
    "index_path": "index.md",
}


def plain(text: str) -> str:
    """Wiki links -> display text, for one-line fields (frontmatter, index)."""
    return WIKI_LINK_RE.sub(lambda m: m.group(2) or m.group(1).rsplit("/", 1)[-1], text or "")


@dataclass
class RenderContext:
    options: Dict[str, Any]
    pages: Dict[str, WikiPage]  # every page, by slug


# --- 1. layout ---------------------------------------------------------------

def page_path(page: WikiPage, ctx: RenderContext) -> str:
    """Path of the page file, relative to wiki_dir. Default: the slug itself,
    e.g. entity/acme-corp.md, concept/rag.md, summary/guides/setup.md."""
    return f"{page.slug}.md"


# --- 2. frontmatter ----------------------------------------------------------

def frontmatter(page: WikiPage, ctx: RenderContext) -> Dict[str, Any]:
    """Keys are written in this order. Rename / drop / add keys here."""
    return {
        "title": page.title,
        "slug": page.slug,
        "type": page.page_type,  # entity | concept | summary
        "summary": plain(page.summary),
        "aliases": list(page.aliases),
        "category": list(page.category),
        # Provenance: source documents (paths relative to raw_dir) and the
        # exact chunks the page was written from.
        "sources": list(page.source_refs),
        "source_chunks": list(page.chunk_refs),
        "links": [s for s in out_links(page.content) if s in ctx.pages],
        "created": page.created_at,
        "updated": page.updated_at,
        "version": page.version,
    }


def index_frontmatter(ctx: RenderContext) -> Dict[str, Any]:
    return {"title": "Index", "type": "index"}


# --- 3. links ------------------------------------------------------------------

def page_url(slug: str, from_path: str, ctx: RenderContext) -> str:
    """URL of a page as seen from the file at from_path."""
    target = page_path(ctx.pages[slug], ctx) if slug in ctx.pages else f"{slug}.md"
    base = ctx.options["link_base_url"]
    url = f"{base.rstrip('/')}/{target}" if base else \
        posixpath.relpath(target, posixpath.dirname(from_path) or ".")
    return url.replace(" ", "%20")


def render_link(slug: str, text: str, from_path: str, ctx: RenderContext) -> str:
    page = ctx.pages.get(slug)
    if page and (ctx.options["link_text"] == "title" or not text):
        text = page.title
    text = text or slug
    if ctx.options["link_style"] == "markdown":
        return f"[{text}]({page_url(slug, from_path, ctx)})"
    return f"[[{slug}|{text}]]"


def _convert_links(content: str, from_path: str, ctx: RenderContext) -> str:
    return WIKI_LINK_RE.sub(
        lambda m: render_link(normalize_slug(m.group(1)), m.group(2) or "", from_path, ctx), content)


# --- 4. body -------------------------------------------------------------------

def render_body(page: WikiPage, path: str, ctx: RenderContext) -> str:
    body = _convert_links(page.content.strip(), path, ctx)
    if ctx.options["ensure_h1"] and not body.lstrip().startswith("# "):
        body = f"# {page.title}\n\n{body}"
    if ctx.options["sources_section"] and page.source_refs:
        body += "\n\n## Sources\n\n" + "\n".join(f"- {s}" for s in page.source_refs)
    return body + "\n"


def render_page(page: WikiPage, ctx: RenderContext) -> str:
    path = page_path(page, ctx)
    fm = yaml.safe_dump(frontmatter(page, ctx), allow_unicode=True, sort_keys=False, width=1000)
    return f"---\n{fm}---\n\n{render_body(page, path, ctx)}"


# --- 5. index ------------------------------------------------------------------

def render_index(intro: str, ctx: RenderContext) -> str:
    path = ctx.options["index_path"]
    pages = sorted(ctx.pages.values(), key=lambda p: (p.title.lower(), p.slug))

    def item(p: WikiPage, title: str = "") -> str:
        link = render_link(p.slug, title or p.title, path, ctx)
        return f"- {link} — {plain(p.summary)}" if p.summary else f"- {link}"

    lines = [intro.strip() or "# Wiki Index", ""]
    docs = [p for p in pages if p.page_type == PAGE_SUMMARY]
    if docs:
        lines += ["## Documents", ""]
        lines += [item(p, p.title[: -len(" - Summary")] if p.title.endswith(" - Summary") else p.title) for p in docs]
        lines.append("")

    tree: Dict[tuple, List[WikiPage]] = {}
    for p in pages:
        if p.page_type in (PAGE_ENTITY, PAGE_CONCEPT):
            tree.setdefault(tuple(p.category) or ("Uncategorized",), []).append(p)
    if tree:
        lines += ["## Directory", ""]
        last: tuple = ()
        for cat in sorted(tree, key=lambda c: (c == ("Uncategorized",), [s.lower() for s in c])):
            for depth, label in enumerate(cat):
                if last[: depth + 1] != cat[: depth + 1]:
                    lines += [f"{'#' * (depth + 3)} {label}", ""]
            last = cat
            lines += [item(p) for p in tree[cat]]
            lines.append("")

    fm = yaml.safe_dump(index_frontmatter(ctx), allow_unicode=True, sort_keys=False)
    return f"---\n{fm}---\n\n" + "\n".join(lines).rstrip() + "\n"


# --- driver (normally no need to edit below) ---------------------------------

def render_all(pages: Dict[str, WikiPage], intro: str, options: Dict[str, Any]) -> Dict[str, str]:
    """Returns {relative path: file text} for the whole wiki."""
    ctx = RenderContext(options={**DEFAULT_OPTIONS, **(options or {})}, pages=pages)
    files = {page_path(p, ctx): render_page(p, ctx) for p in pages.values()}
    files[ctx.options["index_path"]] = render_index(intro, ctx)
    return {os.path.normpath(k).replace(os.sep, "/"): v for k, v in files.items()}
