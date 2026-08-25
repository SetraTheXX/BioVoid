"""Compare PocketMiner held-out BioVoid, fpocket, and P2Rank records.

The detector outputs are already completed and target-blind. This evaluator
opens only the private held-out labels, applies the frozen DCC/DCA protocol,
and writes a diagnostic comparison. It never reruns a detector, retunes a
policy, enables motion/NMA, trains ML, or authorizes superiority/discovery.
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

from scripts.check_target_family_baseline_readiness import (  # noqa: E402
    validate_baseline_input_manifest,
)
from scripts.evaluate_pocketminer_development import _ground_truth  # noqa: E402
from scripts.evaluate_pocketminer_ranking_policies import (  # noqa: E402
    POLICY_IDS,
    _rank_pockets,
)
from scripts.run_target_family_external_baseline import (  # noqa: E402
    BASELINE_RUN_SCHEMA_VERSION,
    validate_baseline_report,
)
from src.benchmark_v1 import evaluate_case, phase6_frozen_protocol_v1  # noqa: E402
from src.evaluator_format import (  # noqa: E402
    DetectorEvaluationRecord,
    adapt_biovoid_pockets,
    adapt_fpocket_pockets,
    adapt_p2rank_rows,
)

DEFAULT_STATIC_RUN = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/heldout-static-v1/"
    "pocketminer-heldout-static-v1.json"
)
DEFAULT_LABELS = (
    REPO_ROOT / "local-private/research/ranking-study-source-catalog/pocketminer-v1/"
    "heldout-labels-v2/pocketminer-heldout-labels-v2.json"
)
DEFAULT_SELECTION = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/ranking-policy-selection-v1/"
    "pocketminer-ranking-policy-selection-v1.json"
)
DEFAULT_BASELINE_MANIFEST = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/external-baseline-readiness-v1/"
    "pocketminer-heldout-baseline-input-v1.json"
)
DEFAULT_FPOCKET = (
    REPO_ROOT / "data/runtime/target-family/external-baselines-pocketminer-v1/"
    "fpocket-pocketminer-heldout-v1.json"
)
DEFAULT_P2RANK = (
    REPO_ROOT / "data/runtime/target-family/external-baselines-pocketminer-v1/"
    "p2rank-pocketminer-heldout-v1.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/external-baseline-comparison-v1/"
    "pocketminer-external-baseline-comparison-v1.json"
)
EXPECTED_CASES = 4
HELDOUT_SPLITS = frozenset({"validation", "test"})
TOP_K = (1, 3, 5, 10)
LOCKED_POLICY_ID = POLICY_IDS[0]


class PocketMinerExternalComparisonError(RuntimeError):
    """Raised when the evaluator-only comparison contract is invalid."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PocketMinerExternalComparisonError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PocketMinerExternalComparisonError(f"JSON root must be an object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _top_k_metrics(
    evaluation: Any,
    *,
    dcc_tolerance: float,
    dca_tolerance: float,
) -> dict[str, Any]:
    dcc = tuple(evaluation.dcc_by_rank)
    dca = tuple(evaluation.dca_by_rank)
    joint_rank = next(
        (
            index
            for index, (dcc_value, dca_value) in enumerate(zip(dcc, dca, strict=True), start=1)
            if dcc_value <= dcc_tolerance and dca_value <= dca_tolerance
        ),
        None,
    )
    result = asdict(evaluation)
    result["dcc_by_rank"] = list(evaluation.dcc_by_rank)
    result["dca_by_rank"] = list(evaluation.dca_by_rank)
    result["top_k_dcc_hits"] = {
        str(k): any(value <= dcc_tolerance for value in dcc[:k]) for k in TOP_K
    }
    result["top_k_dca_hits"] = {
        str(k): any(value <= dca_tolerance for value in dca[:k]) for k in TOP_K
    }
    result["top_k_joint_hits"] = {
        str(k): any(
            dcc_value <= dcc_tolerance and dca_value <= dca_tolerance
            for dcc_value, dca_value in zip(dcc[:k], dca[:k], strict=True)
        )
        for k in TOP_K
    }
    result["best_dcc_rank"] = next(
        (index for index, value in enumerate(dcc, start=1) if value <= dcc_tolerance), None
    )
    result["best_dca_rank"] = next(
        (index for index, value in enumerate(dca, start=1) if value <= dca_tolerance), None
    )
    result["best_joint_rank"] = joint_rank
    return result


