"""Verify the local RI-3 static detector and evaluator evidence contracts."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_ri3_static_development import (  # noqa: E402
    DEFAULT_REPORT as DEFAULT_EVALUATION_REPORT,
    REPORT_SCHEMA_VERSION as EVALUATION_SCHEMA_VERSION,
    _validate_report,
)
from scripts.run_ri3_static_development import (  # noqa: E402
    DEFAULT_MANIFEST,
    DEFAULT_RUN,
    MANIFEST_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    _stable_hash,
    _validate_manifest,
    _validate_run,
)
from src.evaluator_format import assert_detector_payload_is_blind  # noqa: E402


class RI3CheckError(RuntimeError):
    """Raised when local RI-3 evidence fails an integrity check."""


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RI3CheckError(f"Missing RI-3 runtime evidence: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RI3CheckError(f"Expected JSON object: {path}")
    return payload


def _check_static_run(manifest: Mapping[str, Any], run: Mapping[str, Any]) -> dict[str, int]:
    if run.get("schema_version") != RUN_SCHEMA_VERSION:
        raise RI3CheckError("Unexpected static run schema")
    _validate_run(run, manifest)
    if run.get("status") != "complete":
        raise RI3CheckError("Static RI-3 run is not complete")
    expected_ids = {item["structure_id"] for item in manifest["structures"]}
    records = run.get("records", {})
    if set(records) != expected_ids:
        raise RI3CheckError("Static run record IDs differ from the runtime manifest")
    counts = Counter()
    for structure_id, record in records.items():
        status = record.get("status")
        counts[status] += 1
        detector_payload = record.get("detector_record")
        if not isinstance(detector_payload, Mapping):
            raise RI3CheckError(f"Detector payload missing for {structure_id}")
        try:
            assert_detector_payload_is_blind(detector_payload, path=f"records.{structure_id}")
        except ValueError as exc:
            raise RI3CheckError(str(exc)) from exc
        detector_status = detector_payload.get("status")
        expected_detector_status = {
            "completed": "completed",
            "resource_blocked": "unavailable",
            "failed": "failed",
        }.get(status)
        if expected_detector_status != detector_status:
            raise RI3CheckError(
                f"Status mismatch for {structure_id}: {status} vs {detector_status}"
            )
        if record.get("prepared_structure_sha256") != next(
            item["prepared_structure_sha256"]
            for item in manifest["structures"]
            if item["structure_id"] == structure_id
        ):
            raise RI3CheckError(f"Prepared hash mismatch for {structure_id}")
    expected_counts = {
        "completed": counts["completed"],
        "resource_blocked": counts["resource_blocked"],
        "failed": counts["failed"],
    }
    if run.get("counts") != expected_counts:
        raise RI3CheckError("Static run counts do not match its records")
    if expected_counts["failed"]:
        raise RI3CheckError("Static run contains unexpected detector failures")
    return expected_counts


def _check_evaluation(
    manifest: Mapping[str, Any],
    report: Mapping[str, Any],
) -> dict[str, int]:
    if report.get("schema_version") != EVALUATION_SCHEMA_VERSION:
        raise RI3CheckError("Unexpected evaluator report schema")
    _validate_report(report, manifest)
    if report.get("status") != "complete" or len(report.get("records", {})) != 825:
        raise RI3CheckError("Evaluator report does not cover all 825 cases")
    case_map = {
        case["case_id"]: case for case in manifest["benchmark_manifest"]["cases"]
    }
    records = report["records"]
    if set(records) != set(case_map):
        raise RI3CheckError("Evaluator case IDs differ from the runtime manifest")
    counts = Counter()
    for case_id, record in records.items():
        status = record.get("status")
        counts[status] += 1
        if status == "completed_ground_truth":
            ground_truth = record.get("ground_truth")
            evaluation = record.get("case_evaluation")
            if not isinstance(ground_truth, Mapping) or not isinstance(evaluation, Mapping):
                raise RI3CheckError(f"Accepted evaluator case is incomplete: {case_id}")
            if ground_truth.get("case_id") != case_id:
                raise RI3CheckError(f"Ground-truth case identity mismatch: {case_id}")
            if ground_truth.get("coordinate_frame_sha256") != case_map[case_id][
                "prepared_structure_sha256"
            ]:
                raise RI3CheckError(f"Ground-truth frame mismatch: {case_id}")
    expected_counts = {
        "completed_ground_truth": counts["completed_ground_truth"],
        "alignment_unavailable": counts["alignment_unavailable"],
        "download_failed": counts["download_failed"],
    }
    if report.get("counts") != expected_counts:
        raise RI3CheckError("Evaluator report counts do not match its records")
    summary = report.get("summary", {})
    if summary.get("scientific_superiority_claim_authorized") is not False:
        raise RI3CheckError("Evaluator report authorizes an unsupported superiority claim")
    return expected_counts


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--evaluation", type=Path, default=DEFAULT_EVALUATION_REPORT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    manifest_path = args.manifest if args.manifest.is_absolute() else REPO_ROOT / args.manifest
    static_path = args.static_run if args.static_run.is_absolute() else REPO_ROOT / args.static_run
    evaluation_path = args.evaluation if args.evaluation.is_absolute() else REPO_ROOT / args.evaluation
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise RI3CheckError("Unexpected target-blind manifest schema")
    _validate_manifest(manifest)
    static_counts = _check_static_run(manifest, _read_json(static_path))
    evaluation_counts = _check_evaluation(manifest, _read_json(evaluation_path))
    print("RI-3 static/evaluator evidence check: PASS")
    print(f"manifest sha256: {manifest['manifest_sha256']}")
    print(f"static counts: {json.dumps(static_counts, sort_keys=True)}")
    print(f"evaluator counts: {json.dumps(evaluation_counts, sort_keys=True)}")
    print("target blind detector payloads: PASS")
    print("DCC/DCA claim authorization: CLOSED")
    print("NMA/sealed: CLOSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RI3CheckError as exc:
        print(f"RI-3 evidence check error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
