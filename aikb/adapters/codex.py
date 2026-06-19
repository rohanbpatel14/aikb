from __future__ import annotations

import os
import sqlite3
from typing import Iterable

from ..model import CONVERSATION, DOCUMENT, MEMORY, MESSAGE, Record, make_id
from ..util import mtime_iso, truncate
from ._jsonl import content_to_text, iter_jsonl
from .base import Adapter


class CodexAdapter(Adapter):
    """Local Codex data under ~/.codex.

    Codex rollout sessions wrap everything in {timestamp, type, payload}. The
    real dialogue is `response_item/message`; assistant reasoning is
    `response_item/reasoning`; `session_meta` carries the project cwd. Tool
    calls, command output, and token-count telemetry are dropped as noise.
    SQLite stores (memories/goals) are mined read-only, best-effort.
    """

    name = "codex"
    priority = 10

    def handles(self, path: str) -> bool:
        p = path.replace(os.sep, "/")
        if "/.codex/" not in p:
            return False
        if p.endswith(".jsonl"):
            return True
        if p.endswith(".sqlite"):
            # memories/goals/state hold knowledge; logs_*.sqlite is telemetry noise
            return not os.path.basename(p).lower().startswith("log")
        if p.endswith("/AGENTS.md"):
            return True
        if "/rules/" in p and p.endswith(".rules"):
            return True
        if p.endswith("pasted-text.txt"):
            return True
        return False

    def parse(self, path: str) -> Iterable[Record]:
        p = path.replace(os.sep, "/")
        if p.endswith(".jsonl"):
            yield from self._session(path)
        elif p.endswith(".sqlite"):
            yield from self._sqlite(path)
        else:
            yield self._doc(path)

    # ── rollout session ───────────────────────────────────────────────────
    def _session(self, path: str):
        sid = os.path.splitext(os.path.basename(path))[0]
        cwd = None
        t_first = t_last = None
        first_user = None
        n = 0
        for i, obj in iter_jsonl(path):
            ts = obj.get("timestamp")
            if ts:
                t_first = t_first or ts
                t_last = ts
            typ = obj.get("type")
            pl = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
            if typ == "session_meta":
                cwd = pl.get("cwd") or cwd
                continue
            ptype = pl.get("type")
            role = None
            text = ""
            if typ == "response_item" and ptype == "message":
                role = pl.get("role") or "?"
                text = content_to_text(pl.get("content")).strip()
            elif typ == "response_item" and ptype == "reasoning":
                role = "assistant"
                text = self._reasoning_text(pl).strip()
            else:
                continue  # function_call / token_count / exec output -> noise
            if not text:
                continue
            if role == "user" and first_user is None:
                first_user = text[:90]
            n += 1
            yield Record(
                record_id=f"codex:{sid}:L{i}", source=self.name, source_path=path,
                kind=MESSAGE, text=text, participant=str(role), locator=f"L{i}",
                created_at=ts, parent_id=f"codex:{sid}", project=cwd or "",
            )
        if n:
            title = first_user or sid
            yield Record(
                record_id=f"codex:{sid}", source=self.name, source_path=path,
                kind=CONVERSATION, text=title, title=title[:120],
                created_at=t_first, updated_at=t_last, project=cwd or "",
                metadata={"messages": n},
            )

    @staticmethod
    def _reasoning_text(pl: dict) -> str:
        parts = []
        for s in pl.get("summary") or []:
            if isinstance(s, dict) and s.get("text"):
                parts.append(s["text"])
        c = pl.get("content")
        if c:
            parts.append(content_to_text(c))
        return "\n".join(p for p in parts if p)

    # ── sqlite stores ─────────────────────────────────────────────────────
    def _sqlite(self, path: str):
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
            con.row_factory = sqlite3.Row
        except Exception:
            return
        try:
            tables = [
                r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            ]
            for t in tables:
                try:
                    rows = con.execute(f'SELECT * FROM "{t}" LIMIT 5000')
                except Exception:
                    continue
                for j, row in enumerate(rows):
                    vals = [
                        row[k] for k in row.keys()
                        if isinstance(row[k], str) and len(row[k].strip()) >= 3
                    ]
                    text = "\n".join(vals).strip()
                    if not text:
                        continue
                    kind = MEMORY if ("mem" in t.lower() or "goal" in t.lower()) else DOCUMENT
                    yield Record(
                        record_id=f"codex-db:{make_id(t, path, j)}",
                        source=self.name, source_path=path, kind=kind,
                        title=f"{os.path.basename(path)}:{t}",
                        text=truncate(text, 8000), metadata={"table": t},
                    )
        finally:
            con.close()

    def _doc(self, path: str) -> Record:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            text = ""
        return Record(
            record_id=make_id(self.name, path, 0), source=self.name,
            source_path=path, kind=DOCUMENT, title=os.path.basename(path),
            text=text, created_at=mtime_iso(path),
        )
