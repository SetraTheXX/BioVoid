#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def _valid_center(center: Any) -> bool:
    return (
        isinstance(center, list)
        and len(center) == 3
        and all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in center)
    )


def _volume_match(fp_vol: Any, bv_vol: Any) -> bool:
    if not isinstance(fp_vol, (int, float)) or not isinstance(bv_vol, (int, float)):
        return True
    if not math.isfinite(float(fp_vol)) or not math.isfinite(float(bv_vol)):
        return True
    if fp_vol <= 0 or bv_vol <= 0:
        return True
    ratio = float(fp_vol) / float(bv_vol)
    return 0.5 <= ratio <= 2.0


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    fp = json.loads((root / "data/benchmark/fpocket_results/fpocket_batch_summary.json").read_text(encoding="utf-8"))
    bv = json.loads((root / "data/benchmark/biovoid_results.json").read_text(encoding="utf-8"))

    fp_by_id = {
        str(r.get("pdb_id", "")).upper(): r
        for r in fp.get("results", [])
        if isinstance(r, dict) and r.get("status") == "ok"
    }
    bv_by_id = {
        str(r.get("pdb_id", "")).upper(): r
        for r in bv.get("results", [])
        if isinstance(r, dict)
    }

    common = sorted(set(fp_by_id.keys()) & set(bv_by_id.keys()))

    aggregate = {
        "common_proteins": len(common),
        "distance_only_matches": 0,
        "distance_plus_volume_matches": 0,
        "distance_to_volume_drop": 0,
        "distance_fail": 0,
        "volume_fail": 0,
        "invalid_center": 0,
        "fpocket_valid_total": 0,
    }

    rows: list[dict[str, Any]] = []

    for pdb_id in common:
        fp_pockets = [p for p in fp_by_id[pdb_id].get("pockets", []) if isinstance(p, dict)]
        bv_pockets = [p for p in bv_by_id[pdb_id].get("pockets", []) if isinstance(p, dict)]

        fp_valid = [p for p in fp_pockets if _valid_center(p.get("center"))]
        bv_valid = [p for p in bv_pockets if _valid_center(p.get("center"))]

        fp_invalid = sum(1 for p in fp_pockets if not _valid_center(p.get("center")))
        bv_invalid = sum(1 for p in bv_pockets if not _valid_center(p.get("center")))

        distance_only = 0
        distance_plus_volume = 0
        distance_fail = 0
        volume_fail = 0

        for f in fp_valid:
            aggregate["fpocket_valid_total"] += 1

            within_tol = []
            for b in bv_valid:
                d = math.dist(f["center"], b["center"])
                if d <= 8.0:
                    within_tol.append(b)

            if not within_tol:
                distance_fail += 1
                aggregate["distance_fail"] += 1
                continue

            distance_only += 1
            aggregate["distance_only_matches"] += 1

            if any(_volume_match(f.get("volume"), b.get("volume")) for b in within_tol):
                distance_plus_volume += 1
                aggregate["distance_plus_volume_matches"] += 1
            else:
                volume_fail += 1
                aggregate["volume_fail"] += 1

        invalid_center = fp_invalid + bv_invalid
        aggregate["invalid_center"] += invalid_center

        rows.append(
            {
                "pdb_id": pdb_id,
                "fpocket_valid": len(fp_valid),
                "distance_only": distance_only,
                "distance_plus_volume": distance_plus_volume,
                "transition_drop": distance_only - distance_plus_volume,
                "distance_fail": distance_fail,
                "volume_fail": volume_fail,
                "invalid_center": invalid_center,
            }
        )

    aggregate["distance_to_volume_drop"] = (
        aggregate["distance_only_matches"] - aggregate["distance_plus_volume_matches"]
    )

    rows_sorted = sorted(rows, key=lambda r: (-r["transition_drop"], -r["distance_fail"], r["pdb_id"]))

    out = {
        "aggregate": aggregate,
        "top20_transition_drop": rows_sorted[:20],
    }

    out_path = root / "docs" / "phase55_gate_recovery_diag.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[OK] Wrote {out_path}")
    print(f"[INFO] Common proteins: {len(common)}")
    print(
        "[INFO] distance-only={0} distance+volume={1} drop={2}".format(
            aggregate["distance_only_matches"],
            aggregate["distance_plus_volume_matches"],
            aggregate["distance_to_volume_drop"],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
