"""`aikb timeline` must not silently drop history."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aikb.cli import main
from aikb.indexer import build_index
from aikb.sources import Walker


def _build(tmp: str, n: int) -> str:
    src, idx_dir = os.path.join(tmp, "export"), os.path.join(tmp, "idx")
    os.makedirs(src)
    convos = [
        {"uuid": f"c{i}", "name": f"Chat {i:04d}",
         "created_at": f"2025-{1 + i % 12:02d}-{1 + i % 28:02d}T00:00:00Z",
         "chat_messages": [{"uuid": f"m{i}", "sender": "human", "text": f"hello {i}"}]}
        for i in range(n)
    ]
    with open(os.path.join(src, "conversations.json"), "w", encoding="utf-8") as f:
        json.dump(convos, f)
    build_index(idx_dir, [src], Walker(index_dir=idx_dir))
    return idx_dir


def _run(*argv: str) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(["--no-color", *argv]) == 0
    return out.getvalue()


def test_timeline_shows_every_conversation_by_default():
    with tempfile.TemporaryDirectory() as tmp:
        idx_dir = _build(tmp, 350)
        assert "350 entries" in _run("timeline", idx_dir)


def test_timeline_limit_still_caps_when_asked():
    with tempfile.TemporaryDirectory() as tmp:
        idx_dir = _build(tmp, 20)
        assert "5 entries" in _run("timeline", idx_dir, "--limit", "5")
