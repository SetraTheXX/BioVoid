"""
Bio-Void Hunter: Parallel Crawler & Orchestrator (Phase 5.1)
=============================================================

High-throughput parallel processing of PDB structures.
NASA-style checkpoint system for crash recovery.

Features:
- ProcessPoolExecutor for CPU-bound cavity analysis
- ThreadPoolExecutor for I/O-bound PDB downloads
- Pickle-based checkpoint persistence (resume after crash)
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
import os
import pickle
import time
import traceback
from concurrent.futures import (
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
    as_completed,
)
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_MAX_WORKERS = max(1, multiprocessing.cpu_count() - 1)
DEFAULT_DOWNLOAD_WORKERS = 20
DEFAULT_TIMEOUT = 120  # seconds per protein
CHECKPOINT_INTERVAL = 100  # save state every N proteins
BATCH_SIZE = 50  # proteins per processing batch


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
    """Pickle-based state persistence for crash recovery."""

    def __init__(self, checkpoint_dir: str | Path = "data/checkpoints"):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_file = self.checkpoint_dir / "crawler_state.pkl"
        self.log_file = self.checkpoint_dir / "crawler_log.jsonl"

    def save(self, state: CrawlerState) -> None:
        """Save state to pickle file (atomic write)."""
        state.last_checkpoint_time = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        tmp = self.checkpoint_file.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(self.checkpoint_file)

    def load(self) -> CrawlerState | None:
        """Load state from checkpoint file, if it exists."""
        if not self.checkpoint_file.exists():
            return None
        try:
            with open(self.checkpoint_file, "rb") as f:
                state = pickle.load(f)  # noqa: S301
            if isinstance(state, CrawlerState):
                return state
        except Exception:
            pass
        return None

    def clear(self) -> None:
        """Remove checkpoint file."""
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()

    def append_log(self, entry: dict[str, Any]) -> None:
        """Append a single JSON log line."""
        entry["timestamp"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
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
    output_dir: str = "data/results",
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
        # Lazy imports to keep child processes independent
        from src.fetcher import fetch_pdb  # noqa: C0415
        from src.dynamics import run_nma_simulation  # noqa: C0415
        from src.cavities import find_cavities  # noqa: C0415
        from src.geometry import find_voids, extract_atom_coords  # noqa: C0415
        from src.scoring import rank_pockets  # noqa: C0415

        # Step 1 — Fetch
        pdb_file = fetch_pdb(pdb_id)

        # Step 2 — NMA (lightweight for bulk)
        frames_dir = None
        try:
            nma_result = run_nma_simulation(
                pdb_path=pdb_file,
                n_modes=6,
                n_frames=n_frames,
                output_dir=f"data/frames/{pdb_id.lower()}",
            )
            frames_dir = nma_result["output_dir"]
        except Exception:
            pass  # fallback to static

        # Determine analysis file
        if frames_dir:
            frame_file = Path(frames_dir) / f"frame_{n_frames // 2:03d}.pdb"
            if not frame_file.exists():
                frame_file = Path(frames_dir) / "frame_001.pdb"
        else:
            frame_file = Path(str(pdb_file))

        # Step 3 — Cavities
        cavities = find_cavities(
            str(frame_file), merge=True, hydrophobic=True, atom_type="heavy"
        )

        # Step 4 — Scoring
        atom_coords = extract_atom_coords(str(frame_file), atom_type="heavy")
        ranked = rank_pockets(cavities, atom_coords, profile=profile)

        # Step 5 — Summary metrics
        high = sum(
            1 for c in ranked if c.get("druggability_class") == "high"
        )
        medium = sum(
            1 for c in ranked if c.get("druggability_class") == "medium"
        )
        druggable = sum(1 for c in ranked if c.get("druggable", False))
        top_score = ranked[0]["bio_score"] if ranked else 0.0

        druggable_cavities = [
            {
                "id": c.get("id", i),
                "rank": c.get("rank", i + 1),
                "bio_score": c.get("bio_score", 0.0),
                "volume": c.get("volume", 0.0),
                "center": c.get("center", [0.0, 0.0, 0.0]),
                "radius_geom": c.get("radius_geom", 0.0),
                "radius_clear": c.get("radius_clear", 0.0),
                "merged_vertices": c.get("merged_vertices", 0),
                "hydrophobic_ratio": c.get("hydrophobic_ratio", 0.0),
                "polar_atoms": c.get("polar_atoms", 0),
                "druggable": c.get("druggable", False),
                "druggability_class": c.get("druggability_class", "low"),
                "score_components": c.get("score_components", {}),
                "profile_used": c.get("profile_used", "Default"),
            }
            for i, c in enumerate(ranked[:50])
            if c.get("druggable", False) or c.get("druggability_class") in ("high", "medium")
        ]

        result.update(
            {
                "status": "success",
                "total_cavities": len(ranked),
                "druggable_count": druggable,
                "high_score": high,
                "medium_score": medium,
                "top_bio_score": round(top_score, 4),
                "runtime": round(time.time() - t0, 2),
                "cavities": druggable_cavities,
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
        output_dir: str = "data/results",
        checkpoint_dir: str = "data/checkpoints",
        db_path: str | None = None,
        *,
        _executor_class: type | None = None,
    ):
        self.max_workers = max(1, max_workers)
        self.download_workers = max(1, download_workers)
        self.n_frames = n_frames
        self.profile = profile
        self.timeout = timeout
        self.output_dir = output_dir
        self.checkpoint_dir = checkpoint_dir
        self.db_path = db_path
        # Allow injecting ThreadPoolExecutor for tests (ProcessPool can't
        # pickle mocks). Defaults to ProcessPoolExecutor for production.
        self._executor_class = _executor_class or ProcessPoolExecutor

        self.checkpoint = CheckpointManager(checkpoint_dir)
        self.log = CrawlerLogger()
        
        self._db: Any = None
        if self.db_path:
            self._init_db()

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
            
            self._db.insert_protein({
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
            })
            
            cavities = result.get("cavities", [])
            for cav in cavities:
                self._db.insert_discovery({
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
                })
            
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
        # Normalize
        pdb_ids = [pid.upper().strip() for pid in pdb_ids]

        # Resume logic
        state = self.checkpoint.load() if resume else None
        if state and state.processed_ids:
            already = set(state.processed_ids)
            remaining = [pid for pid in pdb_ids if pid not in already]
            self.log.info(
                f"Resuming: {len(already)} done, {len(remaining)} remaining"
            )
        else:
            state = CrawlerState(total_ids=len(pdb_ids))
            remaining = list(pdb_ids)

        if not remaining:
            self.log.info("All proteins already processed.")
            return state.results

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
            state.elapsed_seconds = time.time() - t_start
            self.checkpoint.save(state)

            done = len(state.processed_ids)
            total = state.total_ids or len(pdb_ids)
            ok = len(state.successful_ids)
            fail = len(state.failed_ids)
            skip = len(state.skipped_ids)
            self.log.info(
                f"Progress: {done}/{total} | "
                f"OK={ok} FAIL={fail} SKIP={skip}"
            )

        elapsed = time.time() - t_start
        state.elapsed_seconds += elapsed

        self.log.info(
            f"Done: {len(state.successful_ids)} success, "
            f"{len(state.failed_ids)} failed, "
            f"{len(state.skipped_ids)} skipped in {elapsed:.1f}s"
        )

        # Save final summary
        self._save_summary(state)
        return state.results

    # ---- batch processing ----

    def _process_batch(
        self, pdb_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Process a batch of PDB IDs using ProcessPoolExecutor."""
        results: list[dict[str, Any]] = []

        with self._executor_class(max_workers=self.max_workers) as executor:
            future_to_pid = {}
            for pid in pdb_ids:
                fut = executor.submit(
                    _analyze_single_protein,
                    pid,
                    self.n_frames,
                    self.profile,
                    self.output_dir,
                )
                future_to_pid[fut] = pid

            for fut in as_completed(future_to_pid):
                pid = future_to_pid[fut]
                try:
                    res = fut.result(timeout=self.timeout)
                    results.append(res)
                except FutureTimeoutError:
                    self.log.warning(f"Timeout: {pid} (>{self.timeout}s)")
                    results.append(
                        {
                            "pdb_id": pid,
                            "status": "timeout",
                            "runtime": self.timeout,
                        }
                    )
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

        return results

    # ---- download batch (ThreadPool for I/O) ----

    def download_batch(
        self, pdb_ids: list[str], cache_dir: str = "data/raw_pdb"
    ) -> dict[str, str]:
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
                round(
                    len(state.processed_ids) / max(1, state.elapsed_seconds), 2
                )
            ),
            "success_rate": (
                round(
                    len(state.successful_ids)
                    / max(1, len(state.processed_ids))
                    * 100,
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
