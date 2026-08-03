"""Tests for Phase 6 Step 4 ops and release guard layer."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.orchestrator import JobOrchestrator
from src.api.rate_limit import InMemoryRateLimiter


def _build_client() -> TestClient:
    orchestrator = JobOrchestrator(
        default_timeout_seconds=1,
        default_max_retries=1,
        backoff_base_seconds=0.01,
    )
    limiter = InMemoryRateLimiter(max_requests=10_000, window_seconds=60)
    return TestClient(create_app(orchestrator=orchestrator, rate_limiter=limiter))


def _wait_terminal(client: TestClient, job_id: str, timeout_seconds: float = 5.0) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        payload = client.get(f"/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            return payload
        time.sleep(0.02)
    raise AssertionError("job did not finish in time")


def test_correlation_id_echoed_from_request_header() -> None:
    with _build_client() as client:
        response = client.get("/health", headers={"X-Correlation-ID": "cid-test-123"})
        assert response.status_code == 200
        assert response.headers["X-Correlation-ID"] == "cid-test-123"
        assert response.json()["correlation_id"] == "cid-test-123"


def test_correlation_id_generated_when_missing() -> None:
    with _build_client() as client:
        response = client.get("/health")
        assert response.status_code == 200
        cid = response.headers.get("X-Correlation-ID")
        assert isinstance(cid, str)
        assert len(cid) >= 16
        assert response.json()["correlation_id"] == cid


def test_ops_metrics_dashboard_shape_and_counts() -> None:
    with _build_client() as client:
        job_ids: list[str] = []
        for idx in range(3):
            resp = client.post(
                "/jobs",
                headers={"Idempotency-Key": f"ops-metric-{idx}"},
                json={
                    "job_type": "quick_probe",
                    "input": {"pdb_id": f"1C{idx}S"},
                    "options": {"timeout_seconds": 1, "max_retries": 1},
                },
            )
            assert resp.status_code == 202
            job_ids.append(resp.json()["job_id"])

        for job_id in job_ids:
            _wait_terminal(client, job_id)

        metrics = client.get("/ops/metrics").json()
        assert metrics["worker_alive"] is True
        assert metrics["submitted_jobs"] >= 3
        assert metrics["completed_jobs"] >= 3
        assert metrics["succeeded_jobs"] >= 3
        assert metrics["failed_jobs"] >= 0
        assert metrics["queue_depth"] >= 0
        assert metrics["p95_job_latency_seconds"] >= 0
        assert metrics["avg_job_latency_seconds"] >= 0
        assert isinstance(metrics["correlation_id"], str)
