#!/usr/bin/env python3
"""
Phase 5.5 - Faz 1
fpocket batch runner (head-to-head benchmark).

- Pre-registration canonical parametrelerini zorunlu doğrular.
- Benchmark set üzerinden fpocket çalıştırır.
- Çıktıları normalize JSON özeti olarak kaydeder.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import time
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
    parser = argparse.ArgumentParser(description="Benchmark set için fpocket batch çalıştırır.")
    parser.add_argument("--benchmark-set", default="data/benchmark/fpocket_test_100.json")
    parser.add_argument("--config", default="data/validation/pre_registered_config.json")
    parser.add_argument("--output-dir", default="data/benchmark/fpocket_results")
    parser.add_argument("--fpocket-bin", default="fpocket")
    parser.add_argument("--pdb-root", default="data/raw_pdb")
    parser.add_argument(
        "--frames-dir",
        default="data/frames",
        help="PDB yoksa fallback için frame_*.pdb aranır.",
    )
    parser.add_argument("--max-proteins", type=int, default=0, help="0 ise tüm benchmark set")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _find_pdb_file(pdb_id: str, pdb_root: Path, frames_dir: Path) -> Path | None:
    pid_l = pdb_id.lower()
    pid_u = pdb_id.upper()

    candidates = [
        pdb_root / f"{pid_l}.pdb",
        pdb_root / f"{pid_u}.pdb",
        pdb_root / f"pdb{pid_l}.ent",
        pdb_root / f"{pid_l}.ent",
    ]
    for c in candidates:
        if c.exists():
            return c

    frame_sub = frames_dir / pid_l
    if frame_sub.exists():
        frames = sorted(frame_sub.glob("frame_*.pdb"))
        if frames:
            return frames[0]

    return None


def _parse_atom_center(pocket_file: Path) -> list[float] | None:
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []

    try:
        for line in pocket_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not (line.startswith("ATOM") or line.startswith("HETATM")):
                continue
            # PDB fixed columns fallback + whitespace fallback
            try:
                x = float(line[30:38].strip())
                y = float(line[38:46].strip())
                z = float(line[46:54].strip())
            except Exception:
                parts = line.split()
                if len(parts) < 9:
                    continue
                x, y, z = float(parts[6]), float(parts[7]), float(parts[8])
            xs.append(x)
            ys.append(y)
            zs.append(z)
    except Exception:
        return None

    if not xs:
        return None

    n = float(len(xs))
    return [sum(xs) / n, sum(ys) / n, sum(zs) / n]


def _parse_info_file(info_file: Path) -> dict[int, dict[str, float]]:
    # fpocket info formatları versiyonlar arasında değiştiği için regex tabanlı tolerant parser
    pocket_map: dict[int, dict[str, float]] = {}
    current_id: int | None = None

    p_pocket = re.compile(r"pocket\s*(\d+)", re.IGNORECASE)
    p_num = re.compile(r"(-?\d+(?:\.\d+)?)")

    for line in info_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = p_pocket.search(line)
        if m:
            current_id = int(m.group(1))
            pocket_map.setdefault(current_id, {})

        if current_id is None:
            continue

        low = line.lower()
        nums = [float(x) for x in p_num.findall(line)]
        if not nums:
            continue

        stripped_low = low.strip()

        if "drugg" in low and "score" in low:
            pocket_map[current_id]["druggability_score"] = nums[-1]
        elif "volume" in low and "volume score" not in low:
            pocket_map[current_id]["volume"] = nums[-1]
        elif stripped_low.startswith("score"):
            pocket_map[current_id]["score"] = nums[-1]

    return pocket_map


def _collect_fpocket_pockets(out_dir: Path, top_n: int) -> list[dict[str, Any]]:
    pockets_dir = out_dir / "pockets"
    info_candidates = list(out_dir.glob("*_info.txt"))
    info_map = _parse_info_file(info_candidates[0]) if info_candidates else {}

    rows: list[dict[str, Any]] = []
    if not pockets_dir.exists():
        return rows

    for p in sorted(pockets_dir.glob("pocket*_atm.pdb")):
        m = re.search(r"pocket(\d+)_atm\.pdb", p.name, flags=re.IGNORECASE)
        if not m:
            continue
        pid = int(m.group(1))
        center = _parse_atom_center(p)
        info = info_map.get(pid, {})
        rows.append(
            {
                "pocket_id": pid,
                "center": center,
                "volume": float(info.get("volume", math.nan)),
                "score": float(info.get("score", math.nan)),
                "druggability_score": float(info.get("druggability_score", math.nan)),
                "source_file": p.name,
            }
        )

    # score varsa score'a göre, yoksa pocket_id'ye göre sıralama
    rows.sort(
        key=lambda x: (
            0 if isinstance(x.get("score"), (int, float)) and math.isfinite(float(x.get("score"))) else 1,
            -float(x.get("score")) if isinstance(x.get("score"), (int, float)) and math.isfinite(float(x.get("score"))) else 0.0,
            x["pocket_id"],
        )
    )
    return rows[:top_n]


def _resolve_fpocket_bin(fpocket_bin: str, project_root: Path) -> Path | str:
    raw = Path(fpocket_bin)

    if raw.is_absolute():
        return raw

    candidate = (project_root / raw).resolve()
    if candidate.exists():
        return candidate

    which_hit = shutil.which(fpocket_bin)
    if which_hit:
        return Path(which_hit)

    return fpocket_bin


def _prepare_command(resolved_bin: Path | str, pdb_file: Path) -> tuple[list[str] | str, bool]:
    exe_str = str(resolved_bin)
    suffix = Path(exe_str).suffix.lower()

    if suffix in {".cmd", ".bat"}:
        argv = [exe_str, "-f", str(pdb_file)]
        cmdline = subprocess.list2cmdline(argv)
        return cmdline, True

    return [exe_str, "-f", str(pdb_file)], False


def main() -> int:
    args = parse_args()

    project_root = Path(__file__).resolve().parent.parent
    benchmark_path = project_root / args.benchmark_set
    config_path = project_root / args.config
    output_dir = project_root / args.output_dir
    pdb_root = project_root / args.pdb_root
    frames_dir = project_root / args.frames_dir

    cfg, params = load_and_validate_config(config_path)

    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    proteins = benchmark.get("proteins", [])
    pdb_ids = [str(x.get("pdb_id", "")).upper() for x in proteins if isinstance(x, dict)]

    if args.max_proteins and args.max_proteins > 0:
        pdb_ids = pdb_ids[: args.max_proteins]

    output_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = output_dir / "raw_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    resolved_fpocket_bin = _resolve_fpocket_bin(args.fpocket_bin, project_root)

    print(f"[DEBUG] fpocket-bin raw: {args.fpocket_bin}")
    print(f"[DEBUG] fpocket-bin resolved: {resolved_fpocket_bin}")
    if isinstance(resolved_fpocket_bin, Path):
        print(f"[DEBUG] fpocket-bin exists: {resolved_fpocket_bin.exists()}")

    for pdb_id in pdb_ids:
        entry: dict[str, Any] = {
            "pdb_id": pdb_id,
            "status": "pending",
            "started_at_utc": _utc_now(),
        }

        pdb_file = _find_pdb_file(pdb_id, pdb_root, frames_dir)
        if pdb_file is None:
            entry["status"] = "missing_input"
            entry["error"] = "PDB/frame dosyası bulunamadı"
            results.append(entry)
            continue

        run_dir = runs_dir / pdb_id.lower()
        run_dir.mkdir(parents=True, exist_ok=True)

        cmd, use_shell = _prepare_command(resolved_fpocket_bin, pdb_file)
        entry["command"] = cmd if isinstance(cmd, list) else [cmd]
        entry["shell"] = use_shell
        entry["resolved_fpocket_bin"] = str(resolved_fpocket_bin)
        entry["run_cwd"] = str(run_dir)
        entry["input_pdb"] = str(pdb_file.relative_to(project_root).as_posix()) if pdb_file.is_relative_to(project_root) else str(pdb_file)

        if args.dry_run:
            entry["status"] = "dry_run"
            results.append(entry)
            continue

        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(run_dir),
                text=True,
                capture_output=True,
                check=False,
                shell=use_shell,
                executable=os.environ.get("COMSPEC", "cmd.exe") if use_shell else None,
            )
            runtime = round(time.perf_counter() - t0, 3)

            entry["runtime_sec"] = runtime
            entry["return_code"] = proc.returncode

            if proc.returncode != 0:
                entry["status"] = "failed"
                entry["stderr_tail"] = "\n".join(proc.stderr.splitlines()[-20:])
                results.append(entry)
                continue
        except FileNotFoundError as exc:
            runtime = round(time.perf_counter() - t0, 3)
            entry["runtime_sec"] = runtime
            entry["status"] = "failed"
            entry["return_code"] = 127
            entry["error"] = f"fpocket binary bulunamadı: {exc}"
            results.append(entry)
            continue

        out_folder_name = f"{pdb_file.stem}_out"
        discovered_out = run_dir / out_folder_name
        if not discovered_out.exists():
            # fpocket bazı durumlarda farklı isim üretebilir, en güncel *_out klasörünü al
            outs = sorted(run_dir.glob("*_out"), key=lambda p: p.stat().st_mtime, reverse=True)
            discovered_out = outs[0] if outs else discovered_out

        if not discovered_out.exists():
            entry["status"] = "failed"
            entry["error"] = "fpocket çıktı klasörü bulunamadı"
            results.append(entry)
            continue

        stable_out = output_dir / f"{pdb_id.lower()}_out"
        if stable_out.exists():
            shutil.rmtree(stable_out)
        shutil.copytree(discovered_out, stable_out)

        pockets = _collect_fpocket_pockets(stable_out, params.top_n)
        entry["status"] = "ok"
        entry["fpocket_output_dir"] = str(stable_out.relative_to(project_root).as_posix())
        entry["pockets"] = pockets
        entry["pocket_count"] = len(pockets)
        results.append(entry)

    summary = {
        "run_at_utc": _utc_now(),
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
        "fpocket_bin": args.fpocket_bin,
        "benchmark_set": args.benchmark_set,
        "processed_proteins": len(pdb_ids),
        "results": results,
    }

    summary_path = output_dir / "fpocket_batch_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    ok = sum(1 for r in results if r.get("status") == "ok")
    print(f"[INFO] İşlenen protein: {len(pdb_ids)}, başarılı: {ok}")
    print(f"[OK] Özet yazıldı: {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
