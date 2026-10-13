#!/usr/bin/env python3
"""Build an LLM wiki from the markdown files in raw/ (WeKnora pipeline port).

    python build_wiki.py                 # incremental: only new/changed/removed docs
    python build_wiki.py --dry-run       # show what would be processed
    python build_wiki.py --rebuild       # discard state and rebuild from scratch
    python build_wiki.py --render-only   # re-render wiki/ from state (no LLM calls)
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikibuilder.config import load_config  # noqa: E402
from wikibuilder.pipeline import build  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", default=str(Path(__file__).resolve().parent / "config.yaml"))
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="list added/changed/removed docs and exit")
    mode.add_argument("--rebuild", action="store_true", help="ignore existing state and rebuild everything")
    mode.add_argument("--render-only", action="store_true", help="re-render wiki/ from state without LLM calls")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cfg = load_config(Path(args.config))
    build(cfg, rebuild=args.rebuild, dry_run=args.dry_run, render_only=args.render_only)


if __name__ == "__main__":
    main()
