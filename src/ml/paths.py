"""Canonical paths for optional experimental ML assets.

Training and inference must resolve the same repository-relative location.
Model files remain local ignored artifacts and are never bundled in the
source-only repository.
"""

from __future__ import annotations

from pathlib import Path

from src.config import PATHS

MODEL_FILENAME = "pocket_classifier.pkl"


def project_root() -> Path:
    """Return the repository root independently of the current shell cwd."""
    return Path(__file__).resolve().parents[2]


def model_directory(root: str | Path | None = None) -> Path:
    """Return the shared local model directory."""
    base = Path(root).resolve() if root is not None else project_root()
    return base / PATHS.models


def pocket_classifier_path(root: str | Path | None = None) -> Path:
    """Return the shared local classifier path used by training and inference."""
    return model_directory(root) / MODEL_FILENAME
