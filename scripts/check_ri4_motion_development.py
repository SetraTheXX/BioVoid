"""Verify a completed RI-4 motion development run and its boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = REPO_ROOT / "data/runtime/ri4/ri4-development-motion-run-v1.json"


class RI4CheckError(RuntimeError):
    """Raised when an RI-4 report is incomplete or claim-unsafe."""


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RI4CheckError(f"Cannot read RI-4 report: {path}") from exc
    if not isinstance(payload, dict):
        raise RI4CheckError("RI-4 report must be a JSON object")
    return payload


def _assert_blind(payload: Any, path: str) -> None:
    prohibited = {
        "ground_truth",
        "ground_truth_center",
        "holo",
        "holo_center",
        "known_center",
        "known_ligand",
        "ligand_atoms",
        "ligand_center",
        "ligand_residues",
        "target_center",
        "target_residues",
    }
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
            if normalized in prohibited:
                raise RI4CheckError(f"Evaluator-only key leaked into detector report: {path}.{key}")
            _assert_blind(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            _assert_blind(value, f"{path}[{index}]")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    path = args.run if args.run.is_absolute() else REPO_ROOT / args.run
    payload = _read(path)
    if payload.get("schema_version") != "biovoid-ri4-motion-development-v1":
        raise RI4CheckError("RI-4 report schema mismatch")
    if payload.get("status") != "complete" and not args.allow_partial:
        raise RI4CheckError("RI-4 report is not complete")
    execution = payload.get("execution", {})
    for key, expected in {
        "resource_profile": "safe-16gb",
        "workers": 1,
        "max_heavy_jobs": 1,
        "motion_execution_started": True,
        "canonical_ranking_affected": False,
        "sealed_evaluation_authorized": False,
    }.items():
        if execution.get(key) is not expected and execution.get(key) != expected:
            raise RI4CheckError(f"RI-4 execution boundary mismatch: {key}")
    if payload.get("target_blind_detector_inputs") is not True:
        raise RI4CheckError("RI-4 detector blindness flag is not closed")

    cohort = payload.get("cohort", {})
    case_ids = cohort.get("case_ids")
    structure_ids = cohort.get("structure_ids")
    if not isinstance(case_ids, list) or not isinstance(structure_ids, list):
        raise RI4CheckError("RI-4 exact cohort lists are missing")
    if len(case_ids) != cohort.get("case_count") or len(structure_ids) != cohort.get(
        "structure_count"
    ):
        raise RI4CheckError("RI-4 cohort counts do not match exact lists")
    if _stable_hash(case_ids) != cohort.get("case_ids_sha256"):
        raise RI4CheckError("RI-4 case list hash mismatch")
    if _stable_hash(structure_ids) != cohort.get("structure_ids_sha256"):
        raise RI4CheckError("RI-4 structure list hash mismatch")

    records = payload.get("records", {})
    if not isinstance(records, dict):
        raise RI4CheckError("RI-4 records must be an object")
    if payload.get("status") == "complete" and len(records) != len(structure_ids):
        raise RI4CheckError("Completed RI-4 report does not cover the fixed structure cohort")
    allowed_statuses = {"completed", "resource_blocked", "failed"}
    for structure_id, record in records.items():
        if str(structure_id).upper() not in {str(value).upper() for value in structure_ids}:
            raise RI4CheckError(f"Unexpected structure in RI-4 records: {structure_id}")
        if record.get("status") not in allowed_statuses:
            raise RI4CheckError(f"Invalid RI-4 record status: {structure_id}")
        detector_record = record.get("detector_record")
        if not isinstance(detector_record, dict):
            raise RI4CheckError(f"Missing detector record: {structure_id}")
        if detector_record.get("detector") != "biovoid_motion":
            raise RI4CheckError(f"Motion detector identity mismatch: {structure_id}")
        _assert_blind(detector_record, f"records.{structure_id}.detector_record")
        if "motion_evidence" in record:
            _assert_blind(record["motion_evidence"], f"records.{structure_id}.motion_evidence")

    if payload.get("status") == "complete":
        results = payload.get("results", {})
        for name in ("static", "motion", "null_control", "integration_decision"):
            if name not in results:
                raise RI4CheckError(f"RI-4 result is missing: {name}")
        static = results["static"]
        motion = results["motion"]
        null_summary = results["null_control"]
        if static.get("detector") != "biovoid_static":
            raise RI4CheckError("Static reference detector identity mismatch")
        if motion.get("detector") != "biovoid_motion":
            raise RI4CheckError("Motion result detector identity mismatch")
        if null_summary.get("detector") != "biovoid_motion":
            raise RI4CheckError("Null-control detector identity mismatch")
        for summary in (static, motion, null_summary):
            if summary.get("target_denominator") != cohort.get("case_count"):
                raise RI4CheckError("RI-4 result denominator differs from cohort")
            if summary.get("structure_denominator") != cohort.get("structure_count"):
                raise RI4CheckError("RI-4 structure denominator differs from cohort")
        if payload.get("null_control", {}).get("status") != "pass":
            raise RI4CheckError("RI-4 zero-displacement null control failed")
        decision = results["integration_decision"]
        if decision.get("decision") not in {"ELIGIBLE", "NOT_ELIGIBLE"}:
            raise RI4CheckError("RI-4 integration decision is invalid")
        if decision.get("canonical_integration_eligible") and execution.get(
            "canonical_ranking_affected"
        ):
            raise RI4CheckError("RI-4 canonical ranking was changed by the motion arm")

    run_hash = payload.get("run_sha256")
    if payload.get("status") == "complete":
        expected_hash = _stable_hash({key: value for key, value in payload.items() if key != "run_sha256"})
        if run_hash != expected_hash:
            raise RI4CheckError("RI-4 run hash mismatch")
    print(
        "RI-4 motion development check: PASS "
        f"status={payload.get('status')} "
        f"structures={len(records)}/{len(structure_ids)} "
        f"cases={cohort.get('case_count')}"
    )
    if payload.get("status") == "complete":
        decision = payload["results"]["integration_decision"]
        print(
            f"decision={decision['decision']} "
            f"static_top3_dcc={decision['static_primary_recall']} "
            f"motion_top3_dcc={decision['motion_primary_recall']}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RI4CheckError as exc:
        print(f"RI-4 motion development check: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
