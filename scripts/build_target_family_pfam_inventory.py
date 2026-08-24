"""Build a bounded PFAM-annotation metadata inventory for target-family review.

The original PF00497 inventory came from a 4P0I sequence search.  This
companion command asks RCSB for the first bounded page of exact PFAM annotation
matches, then reads only entry, polymer-entity and non-polymer metadata.  It
does not download coordinates, open structures, run the detector, run a
benchmark, or train ML.  Ambiguous entries containing multiple PF00497 polymer
entities are skipped rather than silently selecting one entity.

Each retained entry also receives a non-authoritative ``SAFE_16GB`` resource
proxy based on deposited atom/model counts, polymer-instance count and molecular
weight.  The proxy only prioritizes later review; prepared coordinates remain
the authoritative static resource gate.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_target_family_manifest import (  # noqa: E402
    DATA_URL,
    DEFAULT_MAX_RESOLUTION_ANGSTROM,
    DEFAULT_MAX_SEQUENCE_LENGTH,
    DEFAULT_MIN_SEQUENCE_LENGTH,
    MAX_METADATA_ENTRIES,
    SEARCH_URL,
    TargetFamilyMetadataError,
    _api_json,
    _component_metadata,
    _metadata_session,
    _nonpolymer_entity_ids,
    _record_from_entity,
    _record_payload,
)
from src.resources import SAFE_16GB  # noqa: E402
from src.target_family_manifest import RcsbMetadataRecord, select_pilot_pairs  # noqa: E402


INVENTORY_SCHEMA_VERSION = "biovoid-target-family-metadata-inventory-v1"
DEFAULT_FAMILY_ID = "PF00497"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_OUTPUT = REPO_ROOT / "local-private/research/target-family/metadata-inventory-pfam-v1.json"
_PDB_ID_RE = re.compile(r"^[A-Z0-9]{4}$")
RESOURCE_PROXY_SCHEMA_VERSION = "biovoid-target-family-resource-proxy-v1"
RESOURCE_PROXY_STATUSES = (
    "likely_within_static_atom_cap",
    "likely_above_static_atom_cap",
    "review_required",
)


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_pfam_search_request(
    family_id: str = DEFAULT_FAMILY_ID, *, max_entries: int = MAX_METADATA_ENTRIES
) -> dict[str, Any]:
    """Build the exact PFAM annotation query with the local result bound."""

    normalized_family = family_id.strip().upper()
    if not normalized_family:
        raise ValueError("family_id must not be empty")
    if not 1 <= max_entries <= MAX_METADATA_ENTRIES:
        raise ValueError(f"max_entries must be between 1 and {MAX_METADATA_ENTRIES}")
    return {
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "rcsb_polymer_entity_annotation.annotation_id",
                "operator": "exact_match",
                "value": normalized_family,
            },
        },
        "return_type": "entry",
        "request_options": {
            "paginate": {"start": 0, "rows": max_entries},
            "results_content_type": ["experimental"],
            "results_verbosity": "compact",
        },
    }


def _search_entry_ids(
    session: requests.Session, request: Mapping[str, Any], *, timeout: int
) -> tuple[list[str], int]:
    response = session.post(SEARCH_URL, json=dict(request), timeout=timeout)
    if response.status_code == 204:
        raise TargetFamilyMetadataError("RCSB PFAM query returned no entries")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise TargetFamilyMetadataError("RCSB PFAM response is not an object")
    result_set = payload.get("result_set", [])
    if not isinstance(result_set, Sequence) or isinstance(result_set, (str, bytes)):
        raise TargetFamilyMetadataError("RCSB PFAM result_set is invalid")
    entry_ids: set[str] = set()
    for item in result_set:
        identifier = item.get("identifier") if isinstance(item, Mapping) else item
        normalized = str(identifier or "").strip().upper()
        if _PDB_ID_RE.fullmatch(normalized):
            entry_ids.add(normalized)
    if not entry_ids:
        raise TargetFamilyMetadataError("RCSB PFAM query returned no valid PDB IDs")
    total_count = payload.get("total_count")
    try:
        declared_total = int(str(total_count))
    except (TypeError, ValueError):
        declared_total = len(entry_ids)
    return sorted(entry_ids), declared_total


def _records_for_entry(
    session: requests.Session,
    entry_id: str,
    *,
    family_id: str,
    timeout: int,
    component_cache: dict[tuple[str, str], Any],
) -> list[RcsbMetadataRecord]:
    entry = _api_json(session, f"{DATA_URL}/entry/{entry_id}", timeout=timeout)
    identifiers = entry.get("rcsb_entry_container_identifiers")
    if not isinstance(identifiers, Mapping):
        return []
    entity_ids = identifiers.get("polymer_entity_ids", [])
    if not isinstance(entity_ids, Sequence) or isinstance(entity_ids, (str, bytes)):
        return []
    components = []
    for nonpolymer_id in _nonpolymer_entity_ids(entry):
        cache_key = (entry_id, nonpolymer_id)
        if cache_key not in component_cache:
            component_cache[cache_key] = _component_metadata(
                session, entry_id, nonpolymer_id, timeout=timeout
            )
        component = component_cache[cache_key]
        if component is not None:
            components.append(component)
    component_tuple = tuple(sorted(set(components), key=lambda item: item.comp_id))
    records: list[RcsbMetadataRecord] = []
    for entity_id in sorted(str(value) for value in entity_ids if str(value).strip()):
        entity = _api_json(
            session, f"{DATA_URL}/polymer_entity/{entry_id}/{entity_id}", timeout=timeout
        )
        record = _record_from_entity(
            entry_id,
            entry,
            entity,
            family_id=family_id,
            components=component_tuple,
        )
        if record is not None:
            records.append(record)
    return records


def collect_pfam_metadata_records(
    session: requests.Session,
    *,
    family_id: str = DEFAULT_FAMILY_ID,
    max_entries: int = MAX_METADATA_ENTRIES,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[list[RcsbMetadataRecord], dict[str, Any]]:
    """Collect a bounded, de-duplicated PFAM inventory without coordinates."""

    normalized_family = family_id.strip().upper()
    if not normalized_family:
        raise ValueError("family_id must not be empty")
    if not 1 <= max_entries <= MAX_METADATA_ENTRIES:
        raise ValueError(f"max_entries must be between 1 and {MAX_METADATA_ENTRIES}")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    search_request = build_pfam_search_request(normalized_family, max_entries=max_entries)
    entry_ids, declared_total = _search_entry_ids(session, search_request, timeout=timeout)
    records_by_entry: dict[str, list[RcsbMetadataRecord]] = {}
    component_cache: dict[tuple[str, str], Any] = {}
    skipped_empty_entry_count = 0
    for entry_id in entry_ids:
        entry_records = _records_for_entry(
            session,
            entry_id,
            family_id=normalized_family,
            timeout=timeout,
            component_cache=component_cache,
        )
        if not entry_records:
            skipped_empty_entry_count += 1
            continue
        records_by_entry[entry_id] = entry_records

    records: list[RcsbMetadataRecord] = []
    skipped_multi_entity_entry_count = 0
    duplicate_group_count = 0
    for entry_id in sorted(records_by_entry):
        entry_records = records_by_entry[entry_id]
        unique_groups = {record.primary_group_id for record in entry_records}
        duplicate_group_count += len(entry_records) - len(unique_groups)
        if len(entry_records) != 1:
            skipped_multi_entity_entry_count += 1
            continue
        records.append(entry_records[0])
    records.sort(key=lambda record: (record.primary_group_id, record.pdb_id))
    source = {
        "provider": "RCSB PDB Search API + Data API",
        "query_kind": "pfam_annotation_exact_match",
        "family_id": normalized_family,
        "search_url": SEARCH_URL,
        "data_url": DATA_URL,
        "coordinate_files_downloaded": False,
        "search_request_sha256": _stable_hash(search_request),
        "search_result_count": declared_total,
        "bounded_entry_count": len(entry_ids),
        "skipped_empty_entry_count": skipped_empty_entry_count,
        "skipped_multi_entity_entry_count": skipped_multi_entity_entry_count,
        "duplicate_group_count": duplicate_group_count,
    }
    return records, source


def _resource_proxy_payload(record: RcsbMetadataRecord) -> dict[str, Any]:
    """Classify entry metadata without replacing the prepared-coordinate gate."""

    atom_count = record.deposited_atom_count
    model_count = record.deposited_model_count
    if atom_count is None or model_count != 1:
        status = "review_required"
    elif atom_count <= SAFE_16GB.max_static_atoms:
        status = "likely_within_static_atom_cap"
    else:
        status = "likely_above_static_atom_cap"
    return {
        "schema_version": RESOURCE_PROXY_SCHEMA_VERSION,
        "status": status,
        "profile": SAFE_16GB.name,
        "max_static_atoms": SAFE_16GB.max_static_atoms,
        "deposited_atom_count": atom_count,
        "deposited_model_count": model_count,
        "deposited_polymer_entity_instance_count": (record.deposited_polymer_entity_instance_count),
        "molecular_weight_kda": record.molecular_weight_kda,
        "polymer_composition": record.polymer_composition,
        "authoritative_resource_gate": False,
        "coordinates_required_for_authoritative_gate": True,
    }


def _status_counts(records: Sequence[RcsbMetadataRecord]) -> dict[str, int]:
    counts = {status: 0 for status in RESOURCE_PROXY_STATUSES}
    for record in records:
        counts[str(_resource_proxy_payload(record)["status"])] += 1
    return counts


def build_pfam_inventory_payload(
    records: Sequence[RcsbMetadataRecord], source: Mapping[str, Any], *, family_id: str
) -> dict[str, Any]:
    """Serialize the PFAM metadata inventory and retain bounded pair counts."""

    normalized_family = family_id.strip().upper()
    if not records:
        raise ValueError("at least one PFAM metadata record is required")
    strict_pairs = select_pilot_pairs(
        records,
        min_sequence_length=DEFAULT_MIN_SEQUENCE_LENGTH,
        max_sequence_length=DEFAULT_MAX_SEQUENCE_LENGTH,
        max_resolution_angstrom=DEFAULT_MAX_RESOLUTION_ANGSTROM,
    )
    relaxed_pairs = select_pilot_pairs(
        records,
        min_sequence_length=120,
        max_sequence_length=DEFAULT_MAX_SEQUENCE_LENGTH,
        max_resolution_angstrom=DEFAULT_MAX_RESOLUTION_ANGSTROM,
    )
    record_payloads = []
    for record in records:
        record_payload = _record_payload(record)
        record_payload["resource_proxy"] = _resource_proxy_payload(record)
        record_payloads.append(record_payload)
    strict_apo_records = [pair.apo for pair in strict_pairs]
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    inventory: dict[str, Any] = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "status": "metadata_materialized_review_required",
        "retrieved_at_utc": retrieved_at,
        "source": {**dict(source), "family_id": normalized_family},
        "filters": {
            "min_sequence_length": DEFAULT_MIN_SEQUENCE_LENGTH,
            "max_sequence_length": DEFAULT_MAX_SEQUENCE_LENGTH,
            "max_resolution_angstrom": DEFAULT_MAX_RESOLUTION_ANGSTROM,
            "max_cases": 10,
        },
        "record_count": len(records),
        "unique_uniprot_group_count": len({record.primary_group_id for record in records}),
        "records": record_payloads,
        "pilot_pair_count": len(strict_pairs),
        "relaxed_120_pair_count": len(relaxed_pairs),
        "resource_proxy_summary": {
            "schema_version": RESOURCE_PROXY_SCHEMA_VERSION,
            "profile": SAFE_16GB.name,
            "max_static_atoms": SAFE_16GB.max_static_atoms,
            "record_status_counts": _status_counts(records),
            "strict_pair_apo_status_counts": _status_counts(strict_apo_records),
            "authoritative_resource_gate": False,
            "coordinates_required_for_authoritative_gate": True,
        },
        "coordinate_files_downloaded": False,
    }
    inventory["inventory_sha256"] = _stable_hash(inventory)
    return inventory


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def run_pfam_inventory_builder(
    *,
    family_id: str = DEFAULT_FAMILY_ID,
    max_entries: int = MAX_METADATA_ENTRIES,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    session = _metadata_session("BioVoid/0.1 target-family PFAM metadata preflight")
    try:
        records, source = collect_pfam_metadata_records(
            session, family_id=family_id, max_entries=max_entries, timeout=timeout
        )
    finally:
        session.close()
    inventory = build_pfam_inventory_payload(records, source, family_id=family_id)
    _write_json(output_path.resolve(), inventory)
    print(
        f"target-family PFAM metadata: entries={source['bounded_entry_count']} "
        f"records={inventory['record_count']} groups={inventory['unique_uniprot_group_count']} "
        f"strict_pairs={inventory['pilot_pair_count']} relaxed_pairs={inventory['relaxed_120_pair_count']}"
    )
    print(f"PFAM metadata inventory: {output_path}")
    print("coordinate files downloaded: no")
    print("detector/benchmark/NMA/ML started: no")
    return inventory


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family-id", default=DEFAULT_FAMILY_ID)
    parser.add_argument("--max-entries", type=int, default=MAX_METADATA_ENTRIES)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="required acknowledgement before requesting bounded RCSB metadata",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.allow_network:
        print("PFAM metadata preflight requires --allow-network", file=sys.stderr)
        return 2
    try:
        run_pfam_inventory_builder(
            family_id=args.family_id,
            max_entries=args.max_entries,
            timeout=args.timeout,
            output_path=args.output,
        )
    except (TargetFamilyMetadataError, requests.RequestException, ValueError, OSError) as exc:
        print(f"target-family PFAM metadata error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
