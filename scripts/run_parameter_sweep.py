#!/usr/bin/env python3
"""
P1.1.2 Parameter Sweep — Recall Recovery Analysis
===================================================

Uses EXISTING experiment results (recall_recovery_experiments.json) to
perform offline parameter sensitivity analysis.

- Tolerance sweep: re-evaluate hit/miss using different distance thresholds.
  No pipeline re-run needed; we already have best_distance for every pocket.
- Top-N sweep: requires re-evaluation (run validate_known_pockets.py).
- Consensus-distance sweep: requires re-evaluation.

This script optimises for speed: tolerance analysis is instant (pure JSON
re-eval), while pipeline-dependent sweeps are triggered via subprocesses
when specifically requested.
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def load_experiments(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Tolerance Sweep (offline, instant) ────────────────────────────────────
def tolerance_sweep(
    results: list[dict[str, Any]],
    tolerances: list[float],
) -> list[dict[str, Any]]:
    """Re-evaluate hit/miss at different tolerance thresholds."""
    sweep_rows: list[dict[str, Any]] = []

    for tol in tolerances:
        hits = []
        misses = []
        distances: list[float] = []

        for r in results:
            dist = r.get("best_distance")
            if dist is None:
                misses.append(r)
                continue

            distances.append(dist)
            if dist <= tol:
                hits.append(r)
            else:
                misses.append(r)

        recall = len(hits) / len(results) if results else 0.0
        avg_dist = sum(distances) / len(distances) if distances else 0.0

        # by-type breakdown
        by_type: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "hits": 0})
        for r in results:
            pt = r["pocket_type"]
            by_type[pt]["total"] += 1
            dist = r.get("best_distance")
            if dist is not None and dist <= tol:
                by_type[pt]["hits"] += 1
        for v in by_type.values():
            v["rate"] = v["hits"] / v["total"] if v["total"] else 0.0

        sweep_rows.append(
            {
                "tolerance": tol,
                "recall": recall,
                "hits": len(hits),
                "total": len(results),
                "avg_distance": avg_dist,
                "hit_pdb_ids": [r["pdb_id"] for r in hits],
                "near_miss_pdb_ids": [
                    r["pdb_id"]
                    for r in misses
                    if r.get("best_distance") is not None
                    and r["best_distance"] <= tol + 2.0
                ],
                "by_type": dict(by_type),
            }
        )

    return sweep_rows


# ── Delta Analysis (single vs multi at each tolerance) ────────────────────
def delta_analysis(
    single_results: list[dict[str, Any]],
    multi_results: list[dict[str, Any]],
    tolerances: list[float],
) -> list[dict[str, Any]]:
    """Compare single vs multi recall at different tolerances."""
    rows: list[dict[str, Any]] = []

    for tol in tolerances:
        s_hits = sum(
            1
            for r in single_results
            if r.get("best_distance") is not None and r["best_distance"] <= tol
        )
        m_hits = sum(
            1
            for r in multi_results
            if r.get("best_distance") is not None and r["best_distance"] <= tol
        )
        total = len(single_results)
        rows.append(
            {
                "tolerance": tol,
                "single_hits": s_hits,
                "multi_hits": m_hits,
                "single_recall": s_hits / total if total else 0.0,
                "multi_recall": m_hits / total if total else 0.0,
                "delta_recall": (m_hits - s_hits) / total if total else 0.0,
            }
        )

    return rows


# ── Near-Miss Analysis ────────────────────────────────────────────────────
def near_miss_analysis(
    results: list[dict[str, Any]],
    tolerance: float = 8.0,
) -> list[dict[str, Any]]:
    """Identify pockets that are close to threshold — potential gains."""
    near: list[dict[str, Any]] = []
    for r in results:
        dist = r.get("best_distance")
        if dist is None:
            continue
        if dist > tolerance:
            gap = dist - tolerance
            near.append(
                {
                    "pdb_id": r["pdb_id"],
                    "protein_name": r["protein_name"],
                    "pocket_type": r["pocket_type"],
                    "best_distance": dist,
                    "gap_to_tolerance": gap,
                    "tolerance_needed": dist,
                    "category": (
                        "NEAR_MISS"
                        if gap <= 2.0
                        else "CLOSE" if gap <= 7.0 else "FAR" if gap <= 20.0 else "VERY_FAR"
                    ),
                }
            )
    near.sort(key=lambda x: x["best_distance"])
    return near


# ── Per-pocket single→multi delta detail ──────────────────────────────────
def per_pocket_delta(
    single_results: list[dict[str, Any]],
    multi_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-pocket distance change: single → multi."""
    multi_map = {r["pdb_id"]: r for r in multi_results}
    deltas: list[dict[str, Any]] = []
    for sr in single_results:
        mr = multi_map.get(sr["pdb_id"])
        if not mr:
            continue
        sd = sr.get("best_distance")
        md = mr.get("best_distance")
        if sd is None or md is None:
            continue
        deltas.append(
            {
                "pdb_id": sr["pdb_id"],
                "protein_name": sr["protein_name"],
                "pocket_type": sr["pocket_type"],
                "single_distance": round(sd, 2),
                "multi_distance": round(md, 2),
                "delta": round(md - sd, 2),
                "improved": md < sd,
                "regressed": md > sd + 0.1,
            }
        )
    deltas.sort(key=lambda x: x["delta"])
    return deltas