def _evaluate_record(
    detector: DetectorEvaluationRecord,
    truth: Any,
    protocol: Any,
    *,
    case_id: str,
    structure_id: str,
    split: str,
    source: str,
) -> dict[str, Any]:
    if detector.status != "completed" or not detector.pockets:
        raise PocketMinerExternalComparisonError(
            f"{source} detector record is unavailable: {structure_id}"
        )
    evaluation = evaluate_case(detector, truth, protocol)
    metrics = _top_k_metrics(
        evaluation,
        dcc_tolerance=float(protocol.dcc_tolerance_angstrom),
        dca_tolerance=float(protocol.dca_tolerance_angstrom),
    )
    return {
        "case_id": case_id,
        "structure_id": structure_id,
        "split": split,
        "status": "completed_external_diagnostic",
        "source": source,
        "candidate_count": len(detector.pockets),
        "case_evaluation": metrics,
        "detector_scores_used": False,
        "target_blind_detector_record": True,
    }


def _external_record(
    report: Mapping[str, Any], detector: str, structure_id: str
) -> DetectorEvaluationRecord:
    records = report.get("records")
    if not isinstance(records, Mapping):
        raise PocketMinerExternalComparisonError(f"{detector} records are malformed")
    raw_case = records.get(structure_id)
    if not isinstance(raw_case, Mapping) or raw_case.get("detector_status") != "completed":
        raise PocketMinerExternalComparisonError(f"{detector} case is not complete: {structure_id}")
    payload = raw_case.get("detector_record")
    if not isinstance(payload, Mapping) or payload.get("status") != "completed":
        raise PocketMinerExternalComparisonError(
            f"{detector} detector payload is missing: {structure_id}"
        )
    pockets = payload.get("pockets")
    if not isinstance(pockets, list) or not pockets:
        raise PocketMinerExternalComparisonError(f"{detector} pockets are missing: {structure_id}")
    provenance = dict(payload.get("provenance") or {})
    provenance["target_blind"] = True
    provenance["comparison_source"] = "pocketminer-heldout-external-baseline-v1"
    if detector == "fpocket":
        normalized = []
        for pocket in pockets:
            if not isinstance(pocket, Mapping):
                raise PocketMinerExternalComparisonError(
                    f"fpocket pocket payload is malformed: {structure_id}"
                )
            row = dict(pocket.get("raw") or {})
            row.update(
                {
                    "center": pocket.get("center"),
                    "pocket_id": (pocket.get("raw") or {}).get(
                        "pocket_id", pocket.get("pocket_id")
                    ),
                    "rank": pocket.get("rank"),
                    "score": pocket.get("score"),
                    "volume": pocket.get("volume"),
                }
            )
            normalized.append(row)
        return adapt_fpocket_pockets(structure_id, normalized, provenance=provenance)
    if detector == "p2rank":
        normalized = []
        for pocket in pockets:
            if not isinstance(pocket, Mapping):
                raise PocketMinerExternalComparisonError(
                    f"p2rank pocket payload is malformed: {structure_id}"
                )
            center = pocket.get("center")
            if not isinstance(center, (list, tuple)) or len(center) != 3:
                raise PocketMinerExternalComparisonError(
                    f"p2rank pocket center is malformed: {structure_id}"
                )
            row = dict(pocket.get("raw") or {})
            row.update(
                {
                    "center_x": center[0],
                    "center_y": center[1],
                    "center_z": center[2],
                    "rank": pocket.get("rank"),
                    "score": pocket.get("score"),
                    "volume": pocket.get("volume"),
                }
            )
            normalized.append(row)
        return adapt_p2rank_rows(structure_id, normalized, provenance=provenance)
    raise PocketMinerExternalComparisonError(f"unsupported external detector: {detector}")


