"""Validate the RI-6 target lock and bounded TEM-1 control evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_ri6_tem1_transfer_control import (  # noqa: E402
    RI6ContractError,
    _stable_hash,
    _validate_target_blind_manifest,
)
from scripts.run_ri6_prospective_static import (  # noqa: E402
    _validate_prospective_output,
)
from scripts.close_ri6_without_claim import _validate_closure_record  # noqa: E402
from scripts.review_ri6_prospective_static import _validate_review  # noqa: E402


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RI6ContractError(f"Required RI-6 evidence is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RI6ContractError(f"Expected a JSON object: {path}")
    return payload


def _validate_hash(payload: Mapping[str, Any], field: str) -> None:
    expected = _stable_hash({key: value for key, value in payload.items() if key != field})
    if payload.get(field) != expected:
        raise RI6ContractError(f"{field} does not match the evidence content")


def _validate_target_lock(payload: Mapping[str, Any]) -> None:
    _validate_hash(payload, "lock_sha256")
    if payload.get("status") != "frozen_before_candidate_screening":
        raise RI6ContractError("RI-6 target lock is not frozen")
    leakage = payload.get("leakage_control", {})
    if leakage.get("exact_accession_overlap") != []:
        raise RI6ContractError("RI-6 target has exact CryptoBench leakage")
    if leakage.get("known_family_overlap") != ["A2RP81"]:
        raise RI6ContractError("Known class-A family overlap is not explicitly recorded")
    execution = payload.get("execution", {})
    if execution.get("canonical_arm") != "static_only":
        raise RI6ContractError("RI-6 canonical arm must remain static-only")
    if execution.get("motion_arm") != "disabled_not_eligible":
        raise RI6ContractError("RI-6 motion arm is not explicitly disabled")


def _validate_control_report(
    payload: Mapping[str, Any], *, verify_hash: bool = True
) -> None:
    if verify_hash:
        _validate_hash(payload, "report_sha256")
    if payload.get("status") != "completed_retrodiction_control":
        raise RI6ContractError("TEM-1 retrodiction control is incomplete")
    if payload.get("scientific_scope") != "historical_mutant_pair_control_not_prospective_evidence":
        raise RI6ContractError("TEM-1 control has an invalid scientific scope")
    if payload.get("detector_target_blind") is not True:
        raise RI6ContractError("TEM-1 detector was not target-blind")
    if len(payload.get("evaluations", [])) != 2:
        raise RI6ContractError("TEM-1 control must account for both 1PZO CBT molecules")


def _validate_inventory(
    payload: Mapping[str, Any], *, verify_hash: bool = True
) -> None:
    if verify_hash:
        _validate_hash(payload, "inventory_sha256")
    if payload.get("schema_version") != "biovoid-ri6-source-inventory-v1":
        raise RI6ContractError("Unexpected RI-6 source inventory schema")
    if payload.get("status") != "metadata_materialized_review_required":
        raise RI6ContractError("RI-6 source inventory is not review-blocked")
    if payload.get("source", {}).get("coordinate_files_downloaded") is not False:
        raise RI6ContractError("Source inventory downloaded coordinate files")
    records = payload.get("records", [])
    if not records:
        raise RI6ContractError("RI-6 source inventory is empty")
    if any(record.get("preliminary_status") == "eligible" for record in records):
        raise RI6ContractError("RI-6 source inventory contains auto-accepted records")
    if any(record.get("manual_review_required") is not True for record in records):
        raise RI6ContractError("Every RI-6 source record must require manual review")


def check(
    *,
    target_lock_path: Path,
    runtime_root: Path,
    inventory_path: Path | None = None,
    prospective_root: Path | None = None,
    closure_root: Path | None = None,
    review_root: Path | None = None,
) -> dict[str, Any]:
    target_lock = _read_json(target_lock_path)
    _validate_target_lock(target_lock)
    detector_manifest = _read_json(runtime_root / "tem1-detector-input-v1.json")
    _validate_target_blind_manifest(detector_manifest)
    detector_output = _read_json(runtime_root / "tem1-detector-output-v1.json")
    detector_hash = detector_output.get("detector_record_sha256")
    expected_detector_hash = _stable_hash(
        {key: value for key, value in detector_output.items() if key != "detector_record_sha256"}
    )
    if detector_hash != expected_detector_hash:
        raise RI6ContractError("TEM-1 detector output hash does not match its content")
    report = _read_json(runtime_root / "tem1-transfer-control-v1.json")
    _validate_control_report(report)
    if report.get("detector_record_sha256") != detector_hash:
        raise RI6ContractError("Evaluator report is not linked to the sealed detector output")
    if inventory_path is not None:
        _validate_inventory(_read_json(inventory_path))
    if prospective_root is not None:
        prospective_input = _read_json(prospective_root / "detector-input-v1.json")
        _validate_target_blind_manifest(prospective_input)
        prospective_output = _read_json(
            prospective_root / "ri6-prospective-static-run-v1.json"
        )
        _validate_prospective_output(prospective_output)
        if prospective_output.get("detector_input_manifest_sha256") != prospective_input.get(
            "manifest_sha256"
        ):
            raise RI6ContractError("Prospective output is not linked to its detector input")
        decision = _read_json(prospective_root / "source-review-decision-v1.json")
        if decision.get("source_id") != "5UL8":
            raise RI6ContractError("Prospective source decision is not fixed to 5UL8")
        if decision.get("review_status") != "user_approved_for_bounded_static_run":
            raise RI6ContractError("Prospective source approval is missing")
        if closure_root is not None:
            closure = _read_json(closure_root / "ri6-closure-v1.json")
            _validate_closure_record(closure)
            if closure.get("source_run_sha256") != prospective_output.get("run_sha256"):
                raise RI6ContractError("RI-6 closure is not linked to the prospective run")
        if review_root is not None:
            review = _read_json(review_root / "ri6-internal-review-v1.json")
            _validate_review(review)
            if review.get("source_run_sha256") != prospective_output.get("run_sha256"):
                raise RI6ContractError("RI-6 internal review is not linked to the prospective run")
    return {
        "status": (
            "ri6_v1_completed_internal_review_no_eligible_candidate"
            if review_root is not None
            else (
                "ri6_v1_closed_without_scientific_claim"
                if closure_root is not None
                else "ri6_preflight_complete_prospective_review_blocked"
            )
        ),
        "target_lock_sha256": target_lock["lock_sha256"],
        "control_report_sha256": report["report_sha256"],
        "prospective_execution_authorized": False,
        "bounded_static_run_present": prospective_root is not None,
        "bounded_phase_closed": closure_root is not None,
        "blocking_gate": (
            "new_target_or_source_lock_required"
            if review_root is not None
            else "independent candidate-source review"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-lock",
        type=Path,
        default=REPO_ROOT / "local-private/specs/ri6-target-lock-v1.json",
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=REPO_ROOT / "data/runtime/ri6/tem1",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=REPO_ROOT / "data/runtime/ri6/source-inventory/ri6-source-inventory-v1.json",
    )
    parser.add_argument(
        "--prospective-root",
        type=Path,
        default=REPO_ROOT / "data/runtime/ri6/prospective-static",
    )
    parser.add_argument(
        "--closure-root",
        type=Path,
        default=REPO_ROOT / "data/runtime/ri6/prospective-static",
    )
    parser.add_argument(
        "--review-root",
        type=Path,
        default=REPO_ROOT / "data/runtime/ri6/prospective-static",
    )
    args = parser.parse_args()
    result = check(
        target_lock_path=args.target_lock.resolve(),
        runtime_root=args.runtime_root.resolve(),
        inventory_path=args.inventory.resolve(),
        prospective_root=args.prospective_root.resolve(),
        closure_root=args.closure_root.resolve(),
        review_root=args.review_root.resolve(),
    )
    print(f"status={result['status']}")
    print(f"prospective_execution_authorized={str(result['prospective_execution_authorized']).lower()}")
    print(f"blocking_gate={result['blocking_gate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
