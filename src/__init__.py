"""
Bio-Void Hunter: Core Modules
==============================
"""

__version__ = "0.2.0"  # Phase 2: Core Engine
__author__ = "Bio-Void Hunter Team"

from .fetcher import fetch_pdb, get_structure, get_ca_atoms, FetchError

__all__ = [
    "fetch_pdb",
    "get_structure", 
    "get_ca_atoms",
    "FetchError",
]
