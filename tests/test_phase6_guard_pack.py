"""Tests for Phase 6 ops guard pack script."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_guard_pack_dry_run_writes_outputs(tmp_path: Path) -> None:
    output_json = tmp_path / "guard_pack.json"
    output_md = tmp_path / "guard_pack.md"

    cmd = [
        sys.executable,
        "scripts/run_phase6_ops_guard_pack.py",
        "--dry-run",
        "--output-json",
        str(output_json),
        "--output-md",
        str(output_md),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0
    assert output_json.exists()
    assert output_md.exists()

    payload = json.loads(output_json.read_text())
    assert payload["overall_status"] == "SKIPPED"
    assert len(payload["results"]) == 3
