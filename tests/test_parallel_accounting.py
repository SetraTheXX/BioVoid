"""
Regression tests for P0.3 accounting fixes in parallel_crawler.py.
"""

from __future__ import annotations

import itertools
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from src.parallel_crawler import CrawlerState, ParallelCrawler


def _success_result(pid: str) -> dict:
    return {
        "pdb_id": pid,
        "status": "success",
        "runtime": 0.1,
        "total_cavities": 1,
        "druggable_count": 1,
        "high_score": 1,
        "medium_score": 0,
        "top_bio_score": 0.8,
        "cavities": [],
    }


def _load_summary(checkpoint_dir: Path) -> dict:
    return json.loads((checkpoint_dir / "crawler_summary.json").read_text(encoding="utf-8"))


def test_resume_total_ids_normalized_to_current_list(tmp_path: Path) -> None:
    checkpoint_dir = tmp_path / "cp"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    crawler = ParallelCrawler(
        max_workers=1,
        checkpoint_dir=str(checkpoint_dir),
        _executor_class=ThreadPoolExecutor,
    )
    # Stale checkpoint total_ids (historical bug pattern: 50 while processed list moved on).
    stale = CrawlerState(
        total_ids=50,
        processed_ids=["1CBS", "1AKE"],
        successful_ids=["1CBS", "1AKE"],
        results=[
            {"pdb_id": "1CBS", "status": "success"},
            {"pdb_id": "1AKE", "status": "success"},
        ],
        elapsed_seconds=12.0,
    )
    crawler.checkpoint.save(stale)

    with patch(
        "src.parallel_crawler._analyze_single_protein", return_value=_success_result("1TUP")
    ):
        results = crawler.process_pdb_list(["1CBS", "1AKE", "1TUP"], resume=True)

    state = crawler.get_checkpoint_state()
    assert state is not None
    assert state.total_ids == 3  # normalized with current target list
    assert len(state.processed_ids) == 3
    assert len(results) == 3

    summary = _load_summary(checkpoint_dir)
    assert summary["total"] == 3
    assert summary["processed"] == 3


def test_elapsed_not_double_counted_and_metrics_consistent(tmp_path: Path) -> None:
    checkpoint_dir = tmp_path / "cp"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    crawler = ParallelCrawler(
        max_workers=1,
        checkpoint_dir=str(checkpoint_dir),
        _executor_class=ThreadPoolExecutor,
    )

    fake_clock = itertools.chain([100.0, 105.0, 110.0], itertools.repeat(110.0))
    with (
        patch("src.parallel_crawler._analyze_single_protein", return_value=_success_result("TEST")),
        patch(
            "src.parallel_crawler.time.time",
            side_effect=lambda: next(fake_clock),
        ),
    ):
        crawler.process_pdb_list(["TEST"], resume=False)

    state = crawler.get_checkpoint_state()
    assert state is not None
    # Old bug produced 15.0 here (double counted); fixed behavior must be 10.0.
    assert state.elapsed_seconds == pytest.approx(10.0, abs=1e-9)

    summary = _load_summary(checkpoint_dir)
    expected_throughput = round(
        len(state.processed_ids) / max(1, state.elapsed_seconds),
        2,
    )
    expected_success = round(
        len(state.successful_ids) / max(1, len(state.processed_ids)) * 100,
        1,
    )
    assert summary["throughput_per_second"] == expected_throughput
    assert summary["success_rate"] == expected_success


def test_smoke_50_proteins_summary_coherent(tmp_path: Path) -> None:
    checkpoint_dir = tmp_path / "cp"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    crawler = ParallelCrawler(
        max_workers=1,
        checkpoint_dir=str(checkpoint_dir),
        _executor_class=ThreadPoolExecutor,
    )
    ids = [f"T{i:03d}" for i in range(50)]

    with patch(
        "src.parallel_crawler._analyze_single_protein",
        side_effect=lambda pid, *_args, **_kwargs: _success_result(pid),
    ):
        results = crawler.process_pdb_list(ids, resume=False)

    state = crawler.get_checkpoint_state()
    assert state is not None
    summary = _load_summary(checkpoint_dir)

    assert len(results) == 50
    assert summary["total"] == 50
    assert summary["processed"] == 50
    assert summary["successful"] == 50
    assert summary["failed"] == 0
    assert summary["skipped"] == 0

    expected_throughput = round(
        len(state.processed_ids) / max(1, state.elapsed_seconds),
        2,
    )
    assert summary["throughput_per_second"] == expected_throughput
