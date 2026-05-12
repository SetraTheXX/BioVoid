"""
Bio-Void Hunter: Multi-frame Aggregation & Persistence
=======================================================

Consensus-based aggregation over NMA frame ensembles plus
temporal persistence tracking for pocket dynamics.

Features:
- Analyze all generated NMA frames
- Aggregate recurring pockets across frames
- Enforce minimum frame support for consensus
- Report center/volume stability metrics
- Track pocket opening dynamics (persistence, flicker, streaks)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .cavities import find_cavities
from .geometry import extract_atom_coords
from .scoring import rank_pockets


@dataclass(frozen=True)
class ConsensusConfig:
    """Configuration for multi-frame consensus aggregation."""

    profile: str = "default"
    per_frame_top_n: int = 50
    min_support_frames: int = 2
    cluster_distance: float = 6.0
    center_stability_max: float = 4.0
    volume_cv_max: float = 0.35


def list_frame_files(frames_dir: str | Path) -> list[Path]:
    """Return sorted NMA frame files from a directory."""
    root = Path(frames_dir)
    if not root.exists() or not root.is_dir():
        return []
    return sorted(root.glob("frame_*.pdb"))


def analyze_structure_file(
    pdb_file: str | Path,
    profile: str = "default",
) -> list[dict[str, Any]]:
    """
    Run cavity + scoring pipeline on a single structure file.

    Returns ranked pocket dictionaries.
    """
    pdb_path = str(pdb_file)
    cavities = find_cavities(
        pdb_path,
        merge=True,
        hydrophobic=True,
        atom_type="heavy",
    )

    for i, cavity in enumerate(cavities):
        cavity["id"] = i

    atom_coords = extract_atom_coords(pdb_path, atom_type="heavy")
    ranked = rank_pockets(cavities, atom_coords, profile=profile, top_n=None)
    return ranked


def _safe_center(pocket: dict[str, Any]) -> np.ndarray | None:
    """Parse a pocket center as finite float vector."""
    center = pocket.get("center")
    if center is None:
        return None
    arr = np.asarray(center, dtype=float)
    if arr.shape != (3,):
        return None
    if not np.all(np.isfinite(arr)):
        return None
    return arr


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert any numeric-like value to finite float."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(parsed):
        return default
    return parsed


def aggregate_consensus_pockets(
    per_frame_pockets: list[list[dict[str, Any]]],
    frame_labels: list[str],
    config: ConsensusConfig,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Aggregate frame pockets into consensus pockets.

    Clustering is center-distance based. A consensus pocket must appear
    in at least ``config.min_support_frames`` distinct frames.
    """
    if not per_frame_pockets or not frame_labels:
        return [], {
            "clusters_total": 0,
            "consensus_clusters": 0,
            "total_frames": 0,
            "min_support_frames": config.min_support_frames,
        }

    observations: list[dict[str, Any]] = []
    for frame_index, pockets in enumerate(per_frame_pockets):
        if frame_index >= len(frame_labels):
            break
        frame_label = frame_labels[frame_index]
        for pocket in pockets[: config.per_frame_top_n]:
            center = _safe_center(pocket)
            if center is None:
                continue
            observations.append(
                {
                    "frame_label": frame_label,
                    "center": center,
                    "volume": _safe_float(pocket.get("volume"), default=0.0),
                    "bio_score": _safe_float(pocket.get("bio_score"), default=0.0),
                    "pocket": pocket,
                }
            )

    if not observations:
        return [], {
            "clusters_total": 0,
            "consensus_clusters": 0,
            "total_frames": len(frame_labels),
            "min_support_frames": config.min_support_frames,
        }

    clusters: list[dict[str, Any]] = []
    for obs in observations:
        best_idx: int | None = None
        best_dist = float("inf")
        for idx, cluster in enumerate(clusters):
            dist = float(np.linalg.norm(obs["center"] - cluster["center_mean"]))
            if dist <= config.cluster_distance and dist < best_dist:
                best_dist = dist
                best_idx = idx

        if best_idx is None:
            clusters.append(
                {
                    "observations": [obs],
                    "frame_labels": {obs["frame_label"]},
                    "center_sum": obs["center"].copy(),
                    "center_mean": obs["center"].copy(),
                }
            )
            continue

        cluster = clusters[best_idx]
        cluster["observations"].append(obs)
        cluster["frame_labels"].add(obs["frame_label"])
        cluster["center_sum"] += obs["center"]
        cluster["center_mean"] = cluster["center_sum"] / max(1, len(cluster["observations"]))

    total_frames = len(frame_labels)
    consensus_pockets: list[dict[str, Any]] = []

    for cluster in clusters:
        support_frames = len(cluster["frame_labels"])
        if support_frames < config.min_support_frames:
            continue

        obs = cluster["observations"]
        centers = np.stack([o["center"] for o in obs], axis=0)
        center_mean = centers.mean(axis=0)
        center_offsets = np.linalg.norm(centers - center_mean, axis=1)
        center_stability = float(center_offsets.mean())

        volumes = np.asarray([o["volume"] for o in obs], dtype=float)
        volume_mean = float(volumes.mean()) if len(volumes) else 0.0
        volume_std = float(volumes.std(ddof=0)) if len(volumes) else 0.0
        volume_cv = volume_std / volume_mean if volume_mean > 1e-8 else float("inf")

        bio_scores = np.asarray([o["bio_score"] for o in obs], dtype=float)
        avg_bio_score = float(bio_scores.mean()) if len(bio_scores) else 0.0

        support_ratio = support_frames / max(1, total_frames)
        center_score = max(
            0.0,
            1.0 - (center_stability / max(config.center_stability_max, 1e-8)),
        )
        volume_score = max(
            0.0,
            1.0 - (volume_cv / max(config.volume_cv_max, 1e-8)),
        )
        stability_score = 0.5 * center_score + 0.5 * volume_score
        consensus_score = round(
            0.65 * avg_bio_score + 0.25 * support_ratio + 0.10 * stability_score,
            4,
        )

        representative = max(obs, key=lambda x: x["bio_score"])["pocket"].copy()
        representative["center"] = center_mean
        representative["volume"] = volume_mean
        representative["druggable"] = any(bool(o["pocket"].get("druggable", False)) for o in obs)
        representative["consensus_support_frames"] = support_frames
        representative["consensus_support_ratio"] = round(support_ratio, 4)
        representative["consensus_center_stability"] = round(center_stability, 4)
        representative["consensus_volume_mean"] = round(volume_mean, 4)
        representative["consensus_volume_std"] = round(volume_std, 4)
        representative["consensus_volume_cv"] = round(volume_cv, 4)
        representative["consensus_center_stable"] = center_stability <= config.center_stability_max
        representative["consensus_volume_stable"] = volume_cv <= config.volume_cv_max
        representative["consensus_score"] = consensus_score
        representative["frame_hits"] = sorted(cluster["frame_labels"])
        consensus_pockets.append(representative)

    consensus_pockets.sort(
        key=lambda p: (
            _safe_float(p.get("consensus_score"), 0.0),
            _safe_float(p.get("bio_score"), 0.0),
            _safe_float(p.get("consensus_support_frames"), 0.0),
        ),
        reverse=True,
    )
    for rank, pocket in enumerate(consensus_pockets, start=1):
        pocket["rank"] = rank
        pocket["id"] = rank - 1

    support_values = [
        _safe_float(p.get("consensus_support_frames"), 0.0) for p in consensus_pockets
    ]
    center_values = [
        _safe_float(p.get("consensus_center_stability"), 0.0) for p in consensus_pockets
    ]
    volume_values = [_safe_float(p.get("consensus_volume_cv"), 0.0) for p in consensus_pockets]

    stats = {
        "clusters_total": len(clusters),
        "consensus_clusters": len(consensus_pockets),
        "total_frames": total_frames,
        "min_support_frames": config.min_support_frames,
        "avg_support_frames": round(float(np.mean(support_values)), 3) if support_values else 0.0,
        "avg_center_stability": round(float(np.mean(center_values)), 3) if center_values else 0.0,
        "avg_volume_cv": round(float(np.mean(volume_values)), 3) if volume_values else 0.0,
    }
    return consensus_pockets, stats


