"""Tiny zero-dependency terminal styling. Respects NO_COLOR and non-TTY pipes."""
from __future__ import annotations

import os
import sys

_ENABLED = (
    sys.stdout.isatty()
    and os.environ.get("NO_COLOR") is None
    and os.environ.get("TERM") != "dumb"
)


def disable() -> None:
    global _ENABLED
    _ENABLED = False


def _wrap(code: str):
    def fn(s: str) -> str:
        if not _ENABLED:
            return s
        return f"\x1b[{code}m{s}\x1b[0m"

    return fn


bold = _wrap("1")
dim = _wrap("2")
italic = _wrap("3")
red = _wrap("31")
green = _wrap("32")
yellow = _wrap("33")
blue = _wrap("34")
magenta = _wrap("35")
cyan = _wrap("36")
grey = _wrap("90")


# Confidence bucket -> color
_CONF = {
    "high": green,
    "medium": yellow,
    "buried": magenta,
    "false": grey,
}


def confidence(bucket: str, text: str) -> str:
    return _CONF.get(bucket, lambda s: s)(text)


def header(title: str) -> str:
    return bold(cyan(title))


def rule(char: str = "─", width: int = 60) -> str:
    return dim(char * width)


def kv(label: str, value, width: int = 18) -> str:
    return f"  {dim(label.ljust(width))} {value}"


def count(n: int) -> str:
    return f"{n:,}"
