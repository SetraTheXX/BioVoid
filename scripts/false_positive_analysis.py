#!/usr/bin/env python3
"""
Phase 5.5 - Phase 3
False-positive analysis with deterministic sampling and pre-registered guards.

Outputs:
- JSON: data/validation/false_positive_results.json
- Markdown report: docs/false_positive_report.md
- Protocol: docs/false_positive_protocol.md
- Metrics definition: docs/metrics_definition.md
- Statistical appendix: docs/statistical_appendix.md
"""

from __future__ import annotations

import argparse
import json
import math
import random
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

NON_LIGAND_RESNAMES = {
    "HOH",
    "WAT",
    "DOD",
    "SOL",
    "H2O",
    "NA",
    "CL",
    "K",
    "MG",
    "CA",
    "ZN",
    "MN",
    "FE",
    "CU",
    "CO",
    "NI",
    "CD",
    "HG",
    "SO4",
    "PO4",
    "GOL",
    "PEG",
    "EDO",
    "ACT",
}

EVIDENCE_WEIGHTS = {
    "known_match": 0.2,
    "ligand_nearby": 0.3,
    "fpocket_match": 0.3,
    "docking_validated": 0.2,
}
DEFAULT_SUPPORT_THRESHOLD = 0.3
DEFAULT_MIN_EVIDENCE_SOURCES = 2


@dataclass
class CanonicalParams:
    tolerance: float
    top_n: int
    druggable_filter: bool
    min_druggable_volume: float
    max_fpr: float


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Phase 5.5 false-positive analysis on pilot atlas."
    )
    parser.add_argument("--db", default="data/atlas.db", help="Atlas DB path")
    parser.add_argument(
        "--pre-reg",
        default="data/validation/pre_registered_config.json",
        help="Pre-registration config path",
    )
    parser.add_argument(
        "--known-set",
        default="data/validation/known_cryptic_pockets.json",
        help="Known cryptic pocket set (for center proximity evidence).",
    )
    parser.add_argument(
        "--fpocket-summary",
        default="data/benchmark/fpocket_results/fpocket_batch_summary.json",
        help="fpocket benchmark summary (for overlap evidence).",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=50,
        help="Number of proteins sampled from pilot atlas.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=55,
        help="Deterministic random seed.",
    )
    parser.add_argument(
        "--min-bio-score",
        type=float,
        default=0.7,
        help="High-druggability threshold for candidate pockets.",
    )
    parser.add_argument(
        "--ligand-radius",
        type=float,
        default=10.0,
        help="Ligand evidence radius in Angstrom.",
    )
    parser.add_argument(
        "--profile",
        default="default",
        choices=["default", "enzyme", "ppi", "gpcr"],
        help="Profile used in center recomputation fallback.",
    )
    parser.add_argument(
        "--bootstrap-iter",
        type=int,
        default=3000,
        help="Bootstrap iterations for CI estimation.",
    )
    parser.add_argument(
        "--support-threshold",
        type=float,
        default=DEFAULT_SUPPORT_THRESHOLD,
        help=(
            "Weighted evidence threshold for 'supported' class "
            "(default: 0.3)."
        ),
    )
    parser.add_argument(
        "--min-evidence-sources",
        type=int,
        default=DEFAULT_MIN_EVIDENCE_SOURCES,
        help=(
            "Minimum available external evidence sources required "
            "to classify as supported/unsupported (default: 2)."
        ),
    )
    parser.add_argument(
        "--output-json",
        default="data/validation/false_positive_results.json",
        help="Output JSON path.",
    )
    parser.add_argument(
        "--output-md",
        default="docs/false_positive_report.md",
        help="Output Markdown report path.",
    )
    parser.add_argument(
        "--output-protocol",
        default="docs/false_positive_protocol.md",
        help="Output protocol Markdown path.",
    )
    parser.add_argument(
        "--output-metrics",
        default="docs/metrics_definition.md",
        help="Output metrics-definition Markdown path.",
    )
    parser.add_argument(
        "--output-stat",
        default="docs/statistical_appendix.md",
        help="Output statistical appendix Markdown path.",
    )
    parser.add_argument(
        "--output-manual-review",
        default="docs/false_positive_manual_review.md",
        help="Output manual-review Markdown path.",
    )
    parser.add_argument(
        "--manual-review-top-n",
        type=int,
        default=20,
        help="Number of unsupported pockets to include in manual review.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned run without writing outputs.",
    )
    return parser.parse_args()


