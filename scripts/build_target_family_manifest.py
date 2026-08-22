"""Build a metadata-only, target-blind pilot for the selected PF00497 family.

The command uses the RCSB Search and Data APIs only.  It retrieves sequence,
entry, polymer-entity and non-polymer *metadata*; it never requests a PDB/mmCIF
coordinate file, never invokes the detector, and never starts a benchmark.

Evaluator-side apo/holo pair metadata is written below ``local-private``.  The
detector-facing manifest contains only apo PDB identifiers and bounded static
resource constraints, and is validated before it is written.
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

from src.target_family_manifest import (  # noqa: E402
    DEFAULT_MAX_RESOLUTION_ANGSTROM,
    DEFAULT_MAX_SEQUENCE_LENGTH,
    DEFAULT_MIN_SEQUENCE_LENGTH,
    MAX_PILOT_CASES,
    NonPolymerComponent,
    RcsbMetadataRecord,
    build_detector_manifest,
    select_pilot_pairs,
)


SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
DATA_URL = "https://data.rcsb.org/rest/v1/core"
DEFAULT_REFERENCE_ENTRY = "4P0I"
DEFAULT_REFERENCE_ENTITY = "1"
DEFAULT_FAMILY_ID = "PF00497"
MAX_METADATA_ENTRIES = 100
DEFAULT_TIMEOUT_SECONDS = 60
INVENTORY_SCHEMA_VERSION = "biovoid-target-family-metadata-inventory-v1"
DEFAULT_INVENTORY_OUTPUT = (
    REPO_ROOT / "local-private/research/target-family/metadata-inventory-pfam-v1.json"
)
DEFAULT_PAIRS_OUTPUT = REPO_ROOT / "local-private/research/target-family/pilot-pairs-pfam-v1.json"
DEFAULT_MANIFEST_OUTPUT = (
    REPO_ROOT / "data/runtime/target-family/target-blind-static-pilot-pfam-v1.json"
)


class TargetFamilyMetadataError(RuntimeError):
    """Raised when RCSB metadata cannot satisfy the local pilot contract."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _api_json(session: requests.Session, url: str, *, timeout: int) -> Mapping[str, Any]:
    response = session.get(url, timeout=timeout)
    if response.status_code == 404:
        raise TargetFamilyMetadataError(f"RCSB metadata endpoint returned 404: {url}")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise TargetFamilyMetadataError(f"RCSB metadata response is not an object: {url}")
    return payload


def _sequence_from_entity(entity: Mapping[str, Any]) -> str:
    entity_poly = entity.get("entity_poly")
    if not isinstance(entity_poly, Mapping):
        raise TargetFamilyMetadataError("Reference entity has no entity_poly metadata")
    sequence = entity_poly.get("pdbx_seq_one_letter_code_can") or entity_poly.get(
        "pdbx_seq_one_letter_code"
    )
    normalized = "".join(str(sequence or "").split()).upper()
    if not normalized:
        raise TargetFamilyMetadataError("Reference entity has no canonical sequence")
    if any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ*" for character in normalized):
        raise TargetFamilyMetadataError("Reference sequence contains unexpected characters")
    return normalized


