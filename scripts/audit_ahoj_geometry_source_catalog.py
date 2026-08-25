"""Audit a bounded AHoJ apo/holo source without downloading coordinates.

The AHoJ-DB subset is used only as a metadata catalog. The audit queries the
public AHoJ and RCSB metadata APIs, records apo/holo capacity and conservative
resource proxies, and deliberately stops before chain/sequence-cluster
resolution is complete. It never downloads PDB/mmCIF coordinates, ligand files,
opens evaluator data, runs BioVoid, starts Docker, NMA, or ML.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.resources import SAFE_16GB  # noqa: E402

DEFAULT_SOURCE_ROOT = REPO_ROOT / "local-private/research/geometry-data-source-catalog/ahoj-v1"
DEFAULT_QUERY_SUMMARIES = DEFAULT_SOURCE_ROOT / "subset1/query_summaries.csv"
DEFAULT_ARCHIVE = (
    REPO_ROOT / "local-private/research/geometry-data-source-catalog-ahoj-v1-subset1.zip"
)
DEFAULT_OUTPUT = DEFAULT_SOURCE_ROOT / "ahoj-geometry-source-catalog-v1.json"
DEFAULT_RCSB_CACHE = DEFAULT_SOURCE_ROOT / "rcsb-entry-metadata"
AHOJ_API_URL = "https://apoholo.cz/api/db/search"
RCSB_ENTRY_URL = "https://data.rcsb.org/rest/v1/core/entry/{structure_id}"
SOURCE_ID = "ahoj-db-v1-subset1"
SOURCE_VERSION = "AHoJ-DB v1 subset 1"
SOURCE_URL = "https://apoholo.cz/db/archive"
MAX_API_QUERIES = 192
TARGET_CASES = 10
FORBIDDEN_COORDINATE_SUFFIXES = (".pdb", ".cif", ".mmcif", ".sdf")
PDB_PATTERN = re.compile(r"^[A-Z0-9]{4}$")
UNIPROT_PATTERN = re.compile(r"^[A-Z0-9_-]+$")


class AhojCatalogError(RuntimeError):
    """Raised when the metadata-only catalog cannot be audited safely."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AhojCatalogError(f"cannot read JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise AhojCatalogError(f"JSON root is not an object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _pdb_id(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text if PDB_PATTERN.fullmatch(text) else None


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _walk_structure_ids(value: Any, *, key: str = "") -> set[str]:
    found: set[str] = set()
    normalized_key = key.casefold()
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            if str(child_key).casefold() in {
                "structure_id",
                "pdb_id",
                "apo_structure_id",
                "holo_structure_id",
                "target_pdb_id",
            }:
                candidate = _pdb_id(child_value)
                if candidate:
                    found.add(candidate)
            found.update(_walk_structure_ids(child_value, key=str(child_key)))
    elif isinstance(value, list):
        for child in value:
            found.update(_walk_structure_ids(child, key=normalized_key))
    return found


def _prior_structure_ids() -> set[str]:
    paths = (
        REPO_ROOT
        / "local-private/research/ranking-study-source-catalog/pocketminer-v1/pocketminer-cohort-v1.json",
        REPO_ROOT / "data/runtime/ri3/cryptobench-static-pilot-manifest-v1.json",
        REPO_ROOT
        / "data/runtime/target-family/cohort-detector-pfam-v1/target-family-cohort-detector-pfam-v1.json",
    )
    found: set[str] = set()
    for path in paths:
        if path.is_file():
            found.update(_walk_structure_ids(_read_json(path)))
    return found


def load_query_candidates(path: Path, *, prior_structure_ids: set[str]) -> list[dict[str, Any]]:
    if any(path.name.casefold().endswith(suffix) for suffix in FORBIDDEN_COORDINATE_SUFFIXES):
        raise AhojCatalogError("coordinate-like input is not allowed for metadata audit")
    try:
        handle = path.open(newline="", encoding="utf-8")
    except OSError as exc:
        raise AhojCatalogError(f"cannot open query summary: {path}") from exc
    candidates: list[dict[str, Any]] = []
    seen_groups: set[tuple[str, str]] = set()
    with handle:
        reader = csv.DictReader(handle)
        required = {
            "ahoj_query",
            "qstruct",
            "qchains3",
            "qlig",
            "qUNPs",
            "num_apo_pockets",
            "num_holo_pockets",
        }
        if not required.issubset(set(reader.fieldnames or ())):
            raise AhojCatalogError("AHoJ query summary header is incomplete")
        for row in reader:
            structure_id = _pdb_id(row.get("qstruct"))
            chain = str(row.get("qchains3") or "").strip().upper()
            ligand = str(row.get("qlig") or "").strip().upper()
            uniprot = str(row.get("qUNPs") or "").strip().upper()
            apo_count = _positive_int(row.get("num_apo_pockets"))
            holo_count = _positive_int(row.get("num_holo_pockets"))
            if (
                structure_id is None
                or structure_id in prior_structure_ids
                or not re.fullmatch(r"[A-Z0-9]", chain)
                or not ligand
                or not UNIPROT_PATTERN.fullmatch(uniprot)
                or apo_count is None
                or holo_count is None
                or apo_count < 1
                or holo_count < 1
            ):
                continue
            group_key = (uniprot, ligand)
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)
            candidates.append(
                {
                    "ahoj_query": str(row["ahoj_query"]),
                    "query_structure_id": structure_id,
                    "query_chain_id": chain,
                    "query_ligand": ligand,
                    "uniprot_id": uniprot,
                    "query_apo_pocket_count": apo_count,
                    "query_holo_pocket_count": holo_count,
                }
            )
    candidates.sort(
        key=lambda item: (
            item["uniprot_id"],
            item["query_ligand"],
            item["query_structure_id"],
            item["query_chain_id"],
        )
    )
    return candidates


