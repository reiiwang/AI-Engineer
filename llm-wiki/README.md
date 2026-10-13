# LLM Wiki Builder

A Python port of WeKnora's wiki build pipeline (`WeKnora/internal/application/service/wiki_ingest*.go`).
It takes the markdown files in `raw/` and builds a wiki made of entity, concept, and summary pages in `wiki/`.

## Usage

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=...          # or set llm.api_key_env in config.yaml

# Put source markdown into raw/ (subfolders are fine)
python build_wiki.py --dry-run     # show which docs would be added/changed/removed
python build_wiki.py               # incremental build
python build_wiki.py --rebuild     # discard state and rebuild everything
python build_wiki.py --render-only # re-render wiki/ from state only, no LLM calls
```

LLM settings (`base_url` / `model`) live in `config.yaml`. Any OpenAI-compatible endpoint works (OpenAI, vLLM, Ollama, Azure…).

## Directory layout

```
llm-wiki/
├── build_wiki.py          # entry point
├── config.yaml
├── raw/                   # ← your source documents
├── wiki/                  # ← generated wiki (do not edit by hand; it gets overwritten)
├── .wiki_state/
│   ├── state.json         # canonical wiki model (pages + document records)
│   └── llm_calls.jsonl    # every LLM request/response, for debugging
└── wikibuilder/
    ├── prompts.py         # WeKnora prompts (extracted verbatim from the Go source)
    ├── chunker.py         # markdown → chunks (unit of citation)
    ├── extract.py         # map: candidate extraction / summary / chunk citations
    ├── dedup.py           # merge duplicates against existing pages
    ├── reduce.py          # reduce: merge updates into pages + taxonomy
    ├── finalize.py        # index intro / dead links / cross-links
    ├── pipeline.py        # incremental flow and batching
    └── wiki_format.py     # ★ output format (the golden format adapter)
```

## Pipeline (follows WeKnora)

```
Scan raw/ → compare against .wiki_state hashes → added / changed / removed

removed doc   remove its source ref from pages (pages with no sources left are deleted) → queue a retract
added/changed every 5 docs form a batch:
  map     Pass 0 candidate entities/concepts → dedup → summary page ∥ chunk citations
          a changed doc emits retract (old version) + re-add for pages it still feeds;
          pages it no longer mentions get retractStale
  remap   collapse the same name romanized into different slugs within one batch
  taxonomy  one LLM call assigns categories (at most 2 levels) to new pages
  reduce  per slug: original cited chunks + existing page → LLM rewrites the page
finalize (once per run): index intro, dead-link cleanup, automatic cross-links
render  state.json → wiki/ (via wiki_format.py)
```

A doc that fails is not recorded in state, so the next run retries it automatically.

### Deviations from WeKnora

| Item | WeKnora | Here |
|---|---|---|
| Storage | Postgres + Redis | `.wiki_state/state.json` |
| Chunking | docreader service | heading-aware markdown chunks (`chunk_size`) |
| Dedup pre-filter | pg_trgm | character-bigram Jaccard in memory |
| Taxonomy folder selection | embedding similarity when there are many folders | feed every folder directly (capped at 150) |
| Dead-link cleanup | affected pages only | whole wiki (cheap, keeps D3 structure checks clean) |
| Retract leaving a page with no sources | page kept as "(empty page)" | page deleted |

## Output format (default)

Each page is `wiki/<slug>.md`, for example `wiki/entity/acme-corp.md`:

```markdown
---
title: Acme Corp
slug: entity/acme-corp
type: entity                # entity | concept | summary
summary: One sentence describing the page (used by the index)
aliases: [Acme]
category: [Organizations]   # taxonomy path
sources: [acme.md, guides/vector-db.md]          # provenance: source docs (relative to raw/)
source_chunks: [acme.md#c0000, guides/vector-db.md#c0003]  # provenance: exact chunks
links: [concept/vector-database]                 # outbound links
created: '2026-10-13T13:32:48+00:00'
updated: '2026-10-13T13:32:48+00:00'
version: 2
---

# Acme Corp

... [[concept/vector-database|Vector Database]] ...
```

`sources` / `source_chunks` provide the provenance that D1/D2 in `evaluation-design.md` need. Chunk IDs follow the form `<doc_id>#c<index>`, and you can get the chunk text back with `chunk_markdown()`.

## What to change when the golden wiki format changes

**Everything to do with output format is in `wikibuilder/wiki_format.py`.** The pipeline and prompts don't need to change. After editing, run:

```bash
python build_wiki.py --render-only   # re-render from state; no LLM calls, finishes in seconds
```

| Golden format difference | What to change |
|---|---|
| Frontmatter key names, which fields exist, field order | `frontmatter()`: just edit the returned dict (e.g. rename `sources` to `references`, drop `version`) |
| Directory layout / file names | `page_path()`: e.g. `f"{page.page_type}s/{name}.md"`, or put files in taxonomy folders `"/".join(page.category)` |
| Link syntax | First try `format.link_style` in `config.yaml` (`wikilink` / `markdown`); for any other syntax, edit `render_link()` |
| Body structure (H1, a Sources section, etc.) | `format.ensure_h1` / `format.sources_section`, or edit `render_body()` |
| Index page | `render_index()` / `index_frontmatter()` |
| A field the pipeline doesn't produce yet (e.g. `tags`) | Derive it from existing data in `frontmatter()`; if you really need new content from the LLM, add the field to `WikiPage` in `models.py` and populate it in `reduce.py`, then run `--rebuild` |
| Page types other than entity/concept/summary | That's a pipeline change (prompts + extract/reduce), not a format change |

Rule of thumb: **if it can be derived from the data already in state.json, only `wiki_format.py` changes** (re-render with `--render-only`). Only content that needs new LLM output requires changing the pipeline and running `--rebuild`.
