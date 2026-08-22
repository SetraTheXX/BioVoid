"""Run one bounded fpocket/P2Rank baseline on target-family apo inputs.

This runner is intentionally separate from the 663-case RI-3 runner. It accepts
only the prepared apo-only target-family manifest, requires an explicit
``--approve-baselines`` flag before reading that manifest, runs one container at
a time, and never opens evaluator data or writes Atlas.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_target_family_baseline_readiness import (  # noqa: E402
    BASELINE_INPUT_SCHEMA_VERSION,
    DEFAULT_BASELINE_MANIFEST,
    MAX_CASES,
    MAX_DISK_BYTES,
    validate_baseline_input_manifest,
)
from scripts.run_ri3_external_baseline import (  # noqa: E402
    BASELINE_CONFIG,
    BaselineRunError,
    _docker_image_id,
    _record_for_case,
    _safe_child,
)
from scripts.run_target_family_static_pilot import directory_size_bytes  # noqa: E402


BASELINE_RUN_SCHEMA_VERSION = "biovoid-target-family-external-baseline-v1"
RUNNER_ID = "target-family-external-baseline-v1"
DEFAULT_WORK_ROOT = REPO_ROOT / "data/runtime/target-family/external-baselines-pfam-v1"
TARGET_FAMILY_RUNTIME_ROOT = REPO_ROOT / "data/runtime/target-family"


class TargetFamilyBaselineError(RuntimeError):
    """Raised when the bounded external baseline contract cannot proceed."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TargetFamilyBaselineError(f"Cannot read baseline runtime file: {path}") from exc
    if not isinstance(payload, dict):
        raise TargetFamilyBaselineError(f"Expected JSON object: {path}")
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _validate_input_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != BASELINE_INPUT_SCHEMA_VERSION:
        raise TargetFamilyBaselineError("Unexpected target-family baseline input schema")
    try:
        validate_baseline_input_manifest(manifest)
    except ValueError as exc:
        raise TargetFamilyBaselineError(str(exc)) from exc
    structures = manifest.get("structures")
    if not isinstance(structures, list) or not 1 <= len(structures) <= MAX_CASES:
        raise TargetFamilyBaselineError("Target-family baseline case count is outside the bounded range")


def build_initial_report(
    *,
    baseline: str,
    manifest: Mapping[str, Any],
    image_id: str,
) -> dict[str, Any]:
    config = BASELINE_CONFIG[baseline]
    return {
        "schema_version": BASELINE_RUN_SCHEMA_VERSION,
        "runner": RUNNER_ID,
        "status": "not_started",
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "tool": baseline,
        "tool_version": config["version"],
        "tool_commit": config["commit"],
        "container_image": config["image"],
        "container_image_id": image_id,
        "manifest_sha256": manifest["manifest_sha256"],
        "target_blind": True,
        "evaluator_opened": False,
        "sealed_evaluation_authorized": False,
        "claims_authorized": False,
        "resource_limits": {
            "workers": 1,
            "cpus": 1,
            "memory": config["memory"],
            "timeout_seconds": config["timeout_seconds"],
            "max_disk_bytes": MAX_DISK_BYTES,
        },
        "records": {},
        "counts": {"completed": 0, "failed": 0},
    }


def validate_baseline_report(
    report: Mapping[str, Any],
    *,
    baseline: str,
    manifest: Mapping[str, Any],
    image_id: str,
) -> None:
    config = BASELINE_CONFIG[baseline]
    if report.get("schema_version") != BASELINE_RUN_SCHEMA_VERSION:
        raise TargetFamilyBaselineError("Target-family baseline report schema mismatch")
    if report.get("runner") != RUNNER_ID:
        raise TargetFamilyBaselineError("Target-family baseline runner identity mismatch")
    if report.get("tool") != baseline or report.get("tool_commit") != config["commit"]:
        raise TargetFamilyBaselineError("Target-family baseline identity mismatch")
    if report.get("container_image_id") != image_id:
        raise TargetFamilyBaselineError("Target-family baseline image changed after checkpoint")
    if report.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise TargetFamilyBaselineError("Target-family baseline manifest hash mismatch")
    if (
        report.get("target_blind") is not True
        or report.get("evaluator_opened") is not False
        or report.get("sealed_evaluation_authorized") is not False
        or report.get("claims_authorized") is not False
    ):
        raise TargetFamilyBaselineError("Target-family baseline claim boundary is invalid")
    limits = report.get("resource_limits")
    if not isinstance(limits, Mapping):
        raise TargetFamilyBaselineError("Target-family baseline resource limits are missing")
    if limits.get("workers") != 1 or limits.get("cpus") != 1:
        raise TargetFamilyBaselineError("Target-family baseline is not single-worker")
    if limits.get("memory") != config["memory"] or limits.get("max_disk_bytes") != MAX_DISK_BYTES:
        raise TargetFamilyBaselineError("Target-family baseline resource limits drifted")


def _update_counts(report: dict[str, Any]) -> None:
    records = report.get("records", {})
    if not isinstance(records, Mapping):
        records = {}
    report["counts"] = {
        "completed": sum(item.get("detector_status") == "completed" for item in records.values()),
        "failed": sum(item.get("detector_status") == "failed" for item in records.values()),
    }


