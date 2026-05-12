"""
Bio-Void Hunter: Docking Package
==================================

Refactored from monolithic docker.py into modular sub-package.

Modules:
    vina_wrapper:  VinaDocking engine, GridBox, DockingResult, constants
    interactions:  Protein-ligand interaction analysis
    validation:    Known ligand validation + NMA frame docking

Backward-compatible: all original public names are re-exported here.
"""

# --- vina_wrapper.py ---
# --- interactions.py ---
from .interactions import (
    HBOND_ACCEPTORS,
    HBOND_DISTANCE_MAX,
    HBOND_DISTANCE_MIN,
    HBOND_DONORS,
    VDW_DISTANCE_MAX,
    Interaction,
    InteractionReport,
    analyze_interactions,
)

# --- validation.py ---
from .validation import (
    CBS_KNOWN_CENTER,
    CBS_KNOWN_RADIUS,
    RETINOIC_ACID_SMILES,
    dock_nma_frames,
    validate_known_ligand,
)
from .vina_wrapper import (
    AFFINITY_GOOD,
    AFFINITY_STRONG,
    AFFINITY_WEAK,
    DEFAULT_ENERGY_RANGE,
    DEFAULT_EXHAUSTIVENESS,
    DEFAULT_NUM_MODES,
    FRAGMENT_LIBRARY,
    # Constants
    GRID_BUFFER,
    GRID_MAX_SIZE,
    GRID_MIN_SIZE,
    RMSD_ACCEPTABLE,
    RMSD_EXCELLENT,
    # Exceptions
    DockingError,
    DockingPose,
    DockingResult,
    # Data classes
    GridBox,
    PDBQTError,
    # Engine
    VinaDocking,
    VinaNotFoundError,
    # Pipeline
    dock_elite_pockets,
    parse_vina_output_file,
)

__all__ = [
    # Constants
    "GRID_BUFFER",
    "GRID_MIN_SIZE",
    "GRID_MAX_SIZE",
    "DEFAULT_EXHAUSTIVENESS",
    "DEFAULT_NUM_MODES",
    "DEFAULT_ENERGY_RANGE",
    "AFFINITY_STRONG",
    "AFFINITY_GOOD",
    "AFFINITY_WEAK",
    "RMSD_EXCELLENT",
    "RMSD_ACCEPTABLE",
    "FRAGMENT_LIBRARY",
    "HBOND_DISTANCE_MAX",
    "HBOND_DISTANCE_MIN",
    "VDW_DISTANCE_MAX",
    "HBOND_DONORS",
    "HBOND_ACCEPTORS",
    "RETINOIC_ACID_SMILES",
    "CBS_KNOWN_CENTER",
    "CBS_KNOWN_RADIUS",
    # Data classes
    "GridBox",
    "DockingPose",
    "DockingResult",
    "Interaction",
    "InteractionReport",
    # Exceptions
    "DockingError",
    "VinaNotFoundError",
    "PDBQTError",
    # Engine
    "VinaDocking",
    # Functions
    "dock_elite_pockets",
    "parse_vina_output_file",
    "analyze_interactions",
    "validate_known_ligand",
    "dock_nma_frames",
]
