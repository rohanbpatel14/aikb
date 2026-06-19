from __future__ import annotations

from typing import List, Optional

from .base import Adapter
from .claude_code import ClaudeCodeAdapter
from .claude_export import ClaudeExportAdapter
from .codex import CodexAdapter
from .cursor import CursorAdapter
from .gemini import GeminiAdapter
from .generic import GenericAdapter

ADAPTER_CLASSES = [
    ClaudeCodeAdapter,
    ClaudeExportAdapter,
    CodexAdapter,
    CursorAdapter,
    GeminiAdapter,
    GenericAdapter,
]


def default_adapters() -> List[Adapter]:
    """Instantiate adapters in priority order (lowest priority number first)."""
    return sorted((cls() for cls in ADAPTER_CLASSES), key=lambda a: a.priority)


def route(path: str, adapters: List[Adapter]) -> Optional[Adapter]:
    """First adapter that claims this path wins; generic is the last resort."""
    for a in adapters:
        if a.handles(path):
            return a
    return None
