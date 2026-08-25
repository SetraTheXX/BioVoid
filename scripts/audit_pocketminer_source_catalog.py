"""Build a metadata-only PocketMiner source/catalog feasibility report.

PocketMiner is treated here as a curated experimental apo--holo source, not
as a source of BioVoid-generated labels and not as permission to run the
PocketMiner model.  The command reads only its supplementary metadata table,
optionally retrieves bounded RCSB entry/polymer metadata, and pre-seals a
sequence-cluster/date-window allocation before any detector result exists.
Coordinates, model inference, evaluator labels, NMA, external baselines, and
ML are outside this command's boundary.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_target_family_manifest import (  # noqa: E402
    DATA_URL,
    TargetFamilyMetadataError,
    _api_json,
    _metadata_session,
    _sequence_from_entity,
    _uniprot_ids,
)
from scripts.materialize_target_family_sequence_clusters import (  # noqa: E402
    cluster_sequence_records,
)
from src.resources import SAFE_16GB  # noqa: E402


SOURCE_CATALOG_SCHEMA_VERSION = "biovoid-ranking-source-catalog-v1"
DEFAULT_CATALOG_ID = "pocketminer-cryptic-apo-holo-v1"
DEFAULT_XLSX = (
    REPO_ROOT / "local-private/research/ranking-study-source-catalog/pocketminer-v1/"
    "supplementary-tables.xlsx"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "local-private/research/ranking-study-source-catalog/pocketminer-v1/"
    "pocketminer-source-catalog-v1.json"
)
DEFAULT_MARKDOWN = (
    REPO_ROOT / "local-private/research/ranking-study-source-catalog/pocketminer-v1/"
    "pocketminer-source-catalog-v1.md"
)
DEFAULT_VALIDATION_CUTOFF = "2014-01-01"
DEFAULT_TEMPORAL_CUTOFF = "2018-01-01"
TARGET_COUNTS = {"development": 6, "validation": 2, "temporal": 2}
SOURCE_DATASET_ID = "pocketminer-novel-cryptic-pocket-set-v1"
SOURCE_DATASET_URL = "https://github.com/Mickdub/gvp/tree/pocket_pred/data/pm-dataset"
SOURCE_LICENSE = "MIT"
SOURCE_LICENSE_URL = "https://raw.githubusercontent.com/Mickdub/gvp/pocket_pred/LICENSE"
SOURCE_XLSX_URL = (
    "https://raw.githubusercontent.com/Mickdub/gvp/pocket_pred/"
    "data/pm-dataset/supplementary-tables.xlsx"
)
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PDB_ID_RE = re.compile(r"^[A-Z0-9]{4}$")
_CELL_REF_RE = re.compile(r"^([A-Z]+)\d+$")
_ALLOWED_LABEL_CLASS = "curated_experimental_apo_holo"
_RESOURCE_SAFE = "likely_within_static_atom_cap"


class PocketMinerCatalogError(ValueError):
    """Raised when a source/catalog input violates the metadata-only contract."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _text(value: Any, field: str, *, required: bool = True) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise PocketMinerCatalogError(f"{field} must be non-empty")
    return result


def _pdb_id(value: Any, field: str) -> str:
    result = _text(value, field).upper()
    if _PDB_ID_RE.fullmatch(result) is None:
        raise PocketMinerCatalogError(f"{field} must be a four-character PDB ID")
    return result


def _parse_date(value: Any, field: str) -> date | None:
    if value is None or value == "":
        return None
    result = _text(value, field)
    try:
        return datetime.fromisoformat(result.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise PocketMinerCatalogError(f"{field} must be an ISO/RFC3339 date") from exc


def _column_from_ref(reference: str) -> str:
    match = _CELL_REF_RE.match(reference)
    if match is None:
        raise PocketMinerCatalogError(f"invalid spreadsheet cell reference: {reference}")
    return match.group(1)


def _shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(item.text or "" for item in si.iter("{%s}t" % _NS["m"])) for si in root]


def _workbook_sheet_targets(archive: ZipFile) -> dict[str, str]:
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except KeyError as exc:
        raise PocketMinerCatalogError("xlsx workbook metadata is incomplete") from exc
    relation_targets = {
        relation.attrib["Id"]: relation.attrib["Target"]
        for relation in relationships
        if relation.attrib.get("Id") and relation.attrib.get("Target")
    }
    targets: dict[str, str] = {}
    sheets = workbook.find("m:sheets", _NS)
    if sheets is None:
        raise PocketMinerCatalogError("xlsx workbook contains no sheets")
    for sheet in sheets:
        name = sheet.attrib.get("name", "")
        relation_id = sheet.attrib.get("{%s}id" % _REL_NS)
        target = relation_targets.get(relation_id or "")
        if not name or not target:
            continue
        normalized = target.lstrip("/")
        if not normalized.startswith("xl/"):
            normalized = "xl/" + normalized
        targets[name] = normalized
    return targets


