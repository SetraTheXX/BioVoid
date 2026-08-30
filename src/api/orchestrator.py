"""Single-node job orchestrator for the local BioVoid API."""

from __future__ import annotations

import hashlib
import json
import logging
import multiprocessing
import os
import queue
import shutil
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import ApiError
from .models import JobDetailResponse, JobErrorResponse, JobStatus, JobSubmitRequest
from ..resources import ResourceLimitError

logger = logging.getLogger(__name__)
Runner = Callable[[JobSubmitRequest], dict[str, Any]]
ExecutionMode = str
PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_JOB_RUNS_ROOT = (PROJECT_ROOT / "data" / "runtime" / "runs" / "api").resolve()


class JobCancelledError(RuntimeError):
    """Raised when execution observes a user cancellation."""


def _process_runner_entry(
    runner: Runner,
    request: JobSubmitRequest,
    connection: Any,
    execution_id: str | None,
) -> None:
    """Execute one runner in a child process and return a serializable envelope."""
    try:
        if execution_id:
            os.environ["BIOVOID_JOB_ID"] = execution_id
        connection.send(("ok", runner(request)))
    except ResourceLimitError as exc:
        connection.send(("resource_limit", str(exc)))
    except BaseException as exc:
        connection.send(("error", type(exc).__name__, str(exc)))
    finally:
        connection.close()


def utc_now() -> datetime:
    """UTC timestamp helper."""
    return datetime.now(timezone.utc)


