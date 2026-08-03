"""FastAPI application for the local BioVoid research prototype."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from src.config import PATHS
from src.atlas_v1 import AtlasV1 as AtlasDB
from src.version import __version__

from .errors import ApiError
from .models import (
    ALLOWED_OPTION_KEYS,
    CANONICAL_LOCK_KEYS,
    AtlasPocketsResponse,
    BatchJobSubmissionResponse,
    BatchJobSubmitRequest,
    ErrorEnvelope,
    JobCancellationResponse,
    JobDetailResponse,
    JobInput,
    JobListResponse,
    JobOptions,
    JobProgressEvent,
    JobStatus,
    JobSubmissionResponse,
    JobSubmitRequest,
    ProteinDetailResponse,
)
from .orchestrator import JobOrchestrator
from .rate_limit import InMemoryRateLimiter

LOGGER = logging.getLogger("biovoid.api")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ATLAS_DB_PATH = PROJECT_ROOT / PATHS.atlas_db
RESULTS_DIR = PROJECT_ROOT / PATHS.results
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
ALLOWED_DRUGGABILITY_CLASSES = {"high", "medium", "low"}


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


def _safe_validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Return JSON-safe Pydantic errors for the public API envelope."""
    errors: list[dict[str, Any]] = []
    for error in exc.errors(include_url=False):
        item = dict(error)
        context = item.get("ctx")
        if isinstance(context, dict):
            item["ctx"] = {key: str(value) for key, value in context.items()}
        errors.append(item)
    return errors


_LOCAL_RESULT_KEYS = frozenset(
    {
        "cache_path",
        "file_path",
        "frame_file",
        "frame_files",
        "frames_dir",
        "manifest",
        "manifest_path",
        "model_path",
        "output_dir",
        "output_path",
        "path",
        "pdb_file",
        "prepared_path",
        "prepared_structure_path",
        "raw_structure_file",
        "run_manifest",
        "run_manifest_path",
        "run_workspace",
        "saved_files",
        "workspace",
    }
)
_WINDOWS_PATH_TEXT = re.compile(r"(?i)[A-Za-z]:[\\/][^\r\n,;]+")
_UNIX_PATH_PREFIXES = tuple("/" + name + "/" for name in ("Users", "home", "app", "tmp", "var"))
_UNIX_PATH_TEXT = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    + "|".join(re.escape(prefix) for prefix in _UNIX_PATH_PREFIXES)
    + r")[^\r\n,;]+"
)


def _sanitize_public_text(value: str | None) -> str | None:
    """Remove local filesystem details from public API strings."""
    if value is None:
        return None
    sanitized = _WINDOWS_PATH_TEXT.sub("[local path redacted]", str(value))
    sanitized = _UNIX_PATH_TEXT.sub("[local path redacted]", sanitized)
    return sanitized


