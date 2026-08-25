"""Evaluate the sealed PocketMiner development static run, evaluator-only.

This command joins the target-blind BioVoid static output with the private,
independently curated PocketMiner holo labels.  It computes only the frozen
DCC/DCA geometry metrics and a descriptive detection-vs-ranking decomposition.
It never reruns the detector, changes ranking weights, opens validation/test
labels, runs motion/NMA, calls an external baseline, or trains ML.
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

from src.benchmark_v1 import (  # noqa: E402
    EvaluatorGroundTruth,
    evaluate_case,
    phase6_frozen_protocol_v1,
)
from src.evaluator_format import adapt_biovoid_pockets  # noqa: E402


DEFAULT_STATIC_RUN = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/development-static-v1/"
    "pocketminer-development-static-v1.json"
)
DEFAULT_LABELS = (
    REPO_ROOT / "local-private/research/ranking-study-source-catalog/pocketminer-v1/"
    "development-labels-v2/pocketminer-development-labels-v2.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/development-evaluation-v1/"
    "pocketminer-development-evaluation-v1.json"
)
SCHEMA_VERSION = "biovoid-pocketminer-development-evaluation-v1"
MAX_DEVELOPMENT_CASES = 6
TOP_K = (1, 3, 5, 10)


class PocketMinerDevelopmentEvaluationError(RuntimeError):
    """Raised when the evaluator-only development contract cannot proceed."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PocketMinerDevelopmentEvaluationError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PocketMinerDevelopmentEvaluationError(f"JSON root must be an object: {path}")
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _as_coordinate(value: Any, field: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise PocketMinerDevelopmentEvaluationError(f"{field} must contain three coordinates")
    return tuple(float(item) for item in value)


def _ground_truth(payload: Mapping[str, Any]) -> EvaluatorGroundTruth:
    atoms = payload.get("ligand_atoms")
    if not isinstance(atoms, list) or not atoms:
        raise PocketMinerDevelopmentEvaluationError("label ground truth has no ligand atoms")
    residues = payload.get("ligand_residues", [])
    if not isinstance(residues, list):
        raise PocketMinerDevelopmentEvaluationError("label ligand residues are malformed")
    try:
        return EvaluatorGroundTruth(
            case_id=str(payload["case_id"]),
            structure_id=str(payload["structure_id"]).upper(),
            coordinate_frame_sha256=str(payload["coordinate_frame_sha256"]),
            alignment_sha256=str(payload["alignment_sha256"]),
            ligand_center=_as_coordinate(payload["ligand_center"], "ligand_center"),
            ligand_atoms=tuple(_as_coordinate(atom, "ligand_atom") for atom in atoms),
            ligand_residues=tuple(str(value) for value in residues),
            quality=str(payload.get("quality", "exact")),
            provenance=str(payload.get("provenance", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PocketMinerDevelopmentEvaluationError("invalid evaluator ground truth") from exc


def _first_hit(values: tuple[float, ...], tolerance: float) -> int | None:
    for index, value in enumerate(values, start=1):
        if value <= tolerance:
            return index
    return None


def _feature_snapshot(pockets: list[Mapping[str, Any]], rank: int | None) -> dict[str, Any] | None:
    if rank is None or not 1 <= rank <= len(pockets):
        return None
    pocket = pockets[rank - 1]
    fields = (
        "pocket_id",
        "rank",
        "volume",
        "enclosure",
        "depth",
        "hydrophobic_ratio",
        "minimum_surface_clearance",
        "radius_clear",
        "radius_geom",
    )
    return {field: pocket.get(field) for field in fields if field in pocket}


def _case_evaluation(
    static_case: Mapping[str, Any],
    label_record: Mapping[str, Any],
    protocol: Any,
) -> dict[str, Any]:
    case_id = str(static_case.get("case_id"))
    structure_id = str(static_case.get("structure_id", "")).upper()
    if static_case.get("status") != "completed":
        raise PocketMinerDevelopmentEvaluationError(f"static case is not completed: {case_id}")
    if label_record.get("status") != "completed_ground_truth":
        raise PocketMinerDevelopmentEvaluationError(f"label case is not completed: {case_id}")
    pockets = static_case.get("final_pockets")
    if not isinstance(pockets, list) or not pockets:
        raise PocketMinerDevelopmentEvaluationError(f"static case has no final pockets: {case_id}")
    detector = adapt_biovoid_pockets(
        structure_id,
        pockets,
        provenance={
            "source": "pocketminer-development-static-v1",
            "target_blind": True,
            "candidate_retention": "full_final_pocket_list",
        },
    )
    ground_truth = _ground_truth(label_record["ground_truth"])
    if ground_truth.case_id != case_id or ground_truth.structure_id != structure_id:
        raise PocketMinerDevelopmentEvaluationError(
            f"static/label identity mismatch: {case_id} ({structure_id})"
        )
    evaluation = evaluate_case(detector, ground_truth, protocol)
    dcc = tuple(evaluation.dcc_by_rank)
    dca = tuple(evaluation.dca_by_rank)
    dcc_rank = _first_hit(dcc, float(protocol.dcc_tolerance_angstrom))
    dca_rank = _first_hit(dca, float(protocol.dca_tolerance_angstrom))
    joint_rank = next(
        (
            index
            for index, (dcc_value, dca_value) in enumerate(zip(dcc, dca, strict=True), start=1)
            if dcc_value <= float(protocol.dcc_tolerance_angstrom)
            and dca_value <= float(protocol.dca_tolerance_angstrom)
        ),
        None,
    )
    top_k = {
        str(k): {
            "dcc": any(value <= float(protocol.dcc_tolerance_angstrom) for value in dcc[:k]),
            "dca": any(value <= float(protocol.dca_tolerance_angstrom) for value in dca[:k]),
            "joint": any(
                dcc_value <= float(protocol.dcc_tolerance_angstrom)
                and dca_value <= float(protocol.dca_tolerance_angstrom)
                for dcc_value, dca_value in zip(dcc[:k], dca[:k], strict=True)
            ),
        }
        for k in TOP_K
    }
    if joint_rank is None:
        taxonomy = "detector_miss"
    elif joint_rank > 5:
        taxonomy = "ranking_miss"
    else:
        taxonomy = "top5_joint_hit"
    if joint_rank is None and dcc_rank is not None and dca_rank is not None:
        taxonomy = "metric_disagreement"
    result = asdict(evaluation)
    result["dcc_by_rank"] = list(evaluation.dcc_by_rank)
    result["dca_by_rank"] = list(evaluation.dca_by_rank)
    return {
        "case_id": case_id,
        "structure_id": structure_id,
        "status": "completed_diagnostic",
        "candidate_count": len(pockets),
        "dcc_candidate_universe_hit": dcc_rank is not None,
        "dca_candidate_universe_hit": dca_rank is not None,
        "joint_candidate_universe_hit": joint_rank is not None,
        "best_dcc_rank": dcc_rank,
        "best_dca_rank": dca_rank,
        "best_joint_rank": joint_rank,
        "taxonomy": taxonomy,
        "top_k": top_k,
        "best_dcc_angstrom": min(dcc) if dcc else None,
        "best_dca_angstrom": min(dca) if dca else None,
        "best_joint_candidate_features": _feature_snapshot(pockets, joint_rank),
        "top_rank_candidate_features": _feature_snapshot(pockets, 1),
        "case_evaluation": result,
        "detector_scores_used": False,
        "label_only_evaluator_arm": True,
    }


def _recall(records: list[Mapping[str, Any]], metric: str, k: int) -> float:
    if not records:
        return 0.0
    return round(
        sum(bool(record["top_k"][str(k)][metric]) for record in records) / len(records),
        8,
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def evaluate_pocketminer_development(
    *,
    static_run_path: Path = DEFAULT_STATIC_RUN,
    labels_path: Path = DEFAULT_LABELS,
    output_path: Path = DEFAULT_OUTPUT,
    approve_evaluator: bool = False,
) -> dict[str, Any]:
    if not approve_evaluator:
        raise PocketMinerDevelopmentEvaluationError(
            "Opening private holo labels requires --approve-evaluator"
        )
    static_run = _read_json(static_run_path.resolve())
    labels = _read_json(labels_path.resolve())
    if static_run.get("status") != "completed":
        raise PocketMinerDevelopmentEvaluationError("static run is not completed")
    if static_run.get("retention") != "full_final_pocket_list":
        raise PocketMinerDevelopmentEvaluationError("static run is not full-list retained")
    boundary = static_run.get("boundary")
    if not isinstance(boundary, Mapping) or boundary.get("target_blind") is not True:
        raise PocketMinerDevelopmentEvaluationError("static run target-blind boundary is invalid")
    if labels.get("status") != "completed_review_required" or labels.get("counts") != {
        "completed": MAX_DEVELOPMENT_CASES,
        "failed": 0,
    }:
        raise PocketMinerDevelopmentEvaluationError("PocketMiner v2 labels are not complete")
    if labels.get("evaluator_only") is not True or labels.get("detector_started") is not False:
        raise PocketMinerDevelopmentEvaluationError("label boundary is unsafe")
    if labels.get("alignment_policy", {}).get("policy_version") != (
        "ground-truth-alignment-pocketminer-v2"
    ):
        raise PocketMinerDevelopmentEvaluationError("unexpected PocketMiner alignment policy")
    static_cases = static_run.get("records")
    label_cases = labels.get("records")
    if not isinstance(static_cases, list) or not isinstance(label_cases, Mapping):
        raise PocketMinerDevelopmentEvaluationError("static or label records are malformed")
    static_by_case = {str(case.get("case_id")): case for case in static_cases}
    case_ids = sorted(label_cases)
    if len(case_ids) != MAX_DEVELOPMENT_CASES or set(case_ids) != set(static_by_case):
        raise PocketMinerDevelopmentEvaluationError("static/label case sets are not identical")

    protocol = phase6_frozen_protocol_v1()
    records = [
        _case_evaluation(static_by_case[case_id], label_cases[case_id], protocol)
        for case_id in case_ids
    ]
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "diagnostic_only_not_for_claim",
        "source": "pocketminer-novel-cryptic-pocket-set-v1",
        "static_run_sha256": _sha256_file(static_run_path.resolve()),
        "labels_report_sha256": _sha256_file(labels_path.resolve()),
        "protocol": asdict(protocol),
        "protocol_sha256": protocol.protocol_sha256,
        "candidate_scope": "full_final_pocket_list",
        "ranking_policy": static_run.get("ranking_policy"),
        "detector_target_blind": True,
        "evaluator_only": True,
        "detector_scores_used": False,
        "claim_boundary": "diagnostic_dcc_dca_detection_vs_ranking_only",
        "execution": {
            "workers": 1,
            "detector_rerun": False,
            "coordinates_downloaded": False,
            "motion_enabled": False,
            "external_baselines_enabled": False,
            "ml_training_started": False,
        },
        "records": {record["case_id"]: record for record in records},
        "counts": {
            "development_cases": len(records),
            "detector_miss": sum(record["taxonomy"] == "detector_miss" for record in records),
            "metric_disagreement": sum(
                record["taxonomy"] == "metric_disagreement" for record in records
            ),
            "ranking_miss": sum(record["taxonomy"] == "ranking_miss" for record in records),
            "top5_joint_hit": sum(record["taxonomy"] == "top5_joint_hit" for record in records),
            "joint_candidate_universe_hit": sum(
                record["joint_candidate_universe_hit"] for record in records
            ),
        },
        "summary": {
            "dcc_candidate_universe_recall": round(
                sum(record["dcc_candidate_universe_hit"] for record in records) / len(records),
                8,
            ),
            "dca_candidate_universe_recall": round(
                sum(record["dca_candidate_universe_hit"] for record in records) / len(records),
                8,
            ),
            "joint_candidate_universe_recall": round(
                sum(record["joint_candidate_universe_hit"] for record in records) / len(records),
                8,
            ),
            "top_k_dcc_recall": {str(k): _recall(records, "dcc", k) for k in TOP_K},
            "top_k_dca_recall": {str(k): _recall(records, "dca", k) for k in TOP_K},
            "top_k_joint_recall": {str(k): _recall(records, "joint", k) for k in TOP_K},
            "ranking_vs_detector_interpretation": (
                "ranking_dominant_descriptive_signal"
                if any(record["taxonomy"] == "ranking_miss" for record in records)
                else "no_ranking_dominant_signal_in_development"
            ),
        },
        "claims_authorized": {
            "scientific_superiority": False,
            "discovery": False,
            "validated_prediction": False,
        },
        "created_at_utc": _utc_now(),
        "report_sha256": None,
    }
    report["report_sha256"] = _stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    _write_json(output_path.resolve(), report)
    print(
        "PocketMiner development evaluation: "
        f"cases={len(records)} joint-universe={report['counts']['joint_candidate_universe_hit']} "
        f"ranking-miss={report['counts']['ranking_miss']}"
    )
    print(f"evaluation report: {output_path}")
    print("detector rerun/NMA/external baseline/ML: no")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--approve-evaluator", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        evaluate_pocketminer_development(
            static_run_path=args.static_run,
            labels_path=args.labels,
            output_path=args.output,
            approve_evaluator=args.approve_evaluator,
        )
    except (PocketMinerDevelopmentEvaluationError, OSError, ValueError) as exc:
        print(f"PocketMiner development evaluation error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
