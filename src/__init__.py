"""
Bio-Void Hunter: Cryptic Pocket Discovery Pipeline
====================================================

Submodules:
    fetcher     - PDB structure fetching
    dynamics    - NMA simulation engine
    geometry    - Voronoi void scanning
    cavities    - Cavity merging & hydrophobic filtering
    scoring     - Druggability scoring & ranking
    docking     - AutoDock Vina wrapper
    multiframe  - Multi-frame consensus analysis
    parallel_crawler - Parallel protein scanning
    database    - Cryptic Pocket Atlas (SQLite)
    dashboard   - Streamlit discovery dashboard (legacy)
    visualizer  - 3D visualization & PyMOL scripts
    frame_reconstruction - All-atom frame rebuilding

Usage:
    from src.fetcher import fetch_pdb
    from src.dynamics import run_nma_simulation
    from src.scoring import rank_pockets
"""

__version__ = "1.0.0"
__author__ = "Bio-Void Hunter Team"

_SUBMODULES = [
    "fetcher",
    "dynamics",
    "geometry",
    "cavities",
    "scoring",
    "docking",
    "multiframe",
    "parallel_crawler",
    "database",
    "dashboard",
    "visualizer",
    "frame_reconstruction",
    "benchmark",
    "comparison",
    "config",
    "profiling",
    "cache",
    "cli",
    "ml",
    "api",
]


def __getattr__(name: str):
    if name in _SUBMODULES:
        import importlib

        return importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
