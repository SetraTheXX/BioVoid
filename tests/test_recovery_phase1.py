"""Phase 1 runtime and resource-safety regression tests."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from pydantic import ValidationError


def _slow_process_runner(request):
    time.sleep(1.0)
    return {"pdb_id": request.input.pdb_id}


def _write_ca_only_pdb(path: Path) -> None:
    lines = []
    for index in range(1, 6):
        lines.append(
            f"ATOM  {index:5d}  CA  ALA A{index:4d}    "
            f"{index * 1.5:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           C"
        )
    path.write_text("\n".join(lines) + "\nEND\n", encoding="ascii")


def _write_full_atom_pdb(path: Path) -> None:
    atom_names = ("N", "CA", "C", "O")
    lines = []
    serial = 1
    for residue in range(1, 3):
        for atom_name in atom_names:
            lines.append(
                f"ATOM  {serial:5d} {atom_name:>4s} ALA A{residue:4d}    "
                f"{serial * 0.5:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           C"
            )
            serial += 1
    path.write_text("\n".join(lines) + "\nEND\n", encoding="ascii")


def test_job_options_are_typed_and_reject_invalid_values() -> None:
    from src.api.models import JobOptions

    options = JobOptions(
        timeout_seconds=30,
        max_retries=1,
        n_frames=20,
        profile="default",
        priority="normal",
    )
    assert options.timeout_seconds == 30

    invalid_payloads = (
        {"timeout_seconds": 0},
        {"timeout_seconds": 601},
        {"max_retries": -1},
        {"max_retries": 6},
        {"n_frames": 0},
        {"n_frames": 201},
        {"profile": "not-a-profile"},
        {"priority": "urgent"},
    )
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            JobOptions.model_validate(payload)


def test_batch_validation_and_idempotency_are_stable_before_queueing() -> None:
    from fastapi.testclient import TestClient

    from src.api.app import create_app

    with TestClient(create_app()) as client:
        invalid = client.post(
            "/jobs/batch",
            headers={"Idempotency-Key": "phase1-invalid"},
            json={
                "job_type": "quick_probe",
                "pdb_ids": ["1CBS"],
                "options": {"n_frames": 0},
            },
        )
        assert invalid.status_code == 400
        assert client.get("/ready").json()["worker_alive"] is True

        payload = {
            "job_type": "quick_probe",
            "pdb_ids": ["1CBS", "1AKE"],
            "options": {"timeout_seconds": 1, "max_retries": 0},
        }
        first = client.post(
            "/jobs/batch",
            headers={"Idempotency-Key": "phase1-stable-batch"},
            json=payload,
        )
        second = client.post(
            "/jobs/batch",
            headers={"Idempotency-Key": "phase1-stable-batch"},
            json=payload,
        )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["batch_id"] == second.json()["batch_id"]
    assert first.json()["job_ids"] == second.json()["job_ids"]


def test_terminable_process_timeout_has_real_wall_clock_bound() -> None:
    from src.api.models import JobInput, JobSubmitRequest
    from src.api.orchestrator import JobOrchestrator

    orchestrator = JobOrchestrator()
    orchestrator.register_runner(
        "quick_probe",
        _slow_process_runner,
        execution_mode="process",
    )
    request = JobSubmitRequest(
        job_type="quick_probe",
        input=JobInput(pdb_id="1CBS"),
    )

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        orchestrator._run_with_timeout(
            runner=_slow_process_runner,
            request=request,
            timeout_seconds=0.1,
            execution_mode="process",
        )
    assert time.monotonic() - started < 0.8


def test_worker_loop_survives_an_unexpected_job_boundary_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.api.models import JobInput, JobSubmitRequest
    from src.api.orchestrator import JobOrchestrator

    orchestrator = JobOrchestrator()
    request = JobSubmitRequest(job_type="quick_probe", input=JobInput(pdb_id="1CBS"))
    first, _ = orchestrator.submit(request=request, idempotency_key="phase1-crash")
    second, _ = orchestrator.submit(request=request, idempotency_key="phase1-next")

    original = orchestrator._process_job
    calls = 0

    def crash_once(job_id: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic worker-boundary crash")
        original(job_id)

    monkeypatch.setattr(orchestrator, "_process_job", crash_once)
    orchestrator.start()
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and second.status.value == "queued":
            time.sleep(0.01)
        assert orchestrator._worker is not None
        assert orchestrator._worker.is_alive()
        assert first.status.value == "failed"
        assert second.status.value == "succeeded"
    finally:
        orchestrator.stop()


def test_run_workspace_is_unique_empty_and_rejects_stale_frames(tmp_path: Path) -> None:
    from src.runtime import StaleFrameError, create_run_workspace, validate_frame_manifest

    first = create_run_workspace(tmp_path)
    second = create_run_workspace(tmp_path)
    assert first.run_id != second.run_id
    assert list(first.path.iterdir()) == []
    assert list(second.path.iterdir()) == []

    frames = first.path / "frames"
    frames.mkdir()
    expected = frames / "frame_001.pdb"
    expected.write_text("END\n", encoding="ascii")
    validate_frame_manifest(frames, [expected])

    (frames / "frame_999.pdb").write_text("END\n", encoding="ascii")
    with pytest.raises(StaleFrameError):
        validate_frame_manifest(frames, [expected])


def test_canonical_full_atom_guard_rejects_ca_only_before_detection(tmp_path: Path) -> None:
    from src.runtime import CanonicalInputError, require_full_atom_structure

    ca_only = tmp_path / "ca-only.pdb"
    full_atom = tmp_path / "full-atom.pdb"
    _write_ca_only_pdb(ca_only)
    _write_full_atom_pdb(full_atom)

    with pytest.raises(CanonicalInputError, match="C.alpha-only"):
        require_full_atom_structure(ca_only)

    summary = require_full_atom_structure(full_atom)
    assert summary["atom_count"] == 8
    assert summary["ca_count"] == 2


def test_pipeline_uses_run_scoped_output_and_stops_before_ca_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import main
    from main import BioVoidPipeline
    from src.runtime import CanonicalInputError

    ca_only = tmp_path / "ca-only.pdb"
    _write_ca_only_pdb(ca_only)
    detector_called = False

    def forbidden_detector(*_args, **_kwargs):
        nonlocal detector_called
        detector_called = True
        return []

    monkeypatch.setattr(main, "find_voids", forbidden_detector)
    pipeline = BioVoidPipeline("1CBS", output_dir=str(tmp_path / "runs"), use_cache=False)
    pipeline.pdb_file = str(ca_only)

    assert pipeline.output_dir.parent == pipeline.workspace.path
    assert pipeline.workspace.path.parent == tmp_path / "runs"
    assert pipeline.frames_output_dir.parent == pipeline.workspace.path
    with pytest.raises(CanonicalInputError):
        pipeline._scan_voids()
    assert detector_called is False


def test_bulk_crawler_is_hard_disabled_without_recovery_override(tmp_path: Path) -> None:
    from src.parallel_crawler import CrawlerRecoveryDisabledError, ParallelCrawler

    crawler = ParallelCrawler(
        max_workers=1,
        output_dir=str(tmp_path / "experimental"),
        checkpoint_dir=str(tmp_path / "checkpoints"),
    )

    with pytest.raises(CrawlerRecoveryDisabledError):
        crawler.process_pdb_list(["1CBS"], resume=False)


def test_crawler_override_enforces_limits_and_noncanonical_outputs(tmp_path: Path) -> None:
    from src.parallel_crawler import CrawlerConfigurationError, ParallelCrawler

    with pytest.raises(CrawlerConfigurationError):
        ParallelCrawler(
            max_workers=3,
            explicit_recovery_override=True,
            output_dir=str(tmp_path / "experimental"),
            checkpoint_dir=str(tmp_path / "checkpoints"),
        )

    with pytest.raises(CrawlerConfigurationError):
        ParallelCrawler(
            max_workers=1,
            explicit_recovery_override=True,
            output_dir="data/results",
            checkpoint_dir=str(tmp_path / "checkpoints"),
        )

    crawler = ParallelCrawler(
        max_workers=1,
        explicit_recovery_override=True,
        output_dir=str(tmp_path / "experimental"),
        checkpoint_dir=str(tmp_path / "checkpoints"),
    )
    assert crawler.validation_status == "experimental_unvalidated"
    assert crawler.max_workers == 1


def test_safe_16gb_profile_caps_concurrency_and_estimates_hessian_memory() -> None:
    from src.profiling import PipelineProfiler
    from src.resources import (
        ResourceLimitError,
        SAFE_16GB,
        estimate_hessian_bytes,
        get_process_memory_snapshot,
    )

    assert SAFE_16GB.soft_memory_budget_bytes == 8 * 1024**3
    assert SAFE_16GB.max_heavy_jobs == 1
    assert SAFE_16GB.max_analysis_workers == 2
    assert 4 <= SAFE_16GB.max_download_workers <= 6
    assert estimate_hessian_bytes(100) > 0
    memory = get_process_memory_snapshot()
    assert memory.current_rss_bytes > 0
    assert memory.peak_rss_bytes >= memory.current_rss_bytes

    profiler = PipelineProfiler()
    profiler.start_pipeline()
    summary = profiler.summary()
    assert summary["peak_rss_bytes"] >= summary["current_rss_bytes"] > 0

    with pytest.raises(ResourceLimitError):
        SAFE_16GB.validate_request(
            atom_count=5000,
            analysis_workers=3,
            available_memory_bytes=16 * 1024**3,
        )


def test_recovery_crawler_runs_two_static_workers_with_contained_outputs(
    tmp_path: Path,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from src.parallel_crawler import ParallelCrawler

    crawler = ParallelCrawler(
        max_workers=2,
        explicit_recovery_override=True,
        output_dir=str(tmp_path / "experimental"),
        checkpoint_dir=str(tmp_path / "checkpoints"),
        _executor_class=ThreadPoolExecutor,
    )

    def fake_batch(pdb_id, *_args):
        return {"pdb_id": pdb_id, "status": "success", "runtime": 0.01}

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("src.parallel_crawler._analyze_single_protein", fake_batch)
        results = crawler.process_pdb_list(["1CBS", "1AKE"], resume=False)

    assert [result["pdb_id"] for result in results] == ["1CBS", "1AKE"]
    assert all(result["validation_status"] == "experimental_unvalidated" for result in results)
    assert all(result["canonical_eligible"] is False for result in results)
