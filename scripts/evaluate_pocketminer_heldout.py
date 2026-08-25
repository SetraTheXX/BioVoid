"""Evaluate the locked PocketMiner shadow policy on held-out rows once.

The development selection report must already name A-canonical-volume-v1.
This command opens only the four pre-sealed validation and temporal/test label
rows, applies that policy without retuning, and writes a diagnostic report.
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
from scripts.evaluate_pocketminer_ranking_policies import (  # noqa: E402
    POLICY_IDS,
    _rank_pockets,
)
from src.benchmark_v1 import evaluate_case, phase6_frozen_protocol_v1  # noqa: E402
from src.evaluator_format import adapt_biovoid_pockets  # noqa: E402


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
DEFAULT_OUTPUT = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/heldout-evaluation-v1/"
    "pocketminer-heldout-evaluation-v1.json"
)
HELDOUT_SPLITS = frozenset({"validation", "test"})
EXPECTED_CASES = 4
LOCKED_POLICY_ID = POLICY_IDS[0]


class PocketMinerHeldoutEvaluationError(RuntimeError):
    """Raised when the held-out evaluation boundary is invalid."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PocketMinerHeldoutEvaluationError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PocketMinerHeldoutEvaluationError(f"JSON root must be an object: {path}")
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


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _case_evaluation(
    static_case: Mapping[str, Any], label_record: Mapping[str, Any], protocol: Any
) -> dict[str, Any]:
    case_id = str(static_case.get("case_id"))
    structure_id = str(static_case.get("structure_id", "")).upper()
    pockets = static_case.get("final_pockets")
    if static_case.get("status") != "completed" or not isinstance(pockets, list):
        raise PocketMinerHeldoutEvaluationError(f"held-out static case is unavailable: {case_id}")
    if label_record.get("status") != "completed_ground_truth":
        raise PocketMinerHeldoutEvaluationError(f"held-out label case is unavailable: {case_id}")
    ranked = _rank_pockets(pockets, LOCKED_POLICY_ID)
    detector = adapt_biovoid_pockets(
        structure_id,
        ranked,
        provenance={
            "source": "pocketminer-heldout-static-v1",
            "target_blind": True,
            "shadow_policy_id": LOCKED_POLICY_ID,
            "selection_locked": True,
        },
    )
    truth = _ground_truth(label_record["ground_truth"])
    if truth.case_id != case_id or truth.structure_id != structure_id:
        raise PocketMinerHeldoutEvaluationError(f"static/label identity mismatch: {case_id}")
    evaluation = evaluate_case(detector, truth, protocol)
    dcc = tuple(evaluation.dcc_by_rank)
    dca = tuple(evaluation.dca_by_rank)
    dcc_tolerance = float(protocol.dcc_tolerance_angstrom)
    dca_tolerance = float(protocol.dca_tolerance_angstrom)
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
    result["top_k_dcc_hits"] = {str(key): value for key, value in evaluation.top_k_dcc_hits.items()}
    result["top_k_dca_hits"] = {str(key): value for key, value in evaluation.top_k_dca_hits.items()}
    result["top_k_dcc_hits"]["10"] = any(value <= dcc_tolerance for value in dcc[:10])
    result["top_k_dca_hits"]["10"] = any(value <= dca_tolerance for value in dca[:10])
    result["top_k_joint_hits"] = {
        str(k): any(
            dcc_value <= dcc_tolerance and dca_value <= dca_tolerance
            for dcc_value, dca_value in zip(dcc[:k], dca[:k], strict=True)
        )
        for k in (1, 3, 5, 10)
    }
    result["best_joint_rank"] = joint_rank
    return {
        "case_id": case_id,
        "structure_id": structure_id,
        "split": static_case.get("split"),
        "status": "completed_heldout_diagnostic",
        "candidate_count": len(pockets),
        "case_evaluation": result,
        "detector_scores_used": False,
        "locked_policy_id": LOCKED_POLICY_ID,
    }


def _recall(records: list[Mapping[str, Any]], key: str, k: int) -> float:
    return round(
        sum(bool(record["case_evaluation"][key][str(k)]) for record in records) / len(records),
        8,
    )


