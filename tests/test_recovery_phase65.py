"""Phase 6.5 scientific-contract and product-safety regressions."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient


def _pocket(local_id: str, *, rank: int, score: float, tier: str) -> dict:
    return {
        "id": local_id,
        "pocket_id": local_id,
        "rank": rank,
        "center": [float(rank), 2.0, 3.0],
        "volume": 300.0 + rank,
        "radius_geom": 2.0,
        "radius_clear": 1.5,
        "merged_vertices": 4,
        "hydrophobic_ratio": 0.5,
        "polar_atoms": 2,
        "bio_score": score,
        "heuristic_quality_tier": tier,
        "druggability_class": tier,
        "heuristic_shortlist": tier == "high",
        "score_components": {
            "volume_score": 0.5,
            "hydrophobicity_score": 0.5,
            "enclosure_score": 0.7,
            "depth_score": 0.6,
            "sphericity": 0.4,
        },
        "scoring_measurements": {
            "schema_version": "pocket-scoring-measurements-v1",
            "raw_measurements": {"volume": 300.0 + rank},
            "normalized_metrics": {
                "volume": 0.5,
                "hydrophobicity": 0.5,
                "enclosure": 0.7,
                "depth": 0.6,
            },
        },
    }


def _report(
    run_id: str,
    prepared_path: Path,
    pockets: list[dict],
    *,
    prepared_sha256: str | None = None,
) -> dict:
    prepared_hash = prepared_sha256 or hashlib.sha256(prepared_path.read_bytes()).hexdigest()
    return {
        "run_id": run_id,
        "run_workspace": str(prepared_path.parents[1]),
        "pdb_id": "TEST",
        "structure_source": {
            "provider": "local",
            "identifier": "TEST",
            "representation": "asymmetric_unit",
        },
        "runtime_seconds": 0.2,
        "total_cavities": len(pockets),
        "cavities": pockets,
        "provenance": {
            "input_sha256": "1" * 64,
            "prepared_sha256": prepared_hash,
            "prepared_structure_path": str(prepared_path),
            "preparation_config_sha256": "3" * 64,
            "preparation_report_sha256": "4" * 64,
            "code_identity_sha256": "5" * 64,
            "environment_identity_sha256": "6" * 64,
        },
        "static_detector": {
            "detector_version": "canonical-static-v1",
            "detector_config_sha256": "7" * 64,
            "atom_policy_version": "protein-heavy-bondi-v1",
        },
        "scoring": {
            "contract_version": "heuristic-pocket-ranking-v1",
            "profile_manifest": {
                "profile_id": "default",
                "config_sha256": "8" * 64,
            },
        },
        "validation_status": "recovery_unvalidated",
        "canonical_eligible": False,
    }


def _seed_atlas(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    from src.atlas_v1 import AtlasV1

    app_module = importlib.import_module("src.api.app")
    first = tmp_path / "runs" / "run-first" / "preparation" / "prepared_detector.pdb"
    second = tmp_path / "runs" / "run-second" / "preparation" / "prepared_detector.pdb"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("HEADER    FIRST RUN\nEND\n", encoding="ascii")
    second.write_text("HEADER    SECOND RUN\nEND\n", encoding="ascii")

    atlas_path = tmp_path / "atlas.sqlite"
    with AtlasV1(atlas_path) as atlas:
        atlas.persist_report(
            _report(
                "run-first",
                first,
                [_pocket("FIRST-1", rank=1, score=0.25, tier="low")],
            )
        )
        atlas.persist_report(
            _report(
                "run-second",
                second,
                [
                    _pocket("SECOND-1", rank=1, score=0.72, tier="high"),
                    _pocket("SECOND-2", rank=2, score=0.45, tier="medium"),
                ],
            )
        )

    monkeypatch.setattr(app_module, "ATLAS_DB_PATH", atlas_path)
    return atlas_path, first, second


def test_scoring_exposes_heuristic_shortlist_not_validated_druggability() -> None:
    from src.scoring import score_from_measurements

    measurements = {
        "schema_version": "pocket-scoring-measurements-v1",
        "raw_measurements": {},
        "normalized_metrics": {
            "volume": 1.0,
            "hydrophobicity": 1.0,
            "enclosure": 1.0,
            "depth": 1.0,
        },
        "shape_metrics": {},
    }

    result = score_from_measurements(measurements)

    assert result["heuristic_quality_tier"] == "high"
    assert result["heuristic_shortlist"] is True
    assert "druggable" not in result
    assert result["score_semantics"] == "heuristic_ranking_not_probability"


def test_atlas_default_query_is_run_scoped_paginated_and_does_not_hide_pockets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from src.api.app import create_app

    _seed_atlas(tmp_path, monkeypatch)

    with TestClient(create_app()) as client:
        response = client.get("/atlas/pockets?limit=1&offset=0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["total"] == 3
    assert payload["items"][0]["run_id"] == "run-second"
    assert payload["items"][0]["validation_status"] == "recovery_unvalidated"
    assert payload["items"][0]["canonical_eligible"] is False
    assert payload["items"][0]["heuristic_shortlist"] is True


def test_api_error_envelope_exposes_correlation_id() -> None:
    from src.api.app import create_app

    with TestClient(create_app()) as client:
        response = client.get(
            "/atlas/pockets?druggability_class=invalid",
            headers={"X-Correlation-ID": "phase7-error-1"},
        )

    assert response.status_code == 400
    assert response.headers["X-Correlation-ID"] == "phase7-error-1"
    assert response.json()["error"]["correlation_id"] == "phase7-error-1"


def test_protein_detail_never_merges_runs_and_allows_explicit_run_selection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from src.api.app import create_app

    _seed_atlas(tmp_path, monkeypatch)

    with TestClient(create_app()) as client:
        latest = client.get("/protein/TEST/detail")
        first = client.get("/protein/TEST/detail?run_id=run-first")

    assert latest.status_code == 200
    assert latest.json()["run_id"] == "run-second"
    assert {p["pocket_id"] for p in latest.json()["pockets"]} == {
        "SECOND-1",
        "SECOND-2",
    }
    assert latest.json()["available_runs"] == ["run-second", "run-first"]
    assert first.status_code == 200
    assert first.json()["run_id"] == "run-first"
    assert [p["pocket_id"] for p in first.json()["pockets"]] == ["FIRST-1"]


def test_structure_endpoint_serves_and_verifies_the_selected_run_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from src.api.app import create_app

    _, first_path, second_path = _seed_atlas(tmp_path, monkeypatch)

    with TestClient(create_app()) as client:
        latest = client.get("/protein/TEST/structure")
        first = client.get("/protein/TEST/structure?run_id=run-first")

    assert latest.status_code == 200
    assert latest.text == second_path.read_text(encoding="ascii")
    assert latest.headers["X-BioVoid-Run-ID"] == "run-second"
    assert (
        latest.headers["X-BioVoid-Prepared-SHA256"]
        == hashlib.sha256(second_path.read_bytes()).hexdigest()
    )
    assert first.status_code == 200
    assert first.text == first_path.read_text(encoding="ascii")
    assert first.headers["X-BioVoid-Run-ID"] == "run-first"


def test_structure_endpoint_fails_closed_on_artifact_hash_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from src.api.app import create_app
    from src.atlas_v1 import AtlasV1

    app_module = importlib.import_module("src.api.app")
    prepared = tmp_path / "runs" / "bad-run" / "preparation" / "prepared_detector.pdb"
    prepared.parent.mkdir(parents=True)
    prepared.write_text("HEADER    TAMPERED\nEND\n", encoding="ascii")
    atlas_path = tmp_path / "atlas.sqlite"
    with AtlasV1(atlas_path) as atlas:
        atlas.persist_report(
            _report(
                "bad-run",
                prepared,
                [_pocket("BAD-1", rank=1, score=0.7, tier="high")],
                prepared_sha256="a" * 64,
            )
        )
    monkeypatch.setattr(app_module, "ATLAS_DB_PATH", atlas_path)

    with TestClient(create_app()) as client:
        response = client.get("/protein/TEST/structure?run_id=bad-run")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PREPARED_STRUCTURE_HASH_MISMATCH"


def test_safe_16gb_static_preflight_bounds_atoms_candidates_and_memory() -> None:
    from src.resources import ResourceLimitError, SAFE_16GB

    estimate = SAFE_16GB.validate_static_request(
        atom_count=1200,
        candidate_count=800,
        available_memory_bytes=12 * 1024**3,
    )
    assert 0 < estimate < SAFE_16GB.soft_memory_budget_bytes

    with pytest.raises(ResourceLimitError, match="static detector"):
        SAFE_16GB.validate_static_request(
            atom_count=SAFE_16GB.max_static_atoms + 1,
            available_memory_bytes=12 * 1024**3,
        )
    with pytest.raises(ResourceLimitError, match="candidate"):
        SAFE_16GB.validate_static_request(
            atom_count=1200,
            candidate_count=SAFE_16GB.max_static_candidates + 1,
            available_memory_bytes=12 * 1024**3,
        )
    with pytest.raises(ResourceLimitError, match="available memory"):
        SAFE_16GB.validate_static_request(
            atom_count=1200,
            candidate_count=800,
            available_memory_bytes=2 * 1024**3,
        )


def test_quick_probe_is_explicitly_operational_and_has_no_scientific_score() -> None:
    from src.api.models import JobInput, JobSubmitRequest
    from src.api.orchestrator import JobOrchestrator

    result = JobOrchestrator._run_quick_probe(
        JobSubmitRequest(job_type="quick_probe", input=JobInput(pdb_id="1CBS"))
    )

    assert result == {
        "engine": "biovoid.orchestration_probe",
        "pdb_id": "1CBS",
        "probe_kind": "operational_only",
        "scientific_result": False,
    }


def test_product_evaluator_rejects_detector_only_or_unversioned_ranking() -> None:
    from src.evaluator_format import adapt_biovoid_product_pockets

    pocket = {
        "pocket_id": "BV-1",
        "center": [1.0, 2.0, 3.0],
        "volume": 400.0,
        "rank": 1,
        "bio_score": 0.7,
    }
    with pytest.raises(ValueError, match="Product evaluation requires"):
        adapt_biovoid_product_pockets("TEST", [pocket])

    pocket["ranking_contract_version"] = "product-heuristic-ranking-v1"
    record = adapt_biovoid_product_pockets("TEST", [pocket])

    assert record.pockets[0].rank == 1
    assert record.pockets[0].score == 0.7
    assert record.provenance == {"ranking_contract_version": "product-heuristic-ranking-v1"}


def test_job_state_and_idempotency_survive_orchestrator_restart(tmp_path: Path) -> None:
    from src.api.models import JobInput, JobSubmitRequest, JobStatus
    from src.api.orchestrator import JobOrchestrator

    state_path = tmp_path / "jobs.sqlite"
    request = JobSubmitRequest(
        job_type="quick_probe",
        input=JobInput(pdb_id="1CBS"),
    )
    first = JobOrchestrator(state_path=state_path)
    record, reused = first.submit(request=request, idempotency_key="stable-key")
    assert reused is False
    first.stop()

    restored = JobOrchestrator(state_path=state_path)
    restored_record = restored.get(record.job_id)
    reused_record, reused = restored.submit(
        request=request,
        idempotency_key="stable-key",
    )

    assert restored_record.status is JobStatus.QUEUED
    assert reused is True
    assert reused_record.job_id == record.job_id
    assert restored.ops_metrics()["state_persistence"] == "sqlite"
    restored.stop()


def test_running_job_cancellation_is_terminal_and_not_overwritten() -> None:
    from src.api.models import JobInput, JobSubmitRequest, JobStatus
    from src.api.orchestrator import JobOrchestrator

    orchestrator = JobOrchestrator(default_max_retries=0)

    def slow_runner(_request: JobSubmitRequest) -> dict:
        time.sleep(0.15)
        return {"unexpected": "success"}

    orchestrator.register_runner("quick_probe", slow_runner)
    orchestrator.start()
    record, _ = orchestrator.submit(
        request=JobSubmitRequest(
            job_type="quick_probe",
            input=JobInput(pdb_id="1CBS"),
        ),
        idempotency_key="cancel-running",
    )
    deadline = time.time() + 2
    while orchestrator.get(record.job_id).status is JobStatus.QUEUED:
        assert time.time() < deadline
        time.sleep(0.005)

    cancelled = orchestrator.cancel(record.job_id)
    time.sleep(0.2)
    final = orchestrator.get(record.job_id)
    orchestrator.stop()

    assert cancelled.status is JobStatus.CANCELLED
    assert final.status is JobStatus.CANCELLED
    assert final.result is None
    assert final.error is not None
    assert final.error.code == "CANCELLED"


def test_full_analysis_rejects_automatic_retry_configuration() -> None:
    from pydantic import ValidationError

    from src.api.models import JobInput, JobOptions, JobSubmitRequest

    with pytest.raises(ValidationError, match="full_analysis"):
        JobSubmitRequest(
            job_type="full_analysis",
            input=JobInput(pdb_id="1CBS"),
            options=JobOptions(max_retries=1),
        )


def test_motion_request_respects_total_safe_sample_budget() -> None:
    from pydantic import ValidationError

    from src.api.models import JobInput, JobOptions, JobSubmitRequest

    accepted = JobSubmitRequest(
        job_type="full_analysis",
        input=JobInput(pdb_id="1CBS"),
        options=JobOptions(mode="motion_aware", n_frames=6),
    )
    assert accepted.options.n_frames == 6
    with pytest.raises(ValidationError, match="total samples"):
        JobSubmitRequest(
            job_type="full_analysis",
            input=JobInput(pdb_id="1CBS"),
            options=JobOptions(mode="motion_aware", n_frames=8),
        )


def test_relative_pipeline_paths_are_anchored_to_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from main import PROJECT_ROOT, resolve_project_path

    monkeypatch.chdir(tmp_path)
    assert resolve_project_path("data/runtime/atlas-recovery-v1.sqlite") == (
        PROJECT_ROOT / "data/runtime/atlas-recovery-v1.sqlite"
    )
    absolute = tmp_path / "custom.sqlite"
    assert resolve_project_path(absolute) == absolute


def test_worker_boundary_failure_is_persisted(tmp_path: Path) -> None:
    from src.api.models import JobInput, JobStatus, JobSubmitRequest
    from src.api.orchestrator import JobOrchestrator

    state_path = tmp_path / "jobs.sqlite"
    orchestrator = JobOrchestrator(state_path=state_path)

    def boundary_crash(**_kwargs):
        raise KeyboardInterrupt("synthetic boundary crash")

    orchestrator._run_with_timeout = boundary_crash
    record, _ = orchestrator.submit(
        request=JobSubmitRequest(job_type="quick_probe", input=JobInput(pdb_id="1CBS")),
        idempotency_key="boundary-persistence",
    )
    orchestrator.start()
    deadline = time.monotonic() + 2.0
    while orchestrator.get(record.job_id).status is not JobStatus.FAILED:
        assert time.monotonic() < deadline
        time.sleep(0.01)

    persisted = orchestrator._state_conn.execute(
        "SELECT payload_json FROM jobs WHERE job_id = ?", (record.job_id,)
    ).fetchone()
    assert persisted is not None
    assert '"status": "failed"' in persisted[0]
    orchestrator.stop()
    assert orchestrator._state_conn is not None
    orchestrator._state_conn.close()


def test_pickle_model_loading_requires_explicit_local_trust(tmp_path: Path) -> None:
    from src.ml.classifier import load_model, save_model

    model_path = tmp_path / "local-model.pkl"
    payload = {"model_version": "test-only"}
    save_model(payload, model_path)

    with pytest.raises(ValueError, match="trusted=True"):
        load_model(model_path)

    assert load_model(model_path, trusted=True) == payload


def test_environment_manifest_records_versions_and_lock_identity() -> None:
    from src.cache import compute_environment_identity, environment_manifest

    manifest = environment_manifest()

    assert manifest["dependencies"]["numpy"]
    assert manifest["dependencies"]["biotite"]
    assert manifest["dependency_lock"] == "requirements-lock.txt"
    assert len(manifest["dependency_lock_sha256"]) == 64
    assert len(compute_environment_identity()) == 64


def test_job_workspace_cleanup_is_scoped_to_one_hex_job(tmp_path: Path) -> None:
    from src.api.orchestrator import cleanup_job_workspace

    job_root = tmp_path / "api-runs"
    target = job_root / "a1b2"
    sibling = job_root / "c3d4"
    target.mkdir(parents=True)
    sibling.mkdir()
    (target / "partial.tmp").write_text("partial", encoding="utf-8")

    assert cleanup_job_workspace("a1b2", root=job_root) is True
    assert not target.exists()
    assert sibling.is_dir()
    with pytest.raises(ValueError):
        cleanup_job_workspace("../escape", root=job_root)


def test_generated_frontend_contract_matches_current_openapi() -> None:
    import hashlib
    import json
    import re

    from src.api.app import create_app
    from src.api.orchestrator import JobOrchestrator

    schema = create_app(orchestrator=JobOrchestrator()).openapi()
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
    expected = hashlib.sha256(canonical).hexdigest()
    generated = (Path(__file__).resolve().parents[1] / "frontend/src/types/openapi.d.ts").read_text(
        encoding="utf-8"
    )
    match = re.search(r"BioVoid OpenAPI SHA256: ([0-9a-f]{64})", generated)

    assert match is not None
    assert match.group(1) == expected


def test_public_versions_share_one_pre_1_0_identity() -> None:
    import json
    import tomllib

    from src.version import __version__

    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    frontend = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))

    assert __version__.startswith("0.")
    assert pyproject["project"]["version"] == __version__
    assert frontend["version"] == __version__
