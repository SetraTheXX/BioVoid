"""
Bio-Void Hunter: Analysis Caching
====================================

File-based cache for analysis results. Avoids re-running
expensive NMA/scoring for already-analyzed proteins.

Cache key: hash of (pdb_id, n_frames, profile, version)
Storage: JSON files in cache directory
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/.cache")
CACHE_VERSION = 1


def _build_cache_key(
    pdb_id: str,
    n_frames: int = 50,
    profile: str = "default",
) -> str:
    raw = f"{pdb_id.upper()}|{n_frames}|{profile}|v{CACHE_VERSION}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class AnalysisCache:
    """File-based analysis result cache."""

    def __init__(self, cache_dir: str | Path = DEFAULT_CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._hits = 0
        self._misses = 0

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(
        self,
        pdb_id: str,
        n_frames: int = 50,
        profile: str = "default",
        max_age_hours: float = 168.0,
    ) -> dict[str, Any] | None:
        """
        Retrieve cached result. Returns None on miss or expired entry.
        Default max_age: 7 days.
        """
        key = _build_cache_key(pdb_id, n_frames, profile)
        path = self._path(key)

        if not path.exists():
            self._misses += 1
            return None

        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            self._misses += 1
            return None

        cached_at = data.get("_cached_at", 0)
        age_hours = (time.time() - cached_at) / 3600.0
        if age_hours > max_age_hours:
            logger.debug("Cache expired for %s (%.1f hours old)", pdb_id, age_hours)
            self._misses += 1
            return None

        self._hits += 1
        logger.debug("Cache hit for %s (key=%s)", pdb_id, key)
        return data.get("result")

    def put(
        self,
        pdb_id: str,
        result: dict[str, Any],
        n_frames: int = 50,
        profile: str = "default",
    ) -> None:
        """Store analysis result in cache."""
        key = _build_cache_key(pdb_id, n_frames, profile)
        path = self._path(key)

        entry = {
            "_cached_at": time.time(),
            "_pdb_id": pdb_id.upper(),
            "_n_frames": n_frames,
            "_profile": profile,
            "_cache_version": CACHE_VERSION,
            "result": result,
        }

        try:
            path.write_text(json.dumps(entry, indent=2, default=str))
            logger.debug("Cached result for %s (key=%s)", pdb_id, key)
        except OSError as e:
            logger.warning("Failed to write cache for %s: %s", pdb_id, e)

    def invalidate(self, pdb_id: str, n_frames: int = 50, profile: str = "default"):
        """Remove a specific cache entry."""
        key = _build_cache_key(pdb_id, n_frames, profile)
        path = self._path(key)
        if path.exists():
            path.unlink()
            logger.debug("Invalidated cache for %s", pdb_id)

    def clear(self) -> int:
        """Remove all cache entries. Returns count of removed files."""
        count = 0
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
            count += 1
        logger.info("Cleared %d cache entries", count)
        return count

    def stats(self) -> dict[str, Any]:
        """Cache statistics."""
        entries = list(self.cache_dir.glob("*.json"))
        total_bytes = sum(f.stat().st_size for f in entries)
        return {
            "entries": len(entries),
            "size_mb": round(total_bytes / (1024 * 1024), 2),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / max(1, self._hits + self._misses), 4),
        }
