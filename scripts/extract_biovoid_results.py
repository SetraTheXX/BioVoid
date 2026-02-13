#!/usr/bin/env python3
"""
Phase 5.5 - Faz 1
Benchmark set için BioVoid pocket sonuçlarını atlas veritabanından çıkarır.

- Pre-registration canonical parametrelerini zorunlu doğrular.
- top-N, druggable filter ve min_druggable_volume kurallarını config'ten uygular.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EPS = 1e-9

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
    parser = argparse.ArgumentParser(description="Benchmark set için BioVoid pocket sonuçlarını çıkarır.")
    parser.add_argument("--benchmark-set", default="data/benchmark/fpocket_test_100.json")
    parser.add_argument("--db", default="data/atlas.db")
    parser.add_argument("--config", default="data/validation/pre_registered_config.json")
    parser.add_argument("--output", default="data/benchmark/biovoid_results.json")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _is_degenerate_center(center: list[float | None]) -> bool:
    if len(center) != 3:
        return True
    nums: list[float] = []
    for v in center:
        if v is None:
            return True
        try:
            nums.append(float(v))
        except (TypeError, ValueError):
            return True
    return all(abs(v) < EPS for v in nums)


def _load_report_centers(report_path: Path) -> tuple[dict[int, list[float]], dict[int, list[float]]]:
    by_id: dict[int, list[float]] = {}
    by_rank: dict[int, list[float]] = {}

    if not report_path.exists():
        return by_id, by_rank

    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return by_id, by_rank

    cavities = payload.get("cavities", [])
    if not isinstance(cavities, list):
        return by_id, by_rank

    for cav in cavities:
        if not isinstance(cav, dict):
            continue
        center = cav.get("center")
        if not isinstance(center, list) or len(center) != 3:
            continue
        try:
            parsed = [float(center[0]), float(center[1]), float(center[2])]
        except (TypeError, ValueError):
            continue
        if _is_degenerate_center(parsed):
            continue

        cav_id = cav.get("id")
        if isinstance(cav_id, int):
            by_id[cav_id] = parsed

        rank = cav.get("rank")
        if isinstance(rank, int):
            by_rank[rank] = parsed

    return by_id, by_rank


def main() -> int:
    args = parse_args()

    project_root = Path(__file__).resolve().parent.parent
    benchmark_path = project_root / args.benchmark_set
    db_path = project_root / args.db
    config_path = project_root / args.config
    output_path = project_root / args.output

    cfg, params = load_and_validate_config(config_path)
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    pdb_ids = [
        str(item.get("pdb_id", "")).upper()
        for item in benchmark.get("proteins", [])
        if isinstance(item, dict)
    ]

    if not db_path.exists():
        raise FileNotFoundError(f"Atlas DB bulunamadı: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    base_sql = """
        SELECT
            pocket_id,
            rank,
            bio_score,
            volume,
            center_x,
            center_y,
            center_z,
            druggable,
            druggability_class
        FROM pockets
        WHERE pdb_id = ?
    """
    clauses: list[str] = []
    bind_tail: list[Any] = []

    if params.druggable_filter:
        clauses.append("druggable = 1")
        clauses.append("volume >= ?")
        bind_tail.append(params.min_druggable_volume)

    if clauses:
        base_sql += " AND " + " AND ".join(clauses)

    base_sql += " ORDER BY bio_score DESC LIMIT ?"

    results: list[dict[str, Any]] = []

    try:
        for pdb_id in pdb_ids:
            binds: list[Any] = [pdb_id]
            binds.extend(bind_tail)
            binds.append(params.top_n)

            rows = conn.execute(base_sql, tuple(binds)).fetchall()
            report_path = project_root / "data" / "results" / f"{pdb_id.lower()}_report.json"
            centers_by_id, centers_by_rank = _load_report_centers(report_path)

            pockets = []
            fallback_for_pdb = 0
            dropped_degenerate_for_pdb = 0
            for r in rows:
                pocket_id = int(r["pocket_id"])
                rank = int(r["rank"]) if r["rank"] is not None else None
                center = [
                    float(r["center_x"]) if r["center_x"] is not None else None,
                    float(r["center_y"]) if r["center_y"] is not None else None,
                    float(r["center_z"]) if r["center_z"] is not None else None,
                ]

                if _is_degenerate_center(center):
                    fallback = centers_by_id.get(pocket_id)
                    if fallback is None and rank is not None:
                        fallback = centers_by_rank.get(rank)
                    if fallback is not None:
                        center = fallback
                        fallback_for_pdb += 1
                    else:
                        center = [None, None, None]
                        dropped_degenerate_for_pdb += 1

                pockets.append(
                    {
                        "pocket_id": pocket_id,
                        "rank": rank,
                        "bio_score": float(r["bio_score"]) if r["bio_score"] is not None else None,
                        "volume": float(r["volume"]) if r["volume"] is not None else None,
                        "center": center,
                        "druggable": bool(r["druggable"]),
                        "druggability_class": r["druggability_class"],
                    }
                )

            if fallback_for_pdb > 0:
                print(
                    f"[WARN] {pdb_id}: {fallback_for_pdb}/{len(rows)} pocket center fallback uygulandı "
                    f"(kaynak: {report_path.relative_to(project_root) if report_path.exists() else 'yok'})"
                )
            if dropped_degenerate_for_pdb > 0:
                print(
                    f"[WARN] {pdb_id}: {dropped_degenerate_for_pdb}/{len(rows)} pocket center dejenere kaldı; "
                    "merkez [None,None,None] olarak işaretlendi"
                )

            results.append(
                {
                    "pdb_id": pdb_id,
                    "pocket_count": len(pockets),
                    "pockets": pockets,
                }
            )
    finally:
        conn.close()

    payload = {
        "generated_at_utc": _utc_now(),
        "benchmark_set": args.benchmark_set,
        "atlas_db": args.db,
        "pre_registration": {
            "phase": cfg.get("pre_registration", {}).get("phase"),
            "status": cfg.get("pre_registration", {}).get("status"),
            "locked_at_utc": cfg.get("pre_registration", {}).get("locked_at_utc"),
            "canonical_parameters": {
                "proximity_tolerance_angstrom": params.tolerance,
                "top_n_pockets_to_consider": params.top_n,
                "druggable_filter": params.druggable_filter,
                "min_druggable_volume_angstrom3": params.min_druggable_volume,
            },
        },
        "results": results,
    }

    if args.dry_run:
        print(f"[DRY-RUN] Protein sayısı: {len(pdb_ids)}")
        print(f"[DRY-RUN] Örnek ilk kayıt pocket_count: {results[0]['pocket_count'] if results else 0}")
        print(f"[DRY-RUN] Çıktı yazılmadı: {output_path}")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    non_empty = sum(1 for r in results if r["pocket_count"] > 0)
    print(f"[INFO] İşlenen protein: {len(results)}")
    print(f"[INFO] Pocket bulunan protein: {non_empty}")
    print(f"[OK] Sonuç yazıldı: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
