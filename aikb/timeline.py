"""Chronological view — reconstruct "what happened when" across sources."""
from __future__ import annotations

from . import console as c
from .db import Index
from .model import CONVERSATION
from .topics import match_topic


def cmd_timeline(args) -> int:
    with Index(args.index).open() as idx:
        if args.topic:
            pack = idx.get_topic(args.topic)
            if not pack:
                print(c.red(f"No topic '{args.topic}'."))
                return 2
            items = [
                (x.created_at, x.title or x.record_id, x.source)
                for x in match_topic(idx, pack)
                if x.bucket in ("high", "medium")
            ]
        else:
            rows = idx.conn.execute(
                "SELECT created_at, title, record_id, source FROM records "
                "WHERE kind=? ORDER BY created_at", (CONVERSATION,)
            ).fetchall()
            items = [(r["created_at"], r["title"] or r["record_id"], r["source"]) for r in rows]

    items = [it for it in items if it[0]]
    items.sort(key=lambda x: x[0] or "")
    items = items[: args.limit]

    label = f"timeline · {args.topic}" if args.topic else "timeline"
    print(c.header(label) + c.dim(f"  {len(items)} entries"))
    cur = None
    for created, title, source in items:
        month = (created or "")[:7]
        if month != cur:
            print()
            print(c.bold(month))
            cur = month
        print(f"  {c.dim((created or '')[:10])}  {title}  {c.dim(source)}")
    return 0


def register(sub) -> None:
    sp = sub.add_parser("timeline", help="chronological view (optionally for one topic)")
    sp.add_argument("index")
    sp.add_argument("--topic", default=None, help="restrict to a topic's strong matches")
    sp.add_argument("--limit", type=int, default=300)
    sp.set_defaults(func=cmd_timeline)
