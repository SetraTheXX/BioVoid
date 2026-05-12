"""
Test Suite for Phase 2.4: Cavity Analysis Module
=================================================

Tests for:
- Ridge-based volume calculation
- Cavity merging (hierarchical clustering)
- Dual radii calculation
- Hydrophobic filtering
- find_cavities() API
"""

from pathlib import Path

import numpy as np
import pytest

from src.cavities import (
    MERGE_THRESHOLD,
    calculate_cavity_properties,
    calculate_region_volume,
    filter_hydrophobic,
    find_cavities,
    merge_cavities,
)
from src.geometry import calculate_voronoi, extract_atom_coords, find_voids

# Test data paths
TEST_PDB = "data/raw_pdb/1cbs.pdb"
FRAME_PDB = "data/frames/1cbs/frame_010.pdb"


class TestCavityMerging:
    """Test cavity merging functionality"""

    def test_merge_empty_voids(self):
        """Test merging with empty void list"""
        cavities = merge_cavities([])
        assert len(cavities) == 0

    def test_merge_single_void(self):
        """Test merging with single void"""
        void = {"center": np.array([1.0, 2.0, 3.0]), "volume": 300.0, "radius": 5.0}
        cavities = merge_cavities([void])

        assert len(cavities) == 1
        assert cavities[0]["merged_vertices"] == 1
        assert cavities[0]["merge_threshold"] == MERGE_THRESHOLD

    def test_merge_distant_voids(self):
        """Test merging with distant voids (should stay separate)"""
        voids = [
            {"center": np.array([0.0, 0.0, 0.0]), "volume": 300.0, "radius": 5.0},
            {"center": np.array([20.0, 20.0, 20.0]), "volume": 300.0, "radius": 5.0},
        ]
        cavities = merge_cavities(voids, merge_threshold=3.0)

        # Should remain separate (distance > 3.0 Å)
        assert len(cavities) == 2

    def test_merge_close_voids(self):
        """Test merging with close voids (should merge)"""
        voids = [
            {"center": np.array([0.0, 0.0, 0.0]), "volume": 300.0, "radius": 5.0},
            {"center": np.array([2.0, 0.0, 0.0]), "volume": 300.0, "radius": 5.0},
        ]
        cavities = merge_cavities(voids, merge_threshold=3.0)

        # Should merge (distance < 3.0 Å)
        assert len(cavities) == 1
        assert cavities[0]["merged_vertices"] == 2


class TestCavityProperties:
    """Test cavity property calculation"""

    def test_dual_radii_single_vertex(self):
        """Test dual radii with single vertex"""
        cavity = {"vertices": [np.array([0.0, 0.0, 0.0])]}
        coords = np.array([[5.0, 0.0, 0.0], [0.0, 5.0, 0.0]])

        result = calculate_cavity_properties(cavity, coords)

        assert "radius_geom" in result
        assert "radius_clear" in result
        assert result["radius_geom"] == 0.0  # Single vertex
        assert result["radius_clear"] == pytest.approx(5.0, abs=0.1)

    def test_dual_radii_multiple_vertices(self):
        """Test dual radii with multiple vertices"""
        cavity = {
            "vertices": [
                np.array([0.0, 0.0, 0.0]),
                np.array([3.0, 0.0, 0.0]),
            ]
        }
        coords = np.array([[10.0, 0.0, 0.0]])

        result = calculate_cavity_properties(cavity, coords)

        assert result["radius_geom"] > 0.0  # Distance between vertices
        assert result["radius_clear"] > 0.0  # Distance to nearest atom


class TestFindCavities:
    """Test main find_cavities() API"""

    @pytest.mark.skipif(not Path(TEST_PDB).exists(), reason="Test PDB not found")
    def test_find_cavities_basic(self):
        """Test basic cavity finding"""
        cavities = find_cavities(TEST_PDB, merge=True, hydrophobic=False)

        assert isinstance(cavities, list)
        if len(cavities) > 0:
            assert "center" in cavities[0]
            assert "volume" in cavities[0]
            assert "merged_vertices" in cavities[0]
            assert "radius_geom" in cavities[0]
            assert "radius_clear" in cavities[0]

    @pytest.mark.skipif(not Path(TEST_PDB).exists(), reason="Test PDB not found")
    def test_find_cavities_no_merge(self):
        """Test cavity finding without merging"""
        cavities = find_cavities(TEST_PDB, merge=False, hydrophobic=False)

        if len(cavities) > 0:
            # Without merging, each cavity should have 1 vertex
            assert cavities[0]["merged_vertices"] == 1

    @pytest.mark.skipif(not Path(TEST_PDB).exists(), reason="Test PDB not found")
    def test_find_cavities_with_hydrophobic(self):
        """Test cavity finding with hydrophobic filtering"""
        cavities = find_cavities(TEST_PDB, merge=True, hydrophobic=True)

        if len(cavities) > 0:
            assert "druggable" in cavities[0]
            assert "hydrophobic_ratio" in cavities[0]
            assert "polar_atoms" in cavities[0]

    @pytest.mark.skipif(not Path(TEST_PDB).exists(), reason="Test PDB not found")
    def test_backward_compatibility(self):
        """Test that find_voids() still works (backward compatibility)"""
        min_vol = 100.0
        voids = find_voids(TEST_PDB, min_volume=min_vol)
        cavities = find_cavities(TEST_PDB, min_volume=min_vol, merge=False, hydrophobic=False)

        # Without merge, cavity count should match void count (within max_volume filter)
        assert len(cavities) <= len(voids)
        assert len(cavities) > 0


class TestHydrophobicFiltering:
    """Test hydrophobic filtering"""

    @pytest.mark.skipif(not Path(TEST_PDB).exists(), reason="Test PDB not found")
    def test_hydrophobic_filter_structure(self):
        """Test hydrophobic filter output structure"""
        # Get some cavities first
        cavities = find_cavities(TEST_PDB, merge=True, hydrophobic=False)

        if len(cavities) > 0:
            # Apply hydrophobic filter
            filtered = filter_hydrophobic(cavities, TEST_PDB)

            assert len(filtered) == len(cavities)
            for cavity in filtered:
                assert "druggable" in cavity
                assert "hydrophobic_ratio" in cavity
                assert "polar_atoms" in cavity
                assert isinstance(cavity["druggable"], bool)
                assert 0.0 <= cavity["hydrophobic_ratio"] <= 1.0


class TestPerformance:
    """Performance benchmarks"""

    @pytest.mark.skipif(not Path(TEST_PDB).exists(), reason="Test PDB not found")
    def test_performance_benchmark(self):
        """Test that cavity analysis completes in reasonable time"""
        import time

        start = time.time()
        find_cavities(TEST_PDB, merge=True, hydrophobic=True)
        elapsed = time.time() - start

        # Should complete in < 5 seconds for small protein
        assert elapsed < 5.0, f"Cavity analysis took {elapsed:.2f}s (expected < 5s)"


class TestVolumeCalculation:
    """Test volume calculation methods"""

    @pytest.mark.skipif(not Path(TEST_PDB).exists(), reason="Test PDB not found")
    def test_ridge_based_volume(self):
        """Test ridge-based volume calculation"""
        coords = extract_atom_coords(TEST_PDB, atom_type="heavy")
        vor = calculate_voronoi(coords)

        # Test on first few vertices
        for i in range(min(5, len(vor.vertices))):
            volume = calculate_region_volume(i, vor)
            assert volume >= 0.0  # Volume should be non-negative


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
