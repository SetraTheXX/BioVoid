"""Evaluate target-family baselines against the private diagnostic ground truth.

This command is evaluator-only. It combines the already completed, target-blind
BioVoid/fpocket/P2Rank records with the two-case DCC/DCA ground truth and writes
diagnostic metrics. It never changes detector inputs and never authorizes a
superiority or discovery claim.
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
    DEFAULT_BASELINE_MANIFEST,
    _read_json as _read_baseline_json,
    validate_baseline_input_manifest,
)
from scripts.evaluate_target_family_static_pilot import (  # noqa: E402
    CHAIN_SELECTION_POLICY,
    EVALUATION_REPORT_SCHEMA_VERSION,
    _detector_record,
    validate_evaluation_report,
)
from scripts.run_target_family_external_baseline import (  # noqa: E402
    BASELINE_RUN_SCHEMA_VERSION,
    validate_baseline_report,
)
from src.benchmark_v1 import (  # noqa: E402
    BenchmarkCase,
    BenchmarkManifest,
    EvaluatorGroundTruth,
    evaluate_split,
    phase6_frozen_protocol_v1,
)
from src.evaluator_format import (  # noqa: E402
    DetectorEvaluationRecord,
    EvaluatorPocket,
    assert_detector_payload_is_blind,
    failed_record,
)
from src.target_family_manifest import validate_detector_manifest  # noqa: E402


DEFAULT_MANIFEST = REPO_ROOT / "data/runtime/target-family/target-blind-static-pilot-v1.json"
DEFAULT_STATIC_RUN = (
    REPO_ROOT / "data/runtime/target-family/static-pilot-v1/target-family-static-pilot-run-v1.json"
)
DEFAULT_RECOVERY_RUN = (
    REPO_ROOT
    / "data/runtime/target-family/static-pilot-recovery-v4/target-family-static-recovery-v1.json"
)
DEFAULT_EVALUATION_REPORT = (
    REPO_ROOT
    / "data/runtime/target-family/static-evaluation-v1/target-family-static-evaluation-v1.json"
)
DEFAULT_FPOCKET_REPORT = (
    REPO_ROOT
    / "data/runtime/target-family/external-baselines-v1/fpocket-target-family-v1.json"
)
DEFAULT_P2RANK_REPORT = (
    REPO_ROOT
    / "data/runtime/target-family/external-baselines-v1/p2rank-target-family-v1.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data/runtime/target-family/external-baseline-comparison-v1/"
    "target-family-external-baseline-comparison-v1.json"
)
COMPARISON_SCHEMA_VERSION = "biovoid-target-family-external-baseline-comparison-v1"


class TargetFamilyComparisonError(RuntimeError):
    """Raised when the evaluator-only comparison contract is invalid."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_target_family_baseline_records(
    report: Mapping[str, Any],
    *,
    detector: str,
) -> dict[str, DetectorEvaluationRecord]:
    """Load only target-blind detector-shaped records from one baseline report."""

    if report.get("schema_version") != BASELINE_RUN_SCHEMA_VERSION:
        raise TargetFamilyComparisonError(f"Unexpected {detector} baseline report schema")
    if report.get("tool") != detector:
        raise TargetFamilyComparisonError(f"Baseline report tool mismatch for {detector}")
    if report.get("target_blind") is not True or report.get("evaluator_opened") is not False:
        raise TargetFamilyComparisonError(f"{detector} baseline crossed evaluator boundary")
    result: dict[str, DetectorEvaluationRecord] = {}
    raw_records = report.get("records", {})
    if not isinstance(raw_records, Mapping):
        raise TargetFamilyComparisonError(f"{detector} baseline records are not an object")
    for structure_id, raw in raw_records.items():
        normalized_id = str(structure_id).upper()
        if not isinstance(raw, Mapping):
            result[normalized_id] = failed_record(detector, normalized_id, "baseline_record_invalid")
            continue
        payload = raw.get("detector_record")
        if not isinstance(payload, Mapping):
            result[normalized_id] = failed_record(
                detector,
                normalized_id,
                str(raw.get("error", "baseline_result_missing")),
            )
            continue
        assert_detector_payload_is_blind(payload, path=f"{detector}.{normalized_id}")
        pockets = tuple(
            EvaluatorPocket(
                pocket_id=str(pocket["pocket_id"]),
                center=tuple(float(value) for value in pocket["center"]),
                volume=float(pocket["volume"]) if pocket.get("volume") is not None else None,
                rank=int(pocket["rank"]),
                score=float(pocket["score"]) if pocket.get("score") is not None else None,
                raw=dict(pocket.get("raw") or {}),
            )
            for pocket in payload.get("pockets", [])
        )
        record = DetectorEvaluationRecord(
            schema_version=str(payload["schema_version"]),
            detector=str(payload["detector"]),
            structure_id=normalized_id,
            status=str(payload["status"]),
            pockets=pockets,
            error=payload.get("error"),
            provenance=dict(payload.get("provenance") or {}),
        )
        if record.detector != detector:
            raise TargetFamilyComparisonError(f"Detector payload mismatch for {normalized_id}")
        result[normalized_id] = record
    return result


