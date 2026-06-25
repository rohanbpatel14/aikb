# AIKB — Adapter Guide (adding a new source)

Adapters are the *only* part of AIKB that knows about a specific tool's format. Adding support for a new source — a ChatGPT export, a new agent, whatever — is one file. This guide walks the whole thing.

---

## The contract

An adapter implements two methods (`aikb/adapters/base.py`):

```python
class Adapter:
    name = "base"        # appears in results as the `source`
    priority = 50        # lower = checked first; generic is 90 (last resort)

    def handles(self, path: str) -> bool:    # cheap path test
        ...
    def parse(self, path: str) -> Iterable[Record]:   # the real work
        ...
```

- `handles` must be **fast** (string checks on the path) — it runs for every file.
- `parse` may yield **many** records per file (e.g. one conversation file → one `conversation` record + N `message` records).
- Anything `parse` raises is caught by the indexer and logged per-file; one bad file never aborts a run.

---

## Step-by-step: a ChatGPT export adapter

ChatGPT exports are a `conversations.json` array; each conversation has a `mapping` of message nodes. Here's a complete, registered adapter.

**1. Create `aikb/adapters/chatgpt_export.py`:**

```python
from __future__ import annotations
import json, os
from typing import Iterable
from ..model import CONVERSATION, MESSAGE, Record, short_hash
from .base import Adapter

class ChatGPTExportAdapter(Adapter):
    name = "chatgpt-export"
    priority = 10                      # specific formats beat generic (90)

    def handles(self, path: str) -> bool:
        return os.path.basename(path) == "conversations.json" and self._looks_like_chatgpt(path)

    def _looks_like_chatgpt(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(2000)
            return '"mapping"' in head            # ChatGPT-specific key
        except OSError:
            return False

    def parse(self, path: str) -> Iterable[Record]:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return
        for conv in data if isinstance(data, list) else []:
            cid = conv.get("conversation_id") or conv.get("id") or short_hash(str(conv)[:200])
            title = conv.get("title") or "(untitled)"
            n = 0
            for node in (conv.get("mapping") or {}).values():
                msg = (node or {}).get("message")
                if not isinstance(msg, dict):
                    continue
                parts = ((msg.get("content") or {}).get("parts")) or []
                text = "\n".join(p for p in parts if isinstance(p, str)).strip()
                if not text:
                    continue
                role = (msg.get("author") or {}).get("role", "")
                n += 1
                yield Record(
                    record_id=f"chatgpt-export:{cid}:{msg.get('id', n)}",
                    source=self.name, source_path=path, kind=MESSAGE,
                    text=text, participant=role, locator=str(msg.get("id", n)),
                    parent_id=f"chatgpt-export:{cid}",
                )
            yield Record(
                record_id=f"chatgpt-export:{cid}", source=self.name, source_path=path,
                kind=CONVERSATION, text=title, title=title[:120],
                metadata={"messages": n},
            )
```

**2. Register it in `aikb/adapters/__init__.py`:**

```python
from .chatgpt_export import ChatGPTExportAdapter
ADAPTER_CLASSES = [
    ClaudeCodeAdapter, ClaudeExportAdapter, ChatGPTExportAdapter,
    CodexAdapter, CursorAdapter, GeminiAdapter, GenericAdapter,
]
```

That's it. `aikb index ~/Downloads/chatgpt-export --out ./idx` now works, and ChatGPT messages are searchable alongside every other tool.

---

## Patterns from the real adapters

- **One file → many records, conversation last.** Yield message records as you go, accumulate a count, yield the `conversation` record at the end (see `claude_code.py`, `claude_export.py`).
- **Normalize content with `content_to_text`** (`adapters/_jsonl.py`) when messages use the typed-block shape (`[{type:"text", ...}]`). It flattens text + reasoning and **drops tool calls/output by default** — keep that default; tool args are index noise.
- **Best-effort for messy formats.** Gemini stores protobuf; `gemini.py` recovers embedded strings and labels itself low-confidence rather than failing. Honest partial > silent garbage.
- **Use natural ids for provenance.** Prefer the source's own uuid (`claude-export:{conv}:{msg}`); fall back to `make_id(source, path, ordinal)` only when there's no natural key.
- **Set `project`** when the source knows it (Codex reads `cwd` from `session_meta`) — it powers project grouping and topic weighting.

---

## Routing & priority

`route(path, adapters)` returns the **first** adapter (sorted by ascending `priority`) whose `handles` is true. Specific adapters use `priority = 10`; `generic` uses `90` so it only catches files nothing else claimed. If two adapters could match the same path, give the more specific one a lower number.

---

## Testing your adapter

Drop a tiny fixture and assert it parses (mirror `tests/test_smoke.py`):

```python
import tempfile, os, json
from aikb.adapters.chatgpt_export import ChatGPTExportAdapter

def test_chatgpt_parses_messages():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "conversations.json")
        json.dump([{ "id":"c1","title":"Hi","mapping":{
            "n1":{"message":{"id":"m1","author":{"role":"user"},
                  "content":{"parts":["hello kafka"]}}}}}], open(p,"w"))
        recs = list(ChatGPTExportAdapter().parse(p))
    kinds = {r.kind for r in recs}
    assert "message" in kinds and "conversation" in kinds
    assert any("kafka" in r.text for r in recs)
```

Run: `PYTHONPATH=. python3 -m pytest tests/ -q` (or run the file directly).
