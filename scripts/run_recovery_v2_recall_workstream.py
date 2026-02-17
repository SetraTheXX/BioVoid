#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

import sys

sys.path.insert(0, str(ROOT))

from validate_known_pockets import (  # noqa: E402
    check_pocket_match,
    load_test_set,
    run_pipeline_for_protein,
)


CANONICAL_TOLERANCE = 8.0
CANONICAL_TOP_N = 20
CANONICAL_DRUGGABLE_ONLY = True
CONSENSUS_MIN_FRAMES = 3
CENTER_STABILITY_MAX = 2.0
VOLUME_CV_MAX = 0.20


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _to_serializable(obj: Any) -> Any:
    if hasattr(obj, "tolist"):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_serializable(v) for v in obj]
    if isinstance(obj, tuple):
        return [_to_serializable(v) for v in obj]
    return obj


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_to_serializable(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _normalize_minmax(values: list[float], neutral: float = 0.5) -> list[float]:
    if not values:
        return []
    vmin = min(values)
    vmax = max(values)
    if abs(vmax - vmin) < 1e-12:
        return [neutral for _ in values]
    return [(v - vmin) / (vmax - vmin) for v in values]


def _druggability_norm(pocket: dict[str, Any]) -> float:
    cls = str(pocket.get("druggability_class", "")).lower()
    if cls == "high":
        return 1.0
    if cls == "medium":
        return 0.6
    if cls == "low":
        return 0.3
    return 1.0 if bool(pocket.get("druggable", False)) else 0.0


def _prepare_refined_rank(pockets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not pockets:
        return []

    bio_scores = [float(p.get("bio_score", 0.0) or 0.0) for p in pockets]
    supports = [
        float(
            p.get("consensus_support_frames")
            if p.get("consensus_support_frames") is not None
            else 0.0
        )
        for p in pockets
    ]
    max_support = max(supports) if supports else 1.0
    max_support = max(max_support, 1.0)

    bio_norms = _normalize_minmax(bio_scores, neutral=0.5)
    support_norms = [min(1.0, s / max_support) for s in supports]

    scored: list[dict[str, Any]] = []
    for pocket, bio_norm, support_norm in zip(pockets, bio_norms, support_norms):
        center_stability = float(
            pocket.get("consensus_center_stability")
            if pocket.get("consensus_center_stability") is not None
            else CENTER_STABILITY_MAX
        )
        volume_cv = float(
            pocket.get("consensus_volume_cv")
            if pocket.get("consensus_volume_cv") is not None
            else VOLUME_CV_MAX
        )
        center_stability_norm = min(1.0, max(0.0, center_stability / CENTER_STABILITY_MAX))
        volume_cv_norm = min(1.0, max(0.0, volume_cv / VOLUME_CV_MAX))
        drug_norm = _druggability_norm(pocket)

        rank_score = (
            0.35 * bio_norm
            + 0.25 * support_norm
            + 0.15 * drug_norm
            + 0.15 * (1.0 - center_stability_norm)
            + 0.10 * (1.0 - volume_cv_norm)
        )

        hard_filter_pass = (
            float(
                pocket.get("consensus_support_frames")
                if pocket.get("consensus_support_frames") is not None
                else 0.0
            )
            >= CONSENSUS_MIN_FRAMES
            and center_stability <= CENTER_STABILITY_MAX
            and volume_cv <= VOLUME_CV_MAX
        )

        ranked = dict(pocket)
        ranked["rank_score"] = round(rank_score, 6)
        ranked["rank_hard_filter_pass"] = hard_filter_pass
        ranked["rank_score_breakdown"] = {
            "bio_score_norm": round(bio_norm, 6),
            "support_norm": round(support_norm, 6),
            "druggability_norm": round(drug_norm, 6),
            "center_stability_norm": round(center_stability_norm, 6),
            "volume_cv_norm": round(volume_cv_norm, 6),
        }
        ranked["rank_reason"] = (
            f"bio={bio_norm:.3f} support={support_norm:.3f} drug={drug_norm:.3f} "
            f"center={center_stability:.3f}A volume_cv={volume_cv:.3f}"
        )
        scored.append(ranked)
    return scored


def _legacy_rank(pockets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Existing consensus pipeline already returns sorted pockets.
    return [dict(p) for p in pockets]


def _refined_rank(pockets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = _prepare_refined_rank(pockets)
    filtered = [p for p in scored if bool(p.get("rank_hard_filter_pass", False))]
    target = filtered if filtered else scored
    target = sorted(
        target,
        key=lambda p: (
            float(p.get("rank_score", 0.0)),
            float(p.get("bio_score", 0.0)),
            float(p.get("consensus_support_frames", 0.0)),
        ),
        reverse=True,
    )
    for idx, pocket in enumerate(target, start=1):
        pocket["rank"] = idx
    return target


def _evaluate_case(
    test_case: dict[str, Any],
    pockets: list[dict[str, Any]],
    diagnostics: dict[str, Any],
    *,
    ranking_mode: str,
) -> dict[str, Any]:
    ordered = _legacy_rank(pockets) if ranking_mode == "legacy" else _refined_rank(pockets)
    matched, best_distance, best_pocket = check_pocket_match(
        ordered,
        test_case["cryptic_pocket_center"],
        tolerance=CANONICAL_TOLERANCE,
        druggable_only=CANONICAL_DRUGGABLE_ONLY,
        top_n=CANONICAL_TOP_N,
    )
    return {
        "pdb_id": test_case["pdb_id"],
        "protein_name": test_case["name"],
        "pocket_type": test_case["pocket_type"],
        "matched": bool(matched),
        "best_distance": best_distance,
        "best_pocket_center": best_pocket.get("center") if best_pocket else None,
        "best_pocket_score": best_pocket.get("bio_score") if best_pocket else None,
        "best_pocket_volume": best_pocket.get("volume") if best_pocket else None,
        "best_rank_score": best_pocket.get("rank_score") if best_pocket else None,
        "best_rank_reason": best_pocket.get("rank_reason") if best_pocket else None,
        "ranking_mode": ranking_mode,
        "n_pockets_found": len(ordered),
        "n_druggable_pockets": sum(1 for p in ordered if bool(p.get("druggable", False))),
        "diagnostics": diagnostics,
    }


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    error_count = sum(1 for r in results if r.get("error"))
    successful_runs = total - error_count
    tp = sum(1 for r in results if bool(r.get("matched", False)))
    fn = total - tp
    total_found = sum(int(r.get("n_pockets_found", 0) or 0) for r in results)
    recall = tp / total if total > 0 else 0.0
    precision = tp / total_found if total_found > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    distances = [float(r["best_distance"]) for r in results if r.get("best_distance") is not None]
    return {
        "total_cases": total,
        "successful_runs": successful_runs,
        "error_count": error_count,
        "true_positives": tp,
        "false_negatives": fn,
        "recall": recall,
        "precision": precision,
        "f1_score": f1,
        "avg_best_distance": mean(distances) if distances else 0.0,
    }


def _summarize_by_type(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, dict[str, float]] = {}
    for row in results:
        pocket_type = str(row["pocket_type"])
        stats = by_type.setdefault(pocket_type, {"total": 0.0, "hits": 0.0})
        stats["total"] += 1.0
        if bool(row.get("matched", False)):
            stats["hits"] += 1.0
    for stats in by_type.values():
        stats["recall"] = stats["hits"] / stats["total"] if stats["total"] > 0 else 0.0
    return by_type


def _run_multi_case(
    test_case: dict[str, Any],
    *,
    analysis_atom_mode: str,
    frame_selection_mode: str,
    frame_selection_fraction: float,
    per_frame_top_n: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    return run_pipeline_for_protein(
        pdb_id=str(test_case["pdb_id"]),
        n_frames=20,
        aggregation_mode="multi",
        analysis_atom_mode=analysis_atom_mode,
        consensus_min_frames=CONSENSUS_MIN_FRAMES,
        consensus_distance=4.0,
        per_frame_top_n=per_frame_top_n,
        center_stability_max=CENTER_STABILITY_MAX,
        volume_cv_max=VOLUME_CV_MAX,
        reuse_existing_frames=True,
        frame_selection_mode=frame_selection_mode,
        frame_selection_fraction=frame_selection_fraction,
    )


def _run_a1_domain_motion(
    *,
    test_cases: list[dict[str, Any]],
    analysis_atom_mode: str,
    frame_selection_fraction: float,
    per_frame_top_n: int,
) -> dict[str, Any]:
    target_types = {"domain_motion", "loop_rearrangement"}
    mini_cases = [c for c in test_cases if str(c["pocket_type"]) in target_types]
    strategies = [
        ("uniform", "uniform"),
        ("domain_motion_weighted", "domain_motion_weighted"),
    ]

    strategy_rows: dict[str, list[dict[str, Any]]] = {key: [] for key, _ in strategies}
    strategy_errors: dict[str, list[dict[str, str]]] = {key: [] for key, _ in strategies}

    for strategy_key, frame_mode in strategies:
        print(f"[A1] Strategy={strategy_key} cases={len(mini_cases)}")
        for idx, case in enumerate(mini_cases, start=1):
            pdb_id = str(case["pdb_id"]).upper()
            print(f"  [A1:{strategy_key}] {idx}/{len(mini_cases)} {pdb_id}")
            pockets, diagnostics, error = _run_multi_case(
                case,
                analysis_atom_mode=analysis_atom_mode,
                frame_selection_mode=frame_mode,
                frame_selection_fraction=frame_selection_fraction,
                per_frame_top_n=per_frame_top_n,
            )
            if error:
                strategy_errors[strategy_key].append({"pdb_id": pdb_id, "error": error})
                strategy_rows[strategy_key].append(
                    {
                        "pdb_id": pdb_id,
                        "protein_name": case["name"],
                        "pocket_type": case["pocket_type"],
                        "matched": False,
                        "best_distance": None,
                        "error": error,
                        "diagnostics": diagnostics,
                    }
                )
                continue
            eval_row = _evaluate_case(
                case,
                pockets,
                diagnostics,
                ranking_mode="refined",
            )
            strategy_rows[strategy_key].append(eval_row)

    out: dict[str, Any] = {
        "generated_at_utc": _utc_now(),
        "scope": "A1 domain-motion capture mini A/B",
        "canonical_lock": {
            "tolerance": CANONICAL_TOLERANCE,
            "top_n": CANONICAL_TOP_N,
            "druggable_only": CANONICAL_DRUGGABLE_ONLY,
        },
        "config": {
            "analysis_atom_mode": analysis_atom_mode,
            "frame_selection_fraction": frame_selection_fraction,
            "per_frame_top_n": per_frame_top_n,
            "consensus_min_frames": CONSENSUS_MIN_FRAMES,
            "center_stability_max": CENTER_STABILITY_MAX,
            "volume_cv_max": VOLUME_CV_MAX,
        },
        "mini_set_size": len(mini_cases),
        "mini_set_ids": [str(c["pdb_id"]).upper() for c in mini_cases],
        "results": {},
    }

    for strategy_key, _ in strategies:
        rows = strategy_rows[strategy_key]
        summary = _summarize(rows)
        by_type = _summarize_by_type(rows)
        dm_total = int(by_type.get("domain_motion", {}).get("total", 0.0))
        dm_hits = int(by_type.get("domain_motion", {}).get("hits", 0.0))
        dm_recall = float(by_type.get("domain_motion", {}).get("recall", 0.0))
        out["results"][strategy_key] = {
            "summary": summary,
            "by_type": by_type,
            "domain_motion_hits": dm_hits,
            "domain_motion_total": dm_total,
            "domain_motion_recall": dm_recall,
            "case_results": rows,
            "errors": strategy_errors[strategy_key],
        }

    uniform = out["results"]["uniform"]
    weighted = out["results"]["domain_motion_weighted"]
    out["acceptance"] = {
        "domain_motion_target": ">=1/4",
        "domain_motion_before": uniform["domain_motion_hits"],
        "domain_motion_after": weighted["domain_motion_hits"],
        "domain_motion_acceptance_pass": weighted["domain_motion_hits"] >= 1,
        "mini_recall_trend_positive": (
            float(weighted["summary"]["recall"]) > float(uniform["summary"]["recall"])
        ),
    }
    return out


def _mini_set_cases(test_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    target_types = {"domain_motion", "loop_rearrangement"}
    return [c for c in test_cases if str(c["pocket_type"]) in target_types]


def _run_cp_a_trial(
    *,
    trial_id: str,
    title: str,
    mini_cases: list[dict[str, Any]],
    analysis_atom_mode: str,
    frame_selection_mode: str,
    frame_selection_fraction: float,
    ranking_mode: str,
    per_frame_top_n: int,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    print(
        f"[CP-A:{trial_id}] {title} | "
        f"atom={analysis_atom_mode} sampling={frame_selection_mode}:{frame_selection_fraction:.2f} "
        f"ranking={ranking_mode}"
    )
    for idx, case in enumerate(mini_cases, start=1):
        pdb_id = str(case["pdb_id"]).upper()
        print(f"  [CP-A:{trial_id}] {idx}/{len(mini_cases)} {pdb_id}")
        pockets, diagnostics, error = _run_multi_case(
            case,
            analysis_atom_mode=analysis_atom_mode,
            frame_selection_mode=frame_selection_mode,
            frame_selection_fraction=frame_selection_fraction,
            per_frame_top_n=per_frame_top_n,
        )
        if error:
            errors.append({"pdb_id": pdb_id, "error": error})
            rows.append(
                {
                    "pdb_id": pdb_id,
                    "protein_name": case["name"],
                    "pocket_type": case["pocket_type"],
                    "matched": False,
                    "best_distance": None,
                    "error": error,
                    "ranking_mode": ranking_mode,
                    "n_pockets_found": 0,
                    "n_druggable_pockets": 0,
                    "diagnostics": diagnostics,
                }
            )
            continue

        result = _evaluate_case(
            case,
            pockets,
            diagnostics,
            ranking_mode=ranking_mode,
        )
        rows.append(result)

    summary = _summarize(rows)
    by_type = _summarize_by_type(rows)
    domain_motion_hits = int(by_type.get("domain_motion", {}).get("hits", 0.0))
    domain_motion_total = int(by_type.get("domain_motion", {}).get("total", 0.0))
    domain_motion_recall = float(by_type.get("domain_motion", {}).get("recall", 0.0))
    return {
        "trial_id": trial_id,
        "title": title,
        "config": {
            "analysis_atom_mode": analysis_atom_mode,
            "frame_selection_mode": frame_selection_mode,
            "frame_selection_fraction": frame_selection_fraction,
            "ranking_mode": ranking_mode,
            "per_frame_top_n": per_frame_top_n,
            "consensus_min_frames": CONSENSUS_MIN_FRAMES,
            "center_stability_max": CENTER_STABILITY_MAX,
            "volume_cv_max": VOLUME_CV_MAX,
        },
        "summary": summary,
        "by_type": by_type,
        "domain_motion_hits": domain_motion_hits,
        "domain_motion_total": domain_motion_total,
        "domain_motion_recall": domain_motion_recall,
        "case_results": rows,
        "errors": errors,
    }


def _select_best_cp_a_trial(trials: list[dict[str, Any]]) -> dict[str, Any]:
    if not trials:
        raise ValueError("No CP-A trials available.")

    def _key(trial: dict[str, Any]) -> tuple[float, float, float, float]:
        summary = trial["summary"]
        return (
            float(trial.get("domain_motion_hits", 0)),
            float(summary.get("recall", 0.0)),
            -float(summary.get("error_count", 0.0)),
            -float(summary.get("avg_best_distance", 0.0)),
        )

    return max(trials, key=_key)


def _run_cp_a_pivot(
    *,
    test_cases: list[dict[str, Any]],
    per_frame_top_n: int,
) -> dict[str, Any]:
    mini_cases = _mini_set_cases(test_cases)
    trial_specs = [
        {
            "trial_id": "t0_baseline",
            "title": "Baseline frame_ca + uniform + legacy",
            "analysis_atom_mode": "frame_ca",
            "frame_selection_mode": "uniform",
            "frame_selection_fraction": 0.35,
            "ranking_mode": "legacy",
        },
        {
            "trial_id": "t1_rank_refine",
            "title": "frame_ca + uniform + refined",
            "analysis_atom_mode": "frame_ca",
            "frame_selection_mode": "uniform",
            "frame_selection_fraction": 0.35,
            "ranking_mode": "refined",
        },
        {
            "trial_id": "t2_sampling_weighted",
            "title": "frame_ca + domain_motion_weighted + refined",
            "analysis_atom_mode": "frame_ca",
            "frame_selection_mode": "domain_motion_weighted",
            "frame_selection_fraction": 0.35,
            "ranking_mode": "refined",
        },
        {
            "trial_id": "t3_sampling_deeper",
            "title": "frame_ca + domain_motion_weighted(0.60) + refined",
            "analysis_atom_mode": "frame_ca",
            "frame_selection_mode": "domain_motion_weighted",
            "frame_selection_fraction": 0.60,
            "ranking_mode": "refined",
        },
        {
            "trial_id": "t4_atom_mode_heavy",
            "title": "reconstructed_heavy + domain_motion_weighted + refined",
            "analysis_atom_mode": "reconstructed_heavy",
            "frame_selection_mode": "domain_motion_weighted",
            "frame_selection_fraction": 0.35,
            "ranking_mode": "refined",
        },
    ]

    trials: list[dict[str, Any]] = []
    for spec in trial_specs:
        trial = _run_cp_a_trial(
            trial_id=spec["trial_id"],
            title=spec["title"],
            mini_cases=mini_cases,
            analysis_atom_mode=spec["analysis_atom_mode"],
            frame_selection_mode=spec["frame_selection_mode"],
            frame_selection_fraction=float(spec["frame_selection_fraction"]),
            ranking_mode=spec["ranking_mode"],
            per_frame_top_n=per_frame_top_n,
        )
        trials.append(trial)

    baseline = trials[0]
    baseline_recall = float(baseline["summary"]["recall"])
    baseline_dm_hits = int(baseline["domain_motion_hits"])
    baseline_avg_dist = float(baseline["summary"]["avg_best_distance"])

    for trial in trials:
        trial["delta_vs_baseline"] = {
            "recall_delta": float(trial["summary"]["recall"]) - baseline_recall,
            "domain_motion_hit_delta": int(trial["domain_motion_hits"]) - baseline_dm_hits,
            "avg_best_distance_delta": (
                float(trial["summary"]["avg_best_distance"]) - baseline_avg_dist
            ),
        }

    best_trial = _select_best_cp_a_trial(trials)
    best_recall = float(best_trial["summary"]["recall"])
    cp_a_decision = "PIVOT_REQUIRED" if best_recall < 0.22 else "SG2_CANDIDATE"

    return {
        "generated_at_utc": _utc_now(),
        "scope": "CP-A pivot mini-set trials (domain_motion + loop_rearrangement)",
        "canonical_lock": {
            "tolerance": CANONICAL_TOLERANCE,
            "top_n": CANONICAL_TOP_N,
            "druggable_only": CANONICAL_DRUGGABLE_ONLY,
        },
        "mini_set_size": len(mini_cases),
        "mini_set_ids": [str(c["pdb_id"]).upper() for c in mini_cases],
        "trials": trials,
        "best_trial": {
            "trial_id": best_trial["trial_id"],
            "title": best_trial["title"],
            "config": best_trial["config"],
            "summary": best_trial["summary"],
            "domain_motion_hits": best_trial["domain_motion_hits"],
            "domain_motion_total": best_trial["domain_motion_total"],
            "domain_motion_recall": best_trial["domain_motion_recall"],
        },
        "cp_a_decision_rule": "if recall < 0.22 => PIVOT_REQUIRED else SG2_CANDIDATE",
        "cp_a_decision": cp_a_decision,
    }


def _run_a2_a3_full(
    *,
    test_cases: list[dict[str, Any]],
    analysis_atom_mode: str,
    frame_selection_mode: str,
    frame_selection_fraction: float,
    per_frame_top_n: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    per_case: list[dict[str, Any]] = []
    legacy_results: list[dict[str, Any]] = []
    refined_results: list[dict[str, Any]] = []

    for idx, case in enumerate(test_cases, start=1):
        pdb_id = str(case["pdb_id"]).upper()
        print(f"[A2/A3] {idx}/{len(test_cases)} {pdb_id}")
        pockets, diagnostics, error = _run_multi_case(
            case,
            analysis_atom_mode=analysis_atom_mode,
            frame_selection_mode=frame_selection_mode,
            frame_selection_fraction=frame_selection_fraction,
            per_frame_top_n=per_frame_top_n,
        )
        if error:
            legacy_row = {
                "pdb_id": pdb_id,
                "protein_name": case["name"],
                "pocket_type": case["pocket_type"],
                "matched": False,
                "best_distance": None,
                "error": error,
                "ranking_mode": "legacy",
                "n_pockets_found": 0,
                "n_druggable_pockets": 0,
                "diagnostics": diagnostics,
            }
            refined_row = dict(legacy_row)
            refined_row["ranking_mode"] = "refined"
            legacy_results.append(legacy_row)
            refined_results.append(refined_row)
            per_case.append(
                {
                    "pdb_id": pdb_id,
                    "protein_name": case["name"],
                    "pocket_type": case["pocket_type"],
                    "legacy": legacy_row,
                    "refined": refined_row,
                }
            )
            continue

        legacy_row = _evaluate_case(case, pockets, diagnostics, ranking_mode="legacy")
        refined_row = _evaluate_case(case, pockets, diagnostics, ranking_mode="refined")
        legacy_results.append(legacy_row)
        refined_results.append(refined_row)
        per_case.append(
            {
                "pdb_id": pdb_id,
                "protein_name": case["name"],
                "pocket_type": case["pocket_type"],
                "legacy": legacy_row,
                "refined": refined_row,
            }
        )

    legacy_summary = _summarize(legacy_results)
    refined_summary = _summarize(refined_results)

    known_hits_guard = ["1CBS", "1STP", "3K5V"]
    refined_hit_map = {
        str(r["pdb_id"]).upper(): bool(r.get("matched", False)) for r in refined_results
    }
    known_hits_preserved = all(refined_hit_map.get(pid, False) for pid in known_hits_guard)

    avg_distance_delta = (
        float(refined_summary["avg_best_distance"]) - float(legacy_summary["avg_best_distance"])
    )
    regression_count = sum(
        1
        for pair in per_case
        if bool(pair["legacy"].get("matched", False))
        and not bool(pair["refined"].get("matched", False))
    )

    a2_payload = {
        "generated_at_utc": _utc_now(),
        "scope": "A2 consensus/ranking refinement deltas",
        "canonical_lock": {
            "tolerance": CANONICAL_TOLERANCE,
            "top_n": CANONICAL_TOP_N,
            "druggable_only": CANONICAL_DRUGGABLE_ONLY,
        },
        "config": {
            "analysis_atom_mode": analysis_atom_mode,
            "frame_selection_mode": frame_selection_mode,
            "frame_selection_fraction": frame_selection_fraction,
            "per_frame_top_n": per_frame_top_n,
            "consensus_min_frames": CONSENSUS_MIN_FRAMES,
            "center_stability_max": CENTER_STABILITY_MAX,
            "volume_cv_max": VOLUME_CV_MAX,
            "refined_rank_formula": (
                "0.35*bio_score_norm + 0.25*support_norm + 0.15*druggability_norm "
                "+ 0.15*(1-center_stability_norm) + 0.10*(1-volume_cv_norm)"
            ),
            "hard_filters": {
                "support_min": CONSENSUS_MIN_FRAMES,
                "center_stability_max": CENTER_STABILITY_MAX,
                "volume_cv_max": VOLUME_CV_MAX,
            },
        },
        "legacy_summary": legacy_summary,
        "refined_summary": refined_summary,
        "deltas": {
            "recall_delta": float(refined_summary["recall"]) - float(legacy_summary["recall"]),
            "avg_best_distance_delta": avg_distance_delta,
            "regression_count": regression_count,
            "known_hits_guard_set": known_hits_guard,
            "known_hits_preserved": known_hits_preserved,
        },
        "per_case": per_case,
    }

    pocket_type_stats = _summarize_by_type(refined_results)
    domain_motion_stats = pocket_type_stats.get("domain_motion", {"hits": 0.0, "total": 0.0, "recall": 0.0})

    a3_payload = {
        "generated_at_utc": _utc_now(),
        "summary": {
            **refined_summary,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "config": {
                "tolerance": CANONICAL_TOLERANCE,
                "top_n": CANONICAL_TOP_N,
                "druggable_only": CANONICAL_DRUGGABLE_ONLY,
                "aggregation_mode": "multi",
                "analysis_atom_mode": analysis_atom_mode,
                "frame_selection_mode": frame_selection_mode,
                "frame_selection_fraction": frame_selection_fraction,
                "consensus_min_frames": CONSENSUS_MIN_FRAMES,
                "consensus_distance": 4.0,
                "per_frame_top_n": per_frame_top_n,
                "center_stability_max": CENTER_STABILITY_MAX,
                "volume_cv_max": VOLUME_CV_MAX,
                "ranking_policy": "refined",
            },
            "domain_motion_hits": int(domain_motion_stats.get("hits", 0.0)),
            "domain_motion_total": int(domain_motion_stats.get("total", 0.0)),
            "domain_motion_recall": float(domain_motion_stats.get("recall", 0.0)),
        },
        "results": refined_results,
        "by_type": pocket_type_stats,
        "reference_legacy_summary": legacy_summary,
    }
    return a2_payload, a3_payload


def _write_domain_motion_report(path: Path, payload: dict[str, Any]) -> None:
    if "trials" in payload:
        best_trial = payload["best_trial"]
        lines = [
            "# Recovery v2 Recall Domain-Motion Report",
            "",
            f"- Generated at (UTC): {payload['generated_at_utc']}",
            "- Scope: CP-A pivot mini-set (domain_motion + loop_rearrangement)",
            "- Canonical lock: tolerance=8.0A, top-N=20, druggable=true",
            f"- Mini-set size: {payload['mini_set_size']}",
            "",
            "## Denenen Degisiklikler",
            "",
            "- Sampling: uniform vs domain_motion_weighted, fraction=0.35/0.60",
            "- Ranking: legacy vs refined ranking formula + hard filters",
            "- Atom mode: frame_ca vs reconstructed_heavy",
            "",
            "## Trial Sonuclari",
            "",
            "| Trial | Degisiklik | Recall | Domain-motion | Error Count | Avg Best Distance |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
        for trial in payload["trials"]:
            summary = trial["summary"]
            lines.append(
                f"| {trial['trial_id']} | {trial['title']} | "
                f"{summary['recall']*100:.1f}% ({summary['true_positives']}/{summary['total_cases']}) | "
                f"{trial['domain_motion_hits']}/{trial['domain_motion_total']} | "
                f"{summary['error_count']} | "
                f"{summary['avg_best_distance']:.2f}A |"
            )

        lines.extend(
            [
                "",
                "## En Iyi Aday Konfig",
                "",
                f"- Trial: `{best_trial['trial_id']}` - {best_trial['title']}",
                (
                    f"- Recall: {best_trial['summary']['recall']*100:.1f}% "
                    f"({best_trial['summary']['true_positives']}/{best_trial['summary']['total_cases']})"
                ),
                (
                    f"- Domain-motion: {best_trial['domain_motion_hits']}/"
                    f"{best_trial['domain_motion_total']} "
                    f"({best_trial['domain_motion_recall']*100:.1f}%)"
                ),
                f"- Error count: {best_trial['summary']['error_count']}",
                "",
                "## CP-A Karar",
                "",
                f"- Kural: `{payload['cp_a_decision_rule']}`",
                f"- Karar: **{payload['cp_a_decision']}**",
            ]
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        return

    uniform = payload["results"]["uniform"]
    weighted = payload["results"]["domain_motion_weighted"]
    acceptance = payload["acceptance"]
    lines = [
        "# Recovery v2 Recall Domain-Motion Report",
        "",
        f"- Generated at (UTC): {payload['generated_at_utc']}",
        "- Scope: A1 domain-motion + loop_rearrangement mini A/B",
        "- Canonical lock: tolerance=8.0A, top-N=20, druggable=true",
        "",
        "## A/B Summary",
        "",
        "| Strategy | Recall | Domain-motion Hits | Domain-motion Recall | Avg Best Distance |",
        "| --- | ---: | ---: | ---: | ---: |",
        (
            f"| uniform | {uniform['summary']['recall']*100:.1f}% "
            f"({uniform['summary']['true_positives']}/{uniform['summary']['total_cases']}) | "
            f"{uniform['domain_motion_hits']}/{uniform['domain_motion_total']} | "
            f"{uniform['domain_motion_recall']*100:.1f}% | "
            f"{uniform['summary']['avg_best_distance']:.2f}A |"
        ),
        (
            f"| domain_motion_weighted | {weighted['summary']['recall']*100:.1f}% "
            f"({weighted['summary']['true_positives']}/{weighted['summary']['total_cases']}) | "
            f"{weighted['domain_motion_hits']}/{weighted['domain_motion_total']} | "
            f"{weighted['domain_motion_recall']*100:.1f}% | "
            f"{weighted['summary']['avg_best_distance']:.2f}A |"
        ),
        "",
        "## Acceptance",
        "",
        f"- Domain-motion target (>=1/4): **{'PASS' if acceptance['domain_motion_acceptance_pass'] else 'FAIL'}**",
        f"- Recall trend positive: **{'PASS' if acceptance['mini_recall_trend_positive'] else 'FAIL'}**",
        "",
        "## Notes",
        "",
        "- Ranking policy: refined rank formula + hard filters.",
        "- A/B farkı yalnız frame selection stratejisidir.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_consensus_report(path: Path, payload: dict[str, Any]) -> None:
    legacy = payload["legacy_summary"]
    refined = payload["refined_summary"]
    deltas = payload["deltas"]
    lines = [
        "# Recovery v2 Consensus Ranking Report",
        "",
        f"- Generated at (UTC): {payload['generated_at_utc']}",
        "- Scope: A2 legacy vs refined ranking comparison (20 protein full set)",
        "- Canonical lock: tolerance=8.0A, top-N=20, druggable=true",
        "",
        "## Summary",
        "",
        "| Metric | Legacy | Refined | Delta |",
        "| --- | ---: | ---: | ---: |",
        (
            f"| Recall | {legacy['recall']*100:.1f}% ({legacy['true_positives']}/{legacy['total_cases']}) | "
            f"{refined['recall']*100:.1f}% ({refined['true_positives']}/{refined['total_cases']}) | "
            f"{deltas['recall_delta']*100:+.1f} puan |"
        ),
        (
            f"| Avg best distance | {legacy['avg_best_distance']:.2f}A | "
            f"{refined['avg_best_distance']:.2f}A | "
            f"{deltas['avg_best_distance_delta']:+.2f}A |"
        ),
        "",
        "## Acceptance",
        "",
        f"- Known hit guard (1CBS, 1STP, 3K5V): **{'PASS' if deltas['known_hits_preserved'] else 'FAIL'}**",
        f"- Regression case count: **{deltas['regression_count']}**",
        "",
        "## Refined Formula",
        "",
        f"- `{payload['config']['refined_rank_formula']}`",
        "- Hard filters: support>=3, center_stability<=2.0A, volume_cv<=0.20",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_v3_report(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# Recall Recovery Experiments v3",
        "",
        f"- Generated at (UTC): {payload['generated_at_utc']}",
        "- Scope: A3 full rerun (20 proteins, refined ranking)",
        "",
        "## Metrics",
        "",
        f"- Recall: **{summary['recall']*100:.1f}%** ({summary['true_positives']}/{summary['total_cases']})",
        f"- Precision: **{summary['precision']*100:.3f}%**",
        f"- F1: **{summary['f1_score']*100:.3f}%**",
        f"- Avg best distance: **{summary['avg_best_distance']:.2f}A**",
        (
            f"- Domain-motion: **{summary['domain_motion_hits']}/"
            f"{summary['domain_motion_total']}** "
            f"({summary['domain_motion_recall']*100:.1f}%)"
        ),
        "",
        "## Config Lock",
        "",
        f"- tolerance={summary['config']['tolerance']}",
        f"- top_n={summary['config']['top_n']}",
        f"- druggable_only={summary['config']['druggable_only']}",
        f"- aggregation_mode={summary['config']['aggregation_mode']}",
        f"- analysis_atom_mode={summary['config']['analysis_atom_mode']}",
        f"- frame_selection_mode={summary['config']['frame_selection_mode']}",
        f"- frame_selection_fraction={summary['config']['frame_selection_fraction']:.2f}",
        "",
        "## Decision",
        "",
        (
            f"- SG1 recall checkpoint (>=0.22): "
            f"**{'PASS' if summary['recall'] >= 0.22 else 'FAIL'}**"
        ),
        (
            f"- Gate-level recall target (>=0.30): "
            f"**{'PASS' if summary['recall'] >= 0.30 else 'FAIL'}**"
        ),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SG1 WS-A recall workstream (A1/A2/A3).")
    parser.add_argument(
        "--test-set",
        default="data/validation/known_cryptic_pockets.json",
    )
    parser.add_argument(
        "--analysis-atom-mode",
        default="frame_ca",
        choices=["frame_ca", "reconstructed_heavy"],
    )
    parser.add_argument(
        "--frame-selection-fraction",
        type=float,
        default=0.35,
    )
    parser.add_argument(
        "--per-frame-top-n",
        type=int,
        default=20,
    )
    parser.add_argument(
        "--a1-output-json",
        default="data/validation/recovery_v2_domain_motion_eval.json",
    )
    parser.add_argument(
        "--a1-output-md",
        default="docs/recovery_v2_recall_domain_motion_report.md",
    )
    parser.add_argument(
        "--a2-output-json",
        default="data/validation/recovery_v2_consensus_deltas.json",
    )
    parser.add_argument(
        "--a2-output-md",
        default="docs/recovery_v2_consensus_ranking_report.md",
    )
    parser.add_argument(
        "--a3-output-json",
        default="data/validation/recall_recovery_experiments_v3.json",
    )
    parser.add_argument(
        "--a3-output-md",
        default="docs/recall_recovery_experiments_v3.md",
    )
    parser.add_argument(
        "--cp-a-mini-only",
        action="store_true",
        help="Run only CP-A mini-set trials and generate A1 outputs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    test_cases, _ = load_test_set(ROOT / args.test_set)

    if args.cp_a_mini_only:
        cp_a_payload = _run_cp_a_pivot(
            test_cases=test_cases,
            per_frame_top_n=args.per_frame_top_n,
        )
        _write_json(ROOT / args.a1_output_json, cp_a_payload)
        _write_domain_motion_report(ROOT / args.a1_output_md, cp_a_payload)
        print("[OK] CP-A mini output json:", ROOT / args.a1_output_json)
        print("[OK] CP-A mini output md  :", ROOT / args.a1_output_md)
        print("[INFO] CP-A decision:", cp_a_payload["cp_a_decision"])
        return 0

    a1_payload = _run_a1_domain_motion(
        test_cases=test_cases,
        analysis_atom_mode=args.analysis_atom_mode,
        frame_selection_fraction=args.frame_selection_fraction,
        per_frame_top_n=args.per_frame_top_n,
    )
    _write_json(ROOT / args.a1_output_json, a1_payload)
    _write_domain_motion_report(ROOT / args.a1_output_md, a1_payload)

    weighted_dm_recall = float(
        a1_payload["results"]["domain_motion_weighted"]["domain_motion_recall"]
    )
    uniform_dm_recall = float(a1_payload["results"]["uniform"]["domain_motion_recall"])
    chosen_frame_mode = (
        "domain_motion_weighted"
        if weighted_dm_recall >= uniform_dm_recall
        else "uniform"
    )
    print(f"[A2/A3] selected frame mode: {chosen_frame_mode}")

    a2_payload, a3_payload = _run_a2_a3_full(
        test_cases=test_cases,
        analysis_atom_mode=args.analysis_atom_mode,
        frame_selection_mode=chosen_frame_mode,
        frame_selection_fraction=args.frame_selection_fraction,
        per_frame_top_n=args.per_frame_top_n,
    )
    _write_json(ROOT / args.a2_output_json, a2_payload)
    _write_consensus_report(ROOT / args.a2_output_md, a2_payload)
    _write_json(ROOT / args.a3_output_json, a3_payload)
    _write_v3_report(ROOT / args.a3_output_md, a3_payload)

    print("[OK] A1 output json:", ROOT / args.a1_output_json)
    print("[OK] A1 output md  :", ROOT / args.a1_output_md)
    print("[OK] A2 output json:", ROOT / args.a2_output_json)
    print("[OK] A2 output md  :", ROOT / args.a2_output_md)
    print("[OK] A3 output json:", ROOT / args.a3_output_json)
    print("[OK] A3 output md  :", ROOT / args.a3_output_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
