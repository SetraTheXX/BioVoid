#!/usr/bin/env python3
"""
Phase 5.5 - Faz 1
fpocket vs BioVoid benchmark raporu üretir.

- Pre-registration canonical parametrelerini zorunlu doğrular.
- Overlap metriğini proximity (8Å) + volume-ratio (0.5-2.0) ile hesaplar.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_TOLERANCE = 8.0
EXPECTED_TOP_N = 20
EXPECTED_DRUGGABLE_FILTER = True


@dataclass
class CanonicalParams:
    tolerance: float
    top_n: int
    druggable_filter: bool
    min_druggable_volume: float


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_and_validate_config(config_path: Path) -> tuple[dict[str, Any], CanonicalParams]:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))

    phase = cfg.get("pre_registration", {}).get("phase")
    status = cfg.get("pre_registration", {}).get("status")
    if phase != "5.5" or status != "locked":
        raise ValueError(f"Pre-registration kilidi geçersiz (phase={phase}, status={status})")

    cp = cfg.get("canonical_parameters", {})
    params = CanonicalParams(
        tolerance=float(cp.get("proximity_tolerance_angstrom")),
        top_n=int(cp.get("top_n_pockets_to_consider")),
        druggable_filter=bool(cp.get("druggable_filter")),
        min_druggable_volume=float(cp.get("min_druggable_volume_angstrom3", 200.0)),
    )

    if params.tolerance != EXPECTED_TOLERANCE:
        raise ValueError("Tolerance drift tespit edildi")
    if params.top_n != EXPECTED_TOP_N:
        raise ValueError("Top-N drift tespit edildi")
    if params.druggable_filter != EXPECTED_DRUGGABLE_FILTER:
        raise ValueError("Druggable filter drift tespit edildi")

    return cfg, params


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="fpocket vs BioVoid benchmark markdown raporu üretir.")
    parser.add_argument("--benchmark-set", default="data/benchmark/fpocket_test_100.json")
    parser.add_argument("--fpocket-summary", default="data/benchmark/fpocket_results/fpocket_batch_summary.json")
    parser.add_argument("--biovoid-results", default="data/benchmark/biovoid_results.json")
    parser.add_argument("--config", default="data/validation/pre_registered_config.json")
    parser.add_argument("--output", default="docs/fpocket_benchmark_report.md")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _distance(a: list[float], b: list[float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _valid_center(x: Any) -> bool:
    return (
        isinstance(x, list)
        and len(x) == 3
        and all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in x)
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


def calculate_overlap(fpocket_pockets: list[dict[str, Any]], biovoid_pockets: list[dict[str, Any]], tolerance: float) -> dict[str, Any]:
    fp = [p for p in fpocket_pockets if _valid_center(p.get("center"))]
    bv = [p for p in biovoid_pockets if _valid_center(p.get("center"))]

    matched_fp = set()
    matched_bv = set()

    for i, f in enumerate(fp):
        best_j = None
        best_dist = float("inf")
        for j, b in enumerate(bv):
            if j in matched_bv:
                continue
            dist = _distance(f["center"], b["center"])
            if dist <= tolerance and _volume_match(f.get("volume"), b.get("volume")):
                if dist < best_dist:
                    best_dist = dist
                    best_j = j

        if best_j is not None:
            matched_fp.add(i)
            matched_bv.add(best_j)

    matches = len(matched_fp)
    denom = len(fp) + len(bv)
    overlap_score = (2 * matches / denom) if denom > 0 else 0.0

    return {
        "overlap_score": overlap_score,
        "matched": matches,
        "total_fpocket": len(fp),
        "total_biovoid": len(bv),
        "fpocket_unique": len(fp) - matches,
        "biovoid_unique": len(bv) - matches,
    }


def main() -> int:
    args = parse_args()

    project_root = Path(__file__).resolve().parent.parent
    benchmark_path = project_root / args.benchmark_set
    fpocket_path = project_root / args.fpocket_summary
    biovoid_path = project_root / args.biovoid_results
    config_path = project_root / args.config
    output_path = project_root / args.output

    cfg, params = load_and_validate_config(config_path)

    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    fpocket = json.loads(fpocket_path.read_text(encoding="utf-8"))
    biovoid = json.loads(biovoid_path.read_text(encoding="utf-8"))

    fp_by_id = {str(r.get("pdb_id", "")).upper(): r for r in fpocket.get("results", []) if isinstance(r, dict)}
    bv_by_id = {str(r.get("pdb_id", "")).upper(): r for r in biovoid.get("results", []) if isinstance(r, dict)}

    proteins = [
        str(item.get("pdb_id", "")).upper()
        for item in benchmark.get("proteins", [])
        if isinstance(item, dict)
    ]

    rows = []
    agg = {
        "matched": 0,
        "total_fpocket": 0,
        "total_biovoid": 0,
        "fpocket_unique": 0,
        "biovoid_unique": 0,
    }

    for pdb_id in proteins:
        fp_row = fp_by_id.get(pdb_id, {})
        bv_row = bv_by_id.get(pdb_id, {})
        ov = calculate_overlap(
            fp_row.get("pockets", []) if isinstance(fp_row.get("pockets"), list) else [],
            bv_row.get("pockets", []) if isinstance(bv_row.get("pockets"), list) else [],
            params.tolerance,
        )
        agg["matched"] += ov["matched"]
        agg["total_fpocket"] += ov["total_fpocket"]
        agg["total_biovoid"] += ov["total_biovoid"]
        agg["fpocket_unique"] += ov["fpocket_unique"]
        agg["biovoid_unique"] += ov["biovoid_unique"]

        rows.append(
            {
                "pdb_id": pdb_id,
                **ov,
                "fpocket_status": fp_row.get("status", "missing"),
                "biovoid_count": bv_row.get("pocket_count", 0),
            }
        )

    denom = agg["total_fpocket"] + agg["total_biovoid"]
    global_overlap = (2 * agg["matched"] / denom) if denom > 0 else 0.0
    overlap_gate = float(cfg.get("decision_gates", {}).get("min_fpocket_overlap", 0.40))
    gate_status = "PASS" if global_overlap >= overlap_gate else "FAIL"

    report_lines = [
        "# fpocket vs Bio-Void Hunter Benchmark Report (Phase 5.5 / Faz 1)",
        "",
        f"- Generated at (UTC): { _utc_now() }",
        f"- Benchmark protein count: {len(proteins)}",
        f"- Canonical tolerance (Å): {params.tolerance}",
        f"- Canonical Top-N: {params.top_n}",
        f"- Canonical druggable filter: {str(params.druggable_filter).lower()}",
        "",
        "## Global Overlap Summary",
        "",
        f"- Global overlap score: **{global_overlap:.4f}**",
        f"- Matched pockets: {agg['matched']}",
        f"- fpocket total (valid-center): {agg['total_fpocket']}",
        f"- BioVoid total (valid-center): {agg['total_biovoid']}",
        f"- fpocket unique: {agg['fpocket_unique']}",
        f"- BioVoid unique: {agg['biovoid_unique']}",
        f"- Decision gate (min overlap {overlap_gate:.2f}): **{gate_status}**",
        "",
        "## Protein-level Details",
        "",
        "| PDB | fpocket status | fpocket pockets | biovoid pockets | matched | overlap | fpocket-only | biovoid-only |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for r in rows:
        report_lines.append(
            "| {pdb} | {st} | {tf} | {tb} | {m} | {ov:.4f} | {fu} | {bu} |".format(
                pdb=r["pdb_id"],
                st=r["fpocket_status"],
                tf=r["total_fpocket"],
                tb=r["total_biovoid"],
                m=r["matched"],
                ov=r["overlap_score"],
                fu=r["fpocket_unique"],
                bu=r["biovoid_unique"],
            )
        )

    report_lines.extend(
        [
            "",
            "## Reproducibility / Lock",
            "",
            "Bu rapor pre-registration kilidine bağlı canonical parametrelerle üretildi:",
            f"- tolerance = {params.tolerance}",
            f"- top-N = {params.top_n}",
            f"- druggable_filter = {str(params.druggable_filter).lower()}",
            "",
            "Config drift tespit edilirse script hata vererek durur.",
            "",
        ]
    )

    if args.dry_run:
        print("[DRY-RUN] Rapor üretim planı hazır.")
        print(f"[DRY-RUN] Protein sayısı: {len(proteins)}")
        print(f"[DRY-RUN] Global overlap: {global_overlap:.4f}")
        print(f"[DRY-RUN] Çıktı yazılmadı: {output_path}")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"[OK] Rapor yazıldı: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
