"""
Timeout enforcement regressions for P0.4.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from src.parallel_crawler import ParallelCrawler


def _synthetic_worker(pid: str, *_args, **_kwargs) -> dict:
    """Deterministic synthetic sleeper worker for timeout tests."""
    if pid.startswith("SLOW"):
        time.sleep(0.35)
    return {
        "pdb_id": pid,
        "status": "success",
        "runtime": 0.01,
        "cavities": [],
    }


def test_wall_clock_timeout_with_synthetic_sleeper(tmp_path: Path) -> None:
    crawler = ParallelCrawler(
        max_workers=1,
        timeout=0.05,
        checkpoint_dir=str(tmp_path / "cp"),
        _executor_class=ThreadPoolExecutor,
    )

    with patch("src.parallel_crawler._analyze_single_protein", side_effect=_synthetic_worker):
        t0 = time.perf_counter()
        results = crawler._process_batch(["SLOW_1"])
        elapsed = time.perf_counter() - t0

    assert elapsed < 0.25  # Should not wait full synthetic sleep.
    assert len(results) == 1
    assert results[0]["pdb_id"] == "SLOW_1"
    assert results[0]["status"] == "timeout"
    assert results[0]["runtime"] == pytest.approx(0.05, abs=1e-9)


def test_hung_worker_isolation_keeps_fast_results(tmp_path: Path) -> None:
    crawler = ParallelCrawler(
        max_workers=2,
        timeout=0.05,
        checkpoint_dir=str(tmp_path / "cp"),
        _executor_class=ThreadPoolExecutor,
    )

    with patch("src.parallel_crawler._analyze_single_protein", side_effect=_synthetic_worker):
        results = crawler._process_batch(["FAST_1", "SLOW_1", "FAST_2"])

    by_pid = {r["pdb_id"]: r["status"] for r in results}
    assert len(results) == 3
    assert by_pid["FAST_1"] == "success"
    assert by_pid["FAST_2"] == "success"
    assert by_pid["SLOW_1"] == "timeout"


def test_timeout_uses_nonblocking_shutdown(tmp_path: Path) -> None:
    class InspectingExecutor(ThreadPoolExecutor):
        last_wait: bool | None = None
        last_cancel: bool | None = None

        def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
            type(self).last_wait = wait
            type(self).last_cancel = cancel_futures
            super().shutdown(wait=wait, cancel_futures=cancel_futures)

    crawler = ParallelCrawler(
        max_workers=1,
        timeout=0.05,
        checkpoint_dir=str(tmp_path / "cp"),
        _executor_class=InspectingExecutor,
    )

    with patch("src.parallel_crawler._analyze_single_protein", side_effect=_synthetic_worker):
        results = crawler._process_batch(["SLOW_1"])

    assert len(results) == 1
    assert results[0]["status"] == "timeout"
    assert InspectingExecutor.last_wait is False
    assert InspectingExecutor.last_cancel is True
