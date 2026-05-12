"""Tests for Phase 6 Step 3 web portal."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.models import JobSubmitRequest
from src.api.orchestrator import JobOrchestrator
from src.api.rate_limit import InMemoryRateLimiter


def _build_client() -> TestClient:
    orchestrator = JobOrchestrator(
        default_timeout_seconds=2,
        default_max_retries=1,
        backoff_base_seconds=0.01,
    )
    limiter = InMemoryRateLimiter(max_requests=10_000, window_seconds=60)
    return TestClient(create_app(orchestrator=orchestrator, rate_limiter=limiter))


def _wait_terminal(client: TestClient, job_id: str, timeout_seconds: float = 5.0) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        data = client.get(f"/jobs/{job_id}").json()
        if data["status"] in {"succeeded", "failed"}:
            return data
        time.sleep(0.02)
    raise AssertionError("job did not finish in time")


def test_portal_page_renders() -> None:
    with _build_client() as client:
        response = client.get("/portal")
        assert response.status_code == 200
        html = response.text
        assert "BioVoid" in html
        assert "Cryptic Pocket Discovery" in html


def test_portal_submit_poll_download_path() -> None:
    with _build_client() as client:
        create = client.post(
            "/jobs",
            headers={"Idempotency-Key": "portal-flow-1"},
            json={
                "job_type": "quick_probe",
                "input": {"pdb_id": "1CBS"},
                "options": {"priority": "normal", "timeout_seconds": 2, "max_retries": 1},
            },
        )
        assert create.status_code == 202
        job_id = create.json()["job_id"]

        final = _wait_terminal(client, job_id)
        assert final["status"] == "succeeded"

        download = client.get(f"/jobs/{job_id}/result")
        assert download.status_code == 200
        assert "attachment; filename=" in download.headers.get("content-disposition", "")
        body = download.json()
        assert body["job_id"] == job_id
        assert body["status"] == "succeeded"
        assert body["result"]["pdb_id"] == "1CBS"


def test_result_endpoint_rejects_when_job_not_ready() -> None:
    with _build_client() as client:

        def slow_runner(_: JobSubmitRequest) -> dict:
            time.sleep(0.4)
            return {"ok": True}

        client.app.state.orchestrator.register_runner("quick_probe", slow_runner)

        create = client.post(
            "/jobs",
            headers={"Idempotency-Key": "portal-not-ready-1"},
            json={
                "job_type": "quick_probe",
                "input": {"pdb_id": "1AKE"},
                "options": {"timeout_seconds": 2, "max_retries": 0},
            },
        )
        assert create.status_code == 202
        job_id = create.json()["job_id"]

        response = client.get(f"/jobs/{job_id}/result")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "JOB_RESULT_NOT_READY"
