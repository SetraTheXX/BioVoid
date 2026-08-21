"""
Bio-Void Hunter: PDB Fetcher Module (v2)
==========================================

Downloads protein structures from RCSB PDB and AlphaFold DB
with intelligent caching, batch download, and retry logic.

Sources:
    - RCSB PDB: experimental structures (rcsb.org)
    - AlphaFold DB: predicted structures (alphafold.ebi.ac.uk)
"""

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import biotite.database.rcsb as rcsb
import biotite.structure.io.pdb as pdb
import requests

logger = logging.getLogger(__name__)

ALPHAFOLD_PREDICTION_API = "https://alphafold.com/api/prediction"
RCSB_FILES_BASE = "https://files.rcsb.org/download"
RCSB_DATA_API = "https://data.rcsb.org/rest/v1/core"


class FetchError(Exception):
    """Custom exception for fetch errors."""

    pass


@dataclass(frozen=True)
class FetchedStructure:
    """Raw structure and source metadata fetched before preparation."""

    path: Path
    metadata: dict[str, Any]


def fetch_pdb(pdb_id: str, cache_dir: Path | None = None, source: str = "rcsb") -> Path:
    """
    Download PDB file with caching.

    Args:
        pdb_id: PDB identifier (e.g., '1cbs') or UniProt ID for AlphaFold
        cache_dir: Directory to store downloaded files
        source: 'rcsb' (default) or 'alphafold'

    Returns:
        Path to the downloaded PDB file
    """
    if cache_dir is None:
        project_root = Path(__file__).parent.parent
        cache_dir = project_root / "data" / "raw_pdb"

    cache_dir.mkdir(parents=True, exist_ok=True)
    pdb_id = pdb_id.strip()

    if source == "alphafold":
        return _fetch_alphafold(pdb_id, cache_dir)
    return _fetch_rcsb(pdb_id.lower(), cache_dir)


def _fetch_rcsb(pdb_id: str, cache_dir: Path) -> Path:
    """Fetch from RCSB PDB."""
    if len(pdb_id) != 4 or not pdb_id.isalnum():
        raise FetchError(f"Invalid PDB ID: '{pdb_id}'. Must be 4 alphanumeric characters.")

    pdb_file = cache_dir / f"{pdb_id}.pdb"

    if pdb_file.exists():
        try:
            pdb_file_obj = pdb.PDBFile.read(str(pdb_file))
            structure = pdb_file_obj.get_structure()
            if len(structure) == 0:
                raise ValueError("Empty structure")
            logger.info("Cache hit: %s", pdb_file)
            return pdb_file.absolute()
        except Exception as e:
            logger.warning("Cached file corrupted, re-downloading: %s", e)
            pdb_file.unlink()

    logger.info("Downloading %s from RCSB PDB...", pdb_id.upper())
    start_time = time.time()

    try:
        rcsb.fetch(pdb_id, "pdb", target_path=str(cache_dir))

        actual_file = None
        for candidate in cache_dir.glob(f"*{pdb_id}*"):
            if candidate.suffix in [".pdb", ".ent", ".cif"]:
                actual_file = candidate
                break

        if actual_file is None:
            raise FetchError(f"Downloaded file not found in {cache_dir}")

        if actual_file != pdb_file:
            actual_file.rename(pdb_file)

        elapsed = time.time() - start_time
        logger.info("Downloaded %s in %.2fs", pdb_id.upper(), elapsed)
        return pdb_file.absolute()

    except Exception as e:
        raise FetchError(f"Failed to download {pdb_id.upper()}: {e}") from e


def _fetch_alphafold(uniprot_id: str, cache_dir: Path) -> Path:
    """Fetch the current AlphaFold model URL through the prediction API."""
    from src.structure_preparation import StructureSource

    fetched = fetch_structure_input(
        StructureSource(
            provider="alphafold",
            identifier=uniprot_id,
            representation="predicted_model",
        ),
        cache_dir=cache_dir,
    )
    return fetched.path


def _request_json(url: str) -> Any:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def _request_bytes(url: str) -> bytes:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    if not response.content:
        raise FetchError(f"Empty structure response from {url}")
    return response.content


