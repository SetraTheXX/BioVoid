"""Content-addressed cache for completed BioVoid analysis cores."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import PATHS


DEFAULT_CACHE_DIR = PATHS.cache
CACHE_SCHEMA_VERSION = "analysis-core-cache-v2"
_HASH_FIELDS = (
    "raw_input_sha256",
    "prepared_structure_sha256",
    "preparation_config_sha256",
    "detector_config_sha256",
    "motion_config_sha256",
    "model_sha256",
    "code_identity_sha256",
    "environment_identity_sha256",
)


class CacheWriteError(RuntimeError):
    """Raised when a completed cache entry cannot be written atomically."""


def hash_cache_payload(payload: Any) -> str:
    """Return a deterministic SHA-256 for JSON-compatible cache identity data."""
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def hash_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_code_identity(project_root: str | Path | None = None) -> str:
    """Hash executable Python sources, including dirty local changes."""
    root = (
        Path(project_root).resolve()
        if project_root is not None
        else Path(__file__).resolve().parents[1]
    )
    paths = sorted((root / "src").rglob("*.py"))
    paths.extend(path for path in (root / "main.py", root / "main_parallel.py") if path.is_file())
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def environment_manifest(project_root: str | Path | None = None) -> dict[str, Any]:
    """Return the inspectable runtime identity used by scientific cache keys."""
    packages = (
        "biopython",
        "biotite",
        "numpy",
        "scipy",
        "scikit-learn",
        "pandas",
        "pydantic",
        "fastapi",
        "starlette",
    )
    versions: dict[str, str] = {}
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "unavailable"

    root = (
        Path(project_root).resolve()
        if project_root is not None
        else Path(__file__).resolve().parents[1]
    )
    lock_path = root / "requirements-lock.txt"
    lock_sha256 = (
        hashlib.sha256(lock_path.read_bytes()).hexdigest() if lock_path.is_file() else None
    )
    return {
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "dependencies": versions,
        "dependency_lock": lock_path.name if lock_sha256 else None,
        "dependency_lock_sha256": lock_sha256,
    }


def compute_environment_identity(project_root: str | Path | None = None) -> str:
    """Hash the runtime, dependency versions, and lock-file identity."""
    return hash_cache_payload(environment_manifest(project_root))


@dataclass(frozen=True)
class CacheIdentity:
    """Complete scientific and executable identity for one cached analysis core."""

    source_identifier: str
    raw_input_sha256: str
    prepared_structure_sha256: str
    preparation_config_sha256: str
    detector_config_sha256: str
    motion_config_sha256: str
    model_sha256: str
    code_identity_sha256: str
    environment_identity_sha256: str
    benchmark_cache_policy: str = "not_benchmark"
    schema_version: str = CACHE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.source_identifier.strip():
            raise ValueError("source_identifier is required")
        for field_name in _HASH_FIELDS:
            value = getattr(self, field_name)
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
        if self.benchmark_cache_policy not in {
            "not_benchmark",
            "development_only",
            "sealed_read_only",
            "disabled",
        }:
            raise ValueError("Unsupported benchmark cache policy")

    def to_payload(self) -> dict[str, str]:
        return dict(sorted(asdict(self).items()))

    @property
    def key(self) -> str:
        return hash_cache_payload(self.to_payload())


class AnalysisCache:
    """Atomic content-addressed JSON cache with strict identity verification."""

    def __init__(self, cache_dir: str | Path = DEFAULT_CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._hits = 0
        self._misses = 0
        self._invalid = 0
        self.last_event: dict[str, Any] = {"status": "uninitialized"}

    def _path(self, identity: CacheIdentity) -> Path:
        return self.cache_dir / f"{identity.key}.json"

    def get(
        self,
        identity: CacheIdentity,
        *,
        max_age_hours: float = 168.0,
    ) -> dict[str, Any] | None:
        """Return only a complete, untampered entry with the exact requested identity."""
        if identity.benchmark_cache_policy == "disabled":
            self._misses += 1
            self.last_event = {
                "status": "disabled",
                "key": identity.key,
                "reason": "benchmark_cache_disabled",
            }
            return None
        path = self._path(identity)
        if not path.is_file():
            self._misses += 1
            self.last_event = {"status": "miss", "key": identity.key, "reason": "not_found"}
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            age_hours = (time.time() - float(entry["cached_at_unix"])) / 3600.0
            result = entry["result"]
            valid = (
                entry["schema_version"] == CACHE_SCHEMA_VERSION
                and entry["cache_key"] == identity.key
                and entry["identity"] == identity.to_payload()
                and entry["completion_status"] == "complete"
                and entry["result_sha256"] == hash_cache_payload(result)
                and age_hours <= max_age_hours
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
            valid = False
            age_hours = 0.0
        if not valid:
            self._invalid += 1
            self._misses += 1
            self.last_event = {
                "status": "invalid",
                "key": identity.key,
                "reason": "identity_payload_or_expiry_mismatch",
            }
            return None
        self._hits += 1
        self.last_event = {
            "status": "hit",
            "key": identity.key,
            "age_hours": round(age_hours, 6),
        }
        return result

    def put(self, identity: CacheIdentity, result: dict[str, Any]) -> Path:
        """Atomically store one completed result; write failures are explicit."""
        if identity.benchmark_cache_policy in {"sealed_read_only", "disabled"}:
            raise CacheWriteError(
                "Cache writes are forbidden by benchmark policy "
                f"'{identity.benchmark_cache_policy}'"
            )
        path = self._path(identity)
        entry = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "cache_key": identity.key,
            "cached_at_unix": time.time(),
            "identity": identity.to_payload(),
            "completion_status": "complete",
            "result_sha256": hash_cache_payload(result),
            "result": result,
        }
        temporary = self.cache_dir / f".{identity.key}.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(
                json.dumps(entry, indent=2, sort_keys=True, default=str) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, path)
        except OSError as exc:
            if temporary.exists():
                temporary.unlink()
            raise CacheWriteError(f"Unable to write cache entry {identity.key}") from exc
        self.last_event = {"status": "stored", "key": identity.key}
        return path

    def invalidate(self, identity: CacheIdentity) -> bool:
        path = self._path(identity)
        if not path.exists():
            return False
        path.unlink()
        return True

    def invalidate_source(self, source_identifier: str) -> int:
        """Remove entries for one source by verified entry metadata."""
        normalized = source_identifier.upper().strip()
        removed = 0
        for path in self.cache_dir.glob("*.json"):
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
                source = str(entry.get("identity", {}).get("source_identifier", "")).upper()
            except (json.JSONDecodeError, OSError, TypeError):
                continue
            if source == normalized:
                path.unlink()
                removed += 1
        return removed

    def clear(self) -> int:
        count = 0
        for path in self.cache_dir.glob("*.json"):
            path.unlink()
            count += 1
        return count

    def stats(self) -> dict[str, Any]:
        entries = list(self.cache_dir.glob("*.json"))
        total_bytes = sum(path.stat().st_size for path in entries)
        return {
            "schema_version": CACHE_SCHEMA_VERSION,
            "entries": len(entries),
            "size_mb": round(total_bytes / (1024 * 1024), 2),
            "hits": self._hits,
            "misses": self._misses,
            "invalid": self._invalid,
            "hit_rate": round(self._hits / max(1, self._hits + self._misses), 4),
        }
