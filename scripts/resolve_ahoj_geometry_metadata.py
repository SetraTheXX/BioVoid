"""Resolve bounded AHoJ source metadata without downloading structures.

This is the second gate after the AHoJ metadata-only feasibility audit.  It
fetches only RCSB entry/polymer-entity JSON, resolves a UniProt-matched protein
entity and its chain IDs for each side of an apo/holo pair, and clusters apo
sequences in memory.  Sequence text is never written to the report.  The
source label remains review-required until its provenance is independently
curated; this command cannot authorize detector, evaluator, NMA, or ML work.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_ahoj_geometry_source_catalog import (  # noqa: E402
    AhojCatalogError,
    _prior_structure_ids,
    _read_json,
    _write_json,
)
from scripts.materialize_target_family_sequence_clusters import (  # noqa: E402
    _protein_sequence,
    _uniprot_ids,
    cluster_sequence_records,
)

RCSB_DATA_URL = "https://data.rcsb.org/rest/v1/core"
SOURCE_REPORT = (
    REPO_ROOT / "local-private/research/geometry-data-source-catalog/ahoj-v1/"
    "ahoj-geometry-source-catalog-v1.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "local-private/research/geometry-data-source-catalog/ahoj-v1/"
    "ahoj-geometry-metadata-resolution-v1.json"
)
DEFAULT_CACHE = (
    REPO_ROOT / "local-private/research/geometry-data-source-catalog/ahoj-v1/"
    "polymer-entity-metadata"
)
MAX_CASES = 64
DEFAULT_TIMEOUT_SECONDS = 45
# AHoJ-specific split windows are frozen before any coordinates or detector
# output: enough pre-2021 capacity is retained for development and a later
# temporal slice remains held out.
DEV_CUTOFF = "2018-01-01"
TEMPORAL_CUTOFF = "2021-01-01"
LABEL_POLICY_VERSION = "ahoj-biolip2-site-assignment-v1"
LABEL_SOURCE_URL = "https://apoholo.cz/db"
LABEL_ARCHIVE_URL = "https://apoholo.cz/db/archive"


class AhojMetadataResolutionError(RuntimeError):
    """Raised when the metadata resolution contract cannot be evaluated."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _api_json(session: requests.Session, url: str, *, timeout: int) -> Mapping[str, Any]:
    if any(suffix in url.casefold() for suffix in (".pdb", ".cif", ".mmcif", ".sdf")):
        raise AhojMetadataResolutionError("coordinate-like URL is outside metadata boundary")
    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise AhojMetadataResolutionError(f"RCSB metadata request failed: {url}") from exc
    except (TypeError, ValueError) as exc:
        raise AhojMetadataResolutionError(f"RCSB metadata JSON is invalid: {url}") from exc
    if not isinstance(payload, Mapping):
        raise AhojMetadataResolutionError(f"RCSB metadata response is not an object: {url}")
    return payload


def _cached_api_json(
    session: requests.Session,
    url: str,
    *,
    cache_dir: Path,
    cache_name: str,
    timeout: int,
) -> Mapping[str, Any]:
    cache_path = cache_dir / f"{cache_name}.json"
    if cache_path.is_file():
        return _read_json(cache_path)
    payload = _api_json(session, url, timeout=timeout)
    _write_json(cache_path, dict(payload))
    return payload


def _entity_ids(entry: Mapping[str, Any], *, structure_id: str) -> list[str]:
    identifiers = entry.get("rcsb_entry_container_identifiers")
    if not isinstance(identifiers, Mapping):
        raise AhojMetadataResolutionError(f"entry {structure_id} lacks polymer entity IDs")
    values = identifiers.get("polymer_entity_ids")
    if not isinstance(values, list):
        raise AhojMetadataResolutionError(f"entry {structure_id} has invalid polymer entity IDs")
    entity_ids = sorted({str(value).strip() for value in values if str(value).strip()})
    if not entity_ids:
        raise AhojMetadataResolutionError(f"entry {structure_id} has no polymer entities")
    return entity_ids


def _chain_ids(entity: Mapping[str, Any]) -> list[str]:
    identifiers = entity.get("rcsb_polymer_entity_container_identifiers")
    if not isinstance(identifiers, Mapping):
        return []
    values = identifiers.get("auth_asym_ids") or identifiers.get("asym_ids") or []
    if not isinstance(values, list):
        return []
    return sorted({str(value).strip().upper() for value in values if str(value).strip()})


