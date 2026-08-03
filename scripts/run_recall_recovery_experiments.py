#!/usr/bin/env python3
"""
Faz 5.5 P1.1: Recall Recovery Controlled Experiments
====================================================

20 known cryptic pocket setinde baseline (single-frame) ve
multi-frame consensus yaklasimlarini karsilastirir.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from validate_known_pockets import (
    ValidationResult,
    ValidationSummary,
    calculate_summary,
    load_test_set,
    validate_single_case,
)


CHECKPOINT_SCHEMA_VERSION = 1


def _result_from_payload(payload: dict[str, Any]) -> ValidationResult | None:
    try:
        return ValidationResult(**payload)
    except TypeError:
        return None


def _default_checkpoint_path(output_json_path: Path) -> Path:
    return output_json_path.parent / f"{output_json_path.stem}.checkpoint.json"


def _load_checkpoint(
    checkpoint_path: Path,
    expected_config: dict[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    if not checkpoint_path.exists():
        return {}
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        print("Checkpoint schema uyumsuz, sifirdan baslanacak.")
        return {}

    if payload.get("config") != expected_config:
        print("Checkpoint config uyumsuz, sifirdan baslanacak.")
        return {}

    results = payload.get("results")
    if not isinstance(results, dict):
        return {}
    return results


def _save_checkpoint(
    checkpoint_path: Path,
    *,
    config: dict[str, Any],
    results: dict[str, dict[str, dict[str, Any]]],
    completed: bool,
) -> None:
    payload = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "completed": completed,
        "config": config,
        "results": results,
    }
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(
        json.dumps(_to_serializable(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _by_type(results: list[ValidationResult]) -> dict[str, dict[str, float]]:
    stats: dict[str, dict[str, float]] = {}
    for result in results:
        if result.error:
            continue
        ptype = result.pocket_type
        row = stats.setdefault(ptype, {"total": 0.0, "hits": 0.0})
        row["total"] += 1.0
        if result.matched:
            row["hits"] += 1.0

    for row in stats.values():
        total = row["total"]
        row["rate"] = (row["hits"] / total) if total > 0 else 0.0
    return stats


def _status_mark(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _to_serializable(obj: Any) -> Any:
    """Convert numpy-like objects to JSON-safe payloads."""
    if hasattr(obj, "tolist"):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_serializable(v) for v in obj]
    if isinstance(obj, tuple):
        return [_to_serializable(v) for v in obj]
    return obj


def _generate_markdown(
    output_path: Path,
    *,
    single_summary: ValidationSummary,
    multi_summary: ValidationSummary,
    single_type: dict[str, dict[str, float]],
    multi_type: dict[str, dict[str, float]],
    tolerance: float,
    top_n: int,
    consensus_min_frames: int,
    analysis_atom_mode: str,
) -> None:
    all_types = sorted(set(single_type.keys()) | set(multi_type.keys()))
    lines = [
        "# Faz 5.5 P1.1 - Recall Recovery Experiments",
        "",
        f"> **Uretim Tarihi:** {datetime.now().isoformat(timespec='seconds')}",
        "> **Controlled Set:** 20 known cryptic pocket",
        f"> **Tolerance:** {tolerance:.1f}A (sabit)",
        f"> **Top-N:** {top_n} (sabit)",
        f"> **Consensus Min Support:** {consensus_min_frames} frame",
        f"> **Analysis Atom Mode:** {analysis_atom_mode}",
        "",
        "---",
        "",
        "## 1) Genel Karsilastirma",
        "",
        "| Metrik | Baseline (Single) | Multi-frame Consensus | Delta |",
        "|---|---:|---:|---:|",
        (
            f"| Recall | {single_summary.recall*100:.1f}% "
            f"({single_summary.true_positives}/{single_summary.true_positives + single_summary.false_negatives}) | "
            f"{multi_summary.recall*100:.1f}% "
            f"({multi_summary.true_positives}/{multi_summary.true_positives + multi_summary.false_negatives}) | "
            f"{(multi_summary.recall-single_summary.recall)*100:+.1f} puan |"
        ),
        (
            f"| Avg Best Distance | {single_summary.avg_best_distance:.1f}A | "
            f"{multi_summary.avg_best_distance:.1f}A | "
            f"{(multi_summary.avg_best_distance-single_summary.avg_best_distance):+.1f}A |"
        ),
        (
            f"| Avg Frames Analyzed | {single_summary.avg_frames_analyzed:.1f} | "
            f"{multi_summary.avg_frames_analyzed:.1f} | "
            f"{(multi_summary.avg_frames_analyzed-single_summary.avg_frames_analyzed):+.1f} |"
        ),
        (
            f"| Avg Consensus Support | {single_summary.avg_consensus_support:.2f} | "
            f"{multi_summary.avg_consensus_support:.2f} | "
            f"{(multi_summary.avg_consensus_support-single_summary.avg_consensus_support):+.2f} |"
        ),
        "",
        "---",
        "",
        "## 2) Pocket Type Bazli Kazanim",
        "",
        "| Pocket Type | Single Hits/Total | Single Rate | Multi Hits/Total | Multi Rate | Delta |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    for pocket_type in all_types:
        s = single_type.get(pocket_type, {"hits": 0.0, "total": 0.0, "rate": 0.0})
        m = multi_type.get(pocket_type, {"hits": 0.0, "total": 0.0, "rate": 0.0})
        lines.append(
            (
                f"| {pocket_type} | "
                f"{int(s['hits'])}/{int(s['total'])} | {s['rate']*100:.1f}% | "
                f"{int(m['hits'])}/{int(m['total'])} | {m['rate']*100:.1f}% | "
                f"{(m['rate']-s['rate'])*100:+.1f} puan |"
            )
        )

    domain_single = single_type.get("domain_motion", {"rate": 0.0})["rate"]
    domain_multi = multi_type.get("domain_motion", {"rate": 0.0})["rate"]
    recall_gain = (multi_summary.recall - single_summary.recall) * 100
    domain_gain = (domain_multi - domain_single) * 100

    recall_ok = multi_summary.recall >= 0.20
    gain_ok = recall_gain >= 10.0
    domain_ok = domain_gain >= 25.0

    lines.extend(
        [
            "",
            "---",
            "",
            "## 3) P1.1 Kabul Kriterleri",
            "",
            "| Kriter | Hedef | Sonuc | Durum |",
            "|---|---:|---:|---|",
            (
                f"| Recall artisi | >= +10 puan | {recall_gain:+.1f} puan | "
                f"{_status_mark(gain_ok)} |"
            ),
            (
                f"| Recall seviyesi | >= 20% | {multi_summary.recall*100:.1f}% | "
                f"{_status_mark(recall_ok)} |"
            ),
            (
                f"| Domain motion recall artisi | >= +25 puan | {domain_gain:+.1f} puan | "
                f"{_status_mark(domain_ok)} |"
            ),
            "",
            "---",
            "",
            "## 4) Teknik Notlar",
            "",
            "- Multi-frame konsensus sadece en az 3 frame'de gorulen pocket'lari tuttu.",
            (
                f"- Multi mode ortalama center stability: "
                f"{multi_summary.avg_center_stability:.2f}A"
            ),
            f"- Multi mode ortalama volume CV: {multi_summary.avg_volume_cv:.3f}",
            "- Tolerance/Top-N pre-registered sabit parametrelerle korunmustur.",
            "",
            "---",
            "",
            "## 5) Sonuc",
            "",
            (
                f"- Baseline recall: **{single_summary.recall*100:.1f}%** -> "
                f"Multi-frame recall: **{multi_summary.recall*100:.1f}%** "
                f"({recall_gain:+.1f} puan)."
            ),
            (
                f"- Domain-motion recall: **{domain_single*100:.1f}%** -> "
                f"**{domain_multi*100:.1f}%** ({domain_gain:+.1f} puan)."
            ),
            "",
        ]
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Phase 5.5 P1.1 controlled recall recovery experiments"
    )
    parser.add_argument(
        "--test-set",
        type=str,
        default="data/validation/known_cryptic_pockets.json",
    )
    parser.add_argument("--tolerance", type=float, default=8.0)
    parser.add_argument("--n-frames", type=int, default=20)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument(
        "--analysis-atom-mode",
        type=str,
        default="frame_ca",
        choices=["frame_ca", "reconstructed_heavy"],
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--consensus-min-frames", type=int, default=3)
    parser.add_argument("--consensus-distance", type=float, default=4.0)
    parser.add_argument("--per-frame-top-n", type=int, default=20)
    parser.add_argument("--center-stability-max", type=float, default=2.0)
    parser.add_argument("--volume-cv-max", type=float, default=0.20)
    parser.add_argument(
        "--frame-selection-mode",
        type=str,
        default="all",
        choices=["all", "uniform", "domain_motion_weighted"],
    )
    parser.add_argument(
        "--frame-selection-fraction",
        type=float,
        default=1.0,
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default="data/validation/recall_recovery_experiments.json",
    )
    parser.add_argument(
        "--output-md",
        type=str,
        default="docs/recall_recovery_experiments.md",
    )
    parser.add_argument(
        "--checkpoint-file",
        type=str,
        default=None,
        help=(
            "Checkpoint JSON path. Varsayilan: "
            "<output-json>.checkpoint.json"
        ),
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Checkpoint'i kullanma, sifirdan calis.",
    )
    args = parser.parse_args()

    test_set_path = ROOT / args.test_set
    test_cases, _ = load_test_set(test_set_path)
    if args.limit:
        test_cases = test_cases[: args.limit]

    output_json = ROOT / args.output_json
    output_md = ROOT / args.output_md
    checkpoint_path = (
        (ROOT / args.checkpoint_file)
        if args.checkpoint_file
        else _default_checkpoint_path(output_json)
    )
    run_config = {
        "test_set": str(test_set_path),
        "tolerance": args.tolerance,
        "n_frames": args.n_frames,
        "top_n": args.top_n,
        "analysis_atom_mode": args.analysis_atom_mode,
        "consensus_min_frames": args.consensus_min_frames,
        "consensus_distance": args.consensus_distance,
        "per_frame_top_n": args.per_frame_top_n,
        "center_stability_max": args.center_stability_max,
        "volume_cv_max": args.volume_cv_max,
        "frame_selection_mode": args.frame_selection_mode,
        "frame_selection_fraction": args.frame_selection_fraction,
    }
    if args.no_resume and checkpoint_path.exists():
        checkpoint_path.unlink()

    print("=" * 70)
    print("PHASE 5.5 P1.1 - CONTROLLED RECALL EXPERIMENTS")
    print("=" * 70)
    print(f"Test cases: {len(test_cases)}")
    print(f"Tolerance: {args.tolerance}A | Top-N: {args.top_n}")
    print(f"Analysis atom mode: {args.analysis_atom_mode}")
    print(
        "Consensus config: "
        f"min_frames={args.consensus_min_frames}, "
        f"distance={args.consensus_distance}A, "
        f"per_frame_top_n={args.per_frame_top_n}"
    )
    print(
        "Frame selection: "
        f"{args.frame_selection_mode} "
        f"(fraction={args.frame_selection_fraction:.2f})"
    )
    print(f"Checkpoint: {checkpoint_path}")

    checkpoint_results = (
        {}
        if args.no_resume
        else _load_checkpoint(checkpoint_path, expected_config=run_config)
    )
    if checkpoint_results:
        print(
            "Checkpoint yuklendi: "
            f"{sum(1 for v in checkpoint_results.values() if 'single' in v and 'multi' in v)} "
            "protein tamam."
        )

    per_case_results: dict[str, dict[str, ValidationResult]] = {}
    for i, test_case in enumerate(test_cases, start=1):
        pdb_id = str(test_case["pdb_id"]).upper()
        case_checkpoint = checkpoint_results.setdefault(pdb_id, {})
        case_results: dict[str, ValidationResult] = {}

        print()
        print("=" * 70)
        print(f"[{i}/{len(test_cases)}] {pdb_id}")
        print("=" * 70)

        for mode in ("single", "multi"):
            cached_payload = case_checkpoint.get(mode)
            cached = (
                _result_from_payload(cached_payload)
                if isinstance(cached_payload, dict)
                else None
            )
            if cached is not None:
                case_results[mode] = cached
                print(f"  {mode}: checkpoint hit, skip.")
                continue

            print(f"  {mode}: running...")
            result = validate_single_case(
                test_case=test_case,
                tolerance=args.tolerance,
                n_frames=args.n_frames,
                top_n=args.top_n,
                druggable_only=True,
                aggregation_mode=mode,
                analysis_atom_mode=args.analysis_atom_mode,
                consensus_min_frames=args.consensus_min_frames,
                consensus_distance=args.consensus_distance,
                per_frame_top_n=args.per_frame_top_n,
                center_stability_max=args.center_stability_max,
                volume_cv_max=args.volume_cv_max,
                reuse_existing_frames=True,
                frame_selection_mode=args.frame_selection_mode,
                frame_selection_fraction=args.frame_selection_fraction,
            )
            case_results[mode] = result
            case_checkpoint[mode] = asdict(result)
            _save_checkpoint(
                checkpoint_path,
                config=run_config,
                results=checkpoint_results,
                completed=False,
            )

        per_case_results[pdb_id] = case_results

    single_results = [
        per_case_results[str(test_case["pdb_id"]).upper()]["single"]
        for test_case in test_cases
    ]
    multi_results = [
        per_case_results[str(test_case["pdb_id"]).upper()]["multi"]
        for test_case in test_cases
    ]

    single_summary = calculate_summary(
        single_results,
        {
            "tolerance": args.tolerance,
            "n_frames": args.n_frames,
            "top_n": args.top_n,
            "druggable_only": True,
            "aggregation_mode": "single",
            "analysis_atom_mode": args.analysis_atom_mode,
            "consensus_min_frames": args.consensus_min_frames,
            "consensus_distance": args.consensus_distance,
            "per_frame_top_n": args.per_frame_top_n,
            "center_stability_max": args.center_stability_max,
            "volume_cv_max": args.volume_cv_max,
            "frame_selection_mode": args.frame_selection_mode,
            "frame_selection_fraction": args.frame_selection_fraction,
        },
    )
    multi_summary = calculate_summary(
        multi_results,
        {
            "tolerance": args.tolerance,
            "n_frames": args.n_frames,
            "top_n": args.top_n,
            "druggable_only": True,
            "aggregation_mode": "multi",
            "analysis_atom_mode": args.analysis_atom_mode,
            "consensus_min_frames": args.consensus_min_frames,
            "consensus_distance": args.consensus_distance,
            "per_frame_top_n": args.per_frame_top_n,
            "center_stability_max": args.center_stability_max,
            "volume_cv_max": args.volume_cv_max,
            "frame_selection_mode": args.frame_selection_mode,
            "frame_selection_fraction": args.frame_selection_fraction,
        },
    )

    single_type = _by_type(single_results)
    multi_type = _by_type(multi_results)

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(
            _to_serializable(
                {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "single_summary": asdict(single_summary),
                "multi_summary": asdict(multi_summary),
                "single_results": [asdict(r) for r in single_results],
                "multi_results": [asdict(r) for r in multi_results],
                "single_by_type": single_type,
                "multi_by_type": multi_type,
                }
            ),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nJSON saved: {output_json}")

    _generate_markdown(
        output_md,
        single_summary=single_summary,
        multi_summary=multi_summary,
        single_type=single_type,
        multi_type=multi_type,
        tolerance=args.tolerance,
        top_n=args.top_n,
        consensus_min_frames=args.consensus_min_frames,
        analysis_atom_mode=args.analysis_atom_mode,
    )
    print(f"Markdown saved: {output_md}")

    checkpoint_serialized_results: dict[str, dict[str, dict[str, Any]]] = {
        pdb_id: {mode: asdict(res) for mode, res in mode_map.items()}
        for pdb_id, mode_map in per_case_results.items()
    }
    _save_checkpoint(
        checkpoint_path,
        config=run_config,
        results=checkpoint_serialized_results,
        completed=True,
    )

    recall_gain = (multi_summary.recall - single_summary.recall) * 100
    domain_gain = (
        (
            multi_type.get("domain_motion", {"rate": 0.0})["rate"]
            - single_type.get("domain_motion", {"rate": 0.0})["rate"]
        )
        * 100
    )
    ok = (
        multi_summary.recall >= 0.20
        and recall_gain >= 10.0
        and domain_gain >= 25.0
    )

    print("\n" + "=" * 70)
    print("P1.1 ACCEPTANCE CHECK")
    print("=" * 70)
    print(f"Recall (multi): {multi_summary.recall*100:.1f}%")
    print(f"Recall gain: {recall_gain:+.1f} puan")
    print(f"Domain-motion gain: {domain_gain:+.1f} puan")
    print(f"Decision: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
