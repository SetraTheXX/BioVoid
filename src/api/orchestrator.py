"""Single-node in-memory job orchestrator for Phase 6."""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .errors import ApiError
from .models import JobDetailResponse, JobErrorResponse, JobStatus, JobSubmitRequest

Runner = Callable[[JobSubmitRequest], dict[str, Any]]


def utc_now() -> datetime:
    """UTC timestamp helper."""
    return datetime.now(timezone.utc)


@dataclass
class JobRecord:
    """Internal mutable job record."""

    job_id: str
    idempotency_key: str
    payload_hash: str
    request: JobSubmitRequest
    status: JobStatus = JobStatus.QUEUED
    created_at_utc: datetime = field(default_factory=utc_now)
    started_at_utc: datetime | None = None
    finished_at_utc: datetime | None = None
    attempts: int = 0
    result: dict[str, Any] | None = None
    error: JobErrorResponse | None = None

    def to_response(self) -> JobDetailResponse:
        return JobDetailResponse(
            job_id=self.job_id,
            status=self.status,
            created_at_utc=self.created_at_utc,
            started_at_utc=self.started_at_utc,
            finished_at_utc=self.finished_at_utc,
            attempts=self.attempts,
            idempotency_key=self.idempotency_key,
            request=self.request,
            result=self.result,
            error=self.error,
        )


