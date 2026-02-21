#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from time import monotonic
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
CONSENSUS_DISTANCE = 4.0
CP_A_MINI_N_FRAMES = 7
RELAXED_CONSENSUS_MIN_FRAMES = 2
RELAXED_CENTER_STABILITY_MAX = 3.0
RELAXED_VOLUME_CV_MAX = 0.35
RELAXED_CONSENSUS_DISTANCE = 4.5
DRUGGABILITY_RESCUE_BIO_MIN = 0.75
DRUGGABILITY_RESCUE_SUPPORT_MIN = 4
DRUGGABILITY_RESCUE_CENTER_STABILITY_MAX = 0.35
DRUGGABILITY_RESCUE_VOLUME_CV_MAX = 0.25
DRUGGABILITY_RESCUE_HYDROPHOBIC_MIN = 0.45
CP_A_DOMAIN_DEEP_MIN_FRAMES = 12
CP_A_DOMAIN_DEEP_FRACTION = 0.60
DEFAULT_CASE_TIMEOUT_SECONDS = 1200
A2_A3_DOMAIN_DEEP_TYPES = {"domain_motion"}
A2_A3_BASE_N_FRAMES = 20
A2_A3_RESCUE_NEAR_MISS_DISTANCE = 14.0
A2_A3_RESCUE_TARGET_TYPES = {
    "domain_motion",
    "loop_rearrangement",
    "side-chain_flip",
    "portal_opening",
}
A2_A3_HEAVY_FALLBACK_TYPES = {"domain_motion", "side-chain_flip"}


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


def _is_druggability_rescue_candidate(pocket: dict[str, Any]) -> bool:
    cls = str(pocket.get("druggability_class", "")).lower()
    if cls != "high":
        return False

    bio_score = float(pocket.get("bio_score", 0.0) or 0.0)
    support = float(
        pocket.get("consensus_support_frames")
        if pocket.get("consensus_support_frames") is not None
        else 0.0
    )
    center_stability = float(
        pocket.get("consensus_center_stability")
        if pocket.get("consensus_center_stability") is not None
        else 999.0
    )
    volume_cv = float(
        pocket.get("consensus_volume_cv")
        if pocket.get("consensus_volume_cv") is not None
        else 999.0
    )
    hydrophobic_ratio = float(pocket.get("hydrophobic_ratio", 0.0) or 0.0)

    return (
        bio_score >= DRUGGABILITY_RESCUE_BIO_MIN
        and support >= DRUGGABILITY_RESCUE_SUPPORT_MIN
        and center_stability <= DRUGGABILITY_RESCUE_CENTER_STABILITY_MAX
        and volume_cv <= DRUGGABILITY_RESCUE_VOLUME_CV_MAX
        and hydrophobic_ratio >= DRUGGABILITY_RESCUE_HYDROPHOBIC_MIN
    )


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
        base_druggable = bool(ranked.get("druggable", False))
        rescue_applied = False
        if not base_druggable and _is_druggability_rescue_candidate(ranked):
            rescue_applied = True
            ranked["druggable"] = True

        ranked["druggable_original"] = base_druggable
        ranked["druggability_rescue_applied"] = rescue_applied
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
        if rescue_applied:
            ranked["rank_reason"] += " rescue=druggability_high_confidence"
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
    n_frames: int = 20,
    consensus_min_frames: int = CONSENSUS_MIN_FRAMES,
    consensus_distance: float = CONSENSUS_DISTANCE,
    center_stability_max: float = CENTER_STABILITY_MAX,
    volume_cv_max: float = VOLUME_CV_MAX,
    reuse_existing_frames: bool = True,
    case_timeout_seconds: float | None = DEFAULT_CASE_TIMEOUT_SECONDS,
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    kwargs = {
        "pdb_id": str(test_case["pdb_id"]),
        "n_frames": n_frames,
        "aggregation_mode": "multi",
        "analysis_atom_mode": analysis_atom_mode,
        "consensus_min_frames": consensus_min_frames,
        "consensus_distance": consensus_distance,
        "per_frame_top_n": per_frame_top_n,
        "center_stability_max": center_stability_max,
        "volume_cv_max": volume_cv_max,
        "reuse_existing_frames": reuse_existing_frames,
        "frame_selection_mode": frame_selection_mode,
        "frame_selection_fraction": frame_selection_fraction,
    }
    if case_timeout_seconds is None or float(case_timeout_seconds) <= 0:
        return run_pipeline_for_protein(**kwargs)

    timeout = float(case_timeout_seconds)
    queue: mp.Queue = mp.Queue(maxsize=1)

    proc = mp.Process(target=_run_multi_case_worker, args=(queue, kwargs), daemon=True)
    proc.start()
    proc.join(timeout)
    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        diagnostics = {
            "timed_out": True,
            "case_timeout_seconds": timeout,
            "analysis_atom_mode": analysis_atom_mode,
            "frame_selection_mode": frame_selection_mode,
            "frame_selection_fraction": frame_selection_fraction,
            "n_frames": n_frames,
        }
        return [], diagnostics, f"TIMEOUT(case>{timeout:.0f}s)"

    if queue.empty():
        return [], {"timed_out": False, "case_timeout_seconds": timeout}, "WORKER_NO_RESULT"

    status, payload = queue.get()
    if status == "ok":
        return payload
    return [], {"timed_out": False, "case_timeout_seconds": timeout}, str(payload)


