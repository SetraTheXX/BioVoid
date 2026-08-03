"""
Bio-Void Hunter: Parallel Crawler & Orchestrator (Phase 5.1)
=============================================================

High-throughput parallel processing of PDB structures.
NASA-style checkpoint system for crash recovery.

Features:
- ProcessPoolExecutor for CPU-bound cavity analysis
- ThreadPoolExecutor for I/O-bound PDB downloads
- JSON checkpoint persistence (resume after crash)
- Per-protein timeout (zombie prevention)
- tqdm progress bars + JSON structured logging
- Configurable worker count (auto-detect CPU cores)

Architecture:
    ParallelCrawler
        ├── CheckpointManager  (state persistence)
        ├── CrawlerLogger      (JSON structured logs)
        ├── _download_batch()   (ThreadPool I/O)
        └── _process_batch()    (ProcessPool CPU)

Usage:
    from src.parallel_crawler import ParallelCrawler

    crawler = ParallelCrawler(max_workers=8)
    results = crawler.process_pdb_list(['1CBS', '1AKE', '1TUP'])

Author: Bio-Void Hunter Team
Version: 0.7.0 (Phase 5)
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import time
from concurrent.futures import (
    FIRST_COMPLETED,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.config import PATHS
from src.resources import SAFE_16GB

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_MAX_WORKERS = min(SAFE_16GB.max_analysis_workers, max(1, multiprocessing.cpu_count() - 1))
DEFAULT_DOWNLOAD_WORKERS = SAFE_16GB.max_download_workers
DEFAULT_TIMEOUT = 120  # seconds per protein
CHECKPOINT_INTERVAL = 100  # save state every N proteins
BATCH_SIZE = 50  # proteins per processing batch
RECOVERY_MAX_PROTEINS = 50


class CrawlerRecoveryDisabledError(RuntimeError):
    """Raised when bulk crawling is attempted without the recovery override."""


class CrawlerConfigurationError(ValueError):
    """Raised when a recovery override violates containment limits."""


# ============================================================================
# CHECKPOINT MANAGER
# ============================================================================


@dataclass
class CrawlerState:
    """Serializable crawler state for checkpoint/resume."""

    total_ids: int = 0
    processed_ids: list[str] = field(default_factory=list)
    successful_ids: list[str] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)
    skipped_ids: list[str] = field(default_factory=list)
    last_checkpoint_time: str = ""
    elapsed_seconds: float = 0.0
    results: list[dict[str, Any]] = field(default_factory=list)


class CheckpointManager:
    """Schema-limited JSON state persistence for crash recovery."""

    def __init__(self, checkpoint_dir: str | Path = "data/checkpoints"):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_file = self.checkpoint_dir / "crawler_state.json"
        self.log_file = self.checkpoint_dir / "crawler_log.jsonl"

    def save(self, state: CrawlerState) -> None:
        """Save state as JSON with an atomic replace."""
        state.last_checkpoint_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tmp = self.checkpoint_file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "schema_version": "crawler-checkpoint-v1",
                    "state": asdict(state),
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        tmp.replace(self.checkpoint_file)

    def load(self) -> CrawlerState | None:
        """Load state from checkpoint file, if it exists."""
        if not self.checkpoint_file.exists():
            return None
        try:
            payload = json.loads(self.checkpoint_file.read_text(encoding="utf-8"))
            if payload.get("schema_version") != "crawler-checkpoint-v1":
                return None
            state_payload = payload.get("state")
            if not isinstance(state_payload, dict):
                return None
            return CrawlerState(**state_payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        return None

    def clear(self) -> None:
        """Remove checkpoint file."""
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()

    def append_log(self, entry: dict[str, Any]) -> None:
        """Append a single JSON log line."""
        entry["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")


# ============================================================================
# CRAWLER LOGGER
# ============================================================================


class CrawlerLogger:
    """Structured logging for crawler operations."""

    def __init__(self, name: str = "parallel_crawler"):
        self.logger = logging.getLogger(name)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            fmt = logging.Formatter(
                "[%(asctime)s] [%(levelname)s] [CRAWLER] %(message)s",
                datefmt="%H:%M:%S",
            )
            handler.setFormatter(fmt)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def info(self, msg: str) -> None:
        self.logger.info(msg)

    def warning(self, msg: str) -> None:
        self.logger.warning(msg)

    def error(self, msg: str) -> None:
        self.logger.error(msg)


# ============================================================================
# SINGLE-PROTEIN WORKER  (runs in child process)
# ============================================================================


def _analyze_single_protein(
    pdb_id: str,
    n_frames: int = 20,
    profile: str = "default",
    output_dir: str = "data/runtime/experimental/crawler/results",
    motion_aware: bool = False,
) -> dict[str, Any]:
    """
    Run full Bio-Void pipeline on a single protein.

    Designed to run inside a separate process (ProcessPoolExecutor).
    Catches all exceptions and returns a status dict.

    Args:
        pdb_id: 4-char PDB identifier.
        n_frames: NMA frames (lower for bulk scanning).
        profile: Scoring profile name.
        output_dir: Where to write JSON report.

    Returns:
        Dict with keys: pdb_id, status, runtime, cavities, druggable,
        high_score, top_bio_score, error (if any).
    """
    t0 = time.time()
    result: dict[str, Any] = {
        "pdb_id": pdb_id.upper(),
        "status": "pending",
        "runtime": 0.0,
    }
    try:
        from main import BioVoidPipeline  # noqa: C0415

        experimental_root = Path(output_dir)
        pipeline = BioVoidPipeline(
            pdb_id,
            n_frames=n_frames,
            profile=profile,
            output_dir=experimental_root / "runs",
            atlas_db_path=experimental_root / "crawler_atlas.sqlite",
            cache_dir=experimental_root / "cache",
            multiframe=motion_aware,
            allow_experimental=motion_aware,
        )
        report = pipeline.run()
        cavities = list(report.get("cavities", []))
        high = sum(1 for cavity in cavities if cavity.get("heuristic_quality_tier") == "high")
        medium = sum(1 for cavity in cavities if cavity.get("heuristic_quality_tier") == "medium")
        shortlist = sum(1 for cavity in cavities if cavity.get("heuristic_shortlist", False))
        top_score = cavities[0].get("bio_score", 0.0) if cavities else 0.0
        result.update(
            {
                "status": "success",
                "total_cavities": len(cavities),
                "heuristic_shortlist_count": shortlist,
                "high_score": high,
                "medium_score": medium,
                "top_bio_score": round(top_score, 4),
                "runtime": round(time.time() - t0, 2),
                "cavities": cavities[:50],
                "validation_status": "experimental_unvalidated",
                "canonical_eligible": False,
                "analysis_run_id": report.get("run_id"),
                "detector_version": report.get("static_detector", {}).get("detector_version"),
                "ranking_contract_version": report.get("scoring", {}).get(
                    "ranking_contract_version"
                ),
                "motion_aware": report.get("motion_aware"),
            }
        )

    except Exception as exc:
        result.update(
            {
                "status": "error",
                "error": str(exc),
                "error_type": type(exc).__name__,
                "runtime": round(time.time() - t0, 2),
            }
        )

    return result


# ============================================================================
# PARALLEL CRAWLER
# ============================================================================


class ParallelCrawler:
    """
    High-throughput parallel PDB analyzer.

    Processes thousands of proteins using:
    - ThreadPoolExecutor for I/O (downloads)
    - ProcessPoolExecutor for CPU (analysis)
    - CheckpointManager for crash recovery

    Args:
        max_workers: Number of parallel analysis processes (default: CPU-1).
        download_workers: Number of parallel download threads.
        n_frames: NMA frames per protein (lower = faster bulk scan).
        profile: Scoring profile for all analyses.
        timeout: Per-protein timeout in seconds.
        output_dir: Base output directory.
        checkpoint_dir: Checkpoint persistence directory.

    Usage:
        crawler = ParallelCrawler(max_workers=8)
        results = crawler.process_pdb_list(['1CBS', '1AKE', '1TUP'])
    """

    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_WORKERS,
        download_workers: int = DEFAULT_DOWNLOAD_WORKERS,
        n_frames: int = 20,
        profile: str = "default",
        timeout: int = DEFAULT_TIMEOUT,
        output_dir: str = "data/runtime/experimental/crawler/results",
        checkpoint_dir: str = "data/runtime/experimental/crawler/checkpoints",
        db_path: str | None = None,
        *,
        explicit_recovery_override: bool = False,
        motion_aware: bool = False,
        _executor_class: type | None = None,
    ):
        self.max_workers = max(1, max_workers)
        self.download_workers = max(1, download_workers)
        self.n_frames = n_frames
        self.profile = profile
        self.timeout = timeout
        self.output_dir = str(Path(output_dir))
        self.checkpoint_dir = str(Path(checkpoint_dir))
        self.db_path = db_path
        self.explicit_recovery_override = explicit_recovery_override
        self.motion_aware = motion_aware
        self.validation_status = "experimental_unvalidated"
        self.canonical_eligible = False
        if explicit_recovery_override:
            self._validate_recovery_override()
        # Allow injecting ThreadPoolExecutor for tests (ProcessPool can't
        # pickle mocks). Defaults to ProcessPoolExecutor for production.
        self._executor_class = _executor_class or ProcessPoolExecutor

        self.checkpoint = CheckpointManager(checkpoint_dir)
        self.log = CrawlerLogger()

        self._db: Any = None
        if self.db_path and self.explicit_recovery_override:
            self._init_db()

    def _validate_recovery_override(self) -> None:
        """Enforce conservative limits and isolate all crawler side effects."""
        if self.max_workers > SAFE_16GB.max_analysis_workers:
            raise CrawlerConfigurationError(
                f"Recovery crawler allows at most {SAFE_16GB.max_analysis_workers} workers"
            )
        if self.motion_aware and self.max_workers > SAFE_16GB.max_heavy_jobs:
            raise CrawlerConfigurationError(
                "Recovery motion-aware crawling allows only one heavy NMA worker"
            )
        if self.motion_aware and self.n_frames > SAFE_16GB.max_samples_per_mode:
            raise CrawlerConfigurationError(
                "Recovery motion-aware crawling exceeds safe samples per mode"
            )
        if self.download_workers > SAFE_16GB.max_download_workers:
            raise CrawlerConfigurationError(
                f"Recovery crawler allows at most {SAFE_16GB.max_download_workers} download workers"
            )
        if self.n_frames < 1 or self.n_frames > 20:
            raise CrawlerConfigurationError("Recovery crawler n_frames must be in range [1, 20]")
        if self.timeout <= 0 or self.timeout > 600:
            raise CrawlerConfigurationError("Recovery crawler timeout must be in range (0, 600]")

        output = Path(self.output_dir).resolve()
        protected = {
            Path(PATHS.legacy_results).resolve(),
            Path(PATHS.legacy_frames).resolve(),
            Path(PATHS.results).resolve(),
            Path(PATHS.frames).resolve(),
            Path(PATHS.runs).resolve(),
        }
        if any(output == root or output.is_relative_to(root) for root in protected):
            raise CrawlerConfigurationError(
                "Recovery crawler output must use a non-canonical experimental root"
            )

        if self.db_path:
            database = Path(self.db_path).resolve()
            if database in {
                Path(PATHS.legacy_atlas_db).resolve(),
                Path(PATHS.atlas_db).resolve(),
            } or not database.is_relative_to(output):
                raise CrawlerConfigurationError(
                    "Crawler DB must be experimental and contained inside its output root"
                )

    # ---- database integration ----

    def _init_db(self) -> None:
        """Initialize database connection."""
        from src.database import AtlasDB

        self._db = AtlasDB(db_path=self.db_path, check_same_thread=False)
        self.log.info(f"Database initialized: {self.db_path}")

    def _write_result_to_db(self, result: dict[str, Any]) -> None:
        """Write a single protein result to the database."""
        if not self._db or result.get("status") != "success":
            return

        try:
            pdb_id = result["pdb_id"]

            self._db.insert_protein(
                {
                    "pdb_id": pdb_id,
                    "total_cavities": result.get("total_cavities", 0),
                    "druggable_cavities": result.get("druggable_count", 0),
                    "high_score_count": result.get("high_score", 0),
                    "medium_score_count": result.get("medium_score", 0),
                    "top_bio_score": result.get("top_bio_score", 0.0),
                    "analysis_runtime": result.get("runtime", 0.0),
                    "n_frames": self.n_frames,
                    "scoring_profile": self.profile,
                    "status": "success",
                }
            )

            cavities = result.get("cavities", [])
            for cav in cavities:
                self._db.insert_discovery(
                    {
                        "pdb_id": pdb_id,
                        "pocket_id": cav.get("id", 0),
                        "rank": cav.get("rank", 0),
                        "bio_score": cav.get("bio_score", 0.0),
                        "volume": cav.get("volume", 0.0),
                        "center": cav.get("center", [0.0, 0.0, 0.0]),
                        "radius_geom": cav.get("radius_geom", 0.0),
                        "radius_clear": cav.get("radius_clear", 0.0),
                        "merged_vertices": cav.get("merged_vertices", 0),
                        "hydrophobic_ratio": cav.get("hydrophobic_ratio", 0.0),
                        "polar_atoms": cav.get("polar_atoms", 0),
                        "druggable": cav.get("druggable", False),
                        "druggability_class": cav.get("druggability_class", "low"),
                        "score_components": cav.get("score_components", {}),
                        "profile_used": cav.get("profile_used", "Default"),
                    }
                )

            self.log.info(f"DB: Inserted {pdb_id} with {len(cavities)} pockets")
        except Exception as e:
            self.log.warning(f"DB write failed for {result.get('pdb_id')}: {e}")

    def close_db(self) -> None:
        """Close database connection."""
        if self._db:
            self._db.close()
            self._db = None

    # ---- public API ----

    def process_pdb_list(
        self,
        pdb_ids: list[str],
        resume: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Process a list of PDB IDs in parallel.

        Args:
            pdb_ids: List of PDB identifiers.
            resume: If True, skip already-processed IDs from checkpoint.

        Returns:
            List of per-protein result dicts.
        """
        if not self.explicit_recovery_override:
            raise CrawlerRecoveryDisabledError(
                "Bulk crawling is disabled during recovery. "
                "Use explicit_recovery_override with a non-canonical output root."
            )
        if len(pdb_ids) > RECOVERY_MAX_PROTEINS:
            raise CrawlerConfigurationError(
                f"Recovery crawler is limited to {RECOVERY_MAX_PROTEINS} proteins per run"
            )

        # Normalize
        pdb_ids = [pid.upper().strip() for pid in pdb_ids]

        # Resume logic
        state = self.checkpoint.load() if resume else None
        if state is None:
            state = CrawlerState()
        # P0.3 rule: do not trust stale checkpoint total_ids; normalize to current target list.
        state.total_ids = len(pdb_ids)

        if state.processed_ids:
            already = set(state.processed_ids)
            remaining = [pid for pid in pdb_ids if pid not in already]
            self.log.info(f"Resuming: {len(already)} done, {len(remaining)} remaining")
        else:
            remaining = list(pdb_ids)

        if not remaining:
            self.log.info("All proteins already processed.")
            # Keep checkpoint + summary coherent with current target list size.
            self.checkpoint.save(state)
            self._save_summary(state)
            return state.results

        prev_elapsed = float(state.elapsed_seconds or 0.0)
        t_start = time.time()

        self.log.info(
            f"Starting parallel analysis: {len(remaining)} proteins | "
            f"{self.max_workers} workers | timeout={self.timeout}s"
        )

        # Process in batches
        for batch_start in range(0, len(remaining), BATCH_SIZE):
            batch = remaining[batch_start : batch_start + BATCH_SIZE]
            batch_results = self._process_batch(batch)

            for res in batch_results:
                res["validation_status"] = self.validation_status
                res["canonical_eligible"] = self.canonical_eligible
                pid = res["pdb_id"]
                state.processed_ids.append(pid)
                state.results.append(res)

                if res["status"] == "success":
                    state.successful_ids.append(pid)
                    self._write_result_to_db(res)
                elif res["status"] == "error":
                    state.failed_ids.append(pid)
                elif res["status"] == "timeout":
                    state.skipped_ids.append(pid)

                self.checkpoint.append_log(res)

            # Auto-checkpoint
            state.elapsed_seconds = prev_elapsed + (time.time() - t_start)
            self.checkpoint.save(state)

            done = len(state.processed_ids)
            total = state.total_ids
            ok = len(state.successful_ids)
            fail = len(state.failed_ids)
            skip = len(state.skipped_ids)
            self.log.info(f"Progress: {done}/{total} | OK={ok} FAIL={fail} SKIP={skip}")

        elapsed = time.time() - t_start
        # Elapsed must be accumulated once (checkpointed value + this run).
        state.elapsed_seconds = prev_elapsed + elapsed
        self.checkpoint.save(state)

        self.log.info(
            f"Done: {len(state.successful_ids)} success, "
            f"{len(state.failed_ids)} failed, "
            f"{len(state.skipped_ids)} skipped in {elapsed:.1f}s"
        )

        # Save final summary
        self._save_summary(state)
        return state.results

    # ---- batch processing ----

    def _process_batch(self, pdb_ids: list[str]) -> list[dict[str, Any]]:
        """Process a batch with wall-clock timeout enforcement."""
        results: list[dict[str, Any]] = []
        executor = self._executor_class(max_workers=self.max_workers)
        timed_out_count = 0

        try:
            future_to_pid: dict[Any, str] = {}
            start_time: dict[Any, float] = {}
            pending: set[Any] = set()

            for pid in pdb_ids:
                fut = executor.submit(
                    _analyze_single_protein,
                    pid,
                    self.n_frames,
                    self.profile,
                    self.output_dir,
                    self.motion_aware,
                )
                future_to_pid[fut] = pid
                start_time[fut] = time.time()
                pending.add(fut)

            while pending:
                now = time.time()
                nearest_deadline = min(
                    max(0.0, (start_time[fut] + self.timeout) - now) for fut in pending
                )
                done, _ = wait(
                    pending,
                    timeout=nearest_deadline,
                    return_when=FIRST_COMPLETED,
                )

                # Collect completed futures first.
                for fut in done:
                    pending.discard(fut)
                    pid = future_to_pid[fut]
                    try:
                        res = fut.result()
                        results.append(res)
                    except Exception as exc:
                        self.log.error(f"Worker crash: {pid} — {exc}")
                        results.append(
                            {
                                "pdb_id": pid,
                                "status": "error",
                                "error": str(exc),
                                "error_type": type(exc).__name__,
                                "runtime": 0.0,
                            }
                        )

                # Wall-clock timeout sweep.
                now = time.time()
                overdue: list[Any] = []
                for fut in pending:
                    if now - start_time[fut] >= self.timeout:
                        overdue.append(fut)

                for fut in overdue:
                    pending.discard(fut)
                    pid = future_to_pid[fut]
                    fut.cancel()
                    timed_out_count += 1
                    self.log.warning(f"Timeout: {pid} (wall-clock >{self.timeout}s)")
                    results.append(
                        {
                            "pdb_id": pid,
                            "status": "timeout",
                            "runtime": float(self.timeout),
                        }
                    )
        finally:
            # Hung worker isolation: detach timed-out workers from batch completion.
            if timed_out_count > 0:
                self.log.warning(
                    f"Hung worker isolation active: {timed_out_count} timed-out task(s) detached."
                )
                executor.shutdown(wait=False, cancel_futures=True)
            else:
                executor.shutdown(wait=True)

        return results

    # ---- download batch (ThreadPool for I/O) ----

    def download_batch(self, pdb_ids: list[str], cache_dir: str = "data/raw_pdb") -> dict[str, str]:
        """
        Download PDB files in parallel using threads.

        Args:
            pdb_ids: List of PDB IDs to download.
            cache_dir: Download destination.

        Returns:
            Dict mapping pdb_id -> local file path (or "error").
        """
        from src.fetcher import fetch_pdb  # noqa: C0415

        results: dict[str, str] = {}

        def _dl(pid: str) -> tuple[str, str]:
            try:
                path = fetch_pdb(pid, cache_dir=Path(cache_dir))
                return pid, str(path)
            except Exception as exc:
                return pid, f"error:{exc}"

        with ThreadPoolExecutor(max_workers=self.download_workers) as pool:
            futures = {pool.submit(_dl, pid): pid for pid in pdb_ids}
            for fut in as_completed(futures):
                pid, path = fut.result()
                results[pid] = path

        return results

    # ---- summary ----

    def _save_summary(self, state: CrawlerState) -> Path:
        """Save final summary JSON."""
        summary_path = Path(self.checkpoint_dir) / "crawler_summary.json"
        summary = {
            "total": state.total_ids,
            "processed": len(state.processed_ids),
            "successful": len(state.successful_ids),
            "failed": len(state.failed_ids),
            "skipped": len(state.skipped_ids),
            "elapsed_seconds": round(state.elapsed_seconds, 1),
            "throughput_per_second": (
                round(len(state.processed_ids) / max(1, state.elapsed_seconds), 2)
            ),
            "success_rate": (
                round(
                    len(state.successful_ids) / max(1, len(state.processed_ids)) * 100,
                    1,
                )
            ),
            "failed_ids": state.failed_ids[:50],  # first 50 for brevity
        }
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        self.log.info(f"Summary saved: {summary_path}")
        return summary_path

    # ---- convenience ----

    def get_checkpoint_state(self) -> CrawlerState | None:
        """Read current checkpoint state without modifying it."""
        return self.checkpoint.load()

    def clear_checkpoint(self) -> None:
        """Delete checkpoint files to start fresh."""
        self.checkpoint.clear()
        self.log.info("Checkpoint cleared.")
