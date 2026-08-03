"""Freeze a declared RI-3 development evaluator eligibility cohort.

This consumes evaluator-only runtime evidence. It never reads detector pocket
coordinates and does not authorize sealed evaluation or scientific claims.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_ri3_static_development import _read_json  # noqa: E402
from scripts.run_ri3_static_development import (  # noqa: E402
    DEFAULT_MANIFEST,
    MANIFEST_SCHEMA_VERSION,
    _validate_manifest,
)
from src.benchmark_v1 import phase6_frozen_protocol_v1  # noqa: E402


DEFAULT_RECOVERY_REPORT = REPO_ROOT / (
    "data/runtime/ri3/ri3-static-development-evaluation-structural-recovery-v1.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "data/runtime/ri3/ri3-development-evaluator-eligibility-v1.json"
SCHEMA_VERSION = "biovoid-ri3-development-evaluator-eligibility-v1"
EXPECTED_CASE_COUNT = 825
EXPECTED_ELIGIBLE_CASE_COUNT = 775

_RESIDUAL_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("missing_calpha_chain", re.compile(r"has no C-alpha atoms")),
    ("chain_union_mismatch", re.compile(r"chain unions have different lengths")),
    ("ligand_selector_mismatch", re.compile(r"Exact ligand selector matched no atoms")),
    ("sequence_identity_below_threshold", re.compile(r"Sequence identity .* is below")),
    ("alignment_candidate_limit", re.compile(r"candidate count exceeds")),
    ("structural_alignment_tie", re.compile(r"tie remains within")),
    ("no_valid_structural_mapping", re.compile(r"No structurally valid sequence")),
    ("global_fit_rmsd_exceeds_limit", re.compile(r"Protein alignment RMSD .* exceeds")),
)


class EligibilityFreezeError(RuntimeError):
    """Raised when evaluator evidence cannot be frozen safely."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def classify_residual_error(error: str | None) -> str:
    """Map a known evaluator rejection to a stable, non-success eligibility code."""
    normalized = str(error or "")
    for code, pattern in _RESIDUAL_RULES:
        if pattern.search(normalized):
            return code
    return "unexpected_evaluator_error"


