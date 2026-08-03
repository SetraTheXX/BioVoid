#!/usr/bin/env python3
"""
fpocket Known-20 Pairing Builder
=================================

Builds a paired binary detection table for the 20 known cryptic pocket cases:
  - BioVoid detects? (from validation_results.json -> matched)
  - fpocket detects? (from fpocket_known20_direct_eval.json -> fpocket_detects)

Primary source: data/validation/fpocket_known20_direct_eval.json
  (produced by run_fpocket_known20_direct_eval.py)

McNemar computable rule:
  - All 20 cases must have paired data (fpocket_detects != None)
  - At least 1 discordant pair (n10 + n01 >= 1)

Usage:
    python scripts/build_fpocket_known20_pairing.py

Output:
    data/validation/fpocket_known20_pairing.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_RESULTS = REPO_ROOT / "data" / "validation" / "validation_results.json"
DIRECT_EVAL = REPO_ROOT / "data" / "validation" / "fpocket_known20_direct_eval.json"
OUTPUT = REPO_ROOT / "data" / "validation" / "fpocket_known20_pairing.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> Any | None:
    if not path.exists():
        print(f"[WARN] Missing: {path}")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    print("[INFO] Building fpocket known-20 pairing (direct eval source)...")

    # Load BioVoid detection results
    val_data = _load_json(VALIDATION_RESULTS)
    if not val_data:
        print("[ERROR] Cannot load validation_results.json")
        return 1
    bv_map: dict[str, bool] = {}
    for r in val_data.get("results", []):
        bv_map[r["pdb_id"].upper()] = bool(r.get("matched", False))

    # Load direct eval results (primary source for fpocket detection)
    de_data = _load_json(DIRECT_EVAL)
    if not de_data:
        print("[ERROR] Cannot load fpocket_known20_direct_eval.json")
        print("  Run: python scripts/run_fpocket_known20_direct_eval.py first.")
        return 1

    de_map: dict[str, dict[str, Any]] = {}
    for ev in de_data.get("evaluations", []):
        de_map[ev["pdb_id"].upper()] = ev

    print(f"[INFO] Direct eval data: {len(de_map)} cases.")

    # Build pairing table
    pairs: list[dict[str, Any]] = []
    n_available = 0
    n_unavailable = 0

    for ev in de_data.get("evaluations", []):
        pid = ev["pdb_id"].upper()
        bv_detects = bv_map.get(pid, False)
        fp_detects = ev.get("fpocket_detects")  # True, False, or None
        fp_status = ev.get("fpocket_status", "unknown")

        if fp_detects is not None:
            n_available += 1
            data_status = "available"
        else:
            n_unavailable += 1
            data_status = "unavailable"

        pairs.append({
            "pdb_id": pid,
            "name": ev.get("name", ""),
            "pocket_type": ev.get("pocket_type", ""),
            "biovoid_detects": bv_detects,
            "fpocket_detects": fp_detects,
            "fpocket_data_status": data_status,
            "fpocket_eval_status": fp_status,
            "best_distance": ev.get("best_distance"),
        })

    # McNemar contingency table (only for cases where both are available)
    available_pairs = [p for p in pairs if p["fpocket_data_status"] == "available"]
    n11 = sum(1 for p in available_pairs if p["biovoid_detects"] and p["fpocket_detects"])
    n10 = sum(1 for p in available_pairs if p["biovoid_detects"] and not p["fpocket_detects"])
    n01 = sum(1 for p in available_pairs if not p["biovoid_detects"] and p["fpocket_detects"])
    n00 = sum(1 for p in available_pairs if not p["biovoid_detects"] and not p["fpocket_detects"])

    # McNemar computable: paired_count == 20 (all cases must have data).
    # If discordant == 0, test is still computable with p_value = 1.0.
    paired_count = len(available_pairs)
    mcnemar_computable = paired_count == 20

    # Determine limitation text
    if n_unavailable > 0:
        limitation = (
            f"fpocket direct evaluation could not be completed for {n_unavailable}/{len(pairs)} cases "
            f"(fpocket binary not available, no cached results). "
            f"Only {n_available}/{len(pairs)} cases have paired data. "
            f"McNemar test requires all 20 cases to be evaluated."
        )
    else:
        limitation = "All 20 cases evaluated with direct fpocket-vs-known-pocket-center distance comparison."

    output = {
        "generated_at_utc": _utc_now_iso(),
        "source": "fpocket_known20_direct_eval.json",
        "total_cases": len(pairs),
        "fpocket_data_available": n_available,
        "fpocket_data_unavailable": n_unavailable,
        "pairs": pairs,
        "contingency_table": {
            "n11_both_detect": n11,
            "n10_biovoid_only": n10,
            "n01_fpocket_only": n01,
            "n00_neither": n00,
            "n_available_pairs": paired_count,
        },
        "mcnemar_computable": mcnemar_computable,
        "limitation": limitation,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"[INFO] Wrote: {OUTPUT}")

    print(f"[INFO] Pairing summary:")
    print(f"  Total cases: {len(pairs)}")
    print(f"  fpocket data available: {n_available}")
    print(f"  fpocket data unavailable: {n_unavailable}")
    print(f"  Contingency: n11={n11}, n10={n10}, n01={n01}, n00={n00}")
    print(f"  McNemar computable: {mcnemar_computable}")

    if not mcnemar_computable:
        if n_unavailable > 0:
            print(f"[WARN] McNemar NOT computable: {n_unavailable}/20 cases lack fpocket data.")
        elif (n10 + n01) < 1:
            print(f"[WARN] McNemar NOT computable: no discordant pairs (n10+n01=0).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
