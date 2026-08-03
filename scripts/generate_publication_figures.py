#!/usr/bin/env python3
"""
Phase 5.5 - Phase 4
Automated figure generation for publication/readiness artifacts.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parent.parent


@dataclass
class FigureArtifact:
    filename: str
    title: str
    description: str


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate publication figures for Phase 5.5 outputs."
    )
    parser.add_argument("--db", default="data/atlas.db", help="Atlas DB path")
    parser.add_argument(
        "--validation-json",
        default="data/validation/validation_results.json",
        help="Known-pocket validation JSON path.",
    )
    parser.add_argument(
        "--fpocket-report",
        default="docs/fpocket_benchmark_report.md",
        help="fpocket benchmark report Markdown path.",
    )
    parser.add_argument(
        "--md-json",
        default="data/validation/md_validation_1g66.json",
        help="MD validation JSON path.",
    )
    parser.add_argument(
        "--fpr-json",
        default="data/validation/false_positive_results.json",
        help="False-positive analysis JSON path.",
    )
    parser.add_argument(
        "--output-dir",
        default="docs/figures",
        help="Output figures directory.",
    )
    parser.add_argument(
        "--index-md",
        default="docs/figures/README.md",
        help="Output figure index Markdown path.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan only.")
    return parser.parse_args()


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _extract_float(pattern: str, text: str) -> float | None:
    m = re.search(pattern, text, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1))
    except (TypeError, ValueError):
        return None


def _load_fpocket_metrics(report_path: Path) -> dict[str, float | None]:
    if not report_path.exists():
        return {
            "overlap": None,
            "threshold": None,
            "matched": None,
            "total_fpocket": None,
            "total_biovoid": None,
        }
    text = report_path.read_text(encoding="utf-8", errors="ignore")
    overlap = _extract_float(r"Global overlap score:\s*\*\*([0-9.]+)\*\*", text)
    threshold = _extract_float(r"min overlap\s*([0-9.]+)\)", text)
    matched = _extract_float(r"Matched pockets:\s*([0-9.]+)", text)
    total_fpocket = _extract_float(r"fpocket total .*:\s*([0-9.]+)", text)
    total_biovoid = _extract_float(r"BioVoid total .*:\s*([0-9.]+)", text)
    return {
        "overlap": overlap,
        "threshold": threshold,
        "matched": matched,
        "total_fpocket": total_fpocket,
        "total_biovoid": total_biovoid,
    }


def _load_db_data(db_path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "scores": [],
        "top_proteins": [],
    }
    if not db_path.exists():
        return out
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        score_rows = conn.execute(
            "SELECT bio_score FROM pockets WHERE bio_score IS NOT NULL"
        ).fetchall()
        out["scores"] = [float(r["bio_score"]) for r in score_rows]
        top_rows = conn.execute(
            """
            SELECT pdb_id, top_bio_score, total_cavities, druggable_cavities
            FROM proteins
            ORDER BY top_bio_score DESC
            LIMIT 10
            """
        ).fetchall()
        out["top_proteins"] = [dict(r) for r in top_rows]
    finally:
        conn.close()
    return out


def _placeholder(ax: Any, title: str, text: str) -> None:
    ax.set_title(title)
    ax.text(0.5, 0.5, text, ha="center", va="center", fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def write_figure_index(index_path: Path, artifacts: list[FigureArtifact]) -> None:
    lines = [
        "# Phase 5.5 Figure Index",
        "",
        f"- Generated at (UTC): {_utc_now()}",
        f"- Total figures: {len(artifacts)}",
        "",
        "| File | Title | Description |",
        "| --- | --- | --- |",
    ]
    for art in artifacts:
        lines.append(f"| `{art.filename}` | {art.title} | {art.description} |")
    lines.append("")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    out_dir = ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    validation = _safe_load_json(ROOT / args.validation_json) or {}
    fpocket = _load_fpocket_metrics(ROOT / args.fpocket_report)
    md_payload = _safe_load_json(ROOT / args.md_json) or {}
    fpr_payload = _safe_load_json(ROOT / args.fpr_json) or {}
    db_data = _load_db_data(ROOT / args.db)

    if args.dry_run:
        print("[DRY-RUN] Figure generation plan")
        print(f"[DRY-RUN] Output dir: {out_dir}")
        return 0

    try:
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch
    except ImportError as exc:
        raise RuntimeError("matplotlib is required for figure generation") from exc

    artifacts: list[FigureArtifact] = []

    # Figure 1: pipeline overview
    fig1, ax1 = plt.subplots(figsize=(12, 4))
    ax1.axis("off")
    phases = [
        ("Phase 1", "Known-pocket\nvalidation"),
        ("Phase 2", "MD validation\n(1G66)"),
        ("Phase 3", "False-positive\nanalysis"),
        ("Phase 4", "Publication\nartifacts"),
    ]
    xs = [0.05, 0.30, 0.55, 0.80]
    for x, (title, text) in zip(xs, phases):
        box = FancyBboxPatch(
            (x, 0.25),
            0.16,
            0.5,
            boxstyle="round,pad=0.02",
            linewidth=1.5,
            edgecolor="#2c3e50",
            facecolor="#ecf0f1",
            transform=ax1.transAxes,
        )
        ax1.add_patch(box)
        ax1.text(x + 0.08, 0.56, title, ha="center", va="center", fontsize=11, weight="bold", transform=ax1.transAxes)
        ax1.text(x + 0.08, 0.40, text, ha="center", va="center", fontsize=9, transform=ax1.transAxes)
    for i in range(len(xs) - 1):
        ax1.annotate(
            "",
            xy=(xs[i + 1] - 0.01, 0.50),
            xytext=(xs[i] + 0.17, 0.50),
            arrowprops=dict(arrowstyle="->", lw=1.5, color="#34495e"),
            xycoords=ax1.transAxes,
        )
    ax1.set_title("BioVoid Phase 5.5 Pipeline Overview", fontsize=13)
    fig1.tight_layout()
    fig1_path = out_dir / "figure_01_pipeline_overview.png"
    fig1.savefig(fig1_path, dpi=220)
    plt.close(fig1)
    artifacts.append(
        FigureArtifact(
            filename=fig1_path.name,
            title="Pipeline Overview",
            description="Phase 5.5 workflow summary from validation to publication artifacts.",
        )
    )

    # Figure 2: validation metrics
    fig2, ax2 = plt.subplots(figsize=(8, 5))
    summary = validation.get("summary", {})
    recall = float(summary.get("recall", 0.0) or 0.0)
    precision = float(summary.get("precision", 0.0) or 0.0)
    f1 = float(summary.get("f1_score", 0.0) or 0.0)
    bars = ax2.bar(["Recall", "Precision", "F1-score"], [recall, precision, f1], color=["#2ecc71", "#3498db", "#9b59b6"])
    ax2.set_ylim(0, max(0.35, recall * 1.2, precision * 1.2, f1 * 1.2))
    ax2.set_ylabel("Score")
    ax2.set_title("Known Cryptic Pocket Validation Metrics")
    for b in bars:
        ax2.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.005, f"{b.get_height():.3f}", ha="center", va="bottom")
    ax2.grid(axis="y", alpha=0.25)
    fig2.tight_layout()
    fig2_path = out_dir / "figure_02_validation_metrics.png"
    fig2.savefig(fig2_path, dpi=220)
    plt.close(fig2)
    artifacts.append(
        FigureArtifact(
            filename=fig2_path.name,
            title="Validation Metrics",
            description="Recall/precision/F1 from known-pocket validation set.",
        )
    )

    # Figure 3: fpocket overlap gate
    fig3, ax3 = plt.subplots(figsize=(7, 5))
    overlap = fpocket.get("overlap")
    threshold = fpocket.get("threshold")
    if overlap is None or threshold is None:
        _placeholder(ax3, "fpocket Benchmark Gate", "Missing fpocket report data")
    else:
        vals = [float(overlap), float(threshold)]
        ax3.bar(["Observed overlap", "Gate threshold"], vals, color=["#e74c3c", "#95a5a6"])
        ax3.set_ylim(0, max(0.45, max(vals) * 1.2))
        ax3.set_ylabel("Overlap score")
        ax3.set_title("fpocket vs BioVoid Overlap Gate")
        for i, v in enumerate(vals):
            ax3.text(i, v + 0.01, f"{v:.4f}", ha="center", va="bottom")
        ax3.grid(axis="y", alpha=0.25)
    fig3.tight_layout()
    fig3_path = out_dir / "figure_03_fpocket_overlap_gate.png"
    fig3.savefig(fig3_path, dpi=220)
    plt.close(fig3)
    artifacts.append(
        FigureArtifact(
            filename=fig3_path.name,
            title="fpocket Overlap Gate",
            description="Observed overlap versus pre-registered gate threshold.",
        )
    )

    # Figure 4: MD timeline
    fig4, (ax4a, ax4b) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    md_samples = md_payload.get("samples", []) if isinstance(md_payload, dict) else []
    if not md_samples:
        _placeholder(ax4a, "MD Validation Timeline", "Missing MD validation samples")
        _placeholder(ax4b, "Pocket Distance", "Missing MD validation samples")
    else:
        x = np.arange(1, len(md_samples) + 1)
        volumes = np.array([float(s.get("matched_volume", 0.0) or 0.0) for s in md_samples], dtype=float)
        distances = np.array(
            [
                float(s.get("best_distance")) if s.get("best_distance") is not None else np.nan
                for s in md_samples
            ],
            dtype=float,
        )
        nma_volume = float(md_payload.get("reference", {}).get("volume", 0.0) or 0.0)
        tol = float(md_payload.get("config", {}).get("distance_tolerance", 8.0) or 8.0)
        ax4a.plot(x, volumes, marker="o", color="#2980b9", linewidth=1.2)
        ax4a.axhline(nma_volume, linestyle="--", color="#c0392b", label="NMA volume")
        ax4a.set_ylabel("Matched volume (A^3)")
        ax4a.set_title("1G66 MD/Snapshot Validation Timeline")
        ax4a.grid(alpha=0.25)
        ax4a.legend(loc="best")
        ax4b.plot(x, distances, marker="o", color="#27ae60", linewidth=1.2)
        ax4b.axhline(tol, linestyle="--", color="#f39c12", label="Tolerance")
        ax4b.set_ylabel("Center distance (A)")
        ax4b.set_xlabel("Sample index")
        ax4b.grid(alpha=0.25)
        ax4b.legend(loc="best")
    fig4.tight_layout()
    fig4_path = out_dir / "figure_04_md_timeline.png"
    fig4.savefig(fig4_path, dpi=220)
    plt.close(fig4)
    artifacts.append(
        FigureArtifact(
            filename=fig4_path.name,
            title="MD Timeline",
            description="Pocket volume and center-distance timeline for 1G66 validation samples.",
        )
    )

    # Figure 5: bioscore histogram
    fig5, ax5 = plt.subplots(figsize=(9, 5))
    scores = db_data.get("scores", [])
    if not scores:
        _placeholder(ax5, "Bio-Score Distribution", "No pocket scores found in atlas DB")
    else:
        ax5.hist(scores, bins=40, color="#8e44ad", alpha=0.85)
        ax5.set_xlabel("Bio-Score")
        ax5.set_ylabel("Pocket count")
        ax5.set_title("Bio-Score Distribution Across Atlas")
        ax5.grid(alpha=0.25)
    fig5.tight_layout()
    fig5_path = out_dir / "figure_05_bioscore_distribution.png"
    fig5.savefig(fig5_path, dpi=220)
    plt.close(fig5)
    artifacts.append(
        FigureArtifact(
            filename=fig5_path.name,
            title="Bio-Score Distribution",
            description="Distribution of all pocket bio-scores in atlas.db.",
        )
    )

    # Figure 6: top discoveries
    fig6, ax6 = plt.subplots(figsize=(10, 5))
    top = db_data.get("top_proteins", [])
    if not top:
        _placeholder(ax6, "Top Discoveries", "No protein summary data available")
    else:
        labels = [str(r["pdb_id"]) for r in top[:10]]
        vals = [float(r["top_bio_score"] or 0.0) for r in top[:10]]
        ax6.bar(labels, vals, color="#16a085")
        ax6.set_ylim(0, max(vals) * 1.1 if vals else 1.0)
        ax6.set_ylabel("Top bio-score")
        ax6.set_title("Top Discoveries by Protein")
        ax6.tick_params(axis="x", rotation=45)
        ax6.grid(axis="y", alpha=0.25)
    fig6.tight_layout()
    fig6_path = out_dir / "figure_06_top_discoveries.png"
    fig6.savefig(fig6_path, dpi=220)
    plt.close(fig6)
    artifacts.append(
        FigureArtifact(
            filename=fig6_path.name,
            title="Top Discoveries",
            description="Top proteins ranked by highest observed bio-score.",
        )
    )

    # Figure 7: FPR breakdown
    fig7, ax7 = plt.subplots(figsize=(8, 5))
    fpr_summary = (fpr_payload.get("summary") or {}).get("fpr", {})
    conservative = fpr_summary.get("conservative")
    strict = fpr_summary.get("strict")
    unknown_rate = fpr_summary.get("unknown_rate")
    if conservative is None and strict is None and unknown_rate is None:
        _placeholder(ax7, "False Positive Analysis", "Missing false-positive analysis data")
    else:
        labels = []
        values = []
        if conservative is not None:
            labels.append("Conservative FPR")
            values.append(float(conservative))
        if strict is not None:
            labels.append("Strict FPR")
            values.append(float(strict))
        if unknown_rate is not None:
            labels.append("Unknown rate")
            values.append(float(unknown_rate))
        ax7.bar(labels, values, color=["#e67e22", "#c0392b", "#7f8c8d"][: len(values)])
        ax7.axhline(0.60, linestyle="--", color="#2c3e50", label="Gate threshold (0.60)")
        ax7.set_ylim(0, max(0.65, max(values) * 1.2 if values else 0.65))
        ax7.set_ylabel("Rate")
        ax7.set_title("False-Positive Analysis Breakdown")
        for i, v in enumerate(values):
            ax7.text(i, v + 0.01, f"{v:.4f}", ha="center")
        ax7.legend(loc="best")
        ax7.grid(axis="y", alpha=0.25)
    fig7.tight_layout()
    fig7_path = out_dir / "figure_07_fpr_breakdown.png"
    fig7.savefig(fig7_path, dpi=220)
    plt.close(fig7)
    artifacts.append(
        FigureArtifact(
            filename=fig7_path.name,
            title="False-Positive Breakdown",
            description="Conservative/strict FPR and unknown-rate comparison.",
        )
    )

    write_figure_index(ROOT / args.index_md, artifacts)

    print(f"[OK] Generated {len(artifacts)} figures in {out_dir}")
    for art in artifacts:
        print(f"[OK] {art.filename}")
    print(f"[OK] Figure index: {ROOT / args.index_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
