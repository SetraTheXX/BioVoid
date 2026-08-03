"""Target-blind benchmark contracts and lightweight Phase 6 readiness gates."""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping

from .evaluator_format import (
    DetectorEvaluationRecord,
    DetectorName,
    EvaluatorPocket,
    failed_record,
)
from .resources import ResourceLimitError, ResourceProfile, SAFE_16GB


BENCHMARK_PROTOCOL_SCHEMA_VERSION = "benchmark-protocol-v1"
BENCHMARK_EVALUATION_SCHEMA_VERSION = "benchmark-evaluation-v1"
BENCHMARK_MANIFEST_SCHEMA_VERSION = "benchmark-manifest-v1"
BENCHMARK_READINESS_VERSION = "benchmark-readiness-v1"
MAX_SAFE_16GB_BATCH_SIZE = 10

SplitName = Literal["development", "validation", "sealed"]
ProtocolState = Literal["draft", "frozen"]


class BenchmarkContractError(ValueError):
    """Raised when a benchmark contract violates a frozen scientific rule."""


class SealedHoldoutError(RuntimeError):
    """Raised when sealed data access is unsafe, repeated, or unauthorized."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise BenchmarkContractError(f"{field_name} must be a lowercase SHA-256")
    return value


def _coordinate(value: Any, field_name: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise BenchmarkContractError(f"{field_name} must contain three coordinates")
    coordinate = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in coordinate):
        raise BenchmarkContractError(f"{field_name} must contain finite coordinates")
    return coordinate


def _residue_identity(value: Any, field_name: str) -> tuple[str, str]:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkContractError(f"{field_name} must be a non-empty string")
    text = value.strip()
    colon_parts = text.split(":")
    if len(colon_parts) == 2:
        chain_id, residue_id = colon_parts
    elif len(colon_parts) == 3:
        chain_id, residue_name, residue_id = colon_parts
        if not residue_name.strip():
            raise BenchmarkContractError(f"{field_name} has an empty residue name")
    elif ":" not in text and "_" in text:
        chain_id, residue_id = text.rsplit("_", 1)
    else:
        raise BenchmarkContractError(
            f"{field_name} must use CHAIN_RESID, CHAIN:RESID, or CHAIN:RESNAME:RESID"
        )
    chain_id = chain_id.strip()
    residue_id = residue_id.strip()
    if not chain_id or not residue_id:
        raise BenchmarkContractError(f"{field_name} has an empty chain or residue identifier")
    return chain_id, residue_id


@dataclass(frozen=True)
class BenchmarkProtocol:
    """Explicit protocol values; no scientific threshold is silently defaulted."""

    protocol_id: str
    state: ProtocolState = "draft"
    primary_endpoint: str = "top_3_dcc_localization_recall"
    top_k: tuple[int, ...] = (1, 3, 5)
    dcc_tolerance_angstrom: float | None = None
    dca_tolerance_angstrom: float | None = None
    false_pocket_tolerance_angstrom: float | None = None
    false_pocket_scope_k: int | None = None
    bootstrap_replicates: int | None = None
    bootstrap_seed: int | None = None
    minimum_motion_improvement: float | None = None
    false_pocket_noninferiority_margin: float | None = None
    failure_rate_noninferiority_margin: float | None = None
    schema_version: str = BENCHMARK_PROTOCOL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.protocol_id.strip():
            raise BenchmarkContractError("protocol_id is required")
        if self.state not in {"draft", "frozen"}:
            raise BenchmarkContractError("Protocol state must be draft or frozen")
        if self.primary_endpoint != "top_3_dcc_localization_recall":
            raise BenchmarkContractError("Unsupported primary endpoint")
        if self.schema_version != BENCHMARK_PROTOCOL_SCHEMA_VERSION:
            raise BenchmarkContractError("Unsupported benchmark protocol schema")
        if tuple(sorted(set(self.top_k))) != self.top_k or any(k < 1 for k in self.top_k):
            raise BenchmarkContractError("top_k must be unique, positive, and sorted")
        if 3 not in self.top_k:
            raise BenchmarkContractError("The primary Top-3 endpoint must be represented")
        if self.state == "frozen":
            self._validate_frozen_values()

    def _validate_frozen_values(self) -> None:
        required = {
            "dcc_tolerance_angstrom": self.dcc_tolerance_angstrom,
            "dca_tolerance_angstrom": self.dca_tolerance_angstrom,
            "false_pocket_tolerance_angstrom": self.false_pocket_tolerance_angstrom,
            "false_pocket_scope_k": self.false_pocket_scope_k,
            "bootstrap_replicates": self.bootstrap_replicates,
            "bootstrap_seed": self.bootstrap_seed,
            "minimum_motion_improvement": self.minimum_motion_improvement,
            "false_pocket_noninferiority_margin": self.false_pocket_noninferiority_margin,
            "failure_rate_noninferiority_margin": self.failure_rate_noninferiority_margin,
        }
        missing = [key for key, value in required.items() if value is None]
        if missing:
            raise BenchmarkContractError(
                "Frozen protocol is missing: " + ", ".join(sorted(missing))
            )
        if any(
            float(value) <= 0
            for value in (
                self.dcc_tolerance_angstrom,
                self.dca_tolerance_angstrom,
                self.false_pocket_tolerance_angstrom,
            )
        ):
            raise BenchmarkContractError("Distance tolerances must be positive")
        if int(self.false_pocket_scope_k) < max(self.top_k):
            raise BenchmarkContractError(
                "false_pocket_scope_k must cover the largest Top-k endpoint"
            )
        if int(self.bootstrap_replicates) < 1000:
            raise BenchmarkContractError(
                "Frozen protocol requires at least 1000 bootstrap replicates"
            )
        for field_name in (
            "minimum_motion_improvement",
            "false_pocket_noninferiority_margin",
            "failure_rate_noninferiority_margin",
        ):
            value = float(getattr(self, field_name))
            if value < 0 or value > 1:
                raise BenchmarkContractError(f"{field_name} must be in [0, 1]")

    def freeze(self, **decisions: Any) -> "BenchmarkProtocol":
        """Create a frozen copy only after every endpoint decision is explicit."""
        if self.state == "frozen":
            raise BenchmarkContractError("Protocol is already frozen")
        return replace(self, state="frozen", **decisions)

    def to_manifest(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["top_k"] = list(self.top_k)
        payload["protocol_sha256"] = _stable_hash(payload)
        return payload

    @property
    def protocol_sha256(self) -> str:
        return self.to_manifest()["protocol_sha256"]


def phase6_frozen_protocol_v1() -> BenchmarkProtocol:
    """Return the predeclared CryptoBench v1 evaluation policy."""
    return BenchmarkProtocol("phase6-cryptobench-v1").freeze(
        dcc_tolerance_angstrom=4.0,
        dca_tolerance_angstrom=4.0,
        false_pocket_tolerance_angstrom=4.0,
        false_pocket_scope_k=5,
        bootstrap_replicates=5000,
        bootstrap_seed=20260729,
        minimum_motion_improvement=0.0,
        false_pocket_noninferiority_margin=0.0,
        failure_rate_noninferiority_margin=0.0,
    )


@dataclass(frozen=True)
class BenchmarkCase:
    """One evaluator target attached to a detector-visible apo structure."""

    case_id: str
    structure_id: str
    family_id: str
    split: SplitName
    prepared_structure_sha256: str
    preparation_config_sha256: str

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise BenchmarkContractError("case_id is required")
        if not self.structure_id.strip() or not self.family_id.strip():
            raise BenchmarkContractError("structure_id and family_id are required")
        if self.split not in {"development", "validation", "sealed"}:
            raise BenchmarkContractError("Unsupported benchmark split")
        _required_sha256(self.prepared_structure_sha256, "prepared_structure_sha256")
        _required_sha256(self.preparation_config_sha256, "preparation_config_sha256")

    def detector_input(self) -> dict[str, str]:
        """Return the complete and intentionally target-blind detector input."""
        return {
            "structure_id": self.structure_id.upper(),
            "prepared_structure_sha256": self.prepared_structure_sha256,
            "preparation_config_sha256": self.preparation_config_sha256,
        }


@dataclass(frozen=True)
class BenchmarkManifest:
    cases: tuple[BenchmarkCase, ...]
    schema_version: str = BENCHMARK_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != BENCHMARK_MANIFEST_SCHEMA_VERSION:
            raise BenchmarkContractError("Unsupported benchmark manifest schema")
        if not self.cases:
            raise BenchmarkContractError("Benchmark manifest cannot be empty")
        case_ids: set[str] = set()
        family_splits: dict[str, SplitName] = {}
        structure_contracts: dict[str, tuple[str, SplitName, str, str]] = {}
        for case in self.cases:
            case_id = case.case_id.casefold()
            if case_id in case_ids:
                raise BenchmarkContractError(
                    f"Duplicate case_id in benchmark manifest: {case.case_id}"
                )
            case_ids.add(case_id)
            structure_id = case.structure_id.upper()
            structure_contract = (
                case.family_id.casefold(),
                case.split,
                case.prepared_structure_sha256,
                case.preparation_config_sha256,
            )
            previous_structure_contract = structure_contracts.setdefault(
                structure_id,
                structure_contract,
            )
            if previous_structure_contract != structure_contract:
                raise BenchmarkContractError(
                    f"Structure '{structure_id}' has inconsistent family, split, or input hashes"
                )
            family_id = case.family_id.strip().casefold()
            previous_split = family_splits.setdefault(family_id, case.split)
            if previous_split != case.split:
                raise BenchmarkContractError(
                    f"Protein family '{case.family_id}' crosses benchmark splits"
                )

    def to_manifest(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "cases": [asdict(case) for case in self.cases],
        }
        payload["manifest_sha256"] = _stable_hash(payload)
        return payload

    @property
    def manifest_sha256(self) -> str:
        return self.to_manifest()["manifest_sha256"]

    def cases_for_split(self, split: SplitName) -> tuple[BenchmarkCase, ...]:
        return tuple(case for case in self.cases if case.split == split)


@dataclass(frozen=True)
class EvaluatorGroundTruth:
    """Evaluator-only holo evidence that must never enter detector input."""

    case_id: str
    structure_id: str
    coordinate_frame_sha256: str
    alignment_sha256: str
    ligand_center: tuple[float, float, float]
    ligand_atoms: tuple[tuple[float, float, float], ...]
    ligand_residues: tuple[str, ...] = ()
    quality: Literal["exact", "approximate"] = "exact"
    provenance: str = ""

    def __post_init__(self) -> None:
        if not self.case_id.strip() or not self.structure_id.strip():
            raise BenchmarkContractError("case_id and structure_id are required")
        _required_sha256(self.coordinate_frame_sha256, "coordinate_frame_sha256")
        _required_sha256(self.alignment_sha256, "alignment_sha256")
        _coordinate(self.ligand_center, "ligand_center")
        if not self.ligand_atoms:
            raise BenchmarkContractError("At least one ligand atom is required")
        for atom in self.ligand_atoms:
            _coordinate(atom, "ligand_atom")
        for residue in self.ligand_residues:
            _residue_identity(residue, "ligand_residue")
        if self.quality == "approximate" and not self.provenance.strip():
            raise BenchmarkContractError("Approximate ground truth requires explicit provenance")


@dataclass(frozen=True)
class CaseEvaluation:
    case_id: str
    structure_id: str
    detector: DetectorName
    status: Literal["completed", "unavailable", "failed"]
    dcc_by_rank: tuple[float, ...]
    dca_by_rank: tuple[float, ...]
    top_k_dcc_hits: dict[int, bool]
    top_k_dca_hits: dict[int, bool]
    false_pockets: int | None
    residue_precision: float | None
    residue_recall: float | None
    error: str | None
    ground_truth_quality: Literal["exact", "approximate"]
    score_used: bool = False
    schema_version: str = BENCHMARK_EVALUATION_SCHEMA_VERSION


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(a, b, strict=True)))


def _ordered_pockets(record: DetectorEvaluationRecord) -> tuple[EvaluatorPocket, ...]:
    ranks = [pocket.rank for pocket in record.pockets]
    if len(ranks) != len(set(ranks)) or any(rank < 1 for rank in ranks):
        raise BenchmarkContractError("Pocket ranks must be unique positive integers")
    return tuple(sorted(record.pockets, key=lambda pocket: (pocket.rank, pocket.pocket_id)))


def evaluate_case(
    record: DetectorEvaluationRecord,
    ground_truth: EvaluatorGroundTruth,
    protocol: BenchmarkProtocol,
    *,
    false_pocket_reference_centers: tuple[tuple[float, float, float], ...] | None = None,
) -> CaseEvaluation:
    """Evaluate ranked centers using geometry only; detector scores are ignored."""
    if protocol.state != "frozen":
        raise BenchmarkContractError("Canonical evaluation requires a frozen protocol")
    if record.schema_version != "pocket-evaluator-input-v1":
        raise BenchmarkContractError("Unsupported detector evaluation schema")
    if record.structure_id.upper() != ground_truth.structure_id.upper():
        raise BenchmarkContractError("Detector record and ground truth structure mismatch")
    if record.status != "completed":
        misses = {k: False for k in protocol.top_k}
        return CaseEvaluation(
            case_id=ground_truth.case_id,
            structure_id=record.structure_id.upper(),
            detector=record.detector,
            status=record.status,
            dcc_by_rank=(),
            dca_by_rank=(),
            top_k_dcc_hits=misses,
            top_k_dca_hits=dict(misses),
            false_pockets=None,
            residue_precision=None,
            residue_recall=None,
            error=record.error,
            ground_truth_quality=ground_truth.quality,
        )

    pockets = _ordered_pockets(record)
    dcc = tuple(_distance(pocket.center, ground_truth.ligand_center) for pocket in pockets)
    dca = tuple(
        min(_distance(pocket.center, atom) for atom in ground_truth.ligand_atoms)
        for pocket in pockets
    )
    top_k_dcc_hits = {
        k: any(distance <= float(protocol.dcc_tolerance_angstrom) for distance in dcc[:k])
        for k in protocol.top_k
    }
    top_k_dca_hits = {
        k: any(distance <= float(protocol.dca_tolerance_angstrom) for distance in dca[:k])
        for k in protocol.top_k
    }
    false_pockets: int | None = None
    if false_pocket_reference_centers is not None:
        if not false_pocket_reference_centers:
            raise BenchmarkContractError("False-pocket reference centers cannot be empty")
        reference_centers = tuple(
            _coordinate(center, "false_pocket_reference_center")
            for center in false_pocket_reference_centers
        )
        false_scope = pockets[: int(protocol.false_pocket_scope_k)]
        false_pockets = sum(
            min(_distance(pocket.center, center) for center in reference_centers)
            > float(protocol.false_pocket_tolerance_angstrom)
            for pocket in false_scope
        )

    residue_precision: float | None = None
    residue_recall: float | None = None
    if pockets and ground_truth.ligand_residues:
        residue_scope = min(len(dcc), max(protocol.top_k))
        nearest_index = min(range(residue_scope), key=dcc.__getitem__)
        raw_predicted = pockets[nearest_index].raw.get("residues", ())
        if not isinstance(raw_predicted, (list, tuple, set)):
            raise BenchmarkContractError("Pocket residues must be a sequence")
        predicted = {_residue_identity(residue, "pocket_residue") for residue in raw_predicted}
        expected = {
            _residue_identity(residue, "ligand_residue") for residue in ground_truth.ligand_residues
        }
        if predicted:
            residue_precision = len(predicted & expected) / len(predicted)
        residue_recall = len(predicted & expected) / len(expected)

    return CaseEvaluation(
        case_id=ground_truth.case_id,
        structure_id=record.structure_id.upper(),
        detector=record.detector,
        status="completed",
        dcc_by_rank=tuple(round(value, 8) for value in dcc),
        dca_by_rank=tuple(round(value, 8) for value in dca),
        top_k_dcc_hits=top_k_dcc_hits,
        top_k_dca_hits=top_k_dca_hits,
        false_pockets=false_pockets,
        residue_precision=(round(residue_precision, 8) if residue_precision is not None else None),
        residue_recall=round(residue_recall, 8) if residue_recall is not None else None,
        error=None,
        ground_truth_quality=ground_truth.quality,
    )


def _validate_sealed_access(
    ledger_path: str | Path | None,
    *,
    protocol: BenchmarkProtocol,
    manifest: BenchmarkManifest,
) -> None:
    if ledger_path is None:
        raise SealedHoldoutError("Sealed evaluation requires an access ledger")
    path = Path(ledger_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SealedHoldoutError("Sealed access ledger is missing or invalid") from exc
    if (
        payload.get("opened") is not True
        or payload.get("protocol_sha256") != protocol.protocol_sha256
        or payload.get("manifest_sha256") != manifest.manifest_sha256
    ):
        raise SealedHoldoutError("Sealed access ledger identity mismatch")


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    fraction = position - lower_index
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


def _family_cluster_bootstrap(
    cases: tuple[BenchmarkCase, ...],
    evaluations: list[CaseEvaluation],
    protocol: BenchmarkProtocol,
) -> dict[str, Any]:
    grouped: dict[str, list[CaseEvaluation]] = {}
    for case, evaluation in zip(cases, evaluations, strict=True):
        grouped.setdefault(case.family_id.casefold(), []).append(evaluation)
    families = tuple(sorted(grouped))
    family_stats: list[dict[str, Any]] = []
    for family in families:
        family_evaluations = grouped[family]
        family_stats.append(
            {
                "targets": len(family_evaluations),
                "dcc": {
                    k: sum(result.top_k_dcc_hits[k] for result in family_evaluations)
                    for k in protocol.top_k
                },
                "dca": {
                    k: sum(result.top_k_dca_hits[k] for result in family_evaluations)
                    for k in protocol.top_k
                },
            }
        )

    replicates = int(protocol.bootstrap_replicates)
    rng = random.Random(int(protocol.bootstrap_seed))
    dcc_samples = {k: [] for k in protocol.top_k}
    dca_samples = {k: [] for k in protocol.top_k}
    for _ in range(replicates):
        selected = [family_stats[rng.randrange(len(family_stats))] for _ in families]
        denominator = sum(int(item["targets"]) for item in selected)
        for k in protocol.top_k:
            dcc_samples[k].append(sum(int(item["dcc"][k]) for item in selected) / denominator)
            dca_samples[k].append(sum(int(item["dca"][k]) for item in selected) / denominator)

    def intervals(samples: Mapping[int, list[float]]) -> dict[int, list[float]]:
        return {
            k: [
                round(_percentile(values, 0.025), 8),
                round(_percentile(values, 0.975), 8),
            ]
            for k, values in samples.items()
        }

    return {
        "method": "percentile_cluster_bootstrap",
        "resampling_unit": "family",
        "confidence_level": 0.95,
        "replicates": replicates,
        "seed": int(protocol.bootstrap_seed),
        "family_count": len(families),
        "top_k_dcc_recall_95_ci": intervals(dcc_samples),
        "top_k_dca_recall_95_ci": intervals(dca_samples),
    }


def evaluate_split(
    *,
    detector: DetectorName,
    split: SplitName,
    records: Mapping[str, DetectorEvaluationRecord],
    ground_truth: Mapping[str, EvaluatorGroundTruth],
    binding_site_reference_centers: (
        Mapping[str, tuple[tuple[float, float, float], ...]] | None
    ) = None,
    manifest: BenchmarkManifest,
    protocol: BenchmarkProtocol,
    sealed_ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate every manifest case; missing and failed cases stay in the denominator."""
    if split == "sealed":
        _validate_sealed_access(
            sealed_ledger_path,
            protocol=protocol,
            manifest=manifest,
        )
    cases = manifest.cases_for_split(split)
    if not cases:
        raise BenchmarkContractError(f"No cases found for split '{split}'")
    normalized_records = {key.upper(): value for key, value in records.items()}
    normalized_truth = {key.casefold(): value for key, value in ground_truth.items()}
    if len(normalized_records) != len(records) or len(normalized_truth) != len(ground_truth):
        raise BenchmarkContractError("Duplicate case IDs after normalization")

    normalized_binding_sites: (
        dict[
            str,
            tuple[tuple[float, float, float], ...],
        ]
        | None
    ) = None
    if binding_site_reference_centers is not None:
        normalized_binding_sites = {
            key.upper(): tuple(
                _coordinate(center, "binding_site_reference_center") for center in centers
            )
            for key, centers in binding_site_reference_centers.items()
        }
        if any(not centers for centers in normalized_binding_sites.values()):
            raise BenchmarkContractError("Binding-site reference center lists cannot be empty")

    evaluations: list[CaseEvaluation] = []
    for case in cases:
        truth = normalized_truth.get(case.case_id.casefold())
        if truth is None:
            raise BenchmarkContractError(
                f"Evaluator ground truth missing for manifest case {case.case_id}"
            )
        if truth.case_id.casefold() != case.case_id.casefold():
            raise BenchmarkContractError(
                f"Ground truth case identity mismatch for manifest case {case.case_id}"
            )
        structure_id = case.structure_id.upper()
        if truth.structure_id.upper() != structure_id:
            raise BenchmarkContractError(
                f"Ground truth structure mismatch for manifest case {case.case_id}"
            )
        if truth.coordinate_frame_sha256 != case.prepared_structure_sha256:
            raise BenchmarkContractError(
                f"Ground truth coordinate frame mismatch for manifest case {case.case_id}"
            )
        record = normalized_records.get(structure_id)
        if record is None:
            record = failed_record(detector, structure_id, "missing_detector_result")
        if record.structure_id.upper() != structure_id:
            raise BenchmarkContractError(
                f"Detector record identity mismatch for manifest case {structure_id}"
            )
        if record.detector != detector:
            raise BenchmarkContractError(
                f"Detector mismatch for {structure_id}: {record.detector} != {detector}"
            )
        evaluations.append(
            evaluate_case(
                record,
                truth,
                protocol,
                false_pocket_reference_centers=(
                    normalized_binding_sites.get(structure_id)
                    if normalized_binding_sites is not None
                    else None
                ),
            )
        )

    total = len(evaluations)
    completed = sum(result.status == "completed" for result in evaluations)
    failed = total - completed
    structure_ids = tuple(dict.fromkeys(case.structure_id.upper() for case in cases))
    completed_structure_ids = tuple(
        structure_id
        for structure_id in structure_ids
        if structure_id in normalized_records
        and normalized_records[structure_id].status == "completed"
    )
    failed_structures = len(structure_ids) - len(completed_structure_ids)
    if normalized_binding_sites is not None:
        missing_binding_sites = set(structure_ids) - set(normalized_binding_sites)
        if missing_binding_sites:
            raise BenchmarkContractError(
                "Binding-site references missing for structures: "
                + ", ".join(sorted(missing_binding_sites))
            )
    top_k_recall = {
        k: round(
            sum(result.top_k_dcc_hits[k] for result in evaluations) / total,
            8,
        )
        for k in protocol.top_k
    }
    top_k_dca_recall = {
        k: round(
            sum(result.top_k_dca_hits[k] for result in evaluations) / total,
            8,
        )
        for k in protocol.top_k
    }
    distance_scope = max(protocol.top_k)
    best_dcc = [
        min(result.dcc_by_rank[:distance_scope]) for result in evaluations if result.dcc_by_rank
    ]
    best_dca = [
        min(result.dca_by_rank[:distance_scope]) for result in evaluations if result.dca_by_rank
    ]
    completed_records = [
        normalized_records[structure_id] for structure_id in completed_structure_ids
    ]
    runtimes = [
        float(record.provenance["runtime_seconds"])
        for record in completed_records
        if record.provenance is not None and record.provenance.get("runtime_seconds") is not None
    ]
    peak_memory = [
        int(record.provenance["peak_rss_bytes"])
        for record in completed_records
        if record.provenance is not None and record.provenance.get("peak_rss_bytes") is not None
    ]
    false_pocket_by_structure: dict[str, int] = {}
    for result in evaluations:
        if result.false_pockets is not None:
            false_pocket_by_structure.setdefault(
                result.structure_id,
                result.false_pockets,
            )
    false_pocket_values = list(false_pocket_by_structure.values())
    return {
        "schema_version": BENCHMARK_EVALUATION_SCHEMA_VERSION,
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol.protocol_sha256,
        "manifest_sha256": manifest.manifest_sha256,
        "split": split,
        "detector": detector,
        "target_denominator": total,
        "structure_denominator": len(structure_ids),
        "denominator": total,
        "completed_targets": completed,
        "failed_or_unavailable_targets": failed,
        "completed_structures": len(completed_structure_ids),
        "failed_or_unavailable_structures": failed_structures,
        "completed": completed,
        "failed_or_unavailable": failed,
        "failure_rate": round(failed_structures / len(structure_ids), 8),
        "target_failure_rate": round(failed / total, 8),
        "top_k_dcc_recall": top_k_recall,
        "top_k_dca_recall": top_k_dca_recall,
        "bootstrap": _family_cluster_bootstrap(cases, evaluations, protocol),
        "distance_denominator": len(best_dcc),
        "mean_best_dcc_angstrom": (round(sum(best_dcc) / len(best_dcc), 8) if best_dcc else None),
        "mean_best_dca_angstrom": (round(sum(best_dca) / len(best_dca), 8) if best_dca else None),
        "false_pocket_denominator": len(false_pocket_values),
        "false_pocket_metric_status": (
            "complete_annotations" if normalized_binding_sites is not None else "unavailable"
        ),
        "false_pockets_per_completed_protein": (
            round(sum(false_pocket_values) / len(false_pocket_values), 8)
            if false_pocket_values
            else None
        ),
        "runtime_seconds_total": round(sum(runtimes), 8) if runtimes else None,
        "peak_rss_bytes_max": max(peak_memory) if peak_memory else None,
        "resource_reporting_complete": (
            len(runtimes) == len(completed_records) and len(peak_memory) == len(completed_records)
        ),
        "score_used": False,
        "results": [asdict(result) for result in evaluations],
    }