def run_multiframe_consensus(
    frames_dir: str | Path,
    config: ConsensusConfig,
    frame_mapper=None,
    frame_files_override: list[Path] | None = None,
) -> dict[str, Any]:
    """Analyze all frame files and build consensus pockets."""
    frame_files = (
        frame_files_override if frame_files_override is not None else list_frame_files(frames_dir)
    )
    per_frame_pockets: list[list[dict[str, Any]]] = []
    frame_labels: list[str] = []
    frame_stats: list[dict[str, Any]] = []
    frame_errors: list[dict[str, str]] = []

    for frame_file in frame_files:
        try:
            analysis_file = frame_file
            mapper_meta: dict[str, Any] = {}
            if frame_mapper is not None:
                mapped = frame_mapper(frame_file)
                if isinstance(mapped, tuple):
                    analysis_file = Path(mapped[0])
                    maybe_meta = mapped[1]
                    if isinstance(maybe_meta, dict):
                        mapper_meta = maybe_meta
                else:
                    analysis_file = Path(mapped)

            pockets = analyze_structure_file(analysis_file, profile=config.profile)
        except Exception as exc:  # noqa: BLE001
            frame_errors.append({"frame": frame_file.name, "error": str(exc)})
            continue

        per_frame_pockets.append(pockets)
        frame_labels.append(frame_file.name)
        frame_stats.append(
            {
                "frame": frame_file.name,
                "analysis_file": str(analysis_file),
                "n_pockets": len(pockets),
                "n_druggable": sum(1 for p in pockets if p.get("druggable", False)),
                **mapper_meta,
            }
        )

    consensus_pockets, consensus_stats = aggregate_consensus_pockets(
        per_frame_pockets=per_frame_pockets,
        frame_labels=frame_labels,
        config=config,
    )

    result = {
        "frame_files_total": len(frame_files),
        "frames_analyzed": len(frame_labels),
        "frame_errors": frame_errors,
        "frame_stats": frame_stats,
        "per_frame_pockets": per_frame_pockets,
        "consensus_pockets": consensus_pockets,
        "consensus_stats": consensus_stats,
    }

    if consensus_pockets and frame_labels:
        persistence = analyze_pocket_persistence(consensus_pockets, frame_labels)
        result["persistence"] = persistence

    return result


