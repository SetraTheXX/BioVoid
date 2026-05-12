"""
Bio-Void Hunter: Model Evaluation Framework
==============================================

Metrics, ablation analysis, and calibration assessment
for pocket classifiers.

Metrics:
- PR-AUC, ROC-AUC
- Recall@k, Precision@k
- Calibration error (ECE)
- Confusion matrix
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

try:
    from sklearn.metrics import (
        accuracy_score,
        average_precision_score,
        classification_report,
        confusion_matrix,
        f1_score,
        precision_recall_curve,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


def evaluate_model(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_proba: np.ndarray | None = None,
) -> dict[str, Any]:
    """
    Comprehensive evaluation of a binary classifier.

    Returns dict with all standard metrics.
    """
    if not SKLEARN_AVAILABLE:
        raise RuntimeError("scikit-learn is required for evaluation")

    results: dict[str, Any] = {
        "n_samples": len(y_true),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
    }

    cm = confusion_matrix(y_true, y_pred)
    results["confusion_matrix"] = cm.tolist()

    if y_proba is not None:
        pos_proba = y_proba[:, 1] if y_proba.ndim > 1 else y_proba
        try:
            results["roc_auc"] = round(float(roc_auc_score(y_true, pos_proba)), 4)
        except ValueError:
            results["roc_auc"] = None

        try:
            results["pr_auc"] = round(float(average_precision_score(y_true, pos_proba)), 4)
        except ValueError:
            results["pr_auc"] = None

        results["ece"] = round(float(_expected_calibration_error(y_true, pos_proba)), 4)

    return results


def _expected_calibration_error(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    n_bins: int = 10,
) -> float:
    """
    Expected Calibration Error (ECE).

    Measures how well predicted probabilities match actual frequencies.
    Lower is better; 0 = perfectly calibrated.
    """
    bin_edges = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    total = len(y_true)

    for lo, hi in zip(bin_edges[:-1], bin_edges[1:], strict=False):
        mask = (y_proba >= lo) & (y_proba < hi)
        n_bin = mask.sum()
        if n_bin == 0:
            continue

        avg_confidence = y_proba[mask].mean()
        avg_accuracy = y_true[mask].mean()
        ece += (n_bin / total) * abs(avg_accuracy - avg_confidence)

    return ece


def recall_at_k(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    k: int = 10,
) -> float:
    """
    Recall@k: fraction of true positives in the top-k predictions.
    """
    pos_proba = y_proba[:, 1] if y_proba.ndim > 1 else y_proba
    top_k_idx = np.argsort(pos_proba)[::-1][:k]
    n_true_pos_in_top_k = y_true[top_k_idx].sum()
    total_pos = y_true.sum()

    if total_pos == 0:
        return 0.0
    return round(float(n_true_pos_in_top_k / total_pos), 4)


def precision_at_k(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    k: int = 10,
) -> float:
    """
    Precision@k: fraction of top-k predictions that are true positives.
    """
    pos_proba = y_proba[:, 1] if y_proba.ndim > 1 else y_proba
    top_k_idx = np.argsort(pos_proba)[::-1][:k]
    n_true_pos_in_top_k = y_true[top_k_idx].sum()
    return round(float(n_true_pos_in_top_k / max(k, 1)), 4)


def ablation_study(
    train_fn,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
    feature_names: Sequence[str],
) -> list[dict[str, Any]]:
    """
    Leave-one-feature-out ablation study.

    Args:
        train_fn: Callable(X_train, y_train) -> model with predict/predict_proba
        X_train, y_train: Training data
        X_test, y_test: Test data
        feature_names: Names of features (must match X columns)

    Returns:
        List of dicts with feature name, metrics without that feature,
        and delta from full model.
    """
    full_model = train_fn(X_train, y_train)
    full_pred = full_model.predict(X_test)
    full_proba = None
    if hasattr(full_model, "predict_proba"):
        full_proba = full_model.predict_proba(X_test)
    full_metrics = evaluate_model(y_test, full_pred, full_proba)

    results = [
        {
            "feature_removed": "none (full model)",
            "metrics": full_metrics,
            "delta_f1": 0.0,
            "delta_pr_auc": 0.0,
        }
    ]

    for i, feat_name in enumerate(feature_names):
        cols = list(range(X_train.shape[1]))
        cols.pop(i)
        X_tr_reduced = X_train[:, cols]
        X_te_reduced = X_test[:, cols]

        model = train_fn(X_tr_reduced, y_train)
        pred = model.predict(X_te_reduced)
        proba = None
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(X_te_reduced)
        m = evaluate_model(y_test, pred, proba)

        results.append(
            {
                "feature_removed": feat_name,
                "metrics": m,
                "delta_f1": round(full_metrics["f1"] - m["f1"], 4),
                "delta_pr_auc": round(
                    (full_metrics.get("pr_auc") or 0) - (m.get("pr_auc") or 0), 4
                ),
            }
        )

    results.sort(key=lambda r: abs(r["delta_f1"]), reverse=True)
    return results
