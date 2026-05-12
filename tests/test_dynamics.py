"""
Bio-Void Hunter: NMA Dynamics Engine Test Suite
================================================
CRITICAL: This test validates the heart of the project.

Tests verify:
1. Mathematical correctness (comparison with test_nma_math.py)
2. Conformation generation
3. File output
4. Performance targets

Zero tolerance for errors!
"""

import sys
import time
from pathlib import Path

import numpy as np

# Add project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Import original test functions for comparison
import test_nma_math

from src.dynamics import (
    DEFAULT_CUTOFF,
    DEFAULT_GAMMA,
    build_anm_hessian,
    calculate_normal_modes,
    load_ca_atoms,
    run_nma_simulation,
    validate_eigenvalues,
    validate_hessian,
    validate_trivial_modes,
)

# ============================================================================
# TEST 1: MATHEMATICAL IDENTITY WITH ORIGINAL CODE
# ============================================================================


def test_math_identity():
    """
    CRITICAL TEST: Verify refactored code produces IDENTICAL results
    to the original test_nma_math.py
    """
    print("\n" + "=" * 60)
    print("TEST 1: MATHEMATICAL IDENTITY (CRITICAL!)")
    print("=" * 60)

    # Use 1cbs for testing
    pdb_path = str(PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb")

    if not Path(pdb_path).exists():
        print(f"⚠️ Test file not found: {pdb_path}")
        print("   Downloading...")
        from src.fetcher import fetch_pdb

        pdb_path = str(fetch_pdb("1cbs"))

    print(f"\n✓ Testing with: {pdb_path}")

    # === ORIGINAL CODE (test_nma_math.py) ===
    print("\n📊 Running ORIGINAL test_nma_math.py code...")
    coords_orig, n_atoms_orig = test_nma_math.load_pdb_structure(pdb_path)
    hessian_orig = test_nma_math.build_anm_hessian(
        coords_orig, cutoff=DEFAULT_CUTOFF, gamma=DEFAULT_GAMMA
    )
    eigenvalues_orig, eigenvectors_orig = test_nma_math.calculate_normal_modes(
        hessian_orig, n_modes=10
    )

    # === REFACTORED CODE (src/dynamics.py) ===
    print("\n📊 Running REFACTORED src/dynamics.py code...")
    coords_new, n_atoms_new = load_ca_atoms(pdb_path)
    hessian_new = build_anm_hessian(coords_new, cutoff=DEFAULT_CUTOFF, gamma=DEFAULT_GAMMA)
    eigenvalues_new, eigenvectors_new = calculate_normal_modes(hessian_new, n_modes=10)

    # === COMPARE RESULTS ===
    print("\n🔍 Comparing results...")

    # 1. Coordinates match
    assert np.allclose(coords_orig, coords_new, atol=1e-12), "❌ Coordinates differ!"
    print("   ✅ Coordinates: IDENTICAL")

    # 2. Atom count matches
    assert n_atoms_orig == n_atoms_new, "❌ Atom count differs!"
    print(f"   ✅ Atom count: IDENTICAL ({n_atoms_new} CA atoms)")

    # 3. Hessian matrix matches
    hessian_diff = np.max(np.abs(hessian_orig - hessian_new))
    assert np.allclose(hessian_orig, hessian_new, atol=1e-12), (
        f"❌ Hessian differs! (max diff: {hessian_diff})"
    )
    print(f"   ✅ Hessian matrix: IDENTICAL (max diff: {hessian_diff:.2e})")

    # 4. Eigenvalues match (critical for physics!)
    eigenvalue_diff = np.max(np.abs(eigenvalues_orig - eigenvalues_new))
    assert np.allclose(eigenvalues_orig, eigenvalues_new, atol=1e-10), (
        f"❌ Eigenvalues differ! (max diff: {eigenvalue_diff})"
    )
    print(f"   ✅ Eigenvalues: IDENTICAL (max diff: {eigenvalue_diff:.2e})")

    # 5. Eigenvectors match (or are parallel - sign can differ)
    for i in range(eigenvalues_new.shape[0]):
        v1 = eigenvectors_orig[:, i]
        v2 = eigenvectors_new[:, i]
        # Eigenvectors are parallel if |dot product| ≈ 1
        dot = np.abs(np.dot(v1, v2))
        assert dot > 0.9999, f"❌ Eigenvector {i} not parallel! (dot: {dot})"
    print("   ✅ Eigenvectors: IDENTICAL (all parallel)")

    print("\n" + "=" * 60)
    print("🎉 MATHEMATICAL IDENTITY VERIFIED!")
    print("   Refactored code produces IDENTICAL results to original.")
    print("=" * 60)

    return True


# ============================================================================
# TEST 2: HESSIAN VALIDATION
# ============================================================================


def test_hessian_validation():
    """Test Hessian matrix properties"""
    print("\n" + "=" * 60)
    print("TEST 2: HESSIAN MATRIX VALIDATION")
    print("=" * 60)

    pdb_path = str(PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb")

    coords, n_atoms = load_ca_atoms(pdb_path)
    hessian = build_anm_hessian(coords)

    print("\n✓ Checking Hessian properties...")

    # Symmetry
    symmetry_diff = np.max(np.abs(hessian - hessian.T))
    assert np.allclose(hessian, hessian.T, atol=1e-10)
    print(f"   ✅ Symmetric: max diff = {symmetry_diff:.2e}")

    # Size
    expected_size = 3 * n_atoms
    assert hessian.shape == (expected_size, expected_size)
    print(f"   ✅ Size: {expected_size}x{expected_size}")

    # Validation function
    validate_hessian(hessian, n_atoms, DEFAULT_CUTOFF, DEFAULT_GAMMA)
    print("   ✅ validate_hessian() passed")

    return True


# ============================================================================
# TEST 3: TRIVIAL MODES
# ============================================================================


def test_trivial_modes():
    """Test that first 6 modes are trivial (near-zero eigenvalues)"""
    print("\n" + "=" * 60)
    print("TEST 3: TRIVIAL MODES VALIDATION")
    print("=" * 60)

    pdb_path = str(PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb")

    coords, n_atoms = load_ca_atoms(pdb_path)
    hessian = build_anm_hessian(coords)

    print("\n✓ Checking trivial modes (first 6)...")

    # Get all eigenvalues
    all_eigenvalues = np.linalg.eigvalsh(hessian)
    trivial = all_eigenvalues[:6]

    max_trivial = np.max(np.abs(trivial))
    print(f"   Max trivial eigenvalue: {max_trivial:.2e}")

    assert max_trivial < 1e-6, f"Trivial modes not near zero! ({max_trivial})"
    print("   ✅ First 6 modes are trivial (translation + rotation)")

    # Validation function
    validate_trivial_modes(hessian)
    print("   ✅ validate_trivial_modes() passed")

    return True


# ============================================================================
# TEST 4: EIGENVALUE PROPERTIES
# ============================================================================


def test_eigenvalue_properties():
    """Test eigenvalue physics"""
    print("\n" + "=" * 60)
    print("TEST 4: EIGENVALUE PROPERTIES")
    print("=" * 60)

    pdb_path = str(PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb")

    coords, _ = load_ca_atoms(pdb_path)
    hessian = build_anm_hessian(coords)
    eigenvalues, _ = calculate_normal_modes(hessian, n_modes=10)

    print("\n✓ Checking eigenvalue properties...")

    # All positive
    assert np.all(eigenvalues >= 0), "Negative eigenvalue found!"
    print(f"   ✅ All eigenvalues positive (min: {eigenvalues.min():.6f})")

    # Ascending order
    assert np.all(eigenvalues[:-1] <= eigenvalues[1:])
    print(f"   ✅ Ascending order (first: {eigenvalues[0]:.4f}, last: {eigenvalues[-1]:.4f})")

    # Reasonable range (from literature)
    assert eigenvalues[0] >= 0.5, f"First eigenvalue too low: {eigenvalues[0]}"
    assert eigenvalues[0] <= 5.0, f"First eigenvalue too high: {eigenvalues[0]}"
    print("   ✅ Frequency range reasonable (0.5-5.0)")

    # Validation function
    validate_eigenvalues(eigenvalues)
    print("   ✅ validate_eigenvalues() passed")

    return True


# ============================================================================
# TEST 5: CONFORMATION GENERATION
# ============================================================================


def test_conformation_generation():
    """Test frame generation"""
    print("\n" + "=" * 60)
    print("TEST 5: CONFORMATION GENERATION")
    print("=" * 60)

    pdb_path = str(PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb")

    # Run simulation (without saving files)
    result = run_nma_simulation(pdb_path, n_modes=5, n_frames=10, save_frames=False, verbose=False)

    conformations = result["conformations"]
    coords = result["coords"]

    print(f"\n✓ Generated {len(conformations)} conformations")

    # Correct count
    expected = 5 * 10  # n_modes * n_frames
    assert len(conformations) == expected, (
        f"Wrong count: {len(conformations)} (expected {expected})"
    )
    print(f"   ✅ Correct count: {expected} frames")

    # Each frame has correct shape
    for i, frame in enumerate(conformations):
        assert frame.shape == coords.shape, f"Frame {i} wrong shape: {frame.shape}"
    print(f"   ✅ All frames have shape {coords.shape}")

    # Frames are different (RMSD > 0)
    rmsds = []
    for frame in conformations[:10]:
        diff = frame - coords
        rmsd = np.sqrt(np.mean(diff**2))
        rmsds.append(rmsd)

    assert np.mean(rmsds) > 0.01, "Frames not different enough!"
    print(f"   ✅ Frames are different (mean RMSD: {np.mean(rmsds):.4f} Å)")

    return True


# ============================================================================
# TEST 6: FILE OUTPUT
# ============================================================================


def test_file_output():
    """Test PDB file saving"""
    print("\n" + "=" * 60)
    print("TEST 6: FILE OUTPUT")
    print("=" * 60)

    import shutil

    import biotite.structure.io.pdb as pdb_io

    pdb_path = str(PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb")
    output_dir = PROJECT_ROOT / "data" / "frames" / "test_1cbs"

    # Clean up previous test
    if output_dir.exists():
        shutil.rmtree(output_dir)

    # Run with file saving
    result = run_nma_simulation(
        pdb_path, n_modes=3, n_frames=5, output_dir=output_dir, save_frames=True, verbose=False
    )

    saved_files = result["saved_files"]

    print(f"\n✓ Saved {len(saved_files)} files")

    # Files exist
    for f in saved_files:
        assert f.exists(), f"File not found: {f}"
    print("   ✅ All files exist")

    # Files are readable PDB
    for f in saved_files[:3]:
        pdb_file = pdb_io.PDBFile.read(str(f))
        structure = pdb_file.get_structure()
        assert len(structure) > 0, f"Empty structure: {f}"
    print("   ✅ Files are valid PDB format")

    # File names correct
    assert saved_files[0].name == "frame_001.pdb"
    print("   ✅ File naming correct (frame_001.pdb, ...)")

    # Atom count preserved
    original_count = result["n_atoms"]
    pdb_file = pdb_io.PDBFile.read(str(saved_files[0]))
    frame_count = len(pdb_file.get_structure()[0])
    assert frame_count == original_count, f"Atom count changed: {frame_count} vs {original_count}"
    print(f"   ✅ Atom count preserved ({original_count} CA atoms)")

    return True


# ============================================================================
# TEST 7: PERFORMANCE
# ============================================================================


def test_performance():
    """Test performance targets"""
    print("\n" + "=" * 60)
    print("TEST 7: PERFORMANCE")
    print("=" * 60)

    pdb_path = str(PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb")

    # Test with 1cbs (137 CA atoms)
    print("\n✓ Testing 1cbs (137 CA atoms, 50 frames)...")

    start = time.time()
    result = run_nma_simulation(pdb_path, n_modes=10, n_frames=5, save_frames=False, verbose=False)
    elapsed = time.time() - start

    print(f"   Total time: {elapsed:.2f}s")
    print("   Timing breakdown:")
    for key, val in result["timing"].items():
        if key != "save":
            print(f"      - {key}: {val:.2f}s")

    # Target: < 10s for small protein
    assert elapsed < 10.0, f"Too slow: {elapsed}s (target: < 10s)"
    print("   ✅ Performance target met (< 10s)")

    return True


# ============================================================================
# TEST 8: FULL ACCEPTANCE CRITERIA
# ============================================================================


def test_acceptance_criteria():
    """Test against progress.md acceptance criteria"""
    print("\n" + "=" * 60)
    print("TEST 8: ACCEPTANCE CRITERIA (from progress.md)")
    print("=" * 60)

    print("\n✓ Running acceptance test...")

    pdb_path = str(PROJECT_ROOT / "data" / "raw_pdb" / "1cbs.pdb")

    try:
        result = run_nma_simulation(
            pdb_path, n_modes=5, n_frames=10, save_frames=False, verbose=False
        )
        frames = result["conformations"]
        assert len(frames) == 50  # 5 modes * 10 frames
        print("✅ Özel NMA Motoru başarılı")
        return True
    except Exception as e:
        print(f"❌ Acceptance test failed: {e}")
        return False


# ============================================================================
# MAIN
# ============================================================================


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("🧬 BIO-VOID HUNTER: NMA DYNAMICS ENGINE TEST SUITE")
    print("    ⚠️  CRITICAL MODULE - ZERO ERROR TOLERANCE!")
    print("=" * 60)

    tests = [
        ("Mathematical Identity", test_math_identity),
        ("Hessian Validation", test_hessian_validation),
        ("Trivial Modes", test_trivial_modes),
        ("Eigenvalue Properties", test_eigenvalue_properties),
        ("Conformation Generation", test_conformation_generation),
        ("File Output", test_file_output),
        ("Performance", test_performance),
        ("Acceptance Criteria", test_acceptance_criteria),
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
    print("\n" + "=" * 60)
    print("📊 TEST RESULTS")
    print("=" * 60)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    print("\n" + "=" * 60)
    print(f"TOTAL: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 ALL TESTS PASSED!")
        print("   Faz 2.2 (NMA Dynamics Engine) TAMAMLANDI ✅")
        print("   Matematik orijinal kodla BİREBİR!")
        return 0
    else:
        print("⚠️ SOME TESTS FAILED - CRITICAL MODULE!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
