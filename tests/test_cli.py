"""Command-line interface regression tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_info_command_emits_project_configuration() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "info"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )

    output = result.stdout + result.stderr
    assert "Bio-Void Hunter v" in output
    assert "Default profile:" in output


def test_cache_stats_command_emits_cache_statistics() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "cache", "stats"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )

    output = result.stdout + result.stderr
    assert "entries:" in output
    assert "hit_rate:" in output


def test_batch_parser_rejects_blank_or_invalid_identifiers() -> None:
    from src.cli import _parse_batch_pdb_ids

    with pytest.raises(ValueError, match="four alphanumeric characters"):
        _parse_batch_pdb_ids("1CBS,,not-a-pdb")

    with pytest.raises(ValueError, match="limited to 10"):
        _parse_batch_pdb_ids(",".join(["1CBS"] * 11))


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (("analyze", "not-a-pdb"), "PDB ID must contain exactly four alphanumeric characters"),
        (("analyze", "1CBS", "--n-frames", "0"), "--n-frames must be in the range 1-8"),
        (("batch", "1CBS", "--profile", "not-a-profile"), "invalid choice"),
        (("serve", "--port", "70000"), "--port must be in the range 1-65535"),
    ],
)
def test_cli_rejects_invalid_options_before_work_starts(
    argv: tuple[str, ...], message: str
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", *argv],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 2
    assert message in output
    assert "Traceback" not in output


def test_cli_serve_rejects_non_loopback_bind_without_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from src.cli import cmd_serve

    called = False

    def fake_run(*_: object, **__: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))
    args = SimpleNamespace(
        host="0.0.0.0",
        port=8766,
        reload=False,
        verbose=False,
        allow_remote=False,
    )

    assert cmd_serve(args) == 2
    assert not called


def test_cli_serve_allows_non_loopback_bind_with_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from src.cli import cmd_serve

    observed: dict[str, object] = {}

    def fake_run(*_: object, **kwargs: object) -> None:
        observed.update(kwargs)

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))
    args = SimpleNamespace(
        host="0.0.0.0",
        port=8766,
        reload=False,
        verbose=False,
        allow_remote=True,
    )

    assert cmd_serve(args) == 0
    assert observed["host"] == "0.0.0.0"
    assert observed["port"] == 8766


def test_cli_requires_explicit_opt_in_for_alphafold_motion() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "alphafold", "P04637"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 2
    assert "--allow-experimental" in output
    assert "Traceback" not in output


def test_alphafold_cli_handles_no_evidence_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.alphafold_ensemble as ensemble_module
    from src.cli import cmd_alphafold

    def fake_run(**_: object) -> dict[str, object]:
        return {"analysis": {"consensus_pockets": [], "total_frames_analyzed": 0}}

    monkeypatch.setattr(ensemble_module, "run_alphafold_ensemble_pipeline", fake_run)
    args = SimpleNamespace(
        uniprot_id="P04637",
        verbose=False,
        frames_per_amp=1,
        profile="default",
        allow_experimental=True,
    )

    assert cmd_alphafold(args) == 0


def test_batch_command_returns_failure_when_any_analysis_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import main as pipeline_module
    from src.cli import cmd_batch

    class FailingPipeline:
        def __init__(self, **_: object) -> None:
            pass

        def run(self) -> dict[str, object]:
            raise RuntimeError("synthetic CLI failure")

    monkeypatch.setattr(pipeline_module, "BioVoidPipeline", FailingPipeline)
    args = SimpleNamespace(
        pdb_ids="1CBS,1AKE",
        verbose=False,
        n_frames=1,
        profile="default",
        output="data/runtime/test-cli",
    )

    assert cmd_batch(args) == 1


def test_analyze_command_returns_failure_without_traceback_on_pipeline_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import main as pipeline_module
    from src.cli import cmd_analyze

    class FailingPipeline:
        def __init__(self, **_: object) -> None:
            pass

        def run(self) -> dict[str, object]:
            raise RuntimeError("synthetic CLI failure")

    monkeypatch.setattr(pipeline_module, "BioVoidPipeline", FailingPipeline)
    args = SimpleNamespace(
        pdb_id="1CBS",
        verbose=False,
        n_frames=1,
        profile="default",
        output="data/runtime/test-cli",
        dock=False,
        use_ml=False,
        motion_aware=False,
        allow_experimental=False,
    )

    assert cmd_analyze(args) == 1