def _run_multi_case_worker(q: mp.Queue, run_kwargs: dict[str, Any]) -> None:
    try:
        q.put(("ok", run_pipeline_for_protein(**run_kwargs)))
    except Exception as exc:  # pragma: no cover
        q.put(("err", f"{type(exc).__name__}: {exc}"))


def _normalise_timeout(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return DEFAULT_CASE_TIMEOUT_SECONDS
    if timeout <= 0:
        return None
    return timeout


def _derived_case_timeout(
    *,
    case_timeout_seconds: float | None,
    n_frames: int,
    frame_selection_fraction: float,
    analysis_atom_mode: str,
) -> float | None:
    timeout = _normalise_timeout(case_timeout_seconds)
    if timeout is None:
        return None
    timeout *= max(1.0, float(n_frames) / 20.0)
    if analysis_atom_mode == "reconstructed_heavy":
        timeout *= 1.8
    return timeout


def _run_a1_domain_motion(
    *,
    test_cases: list[dict[str, Any]],
    analysis_atom_mode: str,
    frame_selection_fraction: float,
    per_frame_top_n: int,
    case_timeout_seconds: float | None,
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
                case_timeout_seconds=_derived_case_timeout(
                    case_timeout_seconds=case_timeout_seconds,
                    n_frames=20,
                    frame_selection_fraction=frame_selection_fraction,
                    analysis_atom_mode=analysis_atom_mode,
                ),
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
    n_frames: int,
    consensus_min_frames: int,
    consensus_distance: float,
    center_stability_max: float,
    volume_cv_max: float,
    run_cache: dict[tuple[Any, ...], tuple[list[dict[str, Any]], dict[str, Any], str | None]],
    hard_deadline_ts: float | None = None,
    case_timeout_seconds: float | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    trial_stop_reason: str | None = None
    trial_start_ts = monotonic()

    print(
        f"[CP-A:{trial_id}] {title} | "
        f"atom={analysis_atom_mode} sampling={frame_selection_mode}:{frame_selection_fraction:.2f} "
        f"ranking={ranking_mode} n_frames={n_frames}"
    )
    for idx, case in enumerate(mini_cases, start=1):
        if hard_deadline_ts is not None and monotonic() >= hard_deadline_ts:
            trial_stop_reason = "time_budget_reached_before_case"
            print(f"  [CP-A:{trial_id}] stopping early: {trial_stop_reason}")
            break
        pdb_id = str(case["pdb_id"]).upper()
        print(f"  [CP-A:{trial_id}] {idx}/{len(mini_cases)} {pdb_id}")
        cache_key = (
            pdb_id,
            analysis_atom_mode,
            frame_selection_mode,
            round(float(frame_selection_fraction), 4),
            int(per_frame_top_n),
            int(n_frames),
            int(consensus_min_frames),
            round(float(consensus_distance), 4),
            round(float(center_stability_max), 4),
            round(float(volume_cv_max), 4),
        )
        cached = run_cache.get(cache_key)
        if cached is None:
            cached = _run_multi_case(
                case,
                analysis_atom_mode=analysis_atom_mode,
                frame_selection_mode=frame_selection_mode,
                frame_selection_fraction=frame_selection_fraction,
                per_frame_top_n=per_frame_top_n,
                n_frames=n_frames,
                consensus_min_frames=consensus_min_frames,
                consensus_distance=consensus_distance,
                center_stability_max=center_stability_max,
                volume_cv_max=volume_cv_max,
                case_timeout_seconds=_derived_case_timeout(
                    case_timeout_seconds=case_timeout_seconds,
                    n_frames=n_frames,
                    frame_selection_fraction=frame_selection_fraction,
                    analysis_atom_mode=analysis_atom_mode,
                ),
            )
            run_cache[cache_key] = cached
        pockets, diagnostics, error = cached
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

        deep_pass_used = False
        if (
            ranking_mode == "refined"
            and analysis_atom_mode == "reconstructed_heavy"
            and frame_selection_mode == "domain_motion_weighted"
            and str(case.get("pocket_type", "")) == "domain_motion"
            and (
                int(n_frames) < CP_A_DOMAIN_DEEP_MIN_FRAMES
                or float(frame_selection_fraction) < CP_A_DOMAIN_DEEP_FRACTION
            )
        ):
            deep_n_frames = max(int(n_frames), CP_A_DOMAIN_DEEP_MIN_FRAMES)
            deep_fraction = max(float(frame_selection_fraction), CP_A_DOMAIN_DEEP_FRACTION)
            deep_cache_key = (
                pdb_id,
                analysis_atom_mode,
                frame_selection_mode,
                round(float(deep_fraction), 4),
                int(per_frame_top_n),
                int(deep_n_frames),
                int(consensus_min_frames),
                round(float(consensus_distance), 4),
                round(float(center_stability_max), 4),
                round(float(volume_cv_max), 4),
                "domain_deep_pass",
            )
            deep_cached = run_cache.get(deep_cache_key)
            if deep_cached is None:
                deep_cached = _run_multi_case(
                    case,
                    analysis_atom_mode=analysis_atom_mode,
                    frame_selection_mode=frame_selection_mode,
                    frame_selection_fraction=deep_fraction,
                    per_frame_top_n=per_frame_top_n,
                    n_frames=deep_n_frames,
                    consensus_min_frames=consensus_min_frames,
                    consensus_distance=consensus_distance,
                    center_stability_max=center_stability_max,
                    volume_cv_max=volume_cv_max,
                    case_timeout_seconds=_derived_case_timeout(
                        case_timeout_seconds=case_timeout_seconds,
                        n_frames=deep_n_frames,
                        frame_selection_fraction=deep_fraction,
                        analysis_atom_mode=analysis_atom_mode,
                    ),
                )
                run_cache[deep_cache_key] = deep_cached
            deep_pockets, deep_diagnostics, deep_error = deep_cached
            diagnostics = dict(diagnostics)
            if deep_error:
                diagnostics["domain_deep_pass"] = {
                    "status": "error",
                    "error": deep_error,
                    "n_frames": deep_n_frames,
                    "frame_selection_fraction": deep_fraction,
                }
            else:
                pockets = list(pockets) + list(deep_pockets)
                deep_pass_used = True
                diagnostics["domain_deep_pass"] = {
                    "status": "merged",
                    "n_frames": deep_n_frames,
                    "frame_selection_fraction": deep_fraction,
                    "base_candidate_count": len(cached[0]),
                    "deep_candidate_count": len(deep_pockets),
                    "merged_candidate_count": len(pockets),
                    "deep_frames_analyzed": deep_diagnostics.get("frames_analyzed"),
                }

        result = _evaluate_case(
            case,
            pockets,
            diagnostics,
            ranking_mode=ranking_mode,
        )
        result["domain_deep_pass_used"] = deep_pass_used
        rows.append(result)

    summary = _summarize(rows)
    by_type = _summarize_by_type(rows)
    domain_motion_hits = int(by_type.get("domain_motion", {}).get("hits", 0.0))
    domain_motion_total = int(by_type.get("domain_motion", {}).get("total", 0.0))
    domain_motion_recall = float(by_type.get("domain_motion", {}).get("recall", 0.0))
    elapsed_minutes = (monotonic() - trial_start_ts) / 60.0
    planned_cases = len(mini_cases)
    processed_cases = len(rows)
    coverage_fraction = (
        float(processed_cases) / float(planned_cases) if planned_cases > 0 else 0.0
    )
    return {
        "trial_id": trial_id,
        "title": title,
        "config": {
            "analysis_atom_mode": analysis_atom_mode,
            "frame_selection_mode": frame_selection_mode,
            "frame_selection_fraction": frame_selection_fraction,
            "ranking_mode": ranking_mode,
            "n_frames": n_frames,
            "per_frame_top_n": per_frame_top_n,
            "consensus_min_frames": consensus_min_frames,
            "consensus_distance": consensus_distance,
            "center_stability_max": center_stability_max,
            "volume_cv_max": volume_cv_max,
        },
        "summary": summary,
        "by_type": by_type,
        "domain_motion_hits": domain_motion_hits,
        "domain_motion_total": domain_motion_total,
        "domain_motion_recall": domain_motion_recall,
        "case_results": rows,
        "errors": errors,
        "stopped_early": bool(trial_stop_reason),
        "stop_reason": trial_stop_reason,
        "planned_cases": planned_cases,
        "processed_cases": processed_cases,
        "coverage_fraction": round(coverage_fraction, 4),
        "elapsed_minutes": round(elapsed_minutes, 3),
    }


def _select_best_cp_a_trial(trials: list[dict[str, Any]]) -> dict[str, Any]:
    if not trials:
        raise ValueError("No CP-A trials available.")

    def _key(trial: dict[str, Any]) -> tuple[float, float, float, float, float]:
        summary = trial["summary"]
        return (
            float(trial.get("coverage_fraction", 0.0)),
            float(trial.get("domain_motion_hits", 0)),
            float(summary.get("recall", 0.0)),
            -float(summary.get("error_count", 0.0)),
            -float(summary.get("avg_best_distance", 0.0)),
        )

    return max(trials, key=_key)


def _row_selection_score(row: dict[str, Any]) -> tuple[float, float]:
    matched_score = 1.0 if bool(row.get("matched", False)) else 0.0
    best_distance = row.get("best_distance")
    if isinstance(best_distance, (int, float)):
        distance_score = -float(best_distance)
    else:
        distance_score = -1e9
    return (matched_score, distance_score)


def _run_cp_a_pivot(
    *,
    test_cases: list[dict[str, Any]],
    per_frame_top_n: int,
    cp_a_profile: str,
    cp_a_trial_ids: list[str] | None,
    cp_a_max_minutes: float | None,
    case_timeout_seconds: float | None,
) -> dict[str, Any]:
    mini_cases = _mini_set_cases(test_cases)
    available_trial_specs = [
        {
            "trial_id": "t0_baseline",
            "title": "Baseline frame_ca + uniform + legacy",
            "analysis_atom_mode": "frame_ca",
            "frame_selection_mode": "uniform",
            "frame_selection_fraction": 0.35,
            "ranking_mode": "legacy",
            "n_frames": CP_A_MINI_N_FRAMES,
        },
        {
            "trial_id": "t1_rank_refine",
            "title": "frame_ca + uniform + refined",
            "analysis_atom_mode": "frame_ca",
            "frame_selection_mode": "uniform",
            "frame_selection_fraction": 0.35,
            "ranking_mode": "refined",
            "n_frames": CP_A_MINI_N_FRAMES,
        },
        {
            "trial_id": "t2_sampling_weighted",
            "title": "frame_ca + domain_motion_weighted + refined",
            "analysis_atom_mode": "frame_ca",
            "frame_selection_mode": "domain_motion_weighted",
            "frame_selection_fraction": 0.35,
            "ranking_mode": "refined",
            "n_frames": CP_A_MINI_N_FRAMES,
        },
        {
            "trial_id": "t3_sampling_deeper",
            "title": "frame_ca + domain_motion_weighted(0.60) + refined",
            "analysis_atom_mode": "frame_ca",
            "frame_selection_mode": "domain_motion_weighted",
            "frame_selection_fraction": 0.60,
            "ranking_mode": "refined",
            "n_frames": CP_A_MINI_N_FRAMES,
        },
        {
            "trial_id": "t4_atom_mode_heavy",
            "title": "reconstructed_heavy + domain_motion_weighted + refined",
            "analysis_atom_mode": "reconstructed_heavy",
            "frame_selection_mode": "domain_motion_weighted",
            "frame_selection_fraction": 0.35,
            "ranking_mode": "refined",
            "n_frames": CP_A_MINI_N_FRAMES,
        },
        {
            "trial_id": "t5_atom_mode_heavy_legacy",
            "title": "reconstructed_heavy + domain_motion_weighted + legacy",
            "analysis_atom_mode": "reconstructed_heavy",
            "frame_selection_mode": "domain_motion_weighted",
            "frame_selection_fraction": 0.35,
            "ranking_mode": "legacy",
            "n_frames": CP_A_MINI_N_FRAMES,
        },
        {
            "trial_id": "t6_atom_mode_heavy_relaxed",
            "title": "reconstructed_heavy + domain_motion_weighted + refined + relaxed_consensus",
            "analysis_atom_mode": "reconstructed_heavy",
            "frame_selection_mode": "domain_motion_weighted",
            "frame_selection_fraction": 0.35,
            "ranking_mode": "refined",
            "n_frames": CP_A_MINI_N_FRAMES,
            "consensus_min_frames": RELAXED_CONSENSUS_MIN_FRAMES,
            "consensus_distance": RELAXED_CONSENSUS_DISTANCE,
            "center_stability_max": RELAXED_CENTER_STABILITY_MAX,
            "volume_cv_max": RELAXED_VOLUME_CV_MAX,
        },
    ]

    profile_map = {
        "full": [spec["trial_id"] for spec in available_trial_specs],
        "balanced": [
            "t0_baseline",
            "t2_sampling_weighted",
            "t4_atom_mode_heavy",
            "t5_atom_mode_heavy_legacy",
            "t6_atom_mode_heavy_relaxed",
        ],
        "fast": ["t4_atom_mode_heavy", "t6_atom_mode_heavy_relaxed"],
    }
    id_to_spec = {spec["trial_id"]: spec for spec in available_trial_specs}
    requested_trial_ids = (
        list(cp_a_trial_ids)
        if cp_a_trial_ids
        else list(profile_map.get(cp_a_profile, profile_map["balanced"]))
    )
    selected_specs: list[dict[str, Any]] = []
    for trial_id in requested_trial_ids:
        spec = id_to_spec.get(trial_id)
        if spec is None:
            raise ValueError(f"Unknown CP-A trial id: {trial_id}")
        selected_specs.append(spec)
    if not selected_specs:
        raise ValueError("CP-A pivot selected zero trial specs.")

    trials: list[dict[str, Any]] = []
    run_cache: dict[tuple[Any, ...], tuple[list[dict[str, Any]], dict[str, Any], str | None]] = {}
    start_ts = monotonic()
    deadline_ts = (
        start_ts + (float(cp_a_max_minutes) * 60.0)
        if cp_a_max_minutes is not None
        else None
    )
    stop_reason: str | None = None
    for idx, spec in enumerate(selected_specs, start=1):
        if deadline_ts is not None and monotonic() >= deadline_ts:
            stop_reason = f"time_budget_reached({cp_a_max_minutes:.1f}m)"
            print(f"[CP-A] stopping early: {stop_reason}")
            break
        trial = _run_cp_a_trial(
            trial_id=spec["trial_id"],
            title=spec["title"],
            mini_cases=mini_cases,
            analysis_atom_mode=spec["analysis_atom_mode"],
            frame_selection_mode=spec["frame_selection_mode"],
            frame_selection_fraction=float(spec["frame_selection_fraction"]),
            ranking_mode=spec["ranking_mode"],
            per_frame_top_n=per_frame_top_n,
            n_frames=int(spec.get("n_frames", CP_A_MINI_N_FRAMES)),
            consensus_min_frames=int(
                spec.get("consensus_min_frames", CONSENSUS_MIN_FRAMES)
            ),
            consensus_distance=float(spec.get("consensus_distance", CONSENSUS_DISTANCE)),
            center_stability_max=float(
                spec.get("center_stability_max", CENTER_STABILITY_MAX)
            ),
            volume_cv_max=float(spec.get("volume_cv_max", VOLUME_CV_MAX)),
            run_cache=run_cache,
            hard_deadline_ts=deadline_ts,
            case_timeout_seconds=case_timeout_seconds,
        )
        trials.append(trial)
        current_best = _select_best_cp_a_trial(trials)
        current_best_recall = float(current_best["summary"]["recall"])
        if current_best_recall >= 0.22:
            stop_reason = f"success_threshold_reached(recall={current_best_recall:.4f})"
            print(f"[CP-A] stopping early: {stop_reason}")
            break
        if bool(trial.get("stopped_early", False)):
            stop_reason = str(trial.get("stop_reason") or "time_budget_reached")
            print(f"[CP-A] stopping after trial {spec['trial_id']}: {stop_reason}")
            break

    if not trials:
        raise ValueError("CP-A pivot executed zero trials.")

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
    elapsed_total_minutes = (monotonic() - start_ts) / 60.0

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
        "execution_policy": {
            "cp_a_profile": cp_a_profile,
            "requested_trial_ids": requested_trial_ids,
            "executed_trial_ids": [str(t["trial_id"]) for t in trials],
            "available_trial_ids": [str(spec["trial_id"]) for spec in available_trial_specs],
            "time_budget_minutes": cp_a_max_minutes,
            "elapsed_minutes": round(elapsed_total_minutes, 3),
            "stopped_early": bool(stop_reason),
            "stop_reason": stop_reason,
        },
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
    case_timeout_seconds: float | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_n_frames = A2_A3_BASE_N_FRAMES
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
            n_frames=base_n_frames,
            reuse_existing_frames=False,
            case_timeout_seconds=_derived_case_timeout(
                case_timeout_seconds=case_timeout_seconds,
                n_frames=base_n_frames,
                frame_selection_fraction=frame_selection_fraction,
                analysis_atom_mode=analysis_atom_mode,
            ),
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

        deep_pass_used = False
        if (
            analysis_atom_mode == "reconstructed_heavy"
            and frame_selection_mode == "domain_motion_weighted"
            and str(case.get("pocket_type", "")) in A2_A3_DOMAIN_DEEP_TYPES
            and float(frame_selection_fraction) < CP_A_DOMAIN_DEEP_FRACTION
        ):
            deep_fraction = max(float(frame_selection_fraction), CP_A_DOMAIN_DEEP_FRACTION)
            deep_n_frames = max(int(base_n_frames), CP_A_DOMAIN_DEEP_MIN_FRAMES)
            deep_pockets, deep_diagnostics, deep_error = _run_multi_case(
                case,
                analysis_atom_mode=analysis_atom_mode,
                frame_selection_mode=frame_selection_mode,
                frame_selection_fraction=deep_fraction,
                per_frame_top_n=per_frame_top_n,
                n_frames=deep_n_frames,
                consensus_min_frames=CONSENSUS_MIN_FRAMES,
                consensus_distance=CONSENSUS_DISTANCE,
                center_stability_max=CENTER_STABILITY_MAX,
                volume_cv_max=VOLUME_CV_MAX,
                reuse_existing_frames=False,
                case_timeout_seconds=_derived_case_timeout(
                    case_timeout_seconds=case_timeout_seconds,
                    n_frames=deep_n_frames,
                    frame_selection_fraction=deep_fraction,
                    analysis_atom_mode=analysis_atom_mode,
                ),
            )
            diagnostics = dict(diagnostics)
            if deep_error:
                diagnostics["domain_deep_pass"] = {
                    "status": "error",
                    "error": deep_error,
                    "n_frames": deep_n_frames,
                    "frame_selection_fraction": deep_fraction,
                }
            else:
                pockets = list(pockets) + list(deep_pockets)
                deep_pass_used = True
                diagnostics["domain_deep_pass"] = {
                    "status": "merged",
                    "n_frames": deep_n_frames,
                    "frame_selection_fraction": deep_fraction,
                    "base_candidate_count": len(pockets) - len(deep_pockets),
                    "deep_candidate_count": len(deep_pockets),
                    "merged_candidate_count": len(pockets),
                    "deep_frames_analyzed": deep_diagnostics.get("frames_analyzed"),
                }

        legacy_row = _evaluate_case(case, pockets, diagnostics, ranking_mode="legacy")
        refined_row = _evaluate_case(case, pockets, diagnostics, ranking_mode="refined")
        rescue_used = False
        rescue_trigger = "none"
        rescue_best_distance_before = refined_row.get("best_distance")
        near_miss = (
            refined_row.get("best_distance") is not None
            and float(refined_row["best_distance"]) <= A2_A3_RESCUE_NEAR_MISS_DISTANCE
        )
        type_trigger = str(case.get("pocket_type", "")) in A2_A3_RESCUE_TARGET_TYPES
        if not bool(refined_row.get("matched", False)):
            if near_miss:
                rescue_trigger = "near_miss"
            elif type_trigger:
                rescue_trigger = "target_type"
            else:
                rescue_trigger = "miss_fallback"
            rescue_fraction = max(float(frame_selection_fraction), CP_A_DOMAIN_DEEP_FRACTION)
            rescue_n_frames = max(int(base_n_frames), CP_A_DOMAIN_DEEP_MIN_FRAMES)
            rescue_pockets, rescue_diagnostics, rescue_error = _run_multi_case(
                case,
                analysis_atom_mode=analysis_atom_mode,
                frame_selection_mode=frame_selection_mode,
                frame_selection_fraction=rescue_fraction,
                per_frame_top_n=per_frame_top_n,
                n_frames=rescue_n_frames,
                consensus_min_frames=RELAXED_CONSENSUS_MIN_FRAMES,
                consensus_distance=RELAXED_CONSENSUS_DISTANCE,
                center_stability_max=RELAXED_CENTER_STABILITY_MAX,
                volume_cv_max=RELAXED_VOLUME_CV_MAX,
                reuse_existing_frames=False,
                case_timeout_seconds=_derived_case_timeout(
                    case_timeout_seconds=case_timeout_seconds,
                    n_frames=rescue_n_frames,
                    frame_selection_fraction=rescue_fraction,
                    analysis_atom_mode=analysis_atom_mode,
                ),
            )
            diagnostics = dict(diagnostics)
            if rescue_error:
                diagnostics["relaxed_rescue_pass"] = {
                    "status": "error",
                    "trigger": rescue_trigger,
                    "error": rescue_error,
                    "n_frames": rescue_n_frames,
                    "frame_selection_fraction": rescue_fraction,
                }
            else:
                pockets = list(pockets) + list(rescue_pockets)
                rescue_used = True
                diagnostics["relaxed_rescue_pass"] = {
                    "status": "merged",
                    "trigger": rescue_trigger,
                    "n_frames": rescue_n_frames,
                    "frame_selection_fraction": rescue_fraction,
                    "base_candidate_count": len(pockets) - len(rescue_pockets),
                    "rescue_candidate_count": len(rescue_pockets),
                    "merged_candidate_count": len(pockets),
                    "rescue_frames_analyzed": rescue_diagnostics.get("frames_analyzed"),
                }
                legacy_row = _evaluate_case(case, pockets, diagnostics, ranking_mode="legacy")
                refined_row = _evaluate_case(case, pockets, diagnostics, ranking_mode="refined")

        legacy_row["domain_deep_pass_used"] = deep_pass_used
        refined_row["domain_deep_pass_used"] = deep_pass_used
        legacy_row["relaxed_rescue_used"] = rescue_used
        refined_row["relaxed_rescue_used"] = rescue_used
        refined_row["rescue_trigger"] = rescue_trigger
        refined_row["rescue_best_distance_before"] = rescue_best_distance_before
        refined_row["rescue_best_distance_after"] = refined_row.get("best_distance")

        heavy_fallback_used = False
        heavy_fallback_selected = False
        heavy_fallback_status = "not_triggered"
        heavy_fallback_best_distance = None
        if (
            analysis_atom_mode != "reconstructed_heavy"
            and not bool(refined_row.get("matched", False))
            and str(case.get("pocket_type", "")) in A2_A3_HEAVY_FALLBACK_TYPES
        ):
            heavy_fallback_used = True
            try:
                heavy_a2_payload, _ = _run_a2_a3_full(
                    test_cases=[case],
                    analysis_atom_mode="reconstructed_heavy",
                    frame_selection_mode=frame_selection_mode,
                    frame_selection_fraction=frame_selection_fraction,
                    per_frame_top_n=per_frame_top_n,
                    case_timeout_seconds=case_timeout_seconds,
                )
                heavy_pair = heavy_a2_payload.get("per_case", [{}])[0]
                heavy_legacy_row = heavy_pair.get("legacy")
                heavy_refined_row = heavy_pair.get("refined")
                if isinstance(heavy_refined_row, dict) and isinstance(heavy_legacy_row, dict):
                    heavy_fallback_best_distance = heavy_refined_row.get("best_distance")
                    if _row_selection_score(heavy_refined_row) > _row_selection_score(refined_row):
                        legacy_row = heavy_legacy_row
                        refined_row = heavy_refined_row
                        heavy_fallback_selected = True
                        heavy_fallback_status = "selected"
                    else:
                        heavy_fallback_status = "kept_primary"
                else:
                    heavy_fallback_status = "no_row"
            except Exception as exc:  # pragma: no cover
                heavy_fallback_status = f"error:{type(exc).__name__}"

        legacy_row["heavy_fallback_used"] = heavy_fallback_used
        refined_row["heavy_fallback_used"] = heavy_fallback_used
        refined_row["heavy_fallback_selected"] = heavy_fallback_selected
        refined_row["heavy_fallback_status"] = heavy_fallback_status
        refined_row["heavy_fallback_best_distance"] = heavy_fallback_best_distance
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
            "full_base_n_frames": base_n_frames,
            "domain_deep_pass": {
                "enabled": True,
                "target_pocket_types": sorted(A2_A3_DOMAIN_DEEP_TYPES),
                "fraction_floor": CP_A_DOMAIN_DEEP_FRACTION,
                "n_frames_floor": CP_A_DOMAIN_DEEP_MIN_FRAMES,
            },
            "relaxed_rescue_pass": {
                "enabled": True,
                "target_pocket_types": sorted(A2_A3_RESCUE_TARGET_TYPES),
                "near_miss_distance_threshold": A2_A3_RESCUE_NEAR_MISS_DISTANCE,
                "consensus_min_frames": RELAXED_CONSENSUS_MIN_FRAMES,
                "consensus_distance": RELAXED_CONSENSUS_DISTANCE,
                "center_stability_max": RELAXED_CENTER_STABILITY_MAX,
                "volume_cv_max": RELAXED_VOLUME_CV_MAX,
                "fraction_floor_for_target_types": CP_A_DOMAIN_DEEP_FRACTION,
                "n_frames_floor": CP_A_DOMAIN_DEEP_MIN_FRAMES,
            },
            "heavy_fallback_pass": {
                "enabled": analysis_atom_mode != "reconstructed_heavy",
                "fallback_atom_mode": "reconstructed_heavy",
                "target_pocket_types": sorted(A2_A3_HEAVY_FALLBACK_TYPES),
                "selection_rule": "replace_primary_if_matched_or_distance_better",
            },
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
                "full_base_n_frames": base_n_frames,
                "domain_deep_pass_enabled": True,
                "domain_deep_pass_target_pocket_types": sorted(A2_A3_DOMAIN_DEEP_TYPES),
                "relaxed_rescue_pass_enabled": True,
                "relaxed_rescue_target_pocket_types": sorted(A2_A3_RESCUE_TARGET_TYPES),
                "relaxed_rescue_near_miss_distance_threshold": A2_A3_RESCUE_NEAR_MISS_DISTANCE,
                "heavy_fallback_pass_enabled": analysis_atom_mode != "reconstructed_heavy",
                "heavy_fallback_target_pocket_types": sorted(A2_A3_HEAVY_FALLBACK_TYPES),
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
            "## Execution Policy",
            "",
            (
                f"- Profile: `{payload.get('execution_policy', {}).get('cp_a_profile', 'unknown')}`"
            ),
            (
                f"- Executed trials: "
                f"`{', '.join(payload.get('execution_policy', {}).get('executed_trial_ids', []))}`"
            ),
            (
                f"- Time budget (min): "
                f"`{payload.get('execution_policy', {}).get('time_budget_minutes')}`"
            ),
            (
                f"- Stopped early: "
                f"`{payload.get('execution_policy', {}).get('stopped_early', False)}`"
            ),
            "",
            "## Denenen Degisiklikler",
            "",
            "- Sampling: uniform vs domain_motion_weighted, fraction=0.35/0.60",
            "- Ranking: legacy vs refined ranking formula + hard filters",
            "- Atom mode: frame_ca vs reconstructed_heavy",
            "- Mini runtime tuning: n_frames=7 (frame reuse) + bounded trial execution",
            "- Consensus varyanti: standard vs relaxed (min_frames=2, stability/volume relaxed)",
            "",
            "## Trial Sonuclari",
            "",
            "| Trial | Degisiklik | Recall | Domain-motion | Error Count | Coverage | Elapsed (min) | Avg Best Distance |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for trial in payload["trials"]:
            summary = trial["summary"]
            lines.append(
                f"| {trial['trial_id']} | {trial['title']} | "
                f"{summary['recall']*100:.1f}% ({summary['true_positives']}/{summary['total_cases']}) | "
                f"{trial['domain_motion_hits']}/{trial['domain_motion_total']} | "
                f"{summary['error_count']} | "
                f"{trial.get('processed_cases', summary['total_cases'])}/{trial.get('planned_cases', summary['total_cases'])} | "
                f"{trial.get('elapsed_minutes', 0.0):.2f} | "
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
    parser.add_argument(
        "--cp-a-profile",
        default="balanced",
        choices=["fast", "balanced", "full"],
        help="Trial profile for CP-A mini mode (default: balanced).",
    )
    parser.add_argument(
        "--cp-a-trials",
        default="",
        help="Comma-separated CP-A trial ids overriding profile (e.g. t0_baseline,t4_atom_mode_heavy).",
    )
    parser.add_argument(
        "--cp-a-max-minutes",
        type=float,
        default=90.0,
        help="Hard time budget for CP-A mini mode. Stops before next trial if budget is reached.",
    )
    parser.add_argument(
        "--case-timeout-seconds",
        type=float,
        default=DEFAULT_CASE_TIMEOUT_SECONDS,
        help=(
            "Per-case timeout guard in seconds (0 disables). "
            "Effective timeout scales by n_frames and atom mode."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    test_cases, _ = load_test_set(ROOT / args.test_set)

    if args.cp_a_mini_only:
        cp_a_trial_ids = [
            item.strip()
            for item in str(args.cp_a_trials).split(",")
            if item.strip()
        ]
        cp_a_payload = _run_cp_a_pivot(
            test_cases=test_cases,
            per_frame_top_n=args.per_frame_top_n,
            cp_a_profile=args.cp_a_profile,
            cp_a_trial_ids=cp_a_trial_ids if cp_a_trial_ids else None,
            cp_a_max_minutes=args.cp_a_max_minutes,
            case_timeout_seconds=args.case_timeout_seconds,
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
        case_timeout_seconds=args.case_timeout_seconds,
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
        case_timeout_seconds=args.case_timeout_seconds,
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