def build_sequence_search_request(
    sequence: str,
    *,
    identity_cutoff: float = 0.30,
    max_entries: int = MAX_METADATA_ENTRIES,
) -> dict[str, Any]:
    """Build the bounded RCSB sequence-search request used by the CLI."""

    normalized = "".join(str(sequence).split()).upper()
    if not normalized:
        raise ValueError("sequence must not be empty")
    if not 0 < identity_cutoff <= 1:
        raise ValueError("identity_cutoff must be in (0, 1]")
    if not 1 <= max_entries <= MAX_METADATA_ENTRIES:
        raise ValueError(f"max_entries must be between 1 and {MAX_METADATA_ENTRIES}")
    return {
        "query": {
            "type": "terminal",
            "service": "sequence",
            "parameters": {
                "evalue_cutoff": 1,
                "identity_cutoff": identity_cutoff,
                "target": "pdb_protein_sequence",
                "value": normalized,
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
    session: requests.Session,
    request: Mapping[str, Any],
    *,
    timeout: int,
) -> list[str]:
    response = session.post(SEARCH_URL, json=request, timeout=timeout)
    if response.status_code == 204:
        raise TargetFamilyMetadataError("RCSB sequence search returned no entries")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise TargetFamilyMetadataError("RCSB sequence search response is not an object")
    result_set = payload.get("result_set", [])
    if not isinstance(result_set, Sequence) or isinstance(result_set, (str, bytes)):
        raise TargetFamilyMetadataError("RCSB sequence search result_set is invalid")
    entry_ids: set[str] = set()
    for item in result_set:
        identifier = item.get("identifier") if isinstance(item, Mapping) else item
        normalized = str(identifier or "").strip().upper()
        if re.fullmatch(r"[A-Z0-9]{4}", normalized):
            entry_ids.add(normalized)
    if not entry_ids:
        raise TargetFamilyMetadataError("RCSB sequence search returned no valid PDB IDs")
    return sorted(entry_ids)


def _resolution_angstrom(entry: Mapping[str, Any]) -> float | None:
    entry_info = entry.get("rcsb_entry_info")
    if isinstance(entry_info, Mapping):
        combined = entry_info.get("resolution_combined")
        if isinstance(combined, Sequence) and not isinstance(combined, (str, bytes)):
            values = []
            for value in combined:
                try:
                    values.append(float(value))
                except (TypeError, ValueError):
                    continue
            if values:
                return min(values)
    values = []
    for item in entry.get("refine", []):
        if isinstance(item, Mapping) and item.get("ls_d_res_high") is not None:
            try:
                values.append(float(item["ls_d_res_high"]))
            except (TypeError, ValueError):
                continue
    return min(values) if values else None


def _experimental_method(entry: Mapping[str, Any]) -> str:
    methods = sorted(
        {
            str(item.get("method")).strip()
            for item in entry.get("exptl", [])
            if isinstance(item, Mapping) and item.get("method")
        }
    )
    return "; ".join(methods)


def _uniprot_ids(entity: Mapping[str, Any]) -> tuple[str, ...]:
    identifiers = entity.get("rcsb_polymer_entity_container_identifiers")
    if not isinstance(identifiers, Mapping):
        return ()
    values = set()
    for value in identifiers.get("uniprot_ids", []):
        if value:
            values.add(str(value).strip().upper())
    for item in identifiers.get("reference_sequence_identifiers", []):
        if (
            isinstance(item, Mapping)
            and str(item.get("database_name", "")).casefold() == "uniprot"
            and item.get("database_accession")
        ):
            values.add(str(item["database_accession"]).strip().upper())
    return tuple(sorted(values))


def _pfam_ids(entity: Mapping[str, Any]) -> tuple[str, ...]:
    values: set[str] = set()
    annotations = entity.get("rcsb_polymer_entity_annotation", [])
    for item in annotations:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("type", "")).casefold() != "pfam":
            continue
        identifier = item.get("annotation_id") or item.get("feature_id")
        if identifier:
            values.add(str(identifier).strip().upper())
    return tuple(sorted(values))


def _nonpolymer_entity_ids(entry: Mapping[str, Any]) -> tuple[str, ...]:
    identifiers = entry.get("rcsb_entry_container_identifiers")
    if not isinstance(identifiers, Mapping):
        return ()
    values = identifiers.get("non_polymer_entity_ids", [])
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return ()
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def _component_metadata(
    session: requests.Session,
    entry_id: str,
    entity_id: str,
    *,
    timeout: int,
) -> NonPolymerComponent | None:
    payload = _api_json(
        session,
        f"{DATA_URL}/nonpolymer_entity/{entry_id}/{entity_id}",
        timeout=timeout,
    )
    nonpoly = payload.get("pdbx_entity_nonpoly")
    if not isinstance(nonpoly, Mapping):
        return None
    comp_id = str(nonpoly.get("comp_id") or "").strip()
    name = str(nonpoly.get("name") or comp_id).strip()
    if not comp_id or not name:
        return None
    return NonPolymerComponent(comp_id=comp_id, name=name)


def _record_from_entity(
    entry_id: str,
    entry: Mapping[str, Any],
    entity: Mapping[str, Any],
    *,
    family_id: str,
    components: tuple[NonPolymerComponent, ...],
) -> RcsbMetadataRecord | None:
    pfam_ids = _pfam_ids(entity)
    if family_id.upper() not in pfam_ids:
        return None
    uniprot_ids = _uniprot_ids(entity)
    if not uniprot_ids:
        return None
    entity_poly = entity.get("entity_poly")
    if not isinstance(entity_poly, Mapping):
        return None
    if str(entity_poly.get("rcsb_entity_polymer_type", "Protein")).casefold() != "protein":
        return None
    raw_length = entity_poly.get("rcsb_sample_sequence_length")
    try:
        sequence_length = int(str(raw_length))
    except (TypeError, ValueError):
        sequence_length = len(
            "".join(str(entity_poly.get("pdbx_seq_one_letter_code_can") or "").split())
        )
    description_data = entity.get("rcsb_polymer_entity")
    description = ""
    if isinstance(description_data, Mapping):
        description = str(description_data.get("pdbx_description") or "").strip()
    if not description:
        description = str(entry.get("struct", {}).get("title") or entry_id).strip()
    release_data = entry.get("rcsb_accession_info")
    release_date = (
        str(release_data.get("initial_release_date"))
        if isinstance(release_data, Mapping) and release_data.get("initial_release_date")
        else None
    )
    return RcsbMetadataRecord(
        pdb_id=entry_id,
        uniprot_ids=uniprot_ids,
        family_id=family_id.upper(),
        description=description,
        sequence_length=sequence_length,
        resolution_angstrom=_resolution_angstrom(entry),
        experimental_method=_experimental_method(entry),
        nonpolymer_components=components,
        pfam_ids=pfam_ids,
        release_date=release_date,
    )


def collect_metadata_records(
    session: requests.Session,
    *,
    reference_entry: str = DEFAULT_REFERENCE_ENTRY,
    reference_entity: str = DEFAULT_REFERENCE_ENTITY,
    family_id: str = DEFAULT_FAMILY_ID,
    max_entries: int = MAX_METADATA_ENTRIES,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[list[RcsbMetadataRecord], dict[str, Any]]:
    """Collect family records from RCSB without requesting coordinates."""

    reference_entry = reference_entry.strip().upper()
    if re.fullmatch(r"[A-Z0-9]{4}", reference_entry) is None:
        raise ValueError("reference_entry must be a four-character PDB ID")
    if not 1 <= max_entries <= MAX_METADATA_ENTRIES:
        raise ValueError(f"max_entries must be between 1 and {MAX_METADATA_ENTRIES}")
    family_id = family_id.strip().upper()
    reference = _api_json(
        session,
        f"{DATA_URL}/polymer_entity/{reference_entry}/{reference_entity}",
        timeout=timeout,
    )
    reference_pfam_ids = _pfam_ids(reference)
    if family_id not in reference_pfam_ids:
        raise TargetFamilyMetadataError(
            f"Reference {reference_entry}_{reference_entity} lacks requested Pfam {family_id}"
        )
    sequence = _sequence_from_entity(reference)
    search_request = build_sequence_search_request(sequence, max_entries=max_entries)
    entry_ids = _search_entry_ids(session, search_request, timeout=timeout)
    records: list[RcsbMetadataRecord] = []
    seen: set[tuple[str, str]] = set()
    component_cache: dict[tuple[str, str], NonPolymerComponent | None] = {}
    skipped_entities = 0
    for entry_id in entry_ids:
        entry = _api_json(session, f"{DATA_URL}/entry/{entry_id}", timeout=timeout)
        identifiers = entry.get("rcsb_entry_container_identifiers")
        if not isinstance(identifiers, Mapping):
            skipped_entities += 1
            continue
        entity_ids = identifiers.get("polymer_entity_ids", [])
        if not isinstance(entity_ids, Sequence) or isinstance(entity_ids, (str, bytes)):
            skipped_entities += 1
            continue
        components: list[NonPolymerComponent] = []
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
        for entity_id in sorted(str(value) for value in entity_ids):
            entity = _api_json(
                session,
                f"{DATA_URL}/polymer_entity/{entry_id}/{entity_id}",
                timeout=timeout,
            )
            record = _record_from_entity(
                entry_id,
                entry,
                entity,
                family_id=family_id,
                components=component_tuple,
            )
            if record is None:
                skipped_entities += 1
                continue
            key = (record.pdb_id, record.primary_group_id)
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
    records.sort(key=lambda record: (record.primary_group_id, record.pdb_id))
    source = {
        "provider": "RCSB PDB Search API + Data API",
        "search_url": SEARCH_URL,
        "data_url": DATA_URL,
        "coordinate_files_downloaded": False,
        "reference_entry": reference_entry,
        "reference_entity": reference_entity,
        "family_id": family_id,
        "sequence_length": len(sequence),
        "search_request_sha256": _stable_hash(search_request),
        "search_result_count": len(entry_ids),
        "skipped_entity_count": skipped_entities,
    }
    return records, source


def _record_payload(record: RcsbMetadataRecord) -> dict[str, Any]:
    return {
        "pdb_id": record.pdb_id,
        "uniprot_ids": list(record.uniprot_ids),
        "family_id": record.family_id,
        "description": record.description,
        "sequence_length": record.sequence_length,
        "resolution_angstrom": record.resolution_angstrom,
        "experimental_method": record.experimental_method,
        "pfam_ids": list(record.pfam_ids),
        "release_date": record.release_date,
        "nonpolymer_components": [
            {"comp_id": item.comp_id, "name": item.name} for item in record.nonpolymer_components
        ],
        "likely_ligand_components": [
            {"comp_id": item.comp_id, "name": item.name} for item in record.likely_ligand_components
        ],
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-entry", default=DEFAULT_REFERENCE_ENTRY)
    parser.add_argument("--reference-entity", default=DEFAULT_REFERENCE_ENTITY)
    parser.add_argument("--family-id", default=DEFAULT_FAMILY_ID)
    parser.add_argument("--max-entries", type=int, default=MAX_METADATA_ENTRIES)
    parser.add_argument("--max-cases", type=int, default=MAX_PILOT_CASES)
    parser.add_argument("--min-sequence-length", type=int, default=DEFAULT_MIN_SEQUENCE_LENGTH)
    parser.add_argument("--max-sequence-length", type=int, default=DEFAULT_MAX_SEQUENCE_LENGTH)
    parser.add_argument(
        "--max-resolution-angstrom",
        type=float,
        default=DEFAULT_MAX_RESOLUTION_ANGSTROM,
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--inventory-output",
        type=Path,
        default=DEFAULT_INVENTORY_OUTPUT,
    )
    parser.add_argument(
        "--pairs-output",
        type=Path,
        default=DEFAULT_PAIRS_OUTPUT,
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=DEFAULT_MANIFEST_OUTPUT,
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.max_entries > MAX_METADATA_ENTRIES:
        raise SystemExit(f"--max-entries cannot exceed {MAX_METADATA_ENTRIES}")
    if args.max_cases > MAX_PILOT_CASES:
        raise SystemExit(f"--max-cases cannot exceed {MAX_PILOT_CASES}")
    session = requests.Session()
    session.headers.update({"User-Agent": "BioVoid/0.1 target-family metadata pilot"})
    try:
        records, source = collect_metadata_records(
            session,
            reference_entry=args.reference_entry,
            reference_entity=args.reference_entity,
            family_id=args.family_id,
            max_entries=args.max_entries,
            timeout=args.timeout,
        )
    finally:
        session.close()
    pairs = select_pilot_pairs(
        records,
        max_cases=args.max_cases,
        min_sequence_length=args.min_sequence_length,
        max_sequence_length=args.max_sequence_length,
        max_resolution_angstrom=args.max_resolution_angstrom,
    )
    if not pairs:
        raise SystemExit("No eligible apo/holo metadata pairs passed the pilot filters")
    manifest = build_detector_manifest(pairs)
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    inventory: dict[str, Any] = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "status": "metadata_materialized_review_required",
        "retrieved_at_utc": retrieved_at,
        "source": source,
        "filters": {
            "min_sequence_length": args.min_sequence_length,
            "max_sequence_length": args.max_sequence_length,
            "max_resolution_angstrom": args.max_resolution_angstrom,
            "max_cases": args.max_cases,
        },
        "record_count": len(records),
        "unique_uniprot_group_count": len({record.primary_group_id for record in records}),
        "records": [_record_payload(record) for record in records],
        "pilot_pair_count": len(pairs),
    }
    inventory["inventory_sha256"] = _stable_hash(inventory)
    pairs_payload = {
        "schema_version": "biovoid-target-family-pilot-pairs-v1",
        "status": "private_metadata_review_required",
        "retrieved_at_utc": retrieved_at,
        "pairs": [pair.private_metadata() for pair in pairs],
    }
    pairs_payload["pairs_sha256"] = _stable_hash(pairs_payload)
    _write_json(args.inventory_output.resolve(), inventory)
    _write_json(args.pairs_output.resolve(), pairs_payload)
    _write_json(args.manifest_output.resolve(), manifest)
    print("target-family metadata pilot: PASS")
    print(f"family_id: {manifest['family_id']}")
    print(f"search entries: {source['search_result_count']}")
    print(f"metadata records: {len(records)}")
    print(f"unique UniProt groups: {inventory['unique_uniprot_group_count']}")
    print(f"eligible pilot pairs: {len(pairs)}")
    print(f"detector cases: {manifest['constraints']['case_count']}")
    print(f"manifest sha256: {manifest['manifest_sha256']}")
    print("coordinate files downloaded: no")
    print("detector/benchmark/NMA started: no")
    print(f"manifest path: {args.manifest_output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
