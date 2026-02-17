#!/usr/bin/env python3
from __future__ import annotations

from bisect import bisect_left
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


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
    volume_representation: str = "raw"


def _percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    idx = int(round((len(sorted_values) - 1) * p))
    return float(sorted_values[max(0, min(len(sorted_values) - 1, idx))])


class QuantileVolumeCalibrator:
    """Maps fpocket volume values onto BioVoid volume quantiles."""

    def __init__(self, fp_samples: list[float], bv_samples: list[float]) -> None:
        self._fp = sorted(v for v in fp_samples if _valid_volume(v))
        self._bv = sorted(v for v in bv_samples if _valid_volume(v))
        self.is_ready = len(self._fp) >= 10 and len(self._bv) >= 10

    def transform(self, fp_volume: float) -> float:
        if not self.is_ready or not _valid_volume(fp_volume):
            return float(fp_volume)
        if len(self._fp) == 1 or len(self._bv) == 1:
            return float(self._bv[0]) if self._bv else float(fp_volume)
        rank_idx = bisect_left(self._fp, float(fp_volume))
        rank = rank_idx / float(len(self._fp) - 1)
        mapped_idx = int(round(rank * (len(self._bv) - 1)))
        mapped_idx = max(0, min(len(self._bv) - 1, mapped_idx))
        return float(self._bv[mapped_idx])

    def summary(self) -> dict[str, Any]:
        return {
            "is_ready": self.is_ready,
            "fp_sample_count": len(self._fp),
            "bv_sample_count": len(self._bv),
            "fp_p10": _percentile(self._fp, 0.10),
            "fp_p50": _percentile(self._fp, 0.50),
            "fp_p90": _percentile(self._fp, 0.90),
            "bv_p10": _percentile(self._bv, 0.10),
            "bv_p50": _percentile(self._bv, 0.50),
            "bv_p90": _percentile(self._bv, 0.90),
        }


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


