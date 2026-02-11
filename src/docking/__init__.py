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
from .vina_wrapper import (
    # Constants
    GRID_BUFFER,
    GRID_MIN_SIZE,
    GRID_MAX_SIZE,
    DEFAULT_EXHAUSTIVENESS,
    DEFAULT_NUM_MODES,
    DEFAULT_ENERGY_RANGE,
    AFFINITY_STRONG,
    AFFINITY_GOOD,
    AFFINITY_WEAK,
    RMSD_EXCELLENT,
    RMSD_ACCEPTABLE,
    FRAGMENT_LIBRARY,
    # Data classes
    GridBox,
    DockingPose,
    DockingResult,
    # Exceptions
    DockingError,
    VinaNotFoundError,
    PDBQTError,
    # Engine
    VinaDocking,
    # Pipeline
    dock_elite_pockets,
    parse_vina_output_file,
)

# --- interactions.py ---
from .interactions import (
    HBOND_DISTANCE_MAX,
    HBOND_DISTANCE_MIN,
    VDW_DISTANCE_MAX,
    HBOND_DONORS,
    HBOND_ACCEPTORS,
    Interaction,
    InteractionReport,
    analyze_interactions,
)

# --- validation.py ---
from .validation import (
    RETINOIC_ACID_SMILES,
    CBS_KNOWN_CENTER,
    CBS_KNOWN_RADIUS,
    validate_known_ligand,
    dock_nma_frames,
)

__all__ = [
    # Constants
    'GRID_BUFFER', 'GRID_MIN_SIZE', 'GRID_MAX_SIZE',
    'DEFAULT_EXHAUSTIVENESS', 'DEFAULT_NUM_MODES', 'DEFAULT_ENERGY_RANGE',
    'AFFINITY_STRONG', 'AFFINITY_GOOD', 'AFFINITY_WEAK',
    'RMSD_EXCELLENT', 'RMSD_ACCEPTABLE',
    'FRAGMENT_LIBRARY',
    'HBOND_DISTANCE_MAX', 'HBOND_DISTANCE_MIN', 'VDW_DISTANCE_MAX',
    'HBOND_DONORS', 'HBOND_ACCEPTORS',
    'RETINOIC_ACID_SMILES', 'CBS_KNOWN_CENTER', 'CBS_KNOWN_RADIUS',
    # Data classes
    'GridBox', 'DockingPose', 'DockingResult',
    'Interaction', 'InteractionReport',
    # Exceptions
    'DockingError', 'VinaNotFoundError', 'PDBQTError',
    # Engine
    'VinaDocking',
    # Functions
    'dock_elite_pockets', 'parse_vina_output_file',
    'analyze_interactions',
    'validate_known_ligand', 'dock_nma_frames',
]
