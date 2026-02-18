#!/usr/bin/env python3
"""
Recovery v2 regression guard runner (WS-C).

Checks:
- FPR guard
- MD guard
- Drift guard (tolerance/top-N/druggable lock)
- Gate report consistency and freshness

Outputs:
- data/validation/recovery_v2_regression_guard.json
- docs/recovery_v2_regression_guard_report.md
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _format_float(value: float | None, ndigits: int = 4) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{ndigits}f}"


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _safe_read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _extract_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _extract_fpocket_overlap(fpocket_text: str) -> float | None:
    patterns = [
        r"Global overlap score:\s*\*\*([0-9.]+)\*\*",
        r"global overlap score:\s*([0-9.]+)",
        r"Official overlap \(center\+volume, ratio 0\.50-2\.00\):\s*\*\*([0-9.]+)\*\*",
        r"Official overlap .*?:\s*\*\*([0-9.]+)\*\*",
    ]
    for pattern in patterns:
        overlap = _extract_float(pattern, fpocket_text)
        if overlap is not None:
            return overlap
    return None


def _extract_decision(text: str) -> str | None:
    match = re.search(r"-\s*Decision:\s*\*\*(PASS|FAIL)\*\*", text, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).upper()


def _extract_gate_rows(text: str) -> dict[str, dict[str, str]]:
    pattern = re.compile(
        r"\|\s*(Recall|fpocket overlap|MD validation proteins|Conservative FPR)\s*"
        r"\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(PASS|FAIL)\s*\|",
        flags=re.IGNORECASE,
    )
    rows: dict[str, dict[str, str]] = {}
    for match in pattern.finditer(text):
        gate_name = match.group(1).strip().lower()
        rows[gate_name] = {
            "observed": match.group(2).strip(),
            "threshold": match.group(3).strip(),
            "status": match.group(4).strip().upper(),
        }
    return rows


def _parse_float_text(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.strip().replace("%", "")
    if cleaned.lower() in {"n/a", "na", "none", "null"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return default


def _status(pass_condition: bool) -> str:
    return "PASS" if pass_condition else "FAIL"


@dataclass
class GuardCheck:
    status: str
    detail: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Recovery v2 regression guard checks.")
    parser.add_argument("--pre-reg", default="data/validation/pre_registered_config.json")
    parser.add_argument("--validation-json", default="data/validation/validation_results.json")
    parser.add_argument("--fpr-json", default="data/validation/false_positive_results.json")
    parser.add_argument("--md-json", default="data/validation/md_validation_1g66.json")
    parser.add_argument("--fpocket-report", default="docs/fpocket_benchmark_report.md")
    parser.add_argument("--gate-decision", default="docs/phase5_5_gate_decision.md")
    parser.add_argument("--center-report", default="docs/center_integrity_report.md")
    parser.add_argument(
        "--output-json",
        default="data/validation/recovery_v2_regression_guard.json",
    )
    parser.add_argument(
        "--output-md",
        default="docs/recovery_v2_regression_guard_report.md",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    pre_reg_path = ROOT / args.pre_reg
    validation_path = ROOT / args.validation_json
    fpr_path = ROOT / args.fpr_json
    md_path = ROOT / args.md_json
    fpocket_path = ROOT / args.fpocket_report
    gate_path = ROOT / args.gate_decision
    center_report_path = ROOT / args.center_report

    pre_reg = _safe_load_json(pre_reg_path)
    validation = _safe_load_json(validation_path)
    fpr = _safe_load_json(fpr_path)
    md = _safe_load_json(md_path)
    fpocket_text = _safe_read_text(fpocket_path)
    gate_text = _safe_read_text(gate_path)

    if pre_reg is None:
        raise FileNotFoundError(f"Missing pre-registration config: {pre_reg_path}")
    if validation is None:
        raise FileNotFoundError(f"Missing validation results: {validation_path}")
    if fpr is None:
        raise FileNotFoundError(f"Missing false positive results: {fpr_path}")
    if md is None:
        raise FileNotFoundError(f"Missing MD validation results: {md_path}")
    if fpocket_text is None:
        raise FileNotFoundError(f"Missing fpocket report: {fpocket_path}")
    if gate_text is None:
        raise FileNotFoundError(f"Missing gate decision report: {gate_path}")

    decision_gates = pre_reg.get("decision_gates", {})
    canonical = pre_reg.get("canonical_parameters", {})

    min_recall = float(decision_gates.get("min_recall", 0.30))
    min_overlap = float(decision_gates.get("min_fpocket_overlap", 0.40))
    max_fpr = float(decision_gates.get("max_false_positive_rate", 0.60))
    min_md_validated = int(decision_gates.get("min_md_validated_proteins", 1))

    validation_summary = validation.get("summary", {}) if isinstance(validation, dict) else {}
    validation_cfg = (
        validation_summary.get("config", {})
        if isinstance(validation_summary, dict)
        else {}
    )
    recall = float(validation_summary.get("recall", 0.0))

    overlap = _extract_fpocket_overlap(fpocket_text)

    fpr_summary = fpr.get("summary", {}) if isinstance(fpr, dict) else {}
    fpr_metrics = fpr_summary.get("fpr", {}) if isinstance(fpr_summary, dict) else {}
    conservative_fpr = (
        float(fpr_metrics["conservative"])
        if isinstance(fpr_metrics, dict) and fpr_metrics.get("conservative") is not None
        else None
    )

    md_summary = md.get("summary", {}) if isinstance(md, dict) else {}
    md_status = str(md_summary.get("status", "MISSING"))
    md_validated_count = 1 if md_status in {"VALIDATION_SUCCESS", "VALIDATION_PARTIAL"} else 0

    canonical_tolerance = float(canonical.get("proximity_tolerance_angstrom", 8.0))
    canonical_top_n = int(canonical.get("top_n_pockets_to_consider", 20))
    canonical_druggable = _parse_bool(canonical.get("druggable_filter", True), True)

    observed_tolerance = float(validation_cfg.get("tolerance", canonical_tolerance))
    observed_top_n = int(validation_cfg.get("top_n", canonical_top_n))
    observed_druggable = _parse_bool(
        validation_cfg.get("druggable_only", validation_cfg.get("druggable_filter", canonical_druggable)),
        canonical_druggable,
    )

    tolerance_ok = observed_tolerance == canonical_tolerance
    top_n_ok = observed_top_n == canonical_top_n
    druggable_ok = observed_druggable == canonical_druggable

    fpr_guard = GuardCheck(
        status=_status(conservative_fpr is not None and conservative_fpr <= max_fpr),
        detail=f"conservative_fpr={_format_float(conservative_fpr)} threshold<={max_fpr:.2f}",
    )
    md_guard = GuardCheck(
        status=_status(md_validated_count >= min_md_validated),
        detail=f"md_validated_count={md_validated_count} threshold>={min_md_validated} status={md_status}",
    )
    drift_guard = GuardCheck(
        status=_status(tolerance_ok and top_n_ok and druggable_ok),
        detail=(
            f"tolerance={observed_tolerance} top_n={observed_top_n} "
            f"druggable={str(observed_druggable).lower()}"
        ),
    )

    gate_rows = _extract_gate_rows(gate_text)
    gate_decision = _extract_decision(gate_text)

    expected_gate_statuses = {
        "recall": _status(recall >= min_recall and tolerance_ok and top_n_ok and druggable_ok),
        "fpocket overlap": _status(overlap is not None and overlap >= min_overlap),
        "md validation proteins": _status(md_validated_count >= min_md_validated),
        "conservative fpr": _status(conservative_fpr is not None and conservative_fpr <= max_fpr),
    }
    expected_decision = (
        "PASS"
        if all(status == "PASS" for status in expected_gate_statuses.values())
        else "FAIL"
    )

    row_status_consistency = True
    row_metric_consistency = True
    required_gate_rows = [
        "recall",
        "fpocket overlap",
        "md validation proteins",
        "conservative fpr",
    ]
    for row_name in required_gate_rows:
        row = gate_rows.get(row_name)
        if row is None:
            row_status_consistency = False
            row_metric_consistency = False
            continue
        if row.get("status") != expected_gate_statuses[row_name]:
            row_status_consistency = False

    recall_row = gate_rows.get("recall", {})
    overlap_row = gate_rows.get("fpocket overlap", {})
    md_row = gate_rows.get("md validation proteins", {})
    fpr_row = gate_rows.get("conservative fpr", {})

    recall_row_observed = _parse_float_text(recall_row.get("observed"))
    overlap_row_observed = _parse_float_text(overlap_row.get("observed"))
    md_row_observed = _parse_float_text(md_row.get("observed"))
    fpr_row_observed = _parse_float_text(fpr_row.get("observed"))

    tolerance = 5e-4
    if recall_row_observed is None or abs(recall_row_observed - recall) > tolerance:
        row_metric_consistency = False
    if (
        overlap is None
        or overlap_row_observed is None
        or abs(overlap_row_observed - overlap) > tolerance
    ):
        row_metric_consistency = False
    if md_row_observed is None or int(md_row_observed) != md_validated_count:
        row_metric_consistency = False
    if (
        conservative_fpr is None
        or fpr_row_observed is None
        or abs(fpr_row_observed - conservative_fpr) > tolerance
    ):
        row_metric_consistency = False

    gate_decision_consistency = gate_decision == expected_decision
    center_report_linked = "docs/center_integrity_report.md" in gate_text

    freshness_targets = [validation_path, fpr_path, md_path, fpocket_path]
    freshness_sources = [p.stat().st_mtime for p in freshness_targets if p.exists()]
    gate_is_fresh = gate_path.exists() and bool(freshness_sources) and (
        gate_path.stat().st_mtime >= max(freshness_sources)
    )

    report_consistency_guard = GuardCheck(
        status=_status(
            gate_decision_consistency
            and row_status_consistency
            and row_metric_consistency
            and center_report_linked
            and gate_is_fresh
        ),
        detail=(
            f"decision_match={str(gate_decision_consistency).lower()} "
            f"row_status={str(row_status_consistency).lower()} "
            f"row_metrics={str(row_metric_consistency).lower()} "
            f"center_link={str(center_report_linked).lower()} "
            f"fresh={str(gate_is_fresh).lower()}"
        ),
    )

    overall_pass = all(
        check.status == "PASS"
        for check in [fpr_guard, md_guard, drift_guard, report_consistency_guard]
    )

    risks: list[str] = []
    if fpr_guard.status == "FAIL":
        risks.append("FPR guard failed; conservative FPR exceeded threshold.")
    if md_guard.status == "FAIL":
        risks.append("MD guard failed; required MD validated proteins not met.")
    if drift_guard.status == "FAIL":
        risks.append("Drift guard failed; canonical gate parameters are not locked.")
    if report_consistency_guard.status == "FAIL":
        risks.append("Report consistency guard failed; gate report is stale or inconsistent.")
    if not center_report_path.exists():
        risks.append("Center integrity report file is missing.")

    output_payload: dict[str, Any] = {
        "generated_at_utc": _utc_now(),
        "overall_regression_guard_status": _status(overall_pass),
        "inputs": {
            "pre_registered_config": str(pre_reg_path.relative_to(ROOT)),
            "validation_results": str(validation_path.relative_to(ROOT)),
            "false_positive_results": str(fpr_path.relative_to(ROOT)),
            "md_validation_results": str(md_path.relative_to(ROOT)),
            "fpocket_report": str(fpocket_path.relative_to(ROOT)),
            "gate_decision_report": str(gate_path.relative_to(ROOT)),
            "center_integrity_report": str(center_report_path.relative_to(ROOT)),
        },
        "thresholds": {
            "min_recall": min_recall,
            "min_fpocket_overlap": min_overlap,
            "max_false_positive_rate": max_fpr,
            "min_md_validated_proteins": min_md_validated,
            "canonical_tolerance": canonical_tolerance,
            "canonical_top_n": canonical_top_n,
            "canonical_druggable_filter": canonical_druggable,
        },
        "metrics": {
            "recall": recall,
            "fpocket_overlap": overlap,
            "conservative_fpr": conservative_fpr,
            "md_validated_count": md_validated_count,
            "md_status": md_status,
            "observed_tolerance": observed_tolerance,
            "observed_top_n": observed_top_n,
            "observed_druggable_filter": observed_druggable,
        },
        "guards": {
            "fpr_guard": {"status": fpr_guard.status, "detail": fpr_guard.detail},
            "md_guard": {"status": md_guard.status, "detail": md_guard.detail},
            "drift_guard": {"status": drift_guard.status, "detail": drift_guard.detail},
            "report_consistency_guard": {
                "status": report_consistency_guard.status,
                "detail": report_consistency_guard.detail,
            },
        },
        "gate_snapshot": {
            "reported_decision": gate_decision,
            "expected_decision": expected_decision,
            "expected_gate_statuses": expected_gate_statuses,
            "reported_rows": gate_rows,
        },
        "consistency_checks": {
            "gate_decision_consistency": gate_decision_consistency,
            "gate_row_status_consistency": row_status_consistency,
            "gate_row_metric_consistency": row_metric_consistency,
            "center_report_linked_in_gate_decision": center_report_linked,
            "gate_report_freshness": gate_is_fresh,
            "center_report_file_exists": center_report_path.exists(),
        },
        "risks": risks,
    }

    output_json_path = ROOT / args.output_json
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(
        json.dumps(output_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    md_lines = [
        "# Recovery v2 Regression Guard Report",
        "",
        f"- Generated at (UTC): {output_payload['generated_at_utc']}",
        f"- Overall WS-C guard status: **{output_payload['overall_regression_guard_status']}**",
        "",
        "## Guard Summary",
        "",
        "| Guard | Status | Detail |",
        "| --- | --- | --- |",
        f"| FPR guard | {fpr_guard.status} | {fpr_guard.detail} |",
        f"| MD guard | {md_guard.status} | {md_guard.detail} |",
        f"| Drift guard | {drift_guard.status} | {drift_guard.detail} |",
        f"| Report consistency guard | {report_consistency_guard.status} | {report_consistency_guard.detail} |",
        "",
        "## Gate Snapshot",
        "",
        f"- Reported decision: **{gate_decision or 'n/a'}**",
        f"- Expected decision from artifacts: **{expected_decision}**",
        f"- Recall: {_format_float(recall)} (threshold >= {min_recall:.2f})",
        f"- fpocket overlap: {_format_float(overlap)} (threshold >= {min_overlap:.2f})",
        f"- Conservative FPR: {_format_float(conservative_fpr)} (threshold <= {max_fpr:.2f})",
        f"- MD validated proteins: {md_validated_count} (threshold >= {min_md_validated})",
        "",
        "## Consistency Checks",
        "",
        f"- Gate decision consistency: **{_status(gate_decision_consistency)}**",
        f"- Gate row status consistency: **{_status(row_status_consistency)}**",
        f"- Gate row metric consistency: **{_status(row_metric_consistency)}**",
        f"- Gate report freshness: **{_status(gate_is_fresh)}**",
        (
            "- Center integrity attachment linked in gate decision: "
            f"**{_status(center_report_linked)}**"
        ),
        f"- Center integrity file exists: **{_status(center_report_path.exists())}**",
        "",
        "## Open Risks",
        "",
    ]

    if risks:
        md_lines.extend([f"- {risk}" for risk in risks])
    else:
        md_lines.append("- No WS-C regression risk detected in this checkpoint.")

    output_md_path = ROOT / args.output_md
    output_md_path.parent.mkdir(parents=True, exist_ok=True)
    output_md_path.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"[OK] Wrote {output_json_path}")
    print(f"[OK] Wrote {output_md_path}")
    print(f"[INFO] Overall WS-C guard status: {output_payload['overall_regression_guard_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
