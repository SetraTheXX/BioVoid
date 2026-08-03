"""Content-addressed, target-blind CryptoBench manifest helpers.

RI-2 records source metadata and case identity without materializing structures
or exposing evaluator-only labels to a detector-facing manifest.  The module
is deliberately independent of network and filesystem code so its contract can
be tested offline.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from typing import Any, Mapping, Sequence

from .benchmark_v1 import BenchmarkContractError
from .cryptobench_adapter import (
    CryptoBenchTargetSite,
    build_target_sites,
    family_component_ids,
    family_group_id,
)


RI2_MANIFEST_SCHEMA_VERSION = "biovoid-ri2-development-manifest-v1"
RI2_MANIFEST_KIND = "metadata_only_target_blind_inventory"
RI2_SPLITS = ("development", "validation")
SEALED_SPLIT = "sealed"
FORBIDDEN_MANIFEST_KEY_TOKENS = (
    "evaluator",
    "holo",
    "ligand",
    "target",
    "hit_label",
)


def canonical_json_bytes(payload: Any) -> bytes:
    """Serialize JSON deterministically for content hashes."""

    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def stable_sha256(payload: Any) -> str:
    """Return the SHA-256 of a canonical JSON payload."""

    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _content_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Remove volatile envelope fields from the reproducibility hash."""

    return {
        key: value
        for key, value in payload.items()
        if key not in {"manifest_sha256", "generated_at_utc", "api_retrieved_utc"}
    }


def manifest_content_sha256(payload: Mapping[str, Any]) -> str:
    return stable_sha256(_content_payload(payload))


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkContractError(f"{field_name} must be a non-empty string")
    return value.strip()


def _required_sha256_or_null(value: Any, field_name: str) -> None:
    if value is None:
        return
    text = _required_text(value, field_name)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise BenchmarkContractError(f"{field_name} must be lowercase SHA-256 or null")


def _forbidden_key_paths(value: Any, path: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).casefold()
            child_path = f"{path}.{key}"
            if any(token in key_text for token in FORBIDDEN_MANIFEST_KEY_TOKENS):
                paths.append(child_path)
            paths.extend(_forbidden_key_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_forbidden_key_paths(child, f"{path}[{index}]"))
    return paths


def _split_structure_ids(
    folds: Mapping[str, Sequence[str]],
    fold_names: Sequence[str],
) -> tuple[str, ...]:
    structure_ids: list[str] = []
    for fold_name in fold_names:
        values = folds.get(fold_name)
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise BenchmarkContractError(f"Fold '{fold_name}' must be a list")
        structure_ids.extend(str(value).strip().lower() for value in values)
    if any(not structure_id for structure_id in structure_ids):
        raise BenchmarkContractError("Fold structure IDs must be non-empty")
    if len(set(structure_ids)) != len(structure_ids):
        raise BenchmarkContractError("A structure appears more than once in a split")
    return tuple(structure_ids)


def _opaque_case_id(site: CryptoBenchTargetSite) -> str:
    payload = {
        "dataset_id": site.dataset_id,
        "split": site.split,
        "apo_pdb_id": site.apo_pdb_id,
        "family_id": site.family_id,
        "source_case_id": site.case_id,
    }
    return f"{site.dataset_id}:{site.apo_pdb_id}:{stable_sha256(payload)[:16]}"


def _source_record(
    site: CryptoBenchTargetSite,
    *,
    archive_record: Mapping[str, Any] | None,
) -> dict[str, Any]:
    archive_path = archive_record.get("path") if archive_record else None
    archive_sha256 = archive_record.get("sha256") if archive_record else None
    archive_locator = (
        f"{archive_path}::member:{site.apo_pdb_id.lower()}.cif" if archive_path else None
    )
    return {
        "case_id": _opaque_case_id(site),
        "structure_id": site.apo_pdb_id,
        "family_id": site.family_id,
        "split": site.split,
        "dataset_snapshot_id": "",
        "source": {
            "apo_accession": site.apo_pdb_id,
            "apo_source_locator": archive_locator,
            "apo_archive_sha256": archive_sha256,
            "apo_file_sha256": None,
            "source_case_reference": f"dataset.json#/{site.apo_pdb_id}",
        },
        "preparation": {
            "config_sha256": None,
            "prepared_structure_sha256": None,
            "coordinate_frame_sha256": None,
        },
        "eligibility": {
            "status": "planned",
            "reason": "raw_structure_not_materialized;_preflight_deferred_to_RI-3",
        },
    }


