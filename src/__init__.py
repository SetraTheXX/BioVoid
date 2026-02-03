"""
Bio-Void Hunter: Core Modules
==============================
"""

__version__ = "0.4.0"  # Phase 2.4: Cavity Analysis Engine
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

# Geometry module (Voronoi Scanner - Phase 2.3)
from .geometry import (
    find_voids,
    extract_atom_coords,
    calculate_voronoi,
    filter_surface_voids,
    calculate_vertex_void_properties,
    MIN_DISTANCE,
    MAX_DISTANCE,
    MIN_VOLUME,
    HEAVY_ATOMS,
)

# Cavities module (Cavity Analysis - Phase 2.4)
from .cavities import (
    find_cavities,
    merge_cavities,
    calculate_cavity_properties,
    filter_hydrophobic,
    calculate_region_volume,
    MERGE_THRESHOLD,
    HYDROPHOBIC_RESIDUES,
    POLAR_THRESHOLD,
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
    # Geometry (Phase 2.3)
    "find_voids",
    "extract_atom_coords",
    "calculate_voronoi",
    "filter_surface_voids",
    "calculate_vertex_void_properties",
    "MIN_DISTANCE",
    "MAX_DISTANCE",
    "MIN_VOLUME",
    "HEAVY_ATOMS",
    # Cavities (Phase 2.4)
    "find_cavities",
    "merge_cavities",
    "calculate_cavity_properties",
    "filter_hydrophobic",
    "calculate_region_volume",
    "MERGE_THRESHOLD",
    "HYDROPHOBIC_RESIDUES",
    "POLAR_THRESHOLD",
]
