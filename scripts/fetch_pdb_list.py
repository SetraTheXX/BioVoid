#!/usr/bin/env python3
"""
Bio-Void Hunter: RCSB PDB List Fetcher (Phase 5.1)
====================================================

Fetches high-quality PDB IDs from RCSB PDB REST API v2.
Filters by resolution, experimental method, and polymer type.

Usage:
    python scripts/fetch_pdb_list.py --max-resolution 2.5 --output data/pdb_ids.json
    python scripts/fetch_pdb_list.py --limit 1000 --output data/pdb_ids_pilot.json

Author: Bio-Void Hunter Team
Version: 0.7.0 (Phase 5)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests


# RCSB PDB Search API v2
RCSB_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"

# Default filters
DEFAULT_MAX_RESOLUTION = 2.5  # Angstroms
DEFAULT_METHOD = "X-RAY DIFFRACTION"


def build_search_query(
    max_resolution: float = DEFAULT_MAX_RESOLUTION,
    method: str = DEFAULT_METHOD,
) -> dict[str, Any]:
    """
    Build RCSB PDB Search API v2 JSON query.

    Filters:
    - Resolution <= max_resolution (Angstrom)
    - Experimental method = method (X-RAY DIFFRACTION)
    - Entity type = polymer (protein chains)

    Args:
        max_resolution: Maximum allowed resolution in Angstroms.
        method: Experimental method string.

    Returns:
        JSON-serializable query dict for RCSB Search API v2.
    """
    query = {
        "query": {
            "type": "group",
            "logical_operator": "and",
            "nodes": [
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "rcsb_entry_info.resolution_combined",
                        "operator": "less_or_equal",
                        "value": max_resolution,
                    },
                },
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "exptl.method",
                        "operator": "exact_match",
                        "value": method,
                    },
                },
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "entity_poly.rcsb_entity_polymer_type",
                        "operator": "exact_match",
                        "value": "Protein",
                    },
                },
            ],
        },
        "return_type": "entry",
        "request_options": {
            "paginate": {
                "start": 0,
                "rows": 10,  # overridden per-call
            },
            "results_content_type": ["experimental"],
            "sort": [
                {
                    "sort_by": "rcsb_entry_info.resolution_combined",
                    "direction": "asc",
                }
            ],
        },
    }
    return query


def fetch_pdb_count(
    max_resolution: float = DEFAULT_MAX_RESOLUTION,
    method: str = DEFAULT_METHOD,
    timeout: int = 30,
) -> int:
    """
    Get total count of matching PDB entries without downloading all IDs.

    Returns:
        Number of matching PDB entries.

    Raises:
        requests.HTTPError: On API failure.
    """
    query = build_search_query(max_resolution, method)
    query["request_options"]["paginate"]["rows"] = 0  # count only

    resp = requests.post(RCSB_SEARCH_URL, json=query, timeout=timeout)
    resp.raise_for_status()

    data = resp.json()
    return data.get("total_count", 0)


def fetch_pdb_ids(
    max_resolution: float = DEFAULT_MAX_RESOLUTION,
    method: str = DEFAULT_METHOD,
    limit: int | None = None,
    batch_size: int = 5000,
    timeout: int = 60,
) -> list[str]:
    """
    Fetch PDB IDs from RCSB PDB Search API v2 with pagination.

    Downloads IDs in batches for robustness.

    Args:
        max_resolution: Maximum resolution filter.
        method: Experimental method filter.
        limit: Maximum IDs to fetch (None = all).
        batch_size: IDs per API request page.
        timeout: HTTP request timeout in seconds.

    Returns:
        List of PDB ID strings (e.g. ["1CBS", "1AKE", ...]).

    Raises:
        requests.HTTPError: On API failure.
    """
    total = fetch_pdb_count(max_resolution, method, timeout)
    target = min(total, limit) if limit else total
    print(f"[RCSB] Total matches: {total:,} | Fetching: {target:,}")

    pdb_ids: list[str] = []
    start = 0

    while start < target:
        rows = min(batch_size, target - start)
        query = build_search_query(max_resolution, method)
        query["request_options"]["paginate"]["start"] = start
        query["request_options"]["paginate"]["rows"] = rows

        resp = requests.post(RCSB_SEARCH_URL, json=query, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("result_set", [])
        if not results:
            break

        for entry in results:
            pdb_ids.append(entry["identifier"])

        start += len(results)
        print(f"  ... fetched {len(pdb_ids):,} / {target:,}", end="\r")

    print(f"\n[RCSB] Fetched {len(pdb_ids):,} PDB IDs")
    return pdb_ids


def save_pdb_list(
    pdb_ids: list[str],
    output_path: str | Path,
    max_resolution: float = DEFAULT_MAX_RESOLUTION,
) -> Path:
    """
    Save PDB ID list to JSON file with metadata.

    Args:
        pdb_ids: List of PDB IDs.
        output_path: Destination file path.
        max_resolution: Resolution filter used (for metadata).

    Returns:
        Path to saved JSON file.
    """
    outpath = Path(output_path)
    outpath.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "source": "RCSB PDB Search API v2",
        "filter_resolution": max_resolution,
        "filter_method": DEFAULT_METHOD,
        "total_ids": len(pdb_ids),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pdb_ids": pdb_ids,
    }

    with open(outpath, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"[SAVE] {len(pdb_ids):,} IDs saved to {outpath}")
    return outpath


# ---- CLI ----

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch high-quality PDB IDs from RCSB PDB",
    )
    parser.add_argument(
        "--max-resolution",
        type=float,
        default=DEFAULT_MAX_RESOLUTION,
        help=f"Max resolution in Angstroms (default: {DEFAULT_MAX_RESOLUTION})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max IDs to fetch (default: all)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/pdb_ids.json",
        help="Output JSON file path",
    )

    args = parser.parse_args()

    try:
        pdb_ids = fetch_pdb_ids(
            max_resolution=args.max_resolution,
            limit=args.limit,
        )
        save_pdb_list(pdb_ids, args.output, args.max_resolution)
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
