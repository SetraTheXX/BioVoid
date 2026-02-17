#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
TOLERANCE = 8.0
TOP_N = 20
DRUGGABLE_ONLY = True
BASE_VOLUME_MIN_RATIO = 0.5
BASE_VOLUME_MAX_RATIO = 2.0


@dataclass(frozen=True)
class MatchConfig:
    name: str
    min_ratio: float
    max_ratio: float


def _valid_center(center: Any) -> bool:
    return (
        isinstance(center, list)
        and len(center) == 3
        and all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in center)
    )


def _valid_volume(volume: Any) -> bool:
    return isinstance(volume, (int, float)) and math.isfinite(float(volume)) and float(volume) > 0.0


def _volume_ratio(fp_volume: Any, bv_volume: Any) -> float | None:
    if not _valid_volume(fp_volume) or not _valid_volume(bv_volume):
        return None
    return float(fp_volume) / float(bv_volume)


def _is_ratio_match(ratio: float | None, min_ratio: float, max_ratio: float) -> bool:
    if ratio is None:
        return False
    return min_ratio <= ratio <= max_ratio


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _filter_valid_pockets(row: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in row.get("pockets", []):
        if not isinstance(p, dict):
            continue
        if _valid_center(p.get("center")):
            out.append(p)
    return out


def _max_bipartite_matching_size(fp_count: int, bv_count: int, edges: dict[int, list[int]]) -> int:
    match_to_fp: dict[int, int] = {}

    def _dfs(fp_idx: int, visited: set[int]) -> bool:
        for bv_idx in edges.get(fp_idx, []):
            if bv_idx in visited:
                continue
            visited.add(bv_idx)
            if bv_idx not in match_to_fp or _dfs(match_to_fp[bv_idx], visited):
                match_to_fp[bv_idx] = fp_idx
                return True
        return False

    matched = 0
    for fp_idx in range(fp_count):
        if _dfs(fp_idx, set()):
            matched += 1
    return matched


def _greedy_match(
    fp_pockets: list[dict[str, Any]],
    bv_pockets: list[dict[str, Any]],
    tolerance: float,
    min_ratio: float | None = None,
    max_ratio: float | None = None,
) -> int:
    used_bv: set[int] = set()
    matched = 0
    for fp in fp_pockets:
        fp_center = fp["center"]
        best_idx: int | None = None
        best_dist = float("inf")
        for idx, bv in enumerate(bv_pockets):
            if idx in used_bv:
                continue
            dist = math.dist(fp_center, bv["center"])
            if dist > tolerance:
                continue
            if min_ratio is not None and max_ratio is not None:
                ratio = _volume_ratio(fp.get("volume"), bv.get("volume"))
                if not _is_ratio_match(ratio, min_ratio, max_ratio):
                    continue
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
        if best_idx is not None:
            used_bv.add(best_idx)
            matched += 1
    return matched


def _pairwise_geometry(fp_pockets: list[dict[str, Any]], bv_pockets: list[dict[str, Any]]) -> list[dict[str, float | int | None]]:
    rows: list[dict[str, float | int | None]] = []
    for i, fp in enumerate(fp_pockets):
        for j, bv in enumerate(bv_pockets):
            dist = math.dist(fp["center"], bv["center"])
            ratio = _volume_ratio(fp.get("volume"), bv.get("volume"))
            rows.append(
                {
                    "fp_index": i,
                    "bv_index": j,
                    "distance": dist,
                    "volume_ratio": ratio,
                }
            )
    return rows


def _build_edges(
    pairs: list[dict[str, float | int | None]],
    tolerance: float,
    min_ratio: float | None = None,
    max_ratio: float | None = None,
) -> dict[int, list[int]]:
    edges: dict[int, list[int]] = {}
    for pair in pairs:
        dist = float(pair["distance"])
        if dist > tolerance:
            continue
        if min_ratio is not None and max_ratio is not None:
            ratio = pair["volume_ratio"]
            if not _is_ratio_match(ratio if isinstance(ratio, (int, float)) else None, min_ratio, max_ratio):
                continue
        fp_idx = int(pair["fp_index"])
        bv_idx = int(pair["bv_index"])
        edges.setdefault(fp_idx, []).append(bv_idx)
    return edges


def _analyze() -> dict[str, Any]:
    fp_path = ROOT / "data/benchmark/fpocket_results/fpocket_batch_summary.json"
    bv_path = ROOT / "data/benchmark/biovoid_results.json"
    fp = _load_json(fp_path)
    bv = _load_json(bv_path)

    fp_by_id = {
        str(r.get("pdb_id", "")).upper(): r
        for r in fp.get("results", [])
        if isinstance(r, dict) and str(r.get("status", "")) == "ok"
    }
    bv_by_id = {
        str(r.get("pdb_id", "")).upper(): r
        for r in bv.get("results", [])
        if isinstance(r, dict)
    }
    common_ids = sorted(set(fp_by_id) & set(bv_by_id))

    per_protein: list[dict[str, Any]] = []
    ratio_samples: list[float] = []
    nearest_ratio_samples: list[float] = []
    ratio_reason_counts = {"low_ratio": 0, "high_ratio": 0, "missing_volume": 0}
    fp_total = 0
    bv_total = 0
    center_only_greedy_total = 0
    official_volume_greedy_total = 0
    center_max_total = 0
    center_volume_base_total = 0
    fp_with_any_center_candidate = 0

    for pdb_id in common_ids:
        fp_pockets = _filter_valid_pockets(fp_by_id[pdb_id])[:TOP_N]
        bv_pockets = _filter_valid_pockets(bv_by_id[pdb_id])[:TOP_N]
        fp_total += len(fp_pockets)
        bv_total += len(bv_pockets)

        pairs = _pairwise_geometry(fp_pockets, bv_pockets)
        center_edges = _build_edges(pairs, TOLERANCE)
        center_volume_base_edges = _build_edges(
            pairs,
            TOLERANCE,
            BASE_VOLUME_MIN_RATIO,
            BASE_VOLUME_MAX_RATIO,
        )
        center_max = _max_bipartite_matching_size(len(fp_pockets), len(bv_pockets), center_edges)
        center_volume_base_max = _max_bipartite_matching_size(
            len(fp_pockets),
            len(bv_pockets),
            center_volume_base_edges,
        )
        center_only_greedy = _greedy_match(fp_pockets, bv_pockets, TOLERANCE)
        official_volume_greedy = _greedy_match(
            fp_pockets,
            bv_pockets,
            TOLERANCE,
            BASE_VOLUME_MIN_RATIO,
            BASE_VOLUME_MAX_RATIO,
        )
        center_only_greedy_total += center_only_greedy
        official_volume_greedy_total += official_volume_greedy
        center_max_total += center_max
        center_volume_base_total += center_volume_base_max

        distance_fail = 0
        volume_fail = 0
        volume_pass = 0
        ratio_low = 0
        ratio_high = 0
        missing_volume = 0

        for fp_idx, fp_pocket in enumerate(fp_pockets):
            candidates = [
                p for p in pairs if int(p["fp_index"]) == fp_idx and float(p["distance"]) <= TOLERANCE
            ]
            if not candidates:
                distance_fail += 1
                continue

            fp_with_any_center_candidate += 1
            candidates_sorted = sorted(candidates, key=lambda p: float(p["distance"]))
            nearest = candidates_sorted[0]
            nearest_ratio = nearest["volume_ratio"]
            if isinstance(nearest_ratio, (int, float)):
                nearest_ratio_samples.append(float(nearest_ratio))

            pass_any = False
            local_low = 0
            local_high = 0
            local_missing = 0
            for cand in candidates_sorted:
                ratio = cand["volume_ratio"]
                if isinstance(ratio, (int, float)):
                    ratio_val = float(ratio)
                    ratio_samples.append(ratio_val)
                    if _is_ratio_match(ratio_val, BASE_VOLUME_MIN_RATIO, BASE_VOLUME_MAX_RATIO):
                        pass_any = True
                    elif ratio_val < BASE_VOLUME_MIN_RATIO:
                        local_low += 1
                    else:
                        local_high += 1
                else:
                    local_missing += 1

            if pass_any:
                volume_pass += 1
            else:
                volume_fail += 1
                if local_low > 0 and local_high == 0:
                    ratio_low += 1
                    ratio_reason_counts["low_ratio"] += 1
                elif local_high > 0 and local_low == 0:
                    ratio_high += 1
                    ratio_reason_counts["high_ratio"] += 1
                elif local_low == 0 and local_high == 0:
                    missing_volume += 1
                    ratio_reason_counts["missing_volume"] += 1
                else:
                    if local_low >= local_high:
                        ratio_low += 1
                        ratio_reason_counts["low_ratio"] += 1
                    else:
                        ratio_high += 1
                        ratio_reason_counts["high_ratio"] += 1

        per_protein.append(
            {
                "pdb_id": pdb_id,
                "fpocket_valid": len(fp_pockets),
                "biovoid_valid": len(bv_pockets),
                "center_only_greedy_match": center_only_greedy,
                "official_center_volume_greedy_match": official_volume_greedy,
                "center_match_upper_bound": center_max,
                "center_volume_match_base": center_volume_base_max,
                "distance_fail": distance_fail,
                "volume_fail": volume_fail,
                "volume_pass": volume_pass,
                "ratio_low_fail": ratio_low,
                "ratio_high_fail": ratio_high,
                "ratio_missing_fail": missing_volume,
                "transition_drop_upper_bound": max(center_max - center_volume_base_max, 0),
            }
        )

    per_protein_sorted = sorted(
        per_protein,
        key=lambda r: (
            -int(r["transition_drop_upper_bound"]),
            -int(r["volume_fail"]),
            str(r["pdb_id"]),
        ),
    )

    denom = fp_total + bv_total
    center_only_overlap_greedy = (2 * center_only_greedy_total / denom) if denom > 0 else 0.0
    official_overlap = (2 * official_volume_greedy_total / denom) if denom > 0 else 0.0
    center_upper_overlap = (2 * center_max_total / denom) if denom > 0 else 0.0
    center_volume_base_overlap = (2 * center_volume_base_total / denom) if denom > 0 else 0.0

    # Pilot pool: proteins with measurable center signal and volume-gate drop.
    pilot_pool = [
        r for r in per_protein if int(r["transition_drop_upper_bound"]) > 0 and int(r["center_match_upper_bound"]) > 0
    ]
    pilot_ranked = sorted(
        pilot_pool,
        key=lambda r: (
            int(r["official_center_volume_greedy_match"]) == 0,
            -int(r["transition_drop_upper_bound"]),
            -int(r["official_center_volume_greedy_match"]),
            -int(r["center_match_upper_bound"]),
            str(r["pdb_id"]),
        ),
    )
    pilot_set = pilot_ranked[:25] if len(pilot_ranked) >= 25 else per_protein_sorted[:25]
    pilot_ids = {str(r["pdb_id"]) for r in pilot_set}

    configs = [
        MatchConfig("base_ratio_0.50_2.00", 0.50, 2.00),
        MatchConfig("calib_ratio_0.40_2.50", 0.40, 2.50),
        MatchConfig("calib_ratio_0.33_3.00", 0.33, 3.00),
        MatchConfig("calib_ratio_0.25_4.00", 0.25, 4.00),
    ]

    def _eval_config(config: MatchConfig, only_ids: set[str] | None = None) -> dict[str, Any]:
        total_fp = 0
        total_bv = 0
        matched = 0
        rows: list[dict[str, Any]] = []
        for row in per_protein:
            pdb_id = str(row["pdb_id"])
            if only_ids is not None and pdb_id not in only_ids:
                continue

            fp_pockets = _filter_valid_pockets(fp_by_id[pdb_id])[:TOP_N]
            bv_pockets = _filter_valid_pockets(bv_by_id[pdb_id])[:TOP_N]
            pairs = _pairwise_geometry(fp_pockets, bv_pockets)
            edges = _build_edges(pairs, TOLERANCE, config.min_ratio, config.max_ratio)
            m = _max_bipartite_matching_size(len(fp_pockets), len(bv_pockets), edges)

            total_fp += len(fp_pockets)
            total_bv += len(bv_pockets)
            matched += m
            rows.append(
                {
                    "pdb_id": pdb_id,
                    "fpocket_valid": len(fp_pockets),
                    "biovoid_valid": len(bv_pockets),
                    "matched": m,
                    "overlap": (2 * m / (len(fp_pockets) + len(bv_pockets)))
                    if (len(fp_pockets) + len(bv_pockets)) > 0
                    else 0.0,
                }
            )
        overlap = (2 * matched / (total_fp + total_bv)) if (total_fp + total_bv) > 0 else 0.0
        return {
            "config": config.name,
            "min_ratio": config.min_ratio,
            "max_ratio": config.max_ratio,
            "matched": matched,
            "fpocket_total": total_fp,
            "biovoid_total": total_bv,
            "overlap": overlap,
            "per_protein": rows,
        }

    pilot_results = [_eval_config(cfg, pilot_ids) for cfg in configs]
    full_results = [_eval_config(cfg, None) for cfg in configs]
    best_pilot = max(pilot_results, key=lambda r: float(r["overlap"]))
    best_full = max(full_results, key=lambda r: float(r["overlap"]))

    nearest_ratio_sorted = sorted(nearest_ratio_samples)
    ratio_sorted = sorted(ratio_samples)

    def _percentile(sorted_values: list[float], p: float) -> float | None:
        if not sorted_values:
            return None
        idx = int(round((len(sorted_values) - 1) * p))
        return float(sorted_values[max(0, min(len(sorted_values) - 1, idx))])

    return {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "canonical_lock": {
                "tolerance_angstrom": TOLERANCE,
                "top_n": TOP_N,
                "druggable_only": DRUGGABLE_ONLY,
            },
            "inputs": {
                "fpocket_summary": str(fp_path.relative_to(ROOT).as_posix()),
                "biovoid_results": str(bv_path.relative_to(ROOT).as_posix()),
            },
        },
        "global": {
            "common_proteins": len(common_ids),
            "fpocket_valid_total": fp_total,
            "biovoid_valid_total": bv_total,
            "official_overlap_center_volume_greedy": official_overlap,
            "center_only_overlap_greedy": center_only_overlap_greedy,
            "center_overlap_upper_bound": center_upper_overlap,
            "center_plus_volume_overlap_base_ratio": center_volume_base_overlap,
            "gate_target_overlap": 0.40,
            "is_gate_target_reachable_under_center_upper_bound": center_upper_overlap >= 0.40,
            "fp_with_any_center_candidate": fp_with_any_center_candidate,
            "distance_only_candidate_rate": (fp_with_any_center_candidate / fp_total) if fp_total > 0 else 0.0,
        },
        "ratio_statistics": {
            "all_center_candidate_pairs_count": len(ratio_samples),
            "nearest_center_pair_count": len(nearest_ratio_samples),
            "nearest_ratio_p10": _percentile(nearest_ratio_sorted, 0.10),
            "nearest_ratio_p50": _percentile(nearest_ratio_sorted, 0.50),
            "nearest_ratio_p90": _percentile(nearest_ratio_sorted, 0.90),
            "all_ratio_p10": _percentile(ratio_sorted, 0.10),
            "all_ratio_p50": _percentile(ratio_sorted, 0.50),
            "all_ratio_p90": _percentile(ratio_sorted, 0.90),
            "base_ratio_window": [BASE_VOLUME_MIN_RATIO, BASE_VOLUME_MAX_RATIO],
            "volume_fail_reason_counts": ratio_reason_counts,
        },
        "pilot": {
            "selection_rule": "top25_transition_drop_prioritizing_nonzero_official_matches",
            "protein_ids": sorted(pilot_ids),
            "results": pilot_results,
            "best_config": {
                "config": best_pilot["config"],
                "overlap": best_pilot["overlap"],
            },
        },
        "full": {
            "results": full_results,
            "best_config": {
                "config": best_full["config"],
                "overlap": best_full["overlap"],
            },
        },
        "per_protein_top_transition_drop": per_protein_sorted[:30],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    analysis = _analyze()

    metric_audit = {
        "metadata": analysis["metadata"],
        "global": analysis["global"],
        "ratio_statistics": analysis["ratio_statistics"],
        "top_transition_drop": analysis["per_protein_top_transition_drop"],
    }
    diagnostics = {
        "metadata": analysis["metadata"],
        "global": analysis["global"],
        "ratio_statistics": analysis["ratio_statistics"],
        "top_transition_drop": analysis["per_protein_top_transition_drop"],
    }
    pilot = {
        "metadata": analysis["metadata"],
        "pilot": analysis["pilot"],
        "baseline_reference": {
            "center_plus_volume_overlap_base_ratio": analysis["global"]["center_plus_volume_overlap_base_ratio"],
            "official_overlap_center_volume_greedy": analysis["global"]["official_overlap_center_volume_greedy"],
            "center_only_overlap_greedy": analysis["global"]["center_only_overlap_greedy"],
        },
    }
    v3 = {
        "metadata": analysis["metadata"],
        "global": analysis["global"],
        "ratio_statistics": analysis["ratio_statistics"],
        "pilot": analysis["pilot"],
        "full": analysis["full"],
        "top_transition_drop": analysis["per_protein_top_transition_drop"],
    }

    _write_json(ROOT / "data/benchmark/recovery_v2_metric_validity_audit.json", metric_audit)
    _write_json(ROOT / "data/validation/recovery_v2_overlap_diagnostics.json", diagnostics)
    _write_json(ROOT / "data/benchmark/recovery_v2_overlap_pilot.json", pilot)
    _write_json(ROOT / "data/benchmark/fpocket_benchmark_v3.json", v3)

    print("[OK] Wrote data/benchmark/recovery_v2_metric_validity_audit.json")
    print("[OK] Wrote data/validation/recovery_v2_overlap_diagnostics.json")
    print("[OK] Wrote data/benchmark/recovery_v2_overlap_pilot.json")
    print("[OK] Wrote data/benchmark/fpocket_benchmark_v3.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
