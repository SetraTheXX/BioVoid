"""Frozen, ligand-independent evaluator eligibility policy for RI-5 confirmation."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import hashlib
import json
import re
from typing import Any, Mapping

from src.ground_truth_alignment import AlignmentPolicy


EVALUATOR_V3_POLICY = AlignmentPolicy(
    minimum_sequence_identity=0.9,
    minimum_matched_residues=50,
    warning_rmsd_angstrom=3.0,
    maximum_rmsd_angstrom=8.0,
    policy_version="ground-truth-alignment-v3",
    ambiguous_sequence_policy="structural_fit",
    maximum_alignment_candidates=128,
    maximum_alignment_combinations=512,
    structural_tie_rmsd_tolerance_angstrom=0.001,
)

SCHEMA_VERSION = "biovoid-ri5-evaluator-v3-development-lock-v1"

_INELIGIBILITY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("missing_calpha_chain", re.compile(r"has no C-alpha atoms")),
    ("chain_union_mismatch", re.compile(r"chain unions have different lengths")),
    ("ligand_selector_mismatch", re.compile(r"Exact ligand selector matched no atoms")),
    ("sequence_identity_below_threshold", re.compile(r"Sequence identity .* is below")),
    ("alignment_candidate_limit", re.compile(r"candidate count exceeds")),
    ("alignment_combination_limit", re.compile(r"combination count exceeds")),
    ("structural_alignment_tie", re.compile(r"tie remains within")),
    ("no_valid_structural_mapping", re.compile(r"No structurally valid sequence")),
    ("global_fit_rmsd_exceeds_limit", re.compile(r"Protein alignment RMSD .* exceeds")),
)


class EvaluatorV3Error(RuntimeError):
    """Raised when evaluator v3 evidence cannot be frozen or verified."""


def stable_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def classify_ineligibility(error: str | None) -> str:
    normalized = str(error or "")
    for code, pattern in _INELIGIBILITY_RULES:
        if pattern.search(normalized):
            return code
    return "unclassified_evaluator_error"


def _validate_promoted_policy(raw: Mapping[str, Any]) -> None:
    expected = asdict(EVALUATOR_V3_POLICY)
    for key, value in expected.items():
        if key == "policy_version":
            continue
        if raw.get(key) != value:
            raise EvaluatorV3Error(f"Development recovery policy differs from evaluator v3: {key}")


def build_development_eligibility_lock(
    recovery: Mapping[str, Any],
    *,
    recovery_file_sha256: str,
    expected_case_count: int = 825,
) -> dict[str, Any]:
    records = recovery.get("records")
    if not isinstance(records, Mapping) or len(records) != expected_case_count:
        raise EvaluatorV3Error(f"Evaluator v3 requires {expected_case_count} development records")
    policy = recovery.get("alignment_policy")
    if not isinstance(policy, Mapping):
        raise EvaluatorV3Error("Development recovery report has no alignment policy")
    _validate_promoted_policy(policy)

    eligible_case_ids: list[str] = []
    excluded_cases: list[dict[str, str]] = []
    for case_id, raw in sorted(records.items()):
        if not isinstance(raw, Mapping):
            raise EvaluatorV3Error(f"Evaluator record is not an object: {case_id}")
        status = raw.get("status")
        if status == "completed_ground_truth":
            eligible_case_ids.append(str(case_id))
            continue
        if status != "alignment_unavailable":
            raise EvaluatorV3Error(f"Unknown development evaluator status: {status}")
        code = classify_ineligibility(str(raw.get("error", "")))
        if code == "unclassified_evaluator_error":
            raise EvaluatorV3Error(f"Unclassified development evaluator error: {case_id}")
        excluded_cases.append(
            {"case_id": str(case_id), "reason_code": code, "error": str(raw.get("error", ""))}
        )

    reason_counts = Counter(item["reason_code"] for item in excluded_cases)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "frozen_development_only_before_confirmatory_holdout",
        "alignment_policy": asdict(EVALUATOR_V3_POLICY),
        "ligand_used_for_mapping": False,
        "development_case_count": expected_case_count,
        "eligible_case_count": len(eligible_case_ids),
        "ineligible_case_count": len(excluded_cases),
        "eligible_case_ids_sha256": stable_hash(eligible_case_ids),
        "ineligible_case_ids_sha256": stable_hash([item["case_id"] for item in excluded_cases]),
        "ineligible_reason_counts": dict(sorted(reason_counts.items())),
        "excluded_cases": excluded_cases,
        "runtime_manifest_sha256": str(recovery.get("manifest_sha256", "")),
        "protocol_sha256": str(recovery.get("protocol_sha256", "")),
        "development_recovery_file_sha256": recovery_file_sha256,
        "claim_boundary": "development_policy_lock_only_no_performance_claim",
    }
    payload["lock_sha256"] = stable_hash(payload)
    validate_development_eligibility_lock(payload, expected_case_count=expected_case_count)
    return payload


def validate_development_eligibility_lock(
    payload: Mapping[str, Any], *, expected_case_count: int = 825
) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise EvaluatorV3Error("Unexpected evaluator v3 lock schema")
    if payload.get("status") != "frozen_development_only_before_confirmatory_holdout":
        raise EvaluatorV3Error("Evaluator v3 development lock is not frozen")
    policy = payload.get("alignment_policy")
    if policy != asdict(EVALUATOR_V3_POLICY):
        raise EvaluatorV3Error("Evaluator v3 policy drifted")
    if payload.get("ligand_used_for_mapping") is not False:
        raise EvaluatorV3Error("Evaluator v3 mapping must remain ligand-independent")
    eligible = int(payload.get("eligible_case_count", -1))
    ineligible = int(payload.get("ineligible_case_count", -1))
    if eligible + ineligible != expected_case_count:
        raise EvaluatorV3Error("Evaluator v3 does not account for every development case")
    excluded = payload.get("excluded_cases")
    if not isinstance(excluded, list) or len(excluded) != ineligible:
        raise EvaluatorV3Error("Evaluator v3 excluded-case accounting is inconsistent")
    reason_counts = Counter(str(item.get("reason_code", "")) for item in excluded)
    if dict(sorted(reason_counts.items())) != payload.get("ineligible_reason_counts"):
        raise EvaluatorV3Error("Evaluator v3 reason counts are inconsistent")
    expected_hash = stable_hash(
        {key: value for key, value in payload.items() if key != "lock_sha256"}
    )
    if payload.get("lock_sha256") != expected_hash:
        raise EvaluatorV3Error("Evaluator v3 lock hash mismatch")
