"""Tests for Phase 6 Step 2 backend job API."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.models import JobStatus, JobSubmitRequest
from src.api.orchestrator import JobOrchestrator
from src.api.rate_limit import InMemoryRateLimiter


def _build_client() -> TestClient:
    orchestrator = JobOrchestrator(
        default_timeout_seconds=1,
        default_max_retries=2,
        backoff_base_seconds=0.01,
    )
    limiter = InMemoryRateLimiter(max_requests=10_000, window_seconds=60)
    return TestClient(create_app(orchestrator=orchestrator, rate_limiter=limiter))


def _wait_for_terminal_status(
    client: TestClient, job_id: str, timeout_seconds: float = 5.0
) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        payload = client.get(f"/jobs/{job_id}").json()
        if payload["status"] in {JobStatus.SUCCEEDED.value, JobStatus.FAILED.value}:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach terminal state in time")


def _submit_payload(pdb_id: str = "1CBS", options: dict | None = None) -> dict:
    return {
        "job_type": "quick_probe",
        "input": {"pdb_id": pdb_id},
        "options": options or {},
    }


def test_submit_and_fetch_job_lifecycle() -> None:
    with _build_client() as client:
        response = client.post(
            "/jobs",
            headers={"Idempotency-Key": "idem-lifecycle-1"},
            json=_submit_payload("1CBS"),
        )
        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == JobStatus.QUEUED.value

        final_state = _wait_for_terminal_status(client, payload["job_id"])
        assert final_state["status"] == JobStatus.SUCCEEDED.value
        assert final_state["result"]["pdb_id"] == "1CBS"
        assert final_state["attempts"] >= 1


def test_idempotency_reuse_returns_same_job() -> None:
    with _build_client() as client:
        first = client.post(
            "/jobs",
            headers={"Idempotency-Key": "idem-reuse-1"},
            json=_submit_payload("1AKE"),
        )
        second = client.post(
            "/jobs",
            headers={"Idempotency-Key": "idem-reuse-1"},
            json=_submit_payload("1AKE"),
        )

        assert first.status_code == 202
        assert second.status_code == 200
        assert second.json()["idempotent_reused"] is True
        assert first.json()["job_id"] == second.json()["job_id"]


def test_idempotency_conflict_returns_409() -> None:
    with _build_client() as client:
        client.post(
            "/jobs",
            headers={"Idempotency-Key": "idem-conflict-1"},
            json=_submit_payload("1CBS"),
        )
        conflict = client.post(
            "/jobs",
            headers={"Idempotency-Key": "idem-conflict-1"},
            json=_submit_payload("2VTA"),
        )

        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"


def test_canonical_lock_override_is_rejected() -> None:
    with _build_client() as client:
        response = client.post(
            "/jobs",
            headers={"Idempotency-Key": "idem-lock-1"},
            json={
                "job_type": "quick_probe",
                "input": {"pdb_id": "1CBS"},
                "tolerance": 12.0,
            },
        )
        assert response.status_code == 400
        assert (
            response.json()["error"]["code"]
            == "CANONICAL_LOCK_OVERRIDE_FORBIDDEN"
        )


def test_retry_policy_is_deterministic() -> None:
    with _build_client() as client:
        attempts = {"count": 0}

        def flaky_runner(_: JobSubmitRequest) -> dict:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("transient failure")
            return {"ok": True}

        client.app.state.orchestrator.register_runner("quick_probe", flaky_runner)

        response = client.post(
            "/jobs",
            headers={"Idempotency-Key": "idem-retry-1"},
            json=_submit_payload("1CBS", options={"max_retries": 3, "timeout_seconds": 1}),
        )
        assert response.status_code == 202
        final_state = _wait_for_terminal_status(client, response.json()["job_id"])
        assert final_state["status"] == JobStatus.SUCCEEDED.value
        assert final_state["attempts"] == 3


def test_timeout_and_retry_lead_to_failed_job() -> None:
    with _build_client() as client:
        def slow_runner(_: JobSubmitRequest) -> dict:
            time.sleep(0.1)
            return {"ok": True}

        client.app.state.orchestrator.register_runner("quick_probe", slow_runner)

        response = client.post(
            "/jobs",
            headers={"Idempotency-Key": "idem-timeout-1"},
            json=_submit_payload(
                "1CBS", options={"timeout_seconds": 1e-6, "max_retries": 1}
            ),
        )
        assert response.status_code == 202
        final_state = _wait_for_terminal_status(client, response.json()["job_id"])
        assert final_state["status"] == JobStatus.FAILED.value
        assert final_state["attempts"] == 2
        assert final_state["error"]["code"] == "JOB_TIMEOUT"


def test_fifty_jobs_smoke_no_crash() -> None:
    with _build_client() as client:
        job_ids: list[str] = []
        for idx in range(50):
            response = client.post(
                "/jobs",
                headers={"Idempotency-Key": f"idem-smoke-{idx}"},
                json=_submit_payload(f"A{idx:03d}"),
            )
            assert response.status_code == 202
            job_ids.append(response.json()["job_id"])

        finals = [_wait_for_terminal_status(client, job_id, timeout_seconds=10) for job_id in job_ids]
        assert len(set(job_ids)) == 50
        assert all(item["status"] == JobStatus.SUCCEEDED.value for item in finals)


def test_root_and_dashboard_redirect_to_portal() -> None:
    with _build_client() as client:
        root = client.get("/", follow_redirects=False)
        dashboard = client.get("/dashboard", follow_redirects=False)
        assert root.status_code == 307
        assert dashboard.status_code == 307
        assert root.headers["location"] == "/portal"
        assert dashboard.headers["location"] == "/portal"


def test_atlas_endpoints_shape() -> None:
    with _build_client() as client:
        overview = client.get("/atlas/overview")
        pockets = client.get("/atlas/pockets")
        assert overview.status_code == 200
        assert pockets.status_code == 200

        overview_json = overview.json()
        pockets_json = pockets.json()
        assert "available" in overview_json
        assert "summary" in overview_json
        assert "class_distribution" in overview_json
        assert "items" in pockets_json
        assert "count" in pockets_json


def test_atlas_endpoint_rejects_invalid_class_filter() -> None:
    with _build_client() as client:
        response = client.get("/atlas/pockets?druggability_class=invalid")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_DRUGGABILITY_CLASS"
