"""End-to-end smoke test on a synthetic Claude export fixture.

Runnable two ways:
    python tests/test_smoke.py        # standalone, prints OK
    pytest                            # discovered as test_*
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aikb.db import Index, fts_and_query
from aikb.indexer import build_index
from aikb.sources import Walker
from aikb.topics import match_topic, new_pack


def _fixture(root: str) -> None:
    convos = [
        {
            "uuid": "c1", "name": "Apace elevator quote flow",
            "created_at": "2026-01-02T00:00:00Z",
            "chat_messages": [
                {"uuid": "m1", "sender": "human",
                 "text": "How should the ApaceSystems elevator COP quotation work with GST?"},
                {"uuid": "m2", "sender": "assistant",
                 "text": "Model the quote as a state machine: draft -> quoted -> invoiced. "
                         "Call it with api_key=sk-abcdefghij1234567890 (do not log)."},
            ],
        },
        {
            "uuid": "c2", "name": "Unrelated travel plans",
            "created_at": "2026-01-03T00:00:00Z",
            "chat_messages": [
                {"uuid": "m3", "sender": "human", "text": "Find me flights to Tokyo."},
            ],
        },
    ]
    with open(os.path.join(root, "conversations.json"), "w", encoding="utf-8") as f:
        json.dump(convos, f)
    # a credential file that must NOT be indexed
    with open(os.path.join(root, "auth.json"), "w", encoding="utf-8") as f:
        json.dump({"token": "SECRET-DO-NOT-INDEX"}, f)


def test_index_search_and_topic():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "export")
        idx_dir = os.path.join(tmp, "idx")
        os.makedirs(src)
        _fixture(src)

        res = build_index(idx_dir, [src], Walker(index_dir=idx_dir))
        assert res.records >= 3, f"expected >=3 records, got {res.records}"

        # incremental: a second run skips unchanged files and adds nothing new
        res2 = build_index(idx_dir, [src], Walker(index_dir=idx_dir))
        assert res2.files_unchanged >= 1, "expected unchanged files on re-index"
        assert res2.records == 0, f"re-index added {res2.records} records, expected 0"

        with Index(idx_dir).open() as idx:
            # secret shapes are redacted out of indexed text
            texts = [row["text"] for row in idx.iter_records()]
            assert all("sk-abcdefghij1234567890" not in t for t in texts), "API key not redacted"
            assert any("[REDACTED]" in t for t in texts), "expected a redaction marker"

            # full-text search finds the elevator message (queries built the
            # same way the CLI builds them — caller's job to sanitize)
            hits = idx.search(fts_and_query(["elevator"]), limit=10)
            assert any("elevator" in (h["snippet"] or "").lower() for h in hits), hits

            # credentials were skipped — even hyphenated tokens stay safe
            secret = idx.search(fts_and_query(["SECRET-DO-NOT-INDEX"]), limit=10)
            assert not secret, "auth.json must never be indexed"

            # topic matching buckets the apace conversation high, ignores travel
            pack = new_pack("apace")
            pack["terms"] = ["ApaceSystems", "elevator", "GST", "COP", "quotation"]
            cands = match_topic(idx, pack)
            high = [c for c in cands if c.bucket == "high"]
            assert high, "expected at least one high-confidence apace match"
            assert all("Tokyo" not in c.text for c in high), "travel chat leaked into apace"

    return True


if __name__ == "__main__":
    test_index_search_and_topic()
    print("OK — smoke test passed")
