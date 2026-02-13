#!/usr/bin/env python3
"""
Phase 5.5 - Faz 1
Benchmark protein set hazırlama (fpocket head-to-head).

Bu script pre-registration kilidini zorunlu doğrular ve benchmark setini
reproducible şekilde üretir.
"""

from __future__ import annotations

import argparse
import json
import random
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
    if not config_path.exists():
        raise FileNotFoundError(f"Pre-registration config bulunamadı: {config_path}")

    cfg = json.loads(config_path.read_text(encoding="utf-8"))

    phase = cfg.get("pre_registration", {}).get("phase")
    status = cfg.get("pre_registration", {}).get("status")
    if phase != "5.5" or status != "locked":
        raise ValueError(
            f"Pre-registration kilidi geçersiz (phase={phase}, status={status})."
        )

    cp = cfg.get("canonical_parameters", {})
    params = CanonicalParams(
        tolerance=float(cp.get("proximity_tolerance_angstrom")),
        top_n=int(cp.get("top_n_pockets_to_consider")),
        druggable_filter=bool(cp.get("druggable_filter")),
        min_druggable_volume=float(cp.get("min_druggable_volume_angstrom3", 200.0)),
    )

    if params.tolerance != EXPECTED_TOLERANCE:
        raise ValueError(
            f"Tolerance drift tespit edildi: {params.tolerance} != {EXPECTED_TOLERANCE}"
        )
    if params.top_n != EXPECTED_TOP_N:
        raise ValueError(f"Top-N drift tespit edildi: {params.top_n} != {EXPECTED_TOP_N}")
    if params.druggable_filter != EXPECTED_DRUGGABLE_FILTER:
        raise ValueError(
            "Druggable filter drift tespit edildi: "
            f"{params.druggable_filter} != {EXPECTED_DRUGGABLE_FILTER}"
        )

    return cfg, params


def _norm_pdb(value: str) -> str | None:
    v = (value or "").strip().upper()
    if len(v) == 4 and v.isalnum():
        return v
    return None


def _collect_from_json(source_data: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    if isinstance(source_data, dict):
        if isinstance(source_data.get("proteins"), list):
            for item in source_data["proteins"]:
                if not isinstance(item, dict):
                    continue
                pid = _norm_pdb(str(item.get("pdb_id", "")))
                if pid:
                    rows.append({"pdb_id": pid, "metadata": item, "source": "source_json.proteins"})

        if isinstance(source_data.get("test_cases"), list):
            for item in source_data["test_cases"]:
                if not isinstance(item, dict):
                    continue
                pid = _norm_pdb(str(item.get("pdb_id", "")))
                if pid:
                    rows.append({"pdb_id": pid, "metadata": item, "source": "source_json.test_cases"})

    elif isinstance(source_data, list):
        for item in source_data:
            if isinstance(item, dict):
                pid = _norm_pdb(str(item.get("pdb_id", "")))
                if pid:
                    rows.append({"pdb_id": pid, "metadata": item, "source": "source_json.list"})
            elif isinstance(item, str):
                pid = _norm_pdb(item)
                if pid:
                    rows.append({"pdb_id": pid, "metadata": {}, "source": "source_json.list"})

    return rows


def build_candidates(source_path: Path, frames_dir: Path) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}

    if source_path.exists():
        data = json.loads(source_path.read_text(encoding="utf-8"))
        for row in _collect_from_json(data):
            pid = row["pdb_id"]
            prev = candidates.get(pid)
            if prev is None:
                candidates[pid] = row
            else:
                prev.setdefault("source_tags", set()).add(row["source"])

    if frames_dir.exists():
        for sub in frames_dir.iterdir():
            if not sub.is_dir():
                continue
            pid = _norm_pdb(sub.name)
            if not pid:
                continue
            row = candidates.get(pid)
            if row is None:
                candidates[pid] = {
                    "pdb_id": pid,
                    "metadata": {"frames_dir": str(sub.as_posix())},
                    "source": "data.frames",
                }
            else:
                tags = row.setdefault("source_tags", set())
                tags.add("data.frames")

    out: list[dict[str, Any]] = []
    for row in candidates.values():
        tags = set()
        if "source" in row:
            tags.add(str(row["source"]))
        tags.update(set(row.get("source_tags", set())))
        out.append(
            {
                "pdb_id": row["pdb_id"],
                "metadata": row.get("metadata", {}),
                "source_tags": sorted(tags),
            }
        )

    out.sort(key=lambda x: x["pdb_id"])
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="100 protein benchmark set üretir (pre-registration lock enforced)."
    )
    parser.add_argument(
        "--source",
        default="data/validation/known_cryptic_pockets.json",
        help="Kaynak JSON (pdb_id listesi/proteins/test_cases içerebilir).",
    )
    parser.add_argument(
        "--frames-dir",
        default="data/frames",
        help="Ek adaylar için frame dizini (alt klasör adı PDB ID).",
    )
    parser.add_argument(
        "--config",
        default="data/validation/pre_registered_config.json",
        help="Pre-registration config yolu.",
    )
    parser.add_argument(
        "--output",
        default="data/benchmark/fpocket_test_100.json",
        help="Çıktı benchmark JSON yolu.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Reproducible random seed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Yazma yapmadan planlanan işlemi göster.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    project_root = Path(__file__).resolve().parent.parent
    source_path = project_root / args.source
    frames_dir = project_root / args.frames_dir
    config_path = project_root / args.config
    output_path = project_root / args.output

    cfg, params = load_and_validate_config(config_path)
    dataset_size = int(cfg.get("benchmark", {}).get("dataset_size", 100))

    candidates = build_candidates(source_path, frames_dir)
    if len(candidates) < dataset_size:
        raise RuntimeError(
            f"Yetersiz aday protein: {len(candidates)} < {dataset_size}. "
            "Kaynak veri/frames genişletilmeli."
        )

    rng = random.Random(args.seed)
    selected = rng.sample(candidates, dataset_size)
    selected.sort(key=lambda x: x["pdb_id"])

    payload = {
        "benchmark_id": "fpocket_v1_locked",
        "generated_at_utc": _utc_now(),
        "seed": args.seed,
        "source": {
            "source_path": str(source_path.relative_to(project_root).as_posix()) if source_path.exists() else str(source_path.as_posix()),
            "frames_dir": str(frames_dir.relative_to(project_root).as_posix()) if frames_dir.exists() else str(frames_dir.as_posix()),
            "candidate_count": len(candidates),
        },
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
        "proteins": selected,
    }

    print(f"[INFO] Aday sayısı: {len(candidates)}")
    print(f"[INFO] Seçilen benchmark protein sayısı: {len(selected)}")

    if args.dry_run:
        print("[DRY-RUN] Çıktı yazılmadı.")
        print(f"[DRY-RUN] Hedef çıktı: {output_path}")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Benchmark set yazıldı: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