def fetch_structure_input(source, cache_dir: Path | None = None) -> FetchedStructure:
    """Fetch the exact representation declared by a StructureSource."""
    from src.structure_preparation import StructureSource

    if not isinstance(source, StructureSource):
        raise TypeError("source must be a StructureSource")
    if cache_dir is None:
        cache_dir = Path(__file__).resolve().parent.parent / "data" / "raw_pdb"
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    if source.provider == "local":
        local_path = source.local_path
        if local_path is None:
            raise FetchError("Local source is missing local_path")
        path = local_path.resolve()
        if not path.is_file():
            raise FetchError(f"Local structure not found: {path}")
        return FetchedStructure(path=path, metadata={"provider": "local"})

    if source.provider == "rcsb":
        pdb_id = source.identifier.lower()
        if source.representation == "biological_assembly":
            filename = f"{pdb_id}-assembly{source.assembly_id}.cif"
            metadata_url = f"{RCSB_DATA_API}/assembly/{source.identifier}/{source.assembly_id}"
        else:
            filename = f"{pdb_id}.cif"
            metadata_url = f"{RCSB_DATA_API}/entry/{source.identifier}"
        path = cache_dir / filename
        metadata_path = cache_dir / f"{filename}.metadata.json"
        try:
            if metadata_path.is_file():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            else:
                metadata = _request_json(metadata_url)
                metadata_path.write_text(
                    json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            if not path.is_file():
                path.write_bytes(_request_bytes(f"{RCSB_FILES_BASE}/{filename}"))
        except Exception as exc:
            raise FetchError(
                f"Failed to fetch RCSB {source.representation} for {source.identifier}: {exc}"
            ) from exc
        return FetchedStructure(path=path.resolve(), metadata=metadata)

    accession = source.identifier.upper()
    metadata_url = f"{ALPHAFOLD_PREDICTION_API}/{accession}"
    try:
        records = _request_json(metadata_url)
        if not isinstance(records, list) or not records:
            raise FetchError(f"AlphaFold model not found for {accession}")
        selected = None
        if source.model_entity_id:
            selected = next(
                (
                    record
                    for record in records
                    if record.get("modelEntityId") == source.model_entity_id
                ),
                None,
            )
            if selected is None:
                raise FetchError(
                    f"AlphaFold model entity {source.model_entity_id} was not returned"
                )
        else:
            canonical_entity_id = f"AF-{accession}-F1"
            selected = next(
                (
                    record
                    for record in records
                    if record.get("modelEntityId") == canonical_entity_id
                ),
                None,
            )
            if selected is None:
                matching_accession = [
                    record
                    for record in records
                    if str(record.get("uniprotAccession") or "").upper() == accession
                ]
                selected = sorted(
                    matching_accession or records,
                    key=lambda record: (
                        int(record.get("sequenceStart") or 1),
                        str(record.get("modelEntityId") or ""),
                    ),
                )[0]
        pdb_url = selected.get("pdbUrl")
        if not pdb_url:
            raise FetchError("AlphaFold API response does not include pdbUrl")
        path = cache_dir / f"AF-{accession}.pdb"
        metadata_path = cache_dir / f"AF-{accession}.metadata.json"
        cached_metadata = None
        if metadata_path.is_file():
            try:
                cached_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cached_metadata = None
        if not path.is_file() or (cached_metadata or {}).get("pdb_url") != pdb_url:
            path.write_bytes(_request_bytes(str(pdb_url)))
    except Exception as exc:
        if isinstance(exc, FetchError):
            raise
        raise FetchError(f"AlphaFold download failed for {accession}: {exc}") from exc

    sequence_start = selected.get("sequenceStart")
    sequence_end = selected.get("sequenceEnd")
    full_sequence = selected.get("uniprotSequence") or ""
    fragmented_model = bool(
        (sequence_start is not None and int(sequence_start) != 1)
        or (full_sequence and sequence_end is not None and int(sequence_end) < len(full_sequence))
    )
    metadata = {
        "provider": "alphafold",
        "model_entity_id": selected.get("modelEntityId"),
        "latest_version": selected.get("latestVersion"),
        "global_metric_value": selected.get("globalMetricValue"),
        "plddt_url": selected.get("plddtDocUrl"),
        "pae_url": selected.get("paeDocUrl"),
        "cif_url": selected.get("cifUrl"),
        "bcif_url": selected.get("bcifUrl"),
        "sequence_start": sequence_start,
        "sequence_end": sequence_end,
        "fragmented_model": fragmented_model,
        "available_model_entities": [
            record.get("modelEntityId") for record in records if record.get("modelEntityId")
        ],
        "pdb_url": pdb_url,
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return FetchedStructure(path=path.resolve(), metadata=metadata)


def batch_fetch(
    pdb_ids: list[str],
    cache_dir: Path | None = None,
    source: str = "rcsb",
    max_retries: int = 2,
) -> dict[str, Path | str]:
    """
    Download multiple structures with retry logic.

    Returns dict mapping pdb_id -> Path (success) or error string (failure).
    """
    results: dict[str, Path | str] = {}

    for pdb_id in pdb_ids:
        for attempt in range(1, max_retries + 2):
            try:
                path = fetch_pdb(pdb_id, cache_dir=cache_dir, source=source)
                results[pdb_id] = path
                break
            except FetchError as e:
                if attempt > max_retries:
                    logger.error("Failed after %d attempts: %s", max_retries + 1, pdb_id)
                    results[pdb_id] = str(e)
                else:
                    logger.warning("Retry %d/%d for %s", attempt, max_retries, pdb_id)
                    time.sleep(1.0 * attempt)

    succeeded = sum(1 for v in results.values() if isinstance(v, Path))
    logger.info("Batch fetch complete: %d/%d succeeded", succeeded, len(pdb_ids))
    return results


def get_structure(pdb_file: Path):
    """
    Load PDB structure from file.

    Args:
        pdb_file: Path to PDB file

    Returns:
        biotite.structure.AtomArray: Protein structure
    """
    pdb_file_obj = pdb.PDBFile.read(str(pdb_file))
    structure = pdb_file_obj.get_structure()[0]  # First model
    return structure


def get_ca_atoms(structure):
    """
    Extract CA (alpha carbon) atoms from structure.

    Args:
        structure: biotite.structure.AtomArray

    Returns:
        biotite.structure.AtomArray: CA atoms only
    """
    ca_atoms = structure[structure.atom_name == "CA"]
    return ca_atoms
