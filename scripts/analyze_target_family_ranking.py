"""Analyze a frozen target-family ranking without rerunning the detector.

This command is deliberately an offline, evaluator-only diagnostic.  It reads
the already materialized target-blind static run, the separate DCC/DCA report,
and the private cohort split metadata.  It does not open coordinates, download
structures, start the detector, train ML, or modify the canonical artifact.

The shadow policy is fixed in this module before the outcome metrics are
computed:

    0.70 * within-case volume percentile + 0.30 * within-case enclosure

``depth`` is intentionally excluded because canonical-static-v1 derives it
from ``enclosure * enclosure_ray_length``.  The result is exploratory and
top-10-censored; it is not a benchmark claim or a replacement ranking.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_STATIC_RUN = (
    REPO_ROOT / "data/runtime/target-family/static-pilot-pfam-v1-rerun-v2/"
    "target-family-static-pilot-run-v1.json"
)
DEFAULT_EVALUATION_REPORT = (
    REPO_ROOT / "data/runtime/target-family/static-evaluation-pfam-v1-rerun-v2/"
    "target-family-static-evaluation-pfam-v1.json"
)
DEFAULT_COHORT = REPO_ROOT / "local-private/research/target-family/cohort-pfam-v1.json"
DEFAULT_OUTPUT = (
    REPO_ROOT / "data/runtime/target-family/ranking-shadow-v1/target-family-ranking-shadow-v1.json"
)
DEFAULT_MARKDOWN_OUTPUT = (
    REPO_ROOT / "research-local/audits/TARGET_FAMILY_RANKING_SHADOW_ANALYSIS_2026-08-22.md"
)

SCHEMA_VERSION = "target-family-ranking-shadow-v1"
SHADOW_POLICY_VERSION = "volume-enclosure-shadow-v1"
SHADOW_WEIGHTS = {"volume": 0.70, "enclosure": 0.30}
TOP_KS = (1, 3, 5)
DCC_DCA_TOLERANCE_ANGSTROM = 4.0
DEPTH_RELATION_TOLERANCE = 1e-5


class RankingAnalysisError(RuntimeError):
    """Raised when the frozen analysis inputs do not satisfy their contracts."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RankingAnalysisError(f"cannot read JSON input: {path}") from exc
    if not isinstance(payload, dict):
        raise RankingAnalysisError(f"JSON input must be an object: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _number(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise RankingAnalysisError(f"{label} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RankingAnalysisError(f"{label} must be numeric") from exc
    if number != number or number in (float("inf"), float("-inf")):
        raise RankingAnalysisError(f"{label} must be finite")
    return number


def _minmax(values: Sequence[float]) -> list[float]:
    if not values:
        raise RankingAnalysisError("cannot normalize an empty feature vector")
    lower = min(values)
    upper = max(values)
    if upper == lower:
        return [0.0 for _ in values]
    span = upper - lower
    return [(value - lower) / span for value in values]


def _validate_canonical_volume_order(pockets: Sequence[Mapping[str, Any]]) -> None:
    volumes = [_number(pocket.get("volume"), label="pocket.volume") for pocket in pockets]
    if any(left + 1e-8 < right for left, right in zip(volumes, volumes[1:])):
        raise RankingAnalysisError("static run top_pockets are not volume-descending")


def _shadow_order(pockets: Sequence[Mapping[str, Any]]) -> tuple[list[int], list[float]]:
    volumes = [_number(pocket.get("volume"), label="pocket.volume") for pocket in pockets]
    enclosures = [_number(pocket.get("enclosure"), label="pocket.enclosure") for pocket in pockets]
    volume_norm = _minmax(volumes)
    enclosure_norm = _minmax(enclosures)
    scores = [
        SHADOW_WEIGHTS["volume"] * volume_score + SHADOW_WEIGHTS["enclosure"] * enclosure_score
        for volume_score, enclosure_score in zip(volume_norm, enclosure_norm)
    ]
    order = sorted(
        range(len(pockets)),
        key=lambda index: (
            -scores[index],
            -volumes[index],
            -enclosures[index],
            str(pockets[index].get("pocket_id", "")),
        ),
    )
    return order, scores


def _depth_audit(pockets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    errors = []
    for pocket in pockets:
        depth = _number(pocket.get("depth"), label="pocket.depth")
        enclosure = _number(pocket.get("enclosure"), label="pocket.enclosure")
        ray_length = _number(
            pocket.get("enclosure_ray_length"), label="pocket.enclosure_ray_length"
        )
        errors.append(abs(depth - enclosure * ray_length))
    maximum = max(errors, default=0.0)
    return {
        "checked": len(pockets),
        "max_abs_error": round(maximum, 10),
        "within_tolerance": maximum <= DEPTH_RELATION_TOLERANCE,
        "relation": "depth = enclosure * enclosure_ray_length",
        "used_as_independent_feature": False,
    }


def _rank_metrics(
    distances: Sequence[Any],
    order: Sequence[int],
) -> dict[str, Any]:
    values = [_number(value, label="evaluator distance") for value in distances]
    if len(values) != len(order):
        raise RankingAnalysisError("evaluator distance length does not match stored pockets")
    hits = {}
    for top_k in TOP_KS:
        hits[str(top_k)] = any(
            values[index] <= DCC_DCA_TOLERANCE_ANGSTROM for index in order[:top_k]
        )
    best_rank = next(
        (
            rank
            for rank, index in enumerate(order, start=1)
            if values[index] <= DCC_DCA_TOLERANCE_ANGSTROM
        ),
        None,
    )
    return {"best_rank": best_rank, "top_k_hits": hits}


def _metric_summary(case_results: Sequence[Mapping[str, Any]], ranking: str) -> dict[str, Any]:
    result: dict[str, Any] = {"case_count": len(case_results)}
    for metric in ("dcc", "dca"):
        top_k = {}
        for top in TOP_KS:
            hit_count = sum(
                bool(case[ranking][metric]["top_k_hits"][str(top)]) for case in case_results
            )
            top_k[str(top)] = {
                "hit_count": hit_count,
                "rate": round(hit_count / len(case_results), 8) if case_results else None,
            }
        result[metric] = {"top_k": top_k}
    return result


def _comparison_summary(case_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    comparison: dict[str, Any] = {}
    for metric in ("dcc", "dca"):
        metric_result = {}
        for top in TOP_KS:
            key = str(top)
            rescued = sum(
                not case["canonical"][metric]["top_k_hits"][key]
                and case["shadow"][metric]["top_k_hits"][key]
                for case in case_results
            )
            regressed = sum(
                case["canonical"][metric]["top_k_hits"][key]
                and not case["shadow"][metric]["top_k_hits"][key]
                for case in case_results
            )
            metric_result[key] = {"rescued": rescued, "regressed": regressed}
        comparison[metric] = {"top_k": metric_result}
    return comparison


def _case_split_map(cohort: Mapping[str, Any]) -> dict[str, str]:
    cases = cohort.get("cases")
    if not isinstance(cases, list):
        raise RankingAnalysisError("cohort cases must be a list")
    result = {}
    for case in cases:
        if not isinstance(case, dict):
            raise RankingAnalysisError("cohort case must be an object")
        case_id = case.get("case_id")
        split = case.get("split")
        if not isinstance(case_id, str) or not isinstance(split, str):
            raise RankingAnalysisError("cohort case_id and split are required")
        result[case_id] = split
    return result


def _analyze_case(
    case_id: str,
    static_record: Mapping[str, Any],
    evaluation_record: Mapping[str, Any],
    split: str,
) -> dict[str, Any]:
    pockets = static_record.get("top_pockets")
    if not isinstance(pockets, list) or not pockets:
        raise RankingAnalysisError(f"{case_id}: static top_pockets is empty or invalid")
    if not all(isinstance(pocket, dict) for pocket in pockets):
        raise RankingAnalysisError(f"{case_id}: pocket entries must be objects")
    _validate_canonical_volume_order(pockets)

    case_evaluation = evaluation_record.get("case_evaluation")
    if not isinstance(case_evaluation, dict):
        raise RankingAnalysisError(f"{case_id}: evaluator case_evaluation is unavailable")
    if case_evaluation.get("status") != "completed":
        raise RankingAnalysisError(f"{case_id}: evaluator case is not completed")
    if case_evaluation.get("score_used") is not False:
        raise RankingAnalysisError(f"{case_id}: evaluator score_used must remain false")

    dcc = case_evaluation.get("dcc_by_rank")
    dca = case_evaluation.get("dca_by_rank")
    if not isinstance(dcc, list) or not isinstance(dca, list):
        raise RankingAnalysisError(f"{case_id}: evaluator distances are missing")
    if len(dcc) != len(pockets) or len(dca) != len(pockets):
        raise RankingAnalysisError(
            f"{case_id}: evaluator distance arrays must match stored top_pockets"
        )

    shadow_order, shadow_scores = _shadow_order(pockets)
    canonical_order = list(range(len(pockets)))
    alignment = evaluation_record.get("alignment")
    if not isinstance(alignment, dict):
        raise RankingAnalysisError(f"{case_id}: alignment metadata is missing")

    return {
        "case_id": case_id,
        "structure_id": static_record.get("structure_id"),
        "split": split,
        "alignment": {
            "status": alignment.get("status"),
            "fit_rmsd_angstrom": alignment.get("fit_rmsd_angstrom"),
            "warning_count": len(alignment.get("warnings", [])),
        },
        "stored_pocket_count": len(pockets),
        "full_pocket_count": static_record.get("pocket_count"),
        "tail_censored": static_record.get("pocket_count") != len(pockets),
        "depth_audit": _depth_audit(pockets),
        "canonical": {
            "order_pocket_ids": [pockets[index].get("pocket_id") for index in canonical_order],
            "dcc": _rank_metrics(dcc, canonical_order),
            "dca": _rank_metrics(dca, canonical_order),
        },
        "shadow": {
            "order_pocket_ids": [pockets[index].get("pocket_id") for index in shadow_order],
            "order_original_ranks": [index + 1 for index in shadow_order],
            "scores": {
                str(pockets[index].get("pocket_id")): round(shadow_scores[index], 8)
                for index in range(len(pockets))
            },
            "dcc": _rank_metrics(dcc, shadow_order),
            "dca": _rank_metrics(dca, shadow_order),
        },
    }


def analyze_target_family_ranking(
    *,
    static_run_path: Path = DEFAULT_STATIC_RUN,
    evaluation_report_path: Path = DEFAULT_EVALUATION_REPORT,
    cohort_path: Path = DEFAULT_COHORT,
    output_path: Path = DEFAULT_OUTPUT,
    markdown_output_path: Path = DEFAULT_MARKDOWN_OUTPUT,
) -> dict[str, Any]:
    """Create an offline shadow-ranking report from frozen local artifacts."""

    static_run = _read_json(static_run_path.resolve())
    evaluation_report = _read_json(evaluation_report_path.resolve())
    cohort = _read_json(cohort_path.resolve())
    split_map = _case_split_map(cohort)

    if static_run.get("detector", {}).get("version") != "canonical-static-v1":
        raise RankingAnalysisError("static run is not canonical-static-v1")
    if evaluation_report.get("detector_target_blind") is not True:
        raise RankingAnalysisError("evaluator report is not target-blind")
    if evaluation_report.get("evaluator_only") is not True:
        raise RankingAnalysisError("evaluator report is not evaluator-only")

    static_cases = static_run.get("cases")
    evaluation_records = evaluation_report.get("records")
    if not isinstance(static_cases, dict) or not isinstance(evaluation_records, dict):
        raise RankingAnalysisError("static cases and evaluator records must be objects")

    case_results = []
    for case_id, static_record in static_cases.items():
        if not isinstance(static_record, dict):
            raise RankingAnalysisError(f"{case_id}: static case must be an object")
        evaluation_record = evaluation_records.get(case_id)
        if not isinstance(evaluation_record, dict):
            raise RankingAnalysisError(f"{case_id}: missing evaluator record")
        split = split_map.get(case_id)
        if split is None:
            raise RankingAnalysisError(f"{case_id}: missing cohort split")
        case_results.append(_analyze_case(case_id, static_record, evaluation_record, split))

    split_names = sorted({case["split"] for case in case_results})
    by_split = {
        split: {
            "canonical": _metric_summary(
                [case for case in case_results if case["split"] == split], "canonical"
            ),
            "shadow": _metric_summary(
                [case for case in case_results if case["split"] == split], "shadow"
            ),
            "comparison": _comparison_summary(
                [case for case in case_results if case["split"] == split]
            ),
        }
        for split in split_names
    }
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": static_run.get("family_id"),
        "claim_boundary": "exploratory_shadow_ranking_only",
        "interpretation_status": "diagnostic_pending_independent_review",
        "canonical_artifact_modified": False,
        "detector_rerun_started": False,
        "ml_training_started": False,
        "motion_enabled": False,
        "input_hashes": {
            "static_run_sha256": _sha256_file(static_run_path.resolve()),
            "evaluation_report_sha256": _sha256_file(evaluation_report_path.resolve()),
            "cohort_sha256": _sha256_file(cohort_path.resolve()),
        },
        "scope": {
            "case_count": len(case_results),
            "stored_candidates_per_case": 10,
            "candidate_scope": "stored_top10_only",
            "tail_censored_case_count": sum(case["tail_censored"] for case in case_results),
            "tail_censored_cases": [
                case["structure_id"] for case in case_results if case["tail_censored"]
            ],
            "dcc_dca_tolerance_angstrom": DCC_DCA_TOLERANCE_ANGSTROM,
            "top_k": list(TOP_KS),
        },
        "shadow_policy": {
            "policy_version": SHADOW_POLICY_VERSION,
            "formula": "0.70 * within_case_volume_minmax + 0.30 * within_case_enclosure_minmax",
            "weights": SHADOW_WEIGHTS,
            "tie_break": ["volume_descending", "enclosure_descending", "pocket_id_ascending"],
            "depth_included": False,
            "selection_rule": "fixed_before_outcome_metrics; no label-based tuning",
        },
        "aggregate": {
            "canonical": _metric_summary(case_results, "canonical"),
            "shadow": _metric_summary(case_results, "shadow"),
            "comparison": _comparison_summary(case_results),
        },
        "by_split": by_split,
        "cases": case_results,
        "limitations": [
            "The static artifact stores only the first ten volume-ranked pockets.",
            "The shadow result cannot rescue a true pocket outside the stored top ten.",
            "The cohort has two cases per split; rates are descriptive, not inferential.",
            "This analysis was run after the pilot and is exploratory, not confirmatory.",
            "No superiority, validated prediction, or discovery claim is authorized.",
        ],
    }
    _write_json(output_path.resolve(), report)
    markdown_output_path.resolve().parent.mkdir(parents=True, exist_ok=True)
    markdown_output_path.resolve().write_text(_render_markdown(report), encoding="utf-8")
    return report


def _render_markdown(report: Mapping[str, Any]) -> str:
    aggregate = report["aggregate"]
    lines = [
        "# PF00497 shadow-ranking analysis — 22 August 2026",
        "",
        "This is an ignored, offline, exploratory diagnostic. The canonical static",
        "artifact and its volume ranking were not modified; no detector, ML, NMA,",
        "network, or coordinate read was started by this analysis.",
        "",
        "## Fixed policy",
        "",
        "`0.70 * within-case volume_minmax + 0.30 * within-case enclosure_minmax`",
        "",
        "Depth is excluded because canonical-static-v1 deterministically derives it",
        "from enclosure and the frozen ray length. The analysis is limited to the",
        "stored top ten candidates, so full-pocket tail misses remain censored.",
        "",
        "## Aggregate outcome",
        "",
        "| Ranking | DCC Top-1 | DCC Top-3 | DCC Top-5 | DCA Top-1 | DCA Top-3 | DCA Top-5 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for ranking in ("canonical", "shadow"):
        summary = aggregate[ranking]
        values = [
            summary[metric]["top_k"][str(top)]["rate"]
            for metric in ("dcc", "dca")
            for top in TOP_KS
        ]
        rendered = ["n/a" if value is None else f"{value:.3f}" for value in values]
        lines.append(f"| {ranking} | " + " | ".join(rendered) + " |")
    lines.extend(
        [
            "",
            "## Shadow versus canonical changes",
            "",
            "Rescued/regressed counts are descriptive changes inside the stored top ten.",
            "",
        ]
    )
    comparison = aggregate["comparison"]
    lines.append("| Metric | Top-1 | Top-3 | Top-5 |")
    lines.append("|---|---:|---:|---:|")
    for metric in ("dcc", "dca"):
        cells = []
        for top in TOP_KS:
            item = comparison[metric]["top_k"][str(top)]
            cells.append(f"+{item['rescued']} / -{item['regressed']}")
        lines.append(f"| {metric.upper()} | " + " | ".join(cells) + " |")
    lines.extend(
        [
            "",
            "## Decision boundary",
            "",
            "This result does not authorize a canonical ranking change, ML training,",
            "NMA, docking, a broader benchmark, or a discovery claim. A future ranking",
            "change requires a fresh held-out run with the formula versioned before",
            "the evaluator is opened.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--evaluation-report", type=Path, default=DEFAULT_EVALUATION_REPORT)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        report = analyze_target_family_ranking(
            static_run_path=args.static_run,
            evaluation_report_path=args.evaluation_report,
            cohort_path=args.cohort,
            output_path=args.output,
            markdown_output_path=args.markdown_output,
        )
    except RankingAnalysisError as exc:
        print(f"target-family ranking analysis error: {exc}", file=sys.stderr)
        return 2
    print(
        "target-family ranking shadow analysis: "
        f"cases={report['scope']['case_count']} "
        f"tail_censored={report['scope']['tail_censored_case_count']}"
    )
    print(f"JSON report: {args.output}")
    print(f"Markdown audit: {args.markdown_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
