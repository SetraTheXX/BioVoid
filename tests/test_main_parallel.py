"""
Regression tests for main_parallel.py resume/DB behavior (P0.2).
"""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

import main_parallel
from src.parallel_crawler import CheckpointManager, CrawlerState, ParallelCrawler as RealParallelCrawler


def _resume_args(
    *,
    db: str | None,
    input_path: str | None,
    checkpoint_dir: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        input=input_path,
        workers=1,
        n_frames=5,
        profile="default",
        timeout=30,
        checkpoint_dir=checkpoint_dir,
        db=db,
    )


def test_resume_without_db_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = _resume_args(db=None, input_path=None, checkpoint_dir=str(tmp_path))
    rc = main_parallel.cmd_resume(args)
    captured = capsys.readouterr()
    assert rc == 1
    assert "--db is required for resume" in captured.err


def test_resume_with_missing_db_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing_db = tmp_path / "missing.db"
    args = _resume_args(db=str(missing_db), input_path=None, checkpoint_dir=str(tmp_path))
    rc = main_parallel.cmd_resume(args)
    captured = capsys.readouterr()
    assert rc == 1
    assert "DB file not found" in captured.err


def test_resume_passes_db_to_crawler(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "atlas.db"
    db_path.touch()
    input_json = tmp_path / "ids.json"
    input_json.write_text(json.dumps({"pdb_ids": ["1ABC"]}), encoding="utf-8")

    observed: dict[str, object] = {}

    class DummyCrawler:
        def __init__(self, **kwargs):
            observed["init"] = kwargs
            observed["closed"] = False

        def get_checkpoint_state(self):
            return object()

        def process_pdb_list(self, pdb_ids, resume: bool = True):
            observed["pdb_ids"] = list(pdb_ids)
            observed["resume"] = resume
            return [{"pdb_id": "1ABC", "status": "success"}]

        def close_db(self):
            observed["closed"] = True

    monkeypatch.setattr(main_parallel, "ParallelCrawler", DummyCrawler)

    args = _resume_args(
        db=str(db_path),
        input_path=str(input_json),
        checkpoint_dir=str(tmp_path),
    )
    rc = main_parallel.cmd_resume(args)

    assert rc == 0
    assert observed["init"]["db_path"] == str(db_path)
    assert observed["pdb_ids"] == ["1ABC"]
    assert observed["resume"] is True
    assert observed["closed"] is True


def test_resume_writes_to_db_with_db_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "atlas_resume.db"
    db_path.touch()

    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    mgr = CheckpointManager(str(checkpoint_dir))
    mgr.save(CrawlerState(total_ids=1, processed_ids=[]))

    input_json = tmp_path / "ids.json"
    input_json.write_text(json.dumps({"pdb_ids": ["TST1"]}), encoding="utf-8")

    def fake_analyze_single_protein(*_args, **_kwargs):
        return {
            "pdb_id": "TST1",
            "status": "success",
            "runtime": 0.1,
            "total_cavities": 1,
            "druggable_count": 1,
            "high_score": 1,
            "medium_score": 0,
            "top_bio_score": 0.91,
            "cavities": [
                {
                    "id": 0,
                    "rank": 1,
                    "bio_score": 0.91,
                    "volume": 120.0,
                    "center": [1.0, 2.0, 3.0],
                    "radius_geom": 1.1,
                    "radius_clear": 1.2,
                    "merged_vertices": 2,
                    "hydrophobic_ratio": 0.5,
                    "polar_atoms": 1,
                    "druggable": True,
                    "druggability_class": "high",
                    "score_components": {},
                    "profile_used": "Default",
                }
            ],
        }

    class TestCrawler(RealParallelCrawler):
        def __init__(self, *args, **kwargs):
            kwargs["_executor_class"] = ThreadPoolExecutor
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(main_parallel, "ParallelCrawler", TestCrawler)
    monkeypatch.setattr("src.parallel_crawler._analyze_single_protein", fake_analyze_single_protein)

    args = _resume_args(
        db=str(db_path),
        input_path=str(input_json),
        checkpoint_dir=str(checkpoint_dir),
    )
    rc = main_parallel.cmd_resume(args)
    assert rc == 0

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    protein_count = cur.execute("SELECT COUNT(*) FROM proteins").fetchone()[0]
    pocket_count = cur.execute("SELECT COUNT(*) FROM pockets").fetchone()[0]
    conn.close()

    assert protein_count >= 1
    assert pocket_count >= 1
