"""
Bio-Void Hunter: Druggability Scoring Engine (Phase 3)
=======================================================

Production-grade scoring, profiling, and ranking of protein cavities.
Transforms raw cavity data into actionable druggability predictions.

Key Features:
- Target-specific scoring profiles (Enzyme, PPI, GPCR)
- Bio-Score: weighted composite druggability metric [0, 1]
- Enclosure Metric: cave vs bowl geometry (Convex Hull Defect)
- Depth Score: protein core vs surface proximity
- NMA Flexibility integration (cryptic pocket bonus)
- Benchmarking & Top-N ranking

References:
- Schmidtke & Barril (2010) "Understanding and predicting druggability"
- Halgren (2009) "Identifying and characterizing binding sites and assessing druggability"
- Volkamer et al. (2012) "DoGSiteScorer"
- Liang et al. (1998) "Anatomy of protein pockets and cavities"

Phase 3.1: ScoringProfile base class + Enzyme/PPI/GPCR profiles
Phase 3.2: Bio-Score formula + Enclosure Metric + Energy Filter
Phase 3.3: Benchmarking & rank_pockets() API

Author: Bio-Void Hunter Team
Version: 0.5.0 (Phase 3)
"""

from __future__ import annotations

import numpy as np
from abc import ABC, abstractmethod
from scipy.spatial import ConvexHull
from typing import Any, Dict, List, Optional


# ============================================================================
# CONSTANTS
# ============================================================================

# Volume normalization range (Å³) — Lipinski-compatible drug pocket
VOLUME_MIN = 100.0   # Minimum meaningful pocket
VOLUME_MAX = 2000.0  # Maximum single-drug pocket

# Hydrophobicity normalization
HYDRO_MIN = 0.0
HYDRO_MAX = 1.0

# Enclosure metric
ENCLOSURE_MIN_VERTICES = 4  # Minimum vertices for ConvexHull

# Depth scoring — distance from protein centroid
DEPTH_SURFACE_THRESHOLD = 5.0   # Å — closer = surface noise
DEPTH_CORE_THRESHOLD = 15.0     # Å — deeper = more buried

# Druggability class thresholds
DRUGGABILITY_HIGH = 0.65
DRUGGABILITY_MEDIUM = 0.40


# ============================================================================
# PHASE 3.1: SCORING PROFILES
# ============================================================================

class ScoringProfile(ABC):
    """
    Abstract base class for target-specific scoring profiles.
    
    Each profile defines weights for Bio-Score components:
    - volume_w:       Pocket volume contribution
    - hydrophobicity_w: Hydrophobic ratio contribution
    - enclosure_w:    Enclosure (cave vs bowl) contribution
    - depth_w:        Burial depth contribution
    
    Weights MUST sum to 1.0 (enforced by validation).
    
    Usage:
        profile = EnzymeProfile()
        score = profile.calculate_score(metrics)
    """
    
    def __init__(self):
        self._weights = self._define_weights()
        self._validate_weights()
    
    @abstractmethod
    def _define_weights(self) -> dict[str, float]:
        """Define scoring weights for this profile. Must sum to 1.0."""
        pass
    
    @property
    def name(self) -> str:
        """Profile display name."""
        return self.__class__.__name__.replace("Profile", "")
    
    @property
    def weights(self) -> dict[str, float]:
        """Weight vector (read-only)."""
        return self._weights.copy()
    
    def _validate_weights(self):
        """Enforce weight constraints."""
        total = sum(self._weights.values())
        if not np.isclose(total, 1.0, atol=1e-6):
            raise ValueError(
                f"{self.name} profile weights sum to {total:.4f}, must be 1.0"
            )
        for key, val in self._weights.items():
            if val < 0:
                raise ValueError(
                    f"{self.name} profile weight '{key}' is negative: {val}"
                )
    
    def calculate_score(self, metrics: dict[str, float]) -> float:
        """
        Calculate weighted Bio-Score from normalized metrics.
        
        Args:
            metrics: Dict with keys matching weight keys, values in [0, 1].
        
        Returns:
            score: Weighted sum in [0, 1].
        """
        score = 0.0
        for key, weight in self._weights.items():
            value = metrics.get(key, 0.0)
            # Clamp to [0, 1] for safety
            value = max(0.0, min(1.0, float(value)))
            score += weight * value
        return round(score, 4)
    
    def __repr__(self):
        return f"{self.name}Profile(weights={self._weights})"


