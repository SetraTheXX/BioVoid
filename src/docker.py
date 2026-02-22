"""
DEPRECATED: This file has been refactored into src/docking/ package.

All functionality is now in:
    - src/docking/vina_wrapper.py
    - src/docking/interactions.py
    - src/docking/validation.py

Import from src.docking instead:
    from src.docking import VinaDocking, dock_elite_pockets, DockingError
"""

raise ImportError(
    "docker.py is deprecated. Use 'from src.docking import ...' instead. "
    "See src/docking/__init__.py for available exports."
)