def _pairwise_geometry(fp_pockets: list[dict[str, Any]], bv_pockets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, fp in enumerate(fp_pockets):
        for j, bv in enumerate(bv_pockets):
            dist = math.dist(fp["center"], bv["center"])
            fp_volume = fp.get("volume")
            bv_volume = bv.get("volume")
            ratio = _volume_ratio(fp_volume, bv_volume)
            rows.append(
                {
                    "fp_index": i,
                    "bv_index": j,
                    "distance": dist,
                    "fp_volume": fp_volume,
                    "bv_volume": bv_volume,
                    "volume_ratio": ratio,
                }
            )
    return rows


def _build_edges(
    pairs: list[dict[str, Any]],
    tolerance: float,
    min_ratio: float | None = None,
    max_ratio: float | None = None,
    fp_volume_transform: Callable[[float], float] | None = None,
) -> dict[int, list[int]]:
    edges: dict[int, list[int]] = {}
    for pair in pairs:
        dist = float(pair["distance"])
        if dist > tolerance:
            continue
        if min_ratio is not None and max_ratio is not None:
            ratio: float | None
            if fp_volume_transform is None:
                raw_ratio = pair["volume_ratio"]
                ratio = float(raw_ratio) if isinstance(raw_ratio, (int, float)) else None
            else:
                fp_vol = pair.get("fp_volume")
                bv_vol = pair.get("bv_volume")
                if _valid_volume(fp_vol) and _valid_volume(bv_vol):
                    mapped_fp = fp_volume_transform(float(fp_vol))
                    ratio = _volume_ratio(mapped_fp, float(bv_vol))
                else:
                    ratio = None
            if not _is_ratio_match(ratio, min_ratio, max_ratio):
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
    nearest_fp_volume_samples: list[float] = []
    nearest_bv_volume_samples: list[float] = []
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
            nearest_fp_vol = nearest.get("fp_volume")
            nearest_bv_vol = nearest.get("bv_volume")
            if _valid_volume(nearest_fp_vol) and _valid_volume(nearest_bv_vol):
                nearest_fp_volume_samples.append(float(nearest_fp_vol))
                nearest_bv_volume_samples.append(float(nearest_bv_vol))

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
    option1_calibrator = QuantileVolumeCalibrator(nearest_fp_volume_samples, nearest_bv_volume_samples)

    configs = [
        MatchConfig("base_ratio_0.50_2.00", 0.50, 2.00, "raw"),
        MatchConfig("option1_quantile_calibrated_ratio_0.50_2.00", 0.50, 2.00, "quantile_calibrated"),
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
            transform = (
                option1_calibrator.transform
                if config.volume_representation == "quantile_calibrated" and option1_calibrator.is_ready
                else None
            )
            edges = _build_edges(
                pairs,
                TOLERANCE,
                config.min_ratio,
                config.max_ratio,
                fp_volume_transform=transform,
            )
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
            "volume_representation": config.volume_representation,
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
    cp_b_candidate_ids: list[str] = []
    cp_b_path = ROOT / "data/benchmark/recovery_v2_overlap_cp_b_candidates.json"
    if cp_b_path.exists():
        cp_b_payload = _load_json(cp_b_path)
        cp_b_candidate_ids = [
            str(row.get("pdb_id", "")).upper()
            for row in cp_b_payload.get("top10_candidates", [])
            if isinstance(row, dict)
        ]
    if not cp_b_candidate_ids:
        cp_b_candidate_ids = ["5R35", "1GQV", "9HDW"]

    def _cfg_by_name(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
        for row in rows:
            if str(row.get("config")) == name:
                return row
        raise KeyError(name)

    base_pilot_cfg = _cfg_by_name(pilot_results, "base_ratio_0.50_2.00")
    option1_pilot_cfg = _cfg_by_name(pilot_results, "option1_quantile_calibrated_ratio_0.50_2.00")
    base_full_cfg = _cfg_by_name(full_results, "base_ratio_0.50_2.00")
    option1_full_cfg = _cfg_by_name(full_results, "option1_quantile_calibrated_ratio_0.50_2.00")
    candidate_id_set = set(cp_b_candidate_ids)
    cp_b_candidate_set_results = [_eval_config(cfg, candidate_id_set) for cfg in configs]
    base_candidate_cfg = _cfg_by_name(cp_b_candidate_set_results, "base_ratio_0.50_2.00")
    option1_candidate_cfg = _cfg_by_name(
        cp_b_candidate_set_results,
        "option1_quantile_calibrated_ratio_0.50_2.00",
    )

    def _per_protein_map(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(row.get("pdb_id", "")).upper(): row
            for row in cfg.get("per_protein", [])
            if isinstance(row, dict)
        }

    base_pilot_map = _per_protein_map(base_pilot_cfg)
    option1_pilot_map = _per_protein_map(option1_pilot_cfg)
    base_full_map = _per_protein_map(base_full_cfg)
    option1_full_map = _per_protein_map(option1_full_cfg)
    base_candidate_map = _per_protein_map(base_candidate_cfg)
    option1_candidate_map = _per_protein_map(option1_candidate_cfg)

    candidate_impact_rows: list[dict[str, Any]] = []
    for pdb_id in cp_b_candidate_ids:
        bp = base_pilot_map.get(pdb_id)
        op = option1_pilot_map.get(pdb_id)
        bf = base_full_map.get(pdb_id)
        of = option1_full_map.get(pdb_id)
        bc = base_candidate_map.get(pdb_id)
        oc = option1_candidate_map.get(pdb_id)
        if not bf or not of or not bc or not oc:
            continue
        candidate_impact_rows.append(
            {
                "pdb_id": pdb_id,
                "candidate_set_base_overlap": float(bc["overlap"]),
                "candidate_set_option1_overlap": float(oc["overlap"]),
                "candidate_set_delta_overlap": float(oc["overlap"]) - float(bc["overlap"]),
                "candidate_set_base_matched": int(bc["matched"]),
                "candidate_set_option1_matched": int(oc["matched"]),
                "candidate_set_delta_matched": int(oc["matched"]) - int(bc["matched"]),
                "pilot_top25_base_overlap": float(bp["overlap"]) if bp else None,
                "pilot_top25_option1_overlap": float(op["overlap"]) if op else None,
                "pilot_top25_delta_overlap": (float(op["overlap"]) - float(bp["overlap"])) if (bp and op) else None,
                "pilot_top25_base_matched": int(bp["matched"]) if bp else None,
                "pilot_top25_option1_matched": int(op["matched"]) if op else None,
                "pilot_top25_delta_matched": (int(op["matched"]) - int(bp["matched"])) if (bp and op) else None,
                "full_base_overlap": float(bf["overlap"]),
                "full_option1_overlap": float(of["overlap"]),
                "full_delta_overlap": float(of["overlap"]) - float(bf["overlap"]),
                "full_base_matched": int(bf["matched"]),
                "full_option1_matched": int(of["matched"]),
                "full_delta_matched": int(of["matched"]) - int(bf["matched"]),
            }
        )

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
        "option1_quantile_calibration": option1_calibrator.summary(),
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
        "cp_b_candidate_impact": {
            "candidate_ids": cp_b_candidate_ids,
            "focus_ids": ["5R35", "1GQV", "9HDW"],
            "pilot_top25_base_overlap": float(base_pilot_cfg["overlap"]),
            "pilot_top25_option1_overlap": float(option1_pilot_cfg["overlap"]),
            "pilot_top25_delta_overlap_option1_vs_base": float(option1_pilot_cfg["overlap"])
            - float(base_pilot_cfg["overlap"]),
            "pilot_top25_base_matched": int(base_pilot_cfg["matched"]),
            "pilot_top25_option1_matched": int(option1_pilot_cfg["matched"]),
            "pilot_top25_delta_matched_option1_vs_base": int(option1_pilot_cfg["matched"])
            - int(base_pilot_cfg["matched"]),
            "candidate_set_base_overlap": float(base_candidate_cfg["overlap"]),
            "candidate_set_option1_overlap": float(option1_candidate_cfg["overlap"]),
            "candidate_set_delta_overlap_option1_vs_base": float(option1_candidate_cfg["overlap"])
            - float(base_candidate_cfg["overlap"]),
            "candidate_set_base_matched": int(base_candidate_cfg["matched"]),
            "candidate_set_option1_matched": int(option1_candidate_cfg["matched"]),
            "candidate_set_delta_matched_option1_vs_base": int(option1_candidate_cfg["matched"])
            - int(base_candidate_cfg["matched"]),
            "full_base_overlap": float(base_full_cfg["overlap"]),
            "full_option1_overlap": float(option1_full_cfg["overlap"]),
            "full_delta_overlap_option1_vs_base": float(option1_full_cfg["overlap"])
            - float(base_full_cfg["overlap"]),
            "full_base_matched": int(base_full_cfg["matched"]),
            "full_option1_matched": int(option1_full_cfg["matched"]),
            "full_delta_matched_option1_vs_base": int(option1_full_cfg["matched"])
            - int(base_full_cfg["matched"]),
            "candidate_set_results": cp_b_candidate_set_results,
            "per_candidate": candidate_impact_rows,
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
        "option1_quantile_calibration": analysis["option1_quantile_calibration"],
        "cp_b_candidate_impact": analysis["cp_b_candidate_impact"],
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
        "option1_quantile_calibration": analysis["option1_quantile_calibration"],
        "cp_b_candidate_impact": analysis["cp_b_candidate_impact"],
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
