"""Phase 6 FastAPI application (Step 2: Backend/API)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.database import AtlasDB

from .errors import ApiError
from .models import (
    ALLOWED_OPTION_KEYS,
    CANONICAL_LOCK_KEYS,
    BatchJobSubmissionResponse,
    BatchJobSubmitRequest,
    ErrorEnvelope,
    JobDetailResponse,
    JobInput,
    JobProgressEvent,
    JobStatus,
    JobSubmissionResponse,
    JobSubmitRequest,
)
from .orchestrator import JobOrchestrator
from .portal import render_portal_html
from .rate_limit import InMemoryRateLimiter

LOGGER = logging.getLogger("biovoid.phase6.api")
ATLAS_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "atlas.db"
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
    if priority is not None and priority not in {"normal", "high"}:
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
        description=("Single-node job orchestration API for controlled Phase 6 productization."),
        lifespan=lifespan,
    )
    # Keep app.state available even when lifespan is not entered (e.g., ad-hoc TestClient use).
    app.state.orchestrator = api_orchestrator
    app.state.rate_limiter = limiter

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
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
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

    @app.get("/", include_in_schema=False)
    async def root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/portal", status_code=307)

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard_redirect() -> RedirectResponse:
        return RedirectResponse(url="/portal", status_code=307)

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
            "db_path": str(ATLAS_DB_PATH),
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
                    druggable_only=True,
                    order_by="bio_score DESC",
                    limit=8,
                )
        except Exception as exc:
            payload["message"] = f"Atlas read failed: {exc}"
            return payload

        class_dist = stats.get("class_distribution", {})
        payload["available"] = True
        payload["summary"] = {
            "total_proteins": int(stats.get("total_proteins", 0)),
            "total_pockets": int(stats.get("total_pockets", 0)),
            "druggable_pockets": int(stats.get("druggable_pockets", 0)),
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
                "bio_score": float(row.get("bio_score", 0.0) or 0.0),
                "volume": float(row.get("volume", 0.0) or 0.0),
                "druggability_class": row.get("druggability_class", "low"),
            }
            for row in leaders
        ]
        payload["message"] = "ok"
        return payload

    @app.get("/atlas/pockets")
    async def atlas_pockets(
        request: Request,
        limit: int = Query(default=12, ge=1, le=25),
        min_score: float = Query(default=0.0, ge=0.0, le=1.0),
        druggable_only: bool = True,
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
                "message": "Atlas database not available.",
                "correlation_id": getattr(request.state, "correlation_id", None),
            }

        try:
            with AtlasDB(str(ATLAS_DB_PATH), check_same_thread=False) as db:
                rows = db.search_pockets(
                    min_score=min_score,
                    druggable_only=druggable_only,
                    druggability_class=druggability_class,
                    order_by=order_by,
                    limit=limit,
                )
        except Exception as exc:
            return {
                "available": False,
                "items": [],
                "count": 0,
                "message": f"Atlas read failed: {exc}",
                "correlation_id": getattr(request.state, "correlation_id", None),
            }

        items = []
        for row in rows:
            meta = row.get("metadata_json")
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
                    "bio_score": float(row.get("bio_score", 0.0) or 0.0),
                    "volume": float(row.get("volume", 0.0) or 0.0),
                    "rank": int(row.get("rank", 0) or 0),
                    "druggability_class": row.get("druggability_class", "low"),
                    "druggable": bool(row.get("druggable", False)),
                    "profile_used": row.get("profile_used", ""),
                    "merged_vertices": int(row.get("merged_vertices", 0) or 0),
                    "sphericity": sphericity,
                }
            )
        return {
            "available": True,
            "items": items,
            "count": len(items),
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
                message=("Canonical scientific lock fields cannot be overridden by API requests."),
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

    @app.get("/jobs")
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

    @app.post("/jobs/{job_id}/cancel")
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
                details={"detail": str(exc)},
            ) from exc

        batch_req = BatchJobSubmitRequest.model_validate(raw_payload)
        batch_id = uuid.uuid4().hex[:12]
        job_ids: list[str] = []

        for i, pdb_id in enumerate(batch_req.pdb_ids):
            single_req = JobSubmitRequest(
                job_type=batch_req.job_type,
                input=JobInput(pdb_id=pdb_id),
                options=batch_req.options,
            )
            per_key = f"{idempotency_key.strip()}_batch_{batch_id}_{i}"
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
                    "title": f"Pocket Druggability Scores - {pdb_id}",
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
                    "title": f"Druggability Classes - {pdb_id}",
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

    @app.get("/protein/{pdb_id}/detail")
    async def protein_detail(pdb_id: str, request: Request) -> dict[str, Any]:
        """Full protein detail view with all pockets and stats."""
        await enforce_rate_limit(request)
        pdb_id_upper = pdb_id.strip().upper()

        protein_info: dict[str, Any] = {"pdb_id": pdb_id_upper, "available": False}
        pockets: list[dict[str, Any]] = []

        if _atlas_db_exists():
            try:
                with AtlasDB(str(ATLAS_DB_PATH), check_same_thread=False) as db:
                    rows = db.search_pockets(pdb_id=pdb_id_upper, limit=100)
                    pockets = []
                    for r in rows:
                        meta = r.get("metadata_json")
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
                                "rank": int(r.get("rank", 0) or 0),
                                "bio_score": float(r.get("bio_score", 0) or 0),
                                "volume": float(r.get("volume", 0) or 0),
                                "center": [
                                    float(r.get("center_x", 0) or 0),
                                    float(r.get("center_y", 0) or 0),
                                    float(r.get("center_z", 0) or 0),
                                ],
                                "hydrophobic_ratio": float(r.get("hydrophobic_ratio", 0) or 0),
                                "druggability_class": r.get("druggability_class", "low"),
                                "druggable": bool(r.get("druggable", False)),
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
            except Exception as exc:
                protein_info["error"] = str(exc)

        scores = [p["bio_score"] for p in pockets]
        volumes = [p["volume"] for p in pockets]
        druggable_count = sum(1 for p in pockets if p["druggable"])
        class_dist: dict[str, int] = {}
        for p in pockets:
            c = p["druggability_class"]
            class_dist[c] = class_dist.get(c, 0) + 1

        protein_info.update(
            {
                "pockets": pockets,
                "total_pockets": len(pockets),
                "druggable_pockets": druggable_count,
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
        min_score: float = Query(default=0.0),
        druggable_only: bool = True,
    ) -> Response:
        """Export pockets as CSV download."""
        await enforce_rate_limit(request)
        if not _atlas_db_exists():
            raise ApiError(status_code=404, code="NO_ATLAS", message="Atlas DB not found")

        with AtlasDB(str(ATLAS_DB_PATH), check_same_thread=False) as db:
            rows = db.search_pockets(
                pdb_id=pdb_id,
                min_score=min_score,
                druggable_only=druggable_only,
                limit=5000,
            )

        if not rows:
            raise ApiError(status_code=404, code="NO_DATA", message="No pockets found")

        headers = [
            "pdb_id",
            "pocket_id",
            "rank",
            "bio_score",
            "volume",
            "druggability_class",
            "druggable",
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
        """Generate publication-ready figure data (Plotly JSON for paper figures)."""
        await enforce_rate_limit(request)
        if not _atlas_db_exists():
            return {"available": False, "message": "No atlas data"}

        try:
            with AtlasDB(str(ATLAS_DB_PATH), check_same_thread=False) as db:
                stats = db.get_statistics()
                all_pockets = db.search_pockets(limit=5000)
        except Exception as exc:
            return {"available": False, "message": str(exc)}

        scores = [float(p.get("bio_score", 0) or 0) for p in all_pockets]
        volumes = [float(p.get("volume", 0) or 0) for p in all_pockets]
        classes = [p.get("druggability_class", "low") for p in all_pockets]
        pdb_ids = [p.get("pdb_id", "") for p in all_pockets]

        return {
            "available": True,
            "n_pockets": len(all_pockets),
            "n_proteins": stats.get("total_proteins", 0),
            "figures": {
                "fig1_score_distribution": {
                    "data": scores,
                    "title": "Distribution of BioVoid Druggability Scores",
                    "xlabel": "Bio-Score",
                    "ylabel": "Frequency",
                },
                "fig2_volume_vs_score": {
                    "volumes": volumes,
                    "scores": scores,
                    "classes": classes,
                    "title": "Pocket Volume vs Druggability Score",
                    "xlabel": "Volume (A³)",
                    "ylabel": "Bio-Score",
                },
                "fig3_class_distribution": {
                    "distribution": stats.get("class_distribution", {}),
                    "title": "Druggability Classification",
                },
                "fig4_per_protein": {
                    "pdb_ids": pdb_ids,
                    "scores": scores,
                    "title": "Per-Protein Discovery Summary",
                },
            },
        }

    @app.get("/benchmark/fpocket-comparison")
    async def fpocket_comparison(request: Request) -> dict[str, Any]:
        """Load fpocket vs BioVoid comparison data."""
        await enforce_rate_limit(request)
        fp_path = (
            Path(__file__).resolve().parents[2] / "data" / "benchmark" / "fpocket_benchmark_v3.json"
        )
        if not fp_path.exists():
            return {"available": False, "message": "fpocket benchmark data not found"}

        try:
            data = json.loads(fp_path.read_text())
            g = data.get("global", {})
            return {
                "available": True,
                "common_proteins": g.get("common_proteins", 0),
                "fpocket_pockets": g.get("fpocket_valid_total", 0),
                "biovoid_pockets": g.get("biovoid_valid_total", 0),
                "overlap": round(g.get("official_overlap_center_volume_greedy", 0) * 100, 1),
                "center_overlap": round(g.get("center_only_overlap_greedy", 0) * 100, 1),
                "biovoid_unique_rate": round(
                    (1 - g.get("official_overlap_center_volume_greedy", 0)) * 100, 1
                ),
            }
        except Exception as e:
            return {"available": False, "message": str(e)}

    @app.get("/benchmark/known-pockets")
    async def get_known_pockets(request: Request) -> dict[str, Any]:
        """Return the known cryptic pockets test set."""
        await enforce_rate_limit(request)
        try:
            from src.benchmark import KNOWN_CRYPTIC_POCKETS

            pockets = []
            for pdb_id, info in KNOWN_CRYPTIC_POCKETS.items():
                pockets.append(
                    {
                        "pdb_id": pdb_id,
                        "name": info.get("name", ""),
                        "center": info.get("center", []),
                        "pocket_type": info.get("pocket_type", ""),
                        "known_ligand": info.get("known_ligand", ""),
                        "reference": info.get("reference", ""),
                    }
                )
            return {"pockets": pockets, "count": len(pockets)}
        except Exception as e:
            return {"pockets": [], "count": 0, "error": str(e)}

    results_dir = Path(__file__).resolve().parents[2] / "data" / "results"
    if results_dir.exists():
        app.mount("/static/results", StaticFiles(directory=str(results_dir)), name="results")

    @app.get("/artifacts")
    async def list_artifacts(request: Request) -> dict[str, Any]:
        """List visualization artifacts (images, HTMLs)."""
        await enforce_rate_limit(request)
        artifacts = []
        if results_dir.exists():
            for f in sorted(results_dir.iterdir()):
                if f.suffix in (".png", ".jpg", ".html", ".svg"):
                    artifacts.append(
                        {
                            "name": f.name,
                            "type": f.suffix[1:],
                            "size_kb": round(f.stat().st_size / 1024, 1),
                            "url": f"/static/results/{f.name}",
                        }
                    )
        return {"artifacts": artifacts, "count": len(artifacts)}

    @app.get("/protein/{pdb_id}/structure")
    async def get_protein_structure(pdb_id: str, request: Request) -> Response:
        """Return PDB file content for 3D visualization."""
        await enforce_rate_limit(request)
        pdb_id = pdb_id.strip().lower()
        pdb_path = Path(__file__).resolve().parents[2] / "data" / "raw_pdb" / f"{pdb_id}.pdb"
        if not pdb_path.exists():
            raise ApiError(
                status_code=404,
                code="PDB_NOT_FOUND",
                message=f"PDB file not found for {pdb_id.upper()}. Run an analysis first.",
            )
        return Response(
            content=pdb_path.read_text(),
            media_type="text/plain",
        )

    @app.get("/protein/{pdb_id}/pockets")
    async def get_protein_pockets(pdb_id: str, request: Request) -> dict[str, Any]:
        """Return pocket positions for 3D overlay."""
        await enforce_rate_limit(request)
        pdb_id_upper = pdb_id.strip().upper()
        if not _atlas_db_exists():
            return {"pdb_id": pdb_id_upper, "pockets": [], "message": "No atlas DB"}

        try:
            with AtlasDB(str(ATLAS_DB_PATH), check_same_thread=False) as db:
                rows = db.search_pockets(pdb_id=pdb_id_upper, limit=50)
        except Exception as exc:
            return {"pdb_id": pdb_id_upper, "pockets": [], "message": str(exc)}

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
                    "druggable": bool(row.get("druggable", False)),
                }
            )
        return {"pdb_id": pdb_id_upper, "pockets": pockets}

    return app


app = create_app()
