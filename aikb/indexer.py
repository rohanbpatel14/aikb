"""Orchestration: walk roots -> route each file to an adapter -> store records."""
from __future__ import annotations

import os
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

from .adapters import default_adapters, route
from .db import Index
from .sources import Walker
from .util import redact_secrets


@dataclass
class ScanResult:
    files_seen: int = 0
    files_skipped: int = 0
    matched: int = 0
    by_adapter: Counter = field(default_factory=Counter)  # adapter -> file count


def scan(roots: Sequence[str], walker: Optional[Walker] = None) -> ScanResult:
    """Dry run: report what would be indexed without parsing file bodies."""
    walker = walker or Walker()
    adapters = default_adapters()
    res = ScanResult()
    for root in roots:
        for path in walker.walk(root):
            a = route(path, adapters)
            if a:
                res.by_adapter[a.name] += 1
                res.matched += 1
    res.files_seen = walker.seen
    res.files_skipped = walker.skipped
    return res


@dataclass
class IndexResult:
    files_indexed: int = 0
    files_unchanged: int = 0
    files_error: int = 0
    records: int = 0
    files_seen: int = 0
    files_skipped: int = 0
    by_adapter: Counter = field(default_factory=Counter)  # adapter -> record count
    errors: List[Tuple[str, str]] = field(default_factory=list)


def build_index(
    index_dir: str,
    roots: Sequence[str],
    walker: Optional[Walker] = None,
    on_file: Optional[Callable[[int, str, str], None]] = None,
    force: bool = False,
) -> IndexResult:
    walker = walker or Walker(index_dir=index_dir)
    adapters = default_adapters()
    res = IndexResult()
    idx = Index(index_dir).open(create=True)
    idx.set_meta("roots", "\n".join(roots))
    try:
        i = 0
        for root in roots:
            for path in walker.walk(root):
                a = route(path, adapters)
                if a is None:
                    continue
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                # Incremental: skip files unchanged since the last index.
                if not force:
                    prev = idx.get_source(path)
                    if (prev and prev["status"] == "ok"
                            and prev["mtime"] == st.st_mtime and prev["size"] == st.st_size):
                        res.files_unchanged += 1
                        continue
                try:
                    n = 0
                    for rec in a.parse(path):
                        rec.text = redact_secrets(rec.text)
                        idx.add_record(rec)
                        n += 1
                    idx.record_source(path, a.name, st.st_size, st.st_mtime, "ok", n)
                    res.files_indexed += 1
                    res.records += n
                    res.by_adapter[a.name] += n
                except Exception as e:  # one bad file must not abort the run
                    res.files_error += 1
                    res.errors.append((path, str(e)))
                    idx.record_source(path, a.name, st.st_size, st.st_mtime,
                                      "error", 0, str(e)[:200])
                i += 1
                if on_file:
                    on_file(i, path, a.name)
                if i % 200 == 0:
                    idx.conn.commit()
        idx.set_meta("record_count", str(res.records))
        idx.set_meta("indexed_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    finally:
        idx.close()
    res.files_seen = walker.seen
    res.files_skipped = walker.skipped
    return res
