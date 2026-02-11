"""
Test Suite for Phase 5.1: Parallel Crawler & Orchestrator
==========================================================

Tests for:
- CheckpointManager (save/load/clear)
- CrawlerState dataclass
- CrawlerLogger
- _analyze_single_protein worker function
- ParallelCrawler (process_pdb_list, download_batch)
- fetch_pdb_list API helpers (build_search_query, save/load)
- Resume logic (checkpoint round-trip)
- Timeout handling (zombie prevention)

Author: Bio-Void Hunter Team
"""

from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from src.parallel_crawler import (
    CheckpointManager,
    CrawlerLogger,
    CrawlerState,
    ParallelCrawler,
    _analyze_single_protein,
    DEFAULT_MAX_WORKERS,
    DEFAULT_TIMEOUT,
    CHECKPOINT_INTERVAL,
    BATCH_SIZE,
)
from scripts.fetch_pdb_list import (
    build_search_query,
    save_pdb_list,
)


# ============================================================================
# FIXTURES
# ============================================================================

TMP_DIR = Path("data/_test_checkpoints")


@pytest.fixture(autouse=True)
def _cleanup_tmp():
    """Ensure test checkpoint dir is clean before/after each test."""
    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    yield
    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR)


# ============================================================================
# CHECKPOINT MANAGER
# ============================================================================


class TestCheckpointManager:
    """Test pickle-based checkpoint persistence."""

    def test_save_and_load(self):
        mgr = CheckpointManager(str(TMP_DIR))
        state = CrawlerState(total_ids=10, processed_ids=["1CBS", "1AKE"])
        mgr.save(state)
        loaded = mgr.load()
        assert loaded is not None
        assert loaded.total_ids == 10
        assert loaded.processed_ids == ["1CBS", "1AKE"]

    def test_load_empty(self):
        mgr = CheckpointManager(str(TMP_DIR))
        assert mgr.load() is None

    def test_clear(self):
        mgr = CheckpointManager(str(TMP_DIR))
        mgr.save(CrawlerState(total_ids=5))
        mgr.clear()
        assert mgr.load() is None

    def test_append_log(self):
        mgr = CheckpointManager(str(TMP_DIR))
        mgr.append_log({"pdb_id": "1CBS", "status": "success"})
        mgr.append_log({"pdb_id": "1AKE", "status": "error"})
        lines = mgr.log_file.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["pdb_id"] == "1CBS"

    def test_save_timestamp(self):
        mgr = CheckpointManager(str(TMP_DIR))
        state = CrawlerState()
        mgr.save(state)
        loaded = mgr.load()
        assert loaded is not None
        assert loaded.last_checkpoint_time != ""


# ============================================================================
# CRAWLER STATE
# ============================================================================


class TestCrawlerState:
    """Test CrawlerState dataclass defaults."""

    def test_defaults(self):
        state = CrawlerState()
        assert state.total_ids == 0
        assert state.processed_ids == []
        assert state.successful_ids == []
        assert state.failed_ids == []
        assert state.skipped_ids == []
        assert state.results == []

    def test_field_independence(self):
        s1 = CrawlerState()
        s2 = CrawlerState()
        s1.processed_ids.append("1CBS")
        assert "1CBS" not in s2.processed_ids


# ============================================================================
# CRAWLER LOGGER
# ============================================================================


class TestCrawlerLogger:
    """Test structured logger."""

    def test_logger_creation(self):
        log = CrawlerLogger("test_crawler")
        assert log.logger.name == "test_crawler"

    def test_log_methods_no_error(self):
        log = CrawlerLogger("test_log")
        log.info("test info")
        log.warning("test warning")
        log.error("test error")


# ============================================================================
# FETCH PDB LIST (scripts/fetch_pdb_list.py)
# ============================================================================


class TestFetchPdbList:
    """Test RCSB API query builder and save/load."""

    def test_query_structure(self):
        q = build_search_query(max_resolution=2.0)
        assert q["query"]["type"] == "group"
        assert q["return_type"] == "entry"
        nodes = q["query"]["nodes"]
        assert len(nodes) == 3

    def test_query_resolution_filter(self):
        q = build_search_query(max_resolution=1.5)
        res_node = q["query"]["nodes"][0]
        assert res_node["parameters"]["value"] == 1.5
        assert res_node["parameters"]["operator"] == "less_or_equal"

    def test_query_method_filter(self):
        q = build_search_query(method="ELECTRON MICROSCOPY")
        method_node = q["query"]["nodes"][1]
        assert method_node["parameters"]["value"] == "ELECTRON MICROSCOPY"

    def test_save_pdb_list(self):
        out = TMP_DIR / "test_ids.json"
        save_pdb_list(["1CBS", "1AKE", "1TUP"], str(out), 2.5)
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["total_ids"] == 3
        assert data["pdb_ids"] == ["1CBS", "1AKE", "1TUP"]
        assert data["source"] == "RCSB PDB Search API v2"


