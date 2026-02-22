"""
Bio-Void Hunter: Cross-Protein Pocket Comparison
==================================================

Compares pocket geometries and properties across proteins.
Answers: "Which other proteins have a similar pocket?"

Features:
- Feature-vector based pocket similarity (cosine + euclidean)
- Atlas DB search for similar pockets
- Pairwise comparison reports
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)

FEATURE_KEYS = [
    "volume",
    "hydrophobic_ratio",
    "radius_geom",
    "radius_clear",
    "merged_vertices",
]

SCORE_KEYS = [
    "volume_score",
    "hydrophobicity_score",
    "enclosure_score",
    "depth_score",
    "sphericity",
]


@dataclass(frozen=True)
class PocketSimilarity:
    """Result of comparing two pockets."""

    pocket_a_id: str
    pocket_b_id: str
    cosine_similarity: float
    euclidean_distance: float
    composite_similarity: float
    feature_deltas: dict[str, float]


def _extract_feature_vector(
    pocket: dict[str, Any],
    keys: Sequence[str] = SCORE_KEYS,
) -> np.ndarray:
    """Build a numeric feature vector from a pocket dict."""
    components = pocket.get("score_components", {})
    values = []
    for k in keys:
        val = components.get(k, pocket.get(k, 0.0))
        try:
            val = float(val)
        except (TypeError, ValueError):
            val = 0.0
        if not np.isfinite(val):
            val = 0.0
        values.append(val)
    return np.array(values, dtype=float)


def compare_pockets(
    pocket_a: dict[str, Any],
    pocket_b: dict[str, Any],
    label_a: str = "A",
    label_b: str = "B",
) -> PocketSimilarity:
    """
    Compare two pockets and return a similarity report.

    Uses both cosine similarity (direction) and euclidean distance
    (magnitude) of score-component vectors.
    """
    vec_a = _extract_feature_vector(pocket_a)
    vec_b = _extract_feature_vector(pocket_b)

    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)

    if norm_a > 0 and norm_b > 0:
        cosine = float(np.dot(vec_a, vec_b) / (norm_a * norm_b))
    else:
        cosine = 0.0

    euclidean = float(np.linalg.norm(vec_a - vec_b))

    max_dist = np.sqrt(len(SCORE_KEYS))
    composite = round(
        0.6 * max(0.0, cosine)
        + 0.4 * max(0.0, 1.0 - euclidean / max_dist),
        4,
    )

    deltas = {}
    for i, k in enumerate(SCORE_KEYS):
        deltas[k] = round(float(vec_a[i] - vec_b[i]), 4)

    return PocketSimilarity(
        pocket_a_id=label_a,
        pocket_b_id=label_b,
        cosine_similarity=round(cosine, 4),
        euclidean_distance=round(euclidean, 4),
        composite_similarity=composite,
        feature_deltas=deltas,
    )


def find_similar_pockets(
    query_pocket: dict[str, Any],
    candidate_pockets: list[dict[str, Any]],
    top_n: int = 10,
    min_similarity: float = 0.0,
) -> list[dict[str, Any]]:
    """
    Find the most similar pockets from a list of candidates.

    Args:
        query_pocket: The pocket to compare against
        candidate_pockets: List of pockets to search through
        top_n: Maximum results to return
        min_similarity: Minimum composite similarity threshold

    Returns:
        List of dicts with pocket data and similarity scores, sorted by similarity.
    """
    query_vec = _extract_feature_vector(query_pocket)
    results: list[dict[str, Any]] = []

    for candidate in candidate_pockets:
        cand_vec = _extract_feature_vector(candidate)

        norm_q = np.linalg.norm(query_vec)
        norm_c = np.linalg.norm(cand_vec)

        if norm_q > 0 and norm_c > 0:
            cosine = float(np.dot(query_vec, cand_vec) / (norm_q * norm_c))
        else:
            cosine = 0.0

        euclidean = float(np.linalg.norm(query_vec - cand_vec))
        max_dist = np.sqrt(len(SCORE_KEYS))
        composite = round(
            0.6 * max(0.0, cosine)
            + 0.4 * max(0.0, 1.0 - euclidean / max_dist),
            4,
        )

        if composite >= min_similarity:
            results.append({
                "pocket": candidate,
                "pdb_id": candidate.get("pdb_id", "unknown"),
                "pocket_id": candidate.get("id", 0),
                "cosine_similarity": round(cosine, 4),
                "euclidean_distance": round(euclidean, 4),
                "composite_similarity": composite,
                "bio_score": candidate.get("bio_score", 0.0),
            })

    results.sort(key=lambda r: r["composite_similarity"], reverse=True)
    return results[:top_n]


def batch_compare(
    pockets_a: list[dict[str, Any]],
    pockets_b: list[dict[str, Any]],
    label_a: str = "protein_A",
    label_b: str = "protein_B",
) -> dict[str, Any]:
    """
    Pairwise comparison of all pockets between two proteins.

    Returns summary and the best-matching pairs.
    """
    pairs: list[dict[str, Any]] = []

    for i, pa in enumerate(pockets_a):
        for j, pb in enumerate(pockets_b):
            sim = compare_pockets(
                pa, pb,
                label_a=f"{label_a}_p{i}",
                label_b=f"{label_b}_p{j}",
            )
            pairs.append({
                "a_index": i,
                "b_index": j,
                "cosine": sim.cosine_similarity,
                "euclidean": sim.euclidean_distance,
                "composite": sim.composite_similarity,
                "deltas": sim.feature_deltas,
            })

    pairs.sort(key=lambda p: p["composite"], reverse=True)

    return {
        "label_a": label_a,
        "label_b": label_b,
        "n_pockets_a": len(pockets_a),
        "n_pockets_b": len(pockets_b),
        "n_pairs": len(pairs),
        "best_match": pairs[0] if pairs else None,
        "top_matches": pairs[:10],
        "avg_similarity": round(
            float(np.mean([p["composite"] for p in pairs])), 4
        ) if pairs else 0.0,
    }
