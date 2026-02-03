"""
Bio-Void Hunter: Voronoi Geometric Scanner
===========================================

Production-grade void detection using Voronoi tessellation with ConvexHull filtering.
Eliminates "ghost void" errors from Phase 1.2 using Liang et al. (1998) algorithm.

Refactored from: scripts/test_voronoi.py (validated implementation)

Elite-Level Refinements:
- Heavy Atoms (C, N, O, S) as default
- ConvexHull filtering (buried voids only)
- Explicit Radius definition (min_dist to nearest atom)
- Floating-point tolerance (eps=1e-6)
- atom_type extensibility (future: backbone, polar, hydrophobic)

References:
- Liang et al. (1998) "Anatomy of protein pockets and cavities"
- Edelsbrunner & Mucke (1994) "Three-dimensional alpha shapes"
"""

import numpy as np
from scipy.spatial import Voronoi, ConvexHull, Delaunay
import biotite.structure.io.pdb as pdb
from pathlib import Path
from typing import List, Dict, Tuple
import time


# ============================================================================
# CONSTANTS (Elite-Level Refinements)
# ============================================================================

# Distance window for druggable pockets (Angstroms)
MIN_DISTANCE = 2.5  # Below this: inside atom (physically impossible)
MAX_DISTANCE = 8.0  # Above this: surface valley, not pocket

# Volume threshold for ligand binding
MIN_VOLUME = 200.0  # Å³ (minimum volume for small molecule binding)

# NOTE: ConvexHull filtering uses Delaunay.find_simplex (more stable)
# Floating-point tolerance not needed for this approach

# Heavy atom elements (bilimsel zorunluluk)
HEAVY_ATOMS = {'C', 'N', 'O', 'S'}


# ============================================================================
# 1. ATOM EXTRACTION (Elite++ Refinements)
# ============================================================================

def extract_atom_coords(pdb_file: str, atom_type: str = 'heavy') -> np.ndarray:
    """
    Extract atom coordinates from PDB file.
    
    Refactored from: test_voronoi.py:load_protein_atoms()
    
    Args:
        pdb_file: Path to PDB file
        atom_type: 'heavy' (C,N,O,S) or 'ca' (CA-only fast-mode)
    
    Returns:
        coords: Atom coordinates (N x 3)
    
    Elite++ Refinements:
    - Heavy atoms as default (bilimsel zorunluluk)
    - atom_type validation (enum-like)
    - NaN/Inf check
    - Bounding box validation (< 1000 Å)
    
    Raises:
        ValueError: Invalid atom_type, NaN/Inf coords, or invalid bounding box
    """
    # Elite++: atom_type validation (enum-like)
    if atom_type not in {'heavy', 'ca'}:
        raise ValueError(f"Invalid atom_type: '{atom_type}'. Must be 'heavy' or 'ca'.")
    
    # Load PDB structure
    pdb_path = Path(pdb_file)
    if not pdb_path.exists():
        raise FileNotFoundError(f"PDB file not found: {pdb_file}")
    
    pdb_obj = pdb.PDBFile.read(str(pdb_path))
    structure = pdb_obj.get_structure()[0]
    
    # Filter atoms based on type
    if atom_type == 'ca':
        # CA-only (fast-mode)
        atom_filter = (structure.atom_name == 'CA')
        atoms = structure[atom_filter]
    else:  # atom_type == 'heavy'
        # Heavy atoms (C, N, O, S) - bilimsel zorunluluk
        element_filter = np.isin(structure.element, list(HEAVY_ATOMS))
        atoms = structure[element_filter]
    
    coords = atoms.coord
    
    # Validation: Atom count
    if len(coords) < 50:
        raise ValueError(f"Too few atoms: {len(coords)} (minimum: 50)")
    if len(coords) > 100000:
        raise ValueError(f"Too many atoms: {len(coords)} (maximum: 100,000)")
    
    # Elite++: NaN/Inf check
    if np.any(np.isnan(coords)) or np.any(np.isinf(coords)):
        raise ValueError("Coordinates contain NaN or Inf values!")
    
    # Elite++: Bounding box validation (< 1000 Å)
    bbox_min = coords.min(axis=0)
    bbox_max = coords.max(axis=0)
    bbox_size = bbox_max - bbox_min
    
    if np.any(bbox_size > 1000.0):
        raise ValueError(f"Bounding box too large: {bbox_size} Å (max: 1000 Å)")
    
    return coords


# ============================================================================
# 2. VORONOI CALCULATION
# ============================================================================

def calculate_voronoi(coords: np.ndarray) -> Voronoi:
    """
    Calculate Voronoi diagram.
    
    Refactored from: test_voronoi.py:compute_voronoi()
    
    Args:
        coords: Atom coordinates (N x 3)
    
    Returns:
        vor: Scipy Voronoi object
    
    Raises:
        ValueError: Voronoi calculation failed
    """
    if len(coords) < 4:
        raise ValueError(f"Too few points for Voronoi: {len(coords)} (minimum: 4)")
    
    try:
        vor = Voronoi(coords)
    except Exception as e:
        raise ValueError(f"Voronoi calculation failed: {e}")
    
    # Validation
    if len(vor.vertices) == 0:
        raise ValueError("Voronoi diagram has no vertices!")
    if len(vor.regions) == 0:
        raise ValueError("Voronoi diagram has no regions!")
    
    return vor


