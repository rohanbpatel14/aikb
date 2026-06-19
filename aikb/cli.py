from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import List, Optional

from . import __author__, __author_url__, __version__
from . import console as c
from .db import Index
from .indexer import build_index, scan
from .sources import Walker, detect_label, expand_roots


# ── doctor ──────────────────────────────────────────────────────────────────
def cmd_doctor(args) -> int:
    print(c.header("aikb doctor"))
    print(c.kv("aikb version", __version__))
    print(c.kv("author", f"{__author__}  {c.dim(__author_url__)}"))
    print(c.kv("python", sys.version.split()[0]))
    ok = True
    try:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        con.close()
        print(c.kv("sqlite fts5", c.green("available")))
    except Exception as e:
        ok = False
        print(c.kv("sqlite fts5", c.red("MISSING — " + str(e))))
    for r in ("~/.claude", "~/.codex", "~/.cursor", "~/.antigravity"):
        p = os.path.expanduser(r)
        mark = c.green("found") if os.path.isdir(p) else c.dim("not present")
        print(c.kv(r, mark))
    print()
    print(c.green("OK — ready to index.") if ok
          else c.red("Problem: SQLite FTS5 is required."))
    return 0 if ok else 1


# ── scan ──────────────────────────────────────────────────────────────────
def _walker(args, index_dir: Optional[str] = None) -> Walker:
    return Walker(
        use_default_ignores=not args.no_default_ignores,
        extra_ignores=args.ignore,
        includes=args.include,
        index_dir=index_dir,
    )


def cmd_scan(args) -> int:
    roots = expand_roots(args.paths)
    print(c.header("aikb scan"))
    for r in roots:
        print(c.kv("source", f"{r}  {c.dim('(' + detect_label(r) + ')')}"))
    res = scan(roots, _walker(args))
    print(c.rule())
    print(c.kv("files seen", c.count(res.files_seen)))
    print(c.kv("files skipped", c.count(res.files_skipped) + c.dim("  noise filter")))
    print(c.kv("indexable", c.bold(c.count(res.matched))))
    if res.by_adapter:
        print()
        print(c.bold("by adapter:"))
        for name, n in res.by_adapter.most_common():
            print(c.kv("  " + name, c.count(n)))
    print()
    print(c.dim(f"Next: aikb index {' '.join(args.paths)} --out ./aikb-index"))
    return 0


# ── index ─────────────────────────────────────────────────────────────────
def cmd_index(args) -> int:
    roots = expand_roots(args.paths)
    print(c.header("aikb index"))
    for r in roots:
        print(c.kv("source", r))
    print(c.kv("index dir", os.path.abspath(args.out)))
    print(c.rule())

    def progress(i: int, path: str, adapter: str) -> None:
        if i % 25 == 0:
            sys.stdout.write("\r" + c.dim(f"  indexing… {i:,} files ({adapter})") + " " * 12)
            sys.stdout.flush()

    res = build_index(args.out, roots, _walker(args, index_dir=args.out),
                      on_file=progress, force=args.reindex)
    sys.stdout.write("\r" + " " * 72 + "\r")

    print(c.kv("files seen", c.count(res.files_seen)))
    print(c.kv("files skipped", c.count(res.files_skipped)))
    if res.files_unchanged:
        print(c.kv("files unchanged", c.count(res.files_unchanged) + c.dim("  incremental skip")))
    print(c.kv("files indexed", c.count(res.files_indexed)))
    if res.files_error:
        print(c.kv("files errored", c.yellow(c.count(res.files_error))))
    print(c.kv("records", c.bold(c.count(res.records))))
    if res.by_adapter:
        print()
        print(c.bold("records by adapter:"))
        for name, n in res.by_adapter.most_common():
            print(c.kv("  " + name, c.count(n)))
    print()
    print(c.green("✓ index ready  ") + c.dim(os.path.abspath(args.out)))
    print(c.dim(f'Next: aikb search {args.out} "your terms"'))
    return 0


# ── search ──────────────────────────────────────────────────────────────────
def cmd_search(args) -> int:
    import sqlite3
    from .db import fts_and_query, fts_or_query
    words = args.query.split()
    query = fts_or_query(words) if args.any else fts_and_query(words)
    if not query:
        print(c.dim("empty query."))
        return 0
    with Index(args.index).open() as idx:
        try:
            rows = idx.search(query, limit=args.limit)
        except sqlite3.OperationalError:
            print(c.red("could not parse that query. Try simpler terms or --any."))
            return 1
    if not rows:
        print(c.dim("no matches."))
        return 0
    print(c.header(f"search: {args.query}") + c.dim(f"  ({len(rows)} hits)"))
    print()
    for r in rows:
        date = (r["created_at"] or "")[:10]
        print(c.bold(r["title"] or r["record_id"]))
        meta = "  ".join(x for x in [c.dim(date), c.cyan(r["kind"]),
                                     c.dim(r["source"])] if x.strip())
        print("  " + meta)
        snip = (r["snippet"] or "").replace("\n", " ").strip()
        if snip:
            print("  " + snip)
        print("  " + c.dim(r["record_id"]))
        print("  " + c.dim(r["source_path"]))
        print()
    return 0


# ── argparse wiring ─────────────────────────────────────────────────────────
def _add_walk_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--ignore", action="append", default=[],
                    metavar="FRAG", help="extra path fragment to skip (repeatable)")
    sp.add_argument("--include", action="append", default=[],
                    metavar="GLOB", help="force-include a path glob/fragment (repeatable)")
    sp.add_argument("--no-default-ignores", action="store_true",
                    help="disable the built-in noise filter")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aikb",
        description="Local-first knowledge archaeology for AI chat histories.",
    )
    p.add_argument("--version", action="version",
                   version=f"aikb {__version__} — by {__author__} ({__author_url__})")
    p.add_argument("--no-color", action="store_true", help="disable colored output")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("doctor", help="check environment + detect known sources")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("scan", help="dry run: what would be indexed")
    sp.add_argument("paths", nargs="+")
    _add_walk_args(sp)
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("index", help="build a searchable index")
    sp.add_argument("paths", nargs="+")
    sp.add_argument("--out", required=True, metavar="DIR", help="index directory")
    sp.add_argument("--reindex", action="store_true",
                    help="re-parse all files instead of skipping unchanged ones")
    _add_walk_args(sp)
    sp.set_defaults(func=cmd_index)

    sp = sub.add_parser("search", help="full-text search the index")
    sp.add_argument("index", help="index directory")
    sp.add_argument("query")
    sp.add_argument("--any", action="store_true", help="match ANY word (OR), not the exact phrase")
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_search)

    # topic + timeline are registered by their own modules to keep this file lean
    try:
        from .topics import register as register_topics
        register_topics(sub)
    except Exception:
        pass
    try:
        from .timeline import register as register_timeline
        register_timeline(sub)
    except Exception:
        pass

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "no_color", False):
        c.disable()
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(c.red(str(e)))
        return 2
    except KeyboardInterrupt:
        print(c.dim("\ninterrupted."))
        return 130
