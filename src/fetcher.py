"""
Bio-Void Hunter: PDB Fetcher Module
====================================
Downloads protein structures from RCSB PDB database with intelligent caching.

Refactored from: scripts/phase1_integration_test.py (download_protein function)
"""

import time
from pathlib import Path
from typing import Optional
import biotite.database.rcsb as rcsb
import biotite.structure.io.pdb as pdb


class FetchError(Exception):
    """Custom exception for fetch errors"""
    pass


def fetch_pdb(pdb_id: str, cache_dir: Optional[Path] = None) -> Path:
    """
    Download PDB file from RCSB database with caching.
    
    Args:
        pdb_id: PDB identifier (e.g., '1cbs', '1ake')
        cache_dir: Directory to store downloaded files (default: data/raw_pdb/)
    
    Returns:
        Path: Absolute path to the downloaded PDB file
    
    Raises:
        FetchError: If download fails or PDB ID is invalid
    
    Examples:
        >>> filepath = fetch_pdb('1cbs')
        >>> print(filepath)
        c:/Users/tunca/Desktop/Proje/BioVoid/data/raw_pdb/1cbs.pdb
    """
    # Setup cache directory
    if cache_dir is None:
        project_root = Path(__file__).parent.parent
        cache_dir = project_root / "data" / "raw_pdb"
    
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    # Normalize PDB ID (lowercase)
    pdb_id = pdb_id.lower().strip()
    
    # Validate PDB ID format (4 characters)
    if len(pdb_id) != 4 or not pdb_id.isalnum():
        raise FetchError(
            f"Invalid PDB ID: '{pdb_id}'. "
            f"PDB IDs must be exactly 4 alphanumeric characters (e.g., '1cbs', '1ake')"
        )
    
    # Check cache
    pdb_file = cache_dir / f"{pdb_id}.pdb"
    
    if pdb_file.exists():
        # Verify file is valid PDB format
        try:
            pdb_file_obj = pdb.PDBFile.read(str(pdb_file))
            structure = pdb_file_obj.get_structure()
            if len(structure) == 0:
                raise ValueError("Empty structure")
            print(f"✅ Cache hit: {pdb_file}")
            return pdb_file.absolute()
        except Exception as e:
            print(f"⚠️ Cached file corrupted, re-downloading: {e}")
            pdb_file.unlink()  # Delete corrupted file
    
    # Download from RCSB
    print(f"📥 Downloading {pdb_id.upper()} from RCSB PDB...")
    start_time = time.time()
    
    try:
        file_path = rcsb.fetch(pdb_id, "pdb", target_path=str(cache_dir))
        download_time = time.time() - start_time
        
        # Verify download
        if not Path(file_path).exists():
            raise FetchError(f"Download failed: file not found at {file_path}")
        
        # Biotite might save with different naming, find the actual file
        actual_file = None
        for candidate in cache_dir.glob(f"*{pdb_id}*"):
            if candidate.suffix in ['.pdb', '.ent', '.cif']:
                actual_file = candidate
                break
        
        if actual_file is None:
            raise FetchError(f"Downloaded file not found in {cache_dir}")
        
        # Rename to standard format if needed
        if actual_file != pdb_file:
            actual_file.rename(pdb_file)
        
        print(f"✅ Downloaded in {download_time:.2f}s: {pdb_file}")
        return pdb_file.absolute()
    
    except Exception as e:
        error_msg = f"Failed to download PDB {pdb_id.upper()}: {str(e)}"
        
        # Provide helpful error messages
        if "404" in str(e) or "not found" in str(e).lower():
            error_msg += f"\n💡 Tip: PDB ID '{pdb_id.upper()}' may not exist. Check https://www.rcsb.org/"
        elif "network" in str(e).lower() or "connection" in str(e).lower():
            error_msg += "\n💡 Tip: Check your internet connection or try again later."
        
        raise FetchError(error_msg) from e


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
