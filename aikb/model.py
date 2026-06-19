"""The normalized record — the single shape every adapter emits.

Adapters turn wildly different sources (Claude export JSON, Claude Code
JSONL, Codex SQLite, loose Markdown) into a stream of `Record`s. Everything
downstream — indexing, search, topic matching, export — speaks only Record.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# ── Record kinds ──────────────────────────────────────────────────────────
CONVERSATION = "conversation"
MESSAGE = "message"
MEMORY = "memory"
PROJECT = "project"
PLAN = "plan"
TASK = "task"
TERMINAL_LOG = "terminal_log"
ATTACHMENT = "attachment"
DOCUMENT = "document"
CONFIG = "config"
TOOL_RESULT = "tool_result"

KINDS = frozenset({
    CONVERSATION, MESSAGE, MEMORY, PROJECT, PLAN, TASK,
    TERMINAL_LOG, ATTACHMENT, DOCUMENT, CONFIG, TOOL_RESULT,
})

# Structural confidence by kind — conversations/messages from a known adapter
# are worth more than a loose generic document when ranking topic matches.
STRUCTURAL_WEIGHT = {
    CONVERSATION: 1.0,
    MESSAGE: 1.0,
    MEMORY: 0.9,
    PROJECT: 0.9,
    PLAN: 0.8,
    TASK: 0.8,
    TERMINAL_LOG: 0.6,
    ATTACHMENT: 0.6,
    TOOL_RESULT: 0.5,
    DOCUMENT: 0.5,
    CONFIG: 0.3,
}


@dataclass
class Record:
    record_id: str          # stable, source-prefixed, e.g. "claude-export:66dfae38:msg-4"
    source: str             # adapter name, e.g. "claude-export"
    source_path: str        # absolute path the record came from
    kind: str               # one of KINDS
    text: str               # normalized searchable text
    title: str = ""
    locator: str = ""       # message uuid / line number / json pointer for provenance
    created_at: Optional[str] = None   # ISO-8601 if known
    updated_at: Optional[str] = None
    participant: str = ""   # role / sender (user, assistant, system, ...)
    parent_id: Optional[str] = None
    project: str = ""       # project / workspace this belongs to, if known
    metadata: Dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""

    def finalize(self) -> "Record":
        if not self.content_hash:
            h = hashlib.sha1()
            h.update((self.text or "").encode("utf-8", "replace"))
            self.content_hash = h.hexdigest()[:16]
        if self.kind not in KINDS:
            self.kind = DOCUMENT
        return self


def short_hash(s: str, n: int = 8) -> str:
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:n]


def make_id(source: str, path: str, ordinal: Any) -> str:
    """Fallback id for records without a natural key (uuid)."""
    return f"{source}:{short_hash(path)}:{ordinal}"
