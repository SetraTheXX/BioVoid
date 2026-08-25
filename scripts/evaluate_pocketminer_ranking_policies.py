"""Select one pre-registered shadow ranking policy on PocketMiner development.

The canonical static pocket list is not regenerated.  A, B, and C are fixed
reorderings from ``local-private/specs/ranking-policy-lock-v1.md``.  Selection
uses only the six development labels and the frozen DCC/DCA protocol; the
reserved validation and temporal-test rows remain unopened.
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

from scripts.evaluate_pocketminer_development import _ground_truth  # noqa: E402
from src.benchmark_v1 import evaluate_case, phase6_frozen_protocol_v1  # noqa: E402
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
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/ranking-policy-selection-v1/"
    "pocketminer-ranking-policy-selection-v1.json"
)
SCHEMA_VERSION = "biovoid-pocketminer-ranking-policy-selection-v1"
POLICY_LOCK_VERSION = "ranking-policy-lock-v1"
POLICY_IDS = (
    "A-canonical-volume-v1",
    "B-volume-enclosure-70-30-v1",
    "C-volume-enclosure-50-50-v1",
)
MAX_DEVELOPMENT_CASES = 6
TOP_K = (1, 3, 5, 10)


class PocketMinerRankingPolicyError(RuntimeError):
    """Raised when the frozen shadow-policy contract cannot proceed."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PocketMinerRankingPolicyError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PocketMinerRankingPolicyError(f"JSON root must be an object: {path}")
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


def _minmax(values: list[float]) -> list[float]:
    if not values:
        raise PocketMinerRankingPolicyError("cannot normalize an empty feature list")
    minimum = min(values)
    maximum = max(values)
    if maximum == minimum:
        return [0.0] * len(values)
    return [(value - minimum) / (maximum - minimum) for value in values]


def _rank_pockets(pockets: list[Mapping[str, Any]], policy_id: str) -> list[dict[str, Any]]:
    if policy_id not in POLICY_IDS:
        raise PocketMinerRankingPolicyError(f"unknown locked policy: {policy_id}")
    if not pockets:
        raise PocketMinerRankingPolicyError("static case has no final pockets")
    try:
        volumes = [float(pocket["volume"]) for pocket in pockets]
        enclosures = [float(pocket["enclosure"]) for pocket in pockets]
    except (KeyError, TypeError, ValueError) as exc:
        raise PocketMinerRankingPolicyError("policy features are incomplete") from exc
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


def _policy_case(
    static_case: Mapping[str, Any], label_record: Mapping[str, Any], policy_id: str
) -> dict[str, Any]:
    case_id = str(static_case.get("case_id"))
    structure_id = str(static_case.get("structure_id", "")).upper()
    pockets = static_case.get("final_pockets")
    if static_case.get("status") != "completed" or not isinstance(pockets, list):
        raise PocketMinerRankingPolicyError(f"static case is unavailable: {case_id}")
    if label_record.get("status") != "completed_ground_truth":
        raise PocketMinerRankingPolicyError(f"label case is unavailable: {case_id}")
    ranked = _rank_pockets(pockets, policy_id)
    detector = adapt_biovoid_pockets(
        structure_id,
        ranked,
        provenance={
            "source": "pocketminer-development-static-v1",
            "target_blind": True,
            "shadow_policy_id": policy_id,
            "policy_lock_version": POLICY_LOCK_VERSION,
        },
    )
    truth = _ground_truth(label_record["ground_truth"])
    if truth.case_id != case_id or truth.structure_id != structure_id:
        raise PocketMinerRankingPolicyError(f"static/label identity mismatch: {case_id}")
    evaluation = evaluate_case(detector, truth, phase6_frozen_protocol_v1())
    summary = asdict(evaluation)
    summary["dcc_by_rank"] = list(evaluation.dcc_by_rank)
    summary["dca_by_rank"] = list(evaluation.dca_by_rank)
    summary["top_k_dcc_hits"] = {
        str(key): value for key, value in evaluation.top_k_dcc_hits.items()
    }
    summary["top_k_dca_hits"] = {
        str(key): value for key, value in evaluation.top_k_dca_hits.items()
    }
    summary["top_k_dcc_hits"]["10"] = any(
        value <= float(phase6_frozen_protocol_v1().dcc_tolerance_angstrom)
        for value in evaluation.dcc_by_rank[:10]
    )
    summary["top_k_dca_hits"]["10"] = any(
        value <= float(phase6_frozen_protocol_v1().dca_tolerance_angstrom)
        for value in evaluation.dca_by_rank[:10]
    )
    return {
        "case_id": case_id,
        "structure_id": structure_id,
        "status": "completed_policy_evaluation",
        "policy_id": policy_id,
        "case_evaluation": summary,
        "detector_scores_used": False,
        "holo_used_only_in_evaluator": True,
    }


