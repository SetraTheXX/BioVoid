"""
Bio-Void Hunter: Baseline Classifiers
=======================================

Sklearn-based classifiers for pocket druggability prediction.

Supported models:
- Random Forest (default baseline)
- Gradient Boosting (XGBoost-style via sklearn)
- Logistic Regression (linear baseline)
"""

from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

try:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import (
        GradientBoostingClassifier,
        RandomForestClassifier,
    )
    from sklearn.linear_model import LogisticRegression

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not available; classifier module disabled")


@dataclass
class ModelConfig:
    """Configuration for model training."""

    model_type: str = "random_forest"
    n_estimators: int = 100
    max_depth: int | None = 10
    random_state: int = 42
    calibrate: bool = True
    calibration_method: str = "isotonic"


AVAILABLE_MODELS = {
    "random_forest": "RandomForestClassifier",
    "gradient_boosting": "GradientBoostingClassifier",
    "logistic": "LogisticRegression",
}


def _create_base_model(config: ModelConfig):
    """Create a base sklearn model from config."""
    if not SKLEARN_AVAILABLE:
        raise RuntimeError("scikit-learn is required for classification")

    if config.model_type == "random_forest":
        return RandomForestClassifier(
            n_estimators=config.n_estimators,
            max_depth=config.max_depth,
            random_state=config.random_state,
            class_weight="balanced",
            n_jobs=-1,
        )
    elif config.model_type == "gradient_boosting":
        return GradientBoostingClassifier(
            n_estimators=config.n_estimators,
            max_depth=min(config.max_depth or 5, 8),
            random_state=config.random_state,
            learning_rate=0.1,
        )
    elif config.model_type == "logistic":
        return LogisticRegression(
            random_state=config.random_state,
            class_weight="balanced",
            max_iter=1000,
        )
    else:
        raise ValueError(
            f"Unknown model_type '{config.model_type}'. Available: {list(AVAILABLE_MODELS.keys())}"
        )


def train_model(
    X_train: np.ndarray,
    y_train: np.ndarray,
    config: ModelConfig = ModelConfig(),
    X_val: np.ndarray | None = None,
    y_val: np.ndarray | None = None,
) -> dict[str, Any]:
    """
    Train a classifier and optionally calibrate probabilities.

    Returns dict with 'model', 'config', 'feature_importances', and training info.
    """
    if X_train.shape[0] == 0:
        raise ValueError("Training set is empty")

    base_model = _create_base_model(config)
    base_model.fit(X_train, y_train)

    model = base_model
    if config.calibrate and X_val is not None and len(X_val) >= 5:
        try:
            n_cal = len(X_val)
            cv_folds = min(5, max(2, n_cal // 3))
            X_cal = np.vstack([X_train, X_val])
            y_cal = np.concatenate([y_train, y_val])
            calibrated = CalibratedClassifierCV(
                _create_base_model(config),
                method=config.calibration_method,
                cv=cv_folds,
            )
            calibrated.fit(X_cal, y_cal)
            model = calibrated
        except Exception as e:
            logger.warning("Calibration failed: %s — using uncalibrated model", e)

    importances = None
    if hasattr(base_model, "feature_importances_"):
        importances = base_model.feature_importances_.tolist()

    train_acc = float((base_model.predict(X_train) == y_train).mean())

    return {
        "model": model,
        "base_model": base_model,
        "config": config,
        "feature_importances": importances,
        "train_accuracy": round(train_acc, 4),
        "train_size": X_train.shape[0],
        "n_features": X_train.shape[1],
    }


def predict(model: Any, X: np.ndarray) -> dict[str, Any]:
    """
    Run prediction and return labels + probabilities.
    """
    y_pred = model.predict(X)
    y_proba = None
    if hasattr(model, "predict_proba"):
        y_proba = model.predict_proba(X)

    return {
        "predictions": y_pred,
        "probabilities": y_proba,
        "n_samples": X.shape[0],
    }


def save_model(model_result: dict[str, Any], path: str | Path) -> None:
    """Save trained model to disk."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        pickle.dump(model_result, f)
    logger.info("Model saved to %s", out)


def load_model(path: str | Path) -> dict[str, Any]:
    """Load trained model from disk."""
    with open(path, "rb") as f:
        return pickle.load(f)
