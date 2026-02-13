#!/usr/bin/env python3
"""
Phase 5.5 / Faz 1 - Benchmark pocket center repair

Amaç:
- Benchmark kapsamındaki proteinler için BioVoid center koordinatlarını yeniden üretir.
- Atlas DB'de center_x/y/z = 0 olan satırları deterministik şekilde günceller.

Notlar:
- Pre-registration config dosyasını değiştirmez.
- Hesaplama kaynağı fpocket değil, BioVoid cavity+scoring zinciridir.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any
import sys

import numpy as np


EPS = 1e-12


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark proteinleri için BioVoid pocket center repair uygular."
    )
    parser.add_argument("--benchmark-set", default="data/benchmark/fpocket_test_100.json")
    parser.add_argument("--db", default="data/atlas.db")
    parser.add_argument("--raw-pdb-dir", default="data/raw_pdb")
    parser.add_argument("--frames-dir", default="data/frames")
    parser.add_argument("--profile", default="default", choices=["default", "enzyme", "ppi", "gpcr"])
    parser.add_argument("--limit", type=int, default=0, help="0 = tüm benchmark proteinleri")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _is_zero_center(x: float, y: float, z: float) -> bool:
    return abs(float(x)) < EPS and abs(float(y)) < EPS and abs(float(z)) < EPS


def _load_benchmark_ids(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    ids = [
        str(item.get("pdb_id", "")).upper()
        for item in payload.get("proteins", [])
        if isinstance(item, dict)
    ]
    # Deterministik: unique + sorted
    return sorted({pid for pid in ids if pid})


def _pick_analysis_pdb(project_root: Path, pdb_id: str, raw_pdb_dir: Path, frames_dir: Path) -> Path | None:
    """
    Deterministik analiz dosyası seçimi:
    1) data/frames/<pdb_id>/frame_*.pdb varsa alfabetik sıralı orta dosya
    2) data/raw_pdb/<pdb_id>.pdb
    """
    pdb_l = pdb_id.lower()
    frame_folder = project_root / frames_dir / pdb_l
    if frame_folder.exists() and frame_folder.is_dir():
        frame_files = sorted(frame_folder.glob("frame_*.pdb"))
        if frame_files:
            return frame_files[len(frame_files) // 2]

    raw_path = project_root / raw_pdb_dir / f"{pdb_l}.pdb"
    if raw_path.exists():
        return raw_path

    return None


def _compute_centers_by_rank(pdb_path: Path, profile: str) -> dict[int, tuple[float, float, float]]:
    from src.cavities import find_cavities
    from src.geometry import extract_atom_coords
    from src.scoring import rank_pockets

    cavities = find_cavities(str(pdb_path), merge=True, hydrophobic=True, atom_type="heavy")
    if not cavities:
        return {}

    atom_coords = extract_atom_coords(str(pdb_path), atom_type="heavy")
    ranked = rank_pockets(cavities, atom_coords, profile=profile, top_n=None)

    centers_by_rank: dict[int, tuple[float, float, float]] = {}
    for i, cavity in enumerate(ranked, start=1):
        c = cavity.get("center")
        if c is None:
            continue
        arr = np.asarray(c, dtype=float)
        if arr.shape != (3,):
            continue
        centers_by_rank[i] = (float(arr[0]), float(arr[1]), float(arr[2]))
    return centers_by_rank


def main() -> int:
    args = parse_args()

    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    benchmark_path = project_root / args.benchmark_set
    db_path = project_root / args.db

    if not benchmark_path.exists():
        raise FileNotFoundError(f"Benchmark set bulunamadı: {benchmark_path}")
    if not db_path.exists():
        raise FileNotFoundError(f"DB bulunamadı: {db_path}")

    pdb_ids = _load_benchmark_ids(benchmark_path)
    if args.limit > 0:
        pdb_ids = pdb_ids[: args.limit]

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    updated_rows_total = 0
    visited = 0
    missing_structure = 0
    no_rank_mapping = 0
    untouched_nonzero = 0

    print(f"[INFO] Benchmark protein sayısı (işlenecek): {len(pdb_ids)}")

    try:
        for pdb_id in pdb_ids:
            visited += 1

            rows = cur.execute(
                """
                SELECT id, pocket_id, rank, center_x, center_y, center_z
                FROM pockets
                WHERE pdb_id = ?
                ORDER BY rank ASC, pocket_id ASC
                """,
                (pdb_id,),
            ).fetchall()

            if not rows:
                print(f"[SKIP] {pdb_id}: DB'de pocket kaydı yok")
                continue

            zero_rows = [r for r in rows if _is_zero_center(r["center_x"], r["center_y"], r["center_z"])]
            if not zero_rows:
                untouched_nonzero += 1
                print(f"[SKIP] {pdb_id}: center zaten non-zero")
                continue

            structure_path = _pick_analysis_pdb(
                project_root=project_root,
                pdb_id=pdb_id,
                raw_pdb_dir=Path(args.raw_pdb_dir),
                frames_dir=Path(args.frames_dir),
            )
            if structure_path is None:
                missing_structure += 1
                print(f"[WARN] {pdb_id}: analiz PDB bulunamadı (frames/raw_pdb yok)")
                continue

            try:
                centers_by_rank = _compute_centers_by_rank(structure_path, profile=args.profile)
            except Exception as exc:
                print(f"[WARN] {pdb_id}: center üretimi başarısız: {exc}")
                continue

            if not centers_by_rank:
                no_rank_mapping += 1
                print(f"[WARN] {pdb_id}: BioVoid ranking center üretmedi")
                continue

            updates: list[tuple[float, float, float, int]] = []
            unmatched = 0
            for r in zero_rows:
                rank = int(r["rank"]) if r["rank"] is not None else None
                if rank is None:
                    unmatched += 1
                    continue
                center = centers_by_rank.get(rank)
                if center is None:
                    unmatched += 1
                    continue
                updates.append((center[0], center[1], center[2], int(r["id"])))

            if args.dry_run:
                print(
                    f"[DRY] {pdb_id}: zero={len(zero_rows)} mapped={len(updates)} "
                    f"unmatched={unmatched} source={structure_path.relative_to(project_root)}"
                )
                continue

            if updates:
                cur.executemany(
                    """
                    UPDATE pockets
                    SET center_x = ?, center_y = ?, center_z = ?
                    WHERE id = ?
                    """,
                    updates,
                )
                conn.commit()

            updated_rows_total += len(updates)
            print(
                f"[OK] {pdb_id}: zero={len(zero_rows)} updated={len(updates)} "
                f"unmatched={unmatched} source={structure_path.relative_to(project_root)}"
            )

    finally:
        conn.close()

    print("=" * 70)
    print(f"[SUMMARY] visited={visited}")
    print(f"[SUMMARY] updated_rows_total={updated_rows_total}")
    print(f"[SUMMARY] missing_structure={missing_structure}")
    print(f"[SUMMARY] no_rank_mapping={no_rank_mapping}")
    print(f"[SUMMARY] untouched_nonzero={untouched_nonzero}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
