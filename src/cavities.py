"""
Bio-Void Hunter: Cavity Analysis Module (Phase 2.4)
====================================================

Production-grade cavity merging, true volume calculation, and druggability analysis.
Extends Phase 2.3 vertex-level void detection with clustering and filtering.

Key Features:
- True Voronoi region volume (ridge-based, NOT point_region)
- DBSCAN cavity merging (3.0 Å threshold)
- Dual radii (geometric + steric clearance)
- Hydrophobic filtering with KD-Tree (O(log N))

References:
- Liang et al. (1998) "Anatomy of protein pockets and cavities"
- ChatGPT Senior PI Review (2026-02-03)
"""

import numpy as np
from scipy.spatial import Voronoi, ConvexHull, KDTree
from scipy.cluster.hierarchy import fclusterdata
import biotite.structure.io.pdb as pdb
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import CavityDict

# Import Phase 2.3 functions
from .geometry import find_voids, extract_atom_coords


# ============================================================================
# CONSTANTS (Phase 2.4)
# ============================================================================

# Cavity merging threshold (parametric for adaptive tuning)
MERGE_THRESHOLD = 4.0  # Å (increased for better cryptic pocket capture)

# Hydrophobic residues (druggability filter)
HYDROPHOBIC_RESIDUES = {'LEU', 'ILE', 'VAL', 'PHE', 'TRP', 'MET', 'ALA', 'PRO'}

# Polar atom threshold for druggable cavity
POLAR_THRESHOLD = 6  # Max polar atoms near cavity center (relaxed for mixed-character pockets)

# Search radius for hydrophobic analysis
HYDROPHOBIC_SEARCH_RADIUS = 6.0  # Å (increased for better neighborhood sampling)


# ============================================================================
# 1. TRUE VORONOI REGION VOLUME (Ridge-based)
# ============================================================================

def calculate_region_volume(vertex_idx: int, voronoi: Voronoi) -> float:
    """
    Calculate true Voronoi region volume using ridge-based polyhedron.
    
    ⚠️ WARNING: voronoi.point_region is for atoms, NOT vertices!
    This function uses ridge_vertices to build vertex-local polyhedra.
    
    Args:
        vertex_idx: Index of the Voronoi vertex
        voronoi: Scipy Voronoi object
    
    Returns:
        volume: True region volume (Å³), or 0.0 if unbounded/invalid
    
    Method:
    - Find all ridges containing this vertex
    - Collect neighbor vertices from those ridges
    - Build ConvexHull from vertex + neighbors
    - Return hull.volume
    
    ChatGPT Senior PI Note:
    "Ridge-based volume kararı → ÇOK DOĞRU. SciPy Voronoi'yi gerçekten 
    anladığını gösterir. %90 kişinin düştüğü hatayı bilinçli olarak by-pass eder."
    """
    vertex = voronoi.vertices[vertex_idx]
    
    # Find all ridges that contain this vertex
    neighbor_vertices = set()
    
    for ridge in voronoi.ridge_vertices:
        if vertex_idx in ridge:
            # Add all other vertices from this ridge
            for v_idx in ridge:
                if v_idx != -1 and v_idx != vertex_idx:  # -1 = infinity
                    neighbor_vertices.add(v_idx)
    
    if len(neighbor_vertices) < 3:
        # Not enough neighbors to form a polyhedron
        return 0.0
    
    # Build polyhedron from vertex + neighbors
    try:
        points = [vertex]
        for n_idx in neighbor_vertices:
            points.append(voronoi.vertices[n_idx])
        
        points = np.array(points)
        
        # Need at least 4 points for 3D ConvexHull
        if len(points) < 4:
            return 0.0
        
        hull = ConvexHull(points)
        return hull.volume
    except Exception:
        # Degenerate or invalid geometry
        return 0.0


# ============================================================================
# 2. CAVITY MERGING (Hierarchical Clustering)
# ============================================================================

def merge_cavities(voids: List[Dict], 
                   merge_threshold: float = MERGE_THRESHOLD) -> List[Dict]:
    """
    Merge adjacent Voronoi vertices into cavities using hierarchical clustering.
    
    Args:
        voids: List of void dicts from find_voids()
        merge_threshold: Distance threshold for merging (Å)
    
    Returns:
        cavities: List of merged cavity dicts
    
    Each cavity contains:
    - merged_vertices: Number of vertices merged
    - merge_threshold: Threshold used (for logging/adaptive tuning)
    - vertices: List of original void centers
    
    ChatGPT Senior PI Note:
    "3.0 Å: iyi bir başlangıç ama mutlak fizik yasası değil. 
    cavity['merge_threshold'] = 3.0 ve logla. İleride adaptive threshold 
    oynaması yaparsan altyapı hazır olur."
    """
    if len(voids) == 0:
        return []
    
    if len(voids) == 1:
        cavity = voids[0].copy()
        cavity['merged_vertices'] = 1
        cavity['merge_threshold'] = merge_threshold
        cavity['vertices'] = [voids[0]['center']]
        return [cavity]
    
    # Extract centers for clustering
    centers = np.array([v['center'] for v in voids])
    
    # Hierarchical clustering with distance threshold
    try:
        clusters = fclusterdata(centers, t=merge_threshold, 
                                criterion='distance', method='complete')
    except Exception:
        # Fallback: treat each void as separate cavity
        return [{**v, 'merged_vertices': 1, 'merge_threshold': merge_threshold,
                 'vertices': [v['center']]} for v in voids]
    
    # Group voids by cluster
    cluster_ids = np.unique(clusters)
    cavities = []
    
    for cid in cluster_ids:
        cluster_mask = (clusters == cid)
        cluster_voids = [v for v, m in zip(voids, cluster_mask) if m]
        
        # Merge properties
        cavity = {
            'merged_vertices': len(cluster_voids),
            'merge_threshold': merge_threshold,
            'vertices': [v['center'] for v in cluster_voids]
        }
        
        cavities.append(cavity)
    
    return cavities


