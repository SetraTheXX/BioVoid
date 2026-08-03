"""Target-blind source and evaluator locks for the RI-5 confirmatory holdout."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.cryptobench_adapter import build_target_sites
from src.evaluator_v3 import stable_hash


SOURCE_SCHEMA_VERSION = "biovoid-ri5-confirmatory-source-lock-v1"
EVALUATOR_SCHEMA_VERSION = "biovoid-ri5-confirmatory-evaluator-lock-v1"
LEDGER_SCHEMA_VERSION = "biovoid-ri5-confirmatory-ledger-v1"

_FORBIDDEN_SOURCE_FIELDS = {
    "holo_pdb_id",
    "holo_chain",
    "ligand",
    "ligand_index",
    "ligand_chain",
    "apo_pocket_selection",
    "holo_pocket_selection",
    "target_center",
    "target_residues",
    "hit_label",
}


class ConfirmatoryHoldoutError(RuntimeError):
    """Raised when the confirmatory holdout boundary cannot be proven."""


def _normalize_id(value: object) -> str:
    normalized = str(value).strip().upper()
    if len(normalized) != 4 or not normalized.isalnum():
        raise ConfirmatoryHoldoutError(f"Invalid structure ID: {value!r}")
    return normalized


def _fold_ids(folds: Mapping[str, Any], name: str) -> tuple[str, ...]:
    raw = folds.get(name)
    if not isinstance(raw, list):
        raise ConfirmatoryHoldoutError(f"CryptoBench fold is missing: {name}")
    values = tuple(sorted(_normalize_id(value) for value in raw))
    if len(values) != len(set(values)):
        raise ConfirmatoryHoldoutError(f"CryptoBench fold has duplicate structures: {name}")
    return values


def _selected_chains(records: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    chains: set[str] = set()
    for record in records:
        for chain in str(record.get("apo_chain", "")).split("-"):
            normalized = chain.strip()
            if normalized:
                chains.add(normalized)
    if not chains:
        raise ConfirmatoryHoldoutError("Confirmatory source has no declared apo chain")
    return tuple(sorted(chains))


def _families(dataset: Mapping[str, Sequence[Mapping[str, Any]]], ids: Sequence[str]) -> set[str]:
    if not ids:
        return set()
    sites = build_target_sites(
        {structure_id.casefold(): dataset[structure_id.casefold()] for structure_id in ids},
        dataset_id="cryptobench",
        split="validation",
    )
    return {site.family_id for site in sites}


def build_confirmatory_locks(
    dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    folds: Mapping[str, Any],
    *,
    snapshot_id: str,
    evaluator_v3_lock_sha256: str,
    expected_structure_count: int = 222,
    expected_case_count: int = 265,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_dataset = {
        _normalize_id(structure_id).casefold(): records for structure_id, records in dataset.items()
    }
    holdout_ids = _fold_ids(folds, "train-3")
    if len(holdout_ids) != expected_structure_count:
        raise ConfirmatoryHoldoutError(
            f"Expected {expected_structure_count} confirmatory structures, found {len(holdout_ids)}"
        )
    missing = sorted(
        structure_id
        for structure_id in holdout_ids
        if structure_id.casefold() not in normalized_dataset
    )
    if missing:
        raise ConfirmatoryHoldoutError("Confirmatory metadata is missing: " + ", ".join(missing))

    comparison_ids = tuple(
        structure_id
        for fold in ("train-0", "train-1", "train-2", "test")
        for structure_id in _fold_ids(folds, fold)
    )
    structure_overlap = sorted(set(holdout_ids) & set(comparison_ids))
    if structure_overlap:
        raise ConfirmatoryHoldoutError(
            "Confirmatory structure overlap: " + ", ".join(structure_overlap)
        )
    holdout_families = _families(normalized_dataset, holdout_ids)
    comparison_families = _families(normalized_dataset, comparison_ids)
    family_overlap = sorted(holdout_families & comparison_families)
    if family_overlap:
        raise ConfirmatoryHoldoutError("Confirmatory family overlap: " + ", ".join(family_overlap))

    scoped = {
        structure_id.casefold(): normalized_dataset[structure_id.casefold()]
        for structure_id in holdout_ids
    }
    sites = build_target_sites(scoped, dataset_id="cryptobench", split="validation")
    if len(sites) != expected_case_count:
        raise ConfirmatoryHoldoutError(
            f"Expected {expected_case_count} confirmatory cases, found {len(sites)}"
        )
    sites_by_structure: dict[str, list[Any]] = {}
    for site in sites:
        sites_by_structure.setdefault(site.apo_pdb_id, []).append(site)

    structures: list[dict[str, Any]] = []
    for structure_id in holdout_ids:
        structure_sites = sites_by_structure[structure_id]
        family_ids = sorted({site.family_id for site in structure_sites})
        if len(family_ids) != 1:
            raise ConfirmatoryHoldoutError(
                f"Confirmatory structure has inconsistent family identity: {structure_id}"
            )
        structures.append(
            {
                "structure_id": structure_id,
                "family_id": family_ids[0],
                "selected_chains": list(_selected_chains(scoped[structure_id.casefold()])),
                "case_count": len(structure_sites),
            }
        )

    source: dict[str, Any] = {
        "schema_version": SOURCE_SCHEMA_VERSION,
        "status": "frozen_before_detector_execution",
        "dataset_id": "cryptobench",
        "snapshot_id": snapshot_id,
        "source_fold": "train-3",
        "benchmark_role": "local_confirmatory_holdout",
        "structure_count": len(structures),
        "case_count": len(sites),
        "structures": structures,
        "detector_boundary": {
            "target_blind": True,
            "evaluator_fields_present": False,
            "holo_coordinates_present": False,
        },
        "family_audit": {
            "holdout_family_count": len(holdout_families),
            "comparison_family_count": len(comparison_families),
            "overlap": [],
        },
        "evaluator_v3_lock_sha256": evaluator_v3_lock_sha256,
    }
    source["source_lock_sha256"] = stable_hash(source)

    evaluator_cases = [asdict(site) for site in sorted(sites, key=lambda item: item.case_id)]
    evaluator: dict[str, Any] = {
        "schema_version": EVALUATOR_SCHEMA_VERSION,
        "status": "frozen_evaluator_only_before_detector_execution",
        "dataset_id": "cryptobench",
        "snapshot_id": snapshot_id,
        "source_fold": "train-3",
        "structure_count": len(structures),
        "case_count": len(evaluator_cases),
        "cases": evaluator_cases,
        "source_lock_sha256": source["source_lock_sha256"],
        "evaluator_v3_lock_sha256": evaluator_v3_lock_sha256,
        "detector_may_read_this_file": False,
    }
    evaluator["evaluator_lock_sha256"] = stable_hash(evaluator)
    validate_detector_source_lock(
        source,
        expected_structure_count=expected_structure_count,
        expected_case_count=expected_case_count,
    )
    return source, evaluator


def validate_detector_source_lock(
    payload: Mapping[str, Any],
    *,
    expected_structure_count: int = 222,
    expected_case_count: int = 265,
) -> None:
    if payload.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise ConfirmatoryHoldoutError("Unexpected confirmatory source-lock schema")
    if payload.get("status") != "frozen_before_detector_execution":
        raise ConfirmatoryHoldoutError("Confirmatory source lock is not frozen")
    if payload.get("structure_count") != expected_structure_count:
        raise ConfirmatoryHoldoutError("Confirmatory source structure count drifted")
    if payload.get("case_count") != expected_case_count:
        raise ConfirmatoryHoldoutError("Confirmatory source case count drifted")
    boundary = payload.get("detector_boundary", {})
    if (
        boundary.get("target_blind") is not True
        or boundary.get("evaluator_fields_present") is not False
    ):
        raise ConfirmatoryHoldoutError("Confirmatory detector boundary is not target-blind")
    encoded = json.dumps(payload, ensure_ascii=True).lower()
    leaked = sorted(key for key in _FORBIDDEN_SOURCE_FIELDS if f'"{key}"' in encoded)
    if leaked:
        raise ConfirmatoryHoldoutError(
            "Evaluator fields leaked into source lock: " + ", ".join(leaked)
        )
    expected_hash = stable_hash(
        {key: value for key, value in payload.items() if key != "source_lock_sha256"}
    )
    if payload.get("source_lock_sha256") != expected_hash:
        raise ConfirmatoryHoldoutError("Confirmatory source-lock hash mismatch")


def authorize_confirmatory_holdout(
    path: Path,
    *,
    source_lock_sha256: str,
    evaluator_lock_sha256: str,
    evaluator_v3_lock_sha256: str,
    protocol_sha256: str,
    explicit_user_authorization: bool,
) -> dict[str, Any]:
    if not explicit_user_authorization:
        raise ConfirmatoryHoldoutError("Explicit user authorization is required")
    if path.exists():
        raise ConfirmatoryHoldoutError("Confirmatory holdout has already been opened")
    for name, value in {
        "source_lock_sha256": source_lock_sha256,
        "evaluator_lock_sha256": evaluator_lock_sha256,
        "evaluator_v3_lock_sha256": evaluator_v3_lock_sha256,
        "protocol_sha256": protocol_sha256,
    }.items():
        if len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value.lower()
        ):
            raise ConfirmatoryHoldoutError(f"Invalid {name}")
    payload: dict[str, Any] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "opened": True,
        "opened_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_lock_sha256": source_lock_sha256,
        "evaluator_lock_sha256": evaluator_lock_sha256,
        "evaluator_v3_lock_sha256": evaluator_v3_lock_sha256,
        "protocol_sha256": protocol_sha256,
        "purpose": "single_local_confirmatory_holdout_execution",
        "external_replication": False,
    }
    payload["ledger_sha256"] = stable_hash(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return payload
