"""The noise filter applies below the folder you index, never to where that folder lives."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aikb.sources import Walker


def _touch(path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[]")
    return path


def test_a_root_that_lives_under_a_tmp_folder_is_still_indexed():
    # Linux temp dirs are /tmp/...; an export kept in ~/tmp or ~/build/... must not vanish.
    with tempfile.TemporaryDirectory() as base:
        export = os.path.join(base, "tmp", "build", "export")
        convo = _touch(os.path.join(export, "conversations.json"))
        assert list(Walker().walk(export)) == [convo]


def test_noise_folders_inside_the_root_are_still_skipped():
    with tempfile.TemporaryDirectory() as base:
        keep = _touch(os.path.join(base, "notes", "plan.md"))
        _touch(os.path.join(base, "node_modules", "pkg", "README.md"))
        _touch(os.path.join(base, "notes", "cache", "blob.json"))
        assert list(Walker().walk(base)) == [keep]


def test_credentials_are_never_yielded():
    with tempfile.TemporaryDirectory() as base:
        keep = _touch(os.path.join(base, "conversations.json"))
        _touch(os.path.join(base, "auth.json"))
        _touch(os.path.join(base, ".env.local"))
        assert list(Walker(use_default_ignores=False).walk(base)) == [keep]
