"""Metadata-only target-family selection and target-blind pilot manifests.

The module intentionally keeps evaluator metadata (holo accessions and ligand
components) in private Python objects.  ``build_detector_manifest`` emits only
apo structure identities and bounded static-run constraints, so its serialized
payload can be passed to a detector without leaking the selection evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping


TARGET_FAMILY_MANIFEST_SCHEMA_VERSION = "biovoid-target-family-static-pilot-v1"
TARGET_FAMILY_COHORT_MANIFEST_SCHEMA_VERSION = "biovoid-target-family-cohort-detector-v1"
DEFAULT_MIN_SEQUENCE_LENGTH = 180
DEFAULT_MAX_SEQUENCE_LENGTH = 350
DEFAULT_MAX_RESOLUTION_ANGSTROM = 2.8
MAX_PILOT_CASES = 10

# Common solvent, buffer, ion, crystallization and artifact components.  The
# list is deliberately conservative: unknown components remain candidates for
# private manual review rather than being silently treated as apo evidence.
NON_LIGAND_COMPONENT_IDS = frozenset(
    {
        "ACE",
        "ACT",
        "BME",
        "BR",
        "CA",
        "CL",
        "CO",
        "DMS",
        "EDO",
        "EOH",
        "FMT",
        "GOL",
        "HOH",
        "IOD",
        "K",
        "MG",
        "MN",
        "NA",
        "NH4",
        "NI",
        "NO3",
        "PEG",
        "PGE",
        "PG4",
        "PO4",
        "SO4",
        "TLA",
        "TRS",
        "UNL",
        "UNX",
    }
)


class TargetFamilyContractError(ValueError):
    """Raised when target-family metadata violates the pilot contract."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TargetFamilyContractError(f"{field_name} must be a non-empty string")
    return value.strip()


def _normalise_pdb_id(value: Any, field_name: str = "pdb_id") -> str:
    text = _required_text(value, field_name).upper()
    if re.fullmatch(r"[A-Z0-9]{4}", text) is None:
        raise TargetFamilyContractError(f"{field_name} must be a four-character PDB ID")
    return text


@dataclass(frozen=True)
class NonPolymerComponent:
    """One RCSB non-polymer component from metadata only."""

    comp_id: str
    name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "comp_id", _required_text(self.comp_id, "comp_id").upper())
        object.__setattr__(self, "name", _required_text(self.name, "name"))

    @property
    def is_likely_ligand(self) -> bool:
        return self.comp_id not in NON_LIGAND_COMPONENT_IDS


@dataclass(frozen=True)
class RcsbMetadataRecord:
    """A structure/entity record obtained without downloading coordinates."""

    pdb_id: str
    uniprot_ids: tuple[str, ...]
    family_id: str
    description: str
    sequence_length: int
    resolution_angstrom: float | None
    experimental_method: str
    nonpolymer_components: tuple[NonPolymerComponent, ...] = ()
    pfam_ids: tuple[str, ...] = ()
    release_date: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "pdb_id", _normalise_pdb_id(self.pdb_id))
        uniprots = tuple(
            sorted({_required_text(value, "uniprot_id").upper() for value in self.uniprot_ids})
        )
        if not uniprots:
            raise TargetFamilyContractError("At least one UniProt ID is required")
        object.__setattr__(self, "uniprot_ids", uniprots)
        object.__setattr__(self, "family_id", _required_text(self.family_id, "family_id"))
        object.__setattr__(self, "description", _required_text(self.description, "description"))
        if not isinstance(self.sequence_length, int) or self.sequence_length < 1:
            raise TargetFamilyContractError("sequence_length must be a positive integer")
        if self.resolution_angstrom is not None:
            resolution = float(self.resolution_angstrom)
            if not math.isfinite(resolution) or resolution <= 0:
                raise TargetFamilyContractError("resolution_angstrom must be positive and finite")
            object.__setattr__(self, "resolution_angstrom", resolution)
        object.__setattr__(
            self,
            "experimental_method",
            _required_text(self.experimental_method, "experimental_method"),
        )
        object.__setattr__(self, "nonpolymer_components", tuple(self.nonpolymer_components))
        object.__setattr__(
            self,
            "pfam_ids",
            tuple(sorted({_required_text(value, "pfam_id") for value in self.pfam_ids})),
        )

    @property
    def primary_group_id(self) -> str:
        return "+".join(self.uniprot_ids)

    @property
    def likely_ligand_components(self) -> tuple[NonPolymerComponent, ...]:
        return tuple(
            component for component in self.nonpolymer_components if component.is_likely_ligand
        )

    @property
    def has_likely_ligand(self) -> bool:
        return bool(self.likely_ligand_components)

    def passes_common_quality(
        self,
        *,
        min_sequence_length: int = DEFAULT_MIN_SEQUENCE_LENGTH,
        max_sequence_length: int = DEFAULT_MAX_SEQUENCE_LENGTH,
        max_resolution_angstrom: float = DEFAULT_MAX_RESOLUTION_ANGSTROM,
    ) -> bool:
        method = self.experimental_method.casefold()
        return (
            "x-ray" in method
            and min_sequence_length <= self.sequence_length <= max_sequence_length
            and self.resolution_angstrom is not None
            and self.resolution_angstrom <= max_resolution_angstrom
        )

    def is_apo_candidate(self, **quality_kwargs: Any) -> bool:
        return self.passes_common_quality(**quality_kwargs) and not self.has_likely_ligand

    def is_holo_candidate(self, **quality_kwargs: Any) -> bool:
        return self.passes_common_quality(**quality_kwargs) and self.has_likely_ligand


