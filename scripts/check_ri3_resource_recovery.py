"""Verify the bounded secondary RI-3 resource-recovery evidence."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_ri3_static_resource_recovery import (  # noqa: E402
    DEFAULT_MANIFEST,
    DEFAULT_PRIMARY_RUN,
    RUN_SCHEMA_VERSION,
    _profile_hash,
    _stable_hash,
)
from src.evaluator_format import assert_detector_payload_is_blind  # noqa: E402
from src.resources import RI3_STATIC_RECOVERY  # noqa: E402


class RI3RecoveryCheckError(RuntimeError):
    """Raised when bounded recovery evidence is inconsistent."""


DEFAULT_RECOVERY_RUN = REPO_ROOT / "data/runtime/ri3/ri3-static-resource-recovery-v2.json"


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RI3RecoveryCheckError(f"Missing recovery evidence: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RI3RecoveryCheckError(f"Expected JSON object: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check(
    report: Mapping[str, Any],
    primary: Mapping[str, Any],
    *,
    primary_path: Path,
) -> dict[str, int]:
    if report.get("schema_version") != RUN_SCHEMA_VERSION:
        raise RI3RecoveryCheckError("Unexpected recovery report schema")
    if report.get("status") != "complete":
        raise RI3RecoveryCheckError("Recovery report is not complete")
    if report.get("primary_run_sha256") != _sha256_file(primary_path):
        raise RI3RecoveryCheckError("Recovery report is not tied to the selected primary run")
    if report.get("profile", {}).get("profile_sha256") != _profile_hash():
        raise RI3RecoveryCheckError("Recovery profile hash does not match local policy")
    if report.get("execution", {}).get("workers") != 1:
        raise RI3RecoveryCheckError("Recovery report is not single-worker")
    if report.get("execution", {}).get("canonical_result_promotion") is not False:
        raise RI3RecoveryCheckError("Recovery report permits canonical promotion")
    if report.get("execution", {}).get("nma_started") is not False:
        raise RI3RecoveryCheckError("Recovery report has NMA enabled")
    if report.get("execution", {}).get("sealed_evaluation_authorized") is not False:
        raise RI3RecoveryCheckError("Recovery report has sealed evaluation enabled")
    if report.get("target_blind") is not True:
        raise RI3RecoveryCheckError("Recovery report is not target-blind")

    primary_blocked = {
        structure_id
        for structure_id, record in primary.get("records", {}).items()
        if record.get("status") == "resource_blocked"
    }
    records = report.get("records", {})
    if set(records) != primary_blocked:
        raise RI3RecoveryCheckError("Recovery records do not exactly cover primary blocked cases")

    counts = Counter()
    for structure_id, record in records.items():
        status = str(record.get("status", ""))
        counts[status] += 1
        if record.get("canonical_static_result") is not False:
            raise RI3RecoveryCheckError(f"Canonical promotion flag set for {structure_id}")
        if record.get("nma_started") is not False or record.get("sealed_evaluation_authorized") is not False:
            raise RI3RecoveryCheckError(f"Closed gate changed for {structure_id}")
        detector_payload = record.get("detector_record")
        if detector_payload is None:
            if not (
                status == "resource_blocked"
                and record.get("recovery_eligible") is False
                and "atom limit exceeded" in str(record.get("error", ""))
            ):
                raise RI3RecoveryCheckError(f"Detector payload missing for {structure_id}")
            # The bounded profile intentionally does not start an out-of-range
            # process. The terminal record itself is the evidence of non-attempt.
            continue
        if not isinstance(detector_payload, Mapping):
            raise RI3RecoveryCheckError(f"Detector payload has an invalid shape for {structure_id}")
        try:
            assert_detector_payload_is_blind(detector_payload, path=f"records.{structure_id}")
        except ValueError as exc:
            raise RI3RecoveryCheckError(str(exc)) from exc
        expected_detector_status = {
            "completed": "completed",
            "resource_blocked": "unavailable",
            "guard_terminated": "unavailable",
            "timeout": "unavailable",
            "failed": "failed",
        }.get(status)
        if detector_payload.get("status") != expected_detector_status:
            raise RI3RecoveryCheckError(f"Detector status mismatch for {structure_id}")
        if int(record.get("peak_rss_bytes", 0)) > int(
            report["profile"]["parent_rss_limit_bytes"]
        ):
            raise RI3RecoveryCheckError(f"RSS guard was exceeded without a terminal guard status: {structure_id}")

    expected_counts = {
        "completed": counts["completed"],
        "resource_blocked": counts["resource_blocked"],
        "failed": counts["failed"],
        "guard_terminated": counts["guard_terminated"],
        "timeout": counts["timeout"],
    }
    if report.get("counts") != expected_counts:
        raise RI3RecoveryCheckError("Recovery counts do not match records")
    if expected_counts["failed"]:
        raise RI3RecoveryCheckError("Recovery contains unexpected detector failures")
    return expected_counts


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-run", type=Path, default=DEFAULT_PRIMARY_RUN)
    parser.add_argument("--recovery", type=Path, default=DEFAULT_RECOVERY_RUN)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    primary_path = _resolve(args.primary_run)
    report = _read_json(_resolve(args.recovery))
    primary = _read_json(primary_path)
    counts = _check(report, primary, primary_path=primary_path)
    print("RI-3 bounded resource-recovery evidence check: PASS")
    print(f"profile: {RI3_STATIC_RECOVERY.name}")
    print(f"counts: {json.dumps(counts, sort_keys=True)}")
    print("target-blind detector payloads: PASS")
    print("canonical promotion: CLOSED")
    print("NMA/sealed: CLOSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RI3RecoveryCheckError as exc:
        print(f"RI-3 recovery evidence error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
