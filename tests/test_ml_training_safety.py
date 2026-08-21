from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("script_name", ["train_ml_model.py", "train_multi_model.py"])
def test_heuristic_label_training_is_disabled_by_default(script_name: str) -> None:
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(project_root / "scripts" / script_name)],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 2
    assert "[DISABLED]" in result.stderr
    assert "not pocket truth" in result.stderr


def test_confirmatory_runner_requires_authorization_before_preparation() -> None:
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(project_root / "scripts" / "run_ri5_confirmatory_static.py")],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 2
    assert "requires explicit authorization" in result.stderr
    assert "Required runtime file is missing" not in result.stderr
