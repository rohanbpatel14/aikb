from __future__ import annotations

import json
import os
from typing import Iterable

from ..model import (CONVERSATION, MEMORY, MESSAGE, PROJECT, Record, make_id,
                     short_hash)
from ._jsonl import content_to_text
from .base import Adapter

_SENDER_ROLE = {"human": "user", "assistant": "assistant"}


class ClaudeExportAdapter(Adapter):
    """Official claude.ai account export (the emailed data ZIP, extracted).

    `conversations.json` is one big array of conversations, each with
    `chat_messages`. We emit a CONVERSATION record per conversation plus a
    MESSAGE record per message, so search has both coarse and fine grain.
    """

    name = "claude-export"
    priority = 10

    def handles(self, path: str) -> bool:
        return os.path.basename(path) in (
            "conversations.json", "projects.json", "memories.json",
        )

    def parse(self, path: str) -> Iterable[Record]:
        base = os.path.basename(path)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return
        if base == "conversations.json":
            yield from self._conversations(path, data)
        elif base == "projects.json":
            yield from self._projects(path, data)
        elif base == "memories.json":
            yield from self._memories(path, data)

    def _conversations(self, path: str, data) -> Iterable[Record]:
        if not isinstance(data, list):
            return
        for conv in data:
            if not isinstance(conv, dict):
                continue
            cuid = conv.get("uuid") or short_hash(json.dumps(conv)[:200])
            name = conv.get("name") or "(untitled)"
            ca, ua = conv.get("created_at"), conv.get("updated_at")
            msgs = conv.get("chat_messages") or []
            n = 0
            for msg in msgs:
                if not isinstance(msg, dict):
                    continue
                text = self._message_text(msg).strip()
                if not text:
                    continue
                muid = msg.get("uuid") or f"m{n}"
                sender = msg.get("sender", "")
                n += 1
                yield Record(
                    record_id=f"claude-export:{cuid}:{muid}",
                    source=self.name, source_path=path, kind=MESSAGE,
                    text=text, participant=_SENDER_ROLE.get(sender, sender),
                    locator=str(muid), created_at=msg.get("created_at"),
                    parent_id=f"claude-export:{cuid}",
                )
            yield Record(
                record_id=f"claude-export:{cuid}",
                source=self.name, source_path=path, kind=CONVERSATION,
                text=name, title=name[:120], created_at=ca, updated_at=ua,
                metadata={"messages": n},
            )

    @staticmethod
    def _message_text(msg: dict) -> str:
        content = msg.get("content")
        if isinstance(content, list):
            t = content_to_text(content)
            if t.strip():
                return t
        return msg.get("text", "") or ""

    def _projects(self, path: str, data) -> Iterable[Record]:
        items = data if isinstance(data, list) else data.get("projects", []) if isinstance(data, dict) else []
        for proj in items:
            if not isinstance(proj, dict):
                continue
            puid = proj.get("uuid") or short_hash(str(proj.get("name", "")))
            name = proj.get("name") or "(project)"
            desc = proj.get("description") or proj.get("prompt_template") or ""
            yield Record(
                record_id=f"claude-export-project:{puid}",
                source=self.name, source_path=path, kind=PROJECT,
                title=name, text=f"{name}\n{desc}", created_at=proj.get("created_at"),
            )

    def _memories(self, path: str, data) -> Iterable[Record]:
        items = data if isinstance(data, list) else [data]
        for i, mem in enumerate(items):
            if isinstance(mem, dict):
                text = mem.get("content") or mem.get("text") or json.dumps(mem, ensure_ascii=False)
            else:
                text = str(mem)
            if not text.strip():
                continue
            yield Record(
                record_id=make_id("claude-export-memory", path, i),
                source=self.name, source_path=path, kind=MEMORY,
                title="memory", text=text,
            )