def _build_sites_for_structure(
    structure_id: str,
    records: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    split: str,
) -> tuple[tuple[CryptoBenchTargetSite, ...], bool, tuple[str, ...]]:
    raw_family_ids = [str(record.get("uniprot_id", "")).strip() for record in records]
    try:
        component_ids = family_component_ids(raw_family_ids)
        structure_family_id = family_group_id(raw_family_ids)
    except BenchmarkContractError as exc:
        raise BenchmarkContractError(
            f"CryptoBench structure '{structure_id}' has no valid family identifier"
        ) from exc
    sites = build_target_sites(
        {structure_id: records},
        dataset_id=dataset_id,
        split=split,  # type: ignore[arg-type]
    )
    if any(site.family_id != structure_family_id for site in sites):
        raise BenchmarkContractError(
            f"CryptoBench structure '{structure_id}' has inconsistent family normalization"
        )
    return (
        tuple(sorted(sites, key=lambda site: site.case_id)),
        len(component_ids) > 1,
        (structure_family_id,),
    )


def _archive_record(source_inventory: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    candidates = [
        record
        for record in source_inventory
        if str(record.get("path", "")).casefold().endswith("/cif-files.zip")
    ]
    if len(candidates) > 1:
        raise BenchmarkContractError("More than one CryptoBench cif archive was found")
    return candidates[0] if candidates else None


def build_manifest_payload(
    *,
    lock_payload: Mapping[str, Any],
    dataset: Mapping[str, Sequence[Mapping[str, Any]]],
    folds: Mapping[str, Sequence[str]],
    source_inventory: Sequence[Mapping[str, Any]],
    api_root: str,
    api_retrieved_utc: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    dataset_lock = lock_payload["dataset"]
    snapshot_id = _required_text(dataset_lock["snapshot_id"], "dataset.snapshot_id")
    allocation = dataset_lock["split_allocation"]
    archive_record = _archive_record(source_inventory)
    cases: list[dict[str, Any]] = []
    split_summaries: dict[str, dict[str, Any]] = {}
    structure_issues: list[dict[str, Any]] = []
    all_split_structure_ids: dict[str, tuple[str, ...]] = {}
    all_split_families: dict[str, set[str]] = {}

    for split in (*RI2_SPLITS, SEALED_SPLIT):
        fold_names = tuple(str(value) for value in allocation[split])
        structure_ids = _split_structure_ids(folds, fold_names)
        all_split_structure_ids[split] = structure_ids
        split_families: set[str] = set()
        split_cases: list[dict[str, Any]] = []
        split_multi_component: list[str] = []
        for structure_id in structure_ids:
            records = dataset.get(structure_id)
            if records is None:
                structure_issues.append(
                    {
                        "split": split,
                        "structure_id": structure_id.upper(),
                        "reason": "structure_missing_from_dataset_metadata",
                    }
                )
                continue
            if split == SEALED_SPLIT:
                raw_family_ids = [str(record.get("uniprot_id", "")).strip() for record in records]
                try:
                    component_ids = family_component_ids(raw_family_ids)
                    structure_family_id = family_group_id(raw_family_ids)
                except BenchmarkContractError:
                    structure_issues.append(
                        {
                            "split": split,
                            "structure_id": structure_id.upper(),
                            "reason": "sealed_structure_has_no_family_identifier",
                        }
                    )
                    continue
                split_families.add(structure_family_id)
                if len(component_ids) > 1:
                    split_multi_component.append(structure_id.upper())
                continue
            try:
                sites, multi_component, family_ids = _build_sites_for_structure(
                    structure_id,
                    records,
                    dataset_id=str(dataset_lock["dataset_id"]),
                    split=split,
                )
            except BenchmarkContractError as exc:
                structure_issues.append(
                    {
                        "split": split,
                        "structure_id": structure_id.upper(),
                        "reason": "target_site_normalization_failed",
                        "detail": str(exc),
                    }
                )
                continue
            split_families.update(family_ids)
            if multi_component:
                split_multi_component.append(structure_id.upper())
            if split in RI2_SPLITS:
                for site in sites:
                    record = _source_record(
                        site,
                        archive_record=archive_record,
                    )
                    record["dataset_snapshot_id"] = snapshot_id
                    split_cases.append(record)
        all_split_families[split] = split_families
        if split in RI2_SPLITS:
            cases.extend(split_cases)
        split_summaries[split] = {
            "folds": list(fold_names),
            "case_records_materialized": split in RI2_SPLITS,
            "structure_count": len(structure_ids),
            "case_count": len(split_cases) if split in RI2_SPLITS else None,
            "structure_ids_sha256": stable_sha256(sorted(structure_ids)),
            "family_ids_sha256": stable_sha256(sorted(split_families)),
            "multi_component_structures": sorted(split_multi_component),
        }

    family_split_map: dict[str, set[str]] = defaultdict(set)
    structure_split_map: dict[str, set[str]] = defaultdict(set)
    for split, structure_ids in all_split_structure_ids.items():
        for structure_id in structure_ids:
            structure_split_map[structure_id].add(split)
        for family_id in all_split_families[split]:
            family_split_map[family_id].add(split)
    cross_split_families = {
        family_id: sorted(splits)
        for family_id, splits in family_split_map.items()
        if len(splits) > 1
    }
    cross_split_structures = {
        structure_id: sorted(splits)
        for structure_id, splits in structure_split_map.items()
        if len(splits) > 1
    }
    case_ids = [record["case_id"] for record in cases]
    if len(case_ids) != len(set(case_ids)):
        raise BenchmarkContractError("RI-2 manifest has duplicate case IDs")
    source_inventory_clean = [dict(record) for record in source_inventory]
    source_inventory_clean.sort(key=lambda record: str(record.get("path", "")))
    payload: dict[str, Any] = {
        "schema_version": RI2_MANIFEST_SCHEMA_VERSION,
        "manifest_kind": RI2_MANIFEST_KIND,
        "materialization_status": "metadata_only",
        "snapshot": {
            "dataset_id": dataset_lock["dataset_id"],
            "snapshot_id": snapshot_id,
            "osf_node_id": dataset_lock["osf_node_id"],
            "osf_storage_path": dataset_lock["osf_storage_path"],
            "source_repository": dataset_lock["source_repository"],
            "source_repository_commit": dataset_lock["source_repository_commit"],
            "locked_metadata_files": dataset_lock["metadata_files"],
        },
        "api_root": api_root,
        "api_retrieved_utc": api_retrieved_utc,
        "generated_at_utc": generated_at_utc,
        "source_inventory": {
            "file_count": len(source_inventory_clean),
            "total_bytes": sum(int(record.get("size") or 0) for record in source_inventory_clean),
            "inventory_sha256": stable_sha256(source_inventory_clean),
            "files": source_inventory_clean,
        },
        "split_summaries": split_summaries,
        "integrity": {
            "cross_split_family_ids": cross_split_families,
            "cross_split_structure_ids": cross_split_structures,
            "structure_issues": structure_issues,
            "no_silent_case_drop": True,
            "sealed_case_records_closed": True,
            "raw_structure_members_materialized": False,
            "detector_boundary_clean": True,
        },
        "coverage": {
            "case_records_materialized": len(cases),
            "planned_case_count": sum(
                record["eligibility"]["status"] == "planned" for record in cases
            ),
            "ineligible_case_count": sum(
                record["eligibility"]["status"] == "ineligible" for record in cases
            ),
            "prepared_structure_count": 0,
            "prepared_structure_hashes_available": False,
            "preflight_status": "deferred_to_RI-3",
        },
        "cases": cases,
        "manifest_sha256": None,
    }
    payload["manifest_sha256"] = manifest_content_sha256(payload)
    validate_manifest_payload(payload)
    return payload


def validate_manifest_payload(payload: Mapping[str, Any]) -> None:
    """Validate RI-2 invariants and the target-blind boundary."""

    if payload.get("schema_version") != RI2_MANIFEST_SCHEMA_VERSION:
        raise BenchmarkContractError("Unsupported RI-2 manifest schema")
    if payload.get("manifest_kind") != RI2_MANIFEST_KIND:
        raise BenchmarkContractError("Unsupported RI-2 manifest kind")
    if payload.get("materialization_status") != "metadata_only":
        raise BenchmarkContractError("RI-2 manifest must remain metadata-only")
    forbidden_paths = _forbidden_key_paths(payload)
    if forbidden_paths:
        raise BenchmarkContractError(
            "Evaluator or target fields are forbidden in RI-2 manifest: "
            + ", ".join(forbidden_paths[:5])
        )
    expected_hash = manifest_content_sha256(payload)
    if payload.get("manifest_sha256") != expected_hash:
        raise BenchmarkContractError("RI-2 manifest content hash does not match payload")
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, Mapping):
        raise BenchmarkContractError("RI-2 manifest is missing snapshot metadata")
    snapshot_id = _required_text(snapshot.get("snapshot_id"), "snapshot.snapshot_id")
    inventory = payload.get("source_inventory")
    if not isinstance(inventory, Mapping) or not isinstance(inventory.get("files"), list):
        raise BenchmarkContractError("Source inventory must contain a files list")
    files = inventory["files"]
    if inventory.get("inventory_sha256") != stable_sha256(files):
        raise BenchmarkContractError("Source inventory hash does not match files")
    if inventory.get("file_count") != len(files):
        raise BenchmarkContractError("Source inventory file count does not match files")
    if inventory.get("total_bytes") != sum(int(record.get("size") or 0) for record in files):
        raise BenchmarkContractError("Source inventory byte count does not match files")
    inventory_paths: set[str] = set()
    for index, record in enumerate(files):
        if not isinstance(record, Mapping):
            raise BenchmarkContractError(f"Source inventory record {index} is not an object")
        path = _required_text(record.get("path"), f"source_inventory.files[{index}].path")
        if path in inventory_paths:
            raise BenchmarkContractError(f"Duplicate source inventory path: {path}")
        inventory_paths.add(path)
        _required_sha256_or_null(record.get("sha256"), f"source_inventory.files[{index}].sha256")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise BenchmarkContractError("RI-2 manifest must contain development/validation cases")
    case_ids: set[str] = set()
    family_splits: dict[str, str] = {}
    structure_contracts: dict[str, tuple[str, str]] = {}
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise BenchmarkContractError(f"Case {index} is not an object")
        for field_name in ("case_id", "structure_id", "family_id", "split", "dataset_snapshot_id"):
            _required_text(case.get(field_name), f"cases[{index}].{field_name}")
        split = case["split"]
        if split not in RI2_SPLITS:
            raise BenchmarkContractError("RI-2 case records may only be development or validation")
        eligibility = case.get("eligibility")
        if not isinstance(eligibility, Mapping) or eligibility.get("status") not in {
            "planned",
            "ineligible",
        }:
            raise BenchmarkContractError(f"Case {index} has an invalid RI-2 eligibility status")
        case_key = case["case_id"].casefold()
        if case_key in case_ids:
            raise BenchmarkContractError(f"Duplicate RI-2 case ID: {case['case_id']}")
        case_ids.add(case_key)
        family_key = case["family_id"].casefold()
        previous_split = family_splits.setdefault(family_key, split)
        if previous_split != split:
            raise BenchmarkContractError(f"Family crosses RI-2 splits: {case['family_id']}")
        structure_key = case["structure_id"].upper()
        structure_contract = (case["family_id"].casefold(), split)
        previous_structure = structure_contracts.setdefault(structure_key, structure_contract)
        if previous_structure != structure_contract and eligibility["status"] != "ineligible":
            raise BenchmarkContractError(
                f"Structure has inconsistent family/split without explicit ineligibility: {structure_key}"
            )
        source = case.get("source")
        preparation = case.get("preparation")
        if not isinstance(source, Mapping) or not isinstance(preparation, Mapping):
            raise BenchmarkContractError(f"Case {index} is missing source/preparation objects")
        if case["dataset_snapshot_id"] != snapshot_id:
            raise BenchmarkContractError(f"Case {index} has a different snapshot ID")
        if source.get("apo_accession") != case["structure_id"]:
            raise BenchmarkContractError(
                f"Case {index} source accession does not match structure ID"
            )
        _required_sha256_or_null(source.get("apo_archive_sha256"), "apo_archive_sha256")
        _required_sha256_or_null(source.get("apo_file_sha256"), "apo_file_sha256")
        for field_name in ("config_sha256", "prepared_structure_sha256", "coordinate_frame_sha256"):
            _required_sha256_or_null(preparation.get(field_name), field_name)
        if any(preparation.get(field_name) is not None for field_name in preparation):
            raise BenchmarkContractError("Metadata-only RI-2 cases cannot have preparation hashes")
    integrity = payload.get("integrity")
    if not isinstance(integrity, Mapping):
        raise BenchmarkContractError("RI-2 manifest is missing integrity metadata")
    if integrity.get("cross_split_family_ids") or integrity.get("cross_split_structure_ids"):
        raise BenchmarkContractError("RI-2 split leakage check failed")
    if integrity.get("detector_boundary_clean") is not True:
        raise BenchmarkContractError("RI-2 target-blind boundary is not explicitly true")
    if integrity.get("sealed_case_records_closed") is not True:
        raise BenchmarkContractError("RI-2 sealed case records must remain closed")
    split_summaries = payload.get("split_summaries")
    if not isinstance(split_summaries, Mapping):
        raise BenchmarkContractError("RI-2 manifest is missing split summaries")
    sealed_summary = split_summaries.get(SEALED_SPLIT)
    if (
        not isinstance(sealed_summary, Mapping)
        or sealed_summary.get("case_records_materialized") is not False
    ):
        raise BenchmarkContractError("RI-2 sealed case rows must remain closed")
    coverage = payload.get("coverage")
    if not isinstance(coverage, Mapping):
        raise BenchmarkContractError("RI-2 manifest is missing coverage metadata")
    planned_count = sum(case["eligibility"]["status"] == "planned" for case in cases)
    ineligible_count = sum(case["eligibility"]["status"] == "ineligible" for case in cases)
    if coverage.get("case_records_materialized") != len(cases):
        raise BenchmarkContractError("RI-2 coverage case count does not match cases")
    if coverage.get("planned_case_count") != planned_count:
        raise BenchmarkContractError("RI-2 planned count does not match cases")
    if coverage.get("ineligible_case_count") != ineligible_count:
        raise BenchmarkContractError("RI-2 ineligible count does not match cases")
