"""Content-addressed disk cache.

Keys are derived from the PDF's own bytes, so the same document always lands on
the same entry no matter what it was called or where it came from. Two things are
cached: whole extraction payloads, and individual OCR'd pages. The second matters
most — OCR is the only part of the pipeline that costs money per page, and caching
it per page means changing a page range re-reads instead of re-paying.
"""

import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

MODULE_DIR = Path(__file__).resolve().parent
TRUTHY = {"1", "true", "yes", "on"}

READ_CHUNK = 1024 * 1024


def enabled() -> bool:
    return os.getenv("CACHE_ENABLED", "true").strip().lower() in TRUTHY


def cache_dir() -> Path:
    configured = os.getenv("CACHE_DIR", "").strip()
    return Path(configured) if configured else MODULE_DIR.parent / ".cache"


def max_bytes() -> int:
    return int(os.getenv("CACHE_MAX_MB", "512")) * 1024 * 1024


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            chunk = f.read(READ_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def bytes_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def make_key(*parts: Any) -> str:
    """Stable key from any JSON-serialisable parts."""
    blob = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _path_for(key: str) -> Path:
    # Shard on the first two characters so one directory never holds everything.
    return cache_dir() / key[:2] / f"{key}.json"


def get(key: str) -> Optional[Any]:
    if not enabled():
        return None
    path = _path_for(key)
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    # Touch for the LRU sweep; failure here is not worth failing the read over.
    try:
        os.utime(path, None)
    except OSError:
        pass
    return payload


def put(key: str, value: Any) -> None:
    if not enabled():
        return
    path = _path_for(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a sibling temp file and rename, so a concurrent reader never
        # sees a half-written entry.
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
    except OSError as exc:
        logger.warning("Could not write cache entry %s: %s", key[:12], exc)


def sweep() -> None:
    """Drop the least recently used entries once the cache outgrows its budget."""
    if not enabled():
        return
    budget = max_bytes()
    root = cache_dir()
    if not root.exists():
        return

    try:
        entries = []
        total = 0
        for path in root.rglob("*.json"):
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size

        if total <= budget:
            return

        entries.sort()  # oldest access first
        for _, size, path in entries:
            if total <= budget:
                break
            try:
                path.unlink()
                total -= size
            except OSError:
                continue
    except OSError as exc:
        logger.warning("Cache sweep failed: %s", exc)


def stats() -> dict:
    root = cache_dir()
    if not enabled() or not root.exists():
        return {"enabled": enabled(), "entries": 0, "bytes": 0}
    entries = 0
    total = 0
    for path in root.rglob("*.json"):
        try:
            total += path.stat().st_size
            entries += 1
        except OSError:
            continue
    return {"enabled": True, "entries": entries, "bytes": total}


def clear() -> int:
    """Remove every entry. Returns how many were deleted."""
    root = cache_dir()
    if not root.exists():
        return 0
    removed = 0
    for path in root.rglob("*.json"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def now_ms() -> int:
    return int(time.time() * 1000)
