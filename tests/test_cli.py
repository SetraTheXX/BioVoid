"""Command-line interface regression tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_info_command_emits_project_configuration() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "info"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )

    output = result.stdout + result.stderr
    assert "Bio-Void Hunter v" in output
    assert "Default profile:" in output


def test_cache_stats_command_emits_cache_statistics() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "cache", "stats"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )

    output = result.stdout + result.stderr
    assert "entries:" in output
    assert "hit_rate:" in output


def test_batch_parser_rejects_blank_or_invalid_identifiers() -> None:
    from src.cli import _parse_batch_pdb_ids

    with pytest.raises(ValueError, match="four alphanumeric characters"):
        _parse_batch_pdb_ids("1CBS,,not-a-pdb")


def test_batch_command_returns_failure_when_any_analysis_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import main as pipeline_module
    from src.cli import cmd_batch

    class FailingPipeline:
        def __init__(self, **_: object) -> None:
            pass

        def run(self) -> dict[str, object]:
            raise RuntimeError("synthetic CLI failure")

    monkeypatch.setattr(pipeline_module, "BioVoidPipeline", FailingPipeline)
    args = SimpleNamespace(
        pdb_ids="1CBS,1AKE",
        verbose=False,
        n_frames=1,
        profile="default",
        output="data/runtime/test-cli",
    )

    assert cmd_batch(args) == 1
