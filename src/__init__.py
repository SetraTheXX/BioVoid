"""
Bio-Void Hunter: Core Modules
==============================
"""

__version__ = "0.9.0"  # Phase 5.3: Discovery Dashboard
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

# Scoring module (Druggability Scoring - Phase 3)
from .scoring import (
    rank_pockets,
    score_all_cavities,
    calculate_bio_score,
    calculate_enclosure,
    calculate_depth,
    normalize_volume,
    normalize_hydrophobicity,
    get_profile,
    get_elite_pockets,
    ScoringProfile,
    EnzymeProfile,
    PPIProfile,
    GPCRProfile,
    DefaultProfile,
    PROFILES,
    DRUGGABILITY_HIGH,
    DRUGGABILITY_MEDIUM,
)

# Docker module (Targeted Docking - Phase 4) — refactored into src/docking/
from .docking import (
    VinaDocking,
    GridBox,
    DockingPose,
    DockingResult,
    DockingError,
    VinaNotFoundError,
    PDBQTError,
    Interaction,
    InteractionReport,
    dock_elite_pockets,
    parse_vina_output_file,
    analyze_interactions,
    validate_known_ligand,
    dock_nma_frames,
    FRAGMENT_LIBRARY,
    GRID_BUFFER,
    GRID_MIN_SIZE,
    GRID_MAX_SIZE,
    AFFINITY_STRONG,
    AFFINITY_GOOD,
    AFFINITY_WEAK,
    HBOND_DISTANCE_MAX,
    HBOND_DISTANCE_MIN,
    VDW_DISTANCE_MAX,
    RETINOIC_ACID_SMILES,
)

# Parallel Crawler module (Phase 5.1)
from .parallel_crawler import (
    ParallelCrawler,
    CheckpointManager,
    CrawlerState,
    CrawlerLogger,
    _analyze_single_protein,
    DEFAULT_MAX_WORKERS,
    DEFAULT_DOWNLOAD_WORKERS,
    DEFAULT_TIMEOUT,
    CHECKPOINT_INTERVAL,
    BATCH_SIZE,
)

# Database module (Cryptic Pocket Atlas - Phase 5.2)
from .database import (
    AtlasDB,
    ProteinRecord,
    PocketRecord,
    DockingRecord,
    DB_VERSION,
    DEFAULT_DB_PATH,
    DEFAULT_BATCH_SIZE,
)

# Dashboard module (Discovery Dashboard - Phase 5.3)
# Lazy import: streamlit dependency may not be available in CLI contexts
try:
    from .dashboard import (
        load_statistics,
        load_pocket_dataframe,
        load_elite_dataframe,
        load_protein_list,
        build_kpi_cards,
        build_score_histogram,
        build_volume_scatter,
        build_class_pie,
        build_3d_pocket_view,
        build_top_proteins_bar,
        dataframe_to_csv,
        APP_TITLE,
        PAGE_SIZE,
        DEFAULT_DB,
    )
except ImportError:
    pass  # Dashboard not available without streamlit

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
    # Scoring (Phase 3)
    "rank_pockets",
    "score_all_cavities",
    "calculate_bio_score",
    "calculate_enclosure",
    "calculate_depth",
    "normalize_volume",
    "normalize_hydrophobicity",
    "get_profile",
    "get_elite_pockets",
    "ScoringProfile",
    "EnzymeProfile",
    "PPIProfile",
    "GPCRProfile",
    "DefaultProfile",
    "PROFILES",
    "DRUGGABILITY_HIGH",
    "DRUGGABILITY_MEDIUM",
    # Docker (Phase 4)
    "VinaDocking",
    "GridBox",
    "DockingPose",
    "DockingResult",
    "DockingError",
    "VinaNotFoundError",
    "PDBQTError",
    "Interaction",
    "InteractionReport",
    "dock_elite_pockets",
    "parse_vina_output_file",
    "analyze_interactions",
    "validate_known_ligand",
    "dock_nma_frames",
    "FRAGMENT_LIBRARY",
    "GRID_BUFFER",
    "GRID_MIN_SIZE",
    "GRID_MAX_SIZE",
    "AFFINITY_STRONG",
    "AFFINITY_GOOD",
    "AFFINITY_WEAK",
    "HBOND_DISTANCE_MAX",
    "HBOND_DISTANCE_MIN",
    "VDW_DISTANCE_MAX",
    "RETINOIC_ACID_SMILES",
    # Parallel Crawler (Phase 5.1)
    "ParallelCrawler",
    "CheckpointManager",
    "CrawlerState",
    "CrawlerLogger",
    "_analyze_single_protein",
    "DEFAULT_MAX_WORKERS",
    "DEFAULT_DOWNLOAD_WORKERS",
    "DEFAULT_TIMEOUT",
    "CHECKPOINT_INTERVAL",
    "BATCH_SIZE",
    # Database (Phase 5.2)
    "AtlasDB",
    "ProteinRecord",
    "PocketRecord",
    "DockingRecord",
    "DB_VERSION",
    "DEFAULT_DB_PATH",
    "DEFAULT_BATCH_SIZE",
    # Dashboard (Phase 5.3)
    "load_statistics",
    "load_pocket_dataframe",
    "load_elite_dataframe",
    "load_protein_list",
    "build_kpi_cards",
    "build_score_histogram",
    "build_volume_scatter",
    "build_class_pie",
    "build_3d_pocket_view",
    "build_top_proteins_bar",
    "dataframe_to_csv",
    "APP_TITLE",
    "PAGE_SIZE",
    "DEFAULT_DB",
]