def _sanitize_public_payload(value: Any) -> Any:
    """Keep useful result data while omitting local paths and artifact links."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key in _LOCAL_RESULT_KEYS:
                continue
            if normalized_key == "url" and str(item).startswith("/static/results/"):
                continue
            sanitized[str(key)] = _sanitize_public_payload(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_public_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_public_payload(item) for item in value]
    if isinstance(value, str):
        return _sanitize_public_text(value)
    return value


def _public_job_response(record: Any) -> JobDetailResponse:
    """Build a job response without exposing local result paths or exceptions."""
    response = record.to_response()
    error = response.error
    if error is not None:
        error = error.model_copy(update={"detail": None})
    return response.model_copy(
        update={
            "result": _sanitize_public_payload(response.result),
            "error": error,
        }
    )


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

    try:
        JobOptions.model_validate(options)
    except ValidationError as exc:
        raise ApiError(
            status_code=400,
            code="INVALID_OPTIONS",
            message="One or more job options are invalid.",
            details={"errors": _safe_validation_errors(exc)},
        ) from exc


def _select_analysis_run(
    db: AtlasDB,
    *,
    pdb_id: str,
    run_id: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    runs = db.list_runs(pdb_id)
    if not runs:
        raise ApiError(
            status_code=404,
            code="ANALYSIS_RUN_NOT_FOUND",
            message=f"No analysis run is available for {pdb_id}.",
        )
    if run_id is None:
        return runs[0], runs
    selected = next((item for item in runs if item["run_id"] == run_id), None)
    if selected is None:
        raise ApiError(
            status_code=404,
            code="ANALYSIS_RUN_NOT_FOUND",
            message=f"Run {run_id} is not available for {pdb_id}.",
        )
    return selected, runs


def _public_run_evidence(run: dict[str, Any]) -> dict[str, Any]:
    """Expose provenance metadata without local paths or generated structure data."""
    try:
        report = json.loads(str(run.get("run_manifest_json", "{}")))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}

    source = report.get("structure_source")
    source = source if isinstance(source, dict) else {}
    preparation = report.get("preparation")
    preparation = preparation if isinstance(preparation, dict) else {}
    hashes = preparation.get("hashes")
    hashes = hashes if isinstance(hashes, dict) else {}
    provenance = report.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    scoring = report.get("scoring")
    scoring = scoring if isinstance(scoring, dict) else {}

    public_source = {
        key: source[key]
        for key in ("provider", "identifier", "representation", "assembly_id")
        if key in source
    }
    public_preparation = {
        "schema_version": preparation.get("schema_version"),
        "status": preparation.get("status"),
        "preparation_policy_version": preparation.get("preparation_policy_version"),
        "source": public_source,
        "selected_chains": preparation.get("selected_chains", []),
        "warnings": _sanitize_public_payload(preparation.get("warnings", [])),
        "hashes": {
            key: hashes[key]
            for key in ("input_sha256", "prepared_sha256", "preparation_config_sha256")
            if key in hashes
        },
    }
    public_provenance = {
        key: provenance[key]
        for key in (
            "input_sha256",
            "prepared_sha256",
            "preparation_config_sha256",
            "preparation_report_sha256",
            "detector_config_sha256",
            "motion_config_sha256",
            "model_sha256",
            "code_identity_sha256",
            "environment_identity_sha256",
        )
        if key in provenance
    }
    public_scoring = {
        key: scoring[key]
        for key in (
            "contract_version",
            "ranking_contract_version",
            "motion_affects_canonical_score",
            "raw_measurements_stored_separately",
        )
        if key in scoring
    }
    motion = report.get("motion_aware")
    if isinstance(motion, dict):
        public_motion = {
            key: motion[key]
            for key in (
                "status",
                "canonical_ranking_affected",
                "quality_counts",
                "accepted_sample_count",
                "accepted_mode_count",
            )
            if key in motion
        }
    else:
        public_motion = {
            "status": "NOT_ELIGIBLE",
            "canonical_ranking_affected": False,
        }

    evidence: dict[str, Any] = {
        "structure_source": public_source,
        "preparation": public_preparation,
        "provenance": public_provenance,
        "scoring": public_scoring,
        "motion_aware": public_motion,
    }
    motion_sampling = report.get("motion_sampling")
    if isinstance(motion_sampling, dict):
        evidence["motion_sampling"] = {
            key: motion_sampling[key]
            for key in ("mode_count", "samples_per_mode", "requested_sample_count")
            if key in motion_sampling
        }
    return evidence


def _prepared_structure_for_run(run: dict[str, Any]) -> tuple[Path, str]:
    try:
        report = json.loads(str(run["run_manifest_json"]))
        workspace = Path(str(report["run_workspace"]))
        if not workspace.is_absolute():
            workspace = PROJECT_ROOT / workspace
        expected_path = (workspace / "preparation" / "prepared_detector.pdb").resolve()
        recorded = report.get("provenance", {}).get("prepared_structure_path")
        if recorded:
            recorded_path = Path(str(recorded))
            if not recorded_path.is_absolute():
                recorded_path = PROJECT_ROOT / recorded_path
            if recorded_path.resolve() != expected_path:
                raise ApiError(
                    status_code=409,
                    code="PREPARED_STRUCTURE_PATH_MISMATCH",
                    message="Run provenance does not identify its canonical prepared structure.",
                )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ApiError(
            status_code=409,
            code="INVALID_RUN_PROVENANCE",
            message="The selected run has invalid prepared-structure provenance.",
        ) from exc

    if not expected_path.is_file():
        raise ApiError(
            status_code=404,
            code="PREPARED_STRUCTURE_NOT_FOUND",
            message="The selected run's prepared structure is not available locally.",
        )
    actual_sha256 = hashlib.sha256(expected_path.read_bytes()).hexdigest()
    expected_sha256 = str(run.get("prepared_sha256", ""))
    if actual_sha256 != expected_sha256:
        raise ApiError(
            status_code=409,
            code="PREPARED_STRUCTURE_HASH_MISMATCH",
            message="The selected run's prepared structure failed hash verification.",
        )
    return expected_path, actual_sha256


def create_app(
    *,
    orchestrator: JobOrchestrator | None = None,
    rate_limiter: InMemoryRateLimiter | None = None,
) -> FastAPI:
    """Build a configured FastAPI application."""
    api_orchestrator = orchestrator or JobOrchestrator(
        default_max_retries=0,
        state_path=PROJECT_ROOT / PATHS.runtime_root / "jobs.sqlite",
    )
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
        title="BioVoid Local Research API",
        version=__version__,
        description="Single-node API for controlled local protein-pocket analysis.",
        lifespan=lifespan,
    )
    # Keep app.state available even when lifespan is not entered (e.g., ad-hoc TestClient use).
    app.state.orchestrator = api_orchestrator
    app.state.rate_limiter = limiter
    if (FRONTEND_DIST / "assets").is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(FRONTEND_DIST / "assets")),
            name="frontend-assets",
        )

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):
        incoming = request.headers.get("X-Correlation-ID", "").strip()
        correlation_id = incoming or uuid.uuid4().hex
        request.state.correlation_id = correlation_id
        client_ip = request.client.host if request.client else "unknown"
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            LOGGER.exception(
                "request_failed method=%s path=%s correlation_id=%s client=%s",
                request.method,
                request.url.path,
                correlation_id,
                client_ip,
            )
            raise
        duration_ms = (time.monotonic() - started) * 1000.0
        response.headers["X-Correlation-ID"] = correlation_id
        LOGGER.info(
            "request method=%s path=%s status=%s correlation_id=%s client=%s duration_ms=%.2f",
            request.method,
            request.url.path,
            response.status_code,
            correlation_id,
            client_ip,
            duration_ms,
        )
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        payload = exc.to_payload()
        correlation_id = getattr(request.state, "correlation_id", None)
        if correlation_id:
            payload["error"]["correlation_id"] = correlation_id
        return JSONResponse(
            status_code=exc.status_code,
            content=payload,
            headers={"X-Correlation-ID": correlation_id} if correlation_id else None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        payload = ErrorEnvelope(
            error={
                "code": "VALIDATION_ERROR",
                "message": "Request payload validation failed.",
                "details": {"errors": exc.errors()},
            }
        )
        body = payload.model_dump()
        if correlation_id:
            body["error"]["correlation_id"] = correlation_id
        return JSONResponse(
            status_code=422,
            content=body,
            headers={"X-Correlation-ID": correlation_id} if correlation_id else None,
        )

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

    @app.get("/portal", include_in_schema=False)
    async def portal() -> RedirectResponse:
        """Keep the old URL stable while sending users to the canonical UI."""
        return RedirectResponse(url="/", status_code=302)

    @app.get("/", include_in_schema=False)
    @app.get("/dashboard", include_in_schema=False)
    @app.get("/analyze", include_in_schema=False)
    @app.get("/atlas", include_in_schema=False)
    @app.get("/system", include_in_schema=False)
    async def frontend_entry() -> Response:
        index_path = FRONTEND_DIST / "index.html"
        if index_path.is_file():
            return FileResponse(
                index_path,
                media_type="text/html",
                headers={"X-BioVoid-UI": "react-canonical"},
            )
        return HTMLResponse(
            status_code=503,
            content="<h1>BioVoid frontend build unavailable</h1>",
            headers={"X-BioVoid-UI": "react-build-required"},
        )

    @app.get("/ops/metrics")
    async def ops_metrics(request: Request) -> dict[str, Any]:
        await enforce_rate_limit(request)
        metrics = app.state.orchestrator.ops_metrics()
        metrics["correlation_id"] = getattr(request.state, "correlation_id", None)
        return metrics

    def _atlas_db_exists() -> bool:
        return ATLAS_DB_PATH.exists()

    def _atlas_default_overview() -> dict[str, Any]:
        return {
            "available": False,
            "summary": {
                "total_proteins": 0,
                "total_pockets": 0,
                "druggable_pockets": 0,
                "elite_pockets": 0,
                "avg_bio_score": 0.0,
                "avg_volume": 0.0,
            },
            "class_distribution": {"high": 0, "medium": 0, "low": 0},
            "leaders": [],
            "message": "Atlas database not available.",
        }

    @app.get("/atlas/overview")
    async def atlas_overview(request: Request) -> dict[str, Any]:
        await enforce_rate_limit(request)
        payload = _atlas_default_overview()
        payload["correlation_id"] = getattr(request.state, "correlation_id", None)
        if not _atlas_db_exists():
            return payload

        try:
            with AtlasDB(str(ATLAS_DB_PATH), check_same_thread=False) as db:
                stats = db.get_statistics()
                leaders = db.search_pockets(
                    druggability_class="high",
                    order_by="bio_score DESC",
                    limit=8,
                )
        except Exception:
            payload["message"] = "Atlas read failed."
            return payload

        class_dist = stats.get("class_distribution", {})
        payload["available"] = True
        payload["summary"] = {
            "total_proteins": int(stats.get("total_proteins", 0)),
            "total_pockets": int(stats.get("total_pockets", 0)),
            "heuristic_shortlist_pockets": int(stats.get("heuristic_shortlist_pockets", 0)),
            "druggable_pockets": int(stats.get("heuristic_shortlist_pockets", 0)),
            "elite_pockets": int(stats.get("elite_pockets", 0)),
            "avg_bio_score": float(stats.get("avg_bio_score", 0.0) or 0.0),
            "avg_volume": float(stats.get("avg_volume", 0.0) or 0.0),
        }
        payload["class_distribution"] = {
            "high": int(class_dist.get("high", 0)),
            "medium": int(class_dist.get("medium", 0)),
            "low": int(class_dist.get("low", 0)),
        }
        payload["leaders"] = [
            {
                "pdb_id": row.get("pdb_id", ""),
                "pocket_id": row.get("pocket_id", 0),
                "run_id": row.get("run_id", ""),
                "bio_score": float(row.get("bio_score", 0.0) or 0.0),
                "volume": float(row.get("volume", 0.0) or 0.0),
                "druggability_class": row.get("druggability_class", "low"),
                "heuristic_shortlist": bool(row.get("heuristic_shortlist", False)),
                "validation_status": row.get("validation_status", "unknown"),
                "canonical_eligible": bool(row.get("canonical_eligible", False)),
            }
            for row in leaders
        ]
        payload["message"] = "ok"
        return payload

    @app.get("/atlas/pockets", response_model=AtlasPocketsResponse)
    async def atlas_pockets(
        request: Request,
        limit: int = Query(default=12, ge=1, le=25),
        offset: int = Query(default=0, ge=0),
        run_id: str | None = Query(default=None),
        pdb_id: str | None = Query(default=None),
        min_score: float = Query(default=0.0, ge=0.0, le=1.0),
        druggable_only: bool = False,
        druggability_class: str | None = Query(default=None),
        order_by: str = Query(default="bio_score DESC"),
    ) -> dict[str, Any]:
        await enforce_rate_limit(request)
        if druggability_class and druggability_class not in ALLOWED_DRUGGABILITY_CLASSES:
            raise ApiError(
                status_code=400,
                code="INVALID_DRUGGABILITY_CLASS",
                message="druggability_class must be one of: high, medium, low",
            )
        if not _atlas_db_exists():
            return {
                "available": False,
                "items": [],
                "count": 0,
                "total": 0,
                "limit": limit,
                "offset": offset,
                "message": "Atlas database not available.",
                "correlation_id": getattr(request.state, "correlation_id", None),
            }

        try:
            with AtlasDB(str(ATLAS_DB_PATH), check_same_thread=False) as db:
                rows = db.search_pockets(
                    min_score=min_score,
                    run_id=run_id,
                    pdb_id=pdb_id,
                    druggable_only=druggable_only,
                    druggability_class=druggability_class,
                    order_by=order_by,
                    limit=limit,
                    offset=offset,
                )
                total = db.count_pockets(
                    run_id=run_id,
                    pdb_id=pdb_id,
                    min_score=min_score,
                    druggable_only=druggable_only,
                    druggability_class=druggability_class,
                )
        except Exception:
            return {
                "available": False,
                "items": [],
                "count": 0,
                "total": 0,
                "limit": limit,
                "offset": offset,
                "message": "Atlas read failed.",
                "correlation_id": getattr(request.state, "correlation_id", None),
            }

        items = []
        for row in rows:
            meta = row.get("score_components_json")
            sphericity = 0.0
            if meta:
                try:
                    m = json.loads(meta) if isinstance(meta, str) else meta
                    sc = m.get("score_components", m) if isinstance(m, dict) else {}
                    sphericity = float(sc.get("sphericity", 0) or 0)
                except (json.JSONDecodeError, TypeError):
                    pass
            items.append(
                {
                    "pdb_id": row.get("pdb_id", ""),
                    "pocket_id": row.get("pocket_id", 0),
                    "run_id": row.get("run_id", ""),
                    "prepared_sha256": row.get("prepared_sha256", ""),
                    "bio_score": float(row.get("bio_score", 0.0) or 0.0),
                    "volume": float(row.get("volume", 0.0) or 0.0),
                    "rank": int(row.get("rank", 0) or 0),
                    "heuristic_quality_tier": row.get("druggability_class", "low"),
                    "heuristic_shortlist": bool(row.get("heuristic_shortlist", False)),
                    "validation_status": row.get("validation_status", "unknown"),
                    "canonical_eligible": bool(row.get("canonical_eligible", False)),
                    "detector_version": row.get("detector_version", "unknown"),
                    "scoring_contract_version": row.get("scoring_contract_version", "unknown"),
                    "profile_used": row.get("profile_used", ""),
                    "merged_vertices": int(row.get("merged_vertices", 0) or 0),
                    "sphericity": sphericity,
                }
            )
        return {
            "available": True,
            "items": items,
            "count": len(items),
            "total": total,
            "limit": limit,
            "offset": offset,
            "message": "ok",
            "correlation_id": getattr(request.state, "correlation_id", None),
        }

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
                details={"exception_type": type(exc).__name__},
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
                message=("Canonical scientific lock fields cannot be overridden by API requests."),
                details={"forbidden_keys": forbidden_keys},
            )

        _validate_options_shape(raw_payload)

        try:
            req_model = JobSubmitRequest.model_validate(raw_payload)
        except ValidationError as exc:
            raise ApiError(
                status_code=400,
                code="INVALID_JOB_REQUEST",
                message="Job request validation failed.",
                details={"errors": _safe_validation_errors(exc)},
            ) from exc
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
        return _public_job_response(record)

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
            "result": _sanitize_public_payload(record.result),
        }
        filename = f"biovoid-job-{job_id}.json"
        return Response(
            content=json.dumps(payload, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/jobs", response_model=JobListResponse)
    async def list_jobs(
        request: Request,
        status: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        """List all jobs, optionally filtered by status."""
        await enforce_rate_limit(request)
        records = app.state.orchestrator.list_jobs(status_filter=status, limit=limit)
        return {
            "jobs": [
                {
                    "job_id": r.job_id,
                    "status": r.status,
                    "pdb_id": r.request.input.pdb_id,
                    "job_type": r.request.job_type,
                    "created_at_utc": r.created_at_utc.isoformat(),
                    "attempts": r.attempts,
                }
                for r in records
            ],
            "count": len(records),
            "correlation_id": getattr(request.state, "correlation_id", None),
        }

    @app.post("/jobs/{job_id}/cancel", response_model=JobCancellationResponse)
    async def cancel_job(job_id: str, request: Request) -> dict[str, Any]:
        """Cancel a queued job."""
        await enforce_rate_limit(request)
        record = app.state.orchestrator.cancel(job_id)
        return {
            "job_id": record.job_id,
            "status": record.status,
            "message": "Job cancelled",
            "correlation_id": getattr(request.state, "correlation_id", None),
        }

    @app.post(
        "/jobs/batch",
        response_model=BatchJobSubmissionResponse,
        responses={400: {"model": ErrorEnvelope}},
    )
    async def submit_batch(
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
    ) -> BatchJobSubmissionResponse:
        await enforce_rate_limit(request)

        try:
            raw_payload = await request.json()
        except Exception as exc:
            raise ApiError(
                status_code=400,
                code="INVALID_JSON",
                message="Request body must be valid JSON.",
                details={"exception_type": type(exc).__name__},
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
                message="Canonical scientific lock fields cannot be overridden by API requests.",
                details={"forbidden_keys": forbidden_keys},
            )
        _validate_options_shape(raw_payload)
        try:
            batch_req = BatchJobSubmitRequest.model_validate(raw_payload)
        except ValidationError as exc:
            raise ApiError(
                status_code=400,
                code="INVALID_BATCH_REQUEST",
                message="Batch request validation failed.",
                details={"errors": _safe_validation_errors(exc)},
            ) from exc

        clean_idempotency_key = idempotency_key.strip()
        if not clean_idempotency_key:
            raise ApiError(
                status_code=400,
                code="INVALID_IDEMPOTENCY_KEY",
                message="Idempotency-Key header cannot be empty.",
            )
        batch_fingerprint = hashlib.sha256(
            (
                clean_idempotency_key
                + json.dumps(batch_req.model_dump(mode="json"), sort_keys=True)
            ).encode("utf-8")
        ).hexdigest()
        batch_id = batch_fingerprint[:12]
        job_ids: list[str] = []

        for i, pdb_id in enumerate(batch_req.pdb_ids):
            single_req = JobSubmitRequest(
                job_type=batch_req.job_type,
                input=JobInput(pdb_id=pdb_id),
                options=batch_req.options,
            )
            per_key = f"{clean_idempotency_key}:batch:{i}:{pdb_id}"
            record, _ = app.state.orchestrator.submit(
                request=single_req,
                idempotency_key=per_key,
            )
            job_ids.append(record.job_id)

        response.status_code = 202
        return BatchJobSubmissionResponse(
            batch_id=batch_id,
            job_ids=job_ids,
            total_jobs=len(job_ids),
        )

    @app.websocket("/ws/jobs/{job_id}")
    async def ws_job_progress(websocket: WebSocket, job_id: str):
        """WebSocket endpoint for real-time job status streaming."""
        await websocket.accept()
        try:
            prev_status = None
            while True:
                try:
                    record = app.state.orchestrator.get(job_id)
                except ApiError:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": f"Job {job_id} not found",
                        }
                    )
                    break

                current_status = record.status

                if current_status != prev_status:
                    progress = 0
                    if current_status == JobStatus.QUEUED:
                        progress = 0
                    elif current_status == JobStatus.RUNNING:
                        progress = 50
                    elif (
                        current_status == JobStatus.SUCCEEDED or current_status == JobStatus.FAILED
                    ):
                        progress = 100

                    event = JobProgressEvent(
                        job_id=job_id,
                        status=current_status,
                        progress_pct=progress,
                        message=f"Job {current_status}",
                        timestamp=record.started_at_utc or record.created_at_utc,
                    )
                    await websocket.send_json(event.model_dump(mode="json"))
                    prev_status = current_status

                if current_status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
                    break

                await asyncio.sleep(0.5)

        except WebSocketDisconnect:
            pass

    @app.get("/jobs/{job_id}/visualization")
    async def job_visualization(job_id: str, request: Request) -> dict[str, Any]:
        """Return Plotly-ready visualization data for a completed job."""
        await enforce_rate_limit(request)
        record = app.state.orchestrator.get(job_id)

        if record.status != JobStatus.SUCCEEDED:
            raise ApiError(
                status_code=409,
                code="JOB_NOT_COMPLETE",
                message="Visualization requires a completed job.",
                details={"job_id": job_id, "status": record.status},
            )

        result = record.result or {}
        pdb_id = result.get("pdb_id", "unknown")

        cavities = result.get("cavities", [])
        scores = [c.get("bio_score", 0) for c in cavities]
        volumes = [c.get("volume", 0) for c in cavities]
        ranks = [c.get("rank", 0) for c in cavities]
        classes = [c.get("druggability_class", "low") for c in cavities]

        class_counts = {}
        for cls in classes:
            class_counts[cls] = class_counts.get(cls, 0) + 1

        return {
            "pdb_id": pdb_id,
            "job_id": job_id,
            "charts": {
                "score_bar": {
                    "type": "bar",
                    "x": ranks,
                    "y": scores,
                    "text": classes,
                    "title": f"Pocket Heuristic Scores - {pdb_id}",
                    "xaxis": "Pocket Rank",
                    "yaxis": "Bio-Score",
                },
                "volume_scatter": {
                    "type": "scatter",
                    "x": volumes,
                    "y": scores,
                    "text": [f"Rank {r}" for r in ranks],
                    "title": f"Volume vs Score - {pdb_id}",
                    "xaxis": "Volume (A³)",
                    "yaxis": "Bio-Score",
                },
                "class_pie": {
                    "type": "pie",
                    "labels": list(class_counts.keys()),
                    "values": list(class_counts.values()),
                    "title": f"Heuristic Quality Tiers - {pdb_id}",
                },
            },
            "summary": {
                "total_cavities": len(cavities),
                "avg_score": round(sum(scores) / max(len(scores), 1), 4),
                "max_score": max(scores) if scores else 0,
                "class_distribution": class_counts,
            },
            "correlation_id": getattr(request.state, "correlation_id", None),
        }

    @app.get("/protein/{pdb_id}/detail", response_model=ProteinDetailResponse)
    async def protein_detail(
        pdb_id: str,
        request: Request,
        run_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Full protein detail view with all pockets and stats."""
        await enforce_rate_limit(request)
        pdb_id_upper = pdb_id.strip().upper()

        protein_info: dict[str, Any] = {"pdb_id": pdb_id_upper, "available": False}
        pockets: list[dict[str, Any]] = []

        if not _atlas_db_exists():
            raise ApiError(
                status_code=404,
                code="ATLAS_NOT_FOUND",
                message="Atlas database is not available.",
            )
        if _atlas_db_exists():
            try:
                with AtlasDB(str(ATLAS_DB_PATH), check_same_thread=False) as db:
                    selected_run, runs = _select_analysis_run(
                        db,
                        pdb_id=pdb_id_upper,
                        run_id=run_id,
                    )
                    rows = db.search_pockets(
                        run_id=str(selected_run["run_id"]),
                        limit=max(1, int(selected_run["detected_total"])),
                        order_by="rank ASC",
                    )
                    protein_info.update(
                        {
                            "run_id": selected_run["run_id"],
                            "prepared_sha256": selected_run["prepared_sha256"],
                            "validation_status": selected_run["validation_status"],
                            "canonical_eligible": bool(selected_run["canonical_eligible"]),
                            "detector_version": selected_run["detector_version"],
                            "scoring_contract_version": selected_run["scoring_contract_version"],
                            "available_runs": [item["run_id"] for item in runs],
                        }
                    )
                    protein_info.update(_public_run_evidence(selected_run))
                    pockets = []
                    for r in rows:
                        meta = r.get("score_components_json")
                        sc = {}
                        if meta:
                            try:
                                sc = json.loads(meta) if isinstance(meta, str) else meta
                                if isinstance(sc, dict) and "score_components" in sc:
                                    sc = sc.get("score_components", {})
                            except (json.JSONDecodeError, TypeError):
                                pass
                        pockets.append(
                            {
                                "pocket_id": r.get("pocket_id", 0),
                                "pdb_id": pdb_id_upper,
                                "run_id": selected_run["run_id"],
                                "prepared_sha256": selected_run["prepared_sha256"],
                                "rank": int(r.get("rank", 0) or 0),
                                "bio_score": float(r.get("bio_score", 0) or 0),
                                "volume": float(r.get("volume", 0) or 0),
                                "center": [
                                    float(r.get("center_x", 0) or 0),
                                    float(r.get("center_y", 0) or 0),
                                    float(r.get("center_z", 0) or 0),
                                ],
                                "hydrophobic_ratio": float(r.get("hydrophobic_ratio", 0) or 0),
                                "heuristic_quality_tier": r.get("druggability_class", "low"),
                                "heuristic_shortlist": bool(r.get("heuristic_shortlist", False)),
                                "validation_status": selected_run["validation_status"],
                                "canonical_eligible": bool(selected_run["canonical_eligible"]),
                                "detector_version": selected_run["detector_version"],
                                "scoring_contract_version": selected_run[
                                    "scoring_contract_version"
                                ],
                                "enclosure_score": float(r.get("enclosure_score", 0) or 0),
                                "depth_score": float(r.get("depth_score", 0) or 0),
                                "profile_used": r.get("profile_used", ""),
                                "merged_vertices": int(r.get("merged_vertices", 0) or 0),
                                "sphericity": float(sc.get("sphericity", 0) or 0),
                                "volume_score": float(
                                    sc.get("volume_score", r.get("volume_score", 0)) or 0
                                ),
                            }
                        )
                    protein_info["available"] = bool(pockets)
            except ApiError:
                raise
            except Exception as exc:
                raise ApiError(
                    status_code=500,
                    code="ATLAS_READ_FAILED",
                    message="The selected analysis run could not be read safely.",
                    details={"exception_type": type(exc).__name__},
                ) from exc

        scores = [p["bio_score"] for p in pockets]
        volumes = [p["volume"] for p in pockets]
        shortlist_count = sum(1 for p in pockets if p["heuristic_shortlist"])
        class_dist: dict[str, int] = {}
        for p in pockets:
            c = p["heuristic_quality_tier"]
            class_dist[c] = class_dist.get(c, 0) + 1

        protein_info.update(
            {
                "pockets": pockets,
                "total_pockets": len(pockets),
                "heuristic_shortlist_pockets": shortlist_count,
                "avg_bio_score": round(sum(scores) / max(1, len(scores)), 4) if scores else 0,
                "max_bio_score": round(max(scores), 4) if scores else 0,
                "avg_volume": round(sum(volumes) / max(1, len(volumes)), 1) if volumes else 0,
                "class_distribution": class_dist,
            }
        )
        return protein_info

    @app.get("/export/pockets.csv")
    async def export_pockets_csv(
        request: Request,
        pdb_id: str | None = Query(default=None),
        run_id: str | None = Query(default=None),
        min_score: float = Query(default=0.0),
        heuristic_shortlist_only: bool = Query(default=False),
    ) -> Response:
        """Export run-scoped heuristic pocket observations as CSV."""
        await enforce_rate_limit(request)
        if not _atlas_db_exists():
            raise ApiError(status_code=404, code="NO_ATLAS", message="Atlas DB not found")

        with AtlasDB(str(ATLAS_DB_PATH), check_same_thread=False) as db:
            rows = db.search_pockets(
                pdb_id=pdb_id,
                run_id=run_id,
                min_score=min_score,
                druggable_only=heuristic_shortlist_only,
                limit=5000,
            )

        if not rows:
            raise ApiError(status_code=404, code="NO_DATA", message="No pockets found")

        headers = [
            "pdb_id",
            "run_id",
            "prepared_sha256",
            "pocket_id",
            "rank",
            "bio_score",
            "volume",
            "heuristic_quality_tier",
            "heuristic_shortlist",
            "validation_status",
            "canonical_eligible",
            "detector_version",
            "scoring_contract_version",
            "hydrophobic_ratio",
            "enclosure_score",
            "depth_score",
            "profile_used",
        ]
        lines = [",".join(headers)]
        for r in rows:
            line = ",".join(str(r.get(h, "")) for h in headers)
            lines.append(line)

        csv_content = "\n".join(lines)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="biovoid_pockets.csv"'},
        )

    @app.get("/publication/figure-data")
    async def publication_figure_data(request: Request) -> dict[str, Any]:
        """Keep publication exports disabled until a sealed benchmark exists."""
        await enforce_rate_limit(request)
        return {
            "available": False,
            "validation_status": "not_eligible",
            "canonical_eligible": False,
            "message": (
                "Publication figure export is disabled until a sealed benchmark "
                "protocol and external validation are complete."
            ),
        }

    @app.get("/benchmark/fpocket-comparison")
    async def fpocket_comparison(request: Request) -> dict[str, Any]:
        """Load fpocket vs BioVoid comparison data."""
        await enforce_rate_limit(request)
        fp_path = (
            Path(__file__).resolve().parents[2] / "data" / "benchmark" / "fpocket_benchmark_v3.json"
        )
        if not fp_path.exists():
            return {
                "available": False,
                "validation_status": "legacy_non_validated",
                "canonical_eligible": False,
                "message": "Historical fpocket benchmark data not found",
            }

        try:
            data = json.loads(fp_path.read_text())
            g = data.get("global", {})
            return {
                "available": True,
                "validation_status": "legacy_non_validated",
                "canonical_eligible": False,
                "protocol_id": "historical_fpocket_comparison_v3",
                "common_proteins": g.get("common_proteins", 0),
                "fpocket_pockets": g.get("fpocket_valid_total", 0),
                "biovoid_pockets": g.get("biovoid_valid_total", 0),
                "overlap": round(g.get("official_overlap_center_volume_greedy", 0) * 100, 1),
                "center_overlap": round(g.get("center_only_overlap_greedy", 0) * 100, 1),
                "biovoid_unique_rate": round(
                    (1 - g.get("official_overlap_center_volume_greedy", 0)) * 100, 1
                ),
            }
        except Exception:
            return {
                "available": False,
                "validation_status": "legacy_non_validated",
                "canonical_eligible": False,
                "message": "Historical comparison data could not be read.",
            }

    @app.get("/benchmark/known-pockets")
    async def get_known_pockets(request: Request) -> dict[str, Any]:
        """Return non-sensitive metadata for the historical development set."""
        await enforce_rate_limit(request)
        try:
            from src.benchmark import KNOWN_CRYPTIC_POCKETS

            pockets = []
            for pdb_id, info in KNOWN_CRYPTIC_POCKETS.items():
                pockets.append(
                    {
                        "pdb_id": pdb_id,
                        "name": info.get("name", ""),
                        "pocket_type": info.get("pocket_type", ""),
                        "reference": info.get("reference", ""),
                        "ground_truth_exposed": False,
                    }
                )
            return {
                "pockets": pockets,
                "count": len(pockets),
                "validation_status": "legacy_non_validated",
                "canonical_eligible": False,
                "protocol_id": "legacy_known_pockets_v1",
            }
        except Exception:
            return {
                "pockets": [],
                "count": 0,
                "validation_status": "legacy_non_validated",
                "canonical_eligible": False,
                "error": "Historical reference data could not be read.",
            }

    @app.get("/artifacts")
    async def list_artifacts(request: Request) -> dict[str, Any]:
        """Report that local generated files are not served by the API."""
        await enforce_rate_limit(request)
        return {
            "available": False,
            "artifacts": [],
            "count": 0,
            "message": "Generated local artifacts are not served by the API.",
        }

    @app.get("/protein/{pdb_id}/structure")
    async def get_protein_structure(
        pdb_id: str,
        request: Request,
        run_id: str | None = Query(default=None),
    ) -> Response:
        """Return the hash-verified prepared structure for one analysis run."""
        await enforce_rate_limit(request)
        pdb_id_upper = pdb_id.strip().upper()
        if not _atlas_db_exists():
            raise ApiError(
                status_code=404,
                code="ATLAS_NOT_FOUND",
                message="Atlas database is not available.",
            )
        with AtlasDB(str(ATLAS_DB_PATH), check_same_thread=False) as db:
            selected_run, _ = _select_analysis_run(
                db,
                pdb_id=pdb_id_upper,
                run_id=run_id,
            )
        pdb_path, prepared_sha256 = _prepared_structure_for_run(selected_run)
        return Response(
            content=pdb_path.read_text(encoding="ascii", errors="replace"),
            media_type="chemical/x-pdb",
            headers={
                "X-BioVoid-Run-ID": str(selected_run["run_id"]),
                "X-BioVoid-Prepared-SHA256": prepared_sha256,
                "X-BioVoid-Validation-Status": str(selected_run["validation_status"]),
            },
        )

    @app.get("/protein/{pdb_id}/pockets")
    async def get_protein_pockets(
        pdb_id: str,
        request: Request,
        run_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Return pocket positions for 3D overlay."""
        await enforce_rate_limit(request)
        pdb_id_upper = pdb_id.strip().upper()
        if not _atlas_db_exists():
            return {"pdb_id": pdb_id_upper, "pockets": [], "message": "No atlas DB"}

        try:
            with AtlasDB(str(ATLAS_DB_PATH), check_same_thread=False) as db:
                selected_run, _ = _select_analysis_run(
                    db,
                    pdb_id=pdb_id_upper,
                    run_id=run_id,
                )
                rows = db.search_pockets(
                    run_id=str(selected_run["run_id"]),
                    limit=max(1, int(selected_run["detected_total"])),
                    order_by="rank ASC",
                )
        except ApiError:
            raise
        except Exception:
            return {
                "pdb_id": pdb_id_upper,
                "pockets": [],
                "message": "Pocket data could not be read.",
            }

        pockets = []
        for row in rows:
            pockets.append(
                {
                    "id": row.get("pocket_id", 0),
                    "center": [
                        float(row.get("center_x", 0) or 0),
                        float(row.get("center_y", 0) or 0),
                        float(row.get("center_z", 0) or 0),
                    ],
                    "radius": float(row.get("radius_geom", 3.0) or 3.0),
                    "bio_score": float(row.get("bio_score", 0) or 0),
                    "volume": float(row.get("volume", 0) or 0),
                    "druggability_class": row.get("druggability_class", "low"),
                    "heuristic_shortlist": bool(row.get("heuristic_shortlist", False)),
                }
            )
        return {
            "pdb_id": pdb_id_upper,
            "run_id": selected_run["run_id"],
            "prepared_sha256": selected_run["prepared_sha256"],
            "validation_status": selected_run["validation_status"],
            "canonical_eligible": bool(selected_run["canonical_eligible"]),
            "pockets": pockets,
        }

    return app


app = create_app()