@dataclass(frozen=True)
class PilotPair:
    """Private selection pair; the holo side never enters the detector manifest."""

    case_id: str
    family_id: str
    apo: RcsbMetadataRecord
    holo: RcsbMetadataRecord

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _required_text(self.case_id, "case_id"))
        object.__setattr__(self, "family_id", _required_text(self.family_id, "family_id"))
        if self.apo.primary_group_id != self.holo.primary_group_id:
            raise TargetFamilyContractError("Apo and holo records must share a UniProt group")
        if self.apo.has_likely_ligand or not self.holo.has_likely_ligand:
            raise TargetFamilyContractError(
                "PilotPair sides do not satisfy apo/holo metadata policy"
            )

    def private_metadata(self) -> dict[str, Any]:
        """Return evaluator-side metadata for ignored local storage only."""

        return {
            "case_id": self.case_id,
            "family_id": self.family_id,
            "uniprot_group": self.apo.primary_group_id,
            "apo_pdb_id": self.apo.pdb_id,
            "holo_pdb_id": self.holo.pdb_id,
            "holo_components": [
                {"comp_id": component.comp_id, "name": component.name}
                for component in self.holo.likely_ligand_components
            ],
        }


def _case_id(record: RcsbMetadataRecord) -> str:
    suffix = _stable_hash(
        {
            "family_id": record.family_id,
            "pdb_id": record.pdb_id,
            "uniprot_group": record.primary_group_id,
        }
    )[:16]
    return f"{record.family_id}:{record.pdb_id}:{suffix}"


def _best_apo(records: Iterable[RcsbMetadataRecord]) -> RcsbMetadataRecord:
    return min(
        records, key=lambda record: (record.resolution_angstrom or float("inf"), record.pdb_id)
    )


def _best_holo(records: Iterable[RcsbMetadataRecord]) -> RcsbMetadataRecord:
    return min(
        records,
        key=lambda record: (
            record.resolution_angstrom or float("inf"),
            -len(record.likely_ligand_components),
            record.pdb_id,
        ),
    )


def select_pilot_pairs(
    records: Iterable[RcsbMetadataRecord],
    *,
    max_cases: int = MAX_PILOT_CASES,
    min_sequence_length: int = DEFAULT_MIN_SEQUENCE_LENGTH,
    max_sequence_length: int = DEFAULT_MAX_SEQUENCE_LENGTH,
    max_resolution_angstrom: float = DEFAULT_MAX_RESOLUTION_ANGSTROM,
) -> tuple[PilotPair, ...]:
    """Select at most one deterministic pair per UniProt group."""

    if max_cases < 1:
        raise ValueError("max_cases must be positive")
    if max_cases > MAX_PILOT_CASES:
        raise ValueError(f"max_cases cannot exceed {MAX_PILOT_CASES}")
    grouped: dict[str, list[RcsbMetadataRecord]] = {}
    for record in records:
        grouped.setdefault(record.primary_group_id, []).append(record)

    selected: list[PilotPair] = []
    quality = {
        "min_sequence_length": min_sequence_length,
        "max_sequence_length": max_sequence_length,
        "max_resolution_angstrom": max_resolution_angstrom,
    }
    for group_id in sorted(grouped):
        group = grouped[group_id]
        apo_candidates = [record for record in group if record.is_apo_candidate(**quality)]
        holo_candidates = [record for record in group if record.is_holo_candidate(**quality)]
        if not apo_candidates or not holo_candidates:
            continue
        apo = _best_apo(apo_candidates)
        holo = _best_holo(holo_candidates)
        selected.append(
            PilotPair(
                case_id=_case_id(apo),
                family_id=apo.family_id,
                apo=apo,
                holo=holo,
            )
        )
        if len(selected) >= max_cases:
            break
    return tuple(selected)


