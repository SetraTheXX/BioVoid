"""Materialize a metadata-only, independently reviewable RI-6 source inventory.

This command queries RCSB identifiers and entry/entity metadata for the frozen
KPC-2/CTX-M-15 target set. It never downloads coordinate files and never runs
the BioVoid detector. Every non-obviously-invalid record remains
``review_required``; an "apo" title is evidence for review, not acceptance.
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

from scripts.run_ri6_tem1_transfer_control import RI6ContractError  # noqa: E402
from scripts.write_ri6_target_lock import TARGET_ACCESSIONS  # noqa: E402

SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
DATA_URL = "https://data.rcsb.org/rest/v1/core"
DEFAULT_OUTPUT = REPO_ROOT / "data/runtime/ri6/source-inventory/ri6-source-inventory-v1.json"
INVENTORY_SCHEMA_VERSION = "biovoid-ri6-source-inventory-v1"
TARGET_LOCK_SCHEMA_VERSION = "biovoid-ri6-target-lock-v1"


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _build_search_request(accessions: Sequence[str]) -> dict[str, Any]:
    normalized_input = [str(value).strip().upper() for value in accessions]
    if set(normalized_input) != set(TARGET_ACCESSIONS) or len(normalized_input) != len(
        TARGET_ACCESSIONS
    ):
        raise RI6ContractError(
            "Source inventory accessions must match the frozen RI-6 target lock"
        )
    normalized = list(TARGET_ACCESSIONS)
    return {
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": (
                    "rcsb_polymer_entity_container_identifiers."
                    "reference_sequence_identifiers.database_accession"
                ),
                "operator": "in",
                "value": normalized,
            },
        },
        "return_type": "polymer_entity",
        "request_options": {
            "paginate": {"start": 0, "rows": 10000},
            "results_content_type": ["experimental"],
            "results_verbosity": "compact",
        },
    }


def _api_json(session: requests.Session, url: str) -> dict[str, Any]:
    response = session.get(url, timeout=60)
    if response.status_code == 404:
        raise RI6ContractError(f"RCSB metadata endpoint returned 404: {url}")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RI6ContractError(f"RCSB metadata response is not an object: {url}")
    return payload


def _resolution(entry: Mapping[str, Any]) -> float | None:
    values: list[float] = []
    for item in entry.get("refine", []):
        if isinstance(item, Mapping) and item.get("ls_d_res_high") is not None:
            values.append(float(item["ls_d_res_high"]))
    if not values:
        for item in entry.get("pdbx_vrpt_summary_diffraction", []):
            if isinstance(item, Mapping) and item.get("EDS_res_high") is not None:
                values.append(float(item["EDS_res_high"]))
    return min(values) if values else None


def _first_source_name(entity: Mapping[str, Any]) -> str | None:
    sources = entity.get("rcsb_entity_source_organism", [])
    if not sources or not isinstance(sources[0], Mapping):
        return None
    return str(sources[0].get("scientific_name") or sources[0].get("ncbi_scientific_name") or "") or None


def _classify_entry_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    title = str(metadata.get("title") or "")
    title_lower = title.lower()
    methods = tuple(str(value).upper() for value in metadata.get("experimental_methods", []))
    resolution = metadata.get("resolution_angstrom")
    reasons: list[str] = []
    if not metadata.get("uniprot_accessions"):
        reasons.append("target_accession_missing")
    if "X-RAY DIFFRACTION" not in methods:
        reasons.append("not_xray_diffraction")
    if resolution is None or float(resolution) > 2.2:
        reasons.append("resolution_missing_or_above_2_2_angstrom")
    if int(metadata.get("mutation_count") or 0) > 0:
        reasons.append("mutation_annotation_requires_manual_review")
    title_ligand_signal = bool(
        re.search(r"\b(holo|ligand|inhibitor|complex|compound|adduct|bound)\b", title_lower)
    )
    if title_ligand_signal:
        reasons.append("title_has_bound_or_complex_signal")
    if int(metadata.get("nonpolymer_entity_count") or 0) > 0:
        reasons.append("nonpolymer_entities_require_manual_review")
    output = dict(metadata)
    output.update(
        {
            "title_apo_signal": bool(re.search(r"\bapo\b", title_lower)),
            "title_ligand_signal": title_ligand_signal,
            "manual_review_required": True,
            "metadata_ineligible_reasons": sorted(set(reasons)),
            "preliminary_status": "metadata_ineligible" if any(
                reason in reasons
                for reason in (
                    "target_accession_missing",
                    "not_xray_diffraction",
                    "resolution_missing_or_above_2_2_angstrom",
                )
            ) else "review_required",
        }
    )
    return output


def _entry_record(
    entry_id: str,
    entity_id: str,
    entity: Mapping[str, Any],
    entry: Mapping[str, Any],
) -> dict[str, Any]:
    identifiers = entity.get("rcsb_polymer_entity_container_identifiers", {})
    uniprots = sorted(
        {
            str(item.get("database_accession")).upper()
            for item in identifiers.get("reference_sequence_identifiers", [])
            if isinstance(item, Mapping)
            and item.get("database_name") == "UniProt"
            and item.get("database_accession")
        }
    )
    methods = sorted(
        {
            str(item.get("method")).upper()
            for item in entry.get("exptl", [])
            if isinstance(item, Mapping) and item.get("method")
        }
    )
    entry_info = entry.get("rcsb_entry_info", {})
    entity_poly = entity.get("entity_poly", {})
    record = {
        "entry_id": entry_id,
        "polymer_entity_id": entity_id,
        "asym_ids": sorted(str(value) for value in identifiers.get("asym_ids", [])),
        "uniprot_accessions": uniprots,
        "title": str(entry.get("struct", {}).get("title") or ""),
        "experimental_methods": methods,
        "resolution_angstrom": _resolution(entry),
        "initial_release_date": entry.get("rcsb_accession_info", {}).get("initial_release_date"),
        "source_organism": _first_source_name(entity),
        "mutation_count": int(entity_poly.get("rcsb_mutation_count") or 0),
        "nonstandard_monomer_count": int(entity_poly.get("rcsb_non_std_monomer_count") or 0),
        "nonpolymer_entity_count": int(entry_info.get("nonpolymer_entity_count") or 0),
        "nonpolymer_entity_ids": sorted(
            str(value)
            for value in entry.get("rcsb_entry_container_identifiers", {}).get(
                "non_polymer_entity_ids", []
            )
        ),
    }
    return _classify_entry_metadata(record)


def materialize_inventory(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    http = session or requests.Session()
    search_request = _build_search_request(TARGET_ACCESSIONS)
    response = http.post(SEARCH_URL, json=search_request, timeout=60)
    if response.status_code == 204:
        raise RI6ContractError("RCSB target search returned no structures")
    response.raise_for_status()
    search_payload = response.json()
    result_ids = sorted(str(value) for value in search_payload.get("result_set", []))
    if not result_ids:
        raise RI6ContractError("RCSB target search returned no polymer entities")

    records: list[dict[str, Any]] = []
    for result_id in result_ids:
        if "_" not in result_id:
            raise RI6ContractError(f"Unexpected polymer entity identifier: {result_id}")
        entry_id, entity_id = result_id.split("_", 1)
        entity = _api_json(http, f"{DATA_URL}/polymer_entity/{entry_id}/{entity_id}")
        entry = _api_json(http, f"{DATA_URL}/entry/{entry_id}")
        records.append(_entry_record(entry_id, entity_id, entity, entry))

    payload: dict[str, Any] = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "status": "metadata_materialized_review_required",
        "target_lock_schema_version": TARGET_LOCK_SCHEMA_VERSION,
        "target_accessions": list(TARGET_ACCESSIONS),
        "source": {
            "provider": "RCSB PDB Search API + Data API",
            "search_url": SEARCH_URL,
            "data_url": DATA_URL,
            "coordinate_files_downloaded": False,
            "retrieved_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "search_request_sha256": _stable_hash(search_request),
            "search_result_count": len(result_ids),
        },
        "review_policy": {
            "auto_accept": False,
            "title_apo_is_not_sufficient": True,
            "review_fields": [
                "ligand identity and binding state",
                "engineered mutation and catalytic-site integrity",
                "biological assembly and chain selection",
                "missing residues and alternate locations",
                "source accession and target identity",
            ],
        },
        "records": records,
    }
    payload["inventory_sha256"] = _stable_hash(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = materialize_inventory(output_path=args.output.resolve())
    print(f"status={payload['status']}")
    print(f"record_count={len(payload['records'])}")
    print(f"inventory_sha256={payload['inventory_sha256']}")
    print("coordinate_files_downloaded=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
