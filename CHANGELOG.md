# Changelog

## 0.2.0

**Added**
- `aikb coverage <index>`: every conversation that no topic claims as a high- or medium-confidence match (directly or through one of its messages), counted by month, with suggested terms for the next topic. Suggestions must be at least twice as common in the leftovers as in claimed conversations, so everyday words are filtered out.
- CI on GitHub Actions: Python 3.9, 3.11 and 3.13 on Ubuntu, plus 3.13 on macOS.
- Tests for coverage, timeline, and the matching rules topic packs depend on (whole-word short terms, fuzzy long terms, confidence buckets, term suggestions).

**Changed**
- `aikb timeline` now shows the whole history by default; it used to stop silently at 300 entries. `--limit N` still caps it.
- Term suggestions strip sentence punctuation ("expected." becomes "expected") and keep dotted names like `node.js`.

## 0.1.0

First release: scan, index, search, topic packs (create, review, terms, export) and timeline across Claude, Claude Code, Codex, Cursor, Gemini and generic files.
