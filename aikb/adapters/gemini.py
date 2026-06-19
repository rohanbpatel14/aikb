from __future__ import annotations

import json
import os
import re
from typing import Iterable

from ..model import CONVERSATION, DOCUMENT, Record, make_id
from ..util import mtime_iso
from .base import Adapter

# Runs of printable text (ASCII + common Unicode), used to recover strings
# embedded in binary protobuf without the .proto schema.
_PRINTABLE = re.compile(r"[\x20-\x7e -￿]{4,}")
_NOISE = ("/Session Storage/", "/Local Storage/", "/IndexedDB/", "/Cache/",
          "/GPUCache/", "/Service Worker/", "/blob_storage/")


class GeminiAdapter(Adapter):
    """Local Gemini / Antigravity data under ~/.gemini.

    Conversations are stored as protobuf (.pb binary, .pbtxt text) inside a
    Chromium-style webview, surrounded by browser caches and image thumbnails.
    We target only the conversation/chat areas and recover text best-effort:
    JSON parsed structurally, .pbtxt read as text, binary .pb mined for
    embedded strings. Low structural confidence by design — clearly labeled.
    """

    name = "gemini"
    priority = 10
    MAX_BYTES = 5_000_000

    def handles(self, path: str) -> bool:
        p = path.replace(os.sep, "/")
        if "/.gemini/" not in p:
            return False
        if any(x in p for x in _NOISE):
            return False
        if "/conversations/" not in p and "/chats/" not in p:
            return False
        return p.endswith((".pb", ".pbtxt", ".json", ".txt", ".md"))

    def parse(self, path: str) -> Iterable[Record]:
        try:
            if os.path.getsize(path) > self.MAX_BYTES:
                return
        except OSError:
            return
        if path.endswith(".json"):
            rec = self._json(path)
        elif path.endswith(".pb"):
            rec = self._binary_pb(path)
        else:
            rec = self._text(path)
        if rec is not None:
            yield rec

    def _json(self, path: str):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                data = json.load(fh)
        except Exception:
            return None
        text = json.dumps(data, ensure_ascii=False, indent=1)
        return self._rec(path, text, CONVERSATION, "json")

    def _text(self, path: str):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        except OSError:
            return None
        # .pbtxt: keep the quoted string values, which hold the human text
        if path.endswith(".pbtxt"):
            strings = re.findall(r'"((?:[^"\\]|\\.){4,})"', raw)
            text = "\n".join(strings) if strings else raw
        else:
            text = raw
        return self._rec(path, text, DOCUMENT, "pbtxt/text")

    def _binary_pb(self, path: str):
        try:
            with open(path, "rb") as fh:
                blob = fh.read(self.MAX_BYTES)
        except OSError:
            return None
        decoded = blob.decode("utf-8", "ignore")
        runs = [r.strip() for r in _PRINTABLE.findall(decoded)]
        # keep substantive runs; drop short proto field-name fragments
        text = "\n".join(r for r in runs if len(r) >= 6)
        if len(text.strip()) < 20:
            return None
        return self._rec(path, text, CONVERSATION, "protobuf-binary (strings-extracted)")

    def _rec(self, path: str, text: str, kind: str, fmt: str):
        if not text.strip():
            return None
        return Record(
            record_id=make_id(self.name, path, 0), source=self.name,
            source_path=path, kind=kind, title=os.path.basename(path),
            text=text, created_at=mtime_iso(path),
            metadata={"format": fmt, "confidence": "low"},
        )
