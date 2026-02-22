"""
Bio-Void Hunter: PDB Fetcher Module (v2)
==========================================

Downloads protein structures from RCSB PDB and AlphaFold DB
with intelligent caching, batch download, and retry logic.

Sources:
    - RCSB PDB: experimental structures (rcsb.org)
    - AlphaFold DB: predicted structures (alphafold.ebi.ac.uk)
"""

import logging
import time
from pathlib import Path
from typing import Optional

import requests
import biotite.database.rcsb as rcsb
import biotite.structure.io.pdb as pdb

logger = logging.getLogger(__name__)

ALPHAFOLD_API = "https://alphafold.ebi.ac.uk/files"


class FetchError(Exception):
    """Custom exception for fetch errors."""
    pass


def fetch_pdb(pdb_id: str, cache_dir: Optional[Path] = None,
              source: str = "rcsb") -> Path:
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
        raise FetchError(
            f"Invalid PDB ID: '{pdb_id}'. Must be 4 alphanumeric characters."
        )
    
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
            if candidate.suffix in ['.pdb', '.ent', '.cif']:
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
    """Fetch predicted structure from AlphaFold DB by UniProt ID."""
    uniprot_id = uniprot_id.upper()
    pdb_file = cache_dir / f"AF-{uniprot_id}.pdb"

    if pdb_file.exists():
        logger.info("AlphaFold cache hit: %s", pdb_file)
        return pdb_file.absolute()

    url = f"{ALPHAFOLD_API}/AF-{uniprot_id}-F1-model_v4.pdb"
    logger.info("Downloading AlphaFold model for %s...", uniprot_id)

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        pdb_file.write_bytes(resp.content)
        logger.info("AlphaFold model saved: %s", pdb_file)
        return pdb_file.absolute()
    except requests.HTTPError as e:
        raise FetchError(
            f"AlphaFold model not found for {uniprot_id}. "
            f"Check UniProt ID at https://www.uniprot.org/"
        ) from e
    except Exception as e:
        raise FetchError(f"AlphaFold download failed: {e}") from e


def batch_fetch(
    pdb_ids: list[str],
    cache_dir: Optional[Path] = None,
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
