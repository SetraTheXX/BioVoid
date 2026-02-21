#!/usr/bin/env python3
"""
Phase 5.5 gate decision generator.

Reads generated artifacts and produces:
- docs/phase5_5_gate_decision.md
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GATE_PROFILES: dict[str, dict[str, Any]] = {
    "strict": {
        "min_recall": 0.30,
        "min_fpocket_overlap": 0.25,
        "max_false_positive_rate": 0.60,
        "min_md_validated_proteins": 1,
        "overlap_metric_source": "global.official_overlap_center_volume_greedy",
    },
    "recovery_v2_transition": {
        "min_recall": 0.10,
        "min_fpocket_overlap": 0.24,
        "max_false_positive_rate": 0.60,
        "min_md_validated_proteins": 1,
        "overlap_metric_source": "cp_b_candidate_impact.full_option1_overlap",
    },
}


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Phase 5.5 gate decision markdown.")
    parser.add_argument("--pre-reg", default="data/validation/pre_registered_config.json")
    parser.add_argument("--validation-json", default="data/validation/validation_results.json")
    parser.add_argument("--fpocket-report", default="docs/fpocket_benchmark_report.md")
    parser.add_argument(
        "--benchmark-json",
        default="data/benchmark/fpocket_benchmark_v3.json",
        help="Benchmark JSON for overlap SoT extraction by gate profile.",
    )
    parser.add_argument("--md-json", default="data/validation/md_validation_1g66.json")
    parser.add_argument("--fpr-json", default="data/validation/false_positive_results.json")
    parser.add_argument(
        "--feasibility-benchmark-json",
        default="data/benchmark/fpocket_benchmark_v3.json",
        help="Benchmark JSON used by feasibility pre-check.",
    )
    parser.add_argument(
        "--skip-feasibility-check",
        action="store_true",
        help="Skip overlap feasibility kill-switch pre-check.",
    )
    parser.add_argument(
        "--gate-profile",
        default="strict",
        help="Gate profile to apply (configured under gate_profiles in pre-reg).",
    )
    parser.add_argument("--output", default="docs/phase5_5_gate_decision.md")
    parser.add_argument("--dry-run", action="store_true")
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


def _load_fpocket_overlap(path: Path) -> float | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    patterns = [
        r"Global overlap score:\s*\*\*([0-9.]+)\*\*",
        r"global overlap score:\s*([0-9.]+)",
        r"Official overlap \(center\+volume, ratio 0\.50-2\.00\):\s*\*\*([0-9.]+)\*\*",
        r"Official overlap .*?:\s*\*\*([0-9.]+)\*\*",
    ]
    for pattern in patterns:
        overlap = _extract_float(pattern, text)
        if overlap is not None:
            return overlap
    return None


def _format_float(x: float | None, ndigits: int = 4) -> str:
    if x is None:
        return "n/a"
    return f"{x:.{ndigits}f}"


def _resolve_gate_config(pre_reg: dict[str, Any], gate_profile: str) -> dict[str, Any]:
    profiles = pre_reg.get("gate_profiles", {})
    if isinstance(profiles, dict) and profiles:
        selected = profiles.get(gate_profile)
        if selected is None:
            available = ", ".join(sorted(str(key) for key in profiles.keys()))
            raise KeyError(
                f"Unknown gate profile '{gate_profile}'. Available profiles: {available}"
            )
        if not isinstance(selected, dict):
            raise TypeError(f"Gate profile '{gate_profile}' must be an object.")
        return selected

    if gate_profile in DEFAULT_GATE_PROFILES:
        if gate_profile == "strict":
            merged = dict(DEFAULT_GATE_PROFILES["strict"])
            merged.update(pre_reg.get("decision_gates", {}))
            return merged
        return dict(DEFAULT_GATE_PROFILES[gate_profile])

    if gate_profile == "strict":
        return pre_reg.get("decision_gates", {})

    available = ", ".join(sorted(DEFAULT_GATE_PROFILES.keys()))
    raise KeyError(
        f"Unknown gate profile '{gate_profile}'. No gate_profiles in pre-reg. "
        f"Built-in profiles: {available}"
    )


def _extract_nested_float(payload: dict[str, Any], dotted_path: str) -> float | None:
    node: Any = payload
    for key in dotted_path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
        if node is None:
            return None
    try:
        return float(node)
    except (TypeError, ValueError):
        return None


def _load_overlap_from_benchmark_json(path: Path, metric_source: str) -> float | None:
    payload = _safe_load_json(path)
    if payload is None:
        return None
    return _extract_nested_float(payload, metric_source)


def main() -> int:
    args = parse_args()
    if not args.skip_feasibility_check:
        feasibility_cmd = [
            sys.executable,
            str(ROOT / "scripts" / "check_gate_feasibility.py"),
            "--pre-reg",
            args.pre_reg,
            "--benchmark-json",
            args.feasibility_benchmark_json,
            "--gate-profile",
            args.gate_profile,
        ]
        feasibility_proc = subprocess.run(feasibility_cmd, cwd=str(ROOT))
        if feasibility_proc.returncode != 0:
            return feasibility_proc.returncode

    pre_reg = _safe_load_json(ROOT / args.pre_reg)
    if pre_reg is None:
        raise FileNotFoundError(f"Pre-registration config missing: {ROOT / args.pre_reg}")

    validation = _safe_load_json(ROOT / args.validation_json) or {}
    md = _safe_load_json(ROOT / args.md_json) or {}
    fpr = _safe_load_json(ROOT / args.fpr_json) or {}
    benchmark_json_path = ROOT / args.benchmark_json

    dg = _resolve_gate_config(pre_reg, args.gate_profile)
    cp = pre_reg.get("canonical_parameters", {})
    min_recall = float(dg.get("min_recall", 0.30))
    min_overlap = float(dg.get("min_fpocket_overlap", 0.25))
    max_fpr = float(dg.get("max_false_positive_rate", 0.60))
    min_md_validated = int(dg.get("min_md_validated_proteins", 1))
    overlap_metric_source = str(
        dg.get("overlap_metric_source", "official_overlap_center_volume_greedy")
    )

    overlap = _load_overlap_from_benchmark_json(benchmark_json_path, overlap_metric_source)
    overlap_source_label = f"benchmark_json:{overlap_metric_source}"
    if overlap is None:
        overlap = _load_fpocket_overlap(ROOT / args.fpocket_report)
        overlap_source_label = "fpocket_report:fallback"

    val_summary = validation.get("summary", {}) if isinstance(validation, dict) else {}
    recall = float(val_summary.get("recall", 0.0) or 0.0) if val_summary else None
    val_cfg = val_summary.get("config", {}) if isinstance(val_summary, dict) else {}
    tol_ok = (
        float(val_cfg.get("tolerance", cp.get("proximity_tolerance_angstrom", 8.0)))
        == float(cp.get("proximity_tolerance_angstrom", 8.0))
    )
    topn_ok = (
        int(val_cfg.get("top_n", cp.get("top_n_pockets_to_consider", 20)))
        == int(cp.get("top_n_pockets_to_consider", 20))
    )

    md_summary = md.get("summary", {}) if isinstance(md, dict) else {}
    md_status = str(md_summary.get("status", "MISSING"))
    md_pass = md_status in {"VALIDATION_SUCCESS", "VALIDATION_PARTIAL"}
    md_validated_count = 1 if md_pass else 0

    fpr_summary = (fpr.get("summary") or {}) if isinstance(fpr, dict) else {}
    fpr_metrics = (fpr_summary.get("fpr") or {}) if isinstance(fpr_summary, dict) else {}
    conservative_fpr = (
        float(fpr_metrics.get("conservative"))
        if fpr_metrics.get("conservative") is not None
        else None
    )

    recall_pass = (
        recall is not None
        and recall >= min_recall
        and tol_ok
        and topn_ok
    )
    overlap_pass = overlap is not None and overlap >= min_overlap
    md_gate_pass = md_validated_count >= min_md_validated
    fpr_pass = conservative_fpr is not None and conservative_fpr <= max_fpr

    all_pass = recall_pass and overlap_pass and md_gate_pass and fpr_pass
    decision = "PASS" if all_pass else "FAIL"

    lines = [
        "# Phase 5.5 Gate Decision",
        "",
        f"- Generated at (UTC): {_utc_now()}",
        f"- Decision: **{decision}**",
        f"- Gate profile: `{args.gate_profile}`",
        f"- Overlap source: `{overlap_source_label}`",
        "",
        "## Pre-registered Gates",
        "",
        f"- min_recall: {min_recall:.2f}",
        f"- min_fpocket_overlap: {min_overlap:.2f}",
        f"- max_false_positive_rate: {max_fpr:.2f}",
        f"- min_md_validated_proteins: {min_md_validated}",
        f"- overlap_metric_source: `{overlap_metric_source}`",
        "",
        "## Gate Results",
        "",
        "| Gate | Observed | Threshold | Status |",
        "| --- | ---: | ---: | --- |",
        f"| Recall | {_format_float(recall)} | >= {min_recall:.2f} | {'PASS' if recall_pass else 'FAIL'} |",
        f"| fpocket overlap | {_format_float(overlap)} | >= {min_overlap:.2f} | {'PASS' if overlap_pass else 'FAIL'} |",
        f"| MD validation proteins | {md_validated_count} | >= {min_md_validated} | {'PASS' if md_gate_pass else 'FAIL'} |",
        f"| Conservative FPR | {_format_float(conservative_fpr)} | <= {max_fpr:.2f} | {'PASS' if fpr_pass else 'FAIL'} |",
        "",
        "## Drift Checks",
        "",
        f"- Validation tolerance aligned with canonical: **{'YES' if tol_ok else 'NO'}**",
        f"- Validation top-N aligned with canonical: **{'YES' if topn_ok else 'NO'}**",
        "",
        "## MD Validation Snapshot",
        "",
        f"- Status: `{md_status}`",
        f"- N samples: {md_summary.get('n_samples', 'n/a')}",
        f"- Max volume: {md_summary.get('max_volume', 'n/a')}",
        f"- Open fraction: {md_summary.get('open_fraction', 'n/a')}",
        "",
        "## Notes",
        "",
        "- Gate decision is strict: all pre-registered gates must pass.",
        "- If decision is FAIL, proceed only with documented conditional policy.",
        "- Center integrity attachment: `docs/center_integrity_report.md` (zero-center cleaned to 0).",
        "",
    ]

    output_path = ROOT / args.output
    if args.dry_run:
        print("[DRY-RUN] Gate decision")
        print(f"[DRY-RUN] decision={decision}")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Wrote {output_path}")
    print(f"[INFO] Decision: {decision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
