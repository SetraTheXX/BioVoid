"""
Bio-Void Hunter: Dataset Builder
==================================

Builds labeled datasets from atlas DB pocket records for ML training.

Features:
- Label assignment (positive/negative/uncertain)
- Train/val/test splitting with protein-level stratification
- Leakage detection (same protein in multiple splits)
- Dataset manifest generation for reproducibility
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .features import ALL_FEATURE_NAMES, extract_batch

logger = logging.getLogger(__name__)


@dataclass
class LabelPolicy:
    """Defines how pockets are labeled for classification."""

    positive_min_bio_score: float = 0.65
    positive_require_druggable: bool = True
    negative_max_bio_score: float = 0.30
    uncertain_label: int = -1
    positive_label: int = 1
    negative_label: int = 0


@dataclass
class SplitConfig:
    """Train/val/test split ratios and settings."""

    train_ratio: float = 0.70
    val_ratio: float = 0.15
    test_ratio: float = 0.15
    seed: int = 42
    stratify_by_protein: bool = True

    def __post_init__(self):
        total = self.train_ratio + self.val_ratio + self.test_ratio
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Split ratios must sum to 1.0, got {total}")


@dataclass
class DatasetManifest:
    """Reproducibility manifest for a built dataset."""

    n_samples: int = 0
    n_positive: int = 0
    n_negative: int = 0
    n_uncertain: int = 0
    n_features: int = 0
    feature_names: list[str] = field(default_factory=list)
    split_config: dict[str, Any] = field(default_factory=dict)
    label_policy: dict[str, Any] = field(default_factory=dict)
    train_size: int = 0
    val_size: int = 0
    test_size: int = 0
    data_hash: str = ""
    proteins_in_train: list[str] = field(default_factory=list)
    proteins_in_val: list[str] = field(default_factory=list)
    proteins_in_test: list[str] = field(default_factory=list)


def assign_labels(
    pockets: list[dict[str, Any]],
    policy: LabelPolicy = LabelPolicy(),
) -> list[int]:
    """
    Assign classification labels to pockets based on policy.

    Returns list of labels aligned with input pocket list.
    """
    labels = []
    for p in pockets:
        bio_score = p.get("bio_score", 0.0)
        druggable = p.get("druggable", False)

        if bio_score >= policy.positive_min_bio_score:
            if policy.positive_require_druggable and not druggable:
                labels.append(policy.uncertain_label)
            else:
                labels.append(policy.positive_label)
        elif bio_score <= policy.negative_max_bio_score:
            labels.append(policy.negative_label)
        else:
            labels.append(policy.uncertain_label)

    return labels


def _protein_level_split(
    pdb_ids: list[str],
    config: SplitConfig,
) -> tuple[set[str], set[str], set[str]]:
    """Split proteins into train/val/test ensuring no leakage."""
    unique_ids = sorted(set(pdb_ids))
    rng = np.random.RandomState(config.seed)
    rng.shuffle(unique_ids)

    n = len(unique_ids)
    n_train = int(n * config.train_ratio)
    n_val = int(n * config.val_ratio)

    train_ids = set(unique_ids[:n_train])
    val_ids = set(unique_ids[n_train : n_train + n_val])
    test_ids = set(unique_ids[n_train + n_val :])

    return train_ids, val_ids, test_ids


def check_leakage(
    train_ids: set[str],
    val_ids: set[str],
    test_ids: set[str],
) -> list[str]:
    """Detect any protein IDs that appear in multiple splits."""
    leaks = []
    tv = train_ids & val_ids
    tt = train_ids & test_ids
    vt = val_ids & test_ids
    if tv:
        leaks.append(f"train-val overlap: {tv}")
    if tt:
        leaks.append(f"train-test overlap: {tt}")
    if vt:
        leaks.append(f"val-test overlap: {vt}")
    return leaks


def build_dataset(
    pockets: list[dict[str, Any]],
    pdb_ids: list[str],
    label_policy: LabelPolicy = LabelPolicy(),
    split_config: SplitConfig = SplitConfig(),
    feature_names: Sequence[str] = ALL_FEATURE_NAMES,
    exclude_uncertain: bool = True,
) -> dict[str, Any]:
    """
    Build a complete ML dataset from pocket data.

    Args:
        pockets: List of pocket dicts (from scoring/consensus)
        pdb_ids: Parallel list of PDB IDs for each pocket
        label_policy: How to assign labels
        split_config: Train/val/test ratios
        feature_names: Which features to extract
        exclude_uncertain: Remove uncertain-labeled samples

    Returns:
        Dict with X_train, y_train, X_val, y_val, X_test, y_test,
        and manifest for reproducibility.
    """
    labels = assign_labels(pockets, label_policy)
    X = extract_batch(pockets, feature_names)

    if exclude_uncertain:
        mask = np.array([l != label_policy.uncertain_label for l in labels])
        X = X[mask]
        labels = [l for l, m in zip(labels, mask, strict=False) if m]
        pdb_ids = [p for p, m in zip(pdb_ids, mask, strict=False) if m]
        pockets = [p for p, m in zip(pockets, mask, strict=False) if m]

    y = np.array(labels, dtype=np.int32)

    train_proteins, val_proteins, test_proteins = _protein_level_split(pdb_ids, split_config)

    leaks = check_leakage(train_proteins, val_proteins, test_proteins)
    if leaks:
        logger.warning("Data leakage detected: %s", leaks)

    train_mask = np.array([p in train_proteins for p in pdb_ids])
    val_mask = np.array([p in val_proteins for p in pdb_ids])
    test_mask = np.array([p in test_proteins for p in pdb_ids])

    X_train, y_train = X[train_mask], y[train_mask]
    X_val, y_val = X[val_mask], y[val_mask]
    X_test, y_test = X[test_mask], y[test_mask]

    data_bytes = X.tobytes() + y.tobytes()
    data_hash = hashlib.sha256(data_bytes).hexdigest()[:16]

    manifest = DatasetManifest(
        n_samples=len(y),
        n_positive=int((y == label_policy.positive_label).sum()),
        n_negative=int((y == label_policy.negative_label).sum()),
        n_uncertain=0 if exclude_uncertain else int((y == label_policy.uncertain_label).sum()),
        n_features=X.shape[1] if X.size else 0,
        feature_names=list(feature_names),
        split_config=asdict(split_config),
        label_policy=asdict(label_policy),
        train_size=len(y_train),
        val_size=len(y_val),
        test_size=len(y_test),
        data_hash=data_hash,
        proteins_in_train=sorted(train_proteins),
        proteins_in_val=sorted(val_proteins),
        proteins_in_test=sorted(test_proteins),
    )

    return {
        "X_train": X_train,
        "y_train": y_train,
        "X_val": X_val,
        "y_val": y_val,
        "X_test": X_test,
        "y_test": y_test,
        "manifest": manifest,
        "leakage_warnings": leaks,
    }


def save_manifest(manifest: DatasetManifest, path: str | Path) -> None:
    """Save dataset manifest as JSON for reproducibility."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(asdict(manifest), f, indent=2, default=str)
    logger.info("Dataset manifest saved to %s", out)