class EnzymeProfile(ScoringProfile):
    """
    Scoring profile for enzyme active sites.
    
    Enzymes prefer:
    - Deep, enclosed pockets (high enclosure)
    - Moderate volume (400-800 Å³)
    - Mixed hydrophobic/polar (catalytic residues)
    - Buried in core (high depth)
    """
    
    def _define_weights(self) -> dict[str, float]:
        return {
            'volume': 0.15,
            'hydrophobicity': 0.20,
            'enclosure': 0.35,
            'depth': 0.30,
        }


class PPIProfile(ScoringProfile):
    """
    Scoring profile for Protein-Protein Interaction (PPI) interfaces.
    
    PPI pockets prefer:
    - Large, shallow surfaces (lower enclosure)
    - High hydrophobicity (hot-spot residues)
    - Moderate depth
    - Larger volumes (> 600 Å³)
    """
    
    def _define_weights(self) -> dict[str, float]:
        return {
            'volume': 0.35,
            'hydrophobicity': 0.35,
            'enclosure': 0.10,
            'depth': 0.20,
        }


class GPCRProfile(ScoringProfile):
    """
    Scoring profile for GPCR/Channel binding sites.
    
    GPCR channels prefer:
    - Narrow, deep channels (high enclosure)
    - Moderate hydrophobicity
    - Very deep burial
    - Specific volume range (300-600 Å³)
    """
    
    def _define_weights(self) -> dict[str, float]:
        return {
            'volume': 0.20,
            'hydrophobicity': 0.15,
            'enclosure': 0.30,
            'depth': 0.35,
        }


class DefaultProfile(ScoringProfile):
    """
    Balanced default profile when target type is unknown.
    Equal emphasis on all four metrics.
    """
    
    def _define_weights(self) -> dict[str, float]:
        return {
            'volume': 0.25,
            'hydrophobicity': 0.25,
            'enclosure': 0.25,
            'depth': 0.25,
        }


# Profile registry for CLI/API access
PROFILES: dict[str, type[ScoringProfile]] = {
    'enzyme': EnzymeProfile,
    'ppi': PPIProfile,
    'gpcr': GPCRProfile,
    'default': DefaultProfile,
}


def get_profile(name: str = 'default') -> ScoringProfile:
    """
    Get a scoring profile by name.
    
    Args:
        name: Profile name ('enzyme', 'ppi', 'gpcr', 'default')
    
    Returns:
        ScoringProfile instance
    
    Raises:
        ValueError: If profile name is unknown
    """
    name_lower = name.lower().strip()
    if name_lower not in PROFILES:
        available = ', '.join(PROFILES.keys())
        raise ValueError(
            f"Unknown profile '{name}'. Available: {available}"
        )
    return PROFILES[name_lower]()


# ============================================================================
# PHASE 3.2: METRIC CALCULATORS
# ============================================================================

def normalize_volume(volume: float,
                     v_min: float = VOLUME_MIN,
                     v_max: float = VOLUME_MAX) -> float:
    """
    Normalize cavity volume to [0, 1].
    
    Uses sigmoid-like clamped linear mapping:
    - Below v_min → 0.0 (too small for drug)
    - Between v_min and v_max → linear 0→1
    - Above v_max → 1.0 (capped, larger ≠ always better)
    
    Args:
        volume: Raw volume (ų)
        v_min: Lower bound
        v_max: Upper bound
    
    Returns:
        Normalized volume score [0, 1]
    """
    if np.isnan(volume) or np.isinf(volume) or volume <= 0:
        return 0.0
    if volume <= v_min:
        return 0.0
    if volume >= v_max:
        return 1.0
    return (volume - v_min) / (v_max - v_min)


def normalize_hydrophobicity(ratio: Optional[float]) -> float:
    """
    Normalize hydrophobic ratio to [0, 1].
    
    Direct mapping — ratio is already in [0, 1] from cavities module.
    Applies NaN/None safety.
    
    Args:
        ratio: Hydrophobic residue ratio from filter_hydrophobic()
    
    Returns:
        Normalized hydrophobicity score [0, 1]
    """
    if ratio is None or np.isnan(ratio) or np.isinf(ratio):
        return 0.0
    return max(0.0, min(1.0, float(ratio)))