def load_pre_reg(config_path: Path) -> tuple[dict[str, Any], CanonicalParams]:
    if not config_path.exists():
        raise FileNotFoundError(f"Pre-registration config not found: {config_path}")
    cfg = json.loads(config_path.read_text(encoding="utf-8"))

    phase = cfg.get("pre_registration", {}).get("phase")
    status = cfg.get("pre_registration", {}).get("status")
    if phase != "5.5" or status != "locked":
        raise ValueError(f"Invalid pre-registration lock (phase={phase}, status={status})")

    cp = cfg.get("canonical_parameters", {})
    dg = cfg.get("decision_gates", {})
    params = CanonicalParams(
        tolerance=float(cp.get("proximity_tolerance_angstrom", 8.0)),
        top_n=int(cp.get("top_n_pockets_to_consider", 20)),
        druggable_filter=bool(cp.get("druggable_filter", True)),
        min_druggable_volume=float(cp.get("min_druggable_volume_angstrom3", 200.0)),
        max_fpr=float(dg.get("max_false_positive_rate", 0.60)),
    )
    if params.tolerance != 8.0:
        raise ValueError("Tolerance drift detected in pre-registration config.")
    if params.top_n != 20:
        raise ValueError("Top-N drift detected in pre-registration config.")
    if not params.druggable_filter:
        raise ValueError("Druggable filter drift detected in pre-registration config.")
    return cfg, params