# ============================================================================
# 3. SURFACE VOID FILTERING (FAZ 1.2 İNTİKAMI!)
# ============================================================================

def filter_surface_voids(voronoi: Voronoi, coords: np.ndarray) -> List[np.ndarray]:
    """
    Filter Voronoi vertices to keep only buried (internal) vertices.
    
    Refactored from: test_voronoi.py:point_in_hull() + find_voids()
    
    Args:
        voronoi: Voronoi diagram
        coords: Atom coordinates
    
    Returns:
        buried_vertices: List of vertices inside ConvexHull
    
    Method:
    - Uses Delaunay.find_simplex for point-in-hull check (stable)
    - Returns -1 if point is outside, >= 0 if inside
    - More robust than hull.equations approach
    
    FAZ 1.2 İNTİKAMI: This function eliminates ghost voids!
    """
    # Build ConvexHull (protein surface)
    try:
        hull = ConvexHull(coords)
    except Exception as e:
        raise ValueError(f"ConvexHull construction failed: {e}")
    
    # Use Delaunay triangulation for point-in-hull check
    # (Refactored from test_voronoi.py:point_in_hull)
    try:
        delaunay = Delaunay(coords)
    except Exception as e:
        raise ValueError(f"Delaunay triangulation failed: {e}")
    
    buried_vertices = []
    
    for vertex in voronoi.vertices:
        # Check if vertex is inside ConvexHull
        # Delaunay.find_simplex returns -1 if point is outside
        simplex_index = delaunay.find_simplex(vertex)
        
        if simplex_index >= 0:
            # Vertex is inside ConvexHull (buried)
            buried_vertices.append(vertex)
    
    return buried_vertices


# ============================================================================
# 4. VOID PROPERTIES CALCULATION
# ============================================================================

def calculate_vertex_void_properties(vertex: np.ndarray, coords: np.ndarray) -> Dict:
    """
    Calculate void properties for a single Voronoi vertex.
    
    IMPORTANT: Properties are calculated per Voronoi vertex (maximal inscribed sphere),
    NOT per merged cavity. Cavity merging will be implemented in Phase 2.4+.
    
    Extracted from: test_voronoi.py:find_voids()
    
    Args:
        vertex: Voronoi vertex (void center)
        coords: Atom coordinates
    
    Returns:
        properties: {'center', 'radius', 'volume'}
    
    Method:
    - Radius: min_dist(center → nearest_atom) - Explicit definition for Phase 3 docking
    - Volume: (4/3) * π * radius³ (spherical approximation)
    - Center: Vertex position (weighted centroid optional for future)
    
    Note: True Voronoi region volume (ConvexHull-based) will be added in Phase 2.4
    when implementing cavity merging and clustering.
    """
    # Calculate distances to all atoms
    distances = np.linalg.norm(coords - vertex, axis=1)
    min_dist = np.min(distances)
    
    # Radius: min distance to nearest atom (Elite refinement)
    radius = min_dist
    
    # Volume: Sphere approximation (from test_voronoi.py)
    volume = (4.0 / 3.0) * np.pi * (radius ** 3)
    
    # Center: Vertex position (simple mean, weighted centroid opsiyonel)
    center = vertex
    
    return {
        'center': center,
        'radius': radius,
        'volume': volume
    }


# ============================================================================
# 5. MAIN API
# ============================================================================

def find_voids(pdb_file: str, min_volume: float = MIN_VOLUME,
               atom_type: str = 'heavy') -> List[Dict]:
    """
    Main API: Find voids in protein structure.
    
    Refactored from: test_voronoi.py:find_voids() (main logic)
    
    Args:
        pdb_file: Path to PDB file
        min_volume: Minimum void volume (Å³)
        atom_type: 'heavy' or 'ca'
    
    Returns:
        voids: List of void dicts, sorted by volume (descending)
    
    Pipeline:
    1. extract_atom_coords()
    2. calculate_voronoi()
    3. filter_surface_voids() - ConvexHull
    4. For each buried vertex:
       - Check distance window (2.5-8.0 Å)
       - calculate_void_properties()
       - Filter by min_volume
    5. Sort by volume (descending)
    
    Elite-Level Refinements:
    - Heavy Atoms default
    - ConvexHull filtering (ghost void elimination)
    - Distance window (2.5-8.0 Å)
    - Volume filter (> min_volume)
    """
    # 1. Extract atom coordinates
    coords = extract_atom_coords(pdb_file, atom_type=atom_type)
    
    # 2. Calculate Voronoi diagram
    vor = calculate_voronoi(coords)
    
    # 3. Filter surface voids (ConvexHull)
    buried_vertices = filter_surface_voids(vor, coords)
    
    # 4. Calculate void properties and filter
    voids = []
    
    for vertex in buried_vertices:
        # Calculate distances to all atoms
        distances = np.linalg.norm(coords - vertex, axis=1)
        min_dist = np.min(distances)
        
        # Distance window filter (2.5-8.0 Å)
        if not (MIN_DISTANCE <= min_dist <= MAX_DISTANCE):
            continue
        
        # Calculate void properties
        void_props = calculate_vertex_void_properties(vertex, coords)
        
        # Volume filter
        if void_props['volume'] < min_volume:
            continue
        
        voids.append(void_props)
    
    # 5. Sort by volume (descending)
    voids = sorted(voids, key=lambda x: x['volume'], reverse=True)
    
    return voids