# ============================================================================
# POCKET PERSISTENCE ANALYSIS
# ============================================================================


@dataclass(frozen=True)
class PersistenceMetrics:
    """Temporal pocket dynamics for a single consensus pocket."""

    pocket_id: int
    total_frames: int
    hit_count: int
    support_ratio: float
    first_appearance: int
    last_appearance: int
    span: int
    consecutive_max: int
    flicker_count: int
    persistence_score: float


def _frame_index_map(frame_labels: list[str]) -> dict[str, int]:
    """Map frame label strings to ordered integer indices."""
    return {label: idx for idx, label in enumerate(frame_labels)}


def _compute_streaks(present: list[bool]) -> tuple[int, int]:
    """Return (max_consecutive_true, number_of_off→on_transitions)."""
    max_streak = 0
    current_streak = 0
    flicker = 0
    prev = False

    for val in present:
        if val:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
            if not prev and current_streak > 1:
                pass
            if not prev:
                flicker += 1
        else:
            current_streak = 0
        prev = val

    flicker = max(0, flicker - 1)
    return max_streak, flicker


def compute_persistence(
    pocket: dict[str, Any],
    frame_labels: list[str],
    frame_index: dict[str, int],
) -> PersistenceMetrics:
    """Compute temporal persistence metrics for one consensus pocket."""
    total = len(frame_labels)
    hits: set[str] = set(pocket.get("frame_hits", []))
    hit_count = len(hits)

    present = [label in hits for label in frame_labels]

    indices = sorted(frame_index[h] for h in hits if h in frame_index)
    first = indices[0] if indices else 0
    last = indices[-1] if indices else 0
    span = last - first + 1 if indices else 0

    max_consec, flicker = _compute_streaks(present)

    support_ratio = hit_count / max(1, total)
    streak_ratio = max_consec / max(1, total)
    flicker_penalty = 1.0 - min(1.0, flicker / max(1, hit_count))

    persistence_score = round(
        0.50 * support_ratio + 0.30 * streak_ratio + 0.20 * flicker_penalty,
        4,
    )

    return PersistenceMetrics(
        pocket_id=pocket.get("id", 0),
        total_frames=total,
        hit_count=hit_count,
        support_ratio=round(support_ratio, 4),
        first_appearance=first,
        last_appearance=last,
        span=span,
        consecutive_max=max_consec,
        flicker_count=flicker,
        persistence_score=persistence_score,
    )


def analyze_pocket_persistence(
    consensus_pockets: list[dict[str, Any]],
    frame_labels: list[str],
) -> dict[str, Any]:
    """
    Analyze temporal persistence of all consensus pockets.

    Returns summary stats and per-pocket persistence metrics.
    Enriches each consensus pocket dict with persistence fields.
    """
    frame_idx = _frame_index_map(frame_labels)
    results: list[dict[str, Any]] = []

    for pocket in consensus_pockets:
        pm = compute_persistence(pocket, frame_labels, frame_idx)
        pocket["persistence_score"] = pm.persistence_score
        pocket["persistence_consecutive_max"] = pm.consecutive_max
        pocket["persistence_flicker_count"] = pm.flicker_count
        pocket["persistence_span"] = pm.span

        results.append(
            {
                "pocket_id": pm.pocket_id,
                "hit_count": pm.hit_count,
                "support_ratio": pm.support_ratio,
                "first_appearance": pm.first_appearance,
                "last_appearance": pm.last_appearance,
                "span": pm.span,
                "consecutive_max": pm.consecutive_max,
                "flicker_count": pm.flicker_count,
                "persistence_score": pm.persistence_score,
            }
        )

    scores = [r["persistence_score"] for r in results]
    return {
        "n_pockets": len(results),
        "avg_persistence": round(float(np.mean(scores)), 4) if scores else 0.0,
        "max_persistence": round(float(np.max(scores)), 4) if scores else 0.0,
        "pockets": results,
    }
