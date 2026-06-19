from __future__ import annotations

import os
import re
import time
from html.parser import HTMLParser

# Secret shapes redacted from indexed text (defense-in-depth on top of the
# file-level skip in sources.py). Conservative, high-signal patterns only.
_SECRET_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.I),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|access[_-]?token)\b\s*[:=]\s*\S+"),
)


def redact_secrets(text: str) -> str:
    if not text:
        return text
    for pat in _SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def strip_html(s: str) -> str:
    p = _Stripper()
    try:
        p.feed(s)
    except Exception:
        return s
    return "".join(p.parts)


def mtime_iso(path: str):
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(path)))
    except OSError:
        return None


def truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + " …"