def select_query_candidates(
    candidates: list[dict[str, Any]], *, max_queries: int
) -> list[dict[str, Any]]:
    """Select a bounded, deterministic, structure-diverse metadata sample."""

    if not 1 <= max_queries <= MAX_API_QUERIES:
        raise ValueError(f"max_queries must be between 1 and {MAX_API_QUERIES}")
    buckets: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        buckets.setdefault(str(candidate["uniprot_id"]), []).append(candidate)
    positions = {key: 0 for key in buckets}
    selected: list[dict[str, Any]] = []
    used_query_structures: set[str] = set()
    while len(selected) < max_queries:
        progressed = False
        for uniprot_id in sorted(buckets):
            bucket = buckets[uniprot_id]
            position = positions[uniprot_id]
            while position < len(bucket):
                candidate = bucket[position]
                position += 1
                if candidate["query_structure_id"] in used_query_structures:
                    continue
                positions[uniprot_id] = position
                selected.append(candidate)
                used_query_structures.add(candidate["query_structure_id"])
                progressed = True
                break
            if len(selected) >= max_queries:
                break
        if not progressed:
            break
    return selected


def _request_json(
    session: requests.Session, url: str, *, params: Mapping[str, Any]
) -> dict[str, Any]:
    try:
        response = session.get(url, params=params, timeout=45)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise AhojCatalogError(f"metadata request failed: {url}") from exc
    if not isinstance(payload, dict):
        raise AhojCatalogError(f"metadata response is not an object: {url}")
    return payload


def _first_entry(payload: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any] | None:
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return None
    query_structure_id = candidate["query_structure_id"]
    query_chain = candidate["query_chain_id"]
    query_ligand = candidate["query_ligand"]
    matches = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("target_pdb_id", "")).upper() != query_structure_id:
            continue
        if str(entry.get("target_ligand", "")).upper() != query_ligand:
            continue
        target_chains = {str(value).upper() for value in entry.get("target_chains", [])}
        if query_chain not in target_chains:
            continue
        matches.append(dict(entry))
    if not matches:
        return None
    matches.sort(key=lambda item: str(item.get("entry_key", "")))
    return matches[0]


def _rcsb_entry_metadata(
    session: requests.Session,
    structure_id: str,
    *,
    cache_dir: Path,
) -> dict[str, Any]:
    cache_path = cache_dir / f"{structure_id.lower()}.json"
    if cache_path.is_file():
        return _read_json(cache_path)
    payload = _request_json(
        session, RCSB_ENTRY_URL.format(structure_id=structure_id.lower()), params={}
    )
    _write_json(cache_path, payload)
    return payload


