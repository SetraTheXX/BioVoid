"""Compare BioVoid static, fpocket, and P2Rank on one frozen input subset.

The subset is the evaluator cases with available ground truth in the RI-3
structural-recovery report. This is a development diagnostic, not a sealed
result and not an authorization for a superiority claim.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_ri3_static_development import (  # noqa: E402
    _ground_truth_from_payload,
    _load_detector_records,
    _read_json,
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


DEFAULT_MANIFEST = REPO_ROOT / "data/runtime/ri3/cryptobench-development-runtime-manifest-v1.json"
DEFAULT_STATIC_RUN = REPO_ROOT / "data/runtime/ri3/ri3-static-development-run-v1.json"
DEFAULT_RECOVERY_REPORT = REPO_ROOT / (
    "data/runtime/ri3/ri3-static-development-evaluation-structural-recovery-v1.json"
)
DEFAULT_ELIGIBILITY_LOCK = REPO_ROOT / "data/runtime/ri3/ri3-development-evaluator-eligibility-v1.json"
DEFAULT_FPOCKET_REPORT = REPO_ROOT / (
    "data/runtime/ri3/external-baselines-v1/fpocket-development-v1.json"
)
DEFAULT_P2RANK_REPORT = REPO_ROOT / (
    "data/runtime/ri3/external-baselines-v1/p2rank-development-v1.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "data/runtime/ri3/ri3-static-external-comparison-v1.json"
REPORT_SCHEMA_VERSION = "biovoid-ri3-static-external-comparison-v1"


class ComparisonError(RuntimeError):
    """Raised when comparison inputs violate the frozen contract."""


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


def _load_baseline_records(
    report: Mapping[str, Any],
    *,
    detector: str,
) -> dict[str, DetectorEvaluationRecord]:
    if report.get("schema_version") != "biovoid-ri3-external-baseline-run-v1":
        raise ComparisonError(f"Unexpected {detector} baseline report schema")
    if report.get("tool") != detector:
        raise ComparisonError(f"Baseline report tool mismatch: {report.get('tool')} != {detector}")
    if report.get("target_blind") is not True:
        raise ComparisonError(f"{detector} baseline report is not target-blind")
    result: dict[str, DetectorEvaluationRecord] = {}
    for structure_id, raw in report.get("records", {}).items():
        normalized_id = str(structure_id).upper()
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
                volume=(float(pocket["volume"]) if pocket.get("volume") is not None else None),
                rank=int(pocket["rank"]),
                score=(float(pocket["score"]) if pocket.get("score") is not None else None),
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
            raise ComparisonError(f"Detector payload mismatch for {normalized_id}")
        result[normalized_id] = record
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--recovery-report", type=Path, default=DEFAULT_RECOVERY_REPORT)
    parser.add_argument("--eligibility-lock", type=Path, default=DEFAULT_ELIGIBILITY_LOCK)
    parser.add_argument("--fpocket-report", type=Path, default=DEFAULT_FPOCKET_REPORT)
    parser.add_argument("--p2rank-report", type=Path, default=DEFAULT_P2RANK_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    paths = {
        name: path if path.is_absolute() else REPO_ROOT / path
        for name, path in {
            "manifest": args.manifest,
            "static_run": args.static_run,
            "recovery": args.recovery_report,
            "eligibility": args.eligibility_lock,
            "fpocket": args.fpocket_report,
            "p2rank": args.p2rank_report,
            "output": args.output,
        }.items()
    }
    manifest_payload = _read_json(paths["manifest"])
    static_run = _read_json(paths["static_run"])
    recovery = _read_json(paths["recovery"])
    eligibility = _read_json(paths["eligibility"])
    fpocket_report = _read_json(paths["fpocket"])
    p2rank_report = _read_json(paths["p2rank"])
    protocol = phase6_frozen_protocol_v1()
    if recovery.get("protocol_sha256") != protocol.protocol_sha256:
        raise ComparisonError("Recovery report protocol hash mismatch")
    if recovery.get("manifest_sha256") != manifest_payload.get("manifest_sha256"):
        raise ComparisonError("Recovery report manifest hash mismatch")
    if eligibility.get("schema_version") != "biovoid-ri3-development-evaluator-eligibility-v1":
        raise ComparisonError("Evaluator eligibility schema mismatch")
    if eligibility.get("status") != "locked_development_evaluator_eligibility":
        raise ComparisonError("Evaluator eligibility is not locked")
    if eligibility.get("runtime_manifest_sha256") != manifest_payload.get("manifest_sha256"):
        raise ComparisonError("Evaluator eligibility manifest hash mismatch")
    if eligibility.get("recovery_report_sha256") != _sha256_file(paths["recovery"]):
        raise ComparisonError("Evaluator eligibility recovery hash mismatch")
    for tool_report in (fpocket_report, p2rank_report):
        if tool_report.get("manifest_sha256") != manifest_payload.get("manifest_sha256"):
            raise ComparisonError("External baseline manifest hash mismatch")
        if tool_report.get("status") != "complete":
            raise ComparisonError("External baseline run is not complete")
    benchmark_cases = tuple(
        BenchmarkCase(**case) for case in manifest_payload["benchmark_manifest"]["cases"]
    )
    all_manifest = BenchmarkManifest(cases=benchmark_cases)
    excluded_case_ids = {
        str(item["case_id"]).casefold() for item in eligibility.get("excluded_cases", [])
    }
    truths: dict[str, EvaluatorGroundTruth] = {
        case_id.casefold(): _ground_truth_from_payload(raw["ground_truth"])
        for case_id, raw in recovery.get("records", {}).items()
        if raw.get("status") == "completed_ground_truth" and raw.get("ground_truth")
    }
    available_cases = tuple(
        case
        for case in all_manifest.cases
        if case.case_id.casefold() not in excluded_case_ids
    )
    if len(available_cases) != int(eligibility.get("eligible_case_count", 0)):
        raise ComparisonError("Eligibility cohort size differs from the lock")
    if {case.case_id.casefold() for case in available_cases} != set(truths):
        raise ComparisonError("Eligibility cohort and recovered ground truth differ")
    if len(available_cases) < 500:
        raise ComparisonError(f"Recovery evaluator coverage is unexpectedly low: {len(available_cases)}")
    available_manifest = BenchmarkManifest(cases=available_cases)

    biovoid_records = _load_detector_records(static_run)
    fpocket_records = _load_baseline_records(fpocket_report, detector="fpocket")
    p2rank_records = _load_baseline_records(p2rank_report, detector="p2rank")
    results = {}
    for detector, records in (
        ("biovoid_static", biovoid_records),
        ("fpocket", fpocket_records),
        ("p2rank", p2rank_records),
    ):
        results[detector] = evaluate_split(
            detector=detector,
            split="development",
            records=records,
            ground_truth=truths,
            manifest=available_manifest,
            protocol=protocol,
        )

    output = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "complete_relocked_development_comparison",
        "scientific_superiority_claim_authorized": False,
        "sealed_evaluation_authorized": False,
        "target_blind_detector_inputs": True,
        "protocol_sha256": protocol.protocol_sha256,
        "original_manifest_sha256": all_manifest.manifest_sha256,
        "available_subset_manifest_sha256": available_manifest.manifest_sha256,
        "recovery_report_sha256": _sha256_file(paths["recovery"]),
        "evaluator_eligibility_lock_sha256": _sha256_file(paths["eligibility"]),
        "baseline_report_sha256": {
            "fpocket": _sha256_file(paths["fpocket"]),
            "p2rank": _sha256_file(paths["p2rank"]),
        },
        "coverage": {
            "original_case_count": len(all_manifest.cases_for_split("development")),
            "available_ground_truth_case_count": len(available_cases),
            "residual_unavailable_case_count": len(all_manifest.cases_for_split("development"))
            - len(available_cases),
            "recovered_by_structural_fit": recovery["counts"]["structural_recovered"],
        },
        "comparison_scope": {
            "split": "development",
            "same_prepared_apo_inputs": True,
            "same_case_subset": True,
            "rank_scope": [1, 3, 5],
            "primary_endpoint": "top_3_dcc_localization_recall",
            "interpretation": "relocked_development_only_not_sealed_or_claim_authorized",
        },
        "results": results,
    }
    _write_json_atomic(paths["output"], output)
    print(
        "RI-3 external comparison: complete re-locked development cohort "
        f"cases={len(available_cases)} residual={output['coverage']['residual_unavailable_case_count']}"
    )
    for detector, result in results.items():
        print(
            f"{detector}: top3_dcc={result['top_k_dcc_recall'][3]} "
            f"top3_dca={result['top_k_dca_recall'][3]} "
            f"failure_rate={result['failure_rate']}"
        )
    print(f"comparison report: {paths['output']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ComparisonError as exc:
        print(f"RI-3 comparison error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
