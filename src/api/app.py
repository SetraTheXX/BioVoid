"""Phase 6 FastAPI application (Step 2: Backend/API)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .errors import ApiError
from .models import (
    ALLOWED_OPTION_KEYS,
    CANONICAL_LOCK_KEYS,
    ErrorEnvelope,
    JobDetailResponse,
    JobSubmissionResponse,
    JobSubmitRequest,
)
from .orchestrator import JobOrchestrator
from .rate_limit import InMemoryRateLimiter


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
        version="6.0.0-step2",
        description=(
            "Single-node job orchestration API for controlled Phase 6 productization."
        ),
        lifespan=lifespan,
    )

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
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready"}

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

    return app


app = create_app()
