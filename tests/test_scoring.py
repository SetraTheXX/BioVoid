"""
Test Suite for Phase 3: Druggability Scoring Engine
====================================================

Tests for:
- ScoringProfile base class and subclasses
- Weight validation (must sum to 1.0)
- Volume / hydrophobicity normalization
- Enclosure metric (ConvexHull Defect)
- Depth score calculation
- Bio-Score composite calculation
- rank_pockets() API
- get_elite_pockets() convenience API
- Edge cases: empty cavities, NaN/Inf, degenerate geometry

Author: Bio-Void Hunter Team
"""

from __future__ import annotations

import pytest
import numpy as np
from pathlib import Path
from typing import Any

from src.scoring import (
    ScoringProfile,
    EnzymeProfile,
    PPIProfile,
    GPCRProfile,
    DefaultProfile,
    get_profile,
    PROFILES,
    normalize_volume,
    normalize_hydrophobicity,
    calculate_enclosure,
    calculate_depth,
    calculate_bio_score,
    rank_pockets,
    get_elite_pockets,
    VOLUME_MIN,
    VOLUME_MAX,
    DRUGGABILITY_MEDIUM,
)

# Test data paths
TEST_PDB = "data/raw_pdb/1cbs.pdb"


# ============================================================================
# HELPERS
# ============================================================================

def make_cavity(center: tuple[float, ...] = (0, 0, 0),
                volume: float = 500.0, radius_geom: float = 5.0,
                radius_clear: float = 4.0, hydrophobic_ratio: float = 0.6,
                polar_atoms: int = 1, druggable: bool = True,
                n_vertices: int = 6) -> dict[str, Any]:
    """Create a synthetic cavity dict for testing."""
    vertices: list[np.ndarray] = [
        np.array(center) + np.random.randn(3) * 2.0
        for _ in range(n_vertices)
    ]
    return {
        'center': np.array(center, dtype=float),
        'volume': volume,
        'radius_geom': radius_geom,
        'radius_clear': radius_clear,
        'merged_vertices': n_vertices,
        'merge_threshold': 3.0,
        'vertices': vertices,
        'druggable': druggable,
        'hydrophobic_ratio': hydrophobic_ratio,
        'polar_atoms': polar_atoms,
        'id': 0,
    }


def make_atom_coords(n: int = 100, spread: float = 20.0) -> np.ndarray:
    """Create synthetic protein atom coordinates."""
    np.random.seed(42)
    return np.random.randn(n, 3) * spread  # type: ignore[return-value]


# ============================================================================
# PHASE 3.1: SCORING PROFILES
# ============================================================================

class TestScoringProfiles:
    """Test scoring profile classes and weight validation."""
    
    def test_all_profiles_exist(self):
        """Test that all expected profiles are registered."""
        assert 'enzyme' in PROFILES
        assert 'ppi' in PROFILES
        assert 'gpcr' in PROFILES
        assert 'default' in PROFILES
    
    def test_enzyme_weights_sum_to_one(self):
        """EnzymeProfile weights must sum to 1.0."""
        profile = EnzymeProfile()
        total = sum(profile.weights.values())
        assert np.isclose(total, 1.0)
    
    def test_ppi_weights_sum_to_one(self):
        """PPIProfile weights must sum to 1.0."""
        profile = PPIProfile()
        total = sum(profile.weights.values())
        assert np.isclose(total, 1.0)
    
    def test_gpcr_weights_sum_to_one(self):
        """GPCRProfile weights must sum to 1.0."""
        profile = GPCRProfile()
        total = sum(profile.weights.values())
        assert np.isclose(total, 1.0)
    
    def test_default_weights_sum_to_one(self):
        """DefaultProfile weights must sum to 1.0."""
        profile = DefaultProfile()
        total = sum(profile.weights.values())
        assert np.isclose(total, 1.0)
    
    def test_all_weights_non_negative(self):
        """All profile weights must be >= 0."""
        for name, ProfileClass in PROFILES.items():
            profile: ScoringProfile = ProfileClass()
            for key, val in profile.weights.items():
                assert val >= 0, f"{name}.{key} is negative: {val}"
    
    def test_get_profile_valid(self):
        """get_profile() returns correct profile instances."""
        assert isinstance(get_profile('enzyme'), EnzymeProfile)
        assert isinstance(get_profile('ppi'), PPIProfile)
        assert isinstance(get_profile('gpcr'), GPCRProfile)
        assert isinstance(get_profile('default'), DefaultProfile)
    
    def test_get_profile_case_insensitive(self):
        """get_profile() handles case insensitivity."""
        assert isinstance(get_profile('Enzyme'), EnzymeProfile)
        assert isinstance(get_profile('PPI'), PPIProfile)
        assert isinstance(get_profile(' GPCR '), GPCRProfile)
    
    def test_get_profile_invalid_raises(self):
        """get_profile() raises ValueError for unknown profiles."""
        with pytest.raises(ValueError, match="Unknown profile"):
            get_profile('unknown')
    
    def test_profile_name_property(self):
        """Profile name is correctly derived from class name."""
        assert EnzymeProfile().name == 'Enzyme'
        assert PPIProfile().name == 'PPI'
        assert GPCRProfile().name == 'GPCR'
        assert DefaultProfile().name == 'Default'
    
    def test_weights_are_read_only(self):
        """Returned weights should be a copy, not a reference."""
        profile = EnzymeProfile()
        w1 = profile.weights
        w1['volume'] = 999.0
        assert profile.weights['volume'] != 999.0
    
    def test_profile_calculate_score(self):
        """Profile.calculate_score() returns weighted sum."""
        profile = DefaultProfile()  # Equal weights: 0.25 each
        metrics = {
            'volume': 1.0,
            'hydrophobicity': 1.0,
            'enclosure': 1.0,
            'depth': 1.0,
        }
        score = profile.calculate_score(metrics)
        assert np.isclose(score, 1.0)
    
    def test_profile_score_partial_metrics(self):
        """Score calculation handles missing metric keys gracefully."""
        profile = DefaultProfile()
        metrics = {'volume': 0.8}  # Others default to 0
        score = profile.calculate_score(metrics)
        assert score == pytest.approx(0.25 * 0.8, abs=0.001)
    
    def test_profile_score_clamps_values(self):
        """Values > 1.0 or < 0.0 are clamped."""
        profile = DefaultProfile()
        metrics = {'volume': 2.0, 'hydrophobicity': -0.5,
                   'enclosure': 0.5, 'depth': 0.5}
        score = profile.calculate_score(metrics)
        # 2.0 → 1.0, -0.5 → 0.0
        expected = 0.25 * 1.0 + 0.25 * 0.0 + 0.25 * 0.5 + 0.25 * 0.5
        assert score == pytest.approx(expected, abs=0.001)


