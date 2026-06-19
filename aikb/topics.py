"""Topic packs — the primary AIKB primitive.

A topic pack starts from the fragments a user actually remembers ("Apace,
elevator, GST, quote") and grows into a persistent, source-linked definition
of a subject. Matching is multi-pass and explainable: every candidate gets a
confidence bucket, the terms it matched, and a one-line reason.

The point (proven by the real ApaceSystems case): exact search misses chats
buried under unrelated titles. So manual include/exclude decisions are saved
into the pack and survive every rerun — recall only improves over time.
"""
from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List

from . import console as c
from .db import Index, fts_or_query
from .model import STRUCTURAL_WEIGHT

BUCKETS = ("high", "medium", "buried", "false")
BUCKET_LABEL = {
    "high": "high-confidence",
    "medium": "medium-confidence",
    "buried": "possible buried match",
    "false": "likely false positive",
}
_DOWNGRADE = {"high": "medium", "medium": "buried", "buried": "false", "false": "false"}

_WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9_+#.-]{2,}")
_STOP = frozenset("""
the a an and or but if then else for to of in on at by with from as is are was were be been being
this that these those it its it's i you he she we they them my your our their me us do does did done
not no yes can could should would will just like get got make made use used using one two also more
""".split())


def squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


# ── topic pack persistence shape ────────────────────────────────────────────
def new_pack(name: str) -> Dict:
    return {
        "name": name,
        "terms": [],
        "exclude_terms": [],
        "accepted_suggestions": [],
        "include_ids": [],
        "exclude_ids": [],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# ── candidate ───────────────────────────────────────────────────────────────
@dataclass
class Candidate:
    record_id: str
    title: str
    kind: str
    source: str
    source_path: str
    created_at: str
    project: str
    participant: str
    text: str
    score: float
    bucket: str
    matched: List[str] = field(default_factory=list)
    snippet: str = ""
    reason: str = ""


# ── matching pipeline ───────────────────────────────────────────────────────
@lru_cache(maxsize=1024)
def _term_pat(term_lower: str):
    # alnum-boundary match so "COP" doesn't hit "copy" and "LOP" doesn't hit "develop"
    return re.compile(r"(?<![a-z0-9])" + re.escape(term_lower) + r"(?![a-z0-9])")


def _matched_terms(text: str, terms: List[str]) -> List[str]:
    tl = text.lower()
    ts = squash(text)
    hits = []
    for term in terms:
        if _term_pat(term.lower()).search(tl):
            hits.append(term)
            continue
        sq = squash(term)
        if len(sq) >= 6 and sq in ts:  # fuzzy: "Apace Systems" ~ "apacesystems"
            hits.append(term)
    return hits


def _context(text: str, terms: List[str], width: int = 90) -> str:
    tl = text.lower()
    pos = -1
    for term in terms:
        i = tl.find(term.lower())
        if i >= 0 and (pos < 0 or i < pos):
            pos = i
    if pos < 0:
        pos = 0
    start = max(0, pos - width)
    end = min(len(text), pos + width)
    s = text[start:end].replace("\n", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return ("…" + s + "…") if (start > 0 or end < len(text)) else s


def _bucket(distinct: int, exclude_hit: bool, matched: List[str], manual: bool) -> str:
    if manual:
        b = "high"
    elif distinct >= 2:
        b = "high"
    elif distinct == 1:
        term = matched[0]
        specific = len(term) >= 6 or " " in term
        b = "medium" if specific else "buried"
    else:
        b = "buried"
    if exclude_hit:
        b = _DOWNGRADE[b]
    return b


def match_topic(idx: Index, pack: Dict, limit: int = 5000) -> List[Candidate]:
    terms = list(pack.get("terms", [])) + list(pack.get("accepted_suggestions", []))
    excludes = list(pack.get("exclude_terms", []))
    include_ids = set(pack.get("include_ids", []))
    exclude_ids = set(pack.get("exclude_ids", []))

    cands: Dict[str, Candidate] = {}
    q = fts_or_query(terms)
    if q:
        for row in idx.raw_fts(q, limit):
            rid = row["record_id"]
            if rid in exclude_ids:
                continue
            text = row["text"] or ""
            hits = _matched_terms(text, terms)
            exh = any(e.lower() in text.lower() for e in excludes)
            manual = rid in include_ids
            bucket = _bucket(len(hits), exh, hits, manual)
            rel = -(row["score"] or 0.0)
            kw = STRUCTURAL_WEIGHT.get(row["kind"], 0.5)
            score = (9999 if manual else 0) + len(hits) * 100 + kw * 10 + rel
            reason = f"{len(hits)} term(s): {', '.join(hits) or '—'}"
            if manual:
                reason = "manually pinned · " + reason
            if exh:
                reason += " · excluded-term hit"
            cands[rid] = Candidate(
                record_id=rid, title=row["title"] or "", kind=row["kind"],
                source=row["source"], source_path=row["source_path"],
                created_at=row["created_at"] or "", project=row["project"] or "",
                participant=row["participant"] or "", text=text,
                score=score, bucket=bucket, matched=hits,
                snippet=_context(text, terms), reason=reason,
            )

    # Manually pinned records that full-text search never surfaced.
    for rid in include_ids:
        if rid in cands:
            continue
        r = idx.get_record(rid)
        if r:
            text = r["text"] or ""
            cands[rid] = Candidate(
                record_id=rid, title=r["title"] or "", kind=r["kind"],
                source=r["source"], source_path=r["source_path"],
                created_at=r["created_at"] or "", project=r["project"] or "",
                participant=r["participant"] or "", text=text,
                score=99999, bucket="high", matched=[],
                snippet=_context(text, terms), reason="manually pinned (not found by search)",
            )

    return sorted(cands.values(), key=lambda x: -x.score)


def bucket_counts(cands: List[Candidate]) -> Counter:
    return Counter(x.bucket for x in cands)


def suggest_terms(cands: List[Candidate], existing: List[str], top: int = 15) -> List[tuple]:
    """Co-occurrence expansion: terms frequent in strong matches but NOT ubiquitous.

    A word appearing in almost every match (users, tool, code) is scaffolding,
    not signal. We keep the mid-frequency band — distinctive enough to matter
    (graphql, rails, invoice), common enough to be a real theme.
    """
    have = {squash(t) for t in existing}
    strong = [c for c in cands if c.bucket in ("high", "medium")]
    n = len(strong) or 1
    freq: Counter = Counter()
    for cand in strong:
        seen = set()
        for w in _WORD.findall(cand.text.lower()):
            if w in _STOP or len(w) < 4 or squash(w) in have or w in seen:
                continue
            seen.add(w)  # document frequency: count each word once per record
            freq[w] += 1
    cap = max(3, int(0.5 * n))  # drop words present in >50% of strong matches
    ranked = [(w, f) for w, f in freq.items() if 3 <= f <= cap]
    ranked.sort(key=lambda x: -x[1])
    return ranked[:top]


# ── CLI command handlers ────────────────────────────────────────────────────
def _split(arg: str) -> List[str]:
    return [t.strip() for t in (arg or "").split(",") if t.strip()]


def _print_summary(name: str, cands: List[Candidate]) -> None:
    counts = bucket_counts(cands)
    print(c.header(f"Topic: {name}"))
    for b in BUCKETS:
        n = counts.get(b, 0)
        print(c.kv("  " + BUCKET_LABEL[b], c.confidence(b, c.count(n))))
    print(c.kv("  total candidates", c.bold(c.count(len(cands)))))


def cmd_topic_create(args) -> int:
    with Index(args.index).open() as idx:
        pack = idx.get_topic(args.name) or new_pack(args.name)
        pack["terms"] = _split(args.terms)
        pack["exclude_terms"] = _split(args.exclude)
        idx.save_topic(args.name, pack)
        cands = match_topic(idx, pack)
    print()
    _print_summary(args.name, cands)
    print()
    print(c.dim(f"Next: aikb topic review {args.index} {args.name}"))
    return 0


def cmd_topic_status(args) -> int:
    with Index(args.index).open() as idx:
        pack = idx.get_topic(args.name)
        if not pack:
            print(c.red(f"No topic '{args.name}'. Create it with `aikb topic create`."))
            return 2
        cands = match_topic(idx, pack)
    print()
    _print_summary(args.name, cands)
    print()
    print(c.kv("terms", ", ".join(pack.get("terms", [])) or c.dim("none")))
    if pack.get("accepted_suggestions"):
        print(c.kv("added", ", ".join(pack["accepted_suggestions"])))
    if pack.get("exclude_terms"):
        print(c.kv("excluded terms", ", ".join(pack["exclude_terms"])))
    print(c.kv("pinned in", c.count(len(pack.get("include_ids", [])))))
    print(c.kv("pinned out", c.count(len(pack.get("exclude_ids", [])))))
    return 0


def cmd_topic_terms(args) -> int:
    with Index(args.index).open() as idx:
        pack = idx.get_topic(args.name)
        if not pack:
            print(c.red(f"No topic '{args.name}'."))
            return 2
        if args.action == "suggest":
            cands = match_topic(idx, pack)
            existing = pack.get("terms", []) + pack.get("accepted_suggestions", [])
            sugg = suggest_terms(cands, existing)
            print(c.header(f"suggested terms for '{args.name}'"))
            if not sugg:
                print(c.dim("  (no strong co-occurring terms found)"))
            for w, n in sugg:
                print(c.kv("  " + w, c.dim(f"in {n} strong matches")))
            print()
            print(c.dim(f"Add with: aikb topic terms {args.index} {args.name} add <word> <word>"))
            return 0
        if args.action == "add":
            added = [w for w in args.words if w]
            acc = pack.setdefault("accepted_suggestions", [])
            for w in added:
                if w not in acc and w not in pack.get("terms", []):
                    acc.append(w)
            idx.save_topic(args.name, pack)
            cands = match_topic(idx, pack)
            print(c.green(f"added: {', '.join(added)}"))
            print()
            _print_summary(args.name, cands)
            return 0
    return 1


def cmd_topic_review(args) -> int:
    from .review import run_review
    return run_review(args.index, args.name, limit=args.limit)


def cmd_topic_export(args) -> int:
    from .export import export_topic
    return export_topic(args.index, args.name, args.out, args.format)


def _topic_help(parser):
    def fn(args):
        parser.print_help()
        return 1
    return fn


def register(sub) -> None:
    tp = sub.add_parser("topic", help="create, review, and export topic packs")
    tsub = tp.add_subparsers(dest="topic_cmd")
    tp.set_defaults(func=_topic_help(tp))

    sp = tsub.add_parser("create", help="build a topic from remembered terms")
    sp.add_argument("index")
    sp.add_argument("name")
    sp.add_argument("--terms", required=True, help="comma-separated terms you remember")
    sp.add_argument("--exclude", default="", help="comma-separated terms to penalize")
    sp.set_defaults(func=cmd_topic_create)

    sp = tsub.add_parser("status", help="show a topic's current match buckets")
    sp.add_argument("index")
    sp.add_argument("name")
    sp.set_defaults(func=cmd_topic_status)

    sp = tsub.add_parser("review", help="interactively include/exclude uncertain matches")
    sp.add_argument("index")
    sp.add_argument("name")
    sp.add_argument("--limit", type=int, default=0, help="max candidates to review (0 = all)")
    sp.set_defaults(func=cmd_topic_review)

    sp = tsub.add_parser("terms", help="suggest or add co-occurring terms")
    sp.add_argument("index")
    sp.add_argument("name")
    sp.add_argument("action", choices=["suggest", "add"])
    sp.add_argument("words", nargs="*")
    sp.set_defaults(func=cmd_topic_terms)

    sp = tsub.add_parser("export", help="write a source-linked topic pack")
    sp.add_argument("index")
    sp.add_argument("name")
    sp.add_argument("--out", required=True, metavar="DIR")
    sp.add_argument("--format", default="markdown",
                    choices=["markdown", "json", "csv", "all"])
    sp.set_defaults(func=cmd_topic_export)