def _pair_from_entry(
    entry: Mapping[str, Any],
    *,
    prior_structure_ids: set[str],
) -> dict[str, Any] | None:
    apo_ids = sorted({_pdb_id(value) for value in entry.get("found_apo_pdbids", [])} - {None})
    holo_ids = sorted({_pdb_id(value) for value in entry.get("found_holo_pdbids", [])} - {None})
    apo_ids = [value for value in apo_ids if value not in prior_structure_ids]
    holo_ids = [value for value in holo_ids if value not in prior_structure_ids]
    for apo_id in apo_ids:
        for holo_id in holo_ids:
            if apo_id != holo_id:
                return {
                    "entry_key": str(entry.get("entry_key", "")),
                    "target_pdb_id": str(entry.get("target_pdb_id", "")).upper(),
                    "target_chains": [
                        str(value).upper() for value in entry.get("target_chains", [])
                    ],
                    "target_ligand": str(entry.get("target_ligand", "")).upper(),
                    "uniprot_ids": [
                        str(value).upper() for value in entry.get("target_uniprot_ids", [])
                    ],
                    "apo_structure_id": apo_id,
                    "holo_structure_id": holo_id,
                    "apo_candidate_structure_ids": apo_ids,
                    "holo_candidate_structure_ids": holo_ids,
                    "num_apo_pdbids": int(entry.get("num_apo_pdbids", 0)),
                    "num_holo_pdbids": int(entry.get("num_holo_pdbids", 0)),
                    "target_resolution_angstrom": entry.get("target_resolution"),
                }
    return None


def _resource_proxy(metadata: Mapping[str, Any]) -> dict[str, Any]:
    info = metadata.get("rcsb_entry_info")
    info = info if isinstance(info, Mapping) else {}
    atom_count = _positive_int(info.get("deposited_atom_count"))
    status = (
        "review_required"
        if atom_count is None
        else (
            "likely_within_static_atom_cap"
            if atom_count <= SAFE_16GB.max_static_atoms
            else "likely_above_static_atom_cap"
        )
    )
    return {
        "profile": SAFE_16GB.name,
        "max_static_atoms": SAFE_16GB.max_static_atoms,
        "deposited_atom_count": atom_count,
        "status": status,
    }


def _release_date(metadata: Mapping[str, Any]) -> str | None:
    accessions = metadata.get("rcsb_accession_info")
    if not isinstance(accessions, Mapping):
        return None
    value = accessions.get("initial_release_date") or accessions.get("deposit_date")
    return str(value) if value else None