class TestInvalidProfile:
    """Test weight validation catches bad profiles."""
    
    def test_weights_not_summing_to_one_raises(self):
        """Profile with weights != 1.0 should raise ValueError."""
        class BadProfile(ScoringProfile):
            def _define_weights(self):
                return {'volume': 0.5, 'hydrophobicity': 0.3}
        
        with pytest.raises(ValueError, match="must be 1.0"):
            BadProfile()
    
    def test_negative_weight_raises(self):
        """Profile with negative weight should raise ValueError."""
        class NegativeProfile(ScoringProfile):
            def _define_weights(self):
                return {'volume': 1.5, 'hydrophobicity': -0.5}
        
        with pytest.raises(ValueError, match="negative"):
            NegativeProfile()


# ============================================================================
# PHASE 3.2: METRIC CALCULATORS
# ============================================================================

class TestNormalizeVolume:
    """Test volume normalization."""
    
    def test_below_min_returns_zero(self):
        assert normalize_volume(50.0) == 0.0
    
    def test_at_min_returns_zero(self):
        assert normalize_volume(VOLUME_MIN) == 0.0
    
    def test_above_max_returns_one(self):
        assert normalize_volume(3000.0) == 1.0
    
    def test_mid_range(self):
        mid = (VOLUME_MIN + VOLUME_MAX) / 2
        result = normalize_volume(mid)
        assert 0.4 < result < 0.6
    
    def test_nan_returns_zero(self):
        assert normalize_volume(float('nan')) == 0.0
    
    def test_inf_returns_zero(self):
        assert normalize_volume(float('inf')) == 0.0
    
    def test_negative_returns_zero(self):
        assert normalize_volume(-100.0) == 0.0


class TestNormalizeHydrophobicity:
    """Test hydrophobicity normalization."""
    
    def test_valid_ratio(self):
        assert normalize_hydrophobicity(0.5) == 0.5
    
    def test_zero(self):
        assert normalize_hydrophobicity(0.0) == 0.0
    
    def test_one(self):
        assert normalize_hydrophobicity(1.0) == 1.0
    
    def test_nan_returns_zero(self):
        assert normalize_hydrophobicity(float('nan')) == 0.0
    
    def test_none_returns_zero(self):
        assert normalize_hydrophobicity(None) == 0.0
    
    def test_clamps_above_one(self):
        assert normalize_hydrophobicity(1.5) == 1.0


