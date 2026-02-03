"""
Bio-Void Hunter: Core Modules
==============================
"""

__version__ = "0.3.0"  # Phase 2: Core Engine + Geometry
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

# Geometry module (Voronoi Scanner)
from .geometry import (
    find_voids,
    extract_atom_coords,
    calculate_voronoi,
    filter_surface_voids,
    calculate_void_properties,
    MIN_DISTANCE,
    MAX_DISTANCE,
    MIN_VOLUME,
    HULL_EPS,
    HEAVY_ATOMS,
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
    # Geometry
    "find_voids",
    "extract_atom_coords",
    "calculate_voronoi",
    "filter_surface_voids",
    "calculate_void_properties",
    "MIN_DISTANCE",
    "MAX_DISTANCE",
    "MIN_VOLUME",
    "HULL_EPS",
    "HEAVY_ATOMS",
]
