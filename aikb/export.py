"""Export a topic into a portable, source-linked pack.

Every record carries its record_id and source path, so every line in the
generated Markdown traces back to the exact origin — no orphaned claims.
"""
from __future__ import annotations

import csv
import json
import os
import time
from typing import Dict, List

from . import console as c
from .db import Index
from .topics import Candidate, match_topic


def _kept(pack: Dict, cands: List[Candidate]) -> List[Candidate]:
    inc = set(pack.get("include_ids", []))
    exc = set(pack.get("exclude_ids", []))
    return [
        x for x in cands
        if (x.bucket in ("high", "medium") or x.record_id in inc)
        and x.record_id not in exc
    ]


def export_topic(index: str, name: str, out: str, fmt: str) -> int:
    with Index(index).open() as idx:
        pack = idx.get_topic(name)
        if not pack:
            print(c.red(f"No topic '{name}'."))
            return 2
        cands = match_topic(idx, pack)
    kept = _kept(pack, cands)
    os.makedirs(out, exist_ok=True)
    now = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    rows = [{
        "record_id": x.record_id, "title": x.title, "kind": x.kind,
        "source": x.source, "source_path": x.source_path,
        "created_at": x.created_at, "project": x.project,
        "bucket": x.bucket, "matched": ";".join(x.matched), "snippet": x.snippet,
    } for x in kept]

    # topic.json (the reusable definition) is always written
    with open(os.path.join(out, "topic.json"), "w", encoding="utf-8") as f:
        json.dump(pack, f, indent=2, ensure_ascii=False)

    if fmt in ("json", "all"):
        with open(os.path.join(out, "records.json"), "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)

    if fmt in ("csv", "all"):
        cols = list(rows[0].keys()) if rows else ["record_id"]
        with open(os.path.join(out, "records.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    if fmt in ("markdown", "all"):
        _write_markdown(out, name, pack, kept, now)

    print(c.green(f"✓ exported {len(kept)} records → {os.path.abspath(out)}"))
    for fn in sorted(os.listdir(out)):
        print(c.kv("  " + fn, ""))
    return 0


def _write_markdown(out: str, name: str, pack: Dict, kept: List[Candidate], now: str) -> None:
    terms = pack.get("terms", []) + pack.get("accepted_suggestions", [])
    lines = [
        f"# Topic: {name}", "",
        f"_Generated {now} by AIKB — {len(kept)} source-linked records._", "",
        "**Terms:** " + (", ".join(terms) or "—"),
    ]
    if pack.get("exclude_terms"):
        lines.append("**Excluded terms:** " + ", ".join(pack["exclude_terms"]))
    lines += ["", "## Records", ""]
    for x in kept:
        d = (x.created_at or "")[:10]
        lines += [
            f"### {x.title or x.record_id}",
            f"- {d} · `{x.kind}` · {x.source} · matched: {', '.join(x.matched) or '—'}",
            "",
            "> " + x.snippet.replace("\n", " "),
            "",
            f"`{x.record_id}`  ",
            f"source: `{x.source_path}`",
            "",
        ]
    with open(os.path.join(out, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    timeline = sorted(kept, key=lambda x: (x.created_at or ""))
    tl = [f"# Timeline: {name}", ""]
    cur = None
    for x in timeline:
        month = (x.created_at or "")[:7] or "undated"
        if month != cur:
            tl += ["", f"## {month}", ""]
            cur = month
        tl.append(f"- {(x.created_at or '')[:10]} — {x.title or x.record_id}  `{x.record_id}`")
    with open(os.path.join(out, "timeline.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(tl))