class JobOrchestrator:
    """Thread-safe queue + worker orchestrator with retry and timeout."""

    def __init__(
        self,
        *,
        default_timeout_seconds: float = 60.0,
        default_max_retries: int = 2,
        backoff_base_seconds: float = 0.2,
    ) -> None:
        self.default_timeout_seconds = default_timeout_seconds
        self.default_max_retries = default_max_retries
        self.backoff_base_seconds = backoff_base_seconds

        self._jobs: dict[str, JobRecord] = {}
        self._idempotency_index: dict[str, str] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._runners: dict[str, Runner] = {"quick_probe": self._run_quick_probe}
        self._started_monotonic = time.monotonic()
        self._submitted_count = 0
        self._succeeded_count = 0
        self._failed_count = 0
        self._retried_jobs = 0
        self._latencies_seconds: list[float] = []

    def start(self) -> None:
        """Start background worker thread."""
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="phase6-job-worker",
            daemon=True,
        )
        self._worker.start()

    def stop(self, timeout_seconds: float = 2.0) -> None:
        """Stop worker thread gracefully."""
        self._stop_event.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=timeout_seconds)

    def register_runner(self, job_type: str, runner: Runner) -> None:
        """Register or override a runner for testing/integration."""
        self._runners[job_type] = runner

    def submit(
        self,
        *,
        request: JobSubmitRequest,
        idempotency_key: str,
    ) -> tuple[JobRecord, bool]:
        """
        Submit a job.

        Returns (job_record, idempotent_reused).
        """
        payload_hash = hashlib.sha256(
            json.dumps(request.model_dump(mode="json"), sort_keys=True).encode("utf-8")
        ).hexdigest()

        with self._lock:
            existing_id = self._idempotency_index.get(idempotency_key)
            if existing_id:
                existing = self._jobs[existing_id]
                if existing.payload_hash != payload_hash:
                    raise ApiError(
                        status_code=409,
                        code="IDEMPOTENCY_KEY_CONFLICT",
                        message=(
                            "This idempotency key was already used with a different "
                            "request payload."
                        ),
                        details={"job_id": existing_id},
                    )
                return existing, True

            if request.job_type not in self._runners:
                raise ApiError(
                    status_code=400,
                    code="UNSUPPORTED_JOB_TYPE",
                    message=f"Unsupported job_type: {request.job_type}",
                    details={"supported": sorted(self._runners)},
                )

            job_id = uuid.uuid4().hex
            record = JobRecord(
                job_id=job_id,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                request=request,
            )
            self._jobs[job_id] = record
            self._idempotency_index[idempotency_key] = job_id
            self._submitted_count += 1
            self._queue.put(job_id)
            return record, False

    def get(self, job_id: str) -> JobRecord:
        """Get a job by ID."""
        with self._lock:
            record = self._jobs.get(job_id)
            if not record:
                raise ApiError(
                    status_code=404,
                    code="JOB_NOT_FOUND",
                    message=f"Job not found: {job_id}",
                    details={"job_id": job_id},
                )
            return record

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                self._process_job(job_id)
            finally:
                self._queue.task_done()

    def _process_job(self, job_id: str) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if not record or record.status != JobStatus.QUEUED:
                return
            record.status = JobStatus.RUNNING
            record.started_at_utc = utc_now()

        request = record.request
        timeout_seconds = float(
            request.options.get("timeout_seconds", self.default_timeout_seconds)
        )
        max_retries = int(request.options.get("max_retries", self.default_max_retries))
        runner = self._runners[request.job_type]

        final_error: JobErrorResponse | None = None
        result: dict[str, Any] | None = None

        for attempt in range(1, max_retries + 2):
            with self._lock:
                record.attempts = attempt

            try:
                result = self._run_with_timeout(
                    runner=runner,
                    request=request,
                    timeout_seconds=timeout_seconds,
                )
                final_error = None
                break
            except FuturesTimeoutError:
                final_error = JobErrorResponse(
                    code="JOB_TIMEOUT",
                    message="Job execution timed out.",
                    detail=f"timeout_seconds={timeout_seconds}",
                    attempts=attempt,
                )
            except Exception as exc:  # pragma: no cover - covered via tests
                final_error = JobErrorResponse(
                    code="JOB_EXECUTION_ERROR",
                    message="Job execution failed.",
                    detail=str(exc),
                    attempts=attempt,
                )

            if attempt <= max_retries:
                backoff = self.backoff_base_seconds * (2 ** (attempt - 1))
                time.sleep(backoff)

        with self._lock:
            record.finished_at_utc = utc_now()
            if result is not None:
                record.status = JobStatus.SUCCEEDED
                record.result = result
                record.error = None
                self._succeeded_count += 1
            else:
                record.status = JobStatus.FAILED
                record.result = None
                record.error = final_error
                self._failed_count += 1
            if record.attempts > 1:
                self._retried_jobs += 1
            if record.started_at_utc and record.finished_at_utc:
                latency = (
                    record.finished_at_utc - record.started_at_utc
                ).total_seconds()
                self._latencies_seconds.append(latency)

    def ops_metrics(self) -> dict[str, Any]:
        """Return operational metrics snapshot for dashboarding."""
        with self._lock:
            completed = self._succeeded_count + self._failed_count
            latencies = list(self._latencies_seconds)
            avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
            p95_latency = 0.0
            if latencies:
                sorted_lat = sorted(latencies)
                idx = max(0, int(0.95 * (len(sorted_lat) - 1)))
                p95_latency = sorted_lat[idx]

            return {
                "uptime_seconds": round(time.monotonic() - self._started_monotonic, 3),
                "worker_alive": bool(self._worker and self._worker.is_alive()),
                "queue_depth": self._queue.qsize(),
                "submitted_jobs": self._submitted_count,
                "completed_jobs": completed,
                "succeeded_jobs": self._succeeded_count,
                "failed_jobs": self._failed_count,
                "retried_jobs": self._retried_jobs,
                "avg_job_latency_seconds": round(avg_latency, 6),
                "p95_job_latency_seconds": round(p95_latency, 6),
            }

    @staticmethod
    def _run_with_timeout(
        *,
        runner: Runner,
        request: JobSubmitRequest,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(runner, request)
            return fut.result(timeout=timeout_seconds)

    @staticmethod
    def _run_quick_probe(request: JobSubmitRequest) -> dict[str, Any]:
        """Deterministic lightweight probe to validate orchestration flow."""
        pdb_id = request.input.pdb_id.upper()
        checksum = sum(ord(ch) for ch in pdb_id)
        probe_score = round((checksum % 100) / 100.0, 4)
        return {
            "engine": "phase6.quick_probe",
            "pdb_id": pdb_id,
            "probe_score": probe_score,
            "recommendation": "follow_up" if probe_score >= 0.5 else "review",
            "canonical_lock": {
                "tolerance": 8.0,
                "top_n": 20,
                "druggable_only": True,
            },
        }
