"""Select one pre-registered shadow ranking policy on AHoJ development.

The detector and its full final-pocket lists are already sealed.  This command
only reorders those lists with the finite A/B/C policy set recorded in the
ranking-policy contract, evaluates the six development-only holo labels, and
writes a private selection report.  Validation and temporal/test labels remain
sealed until this report is complete.
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

from scripts.evaluate_ahoj_geometry_static_development import (  # noqa: E402
    decompose_case_evaluation,
)
from scripts.seal_ahoj_geometry_cohort import _read_json  # noqa: E402
from src.benchmark_v1 import (  # noqa: E402
    EvaluatorGroundTruth,
    evaluate_case,
    phase6_frozen_protocol_v1,
)
from src.evaluator_format import adapt_biovoid_pockets  # noqa: E402


DEFAULT_STATIC_RUN = (
    REPO_ROOT
    / "data/runtime/target-family/cohort-ahoj-geometry-v1/static-development-pilot-v1/"
    "ahoj-geometry-static-pilot-v1.json"
)
DEFAULT_EVALUATION = (
    REPO_ROOT
    / "local-private/research/geometry-data-source-catalog/ahoj-v1/"
    "evaluator-development-v3/ahoj-geometry-static-development-evaluation-v1.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "local-private/research/geometry-data-source-catalog/ahoj-v1/"
    "evaluator-development-v3/ahoj-geometry-ranking-policy-selection-v1.json"
)
SCHEMA_VERSION = "biovoid-ahoj-geometry-ranking-policy-selection-v1"
POLICY_LOCK_VERSION = "ranking-policy-lock-v1"
POLICY_IDS = (
    "A-canonical-volume-v1",
    "B-volume-enclosure-70-30-v1",
    "C-volume-enclosure-50-50-v1",
)
MAX_DEVELOPMENT_CASES = 6
TOP_K = (1, 3, 5, 10)


class AhojRankingPolicyError(RuntimeError):
    """Raised when the frozen A/B/C development contract cannot proceed."""


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


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _as_coordinate(value: Any, field: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise AhojRankingPolicyError(f"{field} must contain three coordinates")
    return tuple(float(item) for item in value)


def _ground_truth(payload: Mapping[str, Any]) -> EvaluatorGroundTruth:
    atoms = payload.get("ligand_atoms")
    if not isinstance(atoms, list) or not atoms:
        raise AhojRankingPolicyError("private evaluator ground truth has no ligand atoms")
    residues = payload.get("ligand_residues", [])
    if not isinstance(residues, list):
        raise AhojRankingPolicyError("private evaluator ligand residues are malformed")
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


def _minmax(values: list[float]) -> list[float]:
    if not values:
        raise AhojRankingPolicyError("cannot normalize an empty feature list")
    minimum = min(values)
    maximum = max(values)
    if maximum == minimum:
        return [0.0] * len(values)
    return [(value - minimum) / (maximum - minimum) for value in values]


def rank_pockets(pockets: list[Mapping[str, Any]], policy_id: str) -> list[dict[str, Any]]:
    """Apply only the locked A/B/C features and tie-breaks."""
    if policy_id not in POLICY_IDS:
        raise AhojRankingPolicyError(f"unknown locked policy: {policy_id}")
    if not pockets:
        raise AhojRankingPolicyError("static case has no final pockets")
    try:
        volumes = [float(pocket["volume"]) for pocket in pockets]
        enclosures = [float(pocket["enclosure"]) for pocket in pockets]
    except (KeyError, TypeError, ValueError) as exc:
        raise AhojRankingPolicyError("policy features are incomplete") from exc
    volume_norm = _minmax(volumes)
    enclosure_norm = _minmax(enclosures)
    scored: list[tuple[float, float, float, str, Mapping[str, Any]]] = []
    for index, pocket in enumerate(pockets):
        if policy_id == POLICY_IDS[0]:
            composite = volumes[index]
        elif policy_id == POLICY_IDS[1]:
            composite = 0.70 * volume_norm[index] + 0.30 * enclosure_norm[index]
        else:
            composite = 0.50 * volume_norm[index] + 0.50 * enclosure_norm[index]
        scored.append(
            (
                composite,
                volumes[index],
                enclosures[index],
                str(pocket.get("pocket_id", index)),
                pocket,
            )
        )
    ordered = sorted(scored, key=lambda item: (-item[0], -item[1], -item[2], item[3]))
    ranked: list[dict[str, Any]] = []
    for rank, (_, _, _, _, pocket) in enumerate(ordered, start=1):
        copy = dict(pocket)
        copy["rank"] = rank
        ranked.append(copy)
    return ranked


def _top10(evaluation: Any, metric: str, tolerance: float) -> bool:
    values = evaluation.dcc_by_rank if metric == "dcc" else evaluation.dca_by_rank
    return any(value <= tolerance for value in values[:10])


def _summary(records: list[Mapping[str, Any]], metric: str, k: int) -> float:
    if not records:
        return 0.0
    return round(
        sum(bool(record["case_evaluation"][f"top_k_{metric}_hits"][str(k)]) for record in records)
        / len(records),
        8,
    )


def _validate_inputs(
    static_run: Mapping[str, Any], evaluation_report: Mapping[str, Any]
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    if static_run.get("status") != "completed_target_blind_static_diagnostic":
        raise AhojRankingPolicyError("static run is not a completed target-blind artifact")
    if static_run.get("execution", {}).get("candidate_retention") != "full_final_pocket_list":
        raise AhojRankingPolicyError("A/B/C selection requires full final-pocket retention")
    if evaluation_report.get("schema_version") != (
        "biovoid-ahoj-geometry-static-development-evaluation-v1"
    ):
        raise AhojRankingPolicyError("unsupported private AHoJ evaluator report")
    if evaluation_report.get("status") != "completed_development_evaluator_diagnostic":
        raise AhojRankingPolicyError("evaluator report is not complete for all development cases")
    execution = evaluation_report.get("execution", {})
    if execution.get("validation_temporal_opened") is not False:
        raise AhojRankingPolicyError("validation/temporal labels were opened")
    if execution.get("detector_rerun") is not False or execution.get("ranking_changed") is not False:
        raise AhojRankingPolicyError("evaluator report is not bound to the original detector run")
    static_cases = static_run.get("cases")
    evaluator_records = evaluation_report.get("records")
    if not isinstance(static_cases, Mapping) or not isinstance(evaluator_records, Mapping):
        raise AhojRankingPolicyError("static/evaluator case maps are missing")
    if len(evaluator_records) != MAX_DEVELOPMENT_CASES:
        raise AhojRankingPolicyError("exactly six development evaluator rows are required")
    for case_id, record in evaluator_records.items():
        if not isinstance(record, Mapping) or record.get("status") != "completed":
            raise AhojRankingPolicyError(f"evaluator case is unavailable: {case_id}")
        static_case = static_cases.get(case_id)
        if not isinstance(static_case, Mapping) or static_case.get("status") != "completed":
            raise AhojRankingPolicyError(f"static case is unavailable: {case_id}")
        if not isinstance(static_case.get("all_pockets"), list):
            raise AhojRankingPolicyError(f"static pocket list is missing: {case_id}")
    return (
        {str(key): value for key, value in static_cases.items()},
        {str(key): value for key, value in evaluator_records.items()},
    )


def evaluate_ahoj_geometry_ranking_policies(
    *,
    static_run_path: Path = DEFAULT_STATIC_RUN,
    evaluation_path: Path = DEFAULT_EVALUATION,
    output_path: Path = DEFAULT_OUTPUT,
    approve_evaluator: bool = False,
) -> dict[str, Any]:
    if not approve_evaluator:
        raise AhojRankingPolicyError("opening private holo labels requires --approve-evaluator")
    static_run = _read_json(static_run_path.resolve())
    evaluation_report = _read_json(evaluation_path.resolve())
    static_cases, evaluator_records = _validate_inputs(static_run, evaluation_report)
    protocol = phase6_frozen_protocol_v1()
    variants: dict[str, Any] = {}
    case_ids = sorted(evaluator_records)
    for policy_id in POLICY_IDS:
        records: list[dict[str, Any]] = []
        for case_id in case_ids:
            static_case = static_cases[case_id]
            evaluator_record = evaluator_records[case_id]
            ranked = rank_pockets(static_case["all_pockets"], policy_id)
            structure_id = str(static_case["structure_id"]).upper()
            detector = adapt_biovoid_pockets(
                structure_id,
                ranked,
                provenance={
                    "source": "ahoj-geometry-static-development-v1",
                    "target_blind": True,
                    "shadow_policy_id": policy_id,
                    "policy_lock_version": POLICY_LOCK_VERSION,
                    "score_used": False,
                },
            )
            truth = _ground_truth(evaluator_record["ground_truth"])
            if truth.case_id != case_id or truth.structure_id != structure_id:
                raise AhojRankingPolicyError(f"static/evaluator identity mismatch: {case_id}")
            evaluation = evaluate_case(detector, truth, protocol)
            evaluation_payload = asdict(evaluation)
            evaluation_payload["dcc_by_rank"] = list(evaluation.dcc_by_rank)
            evaluation_payload["dca_by_rank"] = list(evaluation.dca_by_rank)
            evaluation_payload["top_k_dcc_hits"] = {
                str(key): bool(value) for key, value in evaluation.top_k_dcc_hits.items()
            }
            evaluation_payload["top_k_dca_hits"] = {
                str(key): bool(value) for key, value in evaluation.top_k_dca_hits.items()
            }
            evaluation_payload["top_k_dcc_hits"]["10"] = _top10(
                evaluation, "dcc", float(protocol.dcc_tolerance_angstrom)
            )
            evaluation_payload["top_k_dca_hits"]["10"] = _top10(
                evaluation, "dca", float(protocol.dca_tolerance_angstrom)
            )
            records.append(
                {
                    "case_id": case_id,
                    "structure_id": structure_id,
                    "policy_id": policy_id,
                    "case_evaluation": evaluation_payload,
                    "decomposition": decompose_case_evaluation(evaluation, protocol),
                    "detector_scores_used": False,
                    "holo_used_only_in_evaluator": True,
                }
            )
        variants[policy_id] = {
            "policy_id": policy_id,
            "records": {record["case_id"]: record for record in records},
            "summary": {
                "case_count": len(records),
                "dcc_top_1": _summary(records, "dcc", 1),
                "dcc_top_3": _summary(records, "dcc", 3),
                "dcc_top_5": _summary(records, "dcc", 5),
                "dcc_top_10": _summary(records, "dcc", 10),
                "dca_top_1": _summary(records, "dca", 1),
                "dca_top_3": _summary(records, "dca", 3),
                "dca_top_5": _summary(records, "dca", 5),
                "dca_top_10": _summary(records, "dca", 10),
                "joint_universe": sum(
                    bool(record["decomposition"]["candidate_universe"]["joint_hit"])
                    for record in records
                ),
            },
        }

    ranked_ids = sorted(
        POLICY_IDS,
        key=lambda policy_id: (
            variants[policy_id]["summary"]["dcc_top_3"],
            variants[policy_id]["summary"]["dca_top_3"],
            variants[policy_id]["summary"]["dcc_top_1"],
            -POLICY_IDS.index(policy_id),
        ),
        reverse=True,
    )
    selected_policy_id = ranked_ids[0]
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "development_policy_selected_shadow_only",
        "policy_lock_version": POLICY_LOCK_VERSION,
        "selection_rule": {
            "primary": "highest_case_level_dcc_top_3_recall",
            "tie_break_1": "dca_top_3_recall",
            "tie_break_2": "dcc_top_1_recall",
            "final_tie_break": "retain_A_canonical_baseline",
            "validation_temporal_opened": False,
        },
        "selected_policy_id": selected_policy_id,
        "selection_order": ranked_ids,
        "static_run_sha256": _sha256_file(static_run_path.resolve()),
        "evaluator_report_sha256": _sha256_file(evaluation_path.resolve()),
        "protocol_sha256": protocol.protocol_sha256,
        "ranking_policy_input": {
            "candidate_scope": "full_final_pocket_list",
            "features": ["volume", "enclosure"],
            "normalization": "within_case_minmax_v1",
            "depth_used": False,
            "hydrophobic_ratio_used": False,
            "detector_generation_changed": False,
        },
        "variants": variants,
        "boundary": {
            "development_only": True,
            "validation_labels_opened": False,
            "temporal_labels_opened": False,
            "detector_rerun": False,
            "motion_enabled": False,
            "external_baselines_enabled": False,
            "ml_training_started": False,
            "scientific_superiority_claim_authorized": False,
            "discovery_claim_authorized": False,
        },
        "created_at_utc": _utc_now(),
        "report_sha256": None,
    }
    report["report_sha256"] = _stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    _write_json(output_path.resolve(), report)
    selected = variants[selected_policy_id]["summary"]
    print(
        f"AHoJ ranking policy selection: selected={selected_policy_id} "
        f"dev_dcc_top3={selected['dcc_top_3']} dev_dca_top3={selected['dca_top_3']}"
    )
    print(f"private selection report: {output_path}")
    print("validation/temporal/NMA/external baseline/ML: unopened")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--evaluation", type=Path, default=DEFAULT_EVALUATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--approve-evaluator", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        report = evaluate_ahoj_geometry_ranking_policies(
            static_run_path=args.static_run,
            evaluation_path=args.evaluation,
            output_path=args.output,
            approve_evaluator=args.approve_evaluator,
        )
    except (AhojRankingPolicyError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"AHoJ ranking policy error: {exc}", file=sys.stderr)
        return 2
    return 0 if report["status"] == "development_policy_selected_shadow_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
