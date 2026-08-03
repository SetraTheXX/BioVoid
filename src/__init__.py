"""
BioVoid: Local Protein Pocket Analysis Prototype
================================================

Submodules:
    fetcher     - PDB structure fetching
    dynamics    - NMA simulation engine
    geometry    - Voronoi void scanning
    cavities    - Cavity merging & hydrophobic filtering
    scoring     - Heuristic pocket measurements & ranking
    docking     - AutoDock Vina wrapper
    multiframe  - Multi-frame consensus analysis
    parallel_crawler - Parallel protein scanning
    database    - Atlas persistence helpers (SQLite)
    dashboard   - Legacy Streamlit dashboard
    visualizer  - 3D visualization & PyMOL scripts
    frame_reconstruction - All-atom frame rebuilding

Usage:
    from src.fetcher import fetch_pdb
    from src.dynamics import run_nma_simulation
    from src.scoring import rank_pockets
"""

from .version import __version__

__author__ = "Bio-Void Hunter Team"

_SUBMODULES = [
    "fetcher",
    "dynamics",
    "geometry",
    "cavities",
    "scoring",
    "docking",
    "multiframe",
    "motion_ensemble",
    "atlas_v1",
    "parallel_crawler",
    "database",
    "dashboard",
    "visualizer",
    "frame_reconstruction",
    "benchmark",
    "benchmark_v1",
    "cryptobench_adapter",
    "comparison",
    "evaluator_format",
    "geometry_benchmark",
    "ground_truth_alignment",
    "static_detector",
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
