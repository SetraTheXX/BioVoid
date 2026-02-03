"""
Bio-Void Hunter: Core Modules
==============================
"""

__version__ = "0.2.0"  # Phase 2: Core Engine
__author__ = "Bio-Void Hunter Team"

# Fetcher module
from .fetcher import fetch_pdb, get_structure, get_ca_atoms, FetchError

# Dynamics module (NMA Engine)
from .dynamics import (
    run_nma_simulation,
    build_anm_hessian,
    calculate_normal_modes,
    generate_conformations,
    load_ca_atoms,
    save_frames_as_pdb,
    validate_hessian,
    validate_eigenvalues,
    validate_trivial_modes,
    DEFAULT_CUTOFF,
    DEFAULT_GAMMA,
)

__all__ = [
    # Fetcher
    "fetch_pdb",
    "get_structure", 
    "get_ca_atoms",
    "FetchError",
    # Dynamics
    "run_nma_simulation",
    "build_anm_hessian",
    "calculate_normal_modes",
    "generate_conformations",
    "load_ca_atoms",
    "save_frames_as_pdb",
    "validate_hessian",
    "validate_eigenvalues",
    "validate_trivial_modes",
    "DEFAULT_CUTOFF",
    "DEFAULT_GAMMA",
]
