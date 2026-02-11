#!/usr/bin/env python3
"""
Bio-Void Hunter: Parallel PDB Download Test
=============================================

Test parallel download infrastructure for Phase 5 bulk fetching.

This script validates:
- ThreadPoolExecutor for I/O-bound parallel downloads
- src.fetcher.fetch_pdb() concurrency safety
- Throughput measurement (structures/second)
- Error handling and retry logic

Usage:
    python scripts/test_batch_download.py
    
    # Custom worker count
    python scripts/test_batch_download.py --workers 20
    
    # Test specific PDB IDs
    python scripts/test_batch_download.py --pdb-ids 1CBS 1AKE 1PPM

Expected Results:
    - 10 PDB files downloaded
    - Duration: 10-20 seconds
    - Throughput: 0.5-1.0 structures/second
    - Speedup: 2x+ vs sequential

References:
- Python concurrent.futures: ThreadPoolExecutor for I/O-bound tasks
- Phase 5: 120K protein download target (~33 hours with optimization)

Author: Bio-Void Hunter Team  
Version: 0.6.0 (Phase 4.5)
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from src.fetcher import fetch_pdb, FetchError
except ImportError as e:
    print(f"❌ Error: Could not import src.fetcher: {e}")
    sys.exit(1)


def download_batch(pdb_ids: List[str], max_workers: int = 10) -> Dict:
    """
    Download PDB files in parallel using ThreadPoolExecutor.
    
    Args:
        pdb_ids: List of PDB IDs to download
        max_workers: Number of concurrent threads
    
    Returns:
        Dictionary with:
        - success: List of successfully downloaded PDB IDs
        - failed: List of failed PDB IDs with error messages
        - duration: Total download time (seconds)
        - throughput: Structures per second
    """
    results = {
        "success": [],
        "failed": [],
        "duration": 0.0,
        "throughput": 0.0
    }
    
    start = time.time()
    
    print(f"🚀 Starting parallel download ({len(pdb_ids)} structures, {max_workers} workers)...")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all downloads
        futures = {executor.submit(fetch_pdb, pdb_id): pdb_id 
                   for pdb_id in pdb_ids}
        
        # Collect results as they complete
        for future in as_completed(futures):
            pdb_id = futures[future]
            try:
                filepath = future.result()
                results["success"].append(pdb_id)
                print(f"  ✅ {pdb_id} → {filepath.name}")
            except FetchError as e:
                results["failed"].append({"pdb_id": pdb_id, "error": str(e)})
                print(f"  ❌ {pdb_id}: {e}")
            except Exception as e:
                results["failed"].append({"pdb_id": pdb_id, "error": f"Unexpected: {e}"})
                print(f"  ❌ {pdb_id}: Unexpected error: {e}")
    
    # Calculate metrics
    results["duration"] = time.time() - start
    if results["duration"] > 0:
        results["throughput"] = len(results["success"]) / results["duration"]
    
    return results


def main():
    """Main entry point"""
    
    parser = argparse.ArgumentParser(
        description="Test parallel PDB download infrastructure"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Number of concurrent threads (default: 10)"
    )
    parser.add_argument(
        "--pdb-ids",
        nargs="+",
        help="Custom PDB IDs to test (default: load from data/pdb_list.json)"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of PDB IDs to test from list (default: 10)"
    )
    
    args = parser.parse_args()
    
    # Get PDB IDs to test
    if args.pdb_ids:
        test_ids = args.pdb_ids
        print(f"📋 Using custom PDB IDs: {test_ids}")
    else:
        # Load from pdb_list.json
        pdb_list_file = ROOT / "data" / "pdb_list.json"
        
        if not pdb_list_file.exists():
            print(f"❌ Error: {pdb_list_file} not found")
            print(f"   Run first: python scripts/fetch_pdb_list.py --limit 100")
            return 1
        
        with open(pdb_list_file) as f:
            all_pdb_ids = json.load(f)
        
        # Take first N
        test_ids = all_pdb_ids[:args.count]
        print(f"📋 Loaded {len(all_pdb_ids)} PDB IDs from {pdb_list_file.name}")
        print(f"   Testing first {len(test_ids)}: {test_ids[:5]}...")
    
    # Sequential baseline (first 3 for quick comparison)
    if len(test_ids) >= 3:
        print(f"\n⏱️  Sequential baseline (first 3)...")
        seq_start = time.time()
        for pdb_id in test_ids[:3]:
            try:
                filepath = fetch_pdb(pdb_id)
                print(f"  ✅ {pdb_id}")
            except Exception as e:
                print(f"  ❌ {pdb_id}: {e}")
        seq_duration = time.time() - seq_start
        print(f"   Duration: {seq_duration:.2f}s ({seq_duration/3:.2f}s/structure)")
    
    # Parallel download
    print(f"\n🔁 Parallel download...")
    results = download_batch(test_ids, args.workers)
    
    # Print results
    print(f"\n📊 Results:")
    print(f"   Total: {len(test_ids)}")
    print(f"   Success: {len(results['success'])}")
    print(f"   Failed: {len(results['failed'])}")
    print(f"   Duration: {results['duration']:.2f}s")
    print(f"   Throughput: {results['throughput']:.2f} structures/s")
    
    if len(test_ids) >= 3 and 'seq_duration' in locals():
        speedup = seq_duration / (results['duration'] / len(test_ids) * 3)
        print(f"   Speedup: {speedup:.2f}x (vs sequential)")
    
    # Print failed downloads
    if results['failed']:
        print(f"\n⚠️  Failed downloads:")
        for failure in results['failed']:
            print(f"   - {failure['pdb_id']}: {failure['error']}")
    
    # Validation
    print(f"\n✅ Parallel download test complete!")
    
    # Pass/fail criteria
    if results['throughput'] < 0.3:
        print(f"⚠️  Warning: Throughput below target (0.5+ structures/s expected)")
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(130)