def build_eligibility_lock(
    manifest: Mapping[str, Any], recovery: Mapping[str, Any], *, recovery_sha256: str
) -> dict[str, Any]:
    """Validate terminal evaluator records and produce a deterministic cohort lock."""
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise EligibilityFreezeError("Unexpected RI-3 runtime manifest schema")
    _validate_manifest(manifest)
    if recovery.get("schema_version") != (
        "biovoid-ri3-static-development-evaluation-structural-recovery-v1"
    ):
        raise EligibilityFreezeError("Unexpected structural recovery report schema")
    if recovery.get("status") != "partial":
        raise EligibilityFreezeError("Recovery report must retain unresolved cases as partial")
    protocol = phase6_frozen_protocol_v1()
    if recovery.get("protocol_sha256") != protocol.protocol_sha256:
        raise EligibilityFreezeError("Recovery report protocol hash mismatch")
    if recovery.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise EligibilityFreezeError("Recovery report manifest hash mismatch")
    if recovery.get("detector_target_blind") is not True:
        raise EligibilityFreezeError("Recovery report target-blind boundary is missing")
    if recovery.get("sealed_evaluation_authorized") is not False:
        raise EligibilityFreezeError("Recovery report opens sealed evaluation")

    cases = {
        str(case["case_id"]): case
        for case in manifest["benchmark_manifest"]["cases"]
        if case["split"] == "development"
    }
    records = recovery.get("records")
    if len(cases) != EXPECTED_CASE_COUNT or not isinstance(records, Mapping):
        raise EligibilityFreezeError("Expected all 825 development evaluator records")
    if set(records) != set(cases):
        raise EligibilityFreezeError("Evaluator records differ from the development manifest")

    eligible: list[str] = []
    excluded: list[dict[str, str]] = []
    observed_statuses: Counter[str] = Counter()
    for case_id in sorted(cases):
        record = records[case_id]
        status = str(record.get("status", ""))
        observed_statuses[status] += 1
        if status == "completed_ground_truth":
            truth = record.get("ground_truth")
            if not isinstance(truth, Mapping):
                raise EligibilityFreezeError(f"Eligible case lacks ground truth: {case_id}")
            if truth.get("case_id") != case_id:
                raise EligibilityFreezeError(f"Ground-truth case ID mismatch: {case_id}")
            if truth.get("coordinate_frame_sha256") != cases[case_id]["prepared_structure_sha256"]:
                raise EligibilityFreezeError(f"Ground-truth frame mismatch: {case_id}")
            eligible.append(case_id)
            continue
        if status != "alignment_unavailable":
            raise EligibilityFreezeError(f"Nonterminal evaluator status for {case_id}: {status}")
        reason_code = classify_residual_error(record.get("error"))
        if reason_code == "unexpected_evaluator_error":
            raise EligibilityFreezeError(f"Unclassified evaluator rejection: {case_id}")
        excluded.append(
            {
                "case_id": case_id,
                "structure_id": str(cases[case_id]["structure_id"]).upper(),
                "reason_code": reason_code,
                "error_sha256": _stable_hash(str(record.get("error", ""))),
            }
        )

    if len(eligible) != EXPECTED_ELIGIBLE_CASE_COUNT:
        raise EligibilityFreezeError(
            f"Expected {EXPECTED_ELIGIBLE_CASE_COUNT} eligible cases, found {len(eligible)}"
        )
    if observed_statuses != Counter(
        completed_ground_truth=EXPECTED_ELIGIBLE_CASE_COUNT,
        alignment_unavailable=EXPECTED_CASE_COUNT - EXPECTED_ELIGIBLE_CASE_COUNT,
    ):
        raise EligibilityFreezeError(f"Unexpected terminal evaluator counts: {dict(observed_statuses)}")

    excluded_counts = dict(sorted(Counter(item["reason_code"] for item in excluded).items()))
    lock = {
        "schema_version": SCHEMA_VERSION,
        "status": "locked_development_evaluator_eligibility",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "protocol_sha256": protocol.protocol_sha256,
        "runtime_manifest_sha256": manifest["manifest_sha256"],
        "recovery_report_sha256": recovery_sha256,
        "alignment_policy": recovery["alignment_policy"],
        "development_case_count": EXPECTED_CASE_COUNT,
        "eligible_case_count": len(eligible),
        "ineligible_case_count": len(excluded),
        "eligible_case_ids_sha256": _stable_hash(eligible),
        "ineligible_case_ids_sha256": _stable_hash(excluded),
        "ineligible_reason_counts": excluded_counts,
        "excluded_cases": excluded,
        "policy_decisions": {
            "all_cases_have_terminal_evaluator_records": True,
            "known_unmappable_cases_are_explicitly_ineligible": True,
            "unexpected_evaluator_errors_allowed": False,
            "detector_target_blind": True,
            "sealed_evaluation_authorized": False,
            "scientific_superiority_claim_authorized": False,
            "ri4_preflight_authorized": True,
        },
    }
    lock["eligibility_lock_sha256"] = _stable_hash(lock)
    return lock


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--recovery-report", type=Path, default=DEFAULT_RECOVERY_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def main() -> int:
    args = _parse_args()
    manifest_path = _resolve(args.manifest)
    recovery_path = _resolve(args.recovery_report)
    output_path = _resolve(args.output)
    lock = build_eligibility_lock(
        _read_json(manifest_path),
        _read_json(recovery_path),
        recovery_sha256=_sha256_file(recovery_path),
    )
    _write_json_atomic(output_path, lock)
    print(
        "RI-3 evaluator eligibility: LOCKED "
        f"eligible={lock['eligible_case_count']} ineligible={lock['ineligible_case_count']}"
    )
    print(f"eligibility lock: {output_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EligibilityFreezeError as exc:
        print(f"RI-3 eligibility freeze error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