def _cell_value(cell: ET.Element, shared: Sequence[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(item.text or "" for item in cell.iter("{%s}t" % _NS["m"]))
    value = cell.find("m:v", _NS)
    if value is None:
        return ""
    text = value.text or ""
    if cell_type == "s":
        try:
            return shared[int(text)]
        except (IndexError, ValueError) as exc:
            raise PocketMinerCatalogError("xlsx shared string index is invalid") from exc
    return text


def _sheet_rows(archive: ZipFile, sheet_name: str) -> list[tuple[int, dict[str, str]]]:
    targets = _workbook_sheet_targets(archive)
    target = targets.get(sheet_name)
    if target is None:
        raise PocketMinerCatalogError(f"xlsx sheet is missing: {sheet_name}")
    try:
        root = ET.fromstring(archive.read(target))
    except KeyError as exc:
        raise PocketMinerCatalogError(f"xlsx sheet XML is missing: {sheet_name}") from exc
    shared = _shared_strings(archive)
    rows: list[tuple[int, dict[str, str]]] = []
    sheet_data = root.find("m:sheetData", _NS)
    if sheet_data is None:
        return rows
    for row in sheet_data.findall("m:row", _NS):
        try:
            row_number = int(row.attrib.get("r", "0"))
        except ValueError as exc:
            raise PocketMinerCatalogError("xlsx row number is invalid") from exc
        values: dict[str, str] = {}
        for cell in row.findall("m:c", _NS):
            reference = cell.attrib.get("r", "")
            if reference:
                values[_column_from_ref(reference)] = _cell_value(cell, shared)
        rows.append((row_number, values))
    return rows


def parse_pocketminer_rows(xlsx_path: Path = DEFAULT_XLSX) -> list[dict[str, Any]]:
    """Extract only the 38 curated novel cryptic-pocket metadata rows."""

    try:
        with ZipFile(xlsx_path) as archive:
            rows = _sheet_rows(archive, "validation_and_test_sets")
    except (OSError, BadZipFile, ET.ParseError) as exc:
        raise PocketMinerCatalogError(f"unable to parse PocketMiner xlsx: {xlsx_path}") from exc

    header_row = None
    for row_number, values in rows:
        if values.get("C") == "PDB ID" and values.get("G") == "PDB ID":
            header_row = row_number
            break
    if header_row is None:
        raise PocketMinerCatalogError("PocketMiner validation/test sheet header is missing")

    current_section = ""
    parsed: list[dict[str, Any]] = []
    for row_number, values in rows:
        section = values.get("B", "").strip()
        if section:
            current_section = section
        if row_number <= header_row:
            continue
        if not current_section.casefold().startswith("novel cryptic pocket set"):
            continue
        apo = values.get("C", "").strip().upper()
        holo = values.get("G", "").strip().upper()
        if _PDB_ID_RE.fullmatch(apo) is None or _PDB_ID_RE.fullmatch(holo) is None:
            continue
        source_set = values.get("V", "").strip().casefold()
        if source_set not in {"validation", "test"}:
            raise PocketMinerCatalogError(f"unexpected PocketMiner source split: {source_set}")
        parsed.append(
            {
                "row_number": row_number,
                "apo_pdb_id": apo,
                "apo_chain_id": _text(values.get("E"), "apo_chain_id"),
                "holo_pdb_id": holo,
                "holo_chain_id": _text(values.get("H"), "holo_chain_id"),
                "ligand_code": _text(values.get("I"), "ligand_code"),
                "cryptic_lining_residue_count": values.get("K", "").strip() or None,
                "structure_source": _text(values.get("U"), "structure_source"),
                "source_set": source_set,
                "notes": values.get("W", "").strip() or None,
                "label_provenance_class": _ALLOWED_LABEL_CLASS,
                "pocket_count": 2 if "two cryptic pockets" in values.get("W", "").casefold() else 1,
            }
        )
    if not parsed:
        raise PocketMinerCatalogError("PocketMiner novel cryptic section has no rows")
    keys = {
        (row["apo_pdb_id"], row["apo_chain_id"], row["holo_pdb_id"], row["holo_chain_id"])
        for row in parsed
    }
    if len(keys) != len(parsed):
        raise PocketMinerCatalogError("PocketMiner source contains duplicate apo/holo rows")
    return sorted(parsed, key=lambda row: int(row["row_number"]))


def _metadata_field(metadata: Mapping[str, Any], key: str, field: str) -> Any:
    if key not in metadata:
        raise PocketMinerCatalogError(f"metadata for {field} is incomplete")
    return metadata[key]


def _metadata_uniprot_ids(metadata: Mapping[str, Any]) -> set[str]:
    raw = metadata.get("uniprot_ids", [])
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return set()
    return {str(value).strip().upper() for value in raw if str(value).strip()}


def _lookup_metadata(
    metadata_by_pdb: Mapping[str, Mapping[str, Any]], pdb_id: str, chain_id: str
) -> Mapping[str, Any] | None:
    """Prefer chain-specific metadata for entries containing multiple chains."""

    exact = metadata_by_pdb.get(f"{pdb_id}:{chain_id.upper()}")
    if isinstance(exact, Mapping):
        return exact
    fallback = metadata_by_pdb.get(pdb_id)
    return fallback if isinstance(fallback, Mapping) else None


def _resource_status(metadata: Mapping[str, Any]) -> str:
    proxy = metadata.get("resource_proxy")
    if not isinstance(proxy, Mapping):
        return "review_required"
    status = str(proxy.get("status") or "review_required")
    return (
        status
        if status
        in {
            "likely_within_static_atom_cap",
            "likely_above_static_atom_cap",
            "review_required",
        }
        else "review_required"
    )


def _metadata_snapshot_hash(metadata_by_pdb: Mapping[str, Mapping[str, Any]]) -> str:
    """Hash metadata fields without persisting raw sequences in the report."""

    sanitized: dict[str, dict[str, Any]] = {}
    for key in sorted(metadata_by_pdb):
        value = metadata_by_pdb[key]
        sanitized[key] = {
            field: value.get(field)
            for field in (
                "pdb_id",
                "chain_id",
                "polymer_entity_id",
                "uniprot_ids",
                "sequence_length",
                "release_date",
                "resource_proxy",
            )
            if field in value
        }
        sequence = value.get("sequence")
        if isinstance(sequence, str):
            sanitized[key]["sequence_sha256"] = hashlib.sha256(sequence.encode("ascii")).hexdigest()
    return _stable_hash(sanitized)


def _case_id(catalog_id: str, row: Mapping[str, Any], cluster_id: str | None) -> str:
    digest = _stable_hash(
        {
            "catalog_id": catalog_id,
            "apo_pdb_id": row["apo_pdb_id"],
            "holo_pdb_id": row["holo_pdb_id"],
            "apo_chain_id": row["apo_chain_id"],
            "holo_chain_id": row["holo_chain_id"],
            "sequence_cluster_id": cluster_id,
        }
    )[:16]
    return f"{catalog_id}:{row['apo_pdb_id']}:{digest}"


def _allocation(
    rows: Sequence[Mapping[str, Any]],
    *,
    catalog_id: str,
    validation_cutoff: date,
    temporal_cutoff: date,
) -> dict[str, Any]:
    if validation_cutoff >= temporal_cutoff:
        raise PocketMinerCatalogError("validation cutoff must precede temporal cutoff")
    buckets: dict[str, list[Mapping[str, Any]]] = {
        "development": [],
        "validation": [],
        "temporal": [],
        "review": [],
    }
    for row in rows:
        release = _parse_date(row.get("apo_release_date"), "apo_release_date")
        if release is None:
            buckets["review"].append(row)
        elif release < validation_cutoff:
            buckets["development"].append(row)
        elif release < temporal_cutoff:
            buckets["validation"].append(row)
        else:
            buckets["temporal"].append(row)
    for split in ("development", "validation", "temporal", "review"):
        buckets[split].sort(
            key=lambda row: _stable_hash(
                {
                    "catalog_id": catalog_id,
                    "case_id": row["case_id"],
                    "sequence_cluster_id": row.get("sequence_cluster_id"),
                }
            )
        )
    assignments: list[dict[str, str]] = []
    counts: dict[str, int] = {}
    for split in ("development", "validation", "temporal"):
        quota = TARGET_COUNTS[split]
        selected = buckets[split][:quota]
        counts[split] = len(selected)
        assignments.extend({"case_id": str(row["case_id"]), "split": split} for row in selected)
        buckets["review"].extend(buckets[split][quota:])
    counts["overflow"] = len(buckets["review"])
    allocation = {
        "status": "sealed_metadata_only",
        "policy_id": "sequence_cluster_date_window_hash_v1",
        "catalog_id": catalog_id,
        "validation_cutoff": validation_cutoff.isoformat(),
        "temporal_cutoff": temporal_cutoff.isoformat(),
        "target_counts": TARGET_COUNTS,
        "counts": counts,
        "assignments": sorted(assignments, key=lambda item: (item["split"], item["case_id"])),
        "ranking_outcome_used": False,
    }
    allocation["allocation_sha256"] = _stable_hash(allocation)
    return allocation


def build_pocketminer_catalog(
    source_rows: Sequence[Mapping[str, Any]],
    metadata_by_pdb: Mapping[str, Mapping[str, Any]],
    *,
    prior_structure_ids: set[str],
    prior_uniprot_ids: set[str],
    catalog_id: str = DEFAULT_CATALOG_ID,
    validation_cutoff: str = DEFAULT_VALIDATION_CUTOFF,
    temporal_cutoff: str = DEFAULT_TEMPORAL_CUTOFF,
) -> dict[str, Any]:
    """Join source rows to RCSB metadata and seal a future split allocation."""

    validation_date = _parse_date(validation_cutoff, "validation_cutoff")
    temporal_date = _parse_date(temporal_cutoff, "temporal_cutoff")
    if validation_date is None or temporal_date is None:
        raise PocketMinerCatalogError("both split cutoffs are required")
    prior_structures = {str(item).strip().upper() for item in prior_structure_ids}
    prior_uniprots = {str(item).strip().upper() for item in prior_uniprot_ids}
    apo_sequence_records: list[dict[str, Any]] = []
    seen_apo: set[str] = set()
    for row in source_rows:
        apo = _pdb_id(row.get("apo_pdb_id"), "source.apo_pdb_id")
        metadata = _lookup_metadata(
            metadata_by_pdb, apo, _text(row.get("apo_chain_id"), "source.apo_chain_id")
        )
        sequence = metadata.get("sequence") if isinstance(metadata, Mapping) else None
        if isinstance(sequence, str) and sequence and apo not in seen_apo:
            apo_sequence_records.append(
                {
                    "pdb_id": apo,
                    "sequence": sequence,
                    "uniprot_ids": sorted(_metadata_uniprot_ids(metadata)),
                }
            )
            seen_apo.add(apo)
    cluster_payload = (
        cluster_sequence_records(apo_sequence_records, identity_threshold=0.90)
        if apo_sequence_records
        else {"records": [], "clusters": [], "cluster_count": 0}
    )
    clusters = {
        str(item["pdb_id"]): str(item["sequence_cluster_id"])
        for item in cluster_payload.get("records", [])
    }

    candidates: list[dict[str, Any]] = []
    for raw_row in source_rows:
        row = dict(raw_row)
        apo = _pdb_id(row.get("apo_pdb_id"), "source.apo_pdb_id")
        holo = _pdb_id(row.get("holo_pdb_id"), "source.holo_pdb_id")
        apo_metadata = _lookup_metadata(
            metadata_by_pdb, apo, _text(row.get("apo_chain_id"), "source.apo_chain_id")
        )
        holo_metadata = _lookup_metadata(
            metadata_by_pdb, holo, _text(row.get("holo_chain_id"), "source.holo_chain_id")
        )
        reasons: list[str] = []
        metadata_status = "complete"
        if apo == holo:
            reasons.append("apo_holo_same_entry_not_supported")
        if not isinstance(apo_metadata, Mapping) or not isinstance(holo_metadata, Mapping):
            metadata_status = "missing"
            reasons.append("rcsb_metadata_missing")
        else:
            if (
                str(apo_metadata.get("chain_id", "")).upper()
                != str(row.get("apo_chain_id", "")).upper()
            ):
                metadata_status = "chain_mismatch"
                reasons.append("apo_chain_mismatch")
            if (
                str(holo_metadata.get("chain_id", "")).upper()
                != str(row.get("holo_chain_id", "")).upper()
            ):
                metadata_status = "chain_mismatch"
                reasons.append("holo_chain_mismatch")
        apo_uniprots = _metadata_uniprot_ids(apo_metadata or {})
        holo_uniprots = _metadata_uniprot_ids(holo_metadata or {})
        uniprots = sorted(apo_uniprots | holo_uniprots)
        cluster_id = clusters.get(apo)
        if cluster_id is None:
            reasons.append("sequence_cluster_missing")
        overlap_kind = "none"
        if apo in prior_structures or holo in prior_structures:
            overlap_kind = "structure_id"
            reasons.append("prior_study_structure_overlap")
        elif prior_uniprots.intersection(uniprots):
            overlap_kind = "uniprot_id"
            reasons.append("prior_study_uniprot_overlap")
        label_status = (
            "independent_curated_experimental"
            if row.get("label_provenance_class") == _ALLOWED_LABEL_CLASS
            else "unsupported_label_provenance"
        )
        if label_status != "independent_curated_experimental":
            reasons.append("label_provenance_not_independent")
        resource_status = _resource_status(apo_metadata or {})
        if resource_status != _RESOURCE_SAFE:
            reasons.append(f"resource:{resource_status}")
        case_id = _case_id(catalog_id, row, cluster_id)
        candidates.append(
            {
                **row,
                "case_id": case_id,
                "apo_release_date": (apo_metadata or {}).get("release_date"),
                "holo_release_date": (holo_metadata or {}).get("release_date"),
                "uniprot_group_id": "+".join(uniprots),
                "sequence_cluster_id": cluster_id,
                "metadata_status": metadata_status,
                "label_status": label_status,
                "resource_proxy_status": resource_status,
                "prior_overlap": overlap_kind,
                "excluded_reasons": reasons,
                "metadata_eligible_for_selection": not reasons,
            }
        )

    # A sequence cluster contributes at most one case.  The winner is selected
    # by a stable hash that never reads a BioVoid ranking result.
    cluster_groups: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        if row["metadata_eligible_for_selection"] and row.get("sequence_cluster_id"):
            cluster_groups.setdefault(str(row["sequence_cluster_id"]), []).append(row)
    for group in cluster_groups.values():
        if len(group) < 2:
            continue
        winner = min(
            group,
            key=lambda row: _stable_hash({"catalog_id": catalog_id, "case_id": row["case_id"]}),
        )
        for row in group:
            if row is not winner:
                row["metadata_eligible_for_selection"] = False
                row["excluded_reasons"].append("sequence_cluster_duplicate")

    eligible_rows = [row for row in candidates if row["metadata_eligible_for_selection"]]
    allocation = _allocation(
        eligible_rows,
        catalog_id=catalog_id,
        validation_cutoff=validation_date,
        temporal_cutoff=temporal_date,
    )
    assignment_index = {item["case_id"]: item["split"] for item in allocation["assignments"]}
    for row in candidates:
        row["sealed_split"] = assignment_index.get(row["case_id"])
        if row["metadata_eligible_for_selection"] and row["sealed_split"] is None:
            row["excluded_reasons"].append("split_overflow_or_review")

    split_counts = {
        split: allocation["counts"][split]
        for split in ("development", "validation", "temporal", "overflow")
    }
    resource_counts = {
        status: sum(row["resource_proxy_status"] == status for row in candidates)
        for status in (
            "likely_within_static_atom_cap",
            "likely_above_static_atom_cap",
            "review_required",
        )
    }
    capacity = {
        "source_row_count": len(source_rows),
        "candidate_case_count": len(eligible_rows),
        "independent_label_case_count": sum(
            row["label_status"] == "independent_curated_experimental" for row in eligible_rows
        ),
        "split_counts": split_counts,
        "resource_proxy_status_counts": resource_counts,
    }
    if all(split_counts[split] >= TARGET_COUNTS[split] for split in TARGET_COUNTS):
        decision = "PASS"
    elif split_counts["development"] >= TARGET_COUNTS["development"]:
        decision = "DIAGNOSTIC_ONLY"
    else:
        decision = "NO_GO"
    reasons: list[str] = []
    if capacity["candidate_case_count"] < sum(TARGET_COUNTS.values()):
        reasons.append("independent candidate capacity is below 6+2+2")
    for split in TARGET_COUNTS:
        if split_counts[split] < TARGET_COUNTS[split]:
            reasons.append(f"{split} reserve is below target")
    if any(row["prior_overlap"] != "none" for row in candidates):
        reasons.append("prior RI-3/PF00497 structure or UniProt overlaps are excluded")
    report: dict[str, Any] = {
        "schema_version": SOURCE_CATALOG_SCHEMA_VERSION,
        "status": "metadata_only_source_catalog",
        "decision": decision,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "catalog_id": catalog_id,
        "source": {
            "dataset_id": SOURCE_DATASET_ID,
            "dataset_url": SOURCE_DATASET_URL,
            "supplementary_xlsx_url": SOURCE_XLSX_URL,
            "supplementary_xlsx_sha256": None,
            "license": SOURCE_LICENSE,
            "license_url": SOURCE_LICENSE_URL,
            "rcsb_metadata_snapshot_sha256": _metadata_snapshot_hash(metadata_by_pdb),
            "sequence_cluster_report_sha256": _stable_hash(cluster_payload),
            "label_provenance_class": _ALLOWED_LABEL_CLASS,
            "model_outputs_used_as_labels": False,
            "coordinate_files_downloaded": False,
        },
        "allocation": allocation,
        "capacity": capacity,
        "decision_reasons": reasons,
        "sequence_clustering": {
            "method": cluster_payload.get("method", {"id": "global_pairwise_identity_v1"}),
            "cluster_count": cluster_payload.get("cluster_count", 0),
            "review_required": True,
        },
        "candidates": sorted(candidates, key=lambda item: str(item["case_id"])),
        "boundary": {
            "metadata_only": True,
            "coordinates_downloaded": False,
            "holo_coordinates_opened": False,
            "detector_started": False,
            "evaluator_started": False,
            "model_inference_started": False,
            "nma_started": False,
            "external_baseline_started": False,
            "ml_training_started": False,
            "claims_authorized": False,
        },
        "next_gate": (
            "freeze_manifest_then_materialize_development_apo_only"
            if decision == "PASS"
            else "new_versioned_source_catalog_contract"
        ),
    }
    report["report_sha256"] = _stable_hash(report)
    return report


def build_pocketminer_cohort_payload(
    report: Mapping[str, Any], *, family_id: str = "POCKETMINER-NOVEL-CRYPTIC"
) -> dict[str, Any]:
    """Turn the sealed metadata allocation into private evaluator metadata."""

    if report.get("schema_version") != SOURCE_CATALOG_SCHEMA_VERSION:
        raise PocketMinerCatalogError("source catalog schema is unsupported")
    if report.get("decision") != "PASS":
        raise PocketMinerCatalogError("only a PASS source catalog can build a cohort")
    allocation = report.get("allocation")
    candidates = report.get("candidates")
    if not isinstance(allocation, Mapping) or not isinstance(candidates, list):
        raise PocketMinerCatalogError("source catalog allocation/candidates are missing")
    assignment_by_case = {
        str(item.get("case_id")): str(item.get("split"))
        for item in allocation.get("assignments", [])
        if isinstance(item, Mapping)
    }
    candidate_by_case = {
        str(item.get("case_id")): item for item in candidates if isinstance(item, Mapping)
    }
    cases: list[dict[str, Any]] = []
    for case_id, source_split in sorted(assignment_by_case.items()):
        candidate = candidate_by_case.get(case_id)
        if candidate is None or not candidate.get("metadata_eligible_for_selection"):
            raise PocketMinerCatalogError(f"sealed case is no longer eligible: {case_id}")
        if source_split not in {"development", "validation", "temporal"}:
            raise PocketMinerCatalogError(f"unsupported sealed split: {source_split}")
        apo_id = _pdb_id(candidate.get("apo_pdb_id"), "case.apo_structure_id")
        redacted_case_id = (
            f"pocketminer-v1:{apo_id}:"
            f"{_stable_hash({'source_case_id': case_id, 'apo_structure_id': apo_id})[:16]}"
        )
        cases.append(
            {
                "case_id": redacted_case_id,
                "source_catalog_case_id": case_id,
                "apo_structure_id": apo_id,
                "holo_structure_id": _pdb_id(
                    candidate.get("holo_pdb_id"), "case.holo_structure_id"
                ),
                "apo_chain_id": _text(candidate.get("apo_chain_id"), "case.apo_chain_id"),
                "holo_chain_id": _text(candidate.get("holo_chain_id"), "case.holo_chain_id"),
                "family_id": family_id,
                "uniprot_group_id": _text(
                    candidate.get("uniprot_group_id"), "case.uniprot_group_id"
                ),
                "sequence_cluster_id": _text(
                    candidate.get("sequence_cluster_id"), "case.sequence_cluster_id"
                ),
                "split": "test" if source_split == "temporal" else source_split,
                "apo_release_date": _text(
                    candidate.get("apo_release_date"), "case.apo_release_date"
                ),
                "holo_release_date": _text(
                    candidate.get("holo_release_date"), "case.holo_release_date"
                ),
                "label_source": "independent_annotation_v1",
                "label_provenance_class": _ALLOWED_LABEL_CLASS,
                "source_dataset_id": SOURCE_DATASET_ID,
                "source_row_number": candidate.get("row_number"),
                "ligand_code": candidate.get("ligand_code"),
                "pocket_count": candidate.get("pocket_count", 1),
            }
        )
    payload: dict[str, Any] = {
        "schema_version": "biovoid-target-family-cohort-v1",
        "manifest_kind": "private_target_family_cohort",
        "family_id": family_id,
        "split_strategy": "sequence_cluster_temporal_holdout_v1",
        "temporal_cutoff": _text(allocation.get("temporal_cutoff"), "allocation.temporal_cutoff"),
        "source_catalog_id": report.get("catalog_id"),
        "source_catalog_sha256": report.get("report_sha256"),
        "cases": cases,
        "coordinates_downloaded": False,
        "detector_started": False,
        "evaluator_started": False,
        "model_inference_started": False,
        "nma_started": False,
        "ml_training_started": False,
        "cohort_sha256": None,
    }
    payload["cohort_sha256"] = _stable_hash(
        {key: value for key, value in payload.items() if key != "cohort_sha256"}
    )
    return payload


def _entry_resource_proxy(entry: Mapping[str, Any]) -> dict[str, Any]:
    entry_info = entry.get("rcsb_entry_info")
    info = entry_info if isinstance(entry_info, Mapping) else {}

    def positive_int(key: str) -> int | None:
        try:
            value = int(str(info.get(key)))
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    atom_count = positive_int("deposited_atom_count")
    model_count = positive_int("deposited_model_count")
    if atom_count is None or model_count != 1:
        status = "review_required"
    elif atom_count <= SAFE_16GB.max_static_atoms:
        status = _RESOURCE_SAFE
    else:
        status = "likely_above_static_atom_cap"
    return {
        "status": status,
        "profile": SAFE_16GB.name,
        "max_static_atoms": SAFE_16GB.max_static_atoms,
        "deposited_atom_count": atom_count,
        "deposited_model_count": model_count,
        "deposited_polymer_entity_instance_count": positive_int(
            "deposited_polymer_entity_instance_count"
        ),
        "molecular_weight_kda": info.get("molecular_weight"),
        "authoritative_resource_gate": False,
        "coordinates_required_for_authoritative_gate": True,
    }


def _chain_metadata(
    session: requests.Session,
    pdb_id: str,
    chain_id: str,
    *,
    timeout: int,
    entry_cache: dict[str, Mapping[str, Any]],
    entity_cache: dict[tuple[str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    entry = entry_cache.get(pdb_id)
    if entry is None:
        entry = _api_json(session, f"{DATA_URL}/entry/{pdb_id}", timeout=timeout)
        entry_cache[pdb_id] = entry
    identifiers = entry.get("rcsb_entry_container_identifiers")
    entity_ids = (
        identifiers.get("polymer_entity_ids", []) if isinstance(identifiers, Mapping) else []
    )
    matches: list[tuple[str, Mapping[str, Any]]] = []
    for entity_id in entity_ids:
        normalized_id = str(entity_id).strip()
        if not normalized_id:
            continue
        key = (pdb_id, normalized_id)
        entity = entity_cache.get(key)
        if entity is None:
            entity = _api_json(
                session, f"{DATA_URL}/polymer_entity/{pdb_id}/{normalized_id}", timeout=timeout
            )
            entity_cache[key] = entity
        entity_ids_payload = entity.get("rcsb_polymer_entity_container_identifiers")
        if not isinstance(entity_ids_payload, Mapping):
            continue
        chain_values = set()
        for key_name in ("auth_asym_ids", "asym_ids"):
            values = entity_ids_payload.get(key_name, [])
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                chain_values.update(str(value).strip().upper() for value in values)
        if chain_id.upper() in chain_values:
            matches.append((normalized_id, entity))
    if len(matches) != 1:
        raise TargetFamilyMetadataError(
            f"RCSB chain metadata is ambiguous or missing: {pdb_id}:{chain_id}"
        )
    entity_id, entity = matches[0]
    sequence = _sequence_from_entity(entity)
    release_data = entry.get("rcsb_accession_info")
    release_date = (
        release_data.get("initial_release_date") if isinstance(release_data, Mapping) else None
    )
    return {
        "pdb_id": pdb_id,
        "chain_id": chain_id.upper(),
        "polymer_entity_id": entity_id,
        "uniprot_ids": sorted(_uniprot_ids(entity)),
        "sequence_length": len(sequence),
        "sequence": sequence,
        "release_date": release_date,
        "resource_proxy": _entry_resource_proxy(entry),
    }


def collect_pocketminer_metadata(
    source_rows: Sequence[Mapping[str, Any]],
    *,
    session: requests.Session,
    timeout: int = 60,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Fetch entry/polymer metadata for the bounded apo/holo IDs only."""

    entry_cache: dict[str, Mapping[str, Any]] = {}
    entity_cache: dict[tuple[str, str], Mapping[str, Any]] = {}
    metadata: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        for key in ("apo_pdb_id", "holo_pdb_id"):
            pdb_id = _pdb_id(row.get(key), f"source.{key}")
            chain_key = "apo_chain_id" if key == "apo_pdb_id" else "holo_chain_id"
            chain_id = _text(row.get(chain_key), chain_key)
            metadata_key = f"{pdb_id}:{chain_id.upper()}"
            if metadata_key not in metadata:
                metadata[metadata_key] = _chain_metadata(
                    session,
                    pdb_id,
                    chain_id,
                    timeout=timeout,
                    entry_cache=entry_cache,
                    entity_cache=entity_cache,
                )
    return metadata, {
        "provider": "RCSB PDB Data API",
        "entry_metadata_requests": len(entry_cache),
        "polymer_entity_metadata_requests": len(entity_cache),
        "coordinate_files_downloaded": False,
    }


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n")


def render_markdown(report: Mapping[str, Any]) -> str:
    capacity = report["capacity"]
    allocation = report["allocation"]
    lines = [
        "# PocketMiner ranking-study source/catalog v1",
        "",
        f"Decision: **{report['decision']}**",
        "",
        "Metadata-only source gate; this is not a detector, benchmark, validation, "
        "model, or discovery result.",
        "",
        "## Capacity",
        "",
        "| Quantity | Count |",
        "|---|---:|",
        f"| PocketMiner novel cryptic source rows | {capacity['source_row_count']} |",
        f"| Independent candidate cases | {capacity['candidate_case_count']} |",
        f"| Independent curated labels | {capacity['independent_label_case_count']} |",
        f"| Resource proxy status counts | `{capacity['resource_proxy_status_counts']}` |",
        "",
        "## Pre-sealed allocation",
        "",
        f"Policy `{allocation['policy_id']}`; validation cutoff `"
        f"{allocation['validation_cutoff']}`; temporal cutoff `"
        f"{allocation['temporal_cutoff']}`.",
        "",
        "| Split | Target | Sealed count |",
        "|---|---:|---:|",
    ]
    for split in ("development", "validation", "temporal", "overflow"):
        target = TARGET_COUNTS.get(split, "—")
        lines.append(f"| {split} | {target} | {allocation['counts'][split]} |")
    lines.extend(["", "## Decision reasons", ""])
    lines.extend(f"- {reason}" for reason in report["decision_reasons"] or ["none"])
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "No coordinates, holo evaluator, detector, model inference, NMA, "
            "external baseline, or ML training was started.",
            "",
            f"Report SHA-256: `{report['report_sha256']}`",
            "",
        ]
    )
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PocketMinerCatalogError(f"JSON input must be an object: {path}")
    return value


def _prior_overlap_sets(
    *,
    prior_pairs_path: Path,
    prior_cohort_path: Path,
    ri3_manifest_path: Path,
) -> tuple[set[str], set[str]]:
    structures: set[str] = set()
    uniprots: set[str] = set()
    for path in (prior_pairs_path, prior_cohort_path):
        payload = _read_json(path)
        for pair in payload.get("pairs", []) if isinstance(payload.get("pairs"), list) else []:
            for key in ("apo_pdb_id", "holo_pdb_id"):
                if pair.get(key):
                    structures.add(str(pair[key]).strip().upper())
            if pair.get("uniprot_group"):
                uniprots.update(str(pair["uniprot_group"]).upper().split("+"))
        for case in payload.get("cases", []) if isinstance(payload.get("cases"), list) else []:
            for key in ("apo_structure_id", "holo_structure_id"):
                if case.get(key):
                    structures.add(str(case[key]).strip().upper())
            if case.get("uniprot_group_id"):
                uniprots.update(str(case["uniprot_group_id"]).upper().split("+"))
    ri3 = _read_json(ri3_manifest_path)
    for item in ri3.get("cases", []) if isinstance(ri3.get("cases"), list) else []:
        if item.get("structure_id"):
            structures.add(str(item["structure_id"]).strip().upper())
        for key in ("family_id", "uniprot_id"):
            if item.get(key):
                uniprots.add(str(item[key]).strip().upper())
    return structures, uniprots


def run_pocketminer_catalog(
    *,
    xlsx_path: Path = DEFAULT_XLSX,
    output_path: Path = DEFAULT_OUTPUT,
    markdown_path: Path = DEFAULT_MARKDOWN,
    catalog_id: str = DEFAULT_CATALOG_ID,
    validation_cutoff: str = DEFAULT_VALIDATION_CUTOFF,
    temporal_cutoff: str = DEFAULT_TEMPORAL_CUTOFF,
    allow_network: bool = False,
    prior_pairs_path: Path = REPO_ROOT
    / "local-private/research/target-family/pilot-pairs-pfam-v1.json",
    prior_cohort_path: Path = REPO_ROOT
    / "local-private/research/target-family/cohort-pfam-v1.json",
    ri3_manifest_path: Path = REPO_ROOT
    / "data/runtime/ri3/cryptobench-static-pilot-manifest-v1.json",
) -> dict[str, Any]:
    rows = parse_pocketminer_rows(xlsx_path)
    if not allow_network:
        raise PocketMinerCatalogError(
            "PocketMiner RCSB metadata retrieval requires --allow-network"
        )
    session = _metadata_session("BioVoid/0.1 PocketMiner metadata source preflight")
    try:
        metadata, retrieval = collect_pocketminer_metadata(rows, session=session)
    finally:
        session.close()
    prior_structures, prior_uniprots = _prior_overlap_sets(
        prior_pairs_path=prior_pairs_path,
        prior_cohort_path=prior_cohort_path,
        ri3_manifest_path=ri3_manifest_path,
    )
    report = build_pocketminer_catalog(
        rows,
        metadata,
        prior_structure_ids=prior_structures,
        prior_uniprot_ids=prior_uniprots,
        catalog_id=catalog_id,
        validation_cutoff=validation_cutoff,
        temporal_cutoff=temporal_cutoff,
    )
    report["source"]["retrieval"] = retrieval
    report["source"]["supplementary_xlsx_sha256"] = hashlib.sha256(
        xlsx_path.read_bytes()
    ).hexdigest()
    report["report_sha256"] = _stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    _write_json(output_path, report)
    _write_text(markdown_path, render_markdown(report))
    print(
        f"PocketMiner source catalog: decision={report['decision']} "
        f"candidates={report['capacity']['candidate_case_count']} "
        f"splits={report['capacity']['split_counts']}"
    )
    print(f"source catalog JSON: {output_path}")
    print(f"source catalog markdown: {markdown_path}")
    print("coordinates/model/evaluator/detector/NMA/ML started: no")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--catalog-id", default=DEFAULT_CATALOG_ID)
    parser.add_argument("--validation-cutoff", default=DEFAULT_VALIDATION_CUTOFF)
    parser.add_argument("--temporal-cutoff", default=DEFAULT_TEMPORAL_CUTOFF)
    parser.add_argument(
        "--prior-pairs",
        type=Path,
        default=REPO_ROOT / "local-private/research/target-family/pilot-pairs-pfam-v1.json",
    )
    parser.add_argument(
        "--prior-cohort",
        type=Path,
        default=REPO_ROOT / "local-private/research/target-family/cohort-pfam-v1.json",
    )
    parser.add_argument(
        "--ri3-manifest",
        type=Path,
        default=REPO_ROOT / "data/runtime/ri3/cryptobench-static-pilot-manifest-v1.json",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="acknowledge bounded RCSB metadata-only requests",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        run_pocketminer_catalog(
            xlsx_path=args.xlsx,
            output_path=args.output,
            markdown_path=args.markdown,
            catalog_id=args.catalog_id,
            validation_cutoff=args.validation_cutoff,
            temporal_cutoff=args.temporal_cutoff,
            allow_network=args.allow_network,
            prior_pairs_path=args.prior_pairs,
            prior_cohort_path=args.prior_cohort,
            ri3_manifest_path=args.ri3_manifest,
        )
    except (
        PocketMinerCatalogError,
        TargetFamilyMetadataError,
        OSError,
        requests.RequestException,
    ) as exc:
        print(f"PocketMiner source catalog error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