def evaluate_pocketminer_heldout(
    *,
    static_run_path: Path = DEFAULT_STATIC_RUN,
    labels_path: Path = DEFAULT_LABELS,
    selection_path: Path = DEFAULT_SELECTION,
    output_path: Path = DEFAULT_OUTPUT,
    approve_evaluator: bool = False,
) -> dict[str, Any]:
    if not approve_evaluator:
        raise PocketMinerHeldoutEvaluationError(
            "Opening held-out holo labels requires --approve-evaluator"
        )
    static_run = _read_json(static_run_path.resolve())
    labels = _read_json(labels_path.resolve())
    selection = _read_json(selection_path.resolve())
    if (
        static_run.get("status") != "completed"
        or static_run.get("retention") != "full_final_pocket_list"
    ):
        raise PocketMinerHeldoutEvaluationError("held-out static run is not complete/full-list")
    if static_run.get("boundary", {}).get("target_blind") is not True:
        raise PocketMinerHeldoutEvaluationError("held-out static boundary is unsafe")
    if (
        labels.get("status") != "completed_review_required"
        or labels.get("heldout_only") is not True
    ):
        raise PocketMinerHeldoutEvaluationError("held-out labels are not complete")
    if labels.get("counts") != {"completed": EXPECTED_CASES, "failed": 0}:
        raise PocketMinerHeldoutEvaluationError("held-out labels have incomplete counts")
    if labels.get("evaluator_only") is not True or labels.get("detector_started") is not False:
        raise PocketMinerHeldoutEvaluationError("held-out label boundary is unsafe")
    if labels.get("alignment_policy", {}).get("policy_version") != (
        "ground-truth-alignment-pocketminer-v2"
    ):
        raise PocketMinerHeldoutEvaluationError("unexpected held-out alignment policy")
    if selection.get("selected_policy_id") != LOCKED_POLICY_ID:
        raise PocketMinerHeldoutEvaluationError("development policy selection is not locked to A")
    if selection.get("boundary", {}).get("validation_labels_opened") is not False:
        raise PocketMinerHeldoutEvaluationError("selection report already opened validation labels")

    static_records = static_run.get("records")
    label_records = labels.get("records")
    if not isinstance(static_records, list) or not isinstance(label_records, Mapping):
        raise PocketMinerHeldoutEvaluationError("held-out records are malformed")
    static_by_case = {str(record.get("case_id")): record for record in static_records}
    case_ids = sorted(label_records)
    if len(case_ids) != EXPECTED_CASES or set(case_ids) != set(static_by_case):
        raise PocketMinerHeldoutEvaluationError("held-out static/label case sets differ")
    if {str(static_by_case[case_id].get("split")) for case_id in case_ids} != HELDOUT_SPLITS:
        raise PocketMinerHeldoutEvaluationError("validation and temporal/test rows are incomplete")

    protocol = phase6_frozen_protocol_v1()
    records = [
        _case_evaluation(static_by_case[case_id], label_records[case_id], protocol)
        for case_id in case_ids
    ]
    report: dict[str, Any] = {
        "schema_version": "biovoid-pocketminer-heldout-evaluation-v1",
        "status": "completed_heldout_diagnostic_only",
        "source": "pocketminer-novel-cryptic-pocket-set-v1",
        "locked_policy_id": LOCKED_POLICY_ID,
        "selection_report_sha256": _sha256_file(selection_path.resolve()),
        "static_run_sha256": _sha256_file(static_run_path.resolve()),
        "labels_report_sha256": _sha256_file(labels_path.resolve()),
        "protocol_sha256": protocol.protocol_sha256,
        "candidate_scope": "full_final_pocket_list",
        "records": {record["case_id"]: record for record in records},
        "summary": {
            "case_count": len(records),
            "validation_count": sum(record["split"] == "validation" for record in records),
            "temporal_test_count": sum(record["split"] == "test" for record in records),
            "top_k_dcc_recall": {
                str(k): _recall(records, "top_k_dcc_hits", k) for k in (1, 3, 5, 10)
            },
            "top_k_dca_recall": {
                str(k): _recall(records, "top_k_dca_hits", k) for k in (1, 3, 5, 10)
            },
            "top_k_joint_recall": {
                str(k): _recall(records, "top_k_joint_hits", k) for k in (1, 3, 5, 10)
            },
            "joint_candidate_universe_recall": round(
                sum(record["case_evaluation"]["best_joint_rank"] is not None for record in records)
                / len(records),
                8,
            ),
        },
        "boundary": {
            "heldout_only": True,
            "development_policy_selection_reused": True,
            "retuning_performed": False,
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
        f"PocketMiner held-out evaluation: cases={len(records)} "
        f"locked_policy={LOCKED_POLICY_ID} "
        f"joint_top5={report['summary']['top_k_joint_recall']['5']}"
    )
    print(f"held-out evaluation report: {output_path}")
    print("retuning/NMA/external baseline/ML: no")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--approve-evaluator", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        evaluate_pocketminer_heldout(
            static_run_path=args.static_run,
            labels_path=args.labels,
            selection_path=args.selection,
            output_path=args.output,
            approve_evaluator=args.approve_evaluator,
        )
    except (PocketMinerHeldoutEvaluationError, OSError, ValueError) as exc:
        print(f"PocketMiner held-out evaluation error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