def _ground_truth_from_record(record: Mapping[str, Any]) -> EvaluatorGroundTruth:
    ground_truth = record.get("ground_truth")
    if not isinstance(ground_truth, Mapping):
        raise TargetFamilyComparisonError("Evaluator ground truth is missing")
    try:
        return EvaluatorGroundTruth(
            case_id=str(ground_truth["case_id"]),
            structure_id=str(ground_truth["structure_id"]),
            coordinate_frame_sha256=str(ground_truth["coordinate_frame_sha256"]),
            alignment_sha256=str(ground_truth["alignment_sha256"]),
            ligand_center=tuple(float(value) for value in ground_truth["ligand_center"]),
            ligand_atoms=tuple(
                tuple(float(value) for value in atom) for atom in ground_truth["ligand_atoms"]
            ),
            ligand_residues=tuple(str(value) for value in ground_truth.get("ligand_residues", [])),
            quality=str(ground_truth.get("quality", "exact")),
            provenance=str(ground_truth.get("provenance", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TargetFamilyComparisonError("Evaluator ground truth is malformed") from exc


def _build_benchmark_case(
    case: Mapping[str, Any],
    *,
    structure: Mapping[str, Any],
    static_case: Mapping[str, Any],
) -> BenchmarkCase:
    preparation_sha = static_case.get("preparation_config_sha256")
    if not isinstance(preparation_sha, str) or len(preparation_sha) != 64:
        preparation_sha = "0" * 64
    return BenchmarkCase(
        case_id=str(case["case_id"]),
        structure_id=str(case["structure_id"]),
        family_id=str(case["family_id"]),
        split="development",
        prepared_structure_sha256=str(structure["prepared_structure_sha256"]),
        preparation_config_sha256=preparation_sha,
    )


def _read_json(path: Path) -> dict[str, Any]:
    return _read_baseline_json(path)


def evaluate_target_family_comparison(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    baseline_manifest_path: Path = DEFAULT_BASELINE_MANIFEST,
    static_run_path: Path = DEFAULT_STATIC_RUN,
    recovery_run_path: Path = DEFAULT_RECOVERY_RUN,
    evaluation_report_path: Path = DEFAULT_EVALUATION_REPORT,
    fpocket_report_path: Path = DEFAULT_FPOCKET_REPORT,
    p2rank_report_path: Path = DEFAULT_P2RANK_REPORT,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path.resolve())
    baseline_manifest = _read_json(baseline_manifest_path.resolve())
    static_run = _read_json(static_run_path.resolve())
    recovery_run = _read_json(recovery_run_path.resolve())
    evaluation_report = _read_json(evaluation_report_path.resolve())
    fpocket_report = _read_json(fpocket_report_path.resolve())
    p2rank_report = _read_json(p2rank_report_path.resolve())
    validate_detector_manifest(manifest)
    try:
        validate_baseline_input_manifest(baseline_manifest)
    except ValueError as exc:
        raise TargetFamilyComparisonError(str(exc)) from exc
    validate_evaluation_report(evaluation_report, manifest)
    if evaluation_report.get("schema_version") != EVALUATION_REPORT_SCHEMA_VERSION:
        raise TargetFamilyComparisonError("Unexpected target-family evaluator report schema")
    if fpocket_report.get("manifest_sha256") != baseline_manifest.get("manifest_sha256"):
        raise TargetFamilyComparisonError("fpocket baseline manifest hash mismatch")
    if p2rank_report.get("manifest_sha256") != baseline_manifest.get("manifest_sha256"):
        raise TargetFamilyComparisonError("P2Rank baseline manifest hash mismatch")
    for name, report in (("fpocket", fpocket_report), ("p2rank", p2rank_report)):
        if report.get("status") not in {"complete", "complete_with_failures"}:
            raise TargetFamilyComparisonError(f"{name} baseline is incomplete")
        validate_baseline_report(
            report,
            baseline=name,
            manifest=baseline_manifest,
            image_id=str(report.get("container_image_id", "")),
        )
    static_cases = static_run.get("cases")
    if not isinstance(static_cases, Mapping):
        raise TargetFamilyComparisonError("Static run cases are missing")
    recovery_result = recovery_run.get("result")
    recovery_by_structure = {}
    if isinstance(recovery_result, Mapping):
        recovery_by_structure[str(recovery_result.get("structure_id", "")).upper()] = recovery_result
    baseline_structures = {
        str(item["structure_id"]).upper(): item
        for item in baseline_manifest["structures"]
        if isinstance(item, Mapping)
    }
    evaluator_records = evaluation_report.get("records")
    if not isinstance(evaluator_records, Mapping):
        raise TargetFamilyComparisonError("Evaluator records are missing")
    cases: list[BenchmarkCase] = []
    truths: dict[str, EvaluatorGroundTruth] = {}
    biovoid_records: dict[str, DetectorEvaluationRecord] = {}
    case_arms: dict[str, str] = {}
    for case in manifest["cases"]:
        case_id = str(case["case_id"])
        structure_id = str(case["structure_id"]).upper()
        structure = baseline_structures.get(structure_id)
        if structure is None:
            raise TargetFamilyComparisonError(f"Baseline input missing structure: {structure_id}")
        primary = static_cases.get(case_id)
        if not isinstance(primary, Mapping):
            raise TargetFamilyComparisonError(f"Static case missing: {case_id}")
        evaluator_record = evaluator_records.get(case_id)
        if not isinstance(evaluator_record, Mapping) or evaluator_record.get("status") != "completed_ground_truth":
            raise TargetFamilyComparisonError(f"Ground truth unavailable for case: {case_id}")
        cases.append(_build_benchmark_case(case, structure=structure, static_case=primary))
        truths[case_id.casefold()] = _ground_truth_from_record(evaluator_record)
        recovery_case = recovery_by_structure.get(structure_id)
        detector_record, arm = _detector_record(structure_id, primary, recovery_case)
        biovoid_records[structure_id] = detector_record
        case_arms[case_id] = arm
    benchmark_manifest = BenchmarkManifest(cases=tuple(cases))
    protocol = phase6_frozen_protocol_v1()
    fpocket_records = _load_target_family_baseline_records(fpocket_report, detector="fpocket")
    p2rank_records = _load_target_family_baseline_records(p2rank_report, detector="p2rank")
    results = {
        detector: evaluate_split(
            detector=detector,
            split="development",
            records=records,
            ground_truth=truths,
            manifest=benchmark_manifest,
            protocol=protocol,
        )
        for detector, records in (
            ("biovoid_static", biovoid_records),
            ("fpocket", fpocket_records),
            ("p2rank", p2rank_records),
        )
    }
    output: dict[str, Any] = {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "completed_diagnostic_only",
        "claim_boundary": "diagnostic_dcc_dca_only",
        "manifest_sha256": manifest["manifest_sha256"],
        "baseline_input_manifest_sha256": baseline_manifest["manifest_sha256"],
        "protocol_sha256": protocol.protocol_sha256,
        "evaluator_report_sha256": _sha256_file(evaluation_report_path.resolve()),
        "baseline_report_sha256": {
            "fpocket": _sha256_file(fpocket_report_path.resolve()),
            "p2rank": _sha256_file(p2rank_report_path.resolve()),
        },
        "detector_target_blind": True,
        "evaluator_only": True,
        "sealed_evaluation_authorized": False,
        "scientific_superiority_claim_authorized": False,
        "discovery_claim_authorized": False,
        "comparison_scope": {
            "case_count": len(cases),
            "same_prepared_apo_inputs": True,
            "single_worker": True,
            "motion_enabled": False,
            "ml_training": False,
            "rank_scope": [1, 3, 5],
            "interpretation": "two_case_development_diagnostic_not_for_claim",
        },
        "case_arms": case_arms,
        "results": results,
        "roadmap": {
            "current_gate": "G2-bounded-static-development-pilot",
            "purpose": "Compare three target-blind detectors on the same two prepared apo inputs.",
            "next_step": "Review failure patterns and representative-chain limitations; do not promote this two-case result to superiority or discovery evidence.",
            "status": "diagnostic_only",
        },
    }
    output["run_sha256"] = _stable_hash(
        {key: value for key, value in output.items() if key != "run_sha256"}
    )
    _write_json_atomic(output_path.resolve(), output)
    print(f"target-family external comparison: {output['status']} cases={len(cases)}")
    for detector, result in results.items():
        print(
            f"{detector}: top1/3/5_dcc="
            f"{result['top_k_dcc_recall'][1]}/"
            f"{result['top_k_dcc_recall'][3]}/"
            f"{result['top_k_dcc_recall'][5]} "
            f"top1/3/5_dca="
            f"{result['top_k_dca_recall'][1]}/"
            f"{result['top_k_dca_recall'][3]}/"
            f"{result['top_k_dca_recall'][5]}"
        )
    print(f"comparison report: {output_path}")
    return output


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--baseline-manifest", type=Path, default=DEFAULT_BASELINE_MANIFEST)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--recovery-run", type=Path, default=DEFAULT_RECOVERY_RUN)
    parser.add_argument("--evaluation-report", type=Path, default=DEFAULT_EVALUATION_REPORT)
    parser.add_argument("--fpocket-report", type=Path, default=DEFAULT_FPOCKET_REPORT)
    parser.add_argument("--p2rank-report", type=Path, default=DEFAULT_P2RANK_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        evaluate_target_family_comparison(
            manifest_path=args.manifest,
            baseline_manifest_path=args.baseline_manifest,
            static_run_path=args.static_run,
            recovery_run_path=args.recovery_run,
            evaluation_report_path=args.evaluation_report,
            fpocket_report_path=args.fpocket_report,
            p2rank_report_path=args.p2rank_report,
            output_path=args.output,
        )
    except (TargetFamilyComparisonError, ValueError, KeyError) as exc:
        print(f"target-family external comparison error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