def _distance(a: list[float], b: list[float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _is_valid_center(center: list[float] | None) -> bool:
    if center is None or len(center) != 3:
        return False
    return all(math.isfinite(float(v)) for v in center)


def _is_zero_center(center: list[float]) -> bool:
    return _is_valid_center(center) and all(abs(float(v)) < EPS for v in center)


def load_known_centers(path: Path) -> dict[str, list[list[float]]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[list[float]]] = {}
    for tc in payload.get("test_cases", []):
        if not isinstance(tc, dict):
            continue
        pdb_id = str(tc.get("pdb_id", "")).upper()
        center = tc.get("cryptic_pocket_center")
        if not pdb_id or not isinstance(center, list) or len(center) != 3:
            continue
        try:
            parsed = [float(center[0]), float(center[1]), float(center[2])]
        except (TypeError, ValueError):
            continue
        out.setdefault(pdb_id, []).append(parsed)
    return out


def load_fpocket_centers(path: Path) -> dict[str, list[list[float]]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[list[float]]] = {}
    for row in payload.get("results", []):
        if not isinstance(row, dict):
            continue
        if str(row.get("status", "")).lower() != "ok":
            continue
        pdb_id = str(row.get("pdb_id", "")).upper()
        if not pdb_id:
            continue
        centers: list[list[float]] = []
        for pocket in row.get("pockets", []):
            if not isinstance(pocket, dict):
                continue
            center = pocket.get("center")
            if not isinstance(center, list) or len(center) != 3:
                continue
            try:
                c = [float(center[0]), float(center[1]), float(center[2])]
            except (TypeError, ValueError):
                continue
            if _is_zero_center(c):
                continue
            centers.append(c)
        if centers:
            out[pdb_id] = centers
    return out


def _pick_analysis_pdb(project_root: Path, pdb_id: str) -> Path | None:
    pid = pdb_id.lower()
    frames_dir = project_root / "data" / "frames" / pid
    if frames_dir.exists():
        frames = sorted(frames_dir.glob("frame_*.pdb"))
        if frames:
            return frames[len(frames) // 2]
    raw = project_root / "data" / "raw_pdb" / f"{pid}.pdb"
    if raw.exists():
        return raw
    return None


def recompute_centers_by_rank(
    project_root: Path,
    pdb_id: str,
    profile: str,
) -> dict[int, list[float]]:
    analysis_pdb = _pick_analysis_pdb(project_root, pdb_id)
    if analysis_pdb is None:
        return {}
    cavities = find_cavities(str(analysis_pdb), merge=True, hydrophobic=True, atom_type="heavy")
    if not cavities:
        return {}
    atom_coords = extract_atom_coords(str(analysis_pdb), atom_type="heavy")
    ranked = rank_pockets(cavities, atom_coords, profile=profile, top_n=None)
    out: dict[int, list[float]] = {}
    for i, cavity in enumerate(ranked, start=1):
        center = cavity.get("center")
        if center is None or len(center) != 3:
            continue
        out[i] = [float(center[0]), float(center[1]), float(center[2])]
    return out


def parse_ligand_atoms(pdb_path: Path) -> list[list[float]]:
    atoms: list[list[float]] = []
    if not pdb_path.exists():
        return atoms

    for line in pdb_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.startswith("HETATM"):
            continue
        if len(line) < 54:
            continue
        resname = line[17:20].strip().upper()
        if resname in NON_LIGAND_RESNAMES:
            continue
        try:
            x = float(line[30:38].strip())
            y = float(line[38:46].strip())
            z = float(line[46:54].strip())
        except ValueError:
            continue
        atoms.append([x, y, z])
    return atoms


def bootstrap_ci(values: list[int], n_iter: int = 3000, seed: int = 55) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    rng = np.random.default_rng(seed)
    arr = np.asarray(values, dtype=float)
    boot = []
    for _ in range(max(200, n_iter)):
        sample = rng.choice(arr, size=len(arr), replace=True)
        boot.append(float(np.mean(sample)))
    return float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def compute_weighted_score(evidence_flags: dict[str, bool]) -> float:
    score = 0.0
    for key, weight in EVIDENCE_WEIGHTS.items():
        if evidence_flags.get(key, False):
            score += float(weight)
    return score


def unknown_reason_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in records:
        if row.get("classification") != "unknown":
            continue
        reason = str(row.get("unknown_reason") or "unspecified")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def load_validation_recall(project_root: Path) -> dict[str, Any] | None:
    path = project_root / "data" / "validation" / "validation_results.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload.get("summary", {})
    if not isinstance(summary, dict):
        return None
    tp = int(summary.get("true_positives", 0) or 0)
    fn = int(summary.get("false_negatives", 0) or 0)
    total = tp + fn
    if total <= 0:
        return None
    labels = [1] * tp + [0] * fn
    ci_low, ci_high = bootstrap_ci(labels, n_iter=3000, seed=112)
    return {
        "recall": float(summary.get("recall", 0.0) or 0.0),
        "tp": tp,
        "fn": fn,
        "total": total,
        "ci95": [ci_low, ci_high],
        "config": summary.get("config", {}),
    }


def write_protocol(
    path: Path,
    *,
    support_threshold: float,
    min_evidence_sources: int,
    ligand_radius: float,
) -> None:
    lines = [
        "# False-Positive Analysis Protocol (Phase 5.5 / Phase 3)",
        "",
        "1. Sample 50 proteins from `proteins` table with deterministic seed.",
        "2. For each sampled protein, select high-confidence pockets (`druggable=1` and `bio_score >= 0.7`).",
        "3. Repair missing pocket centers via cavity recomputation on local structures (frame or raw PDB).",
        "4. Evaluate support evidence per pocket:",
        "   - Known-cryptic set proximity (`<= 8A`)",
        f"   - Ligand proximity in raw PDB (`<= {ligand_radius:.1f}A` to non-water HETATM atoms)",
        "   - fpocket overlap in benchmark summary (`<= 8A`)",
        "   - Docking validation flag (`validated = 1`)",
        "5. Compute weighted evidence score:",
        "   - known_match: 0.2",
        "   - ligand_nearby: 0.3",
        "   - fpocket_match: 0.3",
        "   - docking_validated: 0.2",
        f"   - supported if weighted_score >= {support_threshold:.2f}",
        "6. Apply explicit unknown handling:",
        "   - `unknown` if center missing/recompute failed",
        "   - `unknown` if available evidence sources are below minimum",
        f"     (`available_sources < {min_evidence_sources}`)",
        "7. Classification:",
        "   - `supported`: weighted threshold met",
        "   - `unsupported`: threshold not met, sufficient evidence coverage",
        "   - `unknown`: insufficient inputs/coverage",
        "8. Compute:",
        "   - Conservative FPR = unsupported / (supported + unsupported)",
        "   - Strict FPR = (unsupported + unknown) / total",
        "   - Unknown rate = unknown / total",
        "",
        "Notes:",
        "- This is an automated proxy and not a substitute for manual literature curation.",
        "- Unknown cases are reported separately to avoid inflating conservative FPR.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_metrics_definition(
    path: Path,
    *,
    max_fpr: float,
    support_threshold: float,
    min_evidence_sources: int,
) -> None:
    lines = [
        "# Metrics Definition (Phase 5.5)",
        "",
        "## Pre-registered decision metrics",
        "",
        "- Recall: `TP / (TP + FN)`",
        "- fpocket overlap (Dice-like): `2 * matches / (N_fpocket + N_biovoid)`",
        "- MD validation pass rule: at least one required protein validated (`min_md_validated_proteins = 1`)",
        f"- False Positive Rate (FPR) gate: `FPR <= {max_fpr:.2f}`",
        "",
        "## FPR variants in this report",
        "",
        "- Weighted support score:",
        "  - `score = 0.2*known + 0.3*ligand + 0.3*fpocket + 0.2*docking`",
        f"  - `supported` if `score >= {support_threshold:.2f}`",
        f"- Explicit unknown handling: `unknown` if available sources < {min_evidence_sources}",
        "",
        "- Conservative FPR: `unsupported / (supported + unsupported)`",
        "- Strict FPR: `(unsupported + unknown) / total_candidates`",
        "- Unknown rate: `unknown / total_candidates`",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_statistical_appendix(path: Path, payload: dict[str, Any]) -> None:
    fpr = payload["summary"]["fpr"]
    recall = payload.get("recall_context")
    lines = [
        "# Statistical Appendix (Phase 5.5)",
        "",
        "## False-Positive Analysis",
        "",
        f"- Conservative FPR: {fpr['conservative'] if fpr['conservative'] is not None else 'n/a'}",
        f"- Conservative FPR 95% bootstrap CI: {fpr['conservative_ci95']}",
        f"- Strict FPR: {fpr['strict'] if fpr['strict'] is not None else 'n/a'}",
        f"- Strict FPR 95% bootstrap CI: {fpr['strict_ci95']}",
        f"- Unknown rate: {fpr['unknown_rate'] if fpr['unknown_rate'] is not None else 'n/a'}",
        "",
    ]
    if recall is not None:
        lines.extend(
            [
                "## Recall Context (Known-Cryptic Validation Set)",
                "",
                f"- Recall: {recall['recall']:.4f} ({recall['tp']}/{recall['total']})",
                f"- Recall 95% bootstrap CI: {recall['ci95']}",
                f"- Validation config snapshot: {recall['config']}",
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_markdown_report(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    fpr = summary["fpr"]
    weighted_cfg = summary.get("weighted_scoring", {})
    unknown_reasons = summary.get("unknown_reason_counts", {})
    top_n = int(payload["config"].get("manual_review_top_n", 20))
    top_unsupported = sorted(
        [r for r in payload["records"] if r["classification"] == "unsupported"],
        key=lambda r: r.get("bio_score", 0.0),
        reverse=True,
    )[:top_n]

    lines = [
        "# False-Positive Analysis Report (Phase 5.5 / Phase 3 v2)",
        "",
        f"- Generated at (UTC): {payload['generated_at_utc']}",
        f"- Sample size: {summary['sample_size']}",
        f"- Candidate pockets evaluated: {summary['candidate_pockets']}",
        f"- Seed: {payload['config']['seed']}",
        "",
        "## Classification Counts",
        "",
        f"- Supported: {summary['supported_count']}",
        f"- Unsupported: {summary['unsupported_count']}",
        f"- Unknown: {summary['unknown_count']}",
        "",
        "## FPR Metrics",
        "",
        f"- Conservative FPR: **{fpr['conservative']:.4f}**"
        if fpr["conservative"] is not None
        else "- Conservative FPR: n/a",
        f"- Strict FPR: **{fpr['strict']:.4f}**"
        if fpr["strict"] is not None
        else "- Strict FPR: n/a",
        f"- Unknown rate: **{fpr['unknown_rate']:.4f}**"
        if fpr["unknown_rate"] is not None
        else "- Unknown rate: n/a",
        f"- Conservative gate (`<= {payload['config']['max_fpr']:.2f}`): **{summary['gate_status']}**",
        "",
        "## Evidence Source Hits",
        "",
        f"- Known cryptic proximity: {summary['evidence_counts']['known_match']}",
        f"- Ligand proximity: {summary['evidence_counts']['ligand_nearby']}",
        f"- fpocket overlap: {summary['evidence_counts']['fpocket_match']}",
        f"- Docking validated: {summary['evidence_counts']['docking_validated']}",
        "",
        "## Weighted Evidence Configuration",
        "",
        (
            f"- Weights: known={weighted_cfg.get('known_match', 0.2):.1f}, "
            f"ligand={weighted_cfg.get('ligand_nearby', 0.3):.1f}, "
            f"fpocket={weighted_cfg.get('fpocket_match', 0.3):.1f}, "
            f"docking={weighted_cfg.get('docking_validated', 0.2):.1f}"
        ),
        f"- Support threshold: {payload['config']['support_threshold']:.2f}",
        f"- Min evidence sources: {payload['config']['min_evidence_sources']}",
        "",
        "## Unknown Handling Breakdown",
        "",
    ]
    if unknown_reasons:
        for reason, count in sorted(
            unknown_reasons.items(), key=lambda kv: (-kv[1], kv[0])
        ):
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
        "## Top Unsupported Candidates",
        "",
            "| PDB | Pocket | Bio-Score | Volume | Weighted Score | Sources | Center Source |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in top_unsupported:
        lines.append(
            (
                "| {pdb} | {pid} | {score:.4f} | {vol:.2f} | "
                "{wscore:.2f} | {src_count} | {src} |"
            ).format(
                pdb=row["pdb_id"],
                pid=row["pocket_id"],
                score=float(row["bio_score"]),
                vol=float(row["volume"]),
                wscore=float(row.get("weighted_evidence_score", 0.0)),
                src_count=int(row.get("available_sources_count", 0)),
                src=row["center_source"],
            )
        )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Unknown records use explicit reasons (`center_missing`, `no_evidence_sources`, `low_evidence_coverage`).",
            "- Conservative FPR is used for decision-gate comparison.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_manual_review_report(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    threshold = float(payload["config"]["support_threshold"])
    top_n = int(payload["config"].get("manual_review_top_n", 20))
    unsupported = sorted(
        [r for r in payload["records"] if r["classification"] == "unsupported"],
        key=lambda r: r.get("bio_score", 0.0),
        reverse=True,
    )[:top_n]

    lines = [
        "# False Positive Manual Review (Phase 5.5 / P1.3 v2)",
        "",
        f"- Generated at (UTC): {payload['generated_at_utc']}",
        f"- Reviewed unsupported candidates: {len(unsupported)}",
        f"- Manual review scope: top-{top_n} unsupported by bio-score",
        "",
        "## Review Rules",
        "",
        "- Rule 1: weighted_score < threshold and sufficient source coverage => unsupported review candidate.",
        "- Rule 2: weighted_score near threshold (>= threshold-0.1) => borderline candidate.",
        "- Rule 3: no near ligand/fpocket/known evidence with high score => likely false positive.",
        "",
        "## Top Unsupported Manual Review",
        "",
        "| PDB | Pocket | Bio-Score | Weighted | Sources | Near Ligand | Near fpocket | Near Known | Verdict | Notes |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |",
    ]

    verdict_counts = {
        "likely_false_positive": 0,
        "borderline_needs_followup": 0,
    }

    for row in unsupported:
        evidence = row.get("evidence", {})
        w_score = float(row.get("weighted_evidence_score", 0.0))
        near_lig = bool(evidence.get("ligand_nearby", False))
        near_fp = bool(evidence.get("fpocket_match", False))
        near_known = bool(evidence.get("known_match", False))
        if w_score >= max(0.0, threshold - 0.1):
            verdict = "borderline_needs_followup"
            notes = "Thresholda yakin; ek deneysel kanit veya docking onceliklendir."
        else:
            verdict = "likely_false_positive"
            notes = "Yeterli kaynak var ama yakin destek yok; FP olasiligi yuksek."
        verdict_counts[verdict] += 1

        lines.append(
            (
                "| {pdb} | {pid} | {score:.4f} | {w:.2f} | {src} | {lig} | {fp} | {known} | {v} | {n} |"
            ).format(
                pdb=row["pdb_id"],
                pid=row["pocket_id"],
                score=float(row["bio_score"]),
                w=w_score,
                src=int(row.get("available_sources_count", 0)),
                lig="yes" if near_lig else "no",
                fp="yes" if near_fp else "no",
                known="yes" if near_known else "no",
                v=verdict,
                n=notes,
            )
        )

    lines.extend(
        [
            "",
            "## Review Summary",
            "",
            f"- likely_false_positive: {verdict_counts['likely_false_positive']}",
            f"- borderline_needs_followup: {verdict_counts['borderline_needs_followup']}",
            "",
            "## Conclusion",
            "",
            "- Manual review tamamlandi (top unsupported listesi incelendi ve etiketlendi).",
            "- Borderline adaylar P1.3 sonrasi hedefli docking/ligand check ile tekrar gozden gecirilmeli.",
            "",
        ]
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    project_root = ROOT

    db_path = project_root / args.db
    pre_reg_path = project_root / args.pre_reg
    known_set_path = project_root / args.known_set
    fpocket_path = project_root / args.fpocket_summary
    output_json = project_root / args.output_json
    output_md = project_root / args.output_md
    output_protocol = project_root / args.output_protocol
    output_metrics = project_root / args.output_metrics
    output_stat = project_root / args.output_stat
    output_manual_review = project_root / args.output_manual_review

    cfg, canonical = load_pre_reg(pre_reg_path)
    if args.min_bio_score <= 0:
        raise ValueError("--min-bio-score must be > 0")
    if args.sample_size <= 0:
        raise ValueError("--sample-size must be > 0")
    if args.support_threshold <= 0 or args.support_threshold > 1.0:
        raise ValueError("--support-threshold must be in (0, 1]")
    if args.min_evidence_sources <= 0:
        raise ValueError("--min-evidence-sources must be >= 1")
    if args.manual_review_top_n <= 0:
        raise ValueError("--manual-review-top-n must be >= 1")

    known_centers = load_known_centers(known_set_path)
    fpocket_centers = load_fpocket_centers(fpocket_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    has_docking_table = table_exists(conn, "docking_results")

    rng = random.Random(args.seed)
    proteins = [
        str(r["pdb_id"]).upper()
        for r in conn.execute(
            "SELECT pdb_id FROM proteins WHERE status = 'success' ORDER BY pdb_id"
        ).fetchall()
    ]
    if not proteins:
        raise RuntimeError("No proteins available in atlas.")
    sample_size = min(args.sample_size, len(proteins))
    sampled_proteins = sorted(rng.sample(proteins, sample_size))

    recompute_cache: dict[str, dict[int, list[float]]] = {}
    ligand_cache: dict[str, list[list[float]]] = {}

    records: list[dict[str, Any]] = []
    evidence_counts = {
        "known_match": 0,
        "ligand_nearby": 0,
        "fpocket_match": 0,
        "docking_validated": 0,
    }

    def get_ligands(pdb_id: str) -> list[list[float]]:
        if pdb_id in ligand_cache:
            return ligand_cache[pdb_id]
        pdb_path = project_root / "data" / "raw_pdb" / f"{pdb_id.lower()}.pdb"
        atoms = parse_ligand_atoms(pdb_path)
        ligand_cache[pdb_id] = atoms
        return atoms

    for pdb_id in sampled_proteins:
        rows = conn.execute(
            """
            SELECT pocket_id, rank, bio_score, volume, center_x, center_y, center_z
            FROM pockets
            WHERE pdb_id = ?
              AND druggable = 1
              AND bio_score >= ?
              AND volume >= ?
            ORDER BY bio_score DESC
            LIMIT ?
            """,
            (
                pdb_id,
                args.min_bio_score,
                canonical.min_druggable_volume,
                canonical.top_n,
            ),
        ).fetchall()

        for row in rows:
            center = [
                float(row["center_x"] or 0.0),
                float(row["center_y"] or 0.0),
                float(row["center_z"] or 0.0),
            ]
            center_source = "db"
            if _is_zero_center(center):
                if pdb_id not in recompute_cache:
                    recompute_cache[pdb_id] = recompute_centers_by_rank(
                        project_root=project_root,
                        pdb_id=pdb_id,
                        profile=args.profile,
                    )
                rank = int(row["rank"] or 0)
                repaired = recompute_cache[pdb_id].get(rank)
                if repaired is not None:
                    center = repaired
                    center_source = "recomputed"
                else:
                    center_source = "invalid"

            known_match = False
            ligand_nearby = False
            fp_match = False
            docking_validated = False
            known_min_distance: float | None = None
            ligand_min_distance: float | None = None
            fpocket_min_distance: float | None = None
            known_available = False
            ligand_available = False
            fpocket_available = False
            docking_available = False
            unknown_reason: str | None = None
            weighted_score = 0.0
            available_sources_count = 0

            if center_source == "invalid":
                classification = "unknown"
                unknown_reason = "center_missing"
            else:
                known_list = known_centers.get(pdb_id, [])
                if known_list:
                    known_available = True
                    known_min_distance = min(_distance(center, kc) for kc in known_list)
                    known_match = known_min_distance <= canonical.tolerance

                fpocket_list = fpocket_centers.get(pdb_id, [])
                if fpocket_list:
                    fpocket_available = True
                    fpocket_min_distance = min(
                        _distance(center, fc) for fc in fpocket_list
                    )
                    fp_match = fpocket_min_distance <= canonical.tolerance

                ligand_atoms = get_ligands(pdb_id)
                if ligand_atoms:
                    ligand_available = True
                    ligand_min_distance = min(
                        _distance(center, atom) for atom in ligand_atoms
                    )
                    ligand_nearby = ligand_min_distance <= args.ligand_radius

                if has_docking_table:
                    dock_row = conn.execute(
                        """
                        SELECT validated
                        FROM docking_results
                        WHERE pdb_id = ? AND pocket_id = ?
                        LIMIT 1
                        """,
                        (pdb_id, int(row["pocket_id"])),
                    ).fetchone()
                    if dock_row is not None:
                        docking_available = True
                        try:
                            docking_validated = int(dock_row["validated"] or 0) == 1
                        except (TypeError, ValueError):
                            docking_validated = False

                evidence_flags = {
                    "known_match": known_match,
                    "ligand_nearby": ligand_nearby,
                    "fpocket_match": fp_match,
                    "docking_validated": docking_validated,
                }
                weighted_score = compute_weighted_score(evidence_flags)

                for key, flag in evidence_flags.items():
                    if flag:
                        evidence_counts[key] += 1

                available_sources_count = sum(
                    [
                        1 if known_available else 0,
                        1 if ligand_available else 0,
                        1 if fpocket_available else 0,
                        1 if docking_available else 0,
                    ]
                )

                if weighted_score >= args.support_threshold:
                    classification = "supported"
                elif available_sources_count == 0:
                    classification = "unknown"
                    unknown_reason = "no_evidence_sources"
                elif available_sources_count < args.min_evidence_sources:
                    classification = "unknown"
                    unknown_reason = "low_evidence_coverage"
                else:
                    classification = "unsupported"

            records.append(
                {
                    "pdb_id": pdb_id,
                    "pocket_id": int(row["pocket_id"]),
                    "rank": int(row["rank"] or 0),
                    "bio_score": float(row["bio_score"] or 0.0),
                    "volume": float(row["volume"] or 0.0),
                    "center": center,
                    "center_source": center_source,
                    "evidence": {
                        "known_match": known_match,
                        "ligand_nearby": ligand_nearby,
                        "fpocket_match": fp_match,
                        "docking_validated": docking_validated,
                        "known_available": known_available,
                        "ligand_available": ligand_available,
                        "fpocket_available": fpocket_available,
                        "docking_available": docking_available,
                        "known_min_distance": known_min_distance,
                        "ligand_min_distance": ligand_min_distance,
                        "fpocket_min_distance": fpocket_min_distance,
                    },
                    "weighted_evidence_score": weighted_score,
                    "available_sources_count": available_sources_count,
                    "classification": classification,
                    "unknown_reason": unknown_reason,
                }
            )

    conn.close()

    supported = sum(r["classification"] == "supported" for r in records)
    unsupported = sum(r["classification"] == "unsupported" for r in records)
    unknown = sum(r["classification"] == "unknown" for r in records)
    total = len(records)

    conservative_denom = supported + unsupported
    fpr_conservative = (
        float(unsupported / conservative_denom) if conservative_denom > 0 else None
    )
    fpr_strict = float((unsupported + unknown) / total) if total > 0 else None
    unknown_rate = float(unknown / total) if total > 0 else None

    conservative_labels = [1] * unsupported + [0] * supported
    strict_labels = [1] * (unsupported + unknown) + [0] * supported
    conservative_ci95 = bootstrap_ci(
        conservative_labels, n_iter=args.bootstrap_iter, seed=args.seed + 17
    )
    strict_ci95 = bootstrap_ci(
        strict_labels, n_iter=args.bootstrap_iter, seed=args.seed + 29
    )

    gate_status = (
        "PASS"
        if fpr_conservative is not None and fpr_conservative <= canonical.max_fpr
        else "FAIL"
    )

    recall_context = load_validation_recall(project_root)

    payload = {
        "generated_at_utc": _utc_now(),
        "config": {
            "sample_size_requested": args.sample_size,
            "sample_size": sample_size,
            "seed": args.seed,
            "min_bio_score": args.min_bio_score,
            "ligand_radius": args.ligand_radius,
            "profile": args.profile,
            "bootstrap_iter": args.bootstrap_iter,
            "canonical_tolerance": canonical.tolerance,
            "canonical_top_n": canonical.top_n,
            "canonical_druggable_filter": canonical.druggable_filter,
            "max_fpr": canonical.max_fpr,
            "support_threshold": args.support_threshold,
            "min_evidence_sources": args.min_evidence_sources,
            "manual_review_top_n": args.manual_review_top_n,
        },
        "summary": {
            "sample_size": sample_size,
            "candidate_pockets": total,
            "supported_count": supported,
            "unsupported_count": unsupported,
            "unknown_count": unknown,
            "fpr": {
                "conservative": fpr_conservative,
                "conservative_ci95": list(conservative_ci95),
                "strict": fpr_strict,
                "strict_ci95": list(strict_ci95),
                "unknown_rate": unknown_rate,
            },
            "gate_status": gate_status,
            "weighted_scoring": EVIDENCE_WEIGHTS,
            "unknown_reason_counts": unknown_reason_counts(records),
            "evidence_counts": evidence_counts,
            "sampled_proteins": sampled_proteins,
            "pre_registration_phase": cfg.get("pre_registration", {}).get("phase"),
            "pre_registration_status": cfg.get("pre_registration", {}).get("status"),
        },
        "records": records,
        "recall_context": recall_context,
    }

    if args.dry_run:
        print("[DRY-RUN] False-positive analysis plan")
        print(f"[DRY-RUN] proteins={sample_size} candidates={total}")
        print(f"[DRY-RUN] gate={gate_status}")
        return 0

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown_report(output_md, payload)
    write_manual_review_report(output_manual_review, payload)
    write_protocol(
        output_protocol,
        support_threshold=args.support_threshold,
        min_evidence_sources=args.min_evidence_sources,
        ligand_radius=args.ligand_radius,
    )
    write_metrics_definition(
        output_metrics,
        max_fpr=canonical.max_fpr,
        support_threshold=args.support_threshold,
        min_evidence_sources=args.min_evidence_sources,
    )
    write_statistical_appendix(output_stat, payload)

    print(f"[OK] JSON: {output_json}")
    print(f"[OK] Markdown: {output_md}")
    print(f"[OK] Manual review: {output_manual_review}")
    print(f"[OK] Protocol: {output_protocol}")
    print(f"[OK] Metrics: {output_metrics}")
    print(f"[OK] Statistical appendix: {output_stat}")
    print(f"[INFO] Conservative FPR: {fpr_conservative}")
    print(f"[INFO] Gate status: {gate_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