def cleanup_job_workspace(
    job_id: str,
    *,
    root: Path = API_JOB_RUNS_ROOT,
) -> bool:
    """Remove only the isolated workspace root belonging to one API job."""
    if not job_id or any(character not in "0123456789abcdef" for character in job_id.lower()):
        raise ValueError("job_id must be a hexadecimal identifier")
    resolved_root = root.resolve()
    target = (resolved_root / job_id).resolve()
    if target.parent != resolved_root:
        raise ValueError("job workspace escaped the configured API run root")
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


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
        state_path: str | Path | None = None,
    ) -> None:
        self.default_timeout_seconds = default_timeout_seconds
        self.default_max_retries = default_max_retries
        self.backoff_base_seconds = backoff_base_seconds

        self._jobs: dict[str, JobRecord] = {}
        self._idempotency_index: dict[str, str] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._runners: dict[str, Runner] = {
            "quick_probe": type(self)._run_quick_probe,
            "full_analysis": type(self)._run_full_analysis,
        }
        self._runner_modes: dict[str, ExecutionMode] = {
            "quick_probe": "thread",
            "full_analysis": "process",
        }
        self._started_monotonic = time.monotonic()
        self._submitted_count = 0
        self._succeeded_count = 0
        self._failed_count = 0
        self._retried_jobs = 0
        self._cancelled_count = 0
        self._latencies_seconds: list[float] = []
        self._state_path = Path(state_path) if state_path is not None else None
        self._state_conn: sqlite3.Connection | None = None
        if self._state_path is not None:
            self._initialize_state_store()
            self._restore_state()

    def _initialize_state_store(self) -> None:
        assert self._state_path is not None
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_conn = sqlite3.connect(
            self._state_path,
            timeout=30,
            check_same_thread=False,
        )
        self._state_conn.execute("PRAGMA journal_mode = WAL")
        self._state_conn.execute("PRAGMA synchronous = FULL")
        self._state_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        self._state_conn.commit()

    def _persist_record(self, record: JobRecord) -> None:
        if self._state_conn is None:
            return
        payload = {
            "payload_hash": record.payload_hash,
            "record": record.to_response().model_dump(mode="json"),
        }
        self._state_conn.execute(
            """
            INSERT INTO jobs(job_id, payload_json, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(job_id) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (record.job_id, json.dumps(payload, sort_keys=True)),
        )
        self._state_conn.commit()

    def _restore_state(self) -> None:
        assert self._state_conn is not None
        rows = self._state_conn.execute(
            "SELECT payload_json FROM jobs ORDER BY updated_at, job_id"
        ).fetchall()
        for row in rows:
            payload = json.loads(str(row[0]))
            detail = JobDetailResponse.model_validate(payload["record"])
            record = JobRecord(
                job_id=detail.job_id,
                idempotency_key=detail.idempotency_key,
                payload_hash=str(payload["payload_hash"]),
                request=detail.request,
                status=detail.status,
                created_at_utc=detail.created_at_utc,
                started_at_utc=detail.started_at_utc,
                finished_at_utc=detail.finished_at_utc,
                attempts=detail.attempts,
                result=detail.result,
                error=detail.error,
            )
            if record.status is JobStatus.RUNNING:
                record.status = JobStatus.FAILED
                record.finished_at_utc = utc_now()
                record.error = JobErrorResponse(
                    code="PROCESS_RESTARTED",
                    message="The API process restarted while the job was running.",
                    attempts=record.attempts,
                )
            self._jobs[record.job_id] = record
            self._idempotency_index[record.idempotency_key] = record.job_id
            self._cancel_events[record.job_id] = threading.Event()
            if record.status is JobStatus.QUEUED:
                self._queue.put(record.job_id)
            elif record.status is JobStatus.SUCCEEDED:
                self._succeeded_count += 1
            elif record.status is JobStatus.CANCELLED:
                self._cancelled_count += 1
            elif record.status is JobStatus.FAILED:
                self._failed_count += 1
            self._persist_record(record)
        self._submitted_count = len(self._jobs)

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

    def register_runner(
        self,
        job_type: str,
        runner: Runner,
        *,
        execution_mode: ExecutionMode = "thread",
    ) -> None:
        """Register or override a runner for testing/integration."""
        if execution_mode not in {"thread", "process"}:
            raise ValueError("execution_mode must be 'thread' or 'process'")
        self._runners[job_type] = runner
        self._runner_modes[job_type] = execution_mode

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
            self._cancel_events[job_id] = threading.Event()
            self._submitted_count += 1
            self._persist_record(record)
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
            except BaseException as exc:
                logger.exception("Worker boundary contained an unexpected error for %s", job_id)
                with self._lock:
                    record = self._jobs.get(job_id)
                    if record and record.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                        record.status = JobStatus.FAILED
                        record.finished_at_utc = utc_now()
                        record.error = JobErrorResponse(
                            code="WORKER_BOUNDARY_ERROR",
                            message="Worker contained an unexpected job error.",
                            detail=str(exc),
                            attempts=record.attempts,
                        )
                        self._failed_count += 1
                        self._persist_record(record)
            finally:
                self._queue.task_done()

    def _process_job(self, job_id: str) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if not record or record.status != JobStatus.QUEUED:
                return
            record.status = JobStatus.RUNNING
            record.started_at_utc = utc_now()
            self._persist_record(record)

        request = record.request
        timeout_seconds = float(
            request.options.get("timeout_seconds", self.default_timeout_seconds)
        )
        default_retries = 0 if request.job_type == "full_analysis" else self.default_max_retries
        max_retries = int(request.options.get("max_retries", default_retries))
        runner = self._runners[request.job_type]
        execution_mode = self._runner_modes.get(request.job_type, "thread")
        cancel_event = self._cancel_events[job_id]

        final_error: JobErrorResponse | None = None
        result: dict[str, Any] | None = None

        for attempt in range(1, max_retries + 2):
            with self._lock:
                if cancel_event.is_set():
                    break
                record.attempts = attempt
                self._persist_record(record)

            try:
                result = self._run_with_timeout(
                    runner=runner,
                    request=request,
                    timeout_seconds=timeout_seconds,
                    execution_mode=execution_mode,
                    cancel_event=cancel_event,
                    execution_id=job_id,
                )
                final_error = None
                break
            except JobCancelledError:
                break
            except FuturesTimeoutError:
                final_error = JobErrorResponse(
                    code="JOB_TIMEOUT",
                    message="Job execution timed out.",
                    detail=f"timeout_seconds={timeout_seconds}",
                    attempts=attempt,
                )
            except ResourceLimitError as exc:
                final_error = JobErrorResponse(
                    code="RESOURCE_LIMIT",
                    message=(
                        "Job rejected by the active resource safety profile. "
                        "Free available resources or review the request limits."
                    ),
                    detail=str(exc),
                    attempts=attempt,
                )
            except Exception as exc:  # pragma: no cover - covered via tests
                final_error = JobErrorResponse(
                    code="JOB_EXECUTION_ERROR",
                    message="Job execution failed.",
                    detail=str(exc),
                    attempts=attempt,
                )

            if attempt <= max_retries and not cancel_event.is_set():
                backoff = self.backoff_base_seconds * (2 ** (attempt - 1))
                time.sleep(backoff)

        with self._lock:
            if cancel_event.is_set() or record.status is JobStatus.CANCELLED:
                self._persist_record(record)
                return
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
                latency = (record.finished_at_utc - record.started_at_utc).total_seconds()
                self._latencies_seconds.append(latency)
            self._persist_record(record)

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
                "cancelled_jobs": self._cancelled_count,
                "avg_job_latency_seconds": round(avg_latency, 6),
                "p95_job_latency_seconds": round(p95_latency, 6),
                "state_persistence": (
                    "sqlite" if self._state_conn is not None else "in_memory_volatile"
                ),
            }

    @staticmethod
    def _run_with_timeout(
        *,
        runner: Runner,
        request: JobSubmitRequest,
        timeout_seconds: float,
        execution_mode: ExecutionMode = "thread",
        cancel_event: threading.Event | None = None,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        if execution_mode == "process":
            context = multiprocessing.get_context("spawn")
            parent_connection, child_connection = context.Pipe(duplex=False)
            process = context.Process(
                target=_process_runner_entry,
                args=(runner, request, child_connection, execution_id),
                daemon=True,
            )
            process.start()
            child_connection.close()
            try:
                deadline = time.monotonic() + timeout_seconds
                while not parent_connection.poll(0.05):
                    if cancel_event is not None and cancel_event.is_set():
                        process.terminate()
                        process.join(timeout=1.0)
                        if process.is_alive():
                            process.kill()
                            process.join(timeout=1.0)
                        if execution_id:
                            cleanup_job_workspace(execution_id)
                        raise JobCancelledError()
                    if time.monotonic() >= deadline:
                        process.terminate()
                        process.join(timeout=1.0)
                        if process.is_alive():
                            process.kill()
                            process.join(timeout=1.0)
                        if execution_id:
                            cleanup_job_workspace(execution_id)
                        raise FuturesTimeoutError()
                envelope = parent_connection.recv()
            finally:
                parent_connection.close()
                if process.is_alive():
                    process.join(timeout=0.2)

            if envelope[0] == "resource_limit":
                raise ResourceLimitError(str(envelope[1]))
            if envelope[0] == "error":
                raise RuntimeError(f"{envelope[1]}: {envelope[2]}")
            return envelope[1]

        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(runner, request)
            result = fut.result(timeout=timeout_seconds)
            if cancel_event is not None and cancel_event.is_set():
                raise JobCancelledError()
            return result

    def list_jobs(
        self,
        status_filter: str | None = None,
        limit: int = 50,
    ) -> list[JobRecord]:
        """List jobs, optionally filtered by status."""
        with self._lock:
            jobs = list(self._jobs.values())

        if status_filter:
            jobs = [j for j in jobs if j.status == status_filter]

        jobs.sort(key=lambda j: j.created_at_utc, reverse=True)
        return jobs[:limit]

    def cancel(self, job_id: str) -> JobRecord:
        """Cancel a queued or running job and preserve cancellation as terminal."""
        with self._lock:
            record = self._jobs.get(job_id)
            if not record:
                raise ApiError(
                    status_code=404,
                    code="JOB_NOT_FOUND",
                    message=f"Job not found: {job_id}",
                )
            if record.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
                raise ApiError(
                    status_code=409,
                    code="JOB_NOT_CANCELLABLE",
                    message=f"Job {job_id} is already terminal and cannot be cancelled.",
                )
            self._cancel_events[job_id].set()
            record.status = JobStatus.CANCELLED
            record.finished_at_utc = utc_now()
            record.error = JobErrorResponse(
                code="CANCELLED",
                message="Job cancelled by user.",
                attempts=0,
            )
            self._cancelled_count += 1
            self._persist_record(record)
            return record

    @staticmethod
    def _run_quick_probe(request: JobSubmitRequest) -> dict[str, Any]:
        """Return an operational heartbeat without scientific interpretation."""
        return {
            "engine": "biovoid.orchestration_probe",
            "pdb_id": request.input.pdb_id.upper(),
            "probe_kind": "operational_only",
            "scientific_result": False,
        }

    @staticmethod
    def _run_full_analysis(request: JobSubmitRequest) -> dict[str, Any]:
        """Run the complete BioVoid analysis pipeline and save to Atlas DB."""
        import sys

        project_root = PROJECT_ROOT
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from main import BioVoidPipeline
        from src.structure_preparation import PreparationConfig, StructureSource

        pdb_id = request.input.pdb_id.upper()
        options = request.options
        n_frames = options.n_frames or 4
        profile = options.profile
        motion_aware = options.mode == "motion_aware"
        source_provider = options.structure_source
        representation = options.representation
        assembly_id = options.assembly_id
        chains = options.chains
        structure_source = StructureSource(
            provider=source_provider,
            identifier=pdb_id,
            representation=representation,
            assembly_id=assembly_id if representation == "biological_assembly" else None,
        )
        preparation_config = PreparationConfig(chain_ids=chains)
        job_id = os.environ.get("BIOVOID_JOB_ID")
        output_root = API_JOB_RUNS_ROOT / job_id if job_id else project_root / "data/runtime/runs"

        logger.info(
            "Starting full analysis for %s (samples_per_mode=%d, profile=%s)",
            pdb_id,
            n_frames,
            profile,
        )

        pipeline = BioVoidPipeline(
            pdb_id=pdb_id,
            n_frames=n_frames,
            profile=profile,
            use_cache=True,
            multiframe=motion_aware,
            allow_experimental=motion_aware,
            structure_source=structure_source,
            preparation_config=preparation_config,
            output_dir=str(output_root),
        )
        report = pipeline.run()

        report["engine"] = "biovoid.full_analysis"
        report["analysis_contract"] = {
            "preparation_policy_version": report.get("preparation", {}).get(
                "policy_version",
                "structure-preparation-v1",
            ),
            "detector_version": report.get("static_detector", {}).get(
                "detector_version",
                "unknown",
            ),
            "scoring_contract_version": report.get("scoring", {}).get(
                "contract_version",
                "unknown",
            ),
            "ranking_contract": report.get("scoring", {}).get(
                "ranking_contract_version",
                "unknown",
            ),
            "validation_status": report.get("validation_status", "unknown"),
            "canonical_eligible": bool(report.get("canonical_eligible", False)),
        }

        return report
