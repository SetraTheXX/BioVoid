"""Phase 6 FastAPI application (Step 2: Backend/API)."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging
import time
from typing import Any
import uuid

from fastapi import FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse

from .errors import ApiError
from .models import (
    ALLOWED_OPTION_KEYS,
    CANONICAL_LOCK_KEYS,
    ErrorEnvelope,
    JobDetailResponse,
    JobStatus,
    JobSubmissionResponse,
    JobSubmitRequest,
)
from .orchestrator import JobOrchestrator
from .portal import render_portal_html
from .rate_limit import InMemoryRateLimiter

LOGGER = logging.getLogger("biovoid.phase6.api")


def _contains_forbidden_lock_keys(payload: dict[str, Any]) -> list[str]:
    """Find canonical lock override attempts recursively."""
    found: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in CANONICAL_LOCK_KEYS:
                    found.append(key)
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(payload)
    return sorted(set(found))


def _validate_options_shape(payload: dict[str, Any]) -> None:
    options = payload.get("options", {})
    if not isinstance(options, dict):
        raise ApiError(
            status_code=400,
            code="INVALID_OPTIONS",
            message="'options' must be an object",
            details={"received_type": type(options).__name__},
        )

    unknown = sorted(k for k in options if k not in ALLOWED_OPTION_KEYS)
    if unknown:
        raise ApiError(
            status_code=400,
            code="UNKNOWN_OPTION_KEYS",
            message="Unknown option keys detected.",
            details={"unknown_keys": unknown, "allowed_keys": sorted(ALLOWED_OPTION_KEYS)},
        )

    timeout_seconds = options.get("timeout_seconds")
    if timeout_seconds is not None:
        if not isinstance(timeout_seconds, (int, float)):
            raise ApiError(
                status_code=400,
                code="INVALID_TIMEOUT",
                message="'timeout_seconds' must be numeric.",
            )
        if timeout_seconds <= 0 or timeout_seconds > 600:
            raise ApiError(
                status_code=400,
                code="INVALID_TIMEOUT",
                message="'timeout_seconds' must be in range (0, 600].",
            )

    max_retries = options.get("max_retries")
    if max_retries is not None:
        if not isinstance(max_retries, int):
            raise ApiError(
                status_code=400,
                code="INVALID_MAX_RETRIES",
                message="'max_retries' must be an integer.",
            )
        if max_retries < 0 or max_retries > 5:
            raise ApiError(
                status_code=400,
                code="INVALID_MAX_RETRIES",
                message="'max_retries' must be in range [0, 5].",
            )

    priority = options.get("priority")
    if priority is not None:
        if priority not in {"normal", "high"}:
            raise ApiError(
                status_code=400,
                code="INVALID_PRIORITY",
                message="'priority' must be one of ['normal', 'high'].",
            )


def create_app(
    *,
    orchestrator: JobOrchestrator | None = None,
    rate_limiter: InMemoryRateLimiter | None = None,
) -> FastAPI:
    """Build a configured FastAPI application."""
    api_orchestrator = orchestrator or JobOrchestrator()
    limiter = rate_limiter or InMemoryRateLimiter(max_requests=120, window_seconds=60)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.orchestrator = api_orchestrator
        app.state.rate_limiter = limiter
        api_orchestrator.start()
        try:
            yield
        finally:
            api_orchestrator.stop()

    app = FastAPI(
        title="BioVoid Phase 6 Job API",
        version="6.0.0-step4",
        description=(
            "Single-node job orchestration API for controlled Phase 6 productization."
        ),
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):
        incoming = request.headers.get("X-Correlation-ID", "").strip()
        correlation_id = incoming or uuid.uuid4().hex
        request.state.correlation_id = correlation_id
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            LOGGER.exception(
                "request_failed method=%s path=%s correlation_id=%s",
                request.method,
                request.url.path,
                correlation_id,
            )
            raise
        duration_ms = (time.monotonic() - started) * 1000.0
        response.headers["X-Correlation-ID"] = correlation_id
        LOGGER.info(
            "request method=%s path=%s status=%s correlation_id=%s duration_ms=%.2f",
            request.method,
            request.url.path,
            response.status_code,
            correlation_id,
            duration_ms,
        )
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        payload = ErrorEnvelope(
            error={
                "code": "VALIDATION_ERROR",
                "message": "Request payload validation failed.",
                "details": {"errors": exc.errors()},
            }
        )
        return JSONResponse(status_code=422, content=payload.model_dump())

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        return {
            "status": "ok",
            "correlation_id": getattr(request.state, "correlation_id", None),
        }

    @app.get("/ready")
    async def ready(request: Request) -> dict[str, Any]:
        metrics = app.state.orchestrator.ops_metrics()
        return {
            "status": "ready" if metrics["worker_alive"] else "degraded",
            "worker_alive": metrics["worker_alive"],
            "queue_depth": metrics["queue_depth"],
            "correlation_id": getattr(request.state, "correlation_id", None),
        }

    @app.get("/portal", response_class=HTMLResponse)
    async def portal() -> str:
        return render_portal_html()

    @app.get("/ops/metrics")
    async def ops_metrics(request: Request) -> dict[str, Any]:
        await enforce_rate_limit(request)
        metrics = app.state.orchestrator.ops_metrics()
        metrics["correlation_id"] = getattr(request.state, "correlation_id", None)
        return metrics

    async def enforce_rate_limit(request: Request) -> None:
        client_id = request.client.host if request.client else "unknown"
        allowed, retry_after = app.state.rate_limiter.allow(client_id)
        if not allowed:
            raise ApiError(
                status_code=429,
                code="RATE_LIMIT_EXCEEDED",
                message="Too many requests.",
                details={"retry_after_seconds": retry_after},
            )

    @app.post(
        "/jobs",
        response_model=JobSubmissionResponse,
        responses={400: {"model": ErrorEnvelope}, 409: {"model": ErrorEnvelope}},
    )
    async def submit_job(
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
    ) -> JobSubmissionResponse:
        await enforce_rate_limit(request)

        try:
            raw_payload = await request.json()
        except Exception as exc:
            raise ApiError(
                status_code=400,
                code="INVALID_JSON",
                message="Request body must be valid JSON.",
                details={"detail": str(exc)},
            ) from exc
        if not isinstance(raw_payload, dict):
            raise ApiError(
                status_code=400,
                code="INVALID_PAYLOAD",
                message="JSON payload must be an object.",
            )

        forbidden_keys = _contains_forbidden_lock_keys(raw_payload)
        if forbidden_keys:
            raise ApiError(
                status_code=400,
                code="CANONICAL_LOCK_OVERRIDE_FORBIDDEN",
                message=(
                    "Canonical scientific lock fields cannot be overridden by API requests."
                ),
                details={"forbidden_keys": forbidden_keys},
            )

        _validate_options_shape(raw_payload)

        req_model = JobSubmitRequest.model_validate(raw_payload)
        clean_idempotency_key = idempotency_key.strip()
        if not clean_idempotency_key:
            raise ApiError(
                status_code=400,
                code="INVALID_IDEMPOTENCY_KEY",
                message="Idempotency-Key header cannot be empty.",
            )
        record, reused = app.state.orchestrator.submit(
            request=req_model,
            idempotency_key=clean_idempotency_key,
        )

        response.status_code = 200 if reused else 202
        return JobSubmissionResponse(
            job_id=record.job_id,
            status=record.status,
            idempotent_reused=reused,
            created_at_utc=record.created_at_utc,
        )

    @app.get(
        "/jobs/{job_id}",
        response_model=JobDetailResponse,
        responses={404: {"model": ErrorEnvelope}},
    )
    async def get_job(job_id: str, request: Request) -> JobDetailResponse:
        await enforce_rate_limit(request)
        record = app.state.orchestrator.get(job_id)
        return record.to_response()

    @app.get(
        "/jobs/{job_id}/result",
        responses={404: {"model": ErrorEnvelope}, 409: {"model": ErrorEnvelope}},
    )
    async def download_job_result(job_id: str, request: Request) -> Response:
        await enforce_rate_limit(request)
        record = app.state.orchestrator.get(job_id)
        if record.status != JobStatus.SUCCEEDED:
            raise ApiError(
                status_code=409,
                code="JOB_RESULT_NOT_READY",
                message="Job result is not available yet.",
                details={"job_id": job_id, "status": record.status},
            )
        payload = {
            "job_id": record.job_id,
            "status": record.status,
            "created_at_utc": record.created_at_utc.isoformat(),
            "started_at_utc": (
                record.started_at_utc.isoformat() if record.started_at_utc else None
            ),
            "finished_at_utc": (
                record.finished_at_utc.isoformat() if record.finished_at_utc else None
            ),
            "attempts": record.attempts,
            "request": record.request.model_dump(mode="json"),
            "result": record.result,
        }
        filename = f"biovoid-job-{job_id}.json"
        return Response(
            content=json.dumps(payload, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return app


app = create_app()