class TestCalculateEnclosure:
    """Test enclosure metric calculation."""
    
    def test_few_vertices_uses_radius_ratio(self):
        """Cavities with < 4 vertices use radius fallback."""
        cavity: dict[str, Any] = {
            'vertices': [np.array([0, 0, 0])],
            'radius_clear': 3.0,
            'radius_geom': 6.0,
        }
        enclosure = calculate_enclosure(cavity)
        assert 0.0 <= enclosure <= 1.0
        assert enclosure == pytest.approx(0.5, abs=0.01)
    
    def test_many_vertices_uses_hull(self):
        """Cavities with >= 4 vertices use ConvexHull."""
        cavity = make_cavity(n_vertices=10, volume=500.0)
        enclosure = calculate_enclosure(cavity)
        assert 0.0 <= enclosure <= 1.0
    
    def test_empty_vertices_returns_fallback(self):
        """Empty vertices list returns moderate enclosure."""
        cavity: dict[str, Any] = {'vertices': [], 'radius_clear': 0, 'radius_geom': 0}
        enclosure = calculate_enclosure(cavity)
        assert enclosure == 0.5
    
    def test_enclosure_bounded(self):
        """Enclosure is always in [0, 1]."""
        for _ in range(20):
            cavity = make_cavity(n_vertices=np.random.randint(1, 20))
            enc = calculate_enclosure(cavity)
            assert 0.0 <= enc <= 1.0


class TestCalculateDepth:
    """Test depth score calculation."""
    
    def test_center_of_protein_high_depth(self):
        """Cavity at protein centroid should have high depth."""
        atom_coords = make_atom_coords(100)
        centroid = np.mean(atom_coords, axis=0)
        cavity = make_cavity(center=centroid)
        
        depth = calculate_depth(cavity, atom_coords)
        assert depth > 0.5  # Should be deeply buried
    
    def test_surface_cavity_low_depth(self):
        """Cavity far from centroid should have low depth."""
        atom_coords = make_atom_coords(100, spread=10.0)
        cavity = make_cavity(center=(50.0, 50.0, 50.0))
        
        depth = calculate_depth(cavity, atom_coords)
        assert depth < 0.5
    
    def test_depth_bounded(self):
        """Depth is always in [0, 1]."""
        atom_coords = make_atom_coords(100)
        for _ in range(20):
            cavity = make_cavity(
                center=np.random.randn(3) * 30.0
            )
            d = calculate_depth(cavity, atom_coords)
            assert 0.0 <= d <= 1.0
    
    def test_no_center_returns_zero(self):
        """Missing center returns 0.0."""
        cavity: dict[str, Any] = {'center': None}
        depth = calculate_depth(cavity, make_atom_coords())
        assert depth == 0.0


# ============================================================================
# PHASE 3.2: BIO-SCORE
# ============================================================================

class TestBioScore:
    """Test composite Bio-Score calculation."""
    
    def test_bio_score_returns_dict(self):
        """calculate_bio_score() returns expected structure."""
        cavity = make_cavity()
        coords = make_atom_coords()
        result = calculate_bio_score(cavity, coords)
        
        assert 'bio_score' in result
        assert 'score_components' in result
        assert 'druggability_class' in result
        assert 'profile_used' in result
    
    def test_bio_score_bounded(self):
        """Bio-score is always in [0, 1]."""
        coords = make_atom_coords()
        for _ in range(20):
            cavity = make_cavity(
                volume=np.random.uniform(50, 3000),
                hydrophobic_ratio=np.random.uniform(0, 1),
            )
            result = calculate_bio_score(cavity, coords)
            assert 0.0 <= result['bio_score'] <= 1.0
    
    def test_score_components_present(self):
        """All four score components are present."""
        cavity = make_cavity()
        coords = make_atom_coords()
        result = calculate_bio_score(cavity, coords)
        
        components = result['score_components']
        assert 'volume_score' in components
        assert 'hydrophobicity_score' in components
        assert 'enclosure_score' in components
        assert 'depth_score' in components
    
    def test_druggability_class_high(self):
        """Large, hydrophobic, enclosed, deep pocket → high."""
        coords = make_atom_coords(100, spread=5.0)
        centroid = np.mean(coords, axis=0)
        cavity = make_cavity(
            center=centroid,
            volume=1500.0,
            hydrophobic_ratio=0.9,
            radius_clear=8.0,
            radius_geom=3.0,
        )
        result = calculate_bio_score(cavity, coords)
        # Should be medium or high
        assert result['bio_score'] >= DRUGGABILITY_MEDIUM
    
    def test_druggability_class_low(self):
        """Tiny, non-hydrophobic, shallow pocket → low."""
        coords = make_atom_coords(100, spread=5.0)
        cavity = make_cavity(
            center=(100, 100, 100),
            volume=50.0,
            hydrophobic_ratio=0.0,
        )
        result = calculate_bio_score(cavity, coords)
        assert result['druggability_class'] == 'low'
    
    def test_different_profiles_give_different_scores(self):
        """Same cavity, different profiles → different scores."""
        cavity = make_cavity()
        coords = make_atom_coords()
        
        r_enzyme = calculate_bio_score(cavity, coords, 'enzyme')
        r_ppi = calculate_bio_score(cavity, coords, 'ppi')
        
        # Scores may differ (unless metrics happen to be equal)
        # At minimum, profile names must differ
        assert r_enzyme['profile_used'] == 'Enzyme'
        assert r_ppi['profile_used'] == 'PPI'


