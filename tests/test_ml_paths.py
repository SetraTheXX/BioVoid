from __future__ import annotations

from pathlib import Path

from src.ml.paths import MODEL_FILENAME, model_directory, pocket_classifier_path


def test_training_and_inference_share_repository_relative_model_path(tmp_path: Path) -> None:
    expected_directory = tmp_path / "data" / "models"
    assert model_directory(tmp_path) == expected_directory
    assert pocket_classifier_path(tmp_path) == expected_directory / MODEL_FILENAME