def calculate_enclosure(cavity: Dict[str, Any],
                        atom_coords: Optional[np.ndarray] = None) -> float:
    """
    Calculate enclosure metric: how "cave-like" vs "bowl-like" a cavity is.
    
    Method: Convex Hull Defect
    --------------------------
    enclosure = 1.0 - (sum_vertex_radii / hull_volume)
    
    Intuition:
    - A deeply buried cavity's vertices are tightly clustered → 
      hull_volume ≈ sum of spheres → low defect → HIGH enclosure
    - A surface groove's vertices are spread out → 
      hull_volume >> sum of spheres → high defect → LOW enclosure
    
    Simplified approach when few vertices:
    - Uses radius_clear / radius_geom ratio as proxy
    - High ratio = tight/enclosed, low ratio = spread/open
    
    Args:
        cavity: Cavity dict with 'vertices', 'radius_clear', 'radius_geom'
        atom_coords: Optional protein atom coordinates for depth calculation
    
    Returns:
        enclosure: Score in [0, 1] (1.0 = fully enclosed cave)
    """
    vertices = cavity.get('vertices', [])
    radius_clear = cavity.get('radius_clear', 0.0)
    radius_geom = cavity.get('radius_geom', 0.0)
    
    # Case 1: Single vertex — use radius ratio
    if len(vertices) < ENCLOSURE_MIN_VERTICES:
        if radius_geom > 0:
            # Clear/Geom ratio: higher = tighter enclosure
            ratio = radius_clear / radius_geom
            return min(1.0, ratio)
        # Fallback: moderate enclosure assumed
        return 0.5
    
    # Case 2: Multiple vertices — Convex Hull Defect method
    try:
        vert_array = np.array([
            v if isinstance(v, np.ndarray) else np.array(v)
            for v in vertices
        ])
        
        hull = ConvexHull(vert_array)
        hull_volume = hull.volume
        
        if hull_volume <= 0:
            return 0.5
        
        # Spherical approximation volume of merged vertices
        sphere_volume = cavity.get('volume', 0.0)
        
        if sphere_volume <= 0:
            return 0.5
        
        # Defect: how much "empty space" the hull has beyond the spheres
        # Low defect = tightly packed = enclosed
        # High defect = spread out = open
        if hull_volume > sphere_volume:
            defect = 1.0 - (sphere_volume / hull_volume)
            # Invert: high enclosure = low defect
            enclosure = 1.0 - defect
        else:
            # Spheres fill or exceed hull — very enclosed
            enclosure = 1.0
        
        return max(0.0, min(1.0, enclosure))
        
    except Exception:
        # ConvexHull failed (degenerate geometry)
        if radius_geom > 0:
            return min(1.0, radius_clear / radius_geom)
        return 0.5


def calculate_depth(cavity: Dict[str, Any],
                    atom_coords: np.ndarray) -> float:
    """
    Calculate depth score: how deeply buried a cavity is in the protein.
    
    Method:
    - Compute protein centroid (center of mass of all atoms)
    - Measure distance from cavity center to protein centroid
    - Closer to centroid = deeper = higher score
    
    Also applies surface penalty:
    - Cavities very close to convex hull surface get reduced score
    
    Args:
        cavity: Cavity dict with 'center'
        atom_coords: All protein atom coordinates
    
    Returns:
        depth: Score in [0, 1] (1.0 = deeply buried in core)
    """
    center = cavity.get('center')
    if center is None:
        return 0.0
    
    center = np.array(center) if not isinstance(center, np.ndarray) else center
    
    # Protein centroid
    protein_centroid = np.mean(atom_coords, axis=0)
    
    # Distance from cavity to protein center
    dist_to_center = np.linalg.norm(center - protein_centroid)
    
    # Max possible distance (protein radius)
    max_dist = np.max(np.linalg.norm(atom_coords - protein_centroid, axis=1))
    
    if max_dist <= 0:
        return 0.5
    
    # Normalized depth: 0 = surface, 1 = core
    # Inverse of relative distance
    relative_dist = dist_to_center / max_dist
    depth_raw = 1.0 - relative_dist
    
    # Surface penalty: cavities within DEPTH_SURFACE_THRESHOLD of hull
    try:
        hull = ConvexHull(atom_coords)
        # Check if center is near the hull surface
        equations = hull.equations  # (normal_x, normal_y, normal_z, offset)
        # Signed distance to each facet
        signed_dists = equations[:, :3] @ center + equations[:, 3]
        min_surface_dist = np.min(np.abs(signed_dists))
        
        if min_surface_dist < DEPTH_SURFACE_THRESHOLD:
            # Apply penalty: closer to surface = lower score
            surface_penalty = min_surface_dist / DEPTH_SURFACE_THRESHOLD
            depth_raw *= surface_penalty
    except Exception:
        pass  # ConvexHull failed, skip penalty
    
    return max(0.0, min(1.0, depth_raw))


# ============================================================================
# PHASE 3.2: BIO-SCORE CALCULATOR
# ============================================================================