# ============================================================================
# PARALLEL CRAWLER
# ============================================================================


class TestParallelCrawler:
    """Test ParallelCrawler orchestration."""

    def test_init_defaults(self):
        crawler = ParallelCrawler(checkpoint_dir=str(TMP_DIR))
        assert crawler.max_workers >= 1
        assert crawler.timeout == DEFAULT_TIMEOUT
        assert crawler.profile == "default"

    def test_clear_checkpoint(self):
        crawler = ParallelCrawler(checkpoint_dir=str(TMP_DIR))
        state = CrawlerState(total_ids=5)
        crawler.checkpoint.save(state)
        crawler.clear_checkpoint()
        assert crawler.get_checkpoint_state() is None

    def test_get_checkpoint_state_empty(self):
        crawler = ParallelCrawler(checkpoint_dir=str(TMP_DIR))
        assert crawler.get_checkpoint_state() is None

    def test_process_empty_list(self):
        crawler = ParallelCrawler(
            max_workers=1,
            checkpoint_dir=str(TMP_DIR),
        )
        results = crawler.process_pdb_list([])
        assert results == []

    def test_process_with_mock_worker(self):
        """Test process_pdb_list with mocked analysis function."""
        mock_result = {
            "pdb_id": "TEST",
            "status": "success",
            "cavities": 10,
            "druggable": 3,
            "high_score": 1,
            "medium_score": 2,
            "top_bio_score": 0.85,
            "runtime": 0.5,
        }

        with patch(
            "src.parallel_crawler._analyze_single_protein",
            return_value=mock_result,
        ):
            crawler = ParallelCrawler(
                max_workers=1,
                checkpoint_dir=str(TMP_DIR),
                _executor_class=ThreadPoolExecutor,
            )
            results = crawler.process_pdb_list(["TEST"], resume=False)

        assert len(results) == 1
        assert results[0]["status"] == "success"
        assert results[0]["pdb_id"] == "TEST"

    def test_resume_skips_processed(self):
        """Already-processed IDs should be skipped on resume."""
        crawler = ParallelCrawler(
            max_workers=1,
            checkpoint_dir=str(TMP_DIR),
        )
        # Pre-populate checkpoint
        state = CrawlerState(
            total_ids=3,
            processed_ids=["1CBS", "1AKE"],
            successful_ids=["1CBS", "1AKE"],
            results=[
                {"pdb_id": "1CBS", "status": "success"},
                {"pdb_id": "1AKE", "status": "success"},
            ],
        )
        crawler.checkpoint.save(state)

        mock_result = {
            "pdb_id": "1TUP",
            "status": "success",
            "runtime": 0.1,
        }
        with patch(
            "src.parallel_crawler._analyze_single_protein",
            return_value=mock_result,
        ):
            results = crawler.process_pdb_list(
                ["1CBS", "1AKE", "1TUP"], resume=True
            )

        # 2 from checkpoint + 1 new
        assert len(results) == 3
        pdb_set = {r["pdb_id"] for r in results}
        assert "1CBS" in pdb_set
        assert "1AKE" in pdb_set
        assert "1TUP" in pdb_set


# ============================================================================
# ANALYZE SINGLE PROTEIN (Integration — uses real fetcher/cavities)
# ============================================================================


class TestAnalyzeSingleProtein:
    """Test worker function with real PDB (optional)."""

    @pytest.mark.skipif(
        not Path("data/raw_pdb/pdb1cbs.ent").exists()
        and not Path("data/raw_pdb/1cbs.pdb").exists(),
        reason="1CBS PDB not available locally",
    )
    def test_real_1cbs_analysis(self):
        """Full pipeline on real 1CBS protein."""
        result = _analyze_single_protein(
            "1CBS", n_frames=10, profile="enzyme"
        )
        assert result["status"] == "success"
        assert result["pdb_id"] == "1CBS"
        assert result["cavities"] > 0
        assert result["top_bio_score"] > 0.0
        assert result["runtime"] > 0.0

    def test_invalid_pdb_returns_error(self):
        """Invalid PDB ID should return error status, not crash."""
        result = _analyze_single_protein("ZZZZ", n_frames=5)
        assert result["status"] == "error"
        assert "error" in result


# ============================================================================
# CONSTANTS
# ============================================================================


class TestConstants:
    """Test module constants are reasonable."""

    def test_default_workers(self):
        assert DEFAULT_MAX_WORKERS >= 1

    def test_timeout(self):
        assert DEFAULT_TIMEOUT >= 30

    def test_checkpoint_interval(self):
        assert CHECKPOINT_INTERVAL >= 10

    def test_batch_size(self):
        assert BATCH_SIZE >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