def _summary_top_k(summary: Mapping[str, Any], metric: str, rank: int) -> float:
    values = summary.get(metric)
    if not isinstance(values, Mapping):
        raise BenchmarkContractError(f"Benchmark summary is missing {metric}")
    value = values.get(rank, values.get(str(rank)))
    if value is None:
        raise BenchmarkContractError(f"Benchmark summary is missing {metric} Top-{rank}")
    result = float(value)
    if not math.isfinite(result) or result < 0.0 or result > 1.0:
        raise BenchmarkContractError(f"Benchmark summary has invalid {metric} Top-{rank}")
    return result


def assess_motion_integration(
    static_summary: Mapping[str, Any],
    motion_summary: Mapping[str, Any],
    protocol: BenchmarkProtocol,
) -> dict[str, Any]:
    """Apply the frozen scientific gate without changing either detector result."""
    if protocol.state != "frozen":
        raise BenchmarkContractError("Motion integration assessment requires a frozen protocol")
    if static_summary.get("detector") != "biovoid_static":
        raise BenchmarkContractError("Static summary must belong to biovoid_static")
    if motion_summary.get("detector") != "biovoid_motion":
        raise BenchmarkContractError("Motion summary must belong to biovoid_motion")

    identity_fields = (
        "protocol_sha256",
        "manifest_sha256",
        "split",
        "target_denominator",
        "structure_denominator",
    )
    for field_name in identity_fields:
        if static_summary.get(field_name) != motion_summary.get(field_name):
            raise BenchmarkContractError(f"Static and motion summaries differ on {field_name}")
    if static_summary.get("protocol_sha256") != protocol.protocol_sha256:
        raise BenchmarkContractError("Benchmark summary protocol hash mismatch")

    static_primary = _summary_top_k(static_summary, "top_k_dcc_recall", 3)
    motion_primary = _summary_top_k(motion_summary, "top_k_dcc_recall", 3)
    improvement = motion_primary - static_primary
    reasons: list[str] = []
    primary_passed = improvement > 0.0 and improvement >= float(protocol.minimum_motion_improvement)
    if not primary_passed:
        reasons.append("primary_endpoint_not_strictly_improved")

    complete_references = all(
        summary.get("false_pocket_metric_status") == "complete_annotations"
        and summary.get("false_pockets_per_completed_protein") is not None
        for summary in (static_summary, motion_summary)
    )
    false_pocket_passed = False
    static_false_pockets: float | None = None
    motion_false_pockets: float | None = None
    if complete_references:
        static_false_pockets = float(static_summary["false_pockets_per_completed_protein"])
        motion_false_pockets = float(motion_summary["false_pockets_per_completed_protein"])
        false_pocket_passed = motion_false_pockets <= (
            static_false_pockets + float(protocol.false_pocket_noninferiority_margin)
        )
        if not false_pocket_passed:
            reasons.append("false_pocket_noninferiority_failed")
    else:
        reasons.append("complete_binding_site_references_required")

    static_failure_rate = float(static_summary.get("failure_rate", 1.0))
    motion_failure_rate = float(motion_summary.get("failure_rate", 1.0))
    failure_rate_passed = motion_failure_rate <= (
        static_failure_rate + float(protocol.failure_rate_noninferiority_margin)
    )
    if not failure_rate_passed:
        reasons.append("failure_rate_noninferiority_failed")

    resources_complete = all(
        summary.get("resource_reporting_complete") is True
        for summary in (static_summary, motion_summary)
    )
    if not resources_complete:
        reasons.append("resource_reporting_incomplete")

    eligible = primary_passed and false_pocket_passed and failure_rate_passed and resources_complete
    return {
        "schema_version": "motion-integration-decision-v1",
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol.protocol_sha256,
        "manifest_sha256": static_summary["manifest_sha256"],
        "split": static_summary["split"],
        "canonical_integration_eligible": eligible,
        "decision": "ELIGIBLE" if eligible else "NOT_ELIGIBLE",
        "reasons": reasons,
        "primary_endpoint": protocol.primary_endpoint,
        "static_primary_recall": static_primary,
        "motion_primary_recall": motion_primary,
        "primary_improvement": round(improvement, 8),
        "minimum_motion_improvement": protocol.minimum_motion_improvement,
        "complete_binding_site_references": complete_references,
        "static_false_pockets_per_completed_protein": static_false_pockets,
        "motion_false_pockets_per_completed_protein": motion_false_pockets,
        "false_pocket_noninferiority_margin": (protocol.false_pocket_noninferiority_margin),
        "static_failure_rate": static_failure_rate,
        "motion_failure_rate": motion_failure_rate,
        "failure_rate_noninferiority_margin": (protocol.failure_rate_noninferiority_margin),
        "resource_reporting_complete": resources_complete,
    }


