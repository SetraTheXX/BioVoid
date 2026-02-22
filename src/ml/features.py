"""
Bio-Void Hunter: Pocket Feature Engineering
=============================================

Extracts structured feature vectors from pocket dictionaries
for use in ML classifiers and similarity searches.

Feature groups:
    1. Geometric: volume, radii, vertex count, sphericity
    2. Chemical: hydrophobicity, polar atom count
    3. Scoring: bio_score components (enclosure, depth)
    4. Dynamics: persistence, support ratio, flicker (if available)
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)

GEOMETRIC_FEATURES = [
    "volume",
    "radius_geom",
    "radius_clear",
    "merged_vertices",
]

CHEMICAL_FEATURES = [
    "hydrophobic_ratio",
    "polar_atoms",
]

SCORE_FEATURES = [
    "volume_score",
    "hydrophobicity_score",
    "enclosure_score",
    "depth_score",
    "sphericity",
]

DYNAMICS_FEATURES = [
    "consensus_support_ratio",
    "consensus_center_stability",
    "consensus_volume_cv",
    "persistence_score",
    "persistence_consecutive_max",
    "persistence_flicker_count",
]

ALL_FEATURE_NAMES = (
    GEOMETRIC_FEATURES
    + CHEMICAL_FEATURES
    + SCORE_FEATURES
    + DYNAMICS_FEATURES
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
        return v if np.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def extract_features(
    pocket: dict[str, Any],
    feature_names: Sequence[str] = ALL_FEATURE_NAMES,
) -> np.ndarray:
    """
    Extract a fixed-length feature vector from a pocket dict.

    Looks in both top-level keys and score_components sub-dict.
    Missing values default to 0.0.
    """
    components = pocket.get("score_components", {})
    values = []
    for key in feature_names:
        val = pocket.get(key, components.get(key, 0.0))
        values.append(_safe_float(val))
    return np.array(values, dtype=np.float64)


def extract_batch(
    pockets: list[dict[str, Any]],
    feature_names: Sequence[str] = ALL_FEATURE_NAMES,
) -> np.ndarray:
    """
    Extract feature matrix (n_pockets x n_features) from a list of pockets.
    """
    if not pockets:
        return np.empty((0, len(feature_names)), dtype=np.float64)
    rows = [extract_features(p, feature_names) for p in pockets]
    return np.stack(rows, axis=0)


def feature_summary(X: np.ndarray,
                    feature_names: Sequence[str] = ALL_FEATURE_NAMES,
                    ) -> dict[str, dict[str, float]]:
    """
    Compute per-feature statistics (mean, std, min, max) for a feature matrix.
    """
    if X.size == 0:
        return {}

    summary = {}
    for i, name in enumerate(feature_names):
        col = X[:, i]
        summary[name] = {
            "mean": round(float(np.mean(col)), 4),
            "std": round(float(np.std(col)), 4),
            "min": round(float(np.min(col)), 4),
            "max": round(float(np.max(col)), 4),
        }
    return summary


def normalize_features(
    X: np.ndarray,
    method: str = "standard",
    stats: Optional[dict[str, np.ndarray]] = None,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """
    Normalize feature matrix.

    Methods:
        'standard': zero mean, unit variance (z-score)
        'minmax': scale to [0, 1]

    Returns normalized X and the stats dict for applying same transform later.
    """
    if X.size == 0:
        return X, {}

    if method == "standard":
        if stats is not None:
            mean = stats["mean"]
            std = stats["std"]
        else:
            mean = X.mean(axis=0)
            std = X.std(axis=0)
            std[std < 1e-10] = 1.0

        X_norm = (X - mean) / std
        return X_norm, {"mean": mean, "std": std}

    if method == "minmax":
        if stats is not None:
            xmin = stats["min"]
            xmax = stats["max"]
        else:
            xmin = X.min(axis=0)
            xmax = X.max(axis=0)

        denom = xmax - xmin
        denom[denom < 1e-10] = 1.0
        X_norm = (X - xmin) / denom
        return X_norm, {"min": xmin, "max": xmax}

    raise ValueError(f"Unknown normalization method: {method}")
