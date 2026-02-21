"""Phase 6 Step 4 guard command pack runner."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run strict gate/guard/intake command pack for Phase 6 ops guard."
    )
    parser.add_argument("--strict-recall-floor", type=float, default=0.30)
    parser.add_argument("--strict-overlap-floor", type=float, default=0.25)
    parser.add_argument(
        "--output-json",
        default="data/validation/phase6_ops_guard_pack.json",
    )
    parser.add_argument(
        "--output-md",
        default="docs/phase6_step4_guard_snapshot.md",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands but do not execute.",
    )
    return parser.parse_args()


def build_commands(args: argparse.Namespace) -> list[list[str]]:
    return [
        [
            "python",
            "scripts/generate_phase5_5_gate_decision.py",
            "--gate-profile",
            "strict",
            "--fpocket-report",
            "docs/fpocket_benchmark_report.md",
        ],
        [
            "python",
            "scripts/run_recovery_v2_regression_guard.py",
            "--fpocket-report",
            "docs/fpocket_benchmark_report.md",
        ],
        [
            "python",
            "scripts/recovery_v2_intake_check.py",
            "--strict",
            "--recall-floor",
            str(args.strict_recall_floor),
            "--overlap-floor",
            str(args.strict_overlap_floor),
        ],
    ]


def run_command(cmd: list[str]) -> dict[str, Any]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "command": cmd,
        "return_code": proc.returncode,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Phase 6 Step 4 Guard Snapshot",
        "",
        f"- Generated at (UTC): {report['generated_at_utc']}",
        f"- Dry run: `{report['dry_run']}`",
        f"- Overall: **{report['overall_status']}**",
        "",
        "| Command | Status | Return Code |",
        "| --- | --- | ---: |",
    ]
    for row in report["results"]:
        cmd = " ".join(row["command"])
        lines.append(f"| `{cmd}` | {row['status']} | {row['return_code']} |")
    lines.append("")
    path.write_text("\n".join(lines))


def main() -> int:
    args = parse_args()
    commands = build_commands(args)
    results: list[dict[str, Any]] = []

    if args.dry_run:
        for cmd in commands:
            results.append(
                {
                    "command": cmd,
                    "return_code": 0,
                    "status": "SKIPPED",
                    "stdout": "",
                    "stderr": "",
                }
            )
        overall = "SKIPPED"
        exit_code = 0
    else:
        for cmd in commands:
            row = run_command(cmd)
            results.append(row)
        overall = "PASS" if all(x["return_code"] == 0 for x in results) else "FAIL"
        exit_code = 0 if overall == "PASS" else 1

    report = {
        "generated_at_utc": utc_now_iso(),
        "dry_run": args.dry_run,
        "strict_recall_floor": args.strict_recall_floor,
        "strict_overlap_floor": args.strict_overlap_floor,
        "overall_status": overall,
        "results": results,
    }

    out_json = Path(args.output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2))

    out_md = Path(args.output_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    write_markdown(out_md, report)

    print(f"[INFO] overall_status={overall}")
    print(f"[OK] wrote {out_json}")
    print(f"[OK] wrote {out_md}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
