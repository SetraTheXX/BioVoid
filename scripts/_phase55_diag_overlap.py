#!/usr/bin/env python3
import json
import math
import statistics
from pathlib import Path

root = Path(__file__).resolve().parent.parent
fp = json.loads((root / "data/benchmark/fpocket_results/fpocket_batch_summary.json").read_text(encoding="utf-8"))
bv = json.loads((root / "data/benchmark/biovoid_results.json").read_text(encoding="utf-8"))

fpd = {
    str(r.get("pdb_id", "")).upper(): r
    for r in fp.get("results", [])
    if isinstance(r, dict) and r.get("status") == "ok"
}
bvd = {
    str(r.get("pdb_id", "")).upper(): r
    for r in bv.get("results", [])
    if isinstance(r, dict)
}
common = sorted([k for k in fpd.keys() if k in bvd.keys()])
sample = common[:12]

print("PDB,fp_n,bv_n,min_dist,median_nearest,within8,within8_and_vol_gate,median_fp_vol,median_bv_vol,median_ratio_fp_over_nearest_bv")

agg_w8 = 0
agg_w8vg = 0
agg_fp = 0
agg_bv = 0
all_ratios = []

for pdb in sample:
    fp_pockets = [
        p for p in fpd[pdb].get("pockets", [])
        if isinstance(p, dict) and isinstance(p.get("center"), list) and len(p.get("center")) == 3
    ]
    bv_pockets = [
        p for p in bvd[pdb].get("pockets", [])
        if isinstance(p, dict) and isinstance(p.get("center"), list) and len(p.get("center")) == 3
    ]

    agg_fp += len(fp_pockets)
    agg_bv += len(bv_pockets)

    nearest = []
    ratios = []
    w8 = 0
    w8vg = 0

    for f in fp_pockets:
        best_b = None
        best_d = float("inf")
        for b in bv_pockets:
            d = math.dist(f["center"], b["center"])
            if d < best_d:
                best_d = d
                best_b = b

        if best_b is None:
            continue

        nearest.append(best_d)
        fv = f.get("volume")
        bvvol = best_b.get("volume")

        ratio = None
        if isinstance(fv, (int, float)) and isinstance(bvvol, (int, float)) and fv > 0 and bvvol > 0:
            ratio = float(fv) / float(bvvol)
            ratios.append(ratio)
            all_ratios.append(ratio)

        if best_d <= 8.0:
            w8 += 1
            if ratio is not None and 0.5 <= ratio <= 2.0:
                w8vg += 1

    agg_w8 += w8
    agg_w8vg += w8vg

    fp_vols = [p.get("volume") for p in fp_pockets if isinstance(p.get("volume"), (int, float))]
    bv_vols = [p.get("volume") for p in bv_pockets if isinstance(p.get("volume"), (int, float))]

    print(
        "{},{},{},{:.3f},{:.3f},{},{},{:.3f},{:.3f},{:.6f}".format(
            pdb,
            len(fp_pockets),
            len(bv_pockets),
            min(nearest) if nearest else float("nan"),
            statistics.median(nearest) if nearest else float("nan"),
            w8,
            w8vg,
            statistics.median(fp_vols) if fp_vols else float("nan"),
            statistics.median(bv_vols) if bv_vols else float("nan"),
            statistics.median(ratios) if ratios else float("nan"),
        )
    )

print("AGG_WITHIN8", agg_w8)
print("AGG_WITHIN8_AND_VOL_GATE", agg_w8vg)
print("AGG_FP_TOTAL", agg_fp)
print("AGG_BV_TOTAL", agg_bv)
print("GLOBAL_MEDIAN_FP_BV_RATIO", statistics.median(all_ratios) if all_ratios else float("nan"))