def build_detector_manifest(pairs: Iterable[PilotPair]) -> dict[str, Any]:
    """Build a redacted, bounded manifest suitable for detector input."""

    pair_list = tuple(pairs)
    if not pair_list:
        raise TargetFamilyContractError("At least one pilot pair is required")
    if len(pair_list) > MAX_PILOT_CASES:
        raise TargetFamilyContractError(f"Pilot manifest cannot exceed {MAX_PILOT_CASES} cases")
    family_ids = sorted({pair.family_id for pair in pair_list})
    if len(family_ids) != 1:
        raise TargetFamilyContractError("Pilot manifest must contain one selected family")
    cases = [
        {
            "case_id": pair.case_id,
            "structure_id": pair.apo.pdb_id,
            "family_id": pair.family_id,
            "split": "development",
        }
        for pair in pair_list
    ]
    payload: dict[str, Any] = {
        "schema_version": TARGET_FAMILY_MANIFEST_SCHEMA_VERSION,
        "manifest_kind": "target_blind_static_pilot",
        "materialization_status": "metadata_only",
        "family_id": family_ids[0],
        "selection_policy": {
            "one_case_per_uniprot_group": True,
            "metadata_only_selection": True,
            "quality_filter_version": "xray-180-350aa-resolution-2.8-v1",
        },
        "constraints": {
            "case_count": len(cases),
            "max_case_count": MAX_PILOT_CASES,
            "batch_size": len(cases),
            "analysis_workers": 1,
            "include_motion": False,
            "safe_profile": "safe-16gb",
        },
        "boundary": "apo_structure_only_v1",
        "cases": cases,
        "manifest_sha256": None,
    }
    payload["manifest_sha256"] = _stable_hash(
        {key: value for key, value in payload.items() if key != "manifest_sha256"}
    )
    validate_detector_manifest(payload)
    return payload


def validate_detector_manifest(payload: Mapping[str, Any]) -> None:
    """Validate the redacted pilot manifest and its resource boundary."""

    schema_version = payload.get("schema_version")
    if schema_version not in {
        TARGET_FAMILY_MANIFEST_SCHEMA_VERSION,
        TARGET_FAMILY_COHORT_MANIFEST_SCHEMA_VERSION,
    }:
        raise TargetFamilyContractError("Unsupported target-family manifest schema")
    if schema_version == TARGET_FAMILY_MANIFEST_SCHEMA_VERSION:
        if payload.get("manifest_kind") != "target_blind_static_pilot":
            raise TargetFamilyContractError("Unsupported target-family manifest kind")
    else:
        if payload.get("manifest_kind") != "target_blind_cohort":
            raise TargetFamilyContractError("Unsupported target-family cohort manifest kind")
        if payload.get("split_strategy") != "sequence_cluster_temporal_holdout_v1":
            raise TargetFamilyContractError("Cohort manifest split strategy is unsupported")
    if payload.get("materialization_status") != "metadata_only":
        raise TargetFamilyContractError("Pilot manifest must remain metadata-only")
    if payload.get("boundary") != "apo_structure_only_v1":
        raise TargetFamilyContractError("Pilot manifest boundary is not apo-only")
    constraints = payload.get("constraints")
    if not isinstance(constraints, Mapping):
        raise TargetFamilyContractError("Pilot manifest is missing constraints")
    if constraints.get("analysis_workers") != 1 or constraints.get("include_motion") is not False:
        raise TargetFamilyContractError("Pilot manifest violates single-worker static boundary")
    case_count = constraints.get("case_count")
    if not isinstance(case_count, int) or not 1 <= case_count <= MAX_PILOT_CASES:
        raise TargetFamilyContractError("Pilot case count must be between 1 and 10")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != case_count:
        raise TargetFamilyContractError("Pilot case count does not match cases")
    case_ids: set[str] = set()
    structures: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping):
            raise TargetFamilyContractError("Pilot case must be an object")
        for field in ("case_id", "structure_id", "family_id", "split"):
            _required_text(case.get(field), f"case.{field}")
        if (
            schema_version == TARGET_FAMILY_MANIFEST_SCHEMA_VERSION
            and case["split"] != "development"
        ):
            raise TargetFamilyContractError("Pilot cases must use the development split")
        if schema_version == TARGET_FAMILY_COHORT_MANIFEST_SCHEMA_VERSION and case["split"] not in {
            "development",
            "validation",
            "test",
        }:
            raise TargetFamilyContractError("Cohort cases must use a supported split")
        case_id = str(case["case_id"]).casefold()
        structure_id = _normalise_pdb_id(case["structure_id"], "case.structure_id")
        if case_id in case_ids or structure_id in structures:
            raise TargetFamilyContractError("Pilot cases must have unique IDs and structures")
        case_ids.add(case_id)
        structures.add(structure_id)
    expected_hash = _stable_hash(
        {key: value for key, value in payload.items() if key != "manifest_sha256"}
    )
    if payload.get("manifest_sha256") != expected_hash:
        raise TargetFamilyContractError("Pilot manifest hash mismatch")
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True).casefold()
    for forbidden in ("holo", "ligand", "evaluator", "ground_truth"):
        if forbidden in serialized:
            raise TargetFamilyContractError(
                f"Detector manifest contains forbidden evaluator token: {forbidden}"
            )
