"""SQLite + FTS5 index. The only persistence layer AIKB uses.

One index = one directory containing `aikb.db`. The DB holds normalized
records, a full-text index over them, scanned-source bookkeeping, and saved
topic definitions.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Dict, Iterable, Iterator, List, Optional

from .model import Record

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    rowid        INTEGER PRIMARY KEY,
    record_id    TEXT UNIQUE NOT NULL,
    source       TEXT NOT NULL,
    source_path  TEXT NOT NULL,
    kind         TEXT NOT NULL,
    title        TEXT,
    text         TEXT,
    locator      TEXT,
    created_at   TEXT,
    updated_at   TEXT,
    participant  TEXT,
    parent_id    TEXT,
    project      TEXT,
    metadata     TEXT,
    content_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_source  ON records(source);
CREATE INDEX IF NOT EXISTS idx_records_kind    ON records(kind);
CREATE INDEX IF NOT EXISTS idx_records_project ON records(project);
CREATE INDEX IF NOT EXISTS idx_records_created ON records(created_at);
CREATE INDEX IF NOT EXISTS idx_records_hash    ON records(content_hash);

CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
    title, text,
    content='records', content_rowid='rowid',
    tokenize="unicode61 remove_diacritics 2"
);

CREATE TABLE IF NOT EXISTS sources (
    path       TEXT PRIMARY KEY,
    adapter    TEXT,
    size       INTEGER,
    mtime      REAL,
    status     TEXT,
    n_records  INTEGER DEFAULT 0,
    error      TEXT
);

CREATE TABLE IF NOT EXISTS topics (
    name        TEXT PRIMARY KEY,
    definition  TEXT NOT NULL,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def fts_or_query(terms: Iterable[str]) -> str:
    """Build a safe FTS5 OR query from raw user terms.

    Each term is double-quoted, which makes FTS treat multi-word terms as
    phrases and neutralizes punctuation/operators the user might type.
    """
    return _fts_join(terms, " OR ")


def fts_and_query(terms: Iterable[str]) -> str:
    """Build a safe FTS5 query where every term must appear (implicit AND)."""
    return _fts_join(terms, " ")


def _fts_join(terms: Iterable[str], op: str) -> str:
    parts = []
    for t in terms:
        t = (t or "").strip().replace('"', '""')
        if t:
            parts.append(f'"{t}"')
    return op.join(parts)


class Index:
    def __init__(self, path: str):
        self.dir = os.path.abspath(path)
        self.db_path = os.path.join(self.dir, "aikb.db")
        self._conn: Optional[sqlite3.Connection] = None

    # ── lifecycle ─────────────────────────────────────────────────────────
    def open(self, create: bool = False) -> "Index":
        if create:
            os.makedirs(self.dir, exist_ok=True)
        elif not os.path.exists(self.db_path):
            raise FileNotFoundError(
                f"No index at {self.dir} (missing aikb.db). Run `aikb index` first."
            )
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        if create:
            self._conn.executescript(_SCHEMA)
            self.set_meta("schema_version", str(SCHEMA_VERSION))
            self.set_meta("created_at", _now())
        return self

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Index not opened")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.commit()
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Index":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── meta ──────────────────────────────────────────────────────────────
    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    # ── records ───────────────────────────────────────────────────────────
    def add_record(self, r: Record) -> None:
        r.finalize()
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO records("
            "record_id, source, source_path, kind, title, text, locator,"
            "created_at, updated_at, participant, parent_id, project, metadata, content_hash"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r.record_id, r.source, r.source_path, r.kind, r.title, r.text, r.locator,
                r.created_at, r.updated_at, r.participant, r.parent_id, r.project,
                json.dumps(r.metadata, ensure_ascii=False), r.content_hash,
            ),
        )
        if cur.rowcount:
            self.conn.execute(
                "INSERT INTO records_fts(rowid, title, text) VALUES(?,?,?)",
                (cur.lastrowid, r.title or "", r.text or ""),
            )

    def record_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]

    def counts_by(self, column: str) -> List[sqlite3.Row]:
        if column not in ("source", "kind", "project"):
            raise ValueError(column)
        return self.conn.execute(
            f"SELECT {column} AS k, COUNT(*) AS n FROM records GROUP BY {column} ORDER BY n DESC"
        ).fetchall()

    def get_record(self, record_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM records WHERE record_id=?", (record_id,)
        ).fetchone()

    def iter_records(self) -> Iterator[sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM records")
        for row in cur:
            yield row

    # ── search ────────────────────────────────────────────────────────────
    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        sql = (
            "SELECT r.record_id, r.title, r.source, r.source_path, r.kind, "
            "r.created_at, r.project, r.participant, "
            "snippet(records_fts, 1, '〈', '〉', ' … ', 12) AS snippet, "
            "bm25(records_fts) AS score "
            "FROM records_fts JOIN records r ON r.rowid = records_fts.rowid "
            "WHERE records_fts MATCH ? ORDER BY score LIMIT ?"
        )
        out = []
        for row in self.conn.execute(sql, (query, limit)):
            out.append(dict(row))
        return out

    def raw_fts(self, query: str, limit: int = 5000) -> List[sqlite3.Row]:
        """Lower-level match used by the topic engine: returns rows + bm25."""
        sql = (
            "SELECT r.*, bm25(records_fts) AS score "
            "FROM records_fts JOIN records r ON r.rowid = records_fts.rowid "
            "WHERE records_fts MATCH ? ORDER BY score LIMIT ?"
        )
        return self.conn.execute(sql, (query, limit)).fetchall()

    # ── sources bookkeeping ───────────────────────────────────────────────
    def record_source(self, path: str, adapter: str, size: int, mtime: float,
                       status: str, n_records: int, error: str = "") -> None:
        self.conn.execute(
            "INSERT INTO sources(path, adapter, size, mtime, status, n_records, error) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET "
            "adapter=excluded.adapter, size=excluded.size, mtime=excluded.mtime, "
            "status=excluded.status, n_records=excluded.n_records, error=excluded.error",
            (path, adapter, size, mtime, status, n_records, error),
        )

    def source_hash(self, path: str) -> Optional[float]:
        row = self.conn.execute("SELECT mtime FROM sources WHERE path=?", (path,)).fetchone()
        return row["mtime"] if row else None

    def get_source(self, path: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT mtime, size, status FROM sources WHERE path=?", (path,)
        ).fetchone()

    # ── topics ────────────────────────────────────────────────────────────
    def save_topic(self, name: str, definition: Dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO topics(name, definition, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET definition=excluded.definition, "
            "updated_at=excluded.updated_at",
            (name, json.dumps(definition, ensure_ascii=False), _now()),
        )
        self.conn.commit()

    def get_topic(self, name: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT definition FROM topics WHERE name=?", (name,)).fetchone()
        return json.loads(row["definition"]) if row else None

    def list_topics(self) -> List[str]:
        return [r["name"] for r in self.conn.execute("SELECT name FROM topics ORDER BY name")]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