# ── Markdown Report ───────────────────────────────────────────────────────
def generate_report(
    sweep_single: list[dict[str, Any]],
    sweep_multi: list[dict[str, Any]],
    delta: list[dict[str, Any]],
    near_single: list[dict[str, Any]],
    near_multi: list[dict[str, Any]],
    pocket_delta: list[dict[str, Any]],
    output_path: Path,
) -> None:
    lines = [
        "# P1.1.2 Parameter Sweep Results",
        "",
        f"> **Generated:** {datetime.now().isoformat(timespec='seconds')}",
        "> **Method:** Offline re-evaluation of existing experiment data",
        "> **Base Data:** `data/validation/recall_recovery_experiments.json`",
        "",
        "---",
        "",
        "## 1) Tolerance Sweep — Single Frame",
        "",
        "| Tolerance | Hits | Total | Recall | Hit PDB IDs |",
        "|-----------|------|-------|--------|-------------|",
    ]
    for row in sweep_single:
        ids = ", ".join(row["hit_pdb_ids"]) if row["hit_pdb_ids"] else "—"
        lines.append(
            f"| {row['tolerance']:.1f}Å | {row['hits']} | {row['total']} "
            f"| **{row['recall']*100:.1f}%** | {ids} |"
        )

    lines.extend(
        [
            "",
            "## 2) Tolerance Sweep — Multi Frame",
            "",
            "| Tolerance | Hits | Total | Recall | Hit PDB IDs |",
            "|-----------|------|-------|--------|-------------|",
        ]
    )
    for row in sweep_multi:
        ids = ", ".join(row["hit_pdb_ids"]) if row["hit_pdb_ids"] else "—"
        lines.append(
            f"| {row['tolerance']:.1f}Å | {row['hits']} | {row['total']} "
            f"| **{row['recall']*100:.1f}%** | {ids} |"
        )

    lines.extend(
        [
            "",
            "## 3) Single vs Multi Delta (by Tolerance)",
            "",
            "| Tolerance | Single Recall | Multi Recall | Δ Recall |",
            "|-----------|--------------|--------------|----------|",
        ]
    )
    for row in delta:
        delta_str = f"{row['delta_recall']*100:+.1f}%"
        lines.append(
            f"| {row['tolerance']:.1f}Å "
            f"| {row['single_recall']*100:.1f}% "
            f"| {row['multi_recall']*100:.1f}% "
            f"| {delta_str} |"
        )

    # Pocket type breakdown at key tolerances
    lines.extend(
        [
            "",
            "## 4) Pocket Type Breakdown (Multi-Frame)",
            "",
        ]
    )
    key_tols = [8.0, 10.0, 12.0, 14.0, 15.0]
    for row in sweep_multi:
        if row["tolerance"] not in key_tols:
            continue
        lines.append(f"### Tolerance = {row['tolerance']:.1f}Å")
        lines.append("")
        lines.append("| Pocket Type | Hits | Total | Rate |")
        lines.append("|-------------|------|-------|------|")
        for pt, stats in sorted(row["by_type"].items()):
            lines.append(
                f"| {pt} | {stats['hits']} | {stats['total']} "
                f"| {stats['rate']*100:.0f}% |"
            )
        lines.append("")

    # Near misses
    lines.extend(
        [
            "## 5) Near-Miss Analysis (Multi-Frame, tolerance=8.0Å)",
            "",
            "| PDB ID | Protein | Type | Distance | Gap | Category |",
            "|--------|---------|------|----------|-----|----------|",
        ]
    )
    for nm in near_multi:
        lines.append(
            f"| {nm['pdb_id']} | {nm['protein_name'][:25]} | {nm['pocket_type']} "
            f"| {nm['best_distance']:.2f}Å | +{nm['gap_to_tolerance']:.2f}Å | {nm['category']} |"
        )

    # Per-pocket delta
    lines.extend(
        [
            "",
            "## 6) Per-Pocket Multi-Frame Delta",
            "",
            "| PDB ID | Protein | Type | Single Dist | Multi Dist | Δ | Status |",
            "|--------|---------|------|------------|------------|------|--------|",
        ]
    )
    for pd in pocket_delta:
        status = "✅ improved" if pd["improved"] else ("🔴 regressed" if pd["regressed"] else "➡️ same")
        lines.append(
            f"| {pd['pdb_id']} | {pd['protein_name'][:25]} | {pd['pocket_type']} "
            f"| {pd['single_distance']:.2f}Å | {pd['multi_distance']:.2f}Å "
            f"| {pd['delta']:+.2f}Å | {status} |"
        )

    # Recommendations
    lines.extend(
        [
            "",
            "---",
            "",
            "## 7) Recommendations",
            "",
            "### Gate Re-Run (tolerance=8.0Å, fixed)",
            "",
            "Current recall at 8.0Å:",
        ]
    )
    for row in sweep_multi:
        if row["tolerance"] == 8.0:
            lines.append(f"- **{row['recall']*100:.1f}%** ({row['hits']}/{row['total']})")
    lines.extend(
        [
            "",
            "### Exploratory (tolerance change — NOT for gate)",
            "",
        ]
    )
    for row in sweep_multi:
        if row["tolerance"] in [10.0, 12.0, 14.0, 15.0]:
            lines.append(
                f"- tolerance={row['tolerance']:.0f}Å → recall **{row['recall']*100:.1f}%** "
                f"(+{row['hits'] - sweep_multi[0]['hits']} pockets vs 8Å)"
            )

    lines.extend(
        [
            "",
            "### ⚠️ Pre-Registration Drift Warning",
            "",
            "Tolerance changes for gate rerun = PRE-REGISTRATION DRIFT.",
            "Only algorithmically improved recall counts for the official gate.",
            "",
            "### Priority Actions",
            "",
            "1. **CA→Heavy-atom Voronoi** — systematic offset reduction (est. +5-10% recall)",
            "2. **Consensus distance 4→6-8Å** — prevent regression (3ERT, 1G4E cases)",
            "3. **Known pocket coordinate validation** — remove outliers (1YET, 1STP)",
            "",
            "---",
            "",
            f"*Generated by P1.1.2 Parameter Sweep Script — {datetime.now().isoformat(timespec='seconds')}*",
        ]
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="P1.1.2 Parameter Sweep")
    parser.add_argument(
        "--input",
        type=str,
        default="data/validation/recall_recovery_experiments.json",
        help="Path to existing experiment results",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default="data/validation/parameter_sweep_results.json",
        help="Output JSON for sweep results",
    )
    parser.add_argument(
        "--output-md",
        type=str,
        default="docs/p1.1_parameter_sweep.md",
        help="Output markdown report",
    )
    parser.add_argument(
        "--tolerances",
        type=float,
        nargs="+",
        default=[6.0, 8.0, 10.0, 12.0, 13.0, 14.0, 15.0, 18.0, 20.0],
        help="Tolerance values to sweep",
    )
    args = parser.parse_args()

    input_path = ROOT / args.input
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}")
        return 1

    print("=" * 70)
    print("P1.1.2 PARAMETER SWEEP ANALYSIS")
    print("=" * 70)

    data = load_experiments(input_path)
    single_results = data.get("single_results", [])
    multi_results = data.get("multi_results", [])

    print(f"Loaded {len(single_results)} single + {len(multi_results)} multi results")
    print(f"Tolerances to sweep: {args.tolerances}")
    print()

    # 1) Tolerance sweep
    print("[1/4] Tolerance sweep (single)...")
    sweep_single = tolerance_sweep(single_results, args.tolerances)

    print("[2/4] Tolerance sweep (multi)...")
    sweep_multi = tolerance_sweep(multi_results, args.tolerances)

    # 2) Delta analysis
    print("[3/4] Delta analysis...")
    delta = delta_analysis(single_results, multi_results, args.tolerances)

    # 3) Near-miss analysis
    print("[4/4] Near-miss & per-pocket delta...")
    near_single = near_miss_analysis(single_results, tolerance=8.0)
    near_multi = near_miss_analysis(multi_results, tolerance=8.0)
    pocket_delta_list = per_pocket_delta(single_results, multi_results)

    # Print summary table
    print()
    print("=" * 70)
    print("TOLERANCE SWEEP SUMMARY")
    print("=" * 70)
    print(f"{'Tolerance':>10} | {'Single':>8} | {'Multi':>8} | {'Δ':>8}")
    print("-" * 42)
    for d in delta:
        s_pct = f"{d['single_recall']*100:.1f}%"
        m_pct = f"{d['multi_recall']*100:.1f}%"
        d_pct = f"{d['delta_recall']*100:+.1f}%"
        print(f"{d['tolerance']:>9.1f}Å | {s_pct:>8} | {m_pct:>8} | {d_pct:>8}")
    print("=" * 70)

    # Regression summary
    regressions = [p for p in pocket_delta_list if p["regressed"]]
    improvements = [p for p in pocket_delta_list if p["improved"]]
    unchanged = [p for p in pocket_delta_list if not p["improved"] and not p["regressed"]]
    print()
    print(f"Per-pocket delta: {len(improvements)} improved, {len(unchanged)} unchanged, {len(regressions)} regressed")
    if regressions:
        print("Regressions:")
        for r in regressions:
            print(f"  🔴 {r['pdb_id']} ({r['pocket_type']}): {r['delta']:+.2f}Å")

    # Save JSON
    output_json = ROOT / args.output_json
    output_json.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tolerances_tested": args.tolerances,
        "sweep_single": sweep_single,
        "sweep_multi": sweep_multi,
        "delta_analysis": delta,
        "near_miss_multi": near_multi,
        "near_miss_single": near_single,
        "per_pocket_delta": pocket_delta_list,
    }
    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nJSON saved: {output_json}")

    # Generate markdown
    output_md = ROOT / args.output_md
    generate_report(
        sweep_single=sweep_single,
        sweep_multi=sweep_multi,
        delta=delta,
        near_single=near_single,
        near_multi=near_multi,
        pocket_delta=pocket_delta_list,
        output_path=output_md,
    )
    print(f"Markdown saved: {output_md}")

    # Final verdict
    multi_8 = next((r for r in sweep_multi if r["tolerance"] == 8.0), None)
    multi_14 = next((r for r in sweep_multi if r["tolerance"] == 14.0), None)
    print()
    print("=" * 70)
    print("P1.1.2 VERDICT")
    print("=" * 70)
    if multi_8:
        print(f"At tolerance=8.0Å (fixed gate): recall = {multi_8['recall']*100:.1f}% ({multi_8['hits']}/{multi_8['total']})")
    if multi_14:
        print(f"At tolerance=14.0Å (exploratory): recall = {multi_14['recall']*100:.1f}% ({multi_14['hits']}/{multi_14['total']})")
    print()
    print("⚠️  Tolerance alone cannot fix the gate recall. Algorithmic changes needed.")
    print("📋 Priority: CA→heavy-atom Voronoi → consensus refinement → known pocket validation")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