def audit_ahoj_catalog(
    *,
    query_summaries_path: Path = DEFAULT_QUERY_SUMMARIES,
    archive_path: Path = DEFAULT_ARCHIVE,
    output_path: Path = DEFAULT_OUTPUT,
    rcsb_cache_dir: Path = DEFAULT_RCSB_CACHE,
    allow_network: bool = False,
    max_queries: int = MAX_API_QUERIES,
) -> dict[str, Any]:
    if not allow_network:
        raise AhojCatalogError("AHoJ/RCSB metadata access requires --allow-network")
    if not 1 <= max_queries <= MAX_API_QUERIES:
        raise AhojCatalogError(f"max_queries must be between 1 and {MAX_API_QUERIES}")
    if not query_summaries_path.is_file() or not archive_path.is_file():
        raise AhojCatalogError("AHoJ subset snapshot/query summary is missing")
    prior_ids = _prior_structure_ids()
    candidates = load_query_candidates(query_summaries_path, prior_structure_ids=prior_ids)
    selected_queries = select_query_candidates(candidates, max_queries=max_queries)
    session = requests.Session()
    session.headers.update({"User-Agent": "BioVoid/0.1 geometry-data metadata preflight"})
    rcsb_cache_dir.mkdir(parents=True, exist_ok=True)
    pairs: list[dict[str, Any]] = []
    api_failures: list[dict[str, Any]] = []
    for candidate in selected_queries:
        try:
            payload = _request_json(
                session,
                AHOJ_API_URL,
                params={
                    "pdb_ids": candidate["query_structure_id"].lower(),
                    "ligands": candidate["query_ligand"],
                    "xray_only": "true",
                    "exclude_nmr": "true",
                },
            )
            entry = _first_entry(payload, candidate)
            pair = _pair_from_entry(entry, prior_structure_ids=prior_ids) if entry else None
            if pair is None:
                api_failures.append({**candidate, "reason": "no_independent_apo_holo_pair"})
                continue
            apo_meta = _rcsb_entry_metadata(
                session, pair["apo_structure_id"], cache_dir=rcsb_cache_dir
            )
            holo_meta = _rcsb_entry_metadata(
                session, pair["holo_structure_id"], cache_dir=rcsb_cache_dir
            )
            pairs.append(
                {
                    **candidate,
                    **pair,
                    "apo_release_date": _release_date(apo_meta),
                    "holo_release_date": _release_date(holo_meta),
                    "apo_resource_proxy": _resource_proxy(apo_meta),
                    "holo_resource_proxy": _resource_proxy(holo_meta),
                    "chain_mapping_status": "review_required_apo_holo_chain_ids_not_in_subset",
                    "sequence_cluster_status": "unresolved_metadata_only",
                    "label_status": "candidate_ahoj_biolip2_site_assignment_review_required",
                }
            )
        except (AhojCatalogError, OSError, ValueError, KeyError) as exc:
            api_failures.append({**candidate, "reason": type(exc).__name__})
    pairs.sort(
        key=lambda item: (
            item.get("apo_release_date") or "9999",
            item["uniprot_id"],
            item["query_ligand"],
            item["apo_structure_id"],
        )
    )
    safe_pairs = [
        item
        for item in pairs
        if item["apo_resource_proxy"]["status"] == "likely_within_static_atom_cap"
    ]
    safe_apo_structure_ids = {item["apo_structure_id"] for item in safe_pairs}
    safe_uniprot_ids = {item["uniprot_id"] for item in safe_pairs}
    release_known = sum(item.get("apo_release_date") is not None for item in safe_pairs)
    sequence_unresolved = sum(item["sequence_cluster_status"] != "resolved" for item in safe_pairs)
    chain_unresolved = sum(item["chain_mapping_status"] != "resolved" for item in safe_pairs)
    decision = (
        "PASS"
        if (
            len(safe_pairs) >= TARGET_CASES
            and release_known >= TARGET_CASES
            and sequence_unresolved == 0
            and chain_unresolved == 0
        )
        else "DIAGNOSTIC_ONLY"
        if safe_pairs
        else "NO_GO"
    )
    report: dict[str, Any] = {
        "schema_version": "biovoid-ahoj-geometry-source-catalog-v1",
        "status": "metadata_only_feasibility",
        "decision": decision,
        "source": {
            "source_id": SOURCE_ID,
            "version": SOURCE_VERSION,
            "url": SOURCE_URL,
            "archive_sha256": _sha256_file(archive_path),
            "query_summary_sha256": _sha256_file(query_summaries_path),
            "retrieved_at_utc": _utc_now(),
            "label_provenance": "AHoJ-DB precomputed BioLiP2 apo/holo site assignment",
        },
        "selection_policy": {
            "version": "ahoj_query_uniprot_round_robin_structure_v2",
            "query_rows_considered": len(candidates),
            "api_queries_attempted": len(selected_queries),
            "max_api_queries": max_queries,
            "prior_structure_exclusion_count": len(prior_ids),
            "coordinates_downloaded": False,
            "ligand_files_downloaded": False,
        },
        "capacity": {
            "candidate_pairs_returned": len(pairs),
            "resource_likely_safe_pairs": len(safe_pairs),
            "resource_likely_safe_unique_apo_structures": len(safe_apo_structure_ids),
            "resource_likely_safe_unique_uniprot_groups": len(safe_uniprot_ids),
            "target_case_capacity": TARGET_CASES,
            "release_date_known_safe_pairs": release_known,
            "chain_mapping_unresolved_safe_pairs": chain_unresolved,
            "sequence_cluster_unresolved_safe_pairs": sequence_unresolved,
            "api_failures": len(api_failures),
        },
        "pairs": pairs,
        "api_failures": api_failures,
        "boundary": {
            "metadata_only": True,
            "coordinates_downloaded": False,
            "detector_started": False,
            "evaluator_opened": False,
            "external_baseline_started": False,
            "motion_enabled": False,
            "ml_training_started": False,
        },
        "next_gate": (
            "resolve chain IDs and sequence clusters, exclude overlaps, then seal 6/2/2 split"
            if decision == "DIAGNOSTIC_ONLY"
            else "open a separately versioned source contract because capacity is insufficient"
        ),
        "created_at_utc": _utc_now(),
        "report_sha256": None,
    }
    report["report_sha256"] = _stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    _write_json(output_path, report)
    print(
        f"AHoJ geometry source catalog: decision={decision} "
        f"pairs={len(pairs)} safe={len(safe_pairs)} api_failures={len(api_failures)}"
    )
    print(f"catalog report: {output_path}")
    print("coordinates/ligands/detector/evaluator/NMA/ML: no")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query-summaries", type=Path, default=DEFAULT_QUERY_SUMMARIES)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--rcsb-cache", type=Path, default=DEFAULT_RCSB_CACHE)
    parser.add_argument("--max-queries", type=int, default=MAX_API_QUERIES)
    parser.add_argument("--allow-network", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        audit_ahoj_catalog(
            query_summaries_path=args.query_summaries,
            archive_path=args.archive,
            output_path=args.output,
            rcsb_cache_dir=args.rcsb_cache,
            allow_network=args.allow_network,
            max_queries=args.max_queries,
        )
    except (AhojCatalogError, OSError, ValueError) as exc:
        print(f"AHoJ geometry source catalog error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
