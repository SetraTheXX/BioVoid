"""Tests for Phase 6 Step 5 integration suite script."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_step5_suite_dry_run_outputs(tmp_path: Path) -> None:
    out_json = tmp_path / "step5_suite.json"
    out_md = tmp_path / "step5_suite.md"

    cmd = [
        sys.executable,
        "scripts/run_phase6_step5_integration_suite.py",
        "--dry-run",
        "--output-json",
        str(out_json),
        "--output-md",
        str(out_md),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0
    assert out_json.exists()
    assert out_md.exists()

    payload = json.loads(out_json.read_text())
    assert payload["overall_status"] == "SKIPPED"
    assert len(payload["command_results"]) == 2
    assert payload["canary"]["status"] == "SKIPPED"