class SealedHoldoutLedger:
    """One-way local ledger that prevents accidental repeated sealed evaluation."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def authorize_once(
        self,
        *,
        protocol: BenchmarkProtocol,
        manifest: BenchmarkManifest,
        explicit_user_authorization: bool,
    ) -> dict[str, Any]:
        if not explicit_user_authorization:
            raise SealedHoldoutError("Explicit user authorization is required")
        if protocol.state != "frozen":
            raise SealedHoldoutError("Sealed holdout requires a frozen protocol")
        if not manifest.cases_for_split("sealed"):
            raise SealedHoldoutError("Manifest has no sealed cases")
        if self.path.exists():
            raise SealedHoldoutError("Sealed holdout has already been opened")

        payload = {
            "schema_version": "sealed-holdout-ledger-v1",
            "protocol_sha256": protocol.protocol_sha256,
            "manifest_sha256": manifest.manifest_sha256,
            "opened": True,
            "opened_at_utc": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.parent / f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
        return payload


@dataclass(frozen=True)
class BenchmarkResourceRequest:
    case_count: int
    batch_size: int
    analysis_workers: int
    maximum_ca_atoms: int
    include_motion: bool
    motion_modes: int = 0
    samples_per_mode: int = 0


def preflight_benchmark_resources(
    request: BenchmarkResourceRequest,
    *,
    available_memory_bytes: int,
    profile: ResourceProfile = SAFE_16GB,
) -> dict[str, Any]:
    """Reject an unsafe benchmark plan before any detector process starts."""
    if request.case_count < 1:
        raise ResourceLimitError("Benchmark case_count must be positive")
    if request.batch_size < 1 or request.batch_size > MAX_SAFE_16GB_BATCH_SIZE:
        raise ResourceLimitError(
            f"safe-16gb benchmark batches allow 1-{MAX_SAFE_16GB_BATCH_SIZE} cases"
        )
    if request.analysis_workers < 1 or request.analysis_workers > profile.max_analysis_workers:
        raise ResourceLimitError(
            f"{profile.name} allows 1-{profile.max_analysis_workers} analysis workers"
        )
    if available_memory_bytes < profile.minimum_available_memory_bytes:
        raise ResourceLimitError("Available memory is below the safe-16gb reserve")
    if request.maximum_ca_atoms < 1 or request.maximum_ca_atoms > profile.max_nma_atoms:
        raise ResourceLimitError(
            f"{profile.name} benchmark preflight limits structures to "
            f"{profile.max_nma_atoms} C-alpha atoms"
        )

    estimated_heavy_bytes: int | None = None
    recommended_workers = min(request.analysis_workers, profile.max_analysis_workers)
    if request.include_motion:
        if request.analysis_workers > profile.max_heavy_jobs:
            raise ResourceLimitError(
                f"{profile.name} allows only {profile.max_heavy_jobs} heavy motion job"
            )
        estimated_heavy_bytes = profile.validate_motion_request(
            atom_count=request.maximum_ca_atoms,
            samples_per_mode=request.samples_per_mode,
            mode_count=request.motion_modes,
            available_memory_bytes=available_memory_bytes,
            solver="auto",
        )
        recommended_workers = profile.max_heavy_jobs

    return {
        "schema_version": BENCHMARK_READINESS_VERSION,
        "resource_profile": profile.name,
        "safe_to_start_bounded_pilot": True,
        "full_benchmark_approved": False,
        "case_count": request.case_count,
        "batch_size": request.batch_size,
        "recommended_workers": recommended_workers,
        "estimated_heavy_peak_bytes": estimated_heavy_bytes,
        "memory_estimate_scope": (
            "nma_hessian_only" if request.include_motion else "not_estimated"
        ),
        "minimum_memory_reserve_bytes": profile.minimum_available_memory_bytes,
        "runtime_estimate": "requires_bounded_pilot",
        "checkpoint_required": request.case_count > request.batch_size,
    }
