from __future__ import annotations

import os
from typing import Iterable

from ..model import (CONVERSATION, DOCUMENT, MEMORY, MESSAGE, TASK, Record,
                     make_id)
from ..util import mtime_iso
from ._jsonl import content_to_text, first_nonempty, iter_jsonl
from .base import Adapter


class ClaudeCodeAdapter(Adapter):
    """Local Claude Code data under ~/.claude.

    Session transcripts (projects/**/*.jsonl) are the prize: each line is an
    event, and message events carry the real dialogue. Also handles project
    memories, tasks, custom commands, and the prompt history file.
    """

    name = "claude-code"
    priority = 10

    def handles(self, path: str) -> bool:
        p = path.replace(os.sep, "/")
        if "/.claude/" not in p:
            return False
        if "/projects/" in p and p.endswith(".jsonl"):
            return True
        if p.endswith("/history.jsonl"):
            return True
        if "/memory/" in p and p.endswith(".md"):
            return True
        if "/tasks/" in p and p.endswith(".json"):
            return True
        if "/commands/" in p and p.endswith(".md"):
            return True
        return False

    def parse(self, path: str) -> Iterable[Record]:
        p = path.replace(os.sep, "/")
        if "/projects/" in p and p.endswith(".jsonl"):
            yield from self._session(path)
        elif p.endswith("/history.jsonl"):
            yield from self._history(path)
        elif "/memory/" in p:
            yield self._doc(path, MEMORY)
        elif "/tasks/" in p:
            yield self._doc(path, TASK)
        elif "/commands/" in p:
            yield self._doc(path, DOCUMENT)

    # ── session transcript ────────────────────────────────────────────────
    def _session(self, path: str):
        sid = os.path.splitext(os.path.basename(path))[0]
        cwd = None
        t_first = t_last = None
        first_user = None
        n = 0
        for i, obj in iter_jsonl(path):
            if cwd is None and obj.get("cwd"):
                cwd = obj["cwd"]
            ts = obj.get("timestamp")
            if ts:
                t_first = t_first or ts
                t_last = ts
            msg = obj.get("message")
            if not isinstance(msg, dict):
                continue
            role = first_nonempty(msg.get("role"), obj.get("type"), "?")
            text = content_to_text(msg.get("content", "")).strip()
            if not text:
                continue
            muid = first_nonempty(msg.get("id"), obj.get("uuid"), f"L{i}")
            if role == "user" and first_user is None:
                first_user = text[:90]
            n += 1
            yield Record(
                record_id=f"claude-code:{sid}:{muid}",
                source=self.name, source_path=path, kind=MESSAGE,
                text=text, participant=str(role), locator=str(muid),
                created_at=ts, parent_id=f"claude-code:{sid}", project=cwd or "",
            )
        if n:
            title = first_user or sid
            yield Record(
                record_id=f"claude-code:{sid}",
                source=self.name, source_path=path, kind=CONVERSATION,
                text=title, title=title[:120],
                created_at=t_first, updated_at=t_last, project=cwd or "",
                metadata={"messages": n, "session": sid},
            )

    # ── prompt history ────────────────────────────────────────────────────
    def _history(self, path: str):
        for i, obj in iter_jsonl(path):
            text = first_nonempty(obj.get("display"), obj.get("text"), "")
            text = (text or "").strip()
            if not text:
                continue
            yield Record(
                record_id=f"claude-code-history:{make_id('h', path, i)}",
                source=self.name, source_path=path, kind=MESSAGE,
                text=text, participant="user", locator=f"L{i}",
                project=obj.get("project", "") or "",
            )

    # ── plain document (memory / task / command) ──────────────────────────
    def _doc(self, path: str, kind: str) -> Record:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            text = ""
        return Record(
            record_id=make_id(self.name, path, 0),
            source=self.name, source_path=path, kind=kind,
            title=os.path.basename(path), text=text, created_at=mtime_iso(path),
        )
