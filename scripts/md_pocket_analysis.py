#!/usr/bin/env python3
"""
Phase 5.5 - Phase 2
MD validation analysis for a target pocket (default: 1G66).

This script supports two modes:
1) Trajectory mode (if topology + trajectory are provided and MDAnalysis is installed)
2) Snapshot mode (default) using available PDB snapshots (raw, NMA frames, md_smoke outputs)

Outputs:
- JSON summary: data/validation/md_validation_1g66.json
- Markdown report: docs/md_validation_1g66_report.md
- Figure: docs/figures/md_validation_1g66.png
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cavities import find_cavities
from src.geometry import extract_atom_coords
from src.scoring import rank_pockets


EPS = 1e-12


@dataclass
class NmaReference:
    center: list[float]
    volume: float
    bio_score: float | None
    source: str


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze MD/snapshot pocket behavior for Phase 5.5 validation."
    )
    parser.add_argument("--pdb-id", default="1G66", help="Target protein PDB ID")
    parser.add_argument("--db", default="data/atlas.db", help="Atlas DB path")
    parser.add_argument(
        "--reference-pdb",
        default="data/raw_pdb/1g66.pdb",
        help="Reference PDB for fallback center recomputation",
    )
    parser.add_argument(
        "--pre-reg",
        default="data/validation/pre_registered_config.json",
        help="Pre-registration config path",
    )
    parser.add_argument(
        "--trajectory",
        default="",
        help="Optional trajectory path (.xtc/.dcd). Requires MDAnalysis.",
    )
    parser.add_argument(
        "--topology",
        default="",
        help="Optional topology path for trajectory mode (.pdb/.gro).",
    )
    parser.add_argument(
        "--snapshot-glob",
        action="append",
        default=[],
        help=(
            "Extra snapshot glob relative to project root "
            "(can be repeated). Example: data/md_smoke/1g66*/md_smoke_1g66_final.pdb"
        ),
    )
    parser.add_argument(
        "--profile",
        default="default",
        choices=["default", "enzyme", "ppi", "gpcr"],
        help="Scoring profile used during center recomputation.",
    )
    parser.add_argument(
        "--distance-tolerance",
        type=float,
        default=8.0,
        help="Pocket center match tolerance in Angstrom.",
    )
    parser.add_argument(
        "--open-volume-threshold",
        type=float,
        default=100.0,
        help="Pocket volume threshold for open state.",
    )
    parser.add_argument(
        "--trajectory-stride",
        type=int,
        default=100,
        help="Frame stride for trajectory mode.",
    )
    parser.add_argument(
        "--output-json",
        default="data/validation/md_validation_1g66.json",
        help="Output JSON path.",
    )
    parser.add_argument(
        "--output-md",
        default="docs/md_validation_1g66_report.md",
        help="Output Markdown report path.",
    )
    parser.add_argument(
        "--output-figure",
        default="docs/figures/md_validation_1g66.png",
        help="Output figure path.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show plan without writing files.",
    )
    return parser.parse_args()


def _is_zero_center(center: list[float]) -> bool:
    return len(center) == 3 and all(abs(float(v)) < EPS for v in center)


def load_and_validate_pre_reg(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"Pre-registration config not found: {config_path}")

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    phase = cfg.get("pre_registration", {}).get("phase")
    status = cfg.get("pre_registration", {}).get("status")
    if phase != "5.5" or status != "locked":
        raise ValueError(f"Invalid pre-registration lock (phase={phase}, status={status})")
    return cfg


def _analysis_file_for_recompute(project_root: Path, pdb_id: str, reference_pdb: Path) -> Path:
    pid = pdb_id.lower()
    frames_dir = project_root / "data" / "frames" / pid
    if frames_dir.exists():
        frames = sorted(frames_dir.glob("frame_*.pdb"))
        if frames:
            return frames[len(frames) // 2]
    if reference_pdb.exists():
        return reference_pdb
    raw_pdb = project_root / "data" / "raw_pdb" / f"{pid}.pdb"
    if raw_pdb.exists():
        return raw_pdb
    raise FileNotFoundError(
        f"No structure file found for center recompute ({pdb_id})"
    )


def recompute_top_center(
    project_root: Path,
    pdb_id: str,
    profile: str,
    reference_pdb: Path,
) -> NmaReference:
    analysis_pdb = _analysis_file_for_recompute(project_root, pdb_id, reference_pdb)
    cavities = find_cavities(str(analysis_pdb), merge=True, hydrophobic=True, atom_type="heavy")
    if not cavities:
        raise RuntimeError(f"No cavities found in {analysis_pdb}")
    atom_coords = extract_atom_coords(str(analysis_pdb), atom_type="heavy")
    ranked = rank_pockets(cavities, atom_coords, profile=profile, top_n=None)
    if not ranked:
        raise RuntimeError(f"No ranked pockets found in {analysis_pdb}")

    top = ranked[0]
    center = top.get("center")
    if center is None or len(center) != 3:
        raise RuntimeError(f"Top pocket center missing in {analysis_pdb}")
    return NmaReference(
        center=[float(center[0]), float(center[1]), float(center[2])],
        volume=float(top.get("volume", 0.0) or 0.0),
        bio_score=float(top.get("bio_score", 0.0) or 0.0),
        source=f"recomputed:{analysis_pdb.relative_to(project_root)}",
    )


def resolve_nma_reference(
    db_path: Path,
    pdb_id: str,
    project_root: Path,
    profile: str,
    reference_pdb: Path,
) -> NmaReference:
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT center_x, center_y, center_z, volume, bio_score
                FROM pockets
                WHERE pdb_id = ?
                ORDER BY bio_score DESC
                LIMIT 1
                """,
                (pdb_id.upper(),),
            ).fetchone()
            if row:
                center = [
                    float(row["center_x"] or 0.0),
                    float(row["center_y"] or 0.0),
                    float(row["center_z"] or 0.0),
                ]
                if not _is_zero_center(center):
                    return NmaReference(
                        center=center,
                        volume=float(row["volume"] or 0.0),
                        bio_score=float(row["bio_score"] or 0.0),
                        source="atlas_db_top_pocket",
                    )
        finally:
            conn.close()

    return recompute_top_center(
        project_root=project_root,
        pdb_id=pdb_id,
        profile=profile,
        reference_pdb=reference_pdb,
    )


