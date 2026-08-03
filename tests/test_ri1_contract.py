"""Offline regression checks for the RI-1 source-only research contract."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.private


def test_ri1_contract_check_passes_without_data_download() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_ri1_contract.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Sealed evaluation: blocked" in result.stdout
