"""Coverage — what no topic has claimed yet.

A topic only finds what you seed it with, so it can't answer "what else is in
there?". Coverage is the inverse view: every conversation that is not a strong
(high/medium) match for ANY topic, counted by month, plus the words that keep
recurring in those leftovers so the next topic can be seeded from the data
instead of from memory. Rerun after each new topic until the leftovers are small.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Set

from . import console as c
from .db import Index
from .model import CONVERSATION
from .topics import match_topic, suggest_from_texts

STRONG = ("high", "medium")


@dataclass
class CoverageReport:
    total: int
    covered: int
    leftovers: List[Dict[str, str]]  # record_id, title, created_at; oldest first
    by_month: Counter
    suggestions: List[tuple]          # (word, number of leftover conversations it appears in)


def _claimed_conversations(idx: Index, parent_of: Dict[str, str]) -> Set[str]:
    """A conversation is claimed if it, or any of its messages, is a strong topic match."""
    claimed: Set[str] = set()
    for name in idx.list_topics():
        for cand in match_topic(idx, idx.get_topic(name) or {}):
            if cand.bucket in STRONG:
                claimed.add(parent_of.get(cand.record_id) or cand.record_id)
    return claimed


def _topic_terms(idx: Index) -> List[str]:
    terms: List[str] = []
    for name in idx.list_topics():
        pack = idx.get_topic(name) or {}
        terms += pack.get("terms", []) + pack.get("accepted_suggestions", [])
    return terms


def compute_coverage(idx: Index, top: int = 15) -> CoverageReport:
    conn = idx.conn
    conversations = conn.execute(
        "SELECT record_id, title, created_at FROM records WHERE kind=? ORDER BY created_at",
        (CONVERSATION,),
    ).fetchall()
    children = conn.execute(
        "SELECT record_id, parent_id, text FROM records WHERE parent_id IS NOT NULL"
    ).fetchall()
    parent_of = {r["record_id"]: r["parent_id"] for r in children}

    claimed = _claimed_conversations(idx, parent_of)
    leftovers = [
        {"record_id": r["record_id"], "title": r["title"] or r["record_id"],
         "created_at": r["created_at"] or ""}
        for r in conversations if r["record_id"] not in claimed
    ]

    # Each conversation is one document (title + messages). Leftovers are contrasted
    # against claimed conversations so only words distinctive to the leftovers surface.
    docs = {r["record_id"]: [r["title"] or ""] for r in conversations}
    for r in children:
        if r["parent_id"] in docs:
            docs[r["parent_id"]].append(r["text"] or "")
    left_ids = {x["record_id"] for x in leftovers}
    texts = {rid: "\n".join(parts) for rid, parts in docs.items()}
    suggestions = suggest_from_texts(
        [t for rid, t in texts.items() if rid in left_ids], _topic_terms(idx), top,
        background=[t for rid, t in texts.items() if rid not in left_ids],
    )

    return CoverageReport(
        total=len(conversations),
        covered=len(conversations) - len(leftovers),
        leftovers=leftovers,
        by_month=Counter(x["created_at"][:7] for x in leftovers if x["created_at"]),
        suggestions=suggestions,
    )


def cmd_coverage(args) -> int:
    with Index(args.index).open() as idx:
        topics = idx.list_topics()
        rep = compute_coverage(idx, top=args.top)

    pct = (100 * rep.covered // rep.total) if rep.total else 0
    print(c.header("coverage") + c.dim(f"  across {len(topics)} topic(s)"))
    print(c.kv("  conversations", c.count(rep.total)))
    print(c.kv("  claimed by a topic", f"{rep.covered:,} of {rep.total:,} ({pct}%)"))
    print(c.kv("  leftovers", c.bold(c.count(len(rep.leftovers)))))

    if rep.by_month:
        print()
        print(c.bold("leftovers by month"))
        peak = max(rep.by_month.values())
        for month in sorted(rep.by_month):
            n = rep.by_month[month]
            print(f"  {month}  {n:>5}  {c.dim('▇' * max(1, round(20 * n / peak)))}")

    if rep.leftovers:
        shown = rep.leftovers[::-1][: args.limit] if args.limit else rep.leftovers[::-1]
        print()
        print(c.bold("leftover conversations") + c.dim(f"  newest first, {len(shown)} of {len(rep.leftovers)}"))
        for x in shown:
            print(f"  {c.dim(x['created_at'][:10] or '----------')}  {x['title']}  {c.dim(x['record_id'])}")

    print()
    print(c.bold("terms that recur in the leftovers"))
    if not rep.suggestions:
        print(c.dim("  (none yet — too few leftovers share a word)"))
    for w, n in rep.suggestions:
        print(c.kv("  " + w, c.dim(f"in {n} leftover conversations")))
    print()
    print(c.dim(f'Next: aikb topic create {args.index} <name> --terms "word,word"  then rerun coverage'))
    return 0


def register(sub) -> None:
    sp = sub.add_parser("coverage", help="what no topic has claimed yet, by month, with term ideas")
    sp.add_argument("index")
    sp.add_argument("--limit", type=int, default=25, help="leftover conversations to list (0 = all)")
    sp.add_argument("--top", type=int, default=15, help="suggested terms to show")
    sp.set_defaults(func=cmd_coverage)