def run_target_family_baseline(
    *,
    baseline: str,
    manifest_path: Path = DEFAULT_BASELINE_MANIFEST,
    work_root: Path = DEFAULT_WORK_ROOT,
    report_path: Path | None = None,
    max_cases: int = MAX_CASES,
    batch_size: int = 2,
    user_approved: bool = False,
    force_recompute: bool = False,
) -> dict[str, Any]:
    """Run an explicitly approved, one-tool target-family baseline."""

    if not user_approved:
        raise TargetFamilyBaselineError(
            "Target-family baseline requires explicit user approval (--approve-baselines)"
        )
    if baseline not in BASELINE_CONFIG:
        raise TargetFamilyBaselineError(f"Unsupported baseline: {baseline}")
    if not 1 <= max_cases <= MAX_CASES:
        raise TargetFamilyBaselineError("max_cases must be between 1 and 10")
    if not 1 <= batch_size <= 10:
        raise TargetFamilyBaselineError("batch_size must be between 1 and 10")
    manifest = _read_json(manifest_path.resolve())
    _validate_input_manifest(manifest)
    structures = sorted(manifest["structures"], key=lambda item: str(item["structure_id"]))
    image_id = _docker_image_id(str(BASELINE_CONFIG[baseline]["image"]))
    safe_work_root = _safe_child(TARGET_FAMILY_RUNTIME_ROOT, work_root)
    safe_work_root.mkdir(parents=True, exist_ok=True)
    report_path = report_path or safe_work_root / f"{baseline}-target-family-v1.json"
    report_path = report_path if report_path.is_absolute() else REPO_ROOT / report_path
    report = (
        _read_json(report_path)
        if report_path.is_file() and not force_recompute
        else build_initial_report(baseline=baseline, manifest=manifest, image_id=image_id)
    )
    validate_baseline_report(report, baseline=baseline, manifest=manifest, image_id=image_id)
    report["records"] = dict(report.get("records", {}))
    pending = [
        item
        for item in structures
        if str(item["structure_id"]).upper() not in report["records"]
    ]
    selected = pending[:max_cases]
    run_root = _safe_child(safe_work_root, safe_work_root / baseline)
    run_root.mkdir(parents=True, exist_ok=True)
    if directory_size_bytes(safe_work_root) > MAX_DISK_BYTES:
        raise TargetFamilyBaselineError("Target-family baseline disk quota is already exceeded")
    report["status"] = "running"
    report["updated_at_utc"] = _utc_now()
    for index, structure in enumerate(selected, start=1):
        structure_id = str(structure["structure_id"]).upper()
        print(f"[{index}/{len(selected)}] {baseline} {structure_id}", flush=True)
        record, execution = _record_for_case(
            tool=baseline,
            config=BASELINE_CONFIG[baseline],
            image_id=image_id,
            structure=structure,
            work_root=run_root,
            runner_id=RUNNER_ID,
        )
        detector_payload = execution.get("detector_record")
        if isinstance(detector_payload, Mapping):
            detector_payload = dict(detector_payload)
            detector_payload["provenance"] = {
                **dict(detector_payload.get("provenance") or {}),
                "runtime_seconds": execution.get("runtime_seconds"),
                "return_code": execution.get("return_code"),
            }
        report["records"][structure_id] = {
            **execution,
            "case_id": structure["case_id"],
            "structure_id": structure_id,
            "detector_status": record.status,
            "detector_record": detector_payload,
        }
        _update_counts(report)
        report["updated_at_utc"] = _utc_now()
        if directory_size_bytes(safe_work_root) > MAX_DISK_BYTES:
            raise TargetFamilyBaselineError("Target-family baseline disk quota exceeded")
        if index % batch_size == 0 or index == len(selected):
            _write_json_atomic(report_path, report)
            print(f"baseline checkpoint counts={report['counts']}", flush=True)
    _update_counts(report)
    report["status"] = (
        "complete_with_failures"
        if len(report["records"]) == len(structures) and report["counts"]["failed"]
        else "complete"
        if len(report["records"]) == len(structures)
        else "partial"
    )
    report["updated_at_utc"] = _utc_now()
    report["report_sha256"] = _stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    _write_json_atomic(report_path, report)
    print(
        f"target-family {baseline}: {report['status']} "
        f"records={len(report['records'])}/{len(structures)} "
        f"completed={report['counts']['completed']} failed={report['counts']['failed']}"
    )
    print(f"baseline report: {report_path}")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", choices=tuple(BASELINE_CONFIG), required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_BASELINE_MANIFEST)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--max-cases", type=int, default=MAX_CASES)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--approve-baselines", action="store_true")
    parser.add_argument("--recompute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.approve_baselines:
        print(
            "Pass --approve-baselines after explicit user authorization; no manifest is read.",
            file=sys.stderr,
        )
        return 2
    try:
        report = run_target_family_baseline(
            baseline=args.baseline,
            manifest_path=args.manifest,
            work_root=args.work_root,
            report_path=args.report,
            max_cases=args.max_cases,
            batch_size=args.batch_size,
            user_approved=True,
            force_recompute=args.recompute,
        )
    except (TargetFamilyBaselineError, BaselineRunError) as exc:
        print(f"target-family baseline error: {exc}", file=sys.stderr)
        return 2
    return 0 if report["status"] in {"complete", "complete_with_failures"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