def _summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise PocketMinerExternalComparisonError("cannot summarize empty detector records")
    return {
        "case_count": len(records),
        "validation_count": sum(record["split"] == "validation" for record in records),
        "temporal_test_count": sum(record["split"] == "test" for record in records),
        "top_k_dcc_recall": {
            str(k): round(
                sum(record["case_evaluation"]["top_k_dcc_hits"][str(k)] for record in records)
                / len(records),
                8,
            )
            for k in TOP_K
        },
        "top_k_dca_recall": {
            str(k): round(
                sum(record["case_evaluation"]["top_k_dca_hits"][str(k)] for record in records)
                / len(records),
                8,
            )
            for k in TOP_K
        },
        "top_k_joint_recall": {
            str(k): round(
                sum(record["case_evaluation"]["top_k_joint_hits"][str(k)] for record in records)
                / len(records),
                8,
            )
            for k in TOP_K
        },
        "candidate_universe_dcc_recall": round(
            sum(record["case_evaluation"]["best_dcc_rank"] is not None for record in records)
            / len(records),
            8,
        ),
        "candidate_universe_dca_recall": round(
            sum(record["case_evaluation"]["best_dca_rank"] is not None for record in records)
            / len(records),
            8,
        ),
        "candidate_universe_joint_recall": round(
            sum(record["case_evaluation"]["best_joint_rank"] is not None for record in records)
            / len(records),
            8,
        ),
    }


