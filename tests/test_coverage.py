"""`aikb coverage`: what no topic has claimed yet.

A topic only finds what you seed it with. Coverage answers the opposite
question: which conversations are not a strong (high/medium) match for ANY
topic, when they happened, and which words keep showing up in them, so the
next topic can be seeded from the leftovers instead of from memory.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aikb.cli import main
from aikb.coverage import compute_coverage
from aikb.db import Index
from aikb.indexer import build_index
from aikb.sources import Walker
from aikb.topics import new_pack


def _conv(cid, title, created, *messages):
    return {
        "uuid": cid, "name": title, "created_at": created,
        "chat_messages": [
            {"uuid": f"{cid}-m{i}", "sender": "human", "text": text, "created_at": created}
            for i, text in enumerate(messages)
        ],
    }


def _index(tmp, convos, topics=()):
    src = os.path.join(tmp, "export")
    idx_dir = os.path.join(tmp, "idx")
    os.makedirs(src)
    with open(os.path.join(src, "conversations.json"), "w", encoding="utf-8") as f:
        json.dump(convos, f)
    build_index(idx_dir, [src], Walker(index_dir=idx_dir))
    with Index(idx_dir).open() as idx:
        for name, terms, exclude_ids in topics:
            pack = new_pack(name)
            pack["terms"] = terms
            pack["exclude_ids"] = list(exclude_ids)
            idx.save_topic(name, pack)
    return idx_dir


APACE = (["ApaceSystems", "elevator", "GST", "quotation"], ())


def _apace_and_travel():
    return [
        # the title says nothing; only the message mentions the topic terms
        _conv("c1", "Quote flow", "2026-01-02T00:00:00Z",
              "How should the ApaceSystems elevator quotation handle GST?"),
        _conv("c2", "Tokyo trip", "2026-02-10T00:00:00Z", "Find me flights to Tokyo."),
    ]


def test_conversation_is_covered_when_one_of_its_messages_matches_a_topic():
    with tempfile.TemporaryDirectory() as tmp:
        idx_dir = _index(tmp, _apace_and_travel(), [("apace", *APACE)])
        with Index(idx_dir).open() as idx:
            rep = compute_coverage(idx)
        assert rep.total == 2
        assert rep.covered == 1
        assert [x["title"] for x in rep.leftovers] == ["Tokyo trip"]


def test_without_topics_every_conversation_is_a_leftover():
    with tempfile.TemporaryDirectory() as tmp:
        idx_dir = _index(tmp, _apace_and_travel())
        with Index(idx_dir).open() as idx:
            rep = compute_coverage(idx)
        assert rep.covered == 0
        assert len(rep.leftovers) == 2


def test_leftovers_are_counted_by_month():
    convos = _apace_and_travel() + [
        _conv("c3", "Chess opening", "2026-02-20T00:00:00Z", "Explain the Sicilian defence."),
        _conv("c4", "Camry battery", "2026-03-01T00:00:00Z", "My car will not start."),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        idx_dir = _index(tmp, convos, [("apace", *APACE)])
        with Index(idx_dir).open() as idx:
            rep = compute_coverage(idx)
        assert rep.by_month == {"2026-02": 2, "2026-03": 1}


def test_a_match_the_user_pinned_out_does_not_count_as_coverage():
    with tempfile.TemporaryDirectory() as tmp:
        excluded = ["claude-export:c1:c1-m0"]  # the only message that matched
        idx_dir = _index(tmp, _apace_and_travel(), [("apace", APACE[0], excluded)])
        with Index(idx_dir).open() as idx:
            rep = compute_coverage(idx)
        assert rep.covered == 0
        assert {x["title"] for x in rep.leftovers} == {"Quote flow", "Tokyo trip"}


def test_suggests_new_topic_terms_from_the_leftovers_only():
    poker = [
        _conv(f"p{i}", f"Poker night {i}", "2026-04-0%dT00:00:00Z" % (i + 1),
              f"Should my bankroll cover tournament {i} buy-ins?")
        for i in range(4)
    ]
    misc = [
        _conv("m1", "Tokyo trip", "2026-04-05T00:00:00Z", "Find me flights to Tokyo."),
        _conv("m2", "Chess opening", "2026-04-06T00:00:00Z", "Explain the Sicilian defence."),
        _conv("m3", "Camry battery", "2026-04-07T00:00:00Z", "My car will not start."),
        _conv("m4", "Birthday gift", "2026-04-08T00:00:00Z", "Gift ideas for my sister."),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        idx_dir = _index(tmp, _apace_and_travel()[:1] + poker + misc, [("apace", *APACE)])
        with Index(idx_dir).open() as idx:
            rep = compute_coverage(idx)
        words = [w for w, _ in rep.suggestions]
        assert "bankroll" in words
        assert not {"apacesystems", "elevator", "gst", "quotation"} & set(words)


def test_words_just_as_common_in_claimed_conversations_are_not_suggested():
    claimed = [
        _conv(f"a{i}", f"Apace {i}", "2026-01-0%dT00:00:00Z" % (i + 1),
              f"Before we ship, fix the elevator GST quotation step {i}.")
        for i in range(4)
    ]
    leftovers = [
        _conv(f"p{i}", f"Night {i}", "2026-04-0%dT00:00:00Z" % (i + 1),
              f"Before the game, does my bankroll cover round {i}?")
        for i in range(4)
    ] + [
        _conv(f"m{i}", f"Misc {i}", "2026-05-0%dT00:00:00Z" % (i + 1), f"random note {i}")
        for i in range(4)
    ]
    with tempfile.TemporaryDirectory() as tmp:
        idx_dir = _index(tmp, claimed + leftovers, [("apace", *APACE)])
        with Index(idx_dir).open() as idx:
            rep = compute_coverage(idx)
        words = [w for w, _ in rep.suggestions]
        assert "bankroll" in words
        assert "before" not in words  # as common in the claimed chats: scaffolding, not a new topic


def test_cli_prints_coverage_summary_and_leftovers():
    with tempfile.TemporaryDirectory() as tmp:
        idx_dir = _index(tmp, _apace_and_travel(), [("apace", *APACE)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--no-color", "coverage", idx_dir])
        text = out.getvalue()
        assert code == 0
        assert "1 of 2" in text
        assert "Tokyo trip" in text
        assert "2026-02" in text


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("OK — coverage tests passed")
