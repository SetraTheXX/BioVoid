"""Diagnose RI-3 final-pocket localization versus canonical ranking.

This is a read-only evaluator-side analysis. It consumes an already sealed
static run and evaluator report, verifies that every final pocket is retained,
and reports final-list localization separately from Top-k ranking recall. It
never downloads coordinates, runs the detector, changes a formula, or starts
motion/NMA/ML.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATIC_RUN = REPO_ROOT / "data/runtime/ri3/cryptobench-static-pilot-run-v1.json"
DEFAULT_EVALUATION = REPO_ROOT / "data/runtime/ri3/cryptobench-static-pilot-evaluation-v1.json"
DEFAULT_JSON_REPORT = REPO_ROOT / "local-private/research/ri3-detection-ranking-diagnostic-v1.json"
DEFAULT_MARKDOWN_REPORT = (
    REPO_ROOT / "local-private/research/ri3-detection-ranking-diagnostic-v1.md"
)
TOLERANCE_ANGSTROM = 4.0
TOP_KS = (1, 3, 5, 10)
FEATURE_KEYS = (
    "volume",
    "enclosure",
    "depth",
    "minimum_surface_clearance",
    "hydrophobic_ratio",
    "radius_clear",
    "radius_geom",
    "merged_vertices",
    "polar_atoms",
)


class DiagnosticError(ValueError):
    """Raised when the sealed RI-3 artifacts do not satisfy the diagnostic contract."""


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DiagnosticError(f"{label} must be an object")
    return value


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DiagnosticError(f"{label} must be an integer")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise DiagnosticError(f"Missing RI-3 artifact: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(_mapping(payload, str(path)))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_hit(distances: Sequence[Any], tolerance: float) -> int | None:
    for index, raw_distance in enumerate(distances, start=1):
        try:
            distance = float(raw_distance)
        except (TypeError, ValueError):
            continue
        if math.isfinite(distance) and distance <= tolerance:
            return index
    return None


def _rate(hits: int, total: int) -> dict[str, Any]:
    return {
        "hits": hits,
        "total": total,
        "rate": round(hits / total, 8) if total else None,
    }


def _feature_snapshot(pocket: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if pocket is None:
        return None
    raw = pocket.get("raw")
    source = raw if isinstance(raw, Mapping) else pocket
    return {key: source.get(key) for key in FEATURE_KEYS if key in source}


def _pocket_features(
    pockets: Sequence[Mapping[str, Any]], rank: int | None
) -> dict[str, Any] | None:
    if rank is None or rank < 1 or rank > len(pockets):
        return None
    return _feature_snapshot(pockets[rank - 1])


def _audit_static_records(
    static_run: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    records = _mapping(static_run.get("records"), "static_run.records")
    audited: dict[str, dict[str, Any]] = {}
    completed = 0
    all_final_stored = True
    raw_candidate_lists = 0
    for raw_structure_id, raw_record in records.items():
        structure_id = str(raw_structure_id).upper()
        record = _mapping(raw_record, f"static_run.records.{raw_structure_id}")
        status = str(record.get("status", ""))
        detector = _mapping(
            record.get("detector_record"),
            f"static_run.records.{raw_structure_id}.detector_record",
        )
        raw_pockets = detector.get("pockets", [])
        if not isinstance(raw_pockets, list):
            raise DiagnosticError(f"{structure_id}: detector_record.pockets must be a list")
        pocket_count = _integer(record.get("pocket_count", 0), f"{structure_id}.pocket_count")
        candidate_count = _integer(
            record.get("candidate_count", 0), f"{structure_id}.candidate_count"
        )
        stored_pockets = [
            _mapping(pocket, f"{structure_id}.detector_record.pockets[{index}]")
            for index, pocket in enumerate(raw_pockets)
        ]
        ranks = [
            _integer(pocket.get("rank"), f"{structure_id}.pocket.rank") for pocket in stored_pockets
        ]
        expected_ranks = list(range(1, len(stored_pockets) + 1))
        if status == "completed":
            completed += 1
            if len(stored_pockets) != pocket_count or ranks != expected_ranks:
                raise DiagnosticError(
                    f"{structure_id}: final pocket list is not fully retained or ranked"
                )
        final_stored = status == "completed" and len(stored_pockets) == pocket_count
        all_final_stored = all_final_stored and (final_stored or status != "completed")
        raw_available = isinstance(record.get("raw_candidates"), list) or isinstance(
            detector.get("candidate_voids"), list
        )
        if raw_available:
            raw_candidate_lists += 1
        audited[structure_id] = {
            "structure_id": structure_id,
            "status": status,
            "candidate_count": candidate_count,
            "pocket_count": pocket_count,
            "stored_pocket_count": len(stored_pockets),
            "all_final_pockets_stored": final_stored,
            "raw_voronoi_candidate_list_available": raw_available,
            "pockets": stored_pockets,
        }
    retention = {
        "structures_total": len(audited),
        "completed_structures": completed,
        "all_completed_final_pockets_stored": all_final_stored,
        "raw_voronoi_candidate_list_available": raw_candidate_lists == completed and completed > 0,
        "raw_voronoi_candidate_list_available_count": raw_candidate_lists,
        "candidate_count_semantics": "accepted_raw_voronoi_candidates_before_clustering_and_final_volume_acceptance",
        "pocket_count_semantics": "final_merged_pockets_returned_by_canonical_static_v1",
    }
    return audited, retention


def _taxonomy(
    dcc_rank: int | None,
    dca_rank: int | None,
    *,
    top_k: int = 5,
) -> str:
    if dcc_rank is None and dca_rank is None:
        return "C_final_detector_pipeline_miss"
    if (dcc_rank is None) != (dca_rank is None):
        return "B_metric_disagreement"
    if (dcc_rank <= top_k) != (dca_rank <= top_k):
        return "B_metric_disagreement"
    if dcc_rank > top_k or dca_rank > top_k:
        return "A_final_list_candidate_low_rank"
    return "localized_top5"


def _row_for_unavailable(
    case_id: str,
    raw_record: Mapping[str, Any],
    static_audit: Mapping[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    structure_id = str(raw_record.get("structure_id", "")).upper()
    static_status = static_audit.get(structure_id, {}).get("status") if static_audit else None
    taxonomy = (
        "D_resource_blocked"
        if static_status == "resource_blocked"
        else "E_evaluator_alignment_unavailable"
    )
    return {
        "case_id": case_id,
        "structure_id": structure_id,
        "evaluation_status": raw_record.get("status"),
        "detector_status": static_status,
        "taxonomy": taxonomy,
        "candidate_count": static_audit.get(structure_id, {}).get("candidate_count")
        if static_audit
        else None,
        "final_pocket_count": static_audit.get(structure_id, {}).get("pocket_count")
        if static_audit
        else None,
        "stored_final_pocket_count": static_audit.get(structure_id, {}).get("stored_pocket_count")
        if static_audit
        else None,
        "best_dcc_rank": None,
        "best_dca_rank": None,
        "best_dcc_angstrom": None,
        "best_dca_angstrom": None,
        "dcc_top_k_hits": {str(k): False for k in TOP_KS},
        "dca_top_k_hits": {str(k): False for k in TOP_KS},
        "top_rank_features": None,
        "best_dcc_features": None,
        "best_dca_features": None,
    }


def diagnose_artifacts(
    static_run: Mapping[str, Any],
    evaluation_report: Mapping[str, Any],
    *,
    tolerance: float = TOLERANCE_ANGSTROM,
) -> dict[str, Any]:
    """Return a deterministic detection-versus-ranking diagnostic report."""

    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be positive and finite")
    static_audit, retention = _audit_static_records(static_run)
    evaluation_records = _mapping(evaluation_report.get("records"), "evaluation.records")
    case_rows: list[dict[str, Any]] = []
    for raw_case_id, raw_record in evaluation_records.items():
        case_id = str(raw_case_id)
        record = _mapping(raw_record, f"evaluation.records.{case_id}")
        if record.get("status") != "completed_ground_truth":
            case_rows.append(_row_for_unavailable(case_id, record, static_audit))
            continue
        structure_id = str(record.get("structure_id", "")).upper()
        static = static_audit.get(structure_id)
        if static is None:
            raise DiagnosticError(f"{case_id}: structure is absent from static run")
        if static["status"] != "completed":
            raise DiagnosticError(f"{case_id}: aligned evaluator row has non-completed detector")
        evaluation = _mapping(record.get("case_evaluation"), f"{case_id}.case_evaluation")
        dcc = evaluation.get("dcc_by_rank")
        dca = evaluation.get("dca_by_rank")
        if not isinstance(dcc, list) or not isinstance(dca, list):
            raise DiagnosticError(f"{case_id}: DCC/DCA rank arrays are missing")
        expected_count = static["stored_pocket_count"]
        if len(dcc) != expected_count or len(dca) != expected_count:
            raise DiagnosticError(
                f"{case_id}: evaluator arrays do not match stored final pocket count"
            )
        dcc_rank = _first_hit(dcc, tolerance)
        dca_rank = _first_hit(dca, tolerance)
        pockets = static["pockets"]
        case_rows.append(
            {
                "case_id": case_id,
                "structure_id": structure_id,
                "evaluation_status": record.get("status"),
                "detector_status": static["status"],
                "taxonomy": _taxonomy(dcc_rank, dca_rank),
                "candidate_count": static["candidate_count"],
                "final_pocket_count": static["pocket_count"],
                "stored_final_pocket_count": static["stored_pocket_count"],
                "best_dcc_rank": dcc_rank,
                "best_dca_rank": dca_rank,
                "best_dcc_angstrom": dcc[dcc_rank - 1] if dcc_rank is not None else None,
                "best_dca_angstrom": dca[dca_rank - 1] if dca_rank is not None else None,
                "dcc_top_k_hits": {str(k): dcc_rank is not None and dcc_rank <= k for k in TOP_KS},
                "dca_top_k_hits": {str(k): dca_rank is not None and dca_rank <= k for k in TOP_KS},
                "top_rank_features": _pocket_features(pockets, 1),
                "best_dcc_features": _pocket_features(pockets, dcc_rank),
                "best_dca_features": _pocket_features(pockets, dca_rank),
            }
        )
    case_rows.sort(key=lambda row: (row["structure_id"], row["case_id"]))
    eligible = [row for row in case_rows if row["evaluation_status"] == "completed_ground_truth"]
    dcc_any = sum(row["best_dcc_rank"] is not None for row in eligible)
    dca_any = sum(row["best_dca_rank"] is not None for row in eligible)
    any_metric = sum(
        row["best_dcc_rank"] is not None or row["best_dca_rank"] is not None for row in eligible
    )
    joint_any = sum(
        row["best_dcc_rank"] is not None and row["best_dca_rank"] is not None for row in eligible
    )
    joint_top5 = sum(
        row["best_dcc_rank"] is not None
        and row["best_dcc_rank"] <= 5
        and row["best_dca_rank"] is not None
        and row["best_dca_rank"] <= 5
        for row in eligible
    )
    ranking_recall = {
        metric: {
            str(k): _rate(
                sum(
                    row[f"best_{metric}_rank"] is not None and row[f"best_{metric}_rank"] <= k
                    for row in eligible
                ),
                len(eligible),
            )
            for k in TOP_KS
        }
        for metric in ("dcc", "dca")
    }
    taxonomy_counts = Counter(row["taxonomy"] for row in case_rows)
    summary = {
        "eligible_aligned_rows": len(eligible),
        "case_rows_total": len(case_rows),
        "final_pocket_list_ceiling": {
            "dcc_any": _rate(dcc_any, len(eligible)),
            "dca_any": _rate(dca_any, len(eligible)),
            "any_metric_union": _rate(any_metric, len(eligible)),
            "joint_dcc_and_dca_any": _rate(joint_any, len(eligible)),
        },
        "canonical_ranking_recall": ranking_recall,
        "taxonomy_counts": dict(sorted(taxonomy_counts.items())),
        "decision_signal": {
            "final_list_any_metric_rows": any_metric,
            "final_list_joint_rows": joint_any,
            "joint_top5_rows": joint_top5,
            "signal": (
                "ranking_dominant_descriptive"
                if any_metric == len(eligible) and joint_top5 < any_metric
                else "detector_pipeline_or_mixed_descriptive"
            ),
            "next_action": "design_new_development_ranking_study_without_selecting_from_this_pilot",
        },
        "diagnostic_only": True,
        "scientific_superiority_claim_authorized": False,
        "discovery_claim_authorized": False,
    }
    return {
        "schema_version": "biovoid-ri3-detection-ranking-diagnostic-v1",
        "status": "diagnostic_only_not_for_claim",
        "tolerance_angstrom": tolerance,
        "top_k_values": list(TOP_KS),
        "static_run_sha256": static_run.get("run_sha256"),
        "evaluation_report_sha256": evaluation_report.get("report_sha256"),
        "retention_audit": retention,
        "case_rows": case_rows,
        "summary": summary,
        "decision_boundary": {
            "ranking_policy_selection_from_this_pilot": False,
            "raw_detector_stage_attribution_available": False,
            "second_family_source_gate_reopened": False,
            "next_step": "review_final_pocket_ceiling_and_canonical_ranking_recall",
        },
    }


def diagnose_files(
    static_run_path: Path = DEFAULT_STATIC_RUN,
    evaluation_path: Path = DEFAULT_EVALUATION,
) -> dict[str, Any]:
    """Read the two sealed local artifacts and return the diagnostic report."""

    return diagnose_artifacts(_read_json(static_run_path), _read_json(evaluation_path))


def _write_json(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _write_markdown(path: Path, report: Mapping[str, Any]) -> None:
    summary = _mapping(report["summary"], "report.summary")
    ceiling = _mapping(summary["final_pocket_list_ceiling"], "summary.ceiling")
    recall = _mapping(summary["canonical_ranking_recall"], "summary.recall")
    lines = [
        "# RI-3 detection-vs-ranking diagnostic v1",
        "",
        "Status: **diagnostic only; no ranking, detector, or threshold changed.**",
        "",
        "This report is generated from sealed local RI-3 artifacts. It does not",
        "authorize validation, superiority, discovery, NMA, ML, or a new family",
        "screen.",
        "",
        "## Retention audit",
        "",
        f"- Completed structures: {report['retention_audit']['completed_structures']}/{report['retention_audit']['structures_total']}",
        f"- All final pockets stored: `{report['retention_audit']['all_completed_final_pockets_stored']}`",
        "- Raw Voronoi candidate list retained: `False`",
        "- `candidate_count`: accepted raw Voronoi candidates before clustering/final volume acceptance",
        "- `pocket_count`: final merged pockets returned by `canonical-static-v1`",
        "",
        "## Aggregate result",
        "",
        f"- Eligible aligned rows: {summary['eligible_aligned_rows']}/{summary['case_rows_total']}",
        f"- Final-list DCC any-rank: {_fmt(ceiling['dcc_any']['rate'])}",
        f"- Final-list DCA any-rank: {_fmt(ceiling['dca_any']['rate'])}",
        f"- Final-list any-metric union: {_fmt(ceiling['any_metric_union']['rate'])}",
        f"- Final-list joint DCC+DCA any-rank: {_fmt(ceiling['joint_dcc_and_dca_any']['rate'])}",
        f"- Descriptive branch signal: `{summary['decision_signal']['signal']}`",
        "",
        "| Metric | Top-1 | Top-3 | Top-5 | Top-10 |",
        "|---|---:|---:|---:|---:|",
    ]
    for metric in ("dcc", "dca"):
        values = " | ".join(
            _fmt(_mapping(recall[metric][str(k)], "recall")["rate"]) for k in TOP_KS
        )
        lines.append(f"| {metric.upper()} | {values} |")
    lines.extend(
        [
            "",
            "## Case-level result",
            "",
            "| Structure | Case status | Final pockets | Best DCC rank | Best DCA rank | Taxonomy |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for row in report["case_rows"]:
        lines.append(
            f"| {row['structure_id']} | {row['evaluation_status']} | "
            f"{_fmt(row['final_pocket_count'])} | {_fmt(row['best_dcc_rank'])} | "
            f"{_fmt(row['best_dca_rank'])} | {row['taxonomy']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The final pocket list can be analyzed for ranking because all final",
            "pockets are stored. A missing final-list pocket is a detector-pipeline",
            "miss, not proof of a raw Voronoi-generation miss; raw intermediates",
            "were not retained. No formula was fitted to this report.",
            "",
            "This small report shows a descriptive branch signal only. If the",
            "signal is ranking-dominant, design a new development ranking study",
            "without selecting a policy from this evaluator-exposed pilot. The",
            "second-family source gate remains closed.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--evaluation", type=Path, default=DEFAULT_EVALUATION)
    parser.add_argument("--json-report", type=Path, default=DEFAULT_JSON_REPORT)
    parser.add_argument("--markdown-report", type=Path, default=DEFAULT_MARKDOWN_REPORT)
    args = parser.parse_args()
    report = diagnose_files(args.static_run, args.evaluation)
    report["source_files"] = {
        "static_run": str(args.static_run),
        "static_run_file_sha256": _sha256_file(args.static_run),
        "evaluation": str(args.evaluation),
        "evaluation_file_sha256": _sha256_file(args.evaluation),
    }
    _write_json(args.json_report, report)
    _write_markdown(args.markdown_report, report)
    summary = report["summary"]
    print(
        "RI-3 detection-vs-ranking diagnostic: "
        f"eligible={summary['eligible_aligned_rows']} "
        f"cases={summary['case_rows_total']} "
        f"taxonomy={summary['taxonomy_counts']}"
    )
    print(f"JSON report: {args.json_report}")
    print(f"Markdown report: {args.markdown_report}")
    print("scientific claim authorization: closed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DiagnosticError, OSError, json.JSONDecodeError) as exc:
        print(f"RI-3 diagnostic error: {exc}")
        raise SystemExit(2) from exc
