# AIKB — Walkthrough & Demos

Four end-to-end demos with real, representative output. Run them in order to learn the tool, or use them as a script for a knowledge-transfer / interview demo. Output below is from real runs on a multi-tool workstation.

> Setup once: `cd ~/Desktop/aikb && pip install -e .` (or add the shell function from the README). Then `aikb` is a command.

---

## Demo 1 — Index everything, search across tools

The headline: one search hits every tool at once, with provenance.

```bash
aikb doctor
aikb index ~/.claude ~/.codex ~/.cursor --out ~/aikb-idx
aikb search ~/aikb-idx "ruslana"
```

```text
aikb index
  files seen        796
  files skipped     15
  files indexed     561
  records           11,899
records by adapter:
    claude-code   5,223
    cursor        3,623
    codex         2,723
    generic         330
✓ index ready  ~/aikb-idx
```

```text
search: ruslana  (3 hits)

cursor:53709941-…:L41           message  cursor
  … /Downloads/〈ruslana〉_project_reconstruction/context-…
  /Users/…/.cursor/projects/…/agent-transcripts/…jsonl

codex:rollout-2026-04-03…:L1503  message  codex
  … Cannot find module './611.js' Require stack: …〈ruslana〉_project …
  /Users/…/.codex/sessions/2026/04/03/rollout-…jsonl
```

**What to point out:** one query, hits from **both Cursor and Codex**, each linked to the exact file and line. That cross-tool join is free because every adapter emits the same `Record`.

---

## Demo 2 — Topic pack: recover a project from fragments

You don't remember exact words — you remember fragments. Start there.

```bash
aikb topic create ~/aikb-idx apace --terms "Apace,elevator,GST,quote,RFQ,COP,LOP"
```

```text
Topic: apace
  high-confidence        529
  medium-confidence      201
  possible buried match  102
  likely false positive    0
Next: aikb topic review ~/aikb-idx apace
```

```bash
aikb topic terms ~/aikb-idx apace suggest     # forgotten themes to add
aikb topic review ~/aikb-idx apace            # confirm the uncertain ones
aikb topic export ~/aikb-idx apace --out ~/apace-pack --format all
aikb timeline ~/aikb-idx --topic apace
```

`~/apace-pack/` ends up with `README.md`, `timeline.md`, `records.csv`, `records.json`, `topic.json` — every line source-linked.

**What to point out:** `review` only asks about `medium`/`buried` candidates, and your include/exclude choices are saved into `topic.json` — so a re-run is *better*, not the same.

---

## Demo 3 — The "buried under the wrong title" recovery (the why)

This is the demo that explains why the tool exists. Exact search and even the AI vendor's own in-app search miss chats hidden under unrelated titles.

```bash
# Phrase search misses it; fuzzy/topic matching + boundary-aware terms find it:
aikb search ~/aikb-idx "immigration" --limit 3        # the misleading title
aikb topic create ~/aikb-idx apace --terms "Apace,COP,LOP,elevator,GST"
aikb topic review ~/aikb-idx apace                    # pin in the buried thread
```

In review you'll see candidates whose *title* is unrelated but whose *content* matches your terms. Press `i` to pin them in; they're now part of the topic forever. That single capability — recovering a real thread filed under the wrong name — is the founding use case.

---

## Demo 4 — Incremental re-index (it's cheap to stay fresh)

```bash
aikb index ~/.claude ~/.codex ~/.cursor --out ~/aikb-idx     # run again later
```

```text
  files seen        796
  files unchanged   981   incremental skip
  files indexed       4
  records           144
```

**What to point out:** the second run skipped ~all files (mtime+size unchanged, tracked in the `sources` table) and only re-parsed what changed. `--reindex` forces a full rebuild.

---

## Privacy demo (worth showing explicitly)

```bash
# auth.json / .env / *.pem are never indexed, even with default ignores off:
aikb index ~/.codex --out ~/aikb-idx --no-default-ignores
aikb search ~/aikb-idx "sk-"        # secret-shaped strings are redacted to [REDACTED]
```

The smoke test asserts this: `tests/test_smoke.py` plants an `auth.json` with a token and a message containing an `sk-…` key, then proves the credential file is never indexed and the key is redacted.

---

## Talking-track (for a live knowledge-transfer demo)

1. **Problem** (15s): "Thousands of chats across Claude, Codex, Cursor; the knowledge is buried and split." → Demo 1.
2. **The idea** (20s): "Start from fragments you remember, not exact words." → Demo 2.
3. **The proof** (20s): "It finds chats hidden under the wrong title." → Demo 3.
4. **The engineering** (20s): "Uniform Record → cross-tool search is free; incremental, zero-dependency, local-only, credentials never touched." → Demo 4 + privacy.

Total: ~90 seconds to show the whole thing working.