def _recall(records: list[Mapping[str, Any]], metric: str, k: int) -> float:
    if not records:
        return 0.0
    return round(
        sum(bool(record["case_evaluation"][f"top_k_{metric}_hits"][str(k)]) for record in records)
        / len(records),
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


def evaluate_pocketminer_ranking_policies(
    *,
    static_run_path: Path = DEFAULT_STATIC_RUN,
    labels_path: Path = DEFAULT_LABELS,
    output_path: Path = DEFAULT_OUTPUT,
    approve_evaluator: bool = False,
) -> dict[str, Any]:
    if not approve_evaluator:
        raise PocketMinerRankingPolicyError(
            "Opening private holo labels requires --approve-evaluator"
        )
    static_run = _read_json(static_run_path.resolve())
    labels = _read_json(labels_path.resolve())
    if (
        static_run.get("status") != "completed"
        or static_run.get("retention") != "full_final_pocket_list"
    ):
        raise PocketMinerRankingPolicyError("static run is not a completed full-list artifact")
    if (
        labels.get("status") != "completed_review_required"
        or labels.get("development_only") is not True
    ):
        raise PocketMinerRankingPolicyError("labels are not a completed development-only report")
    if labels.get("evaluator_only") is not True or labels.get("detector_started") is not False:
        raise PocketMinerRankingPolicyError("label boundary is unsafe")
    if labels.get("alignment_policy", {}).get("policy_version") != (
        "ground-truth-alignment-pocketminer-v2"
    ):
        raise PocketMinerRankingPolicyError("unexpected PocketMiner alignment policy")
    static_records = static_run.get("records")
    label_records = labels.get("records")
    if not isinstance(static_records, list) or not isinstance(label_records, Mapping):
        raise PocketMinerRankingPolicyError("static or label records are malformed")
    static_by_case = {str(record.get("case_id")): record for record in static_records}
    case_ids = sorted(label_records)
    if len(case_ids) != MAX_DEVELOPMENT_CASES or set(case_ids) != set(static_by_case):
        raise PocketMinerRankingPolicyError("development case sets are not identical")

    variants: dict[str, Any] = {}
    for policy_id in POLICY_IDS:
        records = [
            _policy_case(static_by_case[case_id], label_records[case_id], policy_id)
            for case_id in case_ids
        ]
        variants[policy_id] = {
            "policy_id": policy_id,
            "records": {record["case_id"]: record for record in records},
            "summary": {
                "case_count": len(records),
                "dcc_top_1": _recall(records, "dcc", 1),
                "dcc_top_3": _recall(records, "dcc", 3),
                "dcc_top_5": _recall(records, "dcc", 5),
                "dcc_top_10": _recall(records, "dcc", 10),
                "dca_top_1": _recall(records, "dca", 1),
                "dca_top_3": _recall(records, "dca", 3),
                "dca_top_5": _recall(records, "dca", 5),
                "dca_top_10": _recall(records, "dca", 10),
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
        "source": "pocketminer-novel-cryptic-pocket-set-v1",
        "static_run_sha256": _sha256_file(static_run_path.resolve()),
        "labels_report_sha256": _sha256_file(labels_path.resolve()),
        "protocol_sha256": phase6_frozen_protocol_v1().protocol_sha256,
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
    print(
        f"PocketMiner ranking policy selection: selected={selected_policy_id} "
        f"dev_dcc_top3={variants[selected_policy_id]['summary']['dcc_top_3']}"
    )
    print(f"selection report: {output_path}")
    print("validation/temporal/NMA/external baseline/ML: unopened")
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
        evaluate_pocketminer_ranking_policies(
            static_run_path=args.static_run,
            labels_path=args.labels,
            output_path=args.output,
            approve_evaluator=args.approve_evaluator,
        )
    except (PocketMinerRankingPolicyError, OSError, ValueError) as exc:
        print(f"PocketMiner ranking policy error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