def collect_snapshot_paths(
    project_root: Path,
    pdb_id: str,
    reference_pdb: Path,
    extra_globs: list[str],
) -> list[Path]:
    pid = pdb_id.lower()
    candidates: list[Path] = []

    default_patterns = [
        f"data/raw_pdb/{pid}.pdb",
        f"data/frames/{pid}/frame_*.pdb",
        f"data/md_smoke/{pid}/md_smoke_{pid}_final.pdb",
        f"data/md_smoke/{pid}_cpu_fallback/md_smoke_{pid}_final.pdb",
        f"data/md_smoke/{pid}_pilot/md_smoke_{pid}_final.pdb",
    ]
    default_patterns.extend(extra_globs)

    for pattern in default_patterns:
        if "*" in pattern or "?" in pattern or "[" in pattern:
            for path in sorted(project_root.glob(pattern)):
                if path.is_file():
                    candidates.append(path)
        else:
            path = project_root / pattern
            if path.is_file():
                candidates.append(path)

    if reference_pdb.exists():
        candidates.append(reference_pdb)

    dedup: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            dedup.append(p)
    return dedup


def _distance(a: list[float], b: list[float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def analyze_snapshot(
    snapshot_path: Path,
    target_center: list[float],
    tolerance: float,
    profile: str,
) -> dict[str, Any]:
    cavities = find_cavities(str(snapshot_path), merge=True, hydrophobic=True, atom_type="heavy")
    if not cavities:
        return {
            "snapshot": str(snapshot_path),
            "mode": "snapshot",
            "n_cavities": 0,
            "matched": False,
            "best_distance": None,
            "best_volume": 0.0,
            "matched_volume": 0.0,
            "best_bio_score": None,
            "best_center": None,
        }

    atom_coords = extract_atom_coords(str(snapshot_path), atom_type="heavy")
    ranked = rank_pockets(cavities, atom_coords, profile=profile, top_n=None)
    if not ranked:
        return {
            "snapshot": str(snapshot_path),
            "mode": "snapshot",
            "n_cavities": len(cavities),
            "matched": False,
            "best_distance": None,
            "best_volume": 0.0,
            "matched_volume": 0.0,
            "best_bio_score": None,
            "best_center": None,
        }

    best_idx = -1
    best_dist = float("inf")
    for i, cavity in enumerate(ranked):
        c = cavity.get("center")
        if c is None or len(c) != 3:
            continue
        center = [float(c[0]), float(c[1]), float(c[2])]
        d = _distance(center, target_center)
        if d < best_dist:
            best_dist = d
            best_idx = i

    if best_idx < 0:
        return {
            "snapshot": str(snapshot_path),
            "mode": "snapshot",
            "n_cavities": len(ranked),
            "matched": False,
            "best_distance": None,
            "best_volume": 0.0,
            "matched_volume": 0.0,
            "best_bio_score": None,
            "best_center": None,
        }

    best = ranked[best_idx]
    best_center = [float(x) for x in best.get("center", [0.0, 0.0, 0.0])]
    best_volume = float(best.get("volume", 0.0) or 0.0)
    best_score = float(best.get("bio_score", 0.0) or 0.0)
    matched = best_dist <= tolerance
    matched_volume = best_volume if matched else 0.0

    return {
        "snapshot": str(snapshot_path),
        "mode": "snapshot",
        "n_cavities": len(ranked),
        "matched": matched,
        "best_distance": best_dist,
        "best_volume": best_volume,
        "matched_volume": matched_volume,
        "best_bio_score": best_score,
        "best_center": best_center,
    }


def analyze_trajectory(
    topology_path: Path,
    trajectory_path: Path,
    target_center: list[float],
    stride: int,
) -> list[dict[str, Any]]:
    try:
        import MDAnalysis as mda
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "MDAnalysis is required for trajectory mode. "
            "Install it or run snapshot mode."
        ) from exc

    universe = mda.Universe(str(topology_path), str(trajectory_path))
    center = np.array(target_center, dtype=float)

    samples: list[dict[str, Any]] = []
    for ts in universe.trajectory[:: max(1, stride)]:
        atoms = universe.select_atoms("protein and not name H*")
        if atoms.n_atoms == 0:
            continue
        coords = atoms.positions
        dists = np.linalg.norm(coords - center, axis=1)
        radius_clear = float(np.min(dists))
        pocket_volume = float((4.0 / 3.0) * math.pi * (radius_clear**3))
        samples.append(
            {
                "snapshot": f"frame:{ts.frame}",
                "mode": "trajectory",
                "time_ps": float(ts.time),
                "n_cavities": None,
                "matched": True,
                "best_distance": 0.0,
                "best_volume": pocket_volume,
                "matched_volume": pocket_volume,
                "best_bio_score": None,
                "best_center": target_center,
            }
        )
    return samples


def summarize_samples(
    samples: list[dict[str, Any]],
    nma_volume: float,
    open_volume_threshold: float,
) -> dict[str, Any]:
    volumes = [float(s.get("matched_volume", 0.0) or 0.0) for s in samples]
    if not volumes:
        return {
            "n_samples": 0,
            "avg_volume": 0.0,
            "max_volume": 0.0,
            "open_fraction": 0.0,
            "distance_stats": None,
            "status": "VALIDATION_FAILED",
            "status_label": "FAILED",
            "reason": "No analyzable samples.",
            "nma_volume": nma_volume,
            "md_over_nma_ratio": 0.0,
        }

    distances = [
        float(s["best_distance"])
        for s in samples
        if s.get("best_distance") is not None
    ]
    avg_volume = float(np.mean(volumes))
    max_volume = float(np.max(volumes))
    open_fraction = float(sum(v >= open_volume_threshold for v in volumes) / len(volumes))
    ratio = float((max_volume / nma_volume) if nma_volume > 0 else 0.0)

    if max_volume >= nma_volume * 0.5 and open_fraction > 0.10:
        status = "VALIDATION_SUCCESS"
        status_label = "SUCCESS"
        reason = "MD/snapshot maximum volume reached >= 50% of NMA prediction and open fraction > 10%."
    elif max_volume >= nma_volume * 0.5:
        status = "VALIDATION_PARTIAL"
        status_label = "PARTIAL"
        reason = "Volume criterion met but open fraction <= 10%."
    else:
        status = "VALIDATION_FAILED"
        status_label = "FAILED"
        reason = "Maximum observed volume did not reach 50% of NMA prediction."

    return {
        "n_samples": len(samples),
        "avg_volume": avg_volume,
        "max_volume": max_volume,
        "open_fraction": open_fraction,
        "distance_stats": {
            "min": float(np.min(distances)) if distances else None,
            "mean": float(np.mean(distances)) if distances else None,
            "max": float(np.max(distances)) if distances else None,
        },
        "status": status,
        "status_label": status_label,
        "reason": reason,
        "nma_volume": nma_volume,
        "md_over_nma_ratio": ratio,
    }


def write_md_report(
    output_path: Path,
    payload: dict[str, Any],
) -> None:
    ref = payload["reference"]
    summary = payload["summary"]
    samples = payload["samples"]
    source_counts: dict[str, int] = {}
    for s in samples:
        mode = str(s.get("mode", "unknown"))
        source_counts[mode] = source_counts.get(mode, 0) + 1

    lines = [
        "# 1G66 MD Validation Report (Phase 5.5 / Phase 2)",
        "",
        f"- Generated at (UTC): {payload['generated_at_utc']}",
        f"- Target protein: {payload['pdb_id']}",
        f"- Pre-registration status: {payload['pre_registration_status']}",
        "",
        "## NMA Reference Pocket",
        "",
        f"- Center: {ref['center']}",
        f"- NMA volume: {ref['volume']:.3f}",
        f"- NMA bio-score: {ref['bio_score'] if ref['bio_score'] is not None else 'n/a'}",
        f"- Source: {ref['source']}",
        "",
        "## Analysis Summary",
        "",
        f"- Samples analyzed: {summary['n_samples']}",
        f"- Average matched volume: {summary['avg_volume']:.3f}",
        f"- Maximum matched volume: {summary['max_volume']:.3f}",
        f"- Open fraction (volume >= threshold): {summary['open_fraction'] * 100:.2f}%",
        f"- MD/NMA max-volume ratio: {summary['md_over_nma_ratio']:.4f}",
        f"- Status: **{summary['status_label']}** ({summary['status']})",
        f"- Reason: {summary['reason']}",
        "",
        "## Source Breakdown",
        "",
    ]
    for k, v in sorted(source_counts.items()):
        lines.append(f"- {k}: {v}")

    lines.extend(
        [
            "",
            "## Sample Details (first 15)",
            "",
            "| Sample | Mode | Matched | Distance | Matched Volume | Best Score |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for sample in samples[:15]:
        lines.append(
            "| {sample} | {mode} | {matched} | {dist} | {vol:.3f} | {score} |".format(
                sample=Path(str(sample.get("snapshot", ""))).name,
                mode=sample.get("mode", ""),
                matched="yes" if sample.get("matched") else "no",
                dist=(
                    f"{float(sample['best_distance']):.3f}"
                    if sample.get("best_distance") is not None
                    else "n/a"
                ),
                vol=float(sample.get("matched_volume", 0.0) or 0.0),
                score=(
                    f"{float(sample['best_bio_score']):.4f}"
                    if sample.get("best_bio_score") is not None
                    else "n/a"
                ),
            )
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_figure(
    output_path: Path,
    payload: dict[str, Any],
) -> bool:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    samples = payload["samples"]
    if not samples:
        return False

    x = list(range(1, len(samples) + 1))
    volumes = [float(s.get("matched_volume", 0.0) or 0.0) for s in samples]
    distances: list[float] = []
    for s in samples:
        if s.get("best_distance") is None:
            distances.append(float("nan"))
        else:
            distances.append(float(s["best_distance"]))

    nma_volume = float(payload["reference"]["volume"])
    tolerance = float(payload["config"]["distance_tolerance"])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    ax1.plot(x, volumes, marker="o", linewidth=1.2, color="#1f77b4")
    ax1.axhline(nma_volume, linestyle="--", color="#d62728", label="NMA volume")
    ax1.set_ylabel("Matched volume (A^3)")
    ax1.set_title(f"{payload['pdb_id']} pocket volume timeline")
    ax1.grid(alpha=0.3)
    ax1.legend(loc="best")

    ax2.plot(x, distances, marker="o", linewidth=1.2, color="#2ca02c")
    ax2.axhline(tolerance, linestyle="--", color="#ff7f0e", label="Distance tolerance")
    ax2.set_ylabel("Center distance (A)")
    ax2.set_xlabel("Sample index")
    ax2.set_title("Nearest pocket-to-reference center distance")
    ax2.grid(alpha=0.3)
    ax2.legend(loc="best")

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220)
    plt.close(fig)
    return True


def main() -> int:
    args = parse_args()
    project_root = ROOT
    pdb_id = args.pdb_id.upper()
    db_path = project_root / args.db
    reference_pdb = project_root / args.reference_pdb
    config_path = project_root / args.pre_reg
    output_json = project_root / args.output_json
    output_md = project_root / args.output_md
    output_figure = project_root / args.output_figure

    cfg = load_and_validate_pre_reg(config_path)

    if args.distance_tolerance != float(
        cfg.get("canonical_parameters", {}).get("proximity_tolerance_angstrom", 8.0)
    ):
        raise ValueError(
            "Distance tolerance differs from pre-registered canonical tolerance."
        )

    reference = resolve_nma_reference(
        db_path=db_path,
        pdb_id=pdb_id,
        project_root=project_root,
        profile=args.profile,
        reference_pdb=reference_pdb,
    )

    samples: list[dict[str, Any]] = []
    mode = "snapshot"
    if args.trajectory:
        topology = Path(args.topology) if args.topology else reference_pdb
        topology_abs = topology if topology.is_absolute() else project_root / topology
        trajectory_abs = Path(args.trajectory)
        if not trajectory_abs.is_absolute():
            trajectory_abs = project_root / trajectory_abs
        if topology_abs.exists() and trajectory_abs.exists():
            samples = analyze_trajectory(
                topology_path=topology_abs,
                trajectory_path=trajectory_abs,
                target_center=reference.center,
                stride=args.trajectory_stride,
            )
            mode = "trajectory"
        else:
            raise FileNotFoundError(
                f"Trajectory mode requested but files missing: {topology_abs}, {trajectory_abs}"
            )
    else:
        snapshots = collect_snapshot_paths(
            project_root=project_root,
            pdb_id=pdb_id,
            reference_pdb=reference_pdb,
            extra_globs=args.snapshot_glob,
        )
        if not snapshots:
            raise RuntimeError("No snapshots found for analysis.")
        for path in snapshots:
            samples.append(
                analyze_snapshot(
                    snapshot_path=path,
                    target_center=reference.center,
                    tolerance=args.distance_tolerance,
                    profile=args.profile,
                )
            )

    summary = summarize_samples(
        samples=samples,
        nma_volume=reference.volume,
        open_volume_threshold=args.open_volume_threshold,
    )

    payload = {
        "generated_at_utc": _utc_now(),
        "pdb_id": pdb_id,
        "analysis_mode": mode,
        "pre_registration_status": cfg.get("pre_registration", {}).get("status"),
        "reference": {
            "center": reference.center,
            "volume": reference.volume,
            "bio_score": reference.bio_score,
            "source": reference.source,
        },
        "config": {
            "distance_tolerance": args.distance_tolerance,
            "open_volume_threshold": args.open_volume_threshold,
            "trajectory_stride": args.trajectory_stride,
            "profile": args.profile,
        },
        "summary": summary,
        "samples": samples,
    }

    if args.dry_run:
        print("[DRY-RUN] MD pocket analysis plan")
        print(f"[DRY-RUN] pdb_id={pdb_id} mode={mode}")
        print(f"[DRY-RUN] reference={payload['reference']}")
        print(f"[DRY-RUN] samples={len(samples)}")
        return 0

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    write_md_report(output_md, payload)
    figure_ok = write_figure(output_figure, payload)

    print(f"[OK] JSON: {output_json}")
    print(f"[OK] Markdown: {output_md}")
    if figure_ok:
        print(f"[OK] Figure: {output_figure}")
    else:
        print("[WARN] Figure generation skipped (matplotlib missing or no data).")
    print(f"[INFO] Status: {summary['status']} ({summary['status_label']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
