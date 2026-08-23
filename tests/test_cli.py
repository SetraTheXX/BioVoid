"""Command-line interface regression tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


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
