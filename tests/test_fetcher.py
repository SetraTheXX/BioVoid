"""
Bio-Void Hunter: PDB Fetcher Test
==================================
Tests the fetcher module against all acceptance criteria from progress.md
"""

import sys
import time
import os
from pathlib import Path

# Add src to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.fetcher import fetch_pdb, get_structure, get_ca_atoms, FetchError


def test_basic_functionality():
    """Test 1: Basic download functionality"""
    print("\n" + "="*60)
    print("TEST 1: BASIC FUNCTIONALITY")
    print("="*60)
    
    # Test valid PDB ID
    print("\n✓ Testing valid PDB ID ('1cbs')...")
    try:
        filepath = fetch_pdb('1cbs')
        assert os.path.exists(filepath), "File does not exist!"
        print(f"  ✅ File downloaded: {filepath}")
        
        # Verify file is in correct directory
        assert "data/raw_pdb" in str(filepath) or "data\\raw_pdb" in str(filepath)
        print(f"  ✅ File in correct directory")
        
        # Verify file name
        assert filepath.name == "1cbs.pdb"
        print(f"  ✅ Correct filename: {filepath.name}")
        
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        return False
    
    return True


def test_caching():
    """Test 2: Cache functionality"""
    print("\n" + "="*60)
    print("TEST 2: CACHE FUNCTIONALITY")
    print("="*60)
    
    print("\n✓ Testing cache (second call should be instant)...")
    
    # First call (might download)
    start = time.time()
    filepath1 = fetch_pdb('1cbs')
    time1 = time.time() - start
    
    # Second call (should use cache)
    start = time.time()
    filepath2 = fetch_pdb('1cbs')
    time2 = time.time() - start
    
    print(f"  First call: {time1:.4f}s")
    print(f"  Second call: {time2:.4f}s")
    
    # Cache should be much faster
    if time2 < 0.1:
        print(f"  ✅ Cache working (< 0.1s)")
    else:
        print(f"  ⚠️ Cache might not be working ({time2:.4f}s)")
    
    # Files should be the same
    assert filepath1 == filepath2
    print(f"  ✅ Same file returned")
    
    return True


def test_error_handling():
    """Test 3: Error handling"""
    print("\n" + "="*60)
    print("TEST 3: ERROR HANDLING")
    print("="*60)
    
    # Test invalid PDB ID
    print("\n✓ Testing invalid PDB ID ('XXXX')...")
    try:
        fetch_pdb('XXXX')
        print(f"  ❌ Should have raised error!")
        return False
    except FetchError as e:
        print(f"  ✅ Correct error raised: {str(e)[:80]}...")
    
    # Test invalid format
    print("\n✓ Testing invalid format ('12')...")
    try:
        fetch_pdb('12')
        print(f"  ❌ Should have raised error!")
        return False
    except FetchError as e:
        print(f"  ✅ Correct error raised: {str(e)[:80]}...")
    
    return True


def test_performance():
    """Test 4: Performance"""
    print("\n" + "="*60)
    print("TEST 4: PERFORMANCE")
    print("="*60)
    
    # Test with small protein (1CRN)
    print("\n✓ Testing download performance (1CRN)...")
    
    # Clear cache for this test
    cache_dir = PROJECT_ROOT / "data" / "raw_pdb"
    test_file = cache_dir / "1crn.pdb"
    if test_file.exists():
        test_file.unlink()
    
    start = time.time()
    filepath = fetch_pdb('1crn')
    download_time = time.time() - start
    
    print(f"  Download time: {download_time:.2f}s")
    
    if download_time < 5.0:
        print(f"  ✅ Performance good (< 5s)")
    else:
        print(f"  ⚠️ Slow download ({download_time:.2f}s) - might be network")
    
    # Test cache performance
    start = time.time()
    filepath = fetch_pdb('1crn')
    cache_time = time.time() - start
    
    print(f"  Cache time: {cache_time:.4f}s")
    
    if cache_time < 0.1:
        print(f"  ✅ Cache performance excellent (< 0.1s)")
    else:
        print(f"  ⚠️ Cache slower than expected ({cache_time:.4f}s)")
    
    return True


def test_structure_loading():
    """Test 5: Structure loading helpers"""
    print("\n" + "="*60)
    print("TEST 5: STRUCTURE LOADING")
    print("="*60)
    
    print("\n✓ Testing structure loading...")
    filepath = fetch_pdb('1cbs')
    
    structure = get_structure(filepath)
    print(f"  ✅ Structure loaded: {len(structure)} atoms")
    
    ca_atoms = get_ca_atoms(structure)
    print(f"  ✅ CA atoms extracted: {len(ca_atoms)} atoms")
    
    # Verify CA atoms are subset of structure
    assert len(ca_atoms) < len(structure)
    print(f"  ✅ CA atoms < total atoms")
    
    return True


def test_acceptance_criteria():
    """Final acceptance test from progress.md"""
    print("\n" + "="*60)
    print("ACCEPTANCE CRITERIA (from progress.md)")
    print("="*60)
    
    print("\n✓ Running acceptance test...")
    
    try:
        from src.fetcher import fetch_pdb
        filepath = fetch_pdb('1cbs')
        assert os.path.exists(filepath)
        print("✅ PDB Fetcher çalışıyor")
        return True
    except Exception as e:
        print(f"❌ Acceptance test failed: {e}")
        return False


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("🧬 BIO-VOID HUNTER: PDB FETCHER TEST SUITE")
    print("="*60)
    
    tests = [
        ("Basic Functionality", test_basic_functionality),
        ("Caching", test_caching),
        ("Error Handling", test_error_handling),
        ("Performance", test_performance),
        ("Structure Loading", test_structure_loading),
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
        print("   Faz 2.1 (PDB Fetcher) TAMAMLANDI ✅")
        return 0
    else:
        print("⚠️ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
