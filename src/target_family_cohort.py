"""Leakage-audited target-family cohort contracts.

The cohort input is evaluator-side metadata and is therefore expected to stay
in an ignored local directory.  This module validates the independent label
and split rules, then emits a redacted apo-only manifest for detector work.
It does not download structures, calculate sequence identity, or train a
model; sequence clusters and release dates must be supplied by the metadata
curation step and are treated as locked inputs here.
"""

from __future__ import annotations

from datetime import date
import hashlib
import json
import re
from typing import Any, Mapping


COHORT_SCHEMA_VERSION = "biovoid-target-family-cohort-v1"
TARGET_BLIND_MANIFEST_SCHEMA_VERSION = "biovoid-target-family-cohort-detector-v1"
MAX_COHORT_CASES = 10
ALLOWED_SPLITS = frozenset({"development", "validation", "test"})
ALLOWED_LABEL_SOURCES = frozenset(
    {"holo_ligand_contact_v1", "independent_annotation_v1"}
)
SPLIT_STRATEGY = "sequence_cluster_temporal_holdout_v1"
_PDB_ID_RE = re.compile(r"^[A-Z0-9]{4}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FORBIDDEN_TARGET_TOKENS = ("holo", "ligand", "evaluator", "ground_truth", "bio_score")


class CohortContractError(ValueError):
    """Raised when a private cohort or redacted manifest violates its contract."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CohortContractError(f"{field} must be a non-empty string")
    return value.strip()


def _pdb_id(value: Any, field: str) -> str:
    normalized = _required_text(value, field).upper()
    if _PDB_ID_RE.fullmatch(normalized) is None:
        raise CohortContractError(f"{field} must be a four-character PDB ID")
    return normalized


def _iso_date(value: Any, field: str) -> date:
    text = _required_text(value, field)
    if _DATE_RE.fullmatch(text) is None:
        raise CohortContractError(f"{field} must use YYYY-MM-DD")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise CohortContractError(f"{field} is not a valid calendar date") from exc


def _case_list(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    cases = payload.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_COHORT_CASES:
        raise CohortContractError(
            f"cohort case count must be between 1 and {MAX_COHORT_CASES}"
        )
    if any(not isinstance(case, Mapping) for case in cases):
        raise CohortContractError("every cohort case must be an object")
    return [case for case in cases if isinstance(case, Mapping)]


def _overlap_by_split(cases: list[Mapping[str, Any]], field: str) -> dict[str, list[str]]:
    split_by_value: dict[str, set[str]] = {}
    for case in cases:
        value = str(case[field])
        split_by_value.setdefault(value, set()).add(str(case["split"]))
    return {
        value: sorted(splits)
        for value, splits in sorted(split_by_value.items())
        if len(splits) > 1
    }


def validate_cohort_manifest(payload: Mapping[str, Any]) -> None:
    """Validate evaluator-side metadata before any detector manifest is built."""

    if payload.get("schema_version") != COHORT_SCHEMA_VERSION:
        raise CohortContractError("unsupported target-family cohort schema")
    if payload.get("manifest_kind") != "private_target_family_cohort":
        raise CohortContractError("cohort manifest must be private metadata")
    family_id = _required_text(payload.get("family_id"), "family_id")
    if payload.get("split_strategy") != SPLIT_STRATEGY:
        raise CohortContractError("cohort split strategy is not sequence/temporal holdout")
    cutoff = _iso_date(payload.get("temporal_cutoff"), "temporal_cutoff")
    cases = _case_list(payload)
    case_ids: set[str] = set()
    apo_ids: set[str] = set()
    holo_ids: set[str] = set()
    for case in cases:
        case_id = _required_text(case.get("case_id"), "case.case_id").casefold()
        if case_id in case_ids:
            raise CohortContractError("cohort case IDs must be unique")
        case_ids.add(case_id)
        apo_id = _pdb_id(case.get("apo_structure_id"), "case.apo_structure_id")
        holo_id = _pdb_id(case.get("holo_structure_id"), "case.holo_structure_id")
        if apo_id in apo_ids or holo_id in holo_ids or apo_id == holo_id:
            raise CohortContractError("cohort structure IDs must be unique and paired")
        apo_ids.add(apo_id)
        holo_ids.add(holo_id)
        if _required_text(case.get("family_id"), "case.family_id") != family_id:
            raise CohortContractError("all cohort cases must use the selected family")
        _required_text(case.get("uniprot_group_id"), "case.uniprot_group_id")
        _required_text(case.get("sequence_cluster_id"), "case.sequence_cluster_id")
        split = _required_text(case.get("split"), "case.split")
        if split not in ALLOWED_SPLITS:
            raise CohortContractError(f"unsupported cohort split: {split}")
        apo_date = _iso_date(case.get("apo_release_date"), "case.apo_release_date")
        _iso_date(case.get("holo_release_date"), "case.holo_release_date")
        if split == "test" and apo_date < cutoff:
            raise CohortContractError("test case apo release must be on/after temporal cutoff")
        if split != "test" and apo_date >= cutoff:
            raise CohortContractError("development/validation apo release must be before temporal cutoff")
        label_source = _required_text(case.get("label_source"), "case.label_source")
        if label_source not in ALLOWED_LABEL_SOURCES:
            raise CohortContractError(
                "cohort requires an independent label source, not BioVoid heuristic labels"
            )
    sequence_overlap = _overlap_by_split(cases, "sequence_cluster_id")
    if sequence_overlap:
        raise CohortContractError(
            f"sequence cluster overlap across splits: {sorted(sequence_overlap)}"
        )
    uniprot_overlap = _overlap_by_split(cases, "uniprot_group_id")
    if uniprot_overlap:
        raise CohortContractError(
            f"UniProt group overlap across splits: {sorted(uniprot_overlap)}"
        )


def assess_cohort_readiness(
    payload: Mapping[str, Any], *, minimum_cases: int = 6
) -> dict[str, Any]:
    """Return a bounded readiness report without starting any computation."""

    if not 1 <= minimum_cases <= MAX_COHORT_CASES:
        raise ValueError(f"minimum_cases must be between 1 and {MAX_COHORT_CASES}")
    validate_cohort_manifest(payload)
    cases = _case_list(payload)
    split_counts = {split: sum(case["split"] == split for case in cases) for split in ALLOWED_SPLITS}
    missing_splits = sorted(split for split, count in split_counts.items() if not count)
    if len(cases) < minimum_cases:
        status = "blocked_insufficient_cohort"
    elif missing_splits:
        status = "blocked_split_coverage"
    else:
        status = "ready_for_explicit_user_approval"
    return {
        "schema_version": "biovoid-target-family-cohort-readiness-v1",
        "status": status,
        "family_id": str(payload["family_id"]),
        "case_count": len(cases),
        "minimum_cases": minimum_cases,
        "split_counts": split_counts,
        "missing_splits": missing_splits,
        "sequence_cluster_overlap": _overlap_by_split(cases, "sequence_cluster_id"),
        "uniprot_group_overlap": _overlap_by_split(cases, "uniprot_group_id"),
        "held_out_ready": status == "ready_for_explicit_user_approval",
        "ml_training_started": False,
        "coordinates_downloaded": False,
        "claims_authorized": False,
    }


def build_target_blind_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Remove evaluator metadata and emit a deterministic detector manifest."""

    validate_cohort_manifest(payload)
    cases = _case_list(payload)
    redacted: dict[str, Any] = {
        "schema_version": TARGET_BLIND_MANIFEST_SCHEMA_VERSION,
        "manifest_kind": "target_blind_cohort",
        "materialization_status": "metadata_only",
        "family_id": str(payload["family_id"]),
        "split_strategy": SPLIT_STRATEGY,
        "temporal_cutoff": str(payload["temporal_cutoff"]),
        "constraints": {
            "case_count": len(cases),
            "max_case_count": MAX_COHORT_CASES,
            "analysis_workers": 1,
            "include_motion": False,
            "safe_profile": "safe-16gb",
        },
        "boundary": "apo_structure_only_v1",
        "cases": [
            {
                "case_id": str(case["case_id"]),
                "structure_id": _pdb_id(case["apo_structure_id"], "case.apo_structure_id"),
                "family_id": str(case["family_id"]),
                "split": str(case["split"]),
            }
            for case in cases
        ],
        "manifest_sha256": None,
    }
    redacted["manifest_sha256"] = _stable_hash(
        {key: value for key, value in redacted.items() if key != "manifest_sha256"}
    )
    validate_target_blind_manifest(redacted)
    return redacted


def validate_target_blind_manifest(payload: Mapping[str, Any]) -> None:
    """Validate that the detector-facing cohort contains no evaluator fields."""

    if payload.get("schema_version") != TARGET_BLIND_MANIFEST_SCHEMA_VERSION:
        raise CohortContractError("unsupported target-family detector manifest schema")
    if payload.get("manifest_kind") != "target_blind_cohort":
        raise CohortContractError("unsupported target-family detector manifest kind")
    if payload.get("materialization_status") != "metadata_only":
        raise CohortContractError("detector manifest must remain metadata-only")
    if payload.get("split_strategy") != SPLIT_STRATEGY:
        raise CohortContractError("detector manifest split strategy drifted")
    if payload.get("boundary") != "apo_structure_only_v1":
        raise CohortContractError("detector manifest boundary is not apo-only")
    constraints = payload.get("constraints")
    if not isinstance(constraints, Mapping):
        raise CohortContractError("detector manifest constraints are missing")
    if constraints.get("analysis_workers") != 1 or constraints.get("include_motion") is not False:
        raise CohortContractError("detector manifest violates bounded static boundary")
    cases = payload.get("cases")
    case_count = constraints.get("case_count")
    if (
        not isinstance(cases, list)
        or not isinstance(case_count, int)
        or len(cases) != case_count
        or not 1 <= case_count <= MAX_COHORT_CASES
    ):
        raise CohortContractError("detector manifest case count is invalid")
    case_ids: set[str] = set()
    structure_ids: set[str] = set()
    family_id = _required_text(payload.get("family_id"), "family_id")
    for case in cases:
        if not isinstance(case, Mapping):
            raise CohortContractError("detector manifest case must be an object")
        case_id = _required_text(case.get("case_id"), "case.case_id").casefold()
        structure_id = _pdb_id(case.get("structure_id"), "case.structure_id")
        case_family = _required_text(case.get("family_id"), "case.family_id")
        split = _required_text(case.get("split"), "case.split")
        if case_id in case_ids or structure_id in structure_ids:
            raise CohortContractError("detector manifest IDs must be unique")
        if case_family != family_id:
            raise CohortContractError("detector manifest family drifted")
        if split not in ALLOWED_SPLITS:
            raise CohortContractError(f"unsupported detector manifest split: {split}")
        case_ids.add(case_id)
        structure_ids.add(structure_id)
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True).casefold()
    for forbidden in _FORBIDDEN_TARGET_TOKENS:
        if forbidden in serialized:
            raise CohortContractError(f"detector manifest contains forbidden token: {forbidden}")
    expected_hash = _stable_hash(
        {key: value for key, value in payload.items() if key != "manifest_sha256"}
    )
    if payload.get("manifest_sha256") != expected_hash:
        raise CohortContractError("detector manifest hash mismatch")
