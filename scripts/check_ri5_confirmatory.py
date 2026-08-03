"""Fail-closed verification for RI-5.1 through RI-5.3 evidence."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_ri5_confirmatory_static import (  # noqa: E402
    ConfirmatoryRunError,
    _resume_ledger,
    _validate_completed_baseline,
    _validate_manifest,
    _validate_open_contract,
)
from src.confirmatory_holdout import (  # noqa: E402
    EVALUATOR_SCHEMA_VERSION,
    LEDGER_SCHEMA_VERSION,
    validate_detector_source_lock,
)
from src.evaluator_v3 import (  # noqa: E402
    EVALUATOR_V3_POLICY,
    stable_hash,
    validate_development_eligibility_lock,
)


DEFAULT_ROOT = REPO_ROOT / "data/runtime/ri5-confirmatory"
DEFAULT_DEV_LOCK = DEFAULT_ROOT / "evaluator-v3-development-lock-v1.json"
DEFAULT_SOURCE_LOCK = DEFAULT_ROOT / "confirmatory-source-lock-v1.json"
DEFAULT_EVALUATOR_LOCK = DEFAULT_ROOT / "confirmatory-evaluator-lock-v1.json"
DEFAULT_OPEN_CONTRACT = DEFAULT_ROOT / "confirmatory-open-contract-v1.json"
DEFAULT_LEDGER = DEFAULT_ROOT / "confirmatory-ledger-v1.json"
DEFAULT_PREPARATION = DEFAULT_ROOT / "confirmatory-preparation-v1.json"
DEFAULT_MANIFEST = DEFAULT_ROOT / "confirmatory-runtime-manifest-v1.json"
DEFAULT_STATIC_RUN = DEFAULT_ROOT / "confirmatory-static-run-v1.json"
DEFAULT_EVALUATION = DEFAULT_ROOT / "confirmatory-static-evaluation-v1.json"
DEFAULT_FPOCKET = DEFAULT_ROOT / "external-baselines-v1/fpocket-confirmatory-v1.json"
DEFAULT_P2RANK = DEFAULT_ROOT / "external-baselines-v1/p2rank-confirmatory-v1.json"
DEFAULT_COMPARISON = DEFAULT_ROOT / "confirmatory-static-baseline-comparison-v1.json"


class RI5CheckError(RuntimeError):
    """Raised when RI-5 evidence is incomplete, altered, or out of order."""


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RI5CheckError(f"Required RI-5 evidence is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RI5CheckError(f"Expected JSON object: {path}")
    return payload


def _hash_matches(payload: Mapping[str, Any], field: str) -> None:
    expected = stable_hash({key: value for key, value in payload.items() if key != field})
    if payload.get(field) != expected:
        raise RI5CheckError(f"{field} hash mismatch")


def _check_development_lock(path: Path) -> dict[str, Any]:
    payload = _read(path)
    try:
        validate_development_eligibility_lock(payload, expected_case_count=825)
    except Exception as exc:  # noqa: BLE001 - normalize all contract failures
        raise RI5CheckError(f"Development evaluator v3 lock is invalid: {exc}") from exc
    if payload.get("eligible_case_count") != 775 or payload.get("ineligible_case_count") != 50:
        raise RI5CheckError("Development evaluator v3 cohort counts drifted")
    return payload


def _check_locks(
    source_path: Path,
    evaluator_path: Path,
    open_contract_path: Path,
    ledger_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    source = _read(source_path)
    evaluator = _read(evaluator_path)
    contract = _read(open_contract_path)
    try:
        validate_detector_source_lock(source, expected_structure_count=222, expected_case_count=265)
        _validate_open_contract(contract)
    except Exception as exc:  # noqa: BLE001 - normalize contract failures
        raise RI5CheckError(f"RI-5 source/open lock is invalid: {exc}") from exc
    if evaluator.get("schema_version") != EVALUATOR_SCHEMA_VERSION:
        raise RI5CheckError("Unexpected RI-5 evaluator lock schema")
    _hash_matches(evaluator, "evaluator_lock_sha256")
    if evaluator.get("source_lock_sha256") != source.get("source_lock_sha256"):
        raise RI5CheckError("Evaluator lock is not bound to source lock")
    if evaluator.get("structure_count") != 222 or evaluator.get("case_count") != 265:
        raise RI5CheckError("Evaluator lock cohort drifted")
    if contract.get("source_lock_sha256") != source.get("source_lock_sha256"):
        raise RI5CheckError("Open contract source hash drifted")
    if contract.get("evaluator_lock_sha256") != evaluator.get("evaluator_lock_sha256"):
        raise RI5CheckError("Open contract evaluator hash drifted")
    ledger = _read(ledger_path)
    if ledger.get("schema_version") != LEDGER_SCHEMA_VERSION or ledger.get("opened") is not True:
        raise RI5CheckError("RI-5 confirmatory ledger is not open")
    try:
        _resume_ledger(ledger_path, contract)
    except Exception as exc:  # noqa: BLE001 - normalize contract failures
        raise RI5CheckError(f"RI-5 ledger is invalid: {exc}") from exc
    return source, evaluator, contract, ledger


def _check_preparation(path: Path, source: Mapping[str, Any]) -> dict[str, Any]:
    payload = _read(path)
    if payload.get("schema_version") != "biovoid-ri5-confirmatory-preparation-v1":
        raise RI5CheckError("Unexpected RI-5 preparation schema")
    if payload.get("status") != "complete" or payload.get("structure_count") != 222:
        raise RI5CheckError("RI-5 preparation is incomplete")
    if payload.get("source_lock_sha256") != source.get("source_lock_sha256"):
        raise RI5CheckError("RI-5 preparation is not bound to source lock")
    if payload.get("archive", {}).get("full_archive_downloaded") is not False:
        raise RI5CheckError("RI-5 preparation downloaded the full archive")
    counts = payload.get("counts", {})
    if counts.get("eligible") != 222 or sum(int(value) for value in counts.values()) != 222:
        raise RI5CheckError("RI-5 preparation does not account for all structures")
    if payload.get("detector_started") is not False or payload.get("evaluator_opened") is not False:
        raise RI5CheckError("RI-5 preparation crossed the execution boundary")
    return payload


def _check_static_run(path: Path, manifest: Mapping[str, Any], ledger: Mapping[str, Any]) -> dict[str, Any]:
    payload = _read(path)
    if payload.get("schema_version") != "biovoid-ri5-confirmatory-static-run-v1":
        raise RI5CheckError("Unexpected RI-5 static-run schema")
    if payload.get("status") != "complete":
        raise RI5CheckError("RI-5 static arm is incomplete")
    if payload.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise RI5CheckError("RI-5 static arm is not bound to its manifest")
    if payload.get("ledger_sha256") != ledger.get("ledger_sha256"):
        raise RI5CheckError("RI-5 static arm is not bound to its ledger")
    execution = payload.get("execution", {})
    if execution.get("workers") != 1 or execution.get("resource_profile") != "safe-16gb":
        raise RI5CheckError("RI-5 static arm exceeded its resource profile")
    if execution.get("nma_started") is not False or execution.get("target_blind") is not True:
        raise RI5CheckError("RI-5 static arm crossed motion or target boundary")
    if len(payload.get("records", {})) != 222:
        raise RI5CheckError("RI-5 static arm does not account for all structures")
    counts = payload.get("counts", {})
    if sum(int(value) for value in counts.values()) != 222:
        raise RI5CheckError("RI-5 static counts do not account for all structures")
    if counts.get("failed", 0) != 0:
        raise RI5CheckError("RI-5 static arm contains failed records")
    return payload


def _check_evaluation(path: Path, manifest: Mapping[str, Any], evaluator: Mapping[str, Any]) -> dict[str, Any]:
    payload = _read(path)
    if payload.get("status") != "complete" or payload.get("schema_version") != "biovoid-ri5-confirmatory-static-evaluation-v1":
        raise RI5CheckError("RI-5 evaluator report is incomplete")
    if payload.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise RI5CheckError("RI-5 evaluator report is not bound to its manifest")
    if payload.get("evaluator_lock_sha256") != evaluator.get("evaluator_lock_sha256"):
        raise RI5CheckError("RI-5 evaluator report is not bound to evaluator lock")
    if payload.get("alignment_policy") != asdict(EVALUATOR_V3_POLICY):
        raise RI5CheckError("RI-5 evaluator policy drifted")
    if payload.get("detector_target_blind") is not True:
        raise RI5CheckError("RI-5 evaluator report lost target-blind marker")
    records = payload.get("records", {})
    if len(records) != 265:
        raise RI5CheckError("RI-5 evaluator does not account for all cases")
    statuses = {str(raw.get("status")) for raw in records.values()}
    if not statuses <= {"completed_ground_truth", "evaluator_ineligible"}:
        raise RI5CheckError("RI-5 evaluator contains non-terminal records")
    summary = payload.get("summary", {})
    if summary.get("planned_cases") != 265 or summary.get("evaluator_eligible") != 246:
        raise RI5CheckError("RI-5 evaluator summary cohort drifted")
    if summary.get("evaluator_ineligible") != 19:
        raise RI5CheckError("RI-5 evaluator ineligible count drifted")
    if summary.get("motion_started") is not False or summary.get("external_replication") is not False:
        raise RI5CheckError("RI-5 evaluator report contains unsafe execution flags")
    _hash_matches(payload, "report_sha256")
    return payload


def _check_comparison(
    path: Path, manifest: Mapping[str, Any], evaluation: Mapping[str, Any]
) -> dict[str, Any]:
    payload = _read(path)
    if payload.get("schema_version") != "biovoid-ri5-confirmatory-static-baseline-comparison-v1":
        raise RI5CheckError("Unexpected RI-5 comparison schema")
    if payload.get("status") != "complete_local_blinded_static_baseline_confirmation":
        raise RI5CheckError("RI-5 comparison is incomplete")
    if payload.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise RI5CheckError("RI-5 comparison is not bound to its manifest")
    coverage = payload.get("coverage", {})
    if coverage.get("planned_cases") != 265 or coverage.get("evaluator_eligible") != 246:
        raise RI5CheckError("RI-5 comparison coverage drifted")
    if set(payload.get("results", {})) != {"biovoid_static", "fpocket", "p2rank"}:
        raise RI5CheckError("RI-5 comparison does not contain all static arms")
    decision = payload.get("decision", {})
    if decision.get("static_and_baselines_completed") is not True:
        raise RI5CheckError("RI-5 static/baseline completion flag is missing")
    if decision.get("motion_required_by_protocol") is not False:
        raise RI5CheckError("RI-5 incorrectly requires motion by protocol")
    if decision.get("motion_started") is not False:
        raise RI5CheckError("RI-5 motion arm was started")
    if decision.get("scientific_superiority_claim_authorized") is not False:
        raise RI5CheckError("RI-5 scientific superiority claim was authorized")
    if payload.get("evaluation_report_sha256") is None or evaluation.get("report_sha256") is None:
        raise RI5CheckError("RI-5 comparison is missing report linkage")
    _hash_matches(payload, "report_sha256")
    return payload


def check(
    *,
    dev_lock_path: Path = DEFAULT_DEV_LOCK,
    source_lock_path: Path = DEFAULT_SOURCE_LOCK,
    evaluator_lock_path: Path = DEFAULT_EVALUATOR_LOCK,
    open_contract_path: Path = DEFAULT_OPEN_CONTRACT,
    ledger_path: Path = DEFAULT_LEDGER,
    preparation_path: Path = DEFAULT_PREPARATION,
    manifest_path: Path = DEFAULT_MANIFEST,
    static_run_path: Path = DEFAULT_STATIC_RUN,
    evaluation_path: Path = DEFAULT_EVALUATION,
    fpocket_path: Path = DEFAULT_FPOCKET,
    p2rank_path: Path = DEFAULT_P2RANK,
    comparison_path: Path = DEFAULT_COMPARISON,
) -> dict[str, Any]:
    _check_development_lock(dev_lock_path)
    source, evaluator, _contract, ledger = _check_locks(
        source_lock_path, evaluator_lock_path, open_contract_path, ledger_path
    )
    _check_preparation(preparation_path, source)
    manifest = _read(manifest_path)
    try:
        _validate_manifest(manifest, source)
    except Exception as exc:  # noqa: BLE001 - normalize contract failures
        raise RI5CheckError(f"RI-5 runtime manifest is invalid: {exc}") from exc
    static_run = _check_static_run(static_run_path, manifest, ledger)
    fpocket = _validate_completed_baseline(
        fpocket_path, tool="fpocket", manifest_sha256=manifest["manifest_sha256"]
    )
    p2rank = _validate_completed_baseline(
        p2rank_path, tool="p2rank", manifest_sha256=manifest["manifest_sha256"]
    )
    evaluation = _check_evaluation(evaluation_path, manifest, evaluator)
    comparison = _check_comparison(comparison_path, manifest, evaluation)
    evaluation_summary = evaluation["summary"]
    protocol_result = evaluation_summary["protocol_result"]
    return {
        "status": "ri5_v3_confirmatory_static_and_baselines_complete",
        "development": {"eligible": 775, "ineligible": 50},
        "confirmatory": {"structures": 222, "cases": 265},
        "static": static_run["counts"],
        "fpocket": fpocket["counts"],
        "p2rank": p2rank["counts"],
        "evaluator": {
            "planned_cases": evaluation_summary["planned_cases"],
            "eligible": evaluation_summary["evaluator_eligible"],
            "ineligible": evaluation_summary["evaluator_ineligible"],
            "ineligible_reason_counts": evaluation_summary["ineligible_reason_counts"],
            "top_3_dcc_recall": protocol_result["top_k_dcc_recall"]["3"],
            "top_3_dca_recall": protocol_result["top_k_dca_recall"]["3"],
            "motion_started": evaluation_summary["motion_started"],
        },
        "comparison": comparison["primary_endpoint"],
        "motion_started": comparison["decision"]["motion_started"],
        "external_replication": comparison["decision"]["external_replication"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    result = check(
        dev_lock_path=root / "evaluator-v3-development-lock-v1.json",
        source_lock_path=root / "confirmatory-source-lock-v1.json",
        evaluator_lock_path=root / "confirmatory-evaluator-lock-v1.json",
        open_contract_path=root / "confirmatory-open-contract-v1.json",
        ledger_path=root / "confirmatory-ledger-v1.json",
        preparation_path=root / "confirmatory-preparation-v1.json",
        manifest_path=root / "confirmatory-runtime-manifest-v1.json",
        static_run_path=root / "confirmatory-static-run-v1.json",
        evaluation_path=root / "confirmatory-static-evaluation-v1.json",
        fpocket_path=root / "external-baselines-v1/fpocket-confirmatory-v1.json",
        p2rank_path=root / "external-baselines-v1/p2rank-confirmatory-v1.json",
        comparison_path=root / "confirmatory-static-baseline-comparison-v1.json",
    )
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RI5CheckError, ConfirmatoryRunError) as exc:
        print(f"RI-5 check failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
