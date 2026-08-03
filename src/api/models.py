"""Pydantic models for the local BioVoid job API."""

from __future__ import annotations

from datetime import datetime
import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.config import PIPELINE
from src.resources import SAFE_16GB

CANONICAL_LOCK_KEYS = {"tolerance", "top_n", "druggable_only"}
IDENTIFIER_PATTERN = re.compile(r"^[A-Z0-9]{4,12}$")
RCSB_ID_PATTERN = re.compile(r"^[A-Z0-9]{4}$")


class JobOptions(BaseModel):
    """Typed options shared by single and batch job submissions."""

    priority: Literal["normal", "high"] = "normal"
    timeout_seconds: float | None = Field(default=None, gt=0, le=600)
    max_retries: int | None = Field(default=None, ge=0, le=5)
    n_frames: int | None = Field(default=None, ge=1, le=200)
    profile: Literal["default", "enzyme", "ppi", "gpcr"] = "default"
    mode: Literal["static", "motion_aware"] = "static"
    structure_source: Literal["rcsb", "alphafold"] = "rcsb"
    representation: Literal[
        "asymmetric_unit",
        "biological_assembly",
        "predicted_model",
    ] = "biological_assembly"
    assembly_id: str | None = "1"
    chains: tuple[str, ...] | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("chains")
    @classmethod
    def normalize_chains(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is None:
            return None
        normalized = tuple(sorted({chain.strip() for chain in value if chain.strip()}))
        if not normalized:
            raise ValueError("chains cannot be empty")
        return normalized

    @model_validator(mode="after")
    def validate_structure_contract(self) -> JobOptions:
        if self.mode == "motion_aware":
            samples_per_mode = self.n_frames or PIPELINE.n_frames
            requested_samples = PIPELINE.n_modes * samples_per_mode
            if requested_samples > SAFE_16GB.max_motion_samples:
                raise ValueError(
                    "safe-16gb limits motion-aware jobs to "
                    f"{SAFE_16GB.max_motion_samples} total samples "
                    f"({PIPELINE.n_modes} modes at most)"
                )
        if self.structure_source == "rcsb":
            if self.representation not in {"asymmetric_unit", "biological_assembly"}:
                raise ValueError("RCSB jobs require asymmetric_unit or biological_assembly")
            if self.representation == "biological_assembly" and not self.assembly_id:
                raise ValueError("biological_assembly requires assembly_id")
        elif self.representation != "predicted_model":
            raise ValueError("AlphaFold jobs require predicted_model representation")
        return self

    def get(self, key: str, default: Any = None) -> Any:
        """Small mapping-compatible bridge for existing runtime consumers."""
        value = getattr(self, key, None)
        return default if value is None else value


ALLOWED_OPTION_KEYS = set(JobOptions.model_fields)


class JobStatus(str, Enum):
    """Supported job lifecycle statuses."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


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
        normalized = value.strip().upper()
        if not IDENTIFIER_PATTERN.fullmatch(normalized):
            raise ValueError("pdb_id must be 4-12 alphanumeric characters (e.g. 1CBS)")
        return normalized


class JobSubmitRequest(BaseModel):
    """Create-job request model."""

    job_type: Literal["quick_probe", "full_analysis"] = "quick_probe"
    input: JobInput
    options: JobOptions = Field(default_factory=JobOptions)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def disable_expensive_automatic_retries(self) -> JobSubmitRequest:
        if self.job_type == "full_analysis" and self.options.max_retries not in {
            None,
            0,
        }:
            raise ValueError("full_analysis does not allow automatic retries")
        if self.options.structure_source == "rcsb" and not RCSB_ID_PATTERN.fullmatch(
            self.input.pdb_id
        ):
            raise ValueError(
                "RCSB analysis identifiers must be exactly four alphanumeric characters"
            )
        return self


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
    options: JobOptions = Field(default_factory=JobOptions)

    model_config = ConfigDict(extra="forbid")

    @field_validator("pdb_ids")
    @classmethod
    def normalize_all_ids(cls, values: list[str]) -> list[str]:
        result = []
        for v in values:
            normalized = v.strip().upper()
            if not IDENTIFIER_PATTERN.fullmatch(normalized):
                raise ValueError(f"Invalid structure identifier: {v}")
            result.append(normalized)
        return result

    @model_validator(mode="after")
    def validate_source_identifiers(self) -> BatchJobSubmitRequest:
        if self.job_type == "full_analysis" and self.options.max_retries not in {None, 0}:
            raise ValueError("full_analysis does not allow automatic retries")
        if self.options.structure_source == "rcsb":
            invalid = [pdb_id for pdb_id in self.pdb_ids if not RCSB_ID_PATTERN.fullmatch(pdb_id)]
            if invalid:
                raise ValueError(
                    "RCSB batch analysis identifiers must be exactly four alphanumeric "
                    f"characters: {invalid}"
                )
        return self


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


class AtlasPocketResponse(BaseModel):
    """One run-scoped pocket exposed by the Atlas API."""

    pdb_id: str
    pocket_id: str
    run_id: str
    prepared_sha256: str
    rank: int
    bio_score: float
    volume: float
    heuristic_quality_tier: Literal["high", "medium", "low"]
    heuristic_shortlist: bool
    validation_status: str
    canonical_eligible: bool
    detector_version: str
    scoring_contract_version: str
    profile_used: str
    merged_vertices: int
    sphericity: float
    center: tuple[float, float, float] | None = None
    hydrophobic_ratio: float | None = None
    enclosure_score: float | None = None
    depth_score: float | None = None
    volume_score: float | None = None


class AtlasPocketsResponse(BaseModel):
    available: bool
    items: list[AtlasPocketResponse]
    count: int
    total: int = 0
    limit: int
    offset: int
    message: str
    correlation_id: str | None = None


class ProteinDetailResponse(BaseModel):
    pdb_id: str
    available: bool
    run_id: str
    prepared_sha256: str
    validation_status: str
    canonical_eligible: bool
    detector_version: str
    scoring_contract_version: str
    structure_source: dict[str, Any] | None = None
    preparation: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    scoring: dict[str, Any] | None = None
    motion_sampling: dict[str, Any] | None = None
    motion_aware: dict[str, Any] | None = None
    available_runs: list[str]
    pockets: list[AtlasPocketResponse]
    total_pockets: int
    heuristic_shortlist_pockets: int
    avg_bio_score: float
    max_bio_score: float
    avg_volume: float
    class_distribution: dict[str, int]


class JobListItemResponse(BaseModel):
    job_id: str
    status: JobStatus
    pdb_id: str
    job_type: str
    created_at_utc: datetime
    attempts: int


class JobListResponse(BaseModel):
    jobs: list[JobListItemResponse]
    count: int
    correlation_id: str | None = None


class JobCancellationResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str
    correlation_id: str | None = None
