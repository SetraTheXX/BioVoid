#!/usr/bin/env python3
"""
P0.1 Center Integrity Repair
============================

Atlas DB'deki [0,0,0] pocket center kayıtlarını aşağıdaki sırayla düzeltir:
1) Checkpoint JSONL'den geri yükleme
2) Gerekirse recompute (cavity detection + ranking)
3) Hala bulunamazsa metadata'ya invalid_center=1 işaretleme
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EPS = 1e-12


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Atlas center integrity repair")
    parser.add_argument("--db", default="data/atlas.db", help="Atlas DB path")
    parser.add_argument(
        "--checkpoint-jsonl",
        default="data/checkpoints/crawler_log.jsonl",
        help="Checkpoint JSONL path",
    )
    parser.add_argument("--raw-pdb-dir", default="data/raw_pdb")
    parser.add_argument("--frames-dir", default="data/frames")
    parser.add_argument(
        "--profile",
        default="default",
        choices=["default", "enzyme", "ppi", "gpcr"],
        help="Recompute scoring profile",
    )
    parser.add_argument(
        "--report",
        default="docs/center_integrity_report.md",
        help="Output markdown report path",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _is_zero_center(center: tuple[float, float, float] | list[float]) -> bool:
    return (
        abs(float(center[0])) < EPS
        and abs(float(center[1])) < EPS
        and abs(float(center[2])) < EPS
    )


def _parse_center(center: Any) -> tuple[float, float, float] | None:
    if isinstance(center, (list, tuple)) and len(center) >= 3:
        try:
            parsed = (float(center[0]), float(center[1]), float(center[2]))
        except Exception:
            return None
        return None if _is_zero_center(parsed) else parsed

    if isinstance(center, str):
        raw = center.strip().replace(",", " ")
        if raw.startswith("[") and raw.endswith("]"):
            raw = raw[1:-1]
        parts = [p for p in raw.split() if p]
        if len(parts) >= 3:
            try:
                parsed = (float(parts[0]), float(parts[1]), float(parts[2]))
            except Exception:
                return None
            return None if _is_zero_center(parsed) else parsed

    if hasattr(center, "__len__") and not isinstance(center, (bytes, bytearray, str)):
        try:
            if len(center) >= 3:
                parsed = (float(center[0]), float(center[1]), float(center[2]))
                return None if _is_zero_center(parsed) else parsed
        except Exception:
            return None
    return None


def _load_checkpoint_centers(
    checkpoint_jsonl: Path,
) -> tuple[dict[tuple[str, int], tuple[float, float, float]], dict[tuple[str, int], tuple[float, float, float]], dict[str, int]]:
    by_pocket_id: dict[tuple[str, int], tuple[float, float, float]] = {}
    by_rank: dict[tuple[str, int], tuple[float, float, float]] = {}
    stats = {
        "jsonl_lines": 0,
        "jsonl_parse_errors": 0,
        "jsonl_proteins_with_cavities": 0,
        "jsonl_cavities_seen": 0,
        "jsonl_valid_centers": 0,
    }
    proteins_seen: set[str] = set()

    with checkpoint_jsonl.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = line.strip()
            if not row:
                continue
            stats["jsonl_lines"] += 1
            try:
                obj = json.loads(row)
            except Exception:
                stats["jsonl_parse_errors"] += 1
                continue

            pdb_id = str(obj.get("pdb_id", "")).upper().strip()
            cavities = obj.get("cavities")
            if not pdb_id or not isinstance(cavities, list):
                continue
            proteins_seen.add(pdb_id)

            for cavity in cavities:
                if not isinstance(cavity, dict):
                    continue
                stats["jsonl_cavities_seen"] += 1
                center = _parse_center(cavity.get("center"))
                if center is None:
                    continue

                stats["jsonl_valid_centers"] += 1
                cid = cavity.get("id")
                rank = cavity.get("rank")
                if isinstance(cid, int):
                    by_pocket_id[(pdb_id, cid)] = center
                if isinstance(rank, int):
                    by_rank[(pdb_id, rank)] = center

    stats["jsonl_proteins_with_cavities"] = len(proteins_seen)
    return by_pocket_id, by_rank, stats


def _pick_analysis_pdb(project_root: Path, pdb_id: str, raw_pdb_dir: Path, frames_dir: Path) -> Path | None:
    pid = pdb_id.lower()
    frames_path = project_root / frames_dir / pid
    if frames_path.exists() and frames_path.is_dir():
        frame_files = sorted(frames_path.glob("frame_*.pdb"))
        if frame_files:
            return frame_files[len(frame_files) // 2]

    raw_path = project_root / raw_pdb_dir / f"{pid}.pdb"
    if raw_path.exists():
        return raw_path
    return None


def _recompute_center_maps(
    pdb_path: Path,
    profile: str,
) -> tuple[dict[int, tuple[float, float, float]], dict[int, tuple[float, float, float]]]:
    from src.cavities import find_cavities
    from src.geometry import extract_atom_coords
    from src.scoring import rank_pockets

    cavities = find_cavities(str(pdb_path), merge=True, hydrophobic=True, atom_type="heavy")
    if not cavities:
        return {}, {}

    atom_coords = extract_atom_coords(str(pdb_path), atom_type="heavy")
    ranked = rank_pockets(cavities, atom_coords, profile=profile, top_n=None)

    by_pocket_id: dict[int, tuple[float, float, float]] = {}
    by_rank: dict[int, tuple[float, float, float]] = {}

    for cavity in ranked:
        if not isinstance(cavity, dict):
            continue
        center = _parse_center(cavity.get("center"))
        if center is None:
            continue

        cid = cavity.get("id")
        rank = cavity.get("rank")
        if isinstance(cid, int):
            by_pocket_id[cid] = center
        if isinstance(rank, int):
            by_rank[rank] = center

    return by_pocket_id, by_rank


def _mark_invalid_metadata(metadata_json: str | None, reason: str) -> str:
    payload: dict[str, Any]
    if metadata_json:
        try:
            loaded = json.loads(metadata_json)
            payload = loaded if isinstance(loaded, dict) else {"legacy_metadata": loaded}
        except Exception:
            payload = {"legacy_metadata_raw": metadata_json}
    else:
        payload = {}

    payload["invalid_center"] = 1
    payload["invalid_center_reason"] = reason
    payload["center_repair_stage"] = "p0_1"
    payload["center_guard_mode"] = "soft_warning"
    return json.dumps(payload, ensure_ascii=False)


def _write_markdown_report(report_path: Path, stats: dict[str, Any], args: argparse.Namespace) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    lines = [
        "# Center Integrity Report (P0.1)",
        "",
        f"- Tarih (UTC): `{now}`",
        f"- DB: `{args.db}`",
        f"- Checkpoint JSONL: `{args.checkpoint_jsonl}`",
        f"- Dry run: `{args.dry_run}`",
        "",
        "## Özet",
        "",
        f"- Toplam pocket: **{stats['total_pockets_before']}**",
        f"- Zero-center (önce): **{stats['zero_before']}**",
        f"- Checkpoint ile düzeltildi: **{stats['repaired_from_checkpoint']}**",
        f"- Recompute ile düzeltildi: **{stats['repaired_from_recompute']}**",
        f"- `invalid_center=1` olarak işaretlendi: **{stats['marked_invalid']}**",
        f"- Zero-center (sonra): **{stats['zero_after']}**",
        f"- Zero-center + invalid_center=1 (sonra): **{stats['zero_after_with_invalid']}**",
        f"- Zero-center + invalid_center!=1 (sonra): **{stats['zero_after_without_invalid']}**",
        "",
        "## Checkpoint Geri Yükleme",
        "",
        f"- JSONL satır sayısı: **{stats['jsonl_lines']}**",
        f"- JSONL parse error: **{stats['jsonl_parse_errors']}**",
        f"- JSONL protein (cavity olan): **{stats['jsonl_proteins_with_cavities']}**",
        f"- JSONL cavity sayısı: **{stats['jsonl_cavities_seen']}**",
        f"- JSONL valid center sayısı: **{stats['jsonl_valid_centers']}**",
        f"- Checkpoint recovery oranı (zero-center bazında): **{stats['checkpoint_recovery_pct']:.2f}%**",
        "",
        "## Recompute",
        "",
        f"- Recompute denenen protein: **{stats['recompute_attempted_proteins']}**",
        f"- Recompute başarısız protein: **{stats['recompute_failed_proteins']}**",
        f"- Recompute merkez eşleşmesi bulunamayan satır: **{stats['recompute_unmatched_rows']}**",
        "",
        "## Kabul Kriteri Kontrolü",
        "",
        f"- Zero-center count = 0 (veya sadece invalid): **{'PASS' if stats['zero_after_without_invalid'] == 0 else 'FAIL'}**",
        f"- Checkpoint restore >= %80: **{'PASS' if stats['checkpoint_recovery_pct'] >= 80.0 else 'FAIL'}**",
        "",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    db_path = (project_root / args.db).resolve()
    checkpoint_jsonl = (project_root / args.checkpoint_jsonl).resolve()
    report_path = (project_root / args.report).resolve()

    if not db_path.exists():
        raise FileNotFoundError(f"DB bulunamadı: {db_path}")
    if not checkpoint_jsonl.exists():
        raise FileNotFoundError(f"Checkpoint JSONL bulunamadı: {checkpoint_jsonl}")

    cp_by_pid, cp_by_rank, cp_stats = _load_checkpoint_centers(checkpoint_jsonl)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    stats: dict[str, Any] = {
        **cp_stats,
        "total_pockets_before": 0,
        "zero_before": 0,
        "repaired_from_checkpoint": 0,
        "repaired_from_recompute": 0,
        "marked_invalid": 0,
        "recompute_attempted_proteins": 0,
        "recompute_failed_proteins": 0,
        "recompute_unmatched_rows": 0,
        "zero_after": 0,
        "zero_after_with_invalid": 0,
        "zero_after_without_invalid": 0,
        "checkpoint_recovery_pct": 0.0,
    }

    try:
        stats["total_pockets_before"] = int(cur.execute("SELECT COUNT(*) FROM pockets").fetchone()[0])
        zero_rows = cur.execute(
            """
            SELECT id, pdb_id, pocket_id, rank, metadata_json
            FROM pockets
            WHERE center_x = 0 AND center_y = 0 AND center_z = 0
            ORDER BY pdb_id, rank, pocket_id
            """
        ).fetchall()
        stats["zero_before"] = len(zero_rows)

        center_updates: list[tuple[float, float, float, int]] = []
        pending_recompute: dict[str, list[sqlite3.Row]] = defaultdict(list)

        for row in zero_rows:
            pid = str(row["pdb_id"]).upper()
            pocket_id = int(row["pocket_id"]) if row["pocket_id"] is not None else None
            rank = int(row["rank"]) if row["rank"] is not None else None

            center = None
            if pocket_id is not None:
                center = cp_by_pid.get((pid, pocket_id))
            if center is None and rank is not None:
                center = cp_by_rank.get((pid, rank))

            if center is not None:
                center_updates.append((center[0], center[1], center[2], int(row["id"])))
                stats["repaired_from_checkpoint"] += 1
            else:
                pending_recompute[pid].append(row)

        recompute_cache: dict[str, tuple[dict[int, tuple[float, float, float]], dict[int, tuple[float, float, float]]] | None] = {}
        invalid_updates: list[tuple[str, int]] = []
        raw_pdb_dir = Path(args.raw_pdb_dir)
        frames_dir = Path(args.frames_dir)

        for pid, rows in pending_recompute.items():
            if pid not in recompute_cache:
                stats["recompute_attempted_proteins"] += 1
                pdb_path = _pick_analysis_pdb(project_root, pid, raw_pdb_dir, frames_dir)
                if pdb_path is None:
                    recompute_cache[pid] = None
                else:
                    try:
                        recompute_cache[pid] = _recompute_center_maps(pdb_path, args.profile)
                    except Exception:
                        recompute_cache[pid] = None
                        stats["recompute_failed_proteins"] += 1

            cache_entry = recompute_cache.get(pid)
            for row in rows:
                row_id = int(row["id"])
                pocket_id = int(row["pocket_id"]) if row["pocket_id"] is not None else None
                rank = int(row["rank"]) if row["rank"] is not None else None

                center = None
                reason = "recompute_missing_source"
                if cache_entry is not None:
                    id_map, rank_map = cache_entry
                    if pocket_id is not None:
                        center = id_map.get(pocket_id)
                    if center is None and rank is not None:
                        center = rank_map.get(rank)
                    reason = "recompute_no_center_match"

                if center is not None:
                    center_updates.append((center[0], center[1], center[2], row_id))
                    stats["repaired_from_recompute"] += 1
                else:
                    stats["recompute_unmatched_rows"] += 1
                    metadata_json = _mark_invalid_metadata(row["metadata_json"], reason)
                    invalid_updates.append((metadata_json, row_id))
                    stats["marked_invalid"] += 1

        if not args.dry_run:
            if center_updates:
                cur.executemany(
                    """
                    UPDATE pockets
                    SET center_x = ?, center_y = ?, center_z = ?
                    WHERE id = ?
                    """,
                    center_updates,
                )
            if invalid_updates:
                cur.executemany(
                    """
                    UPDATE pockets
                    SET metadata_json = ?
                    WHERE id = ?
                    """,
                    invalid_updates,
                )
            conn.commit()

        zero_after_rows = cur.execute(
            """
            SELECT metadata_json
            FROM pockets
            WHERE center_x = 0 AND center_y = 0 AND center_z = 0
            """
        ).fetchall()
        stats["zero_after"] = len(zero_after_rows)

        with_invalid = 0
        for row in zero_after_rows:
            raw = row["metadata_json"]
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if isinstance(payload, dict) and int(payload.get("invalid_center", 0) or 0) == 1:
                with_invalid += 1

        stats["zero_after_with_invalid"] = with_invalid
        stats["zero_after_without_invalid"] = stats["zero_after"] - with_invalid
        if stats["zero_before"] > 0:
            stats["checkpoint_recovery_pct"] = (stats["repaired_from_checkpoint"] / stats["zero_before"]) * 100.0

    finally:
        conn.close()

    _write_markdown_report(report_path, stats, args)

    print("=" * 72)
    print(f"[SUMMARY] total_pockets_before={stats['total_pockets_before']}")
    print(f"[SUMMARY] zero_before={stats['zero_before']}")
    print(f"[SUMMARY] repaired_from_checkpoint={stats['repaired_from_checkpoint']}")
    print(f"[SUMMARY] repaired_from_recompute={stats['repaired_from_recompute']}")
    print(f"[SUMMARY] marked_invalid={stats['marked_invalid']}")
    print(f"[SUMMARY] zero_after={stats['zero_after']}")
    print(f"[SUMMARY] zero_after_without_invalid={stats['zero_after_without_invalid']}")
    print(f"[SUMMARY] checkpoint_recovery_pct={stats['checkpoint_recovery_pct']:.2f}")
    print("=" * 72)
    print(f"[REPORT] {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
