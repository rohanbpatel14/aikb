from __future__ import annotations

import os
from typing import Iterable

from ..model import DOCUMENT, Record, make_id
from ..sources import BINARY_EXTS
from ..util import mtime_iso, strip_html
from .base import Adapter

TEXT_EXTS = frozenset({
    ".txt", ".md", ".markdown", ".rst",
    ".json", ".jsonl", ".ndjson", ".csv", ".tsv",
    ".html", ".htm", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".rules", ".log",
})


class GenericAdapter(Adapter):
    """Fallback: index any text-like file as a single document.

    Lower structural confidence than the source-specific adapters, but it's
    what lets AIKB recover knowledge from arbitrary notes, READMEs, and dumps.
    """

    name = "generic"
    priority = 90
    MAX_BYTES = 2_000_000  # bigger text files are usually logs/dumps owned by a real adapter

    def handles(self, path: str) -> bool:
        ext = os.path.splitext(path)[1].lower()
        if ext in BINARY_EXTS:
            return False
        return ext in TEXT_EXTS

    def parse(self, path: str) -> Iterable[Record]:
        try:
            if os.path.getsize(path) > self.MAX_BYTES:
                return
        except OSError:
            return
        ext = os.path.splitext(path)[1].lower()
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        except OSError:
            return
        text = strip_html(raw) if ext in (".html", ".htm") else raw
        if not text.strip():
            return
        yield Record(
            record_id=make_id(self.name, path, 0),
            source=self.name,
            source_path=path,
            kind=DOCUMENT,
            title=os.path.basename(path),
            text=text,
            created_at=mtime_iso(path),
        )