def _cluster_membership(entity: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = entity.get("rcsb_cluster_membership")
    if not isinstance(raw, list):
        return []
    output = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        try:
            identity = int(item.get("identity"))
            cluster_id = int(item.get("cluster_id"))
        except (TypeError, ValueError):
            continue
        output.append({"identity": identity, "cluster_id": cluster_id})
    return sorted(output, key=lambda item: (-item["identity"], item["cluster_id"]))


def _ligand_chain_ids(
    session: requests.Session,
    structure_id: str,
    ligand_code: str,
    *,
    cache_dir: Path,
    timeout: int,
) -> list[str]:
    """Resolve evaluator-side ligand instances from RCSB metadata only."""

    normalized_structure = structure_id.upper()
    normalized_ligand = ligand_code.upper()
    entry = _cached_api_json(
        session,
        f"{RCSB_DATA_URL}/entry/{normalized_structure}",
        cache_dir=cache_dir,
        cache_name=f"entry-{normalized_structure.lower()}",
        timeout=timeout,
    )
    identifiers = entry.get("rcsb_entry_container_identifiers")
    if not isinstance(identifiers, Mapping):
        return []
    raw_ids = identifiers.get("non_polymer_entity_ids") or []
    if not isinstance(raw_ids, list):
        return []
    chains: set[str] = set()
    for entity_id in sorted({str(value).strip() for value in raw_ids if str(value).strip()}):
        entity = _cached_api_json(
            session,
            f"{RCSB_DATA_URL}/nonpolymer_entity/{normalized_structure}/{entity_id}",
            cache_dir=cache_dir,
            cache_name=f"nonpolymer-{normalized_structure.lower()}-{entity_id}",
            timeout=timeout,
        )
        entity_ids = entity.get("rcsb_nonpolymer_entity_container_identifiers")
        if not isinstance(entity_ids, Mapping):
            continue
        comp_id = str(
            entity_ids.get("nonpolymer_comp_id") or entity_ids.get("chem_ref_def_id") or ""
        ).upper()
        if comp_id != normalized_ligand:
            continue
        raw_chains = entity_ids.get("auth_asym_ids") or entity_ids.get("asym_ids") or []
        if isinstance(raw_chains, list):
            chains.update(str(value).strip().upper() for value in raw_chains if str(value).strip())
    return sorted(chains)


def _matching_entity(
    session: requests.Session,
    structure_id: str,
    uniprot_id: str,
    *,
    cache_dir: Path,
    timeout: int,
) -> dict[str, Any]:
    normalized_structure = structure_id.upper()
    normalized_uniprot = uniprot_id.upper()
    entry = _cached_api_json(
        session,
        f"{RCSB_DATA_URL}/entry/{normalized_structure}",
        cache_dir=cache_dir,
        cache_name=f"entry-{normalized_structure.lower()}",
        timeout=timeout,
    )
    candidates: list[dict[str, Any]] = []
    for entity_id in _entity_ids(entry, structure_id=normalized_structure):
        entity = _cached_api_json(
            session,
            f"{RCSB_DATA_URL}/polymer_entity/{normalized_structure}/{entity_id}",
            cache_dir=cache_dir,
            cache_name=f"entity-{normalized_structure.lower()}-{entity_id}",
            timeout=timeout,
        )
        if normalized_uniprot not in _uniprot_ids(entity):
            continue
        sequence = _protein_sequence(entity, pdb_id=normalized_structure, entity_id=str(entity_id))
        if sequence is None:
            continue
        candidates.append(
            {
                "structure_id": normalized_structure,
                "entity_id": str(entity_id),
                "chain_ids": _chain_ids(entity),
                "uniprot_ids": list(_uniprot_ids(entity)),
                "sequence": sequence,
                "sequence_length": len(sequence),
                "sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest(),
                "rcsb_cluster_membership": _cluster_membership(entity),
            }
        )
    if len(candidates) != 1:
        status = "no_matching_entity" if not candidates else "ambiguous_matching_entities"
        return {
            "structure_id": normalized_structure,
            "status": status,
            "candidate_count": len(candidates),
        }
    return {"status": "resolved", **candidates[0]}


def _prior_uniprot_ids() -> set[str]:
    paths = (
        REPO_ROOT
        / "local-private/research/ranking-study-source-catalog/pocketminer-v1/pocketminer-cohort-v1.json",
        REPO_ROOT / "data/runtime/ri3/cryptobench-static-pilot-manifest-v1.json",
        REPO_ROOT
        / "data/runtime/target-family/cohort-detector-pfam-v1/target-family-cohort-detector-pfam-v1.json",
    )
    found: set[str] = set()
    key_names = {"uniprot_id", "uniprot_ids", "uniprot_group_id", "target_uniprot_ids"}

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, Mapping):
            for child_key, child_value in value.items():
                walk(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif key.casefold() in key_names:
            text = str(value).strip().upper()
            if text:
                found.add(text)

    for path in paths:
        if path.is_file():
            walk(_read_json(path))
    return found


def _date_bucket(release_date: str | None) -> str | None:
    if not release_date:
        return None
    date = release_date[:10]
    if date < DEV_CUTOFF:
        return "development"
    if date < TEMPORAL_CUTOFF:
        return "validation"
    return "temporal"


def _case_id(pair: Mapping[str, Any], *, holo_structure_id: str | None = None) -> str:
    return (
        "ahoj-geometry-v1:"
        + _stable_hash(
            {
                "apo": pair["apo_structure_id"],
                "holo": holo_structure_id or pair["holo_structure_id"],
                "uniprot": pair["uniprot_id"],
                "ligand": pair["query_ligand"],
            }
        )[:16]
    )


def resolve_ahoj_metadata(
    *,
    source_report_path: Path = SOURCE_REPORT,
    output_path: Path = DEFAULT_OUTPUT,
    cache_dir: Path = DEFAULT_CACHE,
    allow_network: bool = False,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_cases: int = MAX_CASES,
    accept_label_provenance: bool = False,
) -> dict[str, Any]:
    if not allow_network:
        raise AhojMetadataResolutionError("RCSB metadata access requires --allow-network")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if not 1 <= max_cases <= MAX_CASES:
        raise ValueError(f"max_cases must be between 1 and {MAX_CASES}")
    report = _read_json(source_report_path)
    if report.get("schema_version") != "biovoid-ahoj-geometry-source-catalog-v1":
        raise AhojMetadataResolutionError("unsupported AHoJ source report schema")
    pairs = report.get("pairs")
    if not isinstance(pairs, list):
        raise AhojMetadataResolutionError("source report pairs are missing")

    selected: list[Mapping[str, Any]] = []
    seen_apo: set[str] = set()
    seen_uniprot: set[str] = set()
    for pair in pairs:
        if not isinstance(pair, Mapping):
            continue
        if pair.get("apo_resource_proxy", {}).get("status") != "likely_within_static_atom_cap":
            continue
        apo_id = str(pair.get("apo_structure_id", "")).upper()
        uniprot_id = str(pair.get("uniprot_id", "")).upper()
        if not apo_id or apo_id in seen_apo or not uniprot_id or uniprot_id in seen_uniprot:
            continue
        seen_apo.add(apo_id)
        seen_uniprot.add(uniprot_id)
        selected.append(pair)
        if len(selected) >= max_cases:
            break

    prior_structures = _prior_structure_ids()
    prior_uniprots = _prior_uniprot_ids()
    session = requests.Session()
    session.headers.update({"User-Agent": "BioVoid/0.1 AHoJ metadata resolution"})
    cache_dir.mkdir(parents=True, exist_ok=True)
    resolved_cases: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    sequence_records: list[dict[str, Any]] = []
    for pair in selected:
        uniprot_id = str(pair["uniprot_id"]).upper()
        apo_id = str(pair["apo_structure_id"]).upper()
        ligand_code = str(pair.get("query_ligand", "")).upper()
        holo_candidates = [
            str(value).upper()
            for value in pair.get("holo_candidate_structure_ids", [])
            if str(value).strip()
        ]
        if str(pair.get("holo_structure_id", "")).strip():
            holo_candidates.append(str(pair["holo_structure_id"]).upper())
        holo_candidates = sorted(set(holo_candidates))
        holo_id = holo_candidates[0] if holo_candidates else ""
        ligand_chain_ids: list[str] = []
        for candidate_holo_id in holo_candidates:
            try:
                ligand_chain_ids = _ligand_chain_ids(
                    session,
                    candidate_holo_id,
                    ligand_code,
                    cache_dir=cache_dir,
                    timeout=timeout,
                )
            except AhojMetadataResolutionError:
                ligand_chain_ids = []
            if ligand_chain_ids:
                holo_id = candidate_holo_id
                break
        try:
            apo = _matching_entity(
                session, apo_id, uniprot_id, cache_dir=cache_dir, timeout=timeout
            )
            holo = _matching_entity(
                session, holo_id, uniprot_id, cache_dir=cache_dir, timeout=timeout
            )
            overlap_reasons = []
            if apo_id in prior_structures or holo_id in prior_structures:
                overlap_reasons.append("prior_structure_overlap")
            if uniprot_id in prior_uniprots:
                overlap_reasons.append("prior_uniprot_overlap")
            chain_status = (
                "resolved"
                if apo.get("status") == "resolved"
                and holo.get("status") == "resolved"
                and ligand_chain_ids
                else "review_required_entity_or_chain_mapping"
            )
            case = {
                "case_id": _case_id(pair, holo_structure_id=holo_id),
                "apo_structure_id": apo_id,
                "holo_structure_id": holo_id,
                "uniprot_id": uniprot_id,
                "ligand_code": ligand_code,
                "apo_release_date": pair.get("apo_release_date"),
                "holo_release_date": pair.get("holo_release_date"),
                "apo_entity": {key: value for key, value in apo.items() if key != "sequence"},
                "holo_entity": {key: value for key, value in holo.items() if key != "sequence"},
                "chain_mapping_status": chain_status,
                "sequence_status": "resolved"
                if apo.get("status") == "resolved"
                else "review_required",
                "label_status": (
                    "independent_external_biolip2_site_assignment_v1"
                    if accept_label_provenance and ligand_chain_ids
                    else "review_required_ahoj_biolip2_site_assignment"
                ),
                "holo_ligand_chain_ids": ligand_chain_ids,
                "overlap_reasons": sorted(overlap_reasons),
                "resource_proxy": pair["apo_resource_proxy"],
            }
            resolved_cases.append(case)
            if apo.get("status") == "resolved" and not overlap_reasons and apo.get("sequence"):
                sequence_records.append(
                    {
                        "pdb_id": apo_id,
                        "sequence": apo["sequence"],
                        "uniprot_ids": [uniprot_id],
                    }
                )
        except (AhojMetadataResolutionError, KeyError, TypeError, ValueError) as exc:
            failures.append({"case_id": _case_id(pair), "reason": type(exc).__name__})
    session.close()

    clusters = cluster_sequence_records(sequence_records, identity_threshold=0.90)
    cluster_by_pdb = {str(record["pdb_id"]): record for record in clusters.get("records", [])}
    for case in resolved_cases:
        record = cluster_by_pdb.get(case["apo_structure_id"])
        if record:
            case["sequence_cluster_id"] = record["sequence_cluster_id"]
            case["sequence_cluster_size"] = record["sequence_cluster_size"]
            case["sequence_status"] = "resolved_review_required"
        else:
            case["sequence_cluster_id"] = None
            case["sequence_cluster_size"] = None

    eligible = [
        case
        for case in resolved_cases
        if case["chain_mapping_status"] == "resolved"
        and case["sequence_cluster_id"]
        and not case["overlap_reasons"]
    ]
    allocation: list[dict[str, Any]] = []
    used_clusters: set[str] = set()
    for bucket in ("development", "validation", "temporal"):
        target = {"development": 6, "validation": 2, "temporal": 2}[bucket]
        bucket_cases = sorted(
            (case for case in eligible if _date_bucket(case.get("apo_release_date")) == bucket),
            key=lambda case: (case["sequence_cluster_id"], case["apo_structure_id"]),
        )
        for case in bucket_cases:
            cluster_id = str(case["sequence_cluster_id"])
            if (
                cluster_id in used_clusters
                or len([item for item in allocation if item["split"] == bucket]) >= target
            ):
                continue
            allocation.append({"case_id": case["case_id"], "split": bucket})
            used_clusters.add(cluster_id)

    split_counts = {
        split: sum(item["split"] == split for item in allocation)
        for split in ("development", "validation", "temporal")
    }
    label_review_count = sum(
        case["label_status"].startswith("review_required") for case in eligible
    )
    decision = (
        "PASS"
        if split_counts == {"development": 6, "validation": 2, "temporal": 2}
        and accept_label_provenance
        and label_review_count == 0
        else "DIAGNOSTIC_ONLY"
        if eligible
        else "NO_GO"
    )
    output: dict[str, Any] = {
        "schema_version": "biovoid-ahoj-geometry-metadata-resolution-v1",
        "status": "metadata_only_sequence_and_chain_review",
        "decision": decision,
        "source_report_sha256": _stable_hash(report),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "selection_policy": {
            "version": "safe_unique_apo_uniprot_lexicographic_v1",
            "max_cases": max_cases,
            "selected_case_count": len(selected),
            "coordinates_downloaded": False,
            "ligand_files_downloaded": False,
        },
        "label_policy": {
            "version": LABEL_POLICY_VERSION,
            "source_url": LABEL_SOURCE_URL,
            "archive_url": LABEL_ARCHIVE_URL,
            "provenance": "AHoJ precomputed apo/holo assignment from BioLiP2",
            "semantics": "target PDB chain and bound ligand define the site; matching structures are labelled HOLO or APO",
            "accepted": accept_label_provenance,
            "evaluator_only": True,
        },
        "capacity": {
            "selected_cases": len(selected),
            "resolved_chain_cases": sum(
                case["chain_mapping_status"] == "resolved" for case in resolved_cases
            ),
            "sequence_cluster_records": len(sequence_records),
            "sequence_cluster_count": clusters.get("cluster_count", 0),
            "eligible_cases": len(eligible),
            "label_review_required_cases": label_review_count,
            "allocation_split_counts": split_counts,
            "allocation_target": {"development": 6, "validation": 2, "temporal": 2},
            "failures": len(failures),
        },
        "cases": resolved_cases,
        "allocation": {
            "status": "review_required_not_sealed"
            if decision != "PASS"
            else "sealed_metadata_only",
            "assignments": sorted(allocation, key=lambda item: (item["split"], item["case_id"])),
            "temporal_cutoff": TEMPORAL_CUTOFF,
            "development_cutoff": DEV_CUTOFF,
            "sequence_cluster_identity_threshold": 0.90,
        },
        "sequence_cluster_report": {
            key: value for key, value in clusters.items() if key not in {"records"}
        },
        "failures": failures,
        "boundary": {
            "metadata_only": True,
            "coordinates_downloaded": False,
            "detector_started": False,
            "evaluator_opened": False,
            "motion_enabled": False,
            "nma_started": False,
            "ml_training_started": False,
        },
        "next_gate": (
            "materialize only the six development apo inputs under the sealed detector manifest"
            if decision == "PASS"
            else "accept the versioned external AHoJ/BioLiP2 label policy, then seal 6/2/2"
            if not accept_label_provenance
            else "open a separately versioned source contract because the reserved capacity is insufficient"
        ),
        "report_sha256": None,
    }
    output["report_sha256"] = _stable_hash(
        {key: value for key, value in output.items() if key != "report_sha256"}
    )
    _write_json(output_path, output)
    print(
        f"AHoJ metadata resolution: decision={decision} selected={len(selected)} "
        f"eligible={len(eligible)} allocation={split_counts}"
    )
    print(f"resolution report: {output_path}")
    print("coordinates/ligands/detector/evaluator/NMA/ML: no")
    return output


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", type=Path, default=SOURCE_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-cases", type=int, default=MAX_CASES)
    parser.add_argument(
        "--accept-label-provenance",
        action="store_true",
        help="accept the versioned external AHoJ/BioLiP2 site-assignment policy",
    )
    parser.add_argument("--allow-network", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        resolve_ahoj_metadata(
            source_report_path=args.source_report,
            output_path=args.output,
            cache_dir=args.cache_dir,
            allow_network=args.allow_network,
            timeout=args.timeout,
            max_cases=args.max_cases,
            accept_label_provenance=args.accept_label_provenance,
        )
    except (AhojMetadataResolutionError, AhojCatalogError, OSError, ValueError) as exc:
        print(f"AHoJ metadata resolution error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
