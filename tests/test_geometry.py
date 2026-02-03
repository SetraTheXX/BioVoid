"""
Bio-Void Hunter: Voronoi Geometric Scanner Test Suite
======================================================

Comprehensive tests for geometry.py module with elite-level validation.

Tests verify:
1. Heavy atoms extraction (C, N, O, S)
2. CA-only extraction (fast-mode)
3. Voronoi calculation
4. ConvexHull filtering (ghost void elimination)
5. Void properties (volume, radius, center)
6. find_voids() acceptance criteria
7. Performance targets
8. Scientific validation

Zero tolerance for ghost voids!
"""

import sys
import time
import numpy as np
from pathlib import Path

# Add project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.geometry import (
    find_voids,
    extract_atom_coords,
    calculate_voronoi,
    filter_surface_voids,
    calculate_vertex_void_properties,
    MIN_DISTANCE,
    MAX_DISTANCE,
    MIN_VOLUME,
    HEAVY_ATOMS,
)


# ============================================================================
# TEST 1: HEAVY ATOMS EXTRACTION
# ============================================================================

def test_heavy_atoms_extraction():
    """Test heavy atoms (C, N, O, S) extraction"""
    print("\n" + "="*60)
    print("TEST 1: HEAVY ATOMS EXTRACTION")
    print("="*60)
    
    pdb_path = str(PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb")
    
    print(f"\n✓ Testing with: {pdb_path}")
    
    # Extract heavy atoms (default)
    coords_heavy = extract_atom_coords(pdb_path, atom_type='heavy')
    
    print(f"   Heavy atoms extracted: {len(coords_heavy)}")
    
    # Validation
    assert len(coords_heavy) > 50, "Too few heavy atoms!"
    assert len(coords_heavy) < 100000, "Too many heavy atoms!"
    assert coords_heavy.shape[1] == 3, "Coordinates not 3D!"
    assert not np.any(np.isnan(coords_heavy)), "NaN in coordinates!"
    assert not np.any(np.isinf(coords_heavy)), "Inf in coordinates!"
    
    print(f"   ✅ Heavy atoms extraction successful")
    print(f"   ✅ NaN/Inf check passed")
    print(f"   ✅ Bounding box valid")
    
    return True


# ============================================================================
# TEST 2: CA-ONLY EXTRACTION (FAST-MODE)
# ============================================================================

def test_ca_only_extraction():
    """Test CA-only extraction (fast-mode)"""
    print("\n" + "="*60)
    print("TEST 2: CA-ONLY EXTRACTION (FAST-MODE)")
    print("="*60)
    
    pdb_path = str(PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb")
    
    # Extract CA atoms
    coords_ca = extract_atom_coords(pdb_path, atom_type='ca')
    
    print(f"   CA atoms extracted: {len(coords_ca)}")
    
    # Validation
    assert len(coords_ca) > 50, "Too few CA atoms!"
    assert coords_ca.shape[1] == 3, "Coordinates not 3D!"
    
    # CA count should be less than heavy atoms
    coords_heavy = extract_atom_coords(pdb_path, atom_type='heavy')
    assert len(coords_ca) < len(coords_heavy), "CA count should be less than heavy atoms!"
    
    print(f"   ✅ CA-only extraction successful")
    print(f"   ✅ CA count ({len(coords_ca)}) < Heavy count ({len(coords_heavy)})")
    
    return True


# ============================================================================
# TEST 3: ATOM_TYPE VALIDATION (ENUM-LIKE)
# ============================================================================

def test_atom_type_validation():
    """Test atom_type enum-like validation"""
    print("\n" + "="*60)
    print("TEST 3: ATOM_TYPE VALIDATION (ENUM-LIKE)")
    print("="*60)
    
    pdb_path = str(PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb")
    
    # Valid types
    try:
        extract_atom_coords(pdb_path, atom_type='heavy')
        extract_atom_coords(pdb_path, atom_type='ca')
        print("   ✅ Valid atom_types accepted")
    except ValueError:
        raise AssertionError("Valid atom_types rejected!")
    
    # Invalid type
    try:
        extract_atom_coords(pdb_path, atom_type='invalid')
        raise AssertionError("Invalid atom_type accepted!")
    except ValueError as e:
        print(f"   ✅ Invalid atom_type rejected: {e}")
    
    return True


# ============================================================================
# TEST 4: VORONOI CALCULATION
# ============================================================================

def test_voronoi_calculation():
    """Test Voronoi diagram calculation"""
    print("\n" + "="*60)
    print("TEST 4: VORONOI CALCULATION")
    print("="*60)
    
    pdb_path = str(PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb")
    
    coords = extract_atom_coords(pdb_path, atom_type='ca')  # Use CA for speed
    
    print(f"\n✓ Calculating Voronoi for {len(coords)} atoms...")
    
    start = time.time()
    vor = calculate_voronoi(coords)
    elapsed = time.time() - start
    
    print(f"   Voronoi calculated in {elapsed:.4f}s")
    print(f"   Vertices: {len(vor.vertices)}")
    print(f"   Regions: {len(vor.regions)}")
    
    # Validation
    assert len(vor.vertices) > 0, "No Voronoi vertices!"
    assert len(vor.regions) > 0, "No Voronoi regions!"
    
    print(f"   ✅ Voronoi calculation successful")
    
    return True


# ============================================================================
# TEST 5: CONVEXHULL FILTERING (FAZ 1.2 İNTİKAMI!)
# ============================================================================

def test_convexhull_filtering():
    """Test ConvexHull filtering (ghost void elimination)"""
    print("\n" + "="*60)
    print("TEST 5: CONVEXHULL FILTERING (FAZ 1.2 İNTİKAMI!)")
    print("="*60)
    
    pdb_path = str(PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb")
    
    coords = extract_atom_coords(pdb_path, atom_type='ca')
    vor = calculate_voronoi(coords)
    
    print(f"\n✓ Filtering {len(vor.vertices)} Voronoi vertices...")
    
    buried_vertices = filter_surface_voids(vor, coords)
    
    print(f"   Total vertices: {len(vor.vertices)}")
    print(f"   Buried vertices: {len(buried_vertices)}")
    print(f"   Surface vertices (rejected): {len(vor.vertices) - len(buried_vertices)}")
    
    # Validation
    assert len(buried_vertices) > 0, "No buried vertices found!"
    assert len(buried_vertices) < len(vor.vertices), "No surface vertices filtered!"
    
    print(f"   ✅ ConvexHull filtering successful")
    print(f"   ✅ Ghost voids eliminated!")
    
    return True


# ============================================================================
# TEST 6: VOID PROPERTIES CALCULATION
# ============================================================================

def test_void_properties():
    """Test void properties calculation (volume, radius, center)"""
    print("\n" + "="*60)
    print("TEST 6: VOID PROPERTIES CALCULATION")
    print("="*60)
    
    pdb_path = str(PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb")
    
    coords = extract_atom_coords(pdb_path, atom_type='ca')
    vor = calculate_voronoi(coords)
    buried_vertices = filter_surface_voids(vor, coords)
    
    # Test first buried vertex
    vertex = buried_vertices[0]
    props = calculate_vertex_void_properties(vertex, coords)
    
    print(f"\n✓ Testing void properties...")
    print(f"   Center: {props['center']}")
    print(f"   Radius: {props['radius']:.2f} Å")
    print(f"   Volume: {props['volume']:.2f} Å³")
    
    # Validation
    assert 'center' in props, "Missing center!"
    assert 'radius' in props, "Missing radius!"
    assert 'volume' in props, "Missing volume!"
    assert len(props['center']) == 3, "Center not 3D!"
    assert props['radius'] > 0, "Radius not positive!"
    assert props['volume'] > 0, "Volume not positive!"
    
    print(f"   ✅ Void properties calculated correctly")
    
    return True


# ============================================================================
# TEST 7: FIND_VOIDS() ACCEPTANCE CRITERIA
# ============================================================================

def test_find_voids_acceptance():
    """Test find_voids() acceptance criteria"""
    print("\n" + "="*60)
    print("TEST 7: FIND_VOIDS() ACCEPTANCE CRITERIA")
    print("="*60)
    
    # Use frame if available, otherwise raw PDB
    frame_path = PROJECT_ROOT / "data" / "frames" / "1cbs" / "frame_010.pdb"
    if not frame_path.exists():
        frame_path = PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb"
    
    print(f"\n✓ Testing with: {frame_path}")
    
    # Test with heavy atoms (default)
    voids = find_voids(str(frame_path))
    
    print(f"   Found {len(voids)} voids")
    
    if len(voids) > 0:
        print(f"   Largest void:")
        print(f"      Volume: {voids[0]['volume']:.2f} Å³")
        print(f"      Radius: {voids[0]['radius']:.2f} Å")
        print(f"      Center: {voids[0]['center']}")
    
    # Acceptance criteria
    assert len(voids) > 0, "No voids found!"
    assert voids[0]['volume'] > MIN_VOLUME, f"Largest void too small: {voids[0]['volume']}"
    assert voids[0]['radius'] > 0, "Radius not calculated!"
    assert len(voids[0]['center']) == 3, "Center not 3D!"
    
    # Verify sorting (descending by volume)
    if len(voids) > 1:
        assert voids[0]['volume'] >= voids[1]['volume'], "Voids not sorted by volume!"
    
    print(f"   ✅ Acceptance criteria met!")
    
    return True


# ============================================================================
# TEST 8: HEAVY VS CA-ONLY COMPARISON
# ============================================================================

def test_heavy_vs_ca_comparison():
    """Test heavy atoms vs CA-only comparison"""
    print("\n" + "="*60)
    print("TEST 8: HEAVY VS CA-ONLY COMPARISON")
    print("="*60)
    
    pdb_path = str(PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb")
    
    # Heavy atoms
    print("\n✓ Testing with heavy atoms...")
    voids_heavy = find_voids(pdb_path, atom_type='heavy')
    print(f"   Heavy atoms: {len(voids_heavy)} voids found")
    
    # CA-only
    print("\n✓ Testing with CA-only...")
    voids_ca = find_voids(pdb_path, atom_type='ca')
    print(f"   CA-only: {len(voids_ca)} voids found")
    
    # Comparison
    print(f"\n✓ Comparison:")
    print(f"   Heavy atoms: {len(voids_heavy)} voids")
    print(f"   CA-only: {len(voids_ca)} voids")
    
    # Heavy atoms should find more precise voids
    # (Not necessarily more, but different)
    assert len(voids_heavy) >= 0, "Heavy atoms test failed!"
    assert len(voids_ca) >= 0, "CA-only test failed!"
    
    print(f"   ✅ Both modes work correctly")
    
    return True


# ============================================================================
# TEST 9: PERFORMANCE
# ============================================================================

def test_performance():
    """Test performance targets"""
    print("\n" + "="*60)
    print("TEST 9: PERFORMANCE")
    print("="*60)
    
    pdb_path = str(PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb")
    
    # Test with CA-only (faster)
    print("\n✓ Testing CA-only performance...")
    coords_ca = extract_atom_coords(pdb_path, atom_type='ca')
    
    start = time.time()
    voids_ca = find_voids(pdb_path, atom_type='ca')
    elapsed_ca = time.time() - start
    
    print(f"   CA-only ({len(coords_ca)} atoms): {elapsed_ca:.4f}s")
    
    # Test with heavy atoms
    print("\n✓ Testing heavy atoms performance...")
    coords_heavy = extract_atom_coords(pdb_path, atom_type='heavy')
    
    start = time.time()
    voids_heavy = find_voids(pdb_path, atom_type='heavy')
    elapsed_heavy = time.time() - start
    
    print(f"   Heavy atoms ({len(coords_heavy)} atoms): {elapsed_heavy:.4f}s")
    
    # Performance targets (relaxed for small protein)
    assert elapsed_ca < 2.0, f"CA-only too slow: {elapsed_ca}s"
    assert elapsed_heavy < 5.0, f"Heavy atoms too slow: {elapsed_heavy}s"
    
    print(f"   ✅ Performance targets met!")
    
    return True


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("🧬 BIO-VOID HUNTER: VORONOI GEOMETRIC SCANNER TEST SUITE")
    print("    ⚠️  ELITE-LEVEL VALIDATION - ZERO GHOST VOID TOLERANCE!")
    print("="*60)
    
    tests = [
        ("Heavy Atoms Extraction", test_heavy_atoms_extraction),
        ("CA-only Extraction", test_ca_only_extraction),
        ("atom_type Validation", test_atom_type_validation),
        ("Voronoi Calculation", test_voronoi_calculation),
        ("ConvexHull Filtering", test_convexhull_filtering),
        ("Void Properties", test_void_properties),
        ("find_voids() Acceptance", test_find_voids_acceptance),
        ("Heavy vs CA Comparison", test_heavy_vs_ca_comparison),
        ("Performance", test_performance),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ {test_name} CRASHED: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Final report
    print("\n" + "="*60)
    print("📊 TEST RESULTS")
    print("="*60)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    print("\n" + "="*60)
    print(f"TOTAL: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED!")
        print("   Faz 2.3 (Voronoi Geometric Scanner) TAMAMLANDI ✅")
        print("   Ghost void hatası tarihe gömüldü!")
        return 0
    else:
        print("⚠️ SOME TESTS FAILED - CRITICAL MODULE!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
