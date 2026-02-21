"""Phase 6 Step 5 integration suite runner."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Phase 6 final integration suite and staging canary checks."
    )
    parser.add_argument("--jobs", type=int, default=80, help="Canary job count")
    parser.add_argument("--poll-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--p95-latency-max-seconds", type=float, default=2.5)
    parser.add_argument(
        "--output-json",
        default="data/validation/phase6_step5_integration_suite.json",
    )
    parser.add_argument(
        "--output-md",
        default="docs/phase6_step5_integration_snapshot.md",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def run_subprocess(cmd: list[str]) -> dict[str, Any]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "command": cmd,
        "return_code": proc.returncode,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def run_canary(jobs: int, timeout_seconds: float, p95_max: float) -> dict[str, Any]:
    from fastapi.testclient import TestClient

    from src.api.app import create_app
    from src.api.orchestrator import JobOrchestrator
    from src.api.rate_limit import InMemoryRateLimiter

    orchestrator = JobOrchestrator(
        default_timeout_seconds=2.0,
        default_max_retries=1,
        backoff_base_seconds=0.01,
    )
    limiter = InMemoryRateLimiter(max_requests=100_000, window_seconds=60)
    client = TestClient(create_app(orchestrator=orchestrator, rate_limiter=limiter))

    submitted_ids: list[str] = []
    submit_failures: list[dict[str, Any]] = []

    with client:
        started = time.monotonic()
        for idx in range(jobs):
            pdb_id = f"A{idx:03d}"
            response = client.post(
                "/jobs",
                headers={"Idempotency-Key": f"step5-canary-{idx}"},
                json={
                    "job_type": "quick_probe",
                    "input": {"pdb_id": pdb_id},
                    "options": {"timeout_seconds": 2, "max_retries": 1, "priority": "normal"},
                },
            )
            if response.status_code != 202:
                submit_failures.append(
                    {
                        "index": idx,
                        "status_code": response.status_code,
                        "body": response.json(),
                    }
                )
            else:
                submitted_ids.append(response.json()["job_id"])

        terminal: dict[str, dict[str, Any]] = {}
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and len(terminal) < len(submitted_ids):
            for job_id in submitted_ids:
                if job_id in terminal:
                    continue
                status_resp = client.get(f"/jobs/{job_id}")
                if status_resp.status_code != 200:
                    terminal[job_id] = {"status": "unknown", "error": status_resp.text}
                    continue
                payload = status_resp.json()
                if payload["status"] in {"succeeded", "failed"}:
                    terminal[job_id] = payload
            if len(terminal) < len(submitted_ids):
                time.sleep(0.02)

        timed_out_jobs = [job_id for job_id in submitted_ids if job_id not in terminal]

        download_ok = 0
        download_fail = 0
        for job_id, payload in terminal.items():
            if payload.get("status") != "succeeded":
                continue
            dl = client.get(f"/jobs/{job_id}/result")
            if dl.status_code == 200:
                download_ok += 1
            else:
                download_fail += 1

        metrics_resp = client.get("/ops/metrics")
        metrics = metrics_resp.json() if metrics_resp.status_code == 200 else {}
        elapsed = time.monotonic() - started

    succeeded = sum(1 for row in terminal.values() if row.get("status") == "succeeded")
    failed = sum(1 for row in terminal.values() if row.get("status") == "failed")
    p95_latency = float(metrics.get("p95_job_latency_seconds", 0.0))
    canary_pass = (
        len(submit_failures) == 0
        and len(timed_out_jobs) == 0
        and failed == 0
        and succeeded == len(submitted_ids)
        and download_fail == 0
        and p95_latency <= p95_max
    )

    return {
        "status": "PASS" if canary_pass else "FAIL",
        "jobs_requested": jobs,
        "jobs_submitted": len(submitted_ids),
        "submit_failures": submit_failures,
        "jobs_succeeded": succeeded,
        "jobs_failed": failed,
        "jobs_timed_out_polling": timed_out_jobs,
        "result_download_ok": download_ok,
        "result_download_fail": download_fail,
        "elapsed_seconds": round(elapsed, 3),
        "p95_latency_seconds": p95_latency,
        "p95_latency_max_seconds": p95_max,
        "ops_metrics_snapshot": metrics,
    }


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Phase 6 Step 5 Integration Snapshot",
        "",
        f"- Generated at (UTC): {payload['generated_at_utc']}",
        f"- Overall status: **{payload['overall_status']}**",
        f"- Dry run: `{payload['dry_run']}`",
        "",
        "## Command Pack",
        "",
        "| Command | Status | Return Code |",
        "| --- | --- | ---: |",
    ]
    for row in payload["command_results"]:
        cmd = " ".join(row["command"])
        lines.append(f"| `{cmd}` | {row['status']} | {row['return_code']} |")

    canary = payload["canary"]
    lines.extend(
        [
            "",
            "## Canary Summary",
            "",
            f"- status: `{canary['status']}`",
            f"- jobs_requested: `{canary['jobs_requested']}`",
            f"- jobs_submitted: `{canary['jobs_submitted']}`",
            f"- jobs_succeeded: `{canary['jobs_succeeded']}`",
            f"- jobs_failed: `{canary['jobs_failed']}`",
            f"- p95_latency_seconds: `{canary['p95_latency_seconds']}` (max `{canary['p95_latency_max_seconds']}`)",
            f"- result_download_ok: `{canary['result_download_ok']}`",
            f"- result_download_fail: `{canary['result_download_fail']}`",
        ]
    )
    path.write_text("\n".join(lines))


def main() -> int:
    args = parse_args()

    commands = [
        [
            "python",
            "scripts/run_phase6_ops_guard_pack.py",
            "--strict-recall-floor",
            "0.30",
            "--strict-overlap-floor",
            "0.25",
        ],
        [
            "python",
            "-m",
            "pytest",
            "tests/test_phase6_api.py",
            "tests/test_phase6_portal.py",
            "tests/test_phase6_ops.py",
            "tests/test_phase6_guard_pack.py",
            "-q",
        ],
    ]

    if args.dry_run:
        command_results = [
            {"command": cmd, "return_code": 0, "status": "SKIPPED", "stdout": "", "stderr": ""}
            for cmd in commands
        ]
        canary = {
            "status": "SKIPPED",
            "jobs_requested": args.jobs,
            "jobs_submitted": 0,
            "submit_failures": [],
            "jobs_succeeded": 0,
            "jobs_failed": 0,
            "jobs_timed_out_polling": [],
            "result_download_ok": 0,
            "result_download_fail": 0,
            "elapsed_seconds": 0.0,
            "p95_latency_seconds": 0.0,
            "p95_latency_max_seconds": args.p95_latency_max_seconds,
            "ops_metrics_snapshot": {},
        }
        overall = "SKIPPED"
        exit_code = 0
    else:
        command_results = [run_subprocess(cmd) for cmd in commands]
        canary = run_canary(
            jobs=args.jobs,
            timeout_seconds=args.poll_timeout_seconds,
            p95_max=args.p95_latency_max_seconds,
        )
        overall = (
            "PASS"
            if all(r["return_code"] == 0 for r in command_results) and canary["status"] == "PASS"
            else "FAIL"
        )
        exit_code = 0 if overall == "PASS" else 1

    payload = {
        "generated_at_utc": utc_now_iso(),
        "dry_run": args.dry_run,
        "overall_status": overall,
        "command_results": command_results,
        "canary": canary,
    }

    out_json = Path(args.output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2))

    out_md = Path(args.output_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    write_markdown(out_md, payload)

    print(f"[INFO] overall_status={overall}")
    print(f"[OK] wrote {out_json}")
    print(f"[OK] wrote {out_md}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