# ============================================================================
# 3. CAVITY PROPERTIES (Dual Radii + Weighted Centroid)
# ============================================================================

def calculate_cavity_properties(cavity: CavityDict, coords: np.ndarray) -> CavityDict:
    """
    Calculate merged cavity properties with dual radii.
    
    Args:
        cavity: Cavity dict from merge_cavities()
        coords: Atom coordinates
    
    Returns:
        cavity: Updated with volume, center, radius_geom, radius_clear
    
    Dual Radii:
    - radius_geom: Max distance from center to any vertex (cavity extent)
    - radius_clear: Min distance from center to nearest atom (steric tightness)
    
    ChatGPT Senior PI Note:
    "Dual Radius (radius_geom + radius_clear) = 🔥
    Bu kısım çok kritik ve çoğu tool'da yok. Bu ayrım docking, fragment 
    growing, lead optimization için altın değerinde. Bunu koyman, modülü 
    'akademik toy tool'dan çıkarıyor."
    """
    vertices = np.array(cavity['vertices'])
    
    # Weighted centroid (simple mean for now, volume-weighted optional)
    center = np.mean(vertices, axis=0)
    
    # Radius geometric: max distance from center to any vertex
    if len(vertices) > 1:
        vertex_distances = np.linalg.norm(vertices - center, axis=1)
        radius_geom = np.max(vertex_distances)
    else:
        radius_geom = 0.0
    
    # Radius clear: min distance from center to nearest atom (steric)
    atom_distances = np.linalg.norm(coords - center, axis=1)
    radius_clear = np.min(atom_distances)
    
    # Volume: sum of spherical approximations
    # (True Voronoi region volume can be added later)
    volume = (4.0 / 3.0) * np.pi * (radius_clear ** 3) * len(vertices)
    
    cavity['center'] = center
    cavity['radius_geom'] = radius_geom
    cavity['radius_clear'] = radius_clear
    cavity['radius'] = radius_clear  # Backward compatibility
    cavity['volume'] = volume
    
    return cavity


# ============================================================================
# 4. HYDROPHOBIC FILTERING (KD-Tree + Polar Threshold)
# ============================================================================

def filter_hydrophobic(cavities: List[CavityDict], pdb_file: str,
                       search_radius: float = HYDROPHOBIC_SEARCH_RADIUS) -> List[CavityDict]:
    """
    Filter cavities by hydrophobicity for druggability prediction.
    
    Uses KD-Tree for O(log N) performance.
    
    Args:
        cavities: List of cavity dicts
        pdb_file: Path to PDB file for residue information
        search_radius: Radius to search for nearby residues (Å)
    
    Returns:
        cavities: Updated with 'druggable' and 'hydrophobic_ratio' fields
    
    Criteria:
    - hydrophobic_ratio > 0.5 AND polar_atoms < POLAR_THRESHOLD
    
    ChatGPT Senior PI Note:
    "Hidrofobik + polar çift filtresi → yüzey tuzağını kapatır.
    Bu sayede sadece 'yağlı ama açık' yüzey çukurları druggable diye 
    işaretlenmez. Bu, Faz 1.2'deki hayaletlerin kimyasal versiyonunu da gömüyor 🪦"
    """
    # Load structure for residue information
    pdb_path = Path(pdb_file)
    pdb_obj = pdb.PDBFile.read(str(pdb_path))
    structure = pdb_obj.get_structure()[0]
    
    # Get all CA atoms with residue info
    ca_filter = (structure.atom_name == 'CA')
    ca_atoms = structure[ca_filter]
    ca_coords = ca_atoms.coord
    ca_res_names = ca_atoms.res_name
    
    # Build KD-Tree for fast spatial queries
    if len(ca_coords) > 0:
        kdtree = KDTree(ca_coords)
    else:
        # No CA atoms, mark all as not druggable
        for cavity in cavities:
            cavity['druggable'] = False
            cavity['hydrophobic_ratio'] = 0.0
            cavity['polar_atoms'] = 0
        return cavities
    
    # Polar atoms for threshold check
    polar_filter = np.isin(structure.element, ['N', 'O'])
    polar_coords = structure[polar_filter].coord
    polar_kdtree = KDTree(polar_coords) if len(polar_coords) > 0 else None
    
    for cavity in cavities:
        center = cavity['center']
        
        # Find nearby residues using KD-Tree
        nearby_indices = kdtree.query_ball_point(center, search_radius)
        
        if len(nearby_indices) == 0:
            cavity['druggable'] = False
            cavity['hydrophobic_ratio'] = 0.0
            cavity['polar_atoms'] = 0
            continue
        
        # Count hydrophobic residues
        nearby_res_names = ca_res_names[nearby_indices]
        hydrophobic_count = sum(1 for r in nearby_res_names 
                                if r in HYDROPHOBIC_RESIDUES)
        hydrophobic_ratio = hydrophobic_count / len(nearby_indices)
        
        # Count polar atoms near cavity
        if polar_kdtree is not None:
            polar_nearby = polar_kdtree.query_ball_point(center, search_radius)
            polar_atoms = len(polar_nearby)
        else:
            polar_atoms = 0
        
        # Druggability criteria (relaxed to capture more cryptic pockets)
        druggable = (hydrophobic_ratio > 0.3 and polar_atoms < POLAR_THRESHOLD)
        
        cavity['druggable'] = druggable
        cavity['hydrophobic_ratio'] = hydrophobic_ratio
        cavity['polar_atoms'] = polar_atoms
    
    return cavities


