from __future__ import annotations

import os
from typing import Iterable

from ..model import (CONVERSATION, DOCUMENT, MESSAGE, PLAN, TERMINAL_LOG,
                     Record, make_id)
from ..util import mtime_iso
from ._jsonl import iter_jsonl, probe_role_text
from .base import Adapter


class CursorAdapter(Adapter):
    """Local Cursor data under ~/.cursor: agent transcripts, plans, terminals, skills."""

    name = "cursor"
    priority = 10

    def handles(self, path: str) -> bool:
        p = path.replace(os.sep, "/")
        if "/.cursor/" not in p:
            return False
        if "/agent-transcripts/" in p and p.endswith(".jsonl"):
            return True
        if "/plans/" in p and p.endswith(".md"):
            return True
        if "/terminals/" in p and p.endswith(".txt"):
            return True
        if p.endswith("/SKILL.md"):
            return True
        return False

    def parse(self, path: str) -> Iterable[Record]:
        p = path.replace(os.sep, "/")
        if p.endswith(".jsonl"):
            yield from self._session(path)
        elif "/terminals/" in p:
            yield self._doc(path, TERMINAL_LOG)
        elif "/plans/" in p:
            yield self._doc(path, PLAN)
        else:
            yield self._doc(path, DOCUMENT)

    def _session(self, path: str):
        sid = os.path.splitext(os.path.basename(path))[0]
        first = None
        n = 0
        for i, obj in iter_jsonl(path):
            ts = obj.get("timestamp") or obj.get("created_at")
            role, text = probe_role_text(obj)
            if not text:
                continue
            if role == "user" and first is None:
                first = text[:90]
            n += 1
            yield Record(
                record_id=f"cursor:{sid}:L{i}", source=self.name, source_path=path,
                kind=MESSAGE, text=text, participant=role, locator=f"L{i}",
                created_at=ts, parent_id=f"cursor:{sid}",
            )
        if n:
            title = first or sid
            yield Record(
                record_id=f"cursor:{sid}", source=self.name, source_path=path,
                kind=CONVERSATION, text=title, title=title[:120],
                metadata={"messages": n},
            )

    def _doc(self, path: str, kind: str) -> Record:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            text = ""
        return Record(
            record_id=make_id(self.name, path, 0), source=self.name,
            source_path=path, kind=kind, title=os.path.basename(path),
            text=text, created_at=mtime_iso(path),
        )
