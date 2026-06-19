"""Source discovery + noise filtering.

Local AI-tool folders are mostly noise: plugin caches, extensions, vendored
deps, worktrees, GPU caches. Naively indexing them produces a huge, useless
index. The walker here aggressively skips that noise while staying overridable.
"""
from __future__ import annotations

import os
from typing import Iterator, List, Optional, Sequence

# Whole path segments that mean "vendor / cache / not user knowledge".
SEGMENT_IGNORES = frozenset({
    "node_modules", ".git", ".hg", ".svn",
    "plugins", "extensions", "worktrees",
    "cache", "Cache", "Code Cache", "GPUCache", "DawnCache", "ShaderCache",
    "__pycache__", ".pytest_cache", ".mypy_cache",
    "vendor", "vendor_imports", "dist", "build", ".next", ".turbo",
    "tmp", ".tmp", "temp", "Crashpad", "logs-archive",
    "computer-use", "shell-snapshots", "statsig", "paste-cache",
    "CachedData", "CachedExtensions", "CachedProfilesData",
    "site-packages", ".vscode", "Service Worker", "IndexedDB",
    "Local Storage", "Session Storage", "blob_storage",
})

# Never index credentials, even with --no-default-ignores. Safety first.
SENSITIVE_NAMES = frozenset({
    "auth.json", "credentials.json", "secrets.json", "token.json",
    ".env", ".netrc", "id_rsa", "id_ed25519",
})
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".keychain")

# Substrings anywhere in the path that mark noise (for non-segment cases).
SUBSTR_IGNORES = (
    "/Code Cache/", "/GPUCache/", "/Service Worker/", "/IndexedDB/",
    "/blob_storage/", "/Local Storage/", "/Session Storage/",
)

# Binary / non-text extensions the generic adapter should never read as text.
BINARY_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".svg",
    ".pdf", ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".mp3", ".wav", ".m4a",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".wasm", ".node", ".dylib", ".so", ".dll", ".a", ".o", ".bin",
    ".map", ".lock", ".pack", ".idx", ".pyc", ".class", ".jar",
    ".db-wal", ".db-shm",
})


class Walker:
    """Yields candidate files under roots, honoring ignore rules."""

    def __init__(
        self,
        use_default_ignores: bool = True,
        extra_ignores: Optional[Sequence[str]] = None,
        includes: Optional[Sequence[str]] = None,
        index_dir: Optional[str] = None,
    ):
        self.use_default = use_default_ignores
        self.extra = tuple(extra_ignores or ())
        self.includes = tuple(includes or ())
        self.index_dir = os.path.abspath(index_dir) if index_dir else None
        self.skipped = 0
        self.seen = 0

    def _included(self, path: str) -> bool:
        if not self.includes:
            return False
        from fnmatch import fnmatch
        return any(fnmatch(path, pat) or pat in path for pat in self.includes)

    def _ignored(self, path: str) -> bool:
        if self._included(path):
            return False
        base = os.path.basename(path)
        if (base in SENSITIVE_NAMES or base.startswith(".env")
                or base.endswith(SENSITIVE_SUFFIXES)):
            return True  # credentials: skipped regardless of ignore settings
        if self.index_dir and os.path.abspath(path).startswith(self.index_dir):
            return True
        if not self.use_default:
            return any(frag in path for frag in self.extra)
        parts = set(path.split(os.sep))
        if parts & SEGMENT_IGNORES:
            return True
        if any(sub in path for sub in SUBSTR_IGNORES):
            return True
        if any(frag in path for frag in self.extra):
            return True
        return False

    def walk(self, root: str) -> Iterator[str]:
        root = os.path.abspath(os.path.expanduser(root))
        if os.path.isfile(root):
            self.seen += 1
            yield root
            return
        for dirpath, dirnames, filenames in os.walk(root):
            # prune ignored directories in place (huge speedup on plugin trees)
            kept = []
            for d in dirnames:
                full = os.path.join(dirpath, d)
                if self._ignored(full):
                    self.skipped += 1
                else:
                    kept.append(d)
            dirnames[:] = kept
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                self.seen += 1
                if self._ignored(full):
                    self.skipped += 1
                    continue
                yield full


def expand_roots(roots: Sequence[str]) -> List[str]:
    return [os.path.abspath(os.path.expanduser(r)) for r in roots]


def detect_label(root: str) -> str:
    """Human label for a root, for the scan report."""
    r = os.path.abspath(os.path.expanduser(root))
    base = os.path.basename(r.rstrip(os.sep))
    if base == ".claude":
        return "Claude Code workspace"
    if base == ".codex":
        return "Codex workspace"
    if base == ".cursor":
        return "Cursor workspace"
    if base == ".antigravity":
        return "Antigravity workspace"
    if os.path.isfile(r) or os.path.isdir(r):
        if os.path.exists(os.path.join(r, "conversations.json")):
            return "Claude.ai export"
        if r.endswith(".zip"):
            return "export archive (zip)"
    return "folder"