def evaluate_pocketminer_external_baselines(
    *,
    static_run_path: Path = DEFAULT_STATIC_RUN,
    labels_path: Path = DEFAULT_LABELS,
    selection_path: Path = DEFAULT_SELECTION,
    baseline_manifest_path: Path = DEFAULT_BASELINE_MANIFEST,
    fpocket_path: Path = DEFAULT_FPOCKET,
    p2rank_path: Path = DEFAULT_P2RANK,
    output_path: Path = DEFAULT_OUTPUT,
    approve_evaluator: bool = False,
) -> dict[str, Any]:
    if not approve_evaluator:
        raise PocketMinerExternalComparisonError(
            "Opening held-out labels for external comparison requires --approve-evaluator"
        )
    static_run = _read_json(static_run_path.resolve())
    labels = _read_json(labels_path.resolve())
    selection = _read_json(selection_path.resolve())
    baseline_manifest = _read_json(baseline_manifest_path.resolve())
    fpocket_report = _read_json(fpocket_path.resolve())
    p2rank_report = _read_json(p2rank_path.resolve())
    if (
        static_run.get("status") != "completed"
        or static_run.get("retention") != "full_final_pocket_list"
    ):
        raise PocketMinerExternalComparisonError("held-out static run is not complete/full-list")
    boundary = static_run.get("boundary")
    if not isinstance(boundary, Mapping) or boundary.get("target_blind") is not True:
        raise PocketMinerExternalComparisonError("held-out static boundary is unsafe")
    if (
        labels.get("status") != "completed_review_required"
        or labels.get("heldout_only") is not True
    ):
        raise PocketMinerExternalComparisonError("held-out labels are not complete/held-out-only")
    if labels.get("evaluator_only") is not True or labels.get("detector_started") is not False:
        raise PocketMinerExternalComparisonError("held-out label boundary is unsafe")
    if labels.get("counts") != {"completed": EXPECTED_CASES, "failed": 0}:
        raise PocketMinerExternalComparisonError("held-out label counts are incomplete")
    if labels.get("alignment_policy", {}).get("policy_version") != (
        "ground-truth-alignment-pocketminer-v2"
    ):
        raise PocketMinerExternalComparisonError("unexpected held-out alignment policy")
    if selection.get("selected_policy_id") != LOCKED_POLICY_ID:
        raise PocketMinerExternalComparisonError("development policy selection is not locked to A")
    try:
        validate_baseline_input_manifest(baseline_manifest)
    except ValueError as exc:
        raise PocketMinerExternalComparisonError(str(exc)) from exc
    if baseline_manifest.get("manifest_sha256") not in {
        fpocket_report.get("manifest_sha256"),
        p2rank_report.get("manifest_sha256"),
    }:
        raise PocketMinerExternalComparisonError("baseline report manifest binding is incomplete")
    for name, report in (("fpocket", fpocket_report), ("p2rank", p2rank_report)):
        if report.get("schema_version") != BASELINE_RUN_SCHEMA_VERSION:
            raise PocketMinerExternalComparisonError(f"unexpected {name} baseline schema")
        if report.get("status") not in {"complete", "complete_with_failures"}:
            raise PocketMinerExternalComparisonError(f"{name} baseline is incomplete")
        if report.get("target_blind") is not True or report.get("evaluator_opened") is not False:
            raise PocketMinerExternalComparisonError(f"{name} baseline crossed evaluator boundary")
        try:
            validate_baseline_report(
                report,
                baseline=name,
                manifest=baseline_manifest,
                image_id=str(report.get("container_image_id", "")),
            )
        except (KeyError, ValueError, RuntimeError) as exc:
            raise PocketMinerExternalComparisonError(str(exc)) from exc
    static_records = static_run.get("records")
    label_records = labels.get("records")
    if not isinstance(static_records, list) or not isinstance(label_records, Mapping):
        raise PocketMinerExternalComparisonError("held-out static/label records are malformed")
    static_by_case = {str(record.get("case_id")): record for record in static_records}
    case_ids = sorted(label_records)
    if len(case_ids) != EXPECTED_CASES or set(case_ids) != set(static_by_case):
        raise PocketMinerExternalComparisonError("held-out static/label case sets differ")
    if {str(static_by_case[case_id].get("split")) for case_id in case_ids} != HELDOUT_SPLITS:
        raise PocketMinerExternalComparisonError("validation and temporal/test rows are incomplete")
    baseline_structure_ids = {
        str(item.get("structure_id", "")).upper()
        for item in baseline_manifest.get("structures", [])
        if isinstance(item, Mapping)
    }
    static_structure_ids = {
        str(static_by_case[case_id].get("structure_id", "")).upper() for case_id in case_ids
    }
    if baseline_structure_ids != static_structure_ids:
        raise PocketMinerExternalComparisonError("baseline/static structure sets differ")
    protocol = phase6_frozen_protocol_v1()
    detector_records: dict[str, list[dict[str, Any]]] = {
        "biovoid_static": [],
        "fpocket": [],
        "p2rank": [],
    }
    for case_id in case_ids:
        static_case = static_by_case[case_id]
        structure_id = str(static_case.get("structure_id", "")).upper()
        split = str(static_case.get("split", ""))
        truth = _ground_truth(label_records[case_id]["ground_truth"])
        if truth.case_id != case_id or truth.structure_id != structure_id:
            raise PocketMinerExternalComparisonError(f"static/label identity mismatch: {case_id}")
        pockets = static_case.get("final_pockets")
        if not isinstance(pockets, list) or not pockets:
            raise PocketMinerExternalComparisonError(f"BioVoid pockets are missing: {structure_id}")
        biovoid = adapt_biovoid_pockets(
            structure_id,
            _rank_pockets(pockets, LOCKED_POLICY_ID),
            provenance={
                "source": "pocketminer-heldout-static-v1",
                "target_blind": True,
                "locked_policy_id": LOCKED_POLICY_ID,
            },
        )
        detector_records["biovoid_static"].append(
            _evaluate_record(
                biovoid,
                truth,
                protocol,
                case_id=case_id,
                structure_id=structure_id,
                split=split,
                source="biovoid_static",
            )
        )
        for name, report in (("fpocket", fpocket_report), ("p2rank", p2rank_report)):
            detector_records[name].append(
                _evaluate_record(
                    _external_record(report, name, structure_id),
                    truth,
                    protocol,
                    case_id=case_id,
                    structure_id=structure_id,
                    split=split,
                    source=name,
                )
            )
    results = {
        name: {"summary": _summary(records), "records": {item["case_id"]: item for item in records}}
        for name, records in detector_records.items()
    }
    report: dict[str, Any] = {
        "schema_version": "biovoid-pocketminer-external-baseline-comparison-v1",
        "status": "completed_diagnostic_only",
        "source": "pocketminer-novel-cryptic-pocket-set-v1",
        "static_run_sha256": _sha256_file(static_run_path.resolve()),
        "labels_report_sha256": _sha256_file(labels_path.resolve()),
        "selection_report_sha256": _sha256_file(selection_path.resolve()),
        "baseline_manifest_sha256": baseline_manifest["manifest_sha256"],
        "baseline_report_sha256": {
            "fpocket": _sha256_file(fpocket_path.resolve()),
            "p2rank": _sha256_file(p2rank_path.resolve()),
        },
        "protocol_sha256": protocol.protocol_sha256,
        "candidate_scope": "full_final_pocket_list_for_biovoid;tool_retained_top20_for_external",
        "detector_target_blind": True,
        "evaluator_only": True,
        "claim_boundary": "diagnostic_dcc_dca_comparison_only",
        "results": results,
        "comparison_scope": {
            "case_count": EXPECTED_CASES,
            "validation_count": sum(
                item["split"] == "validation" for item in detector_records["biovoid_static"]
            ),
            "temporal_test_count": sum(
                item["split"] == "test" for item in detector_records["biovoid_static"]
            ),
            "same_prepared_apo_inputs": True,
            "workers": 1,
            "motion_enabled": False,
            "ml_training_started": False,
            "retuning_performed": False,
            "heldout_evaluator_opened_after_detector_runs": True,
        },
        "claims_authorized": {
            "scientific_superiority": False,
            "validated_prediction": False,
            "discovery": False,
        },
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "report_sha256": None,
    }
    report["report_sha256"] = _stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    _write_json(output_path.resolve(), report)
    print(f"PocketMiner external comparison: cases={EXPECTED_CASES} diagnostic_only")
    for name, result in results.items():
        summary = result["summary"]
        print(
            f"{name}: joint_top1/3/5/10="
            f"{summary['top_k_joint_recall']['1']}/"
            f"{summary['top_k_joint_recall']['3']}/"
            f"{summary['top_k_joint_recall']['5']}/"
            f"{summary['top_k_joint_recall']['10']} "
            f"dcc_top5={summary['top_k_dcc_recall']['5']} "
            f"dca_top5={summary['top_k_dca_recall']['5']}"
        )
    print(f"comparison report: {output_path}")
    print("retuning/NMA/ML/discovery claim: no")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--baseline-manifest", type=Path, default=DEFAULT_BASELINE_MANIFEST)
    parser.add_argument("--fpocket", type=Path, default=DEFAULT_FPOCKET)
    parser.add_argument("--p2rank", type=Path, default=DEFAULT_P2RANK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--approve-evaluator", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        evaluate_pocketminer_external_baselines(
            static_run_path=args.static_run,
            labels_path=args.labels,
            selection_path=args.selection,
            baseline_manifest_path=args.baseline_manifest,
            fpocket_path=args.fpocket,
            p2rank_path=args.p2rank,
            output_path=args.output,
            approve_evaluator=args.approve_evaluator,
        )
    except (PocketMinerExternalComparisonError, OSError, ValueError, KeyError) as exc:
        print(f"PocketMiner external comparison error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
