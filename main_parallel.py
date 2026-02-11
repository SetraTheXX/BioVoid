#!/usr/bin/env python3
"""
Bio-Void Hunter: Parallel Pipeline Runner (Phase 5.1)
======================================================

CLI for large-scale parallel PDB analysis.

Modes:
  fetch   — Download PDB ID list from RCSB API
  scan    — Parallel analysis of PDB list
  resume  — Continue interrupted scan from checkpoint
  status  — Show checkpoint progress

Usage:
  python main_parallel.py fetch --limit 1000 --output data/pdb_ids_pilot.json
  python main_parallel.py scan  --input data/pdb_ids_pilot.json --workers 8
  python main_parallel.py resume
  python main_parallel.py status

Author: Bio-Void Hunter Team
Version: 0.7.0 (Phase 5)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from scripts.fetch_pdb_list import fetch_pdb_ids, save_pdb_list
from src.parallel_crawler import ParallelCrawler


def cmd_fetch(args: argparse.Namespace) -> int:
    """Fetch PDB ID list from RCSB API."""
    print("=" * 60)
    print("PHASE 5.1 — RCSB PDB ID Fetcher")
    print("=" * 60)

    pdb_ids = fetch_pdb_ids(
        max_resolution=args.max_resolution,
        limit=args.limit,
    )
    save_pdb_list(pdb_ids, args.output, args.max_resolution)
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    """Run parallel scan on a PDB ID list."""
    print("=" * 60)
    print("PHASE 5.1 — Parallel Crawler Scan")
    print("=" * 60)

    # Load PDB IDs
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] Input file not found: {input_path}", file=sys.stderr)
        return 1

    with open(input_path) as f:
        data = json.load(f)

    pdb_ids = data.get("pdb_ids", data) if isinstance(data, dict) else data
    if not isinstance(pdb_ids, list):
        print("[ERROR] Invalid input format", file=sys.stderr)
        return 1

    if args.limit:
        pdb_ids = pdb_ids[: args.limit]

    print(f"Loaded {len(pdb_ids)} PDB IDs from {input_path}")

    crawler = ParallelCrawler(
        max_workers=args.workers,
        download_workers=args.download_workers,
        n_frames=args.n_frames,
        profile=args.profile,
        timeout=args.timeout,
        output_dir=args.output_dir,
        checkpoint_dir=args.checkpoint_dir,
        db_path=args.db if hasattr(args, "db") else None,
    )

    t0 = time.time()
    results = crawler.process_pdb_list(pdb_ids, resume=not args.fresh)
    crawler.close_db()
    elapsed = time.time() - t0

    # Summary
    success = sum(1 for r in results if r.get("status") == "success")
    failed = sum(1 for r in results if r.get("status") == "error")
    timeout = sum(1 for r in results if r.get("status") == "timeout")

    print("\n" + "=" * 60)
    print("SCAN SUMMARY")
    print("=" * 60)
    print(f"Total:     {len(results)}")
    print(f"Success:   {success}")
    print(f"Failed:    {failed}")
    print(f"Timeout:   {timeout}")
    print(f"Runtime:   {elapsed:.1f}s")
    if elapsed > 0:
        print(f"Throughput: {len(results) / elapsed:.2f} proteins/sec")
    print("=" * 60)
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    """Resume interrupted scan from checkpoint."""
    print("=" * 60)
    print("PHASE 5.1 — Resume from Checkpoint")
    print("=" * 60)

    crawler = ParallelCrawler(
        max_workers=args.workers,
        n_frames=args.n_frames,
        profile=args.profile,
        timeout=args.timeout,
        checkpoint_dir=args.checkpoint_dir,
    )

    state = crawler.get_checkpoint_state()
    if not state:
        print("[INFO] No checkpoint found. Nothing to resume.")
        return 0

    # Need original PDB list to know remaining
    if not args.input:
        print(
            "[ERROR] --input required for resume (original PDB list)",
            file=sys.stderr,
        )
        return 1

    with open(args.input) as f:
        data = json.load(f)
    pdb_ids = data.get("pdb_ids", data) if isinstance(data, dict) else data

    results = crawler.process_pdb_list(pdb_ids, resume=True)
    print(f"Resume complete: {len(results)} total results.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show checkpoint status."""
    crawler = ParallelCrawler(checkpoint_dir=args.checkpoint_dir)
    state = crawler.get_checkpoint_state()

    if not state:
        print("No checkpoint found.")
        return 0

    total = state.total_ids or len(state.processed_ids)
    done = len(state.processed_ids)
    ok = len(state.successful_ids)
    fail = len(state.failed_ids)
    skip = len(state.skipped_ids)
    pct = (done / total * 100) if total > 0 else 0

    print("=" * 60)
    print("CHECKPOINT STATUS")
    print("=" * 60)
    print(f"Total IDs:    {total}")
    print(f"Processed:    {done} ({pct:.1f}%)")
    print(f"Successful:   {ok}")
    print(f"Failed:       {fail}")
    print(f"Skipped:      {skip}")
    print(f"Elapsed:      {state.elapsed_seconds:.1f}s")
    print(f"Last saved:   {state.last_checkpoint_time}")
    print("=" * 60)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bio-Void Hunter: Parallel Pipeline (Phase 5.1)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- fetch ----
    p_fetch = sub.add_parser("fetch", help="Fetch PDB IDs from RCSB")
    p_fetch.add_argument("--max-resolution", type=float, default=2.5)
    p_fetch.add_argument("--limit", type=int, default=None)
    p_fetch.add_argument("--output", type=str, default="data/pdb_ids.json")

    # ---- scan ----
    p_scan = sub.add_parser("scan", help="Run parallel scan")
    p_scan.add_argument("--input", type=str, required=True)
    p_scan.add_argument("--workers", type=int, default=None)
    p_scan.add_argument("--download-workers", type=int, default=20)
    p_scan.add_argument("--n-frames", type=int, default=20)
    p_scan.add_argument("--profile", type=str, default="default")
    p_scan.add_argument("--timeout", type=int, default=120)
    p_scan.add_argument("--limit", type=int, default=None)
    p_scan.add_argument("--output-dir", type=str, default="data/results")
    p_scan.add_argument("--checkpoint-dir", type=str, default="data/checkpoints")
    p_scan.add_argument("--db", type=str, default=None, help="SQLite database path for results")
    p_scan.add_argument(
        "--fresh", action="store_true", help="Ignore existing checkpoint"
    )

    # ---- resume ----
    p_resume = sub.add_parser("resume", help="Resume from checkpoint")
    p_resume.add_argument("--input", type=str, default=None)
    p_resume.add_argument("--workers", type=int, default=None)
    p_resume.add_argument("--n-frames", type=int, default=20)
    p_resume.add_argument("--profile", type=str, default="default")
    p_resume.add_argument("--timeout", type=int, default=120)
    p_resume.add_argument(
        "--checkpoint-dir", type=str, default="data/checkpoints"
    )

    # ---- status ----
    p_status = sub.add_parser("status", help="Show checkpoint status")
    p_status.add_argument(
        "--checkpoint-dir", type=str, default="data/checkpoints"
    )

    args = parser.parse_args()

    # Auto-detect workers
    if hasattr(args, "workers") and args.workers is None:
        import multiprocessing
        args.workers = max(1, multiprocessing.cpu_count() - 1)

    dispatch = {
        "fetch": cmd_fetch,
        "scan": cmd_scan,
        "resume": cmd_resume,
        "status": cmd_status,
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
