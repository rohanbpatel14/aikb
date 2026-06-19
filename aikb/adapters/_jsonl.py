"""Shared helpers for the many JSONL transcript formats AIKB ingests.

Claude Code, Codex, and Cursor all log conversations as line-delimited JSON,
but with different envelopes. These helpers normalize the *content* shape
(string vs. list-of-typed-blocks) that they have in common.
"""
from __future__ import annotations

import json
from typing import Any, Iterator, Tuple


def iter_jsonl(path: str) -> Iterator[Tuple[int, dict]]:
    """Yield (line_number, parsed_obj) for each valid JSON line. Bad lines skipped."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                yield i, obj


def content_to_text(content: Any, include_tool_io: bool = False, cap: int = 2000) -> str:
    """Flatten a message `content` (str or list of blocks) into searchable text.

    By default tool *calls* and *results* are dropped: file paths, shell
    commands, and command output are mechanical noise that bloats the index and
    drowns the actual knowledge (the human/assistant dialogue and reasoning).
    Pass include_tool_io=True for an archival, everything-included flatten.
    """
    include_tool_results = include_tool_io
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return _block_text(content, include_tool_results, cap)
    if isinstance(content, list):
        parts = [_block_text(b, include_tool_results, cap) for b in content]
        return "\n".join(p for p in parts if p)
    return str(content)


def _block_text(b: Any, include_tool_results: bool, cap: int) -> str:
    if not isinstance(b, dict):
        return str(b)
    t = b.get("type")
    if t in ("text", "input_text", "output_text"):
        return b.get("text", "")
    if t == "thinking":
        return b.get("thinking") or b.get("text") or ""
    if t == "tool_use":
        inp = json.dumps(b.get("input", {}), ensure_ascii=False)
        return f"[tool:{b.get('name', '?')}] {inp[:cap]}"
    if t == "tool_result":
        if not include_tool_results:
            return ""
        c = b.get("content", "")
        if isinstance(c, list):
            c = " ".join(
                x.get("text", "") if isinstance(x, dict) else str(x) for x in c
            )
        return str(c)[:cap]
    # Unknown block — probe common text-bearing keys.
    for k in ("text", "content", "value", "summary"):
        v = b.get(k)
        if isinstance(v, str):
            return v
    return ""


def first_nonempty(*vals):
    for v in vals:
        if v:
            return v
    return None


def probe_role_text(obj: dict):
    """Best-effort (role, text) extraction across unknown JSONL envelopes.

    Used by the Codex/Cursor adapters where the exact schema isn't pinned —
    we look in the obvious places (`message.role`, `role`, `type`) and flatten
    whatever content shape we find.
    """
    msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
    role = first_nonempty(msg.get("role"), obj.get("role"), obj.get("type"), "?")
    content = first_nonempty(
        msg.get("content"), obj.get("content"), msg.get("text"), obj.get("text")
    )
    text = content_to_text(content).strip()
    return str(role), text
