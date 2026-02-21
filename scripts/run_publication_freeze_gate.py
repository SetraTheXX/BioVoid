#!/usr/bin/env python3
"""
Publication Freeze Gate Runner
===============================

One-command verification that runs all pre-publication checks in order
and emits a final PASS/FAIL decision.

Steps:
  1. SoT alignment guard
  2. Regression guard
  3. Build repro bundle
  4. Verify repro bundle

Outputs:
  - data/validation/publication_freeze_gate_v1.json
  - docs/publication_freeze_gate_v1.md

Exit codes:
  0 = all steps PASS
  1 = one or more steps FAIL
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_JSON = REPO_ROOT / "data" / "validation" / "publication_freeze_gate_v1.json"
OUTPUT_MD = REPO_ROOT / "docs" / "publication_freeze_gate_v1.md"

STEPS = [
    {
        "name": "SoT alignment guard",
        "cmd": [sys.executable, str(REPO_ROOT / "scripts" / "check_sot_alignment_guard.py")],
        "result_json": REPO_ROOT / "data" / "validation" / "sot_alignment_guard.json",
        "status_key": "status",
    },
    {
        "name": "Regression guard",
        "cmd": [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_recovery_v2_regression_guard.py"),
            "--fpocket-report", "docs/fpocket_benchmark_report.md",
        ],
        "result_json": REPO_ROOT / "data" / "validation" / "recovery_v2_regression_guard.json",
        "status_key": "overall_regression_guard_status",
    },
    {
        "name": "Build repro bundle",
        "cmd": [sys.executable, str(REPO_ROOT / "scripts" / "build_publication_repro_bundle.py")],
        "result_json": REPO_ROOT / "artifacts" / "publication_repro_bundle_v1" / "manifest.json",
        "status_key": None,  # PASS if exit code == 0
    },
    {
        "name": "Verify repro bundle",
        "cmd": [sys.executable, str(REPO_ROOT / "scripts" / "verify_publication_repro_bundle.py")],
        "result_json": REPO_ROOT / "data" / "validation" / "publication_repro_verify_v1.json",
        "status_key": "status",
    },
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def main() -> int:
    print("=" * 60)
    print("  PUBLICATION FREEZE GATE v1")
    print("=" * 60)
    print()

    results: list[dict[str, Any]] = []
    all_pass = True

    for step in STEPS:
        name = step["name"]
        print(f"[STEP] {name}...")

        try:
            proc = subprocess.run(
                step["cmd"],
                capture_output=True, text=True, timeout=120,
                cwd=str(REPO_ROOT),
            )
            exit_code = proc.returncode
        except Exception as exc:
            exit_code = 1
            proc = None
            print(f"  [ERROR] {exc}")

        # Determine status
        status = "FAIL"
        detail = ""

        if exit_code == 0:
            if step["status_key"]:
                result_data = _load_json(step["result_json"])
                if result_data:
                    status = result_data.get(step["status_key"], "FAIL")
                    detail = f"from {step['result_json'].name}"
                else:
                    status = "PASS"
                    detail = "exit_code=0, result_json not found"
            else:
                status = "PASS"
                detail = "exit_code=0"
        else:
            detail = f"exit_code={exit_code}"

        if status != "PASS":
            all_pass = False

        results.append({
            "step": name,
            "status": status,
            "exit_code": exit_code,
            "detail": detail,
        })
        print(f"  [{status}] {detail}")
        print()

    overall = "PASS" if all_pass else "FAIL"

    print("=" * 60)
    print(f"  FREEZE GATE DECISION: {overall}")
    print("=" * 60)

    # Write JSON
    output = {
        "generated_at_utc": _utc_now_iso(),
        "overall_status": overall,
        "steps": results,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n[INFO] Wrote: {OUTPUT_JSON}")

    # Write report
    lines = [
        "# Publication Freeze Gate v1",
        "",
        f"- Generated: {_utc_now_iso()}",
        f"- Overall decision: **{overall}**",
        "",
        "---",
        "",
        "## Step Results",
        "",
        "| # | Step | Status | Exit Code | Detail |",
        "|---|------|--------|-----------|--------|",
    ]
    for i, r in enumerate(results, 1):
        s = f"**{r['status']}**" if r["status"] != "PASS" else r["status"]
        lines.append(f"| {i} | {r['step']} | {s} | {r['exit_code']} | {r['detail']} |")

    lines += [
        "",
        "---",
        "",
        f"## Decision: **{overall}**",
        "",
    ]
    if overall == "PASS":
        lines.append("All pre-publication checks passed. The reproducibility bundle is verified and ready for publication handoff.")
    else:
        lines.append("One or more checks failed. Review the errors above before proceeding.")
    lines.append("")

    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[INFO] Wrote: {OUTPUT_MD}")

    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