def calculate_bio_score(cavity: Dict[str, Any],
                        atom_coords: np.ndarray,
                        profile: str = 'default') -> Dict[str, Any]:
    """
    Calculate composite Bio-Score for a single cavity.
    
    Computes individual metric scores, then applies profile-weighted sum.
    
    Args:
        cavity: Cavity dict from find_cavities()
        atom_coords: Protein atom coordinates (heavy atoms)
        profile: Scoring profile name ('enzyme', 'ppi', 'gpcr', 'default')
    
    Returns:
        Dict with:
        - 'bio_score': float [0, 1]
        - 'score_components': Dict of individual metric scores
        - 'druggability_class': 'high', 'medium', or 'low'
        - 'profile_used': str
    """
    # Get profile
    scoring_profile = get_profile(profile)
    
    # Calculate individual metrics
    volume_score = normalize_volume(cavity.get('volume', 0.0))
    hydro_score = normalize_hydrophobicity(cavity.get('hydrophobic_ratio', 0.0))
    enclosure_score = calculate_enclosure(cavity, atom_coords)
    depth_score = calculate_depth(cavity, atom_coords)
    
    # Build metrics dict
    metrics = {
        'volume': volume_score,
        'hydrophobicity': hydro_score,
        'enclosure': enclosure_score,
        'depth': depth_score,
    }
    
    # Calculate weighted score
    bio_score = scoring_profile.calculate_score(metrics)
    
    # Classify
    if bio_score >= DRUGGABILITY_HIGH:
        druggability_class = 'high'
    elif bio_score >= DRUGGABILITY_MEDIUM:
        druggability_class = 'medium'
    else:
        druggability_class = 'low'
    
    return {
        'bio_score': bio_score,
        'score_components': {
            'volume_score': round(volume_score, 4),
            'hydrophobicity_score': round(hydro_score, 4),
            'enclosure_score': round(enclosure_score, 4),
            'depth_score': round(depth_score, 4),
        },
        'druggability_class': druggability_class,
        'profile_used': scoring_profile.name,
    }


# ============================================================================
# PHASE 3.3: RANKING & BENCHMARKING
# ============================================================================

def score_all_cavities(cavities: List[Dict[str, Any]],
                       atom_coords: np.ndarray,
                       profile: str = 'default') -> List[Dict[str, Any]]:
    """
    Score all cavities and attach results to each cavity dict.
    
    Mutates cavity dicts in-place by adding scoring fields.
    
    Args:
        cavities: List of cavity dicts from find_cavities()
        atom_coords: Protein atom coordinates
        profile: Scoring profile name
    
    Returns:
        cavities: Same list, now with bio_score fields added
    """
    for cavity in cavities:
        result = calculate_bio_score(cavity, atom_coords, profile)
        cavity['bio_score'] = result['bio_score']
        cavity['score_components'] = result['score_components']
        cavity['druggability_class'] = result['druggability_class']
        cavity['profile_used'] = result['profile_used']
    
    return cavities


def rank_pockets(cavities: List[Dict[str, Any]],
                 atom_coords: np.ndarray,
                 profile: str = 'default',
                 top_n: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Score, rank, and optionally filter top-N cavities.
    
    Main API for Phase 3 integration with pipeline.
    
    Args:
        cavities: List of cavity dicts from find_cavities()
        atom_coords: Protein heavy atom coordinates
        profile: Scoring profile ('enzyme', 'ppi', 'gpcr', 'default')
        top_n: Return only top N cavities (None = return all)
    
    Returns:
        ranked: List of cavity dicts sorted by bio_score (descending),
                each with 'rank' field (1-based)
    """
    if not cavities:
        return []
    
    # Score all
    scored = score_all_cavities(cavities, atom_coords, profile)
    
    # Sort by bio_score descending
    ranked = sorted(scored, key=lambda c: c.get('bio_score', 0.0), reverse=True)
    
    # Assign ranks (1-based)
    for i, cavity in enumerate(ranked):
        cavity['rank'] = i + 1
    
    # Top-N filter
    if top_n is not None and top_n > 0:
        ranked = ranked[:top_n]
    
    return ranked


def get_elite_pockets(cavities: List[Dict[str, Any]],
                      atom_coords: np.ndarray,
                      profile: str = 'default',
                      top_n: int = 5,
                      min_score: float = 0.0) -> List[Dict[str, Any]]:
    """
    Get the elite (top-scoring) pockets from a cavity list.
    
    Convenience function for quick analysis.
    
    Args:
        cavities: List of cavity dicts
        atom_coords: Protein atom coordinates
        profile: Scoring profile name
        top_n: Number of top pockets to return
        min_score: Minimum bio_score threshold
    
    Returns:
        elite: Top-N cavities with bio_score >= min_score
    """
    ranked = rank_pockets(cavities, atom_coords, profile)
    
    # Filter by minimum score
    elite = [c for c in ranked if c.get('bio_score', 0.0) >= min_score]
    
    return elite[:top_n]
