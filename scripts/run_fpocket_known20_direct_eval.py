#!/usr/bin/env python3
"""
fpocket Known-20 Direct Evaluator
===================================

For each of the 20 known cryptic pocket cases, determines whether fpocket
detected a pocket near the known cryptic pocket center (within canonical
tolerance).

Strategy:
  1. Load existing fpocket results from data/benchmark/fpocket_results/
     (batch summary JSON + per-protein output dirs).
  2. For cases without cached results, attempt to run fpocket binary
     on the PDB file (if binary is available).
  3. For each case, compute distance from each fpocket pocket center
     to the known cryptic pocket center.
  4. Mark fpocket_detects=True if any pocket is within tolerance AND
     passes druggability/volume filters.

Canonical parameters (from pre_registered_config.json):
  - tolerance = 8.0 A
  - top_n = 20
  - druggable_only = True
  - min_volume = 200 A^3

Output:
  data/validation/fpocket_known20_direct_eval.json

Usage:
  python scripts/run_fpocket_known20_direct_eval.py [--tolerance 8.0] [--min-volume 200] [--fpocket-backend local|docker]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DOCKER_IMAGE = "biovoid-fpocket:latest"
DOCKER_TIMEOUT = 180  # seconds per case

REPO_ROOT = Path(__file__).resolve().parents[1]
KNOWN_CRYPTIC = REPO_ROOT / "data" / "validation" / "known_cryptic_pockets.json"
FPOCKET_BATCH_SUMMARY = REPO_ROOT / "data" / "benchmark" / "fpocket_results" / "fpocket_batch_summary.json"
FPOCKET_RESULTS_DIR = REPO_ROOT / "data" / "benchmark" / "fpocket_results"
PDB_ROOT = REPO_ROOT / "data" / "raw_pdb"
FRAMES_DIR = REPO_ROOT / "data" / "frames"
PRE_REG_CONFIG = REPO_ROOT / "data" / "validation" / "pre_registered_config.json"
OUTPUT = REPO_ROOT / "data" / "validation" / "fpocket_known20_direct_eval.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _euclidean_distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


def _find_pdb_file(pdb_id: str) -> Path | None:
    pid_l = pdb_id.lower()
    pid_u = pdb_id.upper()
    candidates = [
        PDB_ROOT / f"{pid_l}.pdb",
        PDB_ROOT / f"{pid_u}.pdb",
        PDB_ROOT / f"pdb{pid_l}.ent",
    ]
    for c in candidates:
        if c.exists():
            return c
    frame_sub = FRAMES_DIR / pid_l
    if frame_sub.exists():
        frames = sorted(frame_sub.glob("frame_*.pdb"))
        if frames:
            return frames[0]
    return None


def _parse_atom_center(pocket_file: Path) -> list[float] | None:
    xs, ys, zs = [], [], []
    try:
        for line in pocket_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not (line.startswith("ATOM") or line.startswith("HETATM")):
                continue
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
        if "drugg" in low and "score" in low:
            pocket_map[current_id]["druggability_score"] = nums[-1]
        elif "volume" in low and "volume score" not in low:
            pocket_map[current_id]["volume"] = nums[-1]
        elif low.strip().startswith("score"):
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
        rows.append({
            "pocket_id": pid,
            "center": center,
            "volume": float(info.get("volume", math.nan)),
            "score": float(info.get("score", math.nan)),
            "druggability_score": float(info.get("druggability_score", math.nan)),
        })
    rows.sort(key=lambda x: (
        0 if isinstance(x.get("score"), (int, float)) and math.isfinite(x["score"]) else 1,
        -x["score"] if isinstance(x.get("score"), (int, float)) and math.isfinite(x["score"]) else 0.0,
        x["pocket_id"],
    ))
    return rows[:top_n]


def _load_cached_fpocket_pockets(pdb_id: str) -> list[dict[str, Any]] | None:
    """Try to load fpocket pockets from batch summary or output dir."""
    # Try batch summary first
    summary = _load_json(FPOCKET_BATCH_SUMMARY)
    if summary:
        for r in summary.get("results", []):
            if r.get("pdb_id", "").upper() == pdb_id.upper() and r.get("status") == "ok":
                return r.get("pockets", [])

    # Try output dir directly
    out_dir = FPOCKET_RESULTS_DIR / f"{pdb_id.lower()}_out"
    if out_dir.exists():
        return _collect_fpocket_pockets(out_dir, top_n=20)

    return None


def _try_run_fpocket(pdb_id: str, backend: str = "local") -> list[dict[str, Any]] | None:
    """Attempt to run fpocket on the PDB file using local binary or Docker."""
    if backend == "docker":
        return _try_run_fpocket_docker(pdb_id)

    fpocket_bin = shutil.which("fpocket")
    if not fpocket_bin:
        return None

    pdb_file = _find_pdb_file(pdb_id)
    if not pdb_file:
        return None

    run_dir = FPOCKET_RESULTS_DIR / f"{pdb_id.lower()}_run"
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        proc = subprocess.run(
            [fpocket_bin, "-f", str(pdb_file)],
            cwd=str(run_dir),
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
        if proc.returncode != 0:
            return None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    out_folder = run_dir / f"{pdb_file.stem}_out"
    if not out_folder.exists():
        outs = sorted(run_dir.glob("*_out"), key=lambda p: p.stat().st_mtime, reverse=True)
        out_folder = outs[0] if outs else out_folder

    if not out_folder.exists():
        return None

    # Copy to stable location
    stable_out = FPOCKET_RESULTS_DIR / f"{pdb_id.lower()}_out"
    if not stable_out.exists():
        shutil.copytree(out_folder, stable_out)

    return _collect_fpocket_pockets(stable_out, top_n=20)


def _docker_available() -> bool:
    """Check if Docker is available and the fpocket image exists."""
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", DOCKER_IMAGE],
            capture_output=True, text=True, timeout=15,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _try_run_fpocket_docker(pdb_id: str) -> list[dict[str, Any]] | None:
    """Run fpocket inside Docker container, mount PDB, collect results."""
    pdb_file = _find_pdb_file(pdb_id)
    if not pdb_file:
        return None

    # Use a temp dir for Docker output
    run_dir = FPOCKET_RESULTS_DIR / f"{pdb_id.lower()}_docker_run"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Copy PDB into run_dir so Docker can see it
    local_pdb = run_dir / f"{pdb_id.lower()}.pdb"
    if not local_pdb.exists():
        shutil.copy2(pdb_file, local_pdb)

    # Convert Windows path to Docker-compatible mount path
    mount_src = str(run_dir).replace("\\", "/")
    # Docker Desktop on Windows accepts /c/Users/... style paths
    if len(mount_src) >= 2 and mount_src[1] == ":":
        mount_src = "/" + mount_src[0].lower() + mount_src[2:]

    container_workdir = "/work"
    pdb_name = local_pdb.name

    try:
        proc = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", f"{mount_src}:{container_workdir}",
                "-w", container_workdir,
                DOCKER_IMAGE,
                "-f", f"{container_workdir}/{pdb_name}",
            ],
            capture_output=True, text=True, check=False,
            timeout=DOCKER_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        return None

    if proc.returncode != 0 and "POCKET HUNTING" not in (proc.stdout or ""):
        return None

    # Find output dir
    stem = local_pdb.stem
    out_folder = run_dir / f"{stem}_out"
    if not out_folder.exists():
        outs = sorted(run_dir.glob("*_out"), key=lambda p: p.stat().st_mtime, reverse=True)
        out_folder = outs[0] if outs else out_folder

    if not out_folder.exists():
        return None

    # Copy to stable location
    stable_out = FPOCKET_RESULTS_DIR / f"{pdb_id.lower()}_out"
    if not stable_out.exists():
        shutil.copytree(out_folder, stable_out)
    elif stable_out.exists():
        # Update with fresh results
        shutil.rmtree(stable_out)
        shutil.copytree(out_folder, stable_out)

    return _collect_fpocket_pockets(stable_out, top_n=20)


def _evaluate_case(
    case: dict[str, Any],
    tolerance: float,
    min_volume: float,
    druggable_only: bool,
    backend: str = "local",
) -> dict[str, Any]:
    """Evaluate one known cryptic case against fpocket results."""
    pdb_id = case["pdb_id"].upper()
    known_center = case["cryptic_pocket_center"]
    result: dict[str, Any] = {
        "pdb_id": pdb_id,
        "name": case.get("name", ""),
        "pocket_type": case.get("pocket_type", ""),
        "known_center": known_center,
    }

    # Get fpocket pockets
    pockets = _load_cached_fpocket_pockets(pdb_id)
    source = "cached_batch_summary"

    if pockets is None:
        pockets = _try_run_fpocket(pdb_id, backend=backend)
        source = ("docker_fpocket_run" if backend == "docker" else "live_fpocket_run") if pockets is not None else None

    if pockets is None:
        result["fpocket_status"] = "fpocket_not_available"
        result["fpocket_source"] = None
        result["fpocket_detects"] = None
        result["pocket_count"] = 0
        result["best_distance"] = None
        result["best_pocket"] = None
        result["error"] = "No cached fpocket results and fpocket binary not available"
        return result

    result["fpocket_source"] = source
    result["pocket_count"] = len(pockets)

    # Filter and find best matching pocket
    best_dist = float("inf")
    best_pocket = None

    for pocket in pockets:
        center = pocket.get("center")
        if center is None:
            continue

        vol = pocket.get("volume", 0.0)
        if not math.isfinite(vol):
            vol = 0.0

        # Apply filters
        if min_volume > 0 and vol < min_volume:
            continue

        if druggable_only:
            ds = pocket.get("druggability_score", 0.0)
            if not math.isfinite(ds):
                ds = 0.0
            if ds < 0.2:
                continue

        dist = _euclidean_distance(center, known_center)
        if dist < best_dist:
            best_dist = dist
            best_pocket = pocket

    if best_pocket is not None and best_dist <= tolerance:
        result["fpocket_status"] = "detected"
        result["fpocket_detects"] = True
        result["best_distance"] = round(best_dist, 4)
        result["best_pocket"] = best_pocket
    elif best_pocket is not None:
        result["fpocket_status"] = "not_within_tolerance"
        result["fpocket_detects"] = False
        result["best_distance"] = round(best_dist, 4)
        result["best_pocket"] = best_pocket
    else:
        result["fpocket_status"] = "no_qualifying_pockets"
        result["fpocket_detects"] = False
        result["best_distance"] = None
        result["best_pocket"] = None

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="fpocket Known-20 Direct Evaluator")
    parser.add_argument("--tolerance", type=float, default=8.0, help="Distance tolerance in Angstroms (default: 8.0)")
    parser.add_argument("--min-volume", type=float, default=200.0, help="Minimum pocket volume in A^3 (default: 200)")
    parser.add_argument("--top-n", type=int, default=20, help="Top N pockets to consider (default: 20)")
    parser.add_argument("--fpocket-backend", choices=["local", "docker"], default="local",
                        help="Backend for fpocket execution (default: local)")
    args = parser.parse_args()

    backend = args.fpocket_backend
    # Auto-fallback: if local fpocket not found and docker available, use docker
    if backend == "local" and not shutil.which("fpocket") and _docker_available():
        print("[INFO] Local fpocket not found, auto-falling back to Docker backend.")
        backend = "docker"

    tolerance = args.tolerance
    min_volume = args.min_volume
    druggable_only = True

    print(f"[INFO] Canonical parameters: tolerance={tolerance}A, min_volume={min_volume}A^3, druggable_only={druggable_only}, top_n={args.top_n}")

    # Load known cryptic pockets
    kc_data = _load_json(KNOWN_CRYPTIC)
    if not kc_data or "test_cases" not in kc_data:
        print("[ERROR] Cannot load known_cryptic_pockets.json")
        return 1
    test_cases = kc_data["test_cases"]
    print(f"[INFO] Loaded {len(test_cases)} known cryptic pocket cases.")

    # Check fpocket binary / backend
    fpocket_bin = shutil.which("fpocket")
    if backend == "docker":
        docker_ok = _docker_available()
        print(f"[INFO] fpocket backend: DOCKER (image {'FOUND' if docker_ok else 'NOT FOUND'})")
        if not docker_ok:
            print("[ERROR] Docker image not found. Build with: docker build -t biovoid-fpocket:latest BioVoid/docker/fpocket")
            return 1
    else:
        print(f"[INFO] fpocket binary: {'FOUND at ' + fpocket_bin if fpocket_bin else 'NOT FOUND'}")

    # Evaluate each case
    evaluations: list[dict[str, Any]] = []
    n_detected = 0
    n_not_detected = 0
    n_unavailable = 0

    for case in test_cases:
        ev = _evaluate_case(case, tolerance, min_volume, druggable_only, backend=backend)
        evaluations.append(ev)

        status = ev["fpocket_status"]
        if ev.get("fpocket_detects") is True:
            n_detected += 1
            tag = "DETECTED"
        elif ev.get("fpocket_detects") is False:
            n_not_detected += 1
            tag = "NOT_DETECTED"
        else:
            n_unavailable += 1
            tag = "UNAVAILABLE"

        dist_str = f"{ev['best_distance']:.2f}A" if ev.get("best_distance") is not None else "N/A"
        print(f"  {ev['pdb_id']}: {tag} (dist={dist_str}, pockets={ev['pocket_count']}, status={status})")

    # Summary
    n_total = len(evaluations)
    n_evaluated = n_detected + n_not_detected

    output = {
        "generated_at_utc": _utc_now_iso(),
        "canonical_parameters": {
            "tolerance_angstrom": tolerance,
            "min_volume_angstrom3": min_volume,
            "druggable_only": druggable_only,
            "top_n": args.top_n,
        },
        "fpocket_backend": backend,
        "fpocket_binary_available": fpocket_bin is not None or backend == "docker",
        "summary": {
            "total_cases": n_total,
            "evaluated": n_evaluated,
            "detected": n_detected,
            "not_detected": n_not_detected,
            "unavailable": n_unavailable,
            "detection_rate": round(n_detected / n_evaluated, 4) if n_evaluated > 0 else None,
        },
        "evaluations": evaluations,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n[INFO] Wrote: {OUTPUT}")

    print(f"[INFO] Summary: {n_detected} detected, {n_not_detected} not detected, {n_unavailable} unavailable out of {n_total}")
    if n_unavailable > 0:
        print(f"[WARN] {n_unavailable} cases could not be evaluated (fpocket binary not available, no cached results).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
