"""
Bio-Void Hunter: Protein Graph Neural Network Module
======================================================

Graph-based representation of protein structures for
cryptic pocket prediction.

Approach:
    1. Build contact graph from CA atoms (node=residue, edge=contact<8A)
    2. Extract per-node features (B-factor, hydrophobicity, secondary structure)
    3. Graph-level features via message passing (neighbor aggregation)
    4. Predict per-residue pocket opening probability

This uses numpy/sklearn for portability. For GPU acceleration,
replace with PyTorch Geometric when available.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
from scipy.spatial.distance import cdist

logger = logging.getLogger(__name__)

CONTACT_CUTOFF = 8.0
HYDROPHOBIC_RESIDUES = {"ALA", "VAL", "LEU", "ILE", "MET", "PHE", "TRP", "PRO"}
POLAR_RESIDUES = {"SER", "THR", "ASN", "GLN", "TYR", "CYS"}
CHARGED_RESIDUES = {"ASP", "GLU", "LYS", "ARG", "HIS"}
KYTE_DOOLITTLE = {
    "ILE": 4.5, "VAL": 4.2, "LEU": 3.8, "PHE": 2.8, "CYS": 2.5,
    "MET": 1.9, "ALA": 1.8, "GLY": -0.4, "THR": -0.7, "SER": -0.8,
    "TRP": -0.9, "TYR": -1.3, "PRO": -1.6, "HIS": -3.2, "GLU": -3.5,
    "GLN": -3.5, "ASP": -3.5, "ASN": -3.5, "LYS": -3.9, "ARG": -4.5,
}

N_MESSAGE_PASSES = 3


@dataclass
class ProteinGraph:
    """Graph representation of a protein structure."""

    pdb_id: str
    n_residues: int
    node_features: np.ndarray
    adjacency: np.ndarray
    ca_coords: np.ndarray
    residue_names: list[str]
    feature_names: list[str]


def build_protein_graph(
    pdb_path: str,
    contact_cutoff: float = CONTACT_CUTOFF,
) -> ProteinGraph:
    """
    Build a contact graph from a PDB file.

    Nodes: CA atoms (one per residue)
    Edges: Contact pairs within cutoff distance
    """
    import biotite.structure.io.pdb as pdb_io

    pdb_file = pdb_io.PDBFile.read(pdb_path)
    structure = pdb_file.get_structure()[0]

    ca_mask = structure.atom_name == "CA"
    ca_atoms = structure[ca_mask]

    if len(ca_atoms) == 0:
        raise ValueError(f"No CA atoms found in {pdb_path}")

    coords = ca_atoms.coord
    n = len(coords)

    dist_matrix = cdist(coords, coords)
    adjacency = (dist_matrix < contact_cutoff).astype(np.float32)
    np.fill_diagonal(adjacency, 0)

    residue_names = [r.upper() for r in ca_atoms.res_name]

    node_feats = _extract_node_features(ca_atoms, residue_names, dist_matrix)

    feature_names = [
        "hydrophobicity", "is_hydrophobic", "is_polar", "is_charged",
        "relative_position", "contact_count", "avg_contact_dist",
        "local_density", "exposure",
    ]

    return ProteinGraph(
        pdb_id=pdb_path.split("/")[-1].replace(".pdb", "").upper(),
        n_residues=n,
        node_features=node_feats,
        adjacency=adjacency,
        ca_coords=coords,
        residue_names=residue_names,
        feature_names=feature_names,
    )


def _extract_node_features(
    ca_atoms, residue_names: list[str], dist_matrix: np.ndarray,
) -> np.ndarray:
    """Extract per-residue feature vectors."""
    n = len(residue_names)
    features = np.zeros((n, 9), dtype=np.float32)

    for i, res in enumerate(residue_names):
        features[i, 0] = KYTE_DOOLITTLE.get(res, 0.0) / 4.5
        features[i, 1] = 1.0 if res in HYDROPHOBIC_RESIDUES else 0.0
        features[i, 2] = 1.0 if res in POLAR_RESIDUES else 0.0
        features[i, 3] = 1.0 if res in CHARGED_RESIDUES else 0.0
        features[i, 4] = i / max(1, n - 1)

    for i in range(n):
        contacts = dist_matrix[i] < CONTACT_CUTOFF
        contacts[i] = False
        n_contacts = contacts.sum()
        features[i, 5] = n_contacts / max(1, n)

        if n_contacts > 0:
            features[i, 6] = dist_matrix[i][contacts].mean() / CONTACT_CUTOFF
        else:
            features[i, 6] = 1.0

        features[i, 7] = n_contacts / 20.0

        far_contacts = (dist_matrix[i] < 15.0) & (dist_matrix[i] > CONTACT_CUTOFF)
        features[i, 8] = 1.0 - (far_contacts.sum() / max(1, n))

    return features


def graph_message_passing(
    graph: ProteinGraph,
    n_passes: int = N_MESSAGE_PASSES,
) -> np.ndarray:
    """
    Simple message passing: aggregate neighbor features.

    Each pass: node_i = node_i + mean(neighbors of node_i)
    This simulates GNN information propagation without neural network weights.
    """
    features = graph.node_features.copy()
    adj = graph.adjacency

    for _ in range(n_passes):
        degree = adj.sum(axis=1, keepdims=True)
        degree = np.maximum(degree, 1.0)
        neighbor_mean = (adj @ features) / degree
        features = 0.5 * features + 0.5 * neighbor_mean

    return features


def predict_pocket_residues(
    graph: ProteinGraph,
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """
    Predict which residues are likely part of cryptic pockets.

    Uses graph message passing + heuristic scoring:
    - High hydrophobicity + moderate exposure = potential pocket lining
    - Clustered hydrophobic residues = pocket candidate

    Returns top-k residue predictions with scores.
    """
    features = graph_message_passing(graph)

    scores = np.zeros(graph.n_residues)
    for i in range(graph.n_residues):
        hydro = features[i, 0]
        is_hydro = features[i, 1]
        contact = features[i, 5]
        density = features[i, 7]
        exposure = features[i, 8]

        pocket_score = (
            0.3 * max(0, hydro)
            + 0.2 * is_hydro
            + 0.2 * (1.0 - exposure)
            + 0.15 * density
            + 0.15 * contact
        )
        scores[i] = pocket_score

    top_indices = np.argsort(scores)[::-1][:top_k]

    predictions = []
    for idx in top_indices:
        predictions.append({
            "residue_index": int(idx),
            "residue_name": graph.residue_names[idx],
            "pocket_score": round(float(scores[idx]), 4),
            "position": graph.ca_coords[idx].tolist(),
            "features": {
                name: round(float(features[idx, j]), 4)
                for j, name in enumerate(graph.feature_names)
            },
        })

    return predictions


def identify_pocket_clusters(
    predictions: list[dict[str, Any]],
    cluster_distance: float = 6.0,
) -> list[dict[str, Any]]:
    """
    Cluster predicted pocket residues into pocket regions.

    Groups nearby high-scoring residues into pocket candidates.
    """
    if not predictions:
        return []

    positions = np.array([p["position"] for p in predictions])
    scores = np.array([p["pocket_score"] for p in predictions])

    from sklearn.cluster import DBSCAN
    clustering = DBSCAN(eps=cluster_distance, min_samples=3).fit(positions)
    labels = clustering.labels_

    clusters: list[dict[str, Any]] = []
    for label in set(labels):
        if label == -1:
            continue
        mask = labels == label
        cluster_positions = positions[mask]
        cluster_scores = scores[mask]
        cluster_residues = [predictions[i] for i in range(len(predictions)) if mask[i]]

        center = cluster_positions.mean(axis=0)
        radius = float(np.max(np.linalg.norm(cluster_positions - center, axis=1)))

        clusters.append({
            "cluster_id": int(label),
            "center": center.tolist(),
            "radius": round(radius, 2),
            "n_residues": int(mask.sum()),
            "avg_score": round(float(cluster_scores.mean()), 4),
            "max_score": round(float(cluster_scores.max()), 4),
            "residues": [r["residue_name"] for r in cluster_residues],
            "residue_indices": [r["residue_index"] for r in cluster_residues],
        })

    clusters.sort(key=lambda c: c["avg_score"], reverse=True)
    return clusters