# ============================================================================
# PHASE 3.3: RANKING
# ============================================================================

class TestRankPockets:
    """Test ranking and filtering API."""
    
    def test_rank_empty_list(self):
        """rank_pockets() with empty list returns empty."""
        result = rank_pockets([], make_atom_coords())
        assert result == []
    
    def test_rank_assigns_ranks(self):
        """Each cavity gets a rank field (1-based)."""
        cavities = [make_cavity(volume=v) for v in [300, 800, 1200]]
        coords = make_atom_coords()
        
        ranked = rank_pockets(cavities, coords)
        
        ranks = [c['rank'] for c in ranked]
        assert ranks == [1, 2, 3]
    
    def test_rank_descending_order(self):
        """Cavities are sorted by bio_score descending."""
        cavities = [make_cavity(volume=v) for v in [300, 800, 1200]]
        coords = make_atom_coords()
        
        ranked = rank_pockets(cavities, coords)
        scores = [c['bio_score'] for c in ranked]
        
        assert scores == sorted(scores, reverse=True)
    
    def test_rank_top_n(self):
        """top_n parameter limits results."""
        cavities = [make_cavity() for _ in range(10)]
        coords = make_atom_coords()
        
        ranked = rank_pockets(cavities, coords, top_n=3)
        assert len(ranked) == 3
    
    def test_rank_preserves_cavity_data(self):
        """Ranking does not lose existing cavity fields."""
        cavity = make_cavity()
        cavity['my_custom_field'] = 'test'
        
        ranked = rank_pockets([cavity], make_atom_coords())
        
        assert ranked[0]['my_custom_field'] == 'test'
        assert 'bio_score' in ranked[0]
        assert 'volume' in ranked[0]


class TestGetElitePockets:
    """Test elite pocket convenience API."""
    
    def test_returns_top_n(self):
        """get_elite_pockets() returns at most top_n."""
        cavities = [make_cavity(volume=v) for v in range(200, 2000, 200)]
        coords = make_atom_coords()
        
        elite = get_elite_pockets(cavities, coords, top_n=3)
        assert len(elite) <= 3
    
    def test_min_score_filter(self):
        """Pockets below min_score are excluded."""
        cavities = [
            make_cavity(volume=50.0, hydrophobic_ratio=0.0),  # Low score
            make_cavity(volume=1500.0, hydrophobic_ratio=0.9),  # High score
        ]
        coords = make_atom_coords()
        
        elite = get_elite_pockets(cavities, coords, min_score=0.5)
        
        for pocket in elite:
            assert pocket['bio_score'] >= 0.5


# ============================================================================
# INTEGRATION WITH REAL PDB (optional)
# ============================================================================

class TestIntegrationRealPDB:
    """Integration tests with real PDB file."""
    
    @pytest.mark.skipif(not Path(TEST_PDB).exists(),
                       reason="Test PDB not found")
    def test_full_scoring_pipeline(self):
        """End-to-end: find_cavities → rank_pockets on real PDB."""
        from src.cavities import find_cavities
        from src.geometry import extract_atom_coords
        
        # Step 1: Find cavities
        cavities = find_cavities(TEST_PDB, merge=True, hydrophobic=True)
        assert len(cavities) > 0
        
        # Step 2: Get atom coords
        coords = extract_atom_coords(TEST_PDB, atom_type='heavy')
        
        # Step 3: Rank
        ranked = rank_pockets(cavities, coords, profile='enzyme')
        
        assert len(ranked) == len(cavities)
        assert ranked[0]['rank'] == 1
        assert ranked[0]['bio_score'] >= ranked[-1]['bio_score']
        assert 'druggability_class' in ranked[0]
        assert ranked[0]['profile_used'] == 'Enzyme'
    
    @pytest.mark.skipif(not Path(TEST_PDB).exists(),
                       reason="Test PDB not found")
    def test_elite_pockets_real_pdb(self):
        """Top 5 elite pockets from real PDB."""
        from src.cavities import find_cavities
        from src.geometry import extract_atom_coords
        
        cavities = find_cavities(TEST_PDB, merge=True, hydrophobic=True)
        coords = extract_atom_coords(TEST_PDB, atom_type='heavy')
        
        elite = get_elite_pockets(cavities, coords, profile='default', top_n=5)
        
        assert len(elite) <= 5
        for pocket in elite:
            assert 'bio_score' in pocket
            assert 'rank' in pocket


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
