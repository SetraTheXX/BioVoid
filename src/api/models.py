"""Pydantic models for the Phase 6 job API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CANONICAL_LOCK_KEYS = {"tolerance", "top_n", "druggable_only"}
ALLOWED_OPTION_KEYS = {"priority", "timeout_seconds", "max_retries", "n_frames", "profile"}


class JobStatus(str, Enum):
    """Supported job lifecycle statuses."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobInput(BaseModel):
    """User-submitted input payload."""

    pdb_id: str = Field(
        ...,
        min_length=4,
        max_length=12,
        description="PDB identifier (e.g. 1CBS).",
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("pdb_id")
    @classmethod
    def normalize_pdb_id(cls, value: str) -> str:
        import re
        normalized = value.strip().upper()
        if not re.match(r'^[A-Z0-9]{4,12}$', normalized):
            raise ValueError("pdb_id must be 4-12 alphanumeric characters (e.g. 1CBS)")
        return normalized


class JobSubmitRequest(BaseModel):
    """Create-job request model."""

    job_type: Literal["quick_probe", "full_analysis"] = "quick_probe"
    input: JobInput
    options: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class JobSubmissionResponse(BaseModel):
    """Response for POST /jobs."""

    job_id: str
    status: JobStatus
    idempotent_reused: bool
    created_at_utc: datetime


class JobErrorResponse(BaseModel):
    """Structured job execution failure block."""

    code: str
    message: str
    detail: str | None = None
    attempts: int


class JobDetailResponse(BaseModel):
    """Response model for GET /jobs/{job_id}."""

    job_id: str
    status: JobStatus
    created_at_utc: datetime
    started_at_utc: datetime | None = None
    finished_at_utc: datetime | None = None
    attempts: int
    idempotency_key: str
    request: JobSubmitRequest
    result: dict[str, Any] | None = None
    error: JobErrorResponse | None = None


class BatchJobSubmitRequest(BaseModel):
    """Submit multiple PDB IDs for batch analysis."""

    job_type: Literal["quick_probe", "full_analysis"] = "quick_probe"
    pdb_ids: list[str] = Field(..., min_length=1, max_length=50)
    options: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @field_validator("pdb_ids")
    @classmethod
    def normalize_all_ids(cls, values: list[str]) -> list[str]:
        result = []
        for v in values:
            normalized = v.strip().upper()
            if not normalized.isalnum() or len(normalized) < 4:
                raise ValueError(f"Invalid PDB ID: {v}")
            result.append(normalized)
        return result


class BatchJobSubmissionResponse(BaseModel):
    """Response for POST /jobs/batch."""

    batch_id: str
    job_ids: list[str]
    total_jobs: int
    status: str = "accepted"


class JobProgressEvent(BaseModel):
    """WebSocket progress event payload."""

    job_id: str
    status: str
    progress_pct: int = 0
    message: str = ""
    timestamp: datetime


class ErrorEnvelope(BaseModel):
    """Standard API error envelope."""

    error: dict[str, Any]
