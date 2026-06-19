"""Interactive review loop — the trust layer.

Only medium / buried candidates are surfaced (high-confidence is auto-kept,
false positives auto-dropped). The user's include/exclude decisions are
written back into the topic pack so the next run respects them. This is what
turns AIKB from "search" into a curated, improving archive.
"""
from __future__ import annotations

import sys

from . import console as c
from .db import Index
from .topics import BUCKET_LABEL, match_topic

MENU = "[i]nclude  [e]xclude  [s]kip  [o]pen  [a]dd-term  [x] exclude-term  [q]uit"


def run_review(index: str, name: str, limit: int = 0) -> int:
    if not sys.stdin.isatty():
        print(c.red("`topic review` needs an interactive terminal."))
        return 2
    with Index(index).open() as idx:
        pack = idx.get_topic(name)
        if not pack:
            print(c.red(f"No topic '{name}'. Create it first."))
            return 2
        cands = match_topic(idx, pack)
        inc = set(pack.get("include_ids", []))
        exc = set(pack.get("exclude_ids", []))
        pending = [
            x for x in cands
            if x.bucket in ("medium", "buried")
            and x.record_id not in inc and x.record_id not in exc
        ]
        if not pending:
            print(c.dim("Nothing to review — no pending medium/buried candidates."))
            return 0
        if limit and limit > 0:
            pending = pending[:limit]

        print(c.header(f"review: {name}") + c.dim(f"  {len(pending)} uncertain candidates"))
        print(c.dim(MENU))
        print()

        i = 0
        while i < len(pending):
            cand = pending[i]
            print(
                c.confidence(cand.bucket, f"[{BUCKET_LABEL[cand.bucket]}]")
                + f"  {c.dim((cand.created_at or '')[:10])}  "
                + c.bold(cand.title or cand.record_id)
            )
            print(c.kv("matched", ", ".join(cand.matched) or c.dim("(fuzzy/co-occurrence)")))
            print(c.kv("source", c.dim(f"{cand.source} · {cand.record_id}")))
            print("  " + cand.snippet)
            try:
                ans = input(c.cyan(f"  ({i + 1}/{len(pending)}) > ")).strip().lower()
            except EOFError:
                break

            if ans in ("i", "include"):
                inc.add(cand.record_id); i += 1
            elif ans in ("e", "exclude"):
                exc.add(cand.record_id); i += 1
            elif ans in ("s", "skip", ""):
                i += 1
            elif ans in ("o", "open"):
                print()
                print(c.dim(cand.source_path))
                print(cand.text[:1500])
                print()
                continue  # stay on the same candidate
            elif ans == "a":
                term = input("  add positive term: ").strip()
                if term:
                    pack.setdefault("accepted_suggestions", []).append(term)
                    print(c.green(f"  + term '{term}' (re-run create/status to re-match)"))
                i += 1
            elif ans == "x":
                term = input("  add exclude term: ").strip()
                if term:
                    pack.setdefault("exclude_terms", []).append(term)
                    print(c.green(f"  - excluded '{term}'"))
                i += 1
            elif ans in ("q", "quit"):
                break
            else:
                print(c.dim("  " + MENU))
            print()

        pack["include_ids"] = sorted(inc)
        pack["exclude_ids"] = sorted(exc)
        idx.save_topic(name, pack)

    print(c.green(f"saved — {len(inc)} pinned in, {len(exc)} pinned out."))
    print(c.dim(f"Next: aikb topic export {index} {name} --out ./{name}-pack"))
    return 0
