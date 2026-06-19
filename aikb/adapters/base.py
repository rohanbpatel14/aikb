from __future__ import annotations

from typing import Iterable

from ..model import Record


class Adapter:
    """A source adapter turns files into normalized Records.

    `handles` is a cheap path test; `parse` does the real work and may yield
    many records per file (e.g. one conversation file -> N message records).
    Lower `priority` wins when several adapters could handle a path.
    """

    name = "base"
    priority = 50

    def handles(self, path: str) -> bool:
        return False

    def parse(self, path: str) -> Iterable[Record]:
        return iter(())