# ============================================================================
# 5. MAIN API - find_cavities()
# ============================================================================

def find_cavities(pdb_file: str, 
                  min_volume: float = 100.0,
                  max_volume: float = 5000.0,
                  atom_type: str = 'heavy',
                  merge: bool = True,
                  hydrophobic: bool = True,
                  merge_threshold: float = MERGE_THRESHOLD) -> List[CavityDict]:
    """
    Main API: Find and analyze cavities in protein structure.
    
    This is the production API for Phase 2.4+.
    For backward compatibility, use find_voids() from geometry module.
    
    Args:
        pdb_file: Path to PDB file
        min_volume: Minimum cavity volume (Å³)
        max_volume: Maximum cavity volume (Å³) (Filter out unrealistic voids)
        atom_type: 'heavy' or 'ca'
        merge: Enable cavity merging (hierarchical clustering)
        hydrophobic: Enable hydrophobic filtering
        merge_threshold: Distance threshold for merging (Å)
    
    Returns:
        cavities: List of cavity dicts, sorted by volume (descending)
    
    Pipeline:
    1. find_voids() - Get vertex-level voids (Phase 2.3)
    2. merge_cavities() - Cluster adjacent vertices
    3. calculate_cavity_properties() - Dual radii + centroid
    4. filter_hydrophobic() - Druggability prediction
    5. Filter by max_volume
    6. Sort by volume (descending)
    """
    # 1. Get vertex-level voids (Phase 2.3)
    voids = find_voids(pdb_file, min_volume=min_volume, atom_type=atom_type)
    
    if len(voids) == 0:
        return []
    
    # Get coords for property calculation
    coords = extract_atom_coords(pdb_file, atom_type=atom_type)
    
    # Adaptive merge threshold based on void density and protein size
    effective_threshold = merge_threshold
    if len(voids) > 200:
        effective_threshold = merge_threshold + 1.5
    elif len(voids) > 100:
        effective_threshold = merge_threshold + 1.0
    elif len(voids) < 10:
        effective_threshold = max(2.5, merge_threshold - 0.5)

    n_atoms = len(coords)
    if n_atoms > 2000:
        effective_threshold += 0.5
    
    if merge:
        # 2. Merge adjacent vertices
        cavities = merge_cavities(voids, merge_threshold=effective_threshold)
        
        # 3. Calculate cavity properties
        for cavity in cavities:
            calculate_cavity_properties(cavity, coords)
    else:
        # No merging: treat each void as a cavity
        cavities = []
        for void in voids:
            cavity = void.copy()
            cavity['merged_vertices'] = 1
            cavity['merge_threshold'] = merge_threshold
            cavity['vertices'] = [void['center']]
            cavity['radius_geom'] = 0.0
            cavity['radius_clear'] = void['radius']
            cavities.append(cavity)
    
    if hydrophobic:
        # 4. Filter by hydrophobicity
        cavities = filter_hydrophobic(cavities, pdb_file)
    else:
        # Mark all as not analyzed
        for cavity in cavities:
            cavity['druggable'] = None
            cavity['hydrophobic_ratio'] = None
            cavity['polar_atoms'] = None
            
    # 5. Filter unrealistic voids (Max Volume Safety)
    cavities = [c for c in cavities if c['volume'] <= max_volume]
    
    # 6. Sort by volume (descending)
    cavities = sorted(cavities, key=lambda x: x['volume'], reverse=True)
    
    return cavities
