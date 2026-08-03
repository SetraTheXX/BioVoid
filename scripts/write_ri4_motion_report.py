"""Write a public, claim-safe RI-4 development summary from ignored runtime data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = REPO_ROOT / "data/runtime/ri4/ri4-development-motion-run-v1.json"
DEFAULT_OUTPUT = REPO_ROOT / "local-private/research/ri-4-motion-development-report-v1.md"


class ReportError(RuntimeError):
    """Raised when a public RI-4 report cannot be generated safely."""


def _read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"Cannot read RI-4 runtime report: {path}") from exc
    if not isinstance(payload, dict):
        raise ReportError("RI-4 runtime report must be a JSON object")
    return payload


def _value(payload: dict[str, Any], *keys: object) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key, current.get(str(key)))
    return current


def _fmt(value: Any) -> str:
    if value is None:
        return "not available"
    if isinstance(value, float):
        return f"{value:.8f}".rstrip("0").rstrip(".")
    return str(value)


def build_report(payload: dict[str, Any]) -> str:
    if payload.get("schema_version") != "biovoid-ri4-motion-development-v1":
        raise ReportError("Unexpected RI-4 runtime report schema")
    if payload.get("status") != "complete":
        raise ReportError("Only a complete RI-4 run may produce the public report")
    execution = payload.get("execution", {})
    if execution.get("canonical_ranking_affected") is not False:
        raise ReportError("RI-4 report cannot be published with canonical ranking changes")
    results = payload.get("results", {})
    decision = results.get("integration_decision", {})
    static = results.get("static", {})
    motion = results.get("motion", {})
    null_control = payload.get("null_control", {})
    quality = payload.get("quality_counts", {})
    cohort = payload.get("cohort", {})
    lines = [
        "# RI-4 Motion Development Report v1",
        "",
        "Status: **completed development comparison; experimental motion layer**",
        "",
        "This report describes a fixed, ligand-blind development run. It is not a",
        "sealed benchmark result, a discovery claim, a prediction guarantee, or",
        "evidence of clinical or drug-discovery utility. The canonical static",
        "ranking was not changed.",
        "",
        "## Scope",
        "",
        f"- Cases: `{_fmt(cohort.get('case_count'))}`",
        f"- Prepared structures: `{_fmt(cohort.get('structure_count'))}`",
        f"- Resource profile: `{_fmt(execution.get('resource_profile'))}`",
        f"- Heavy workers: `{_fmt(execution.get('workers'))}`",
        f"- Motion configuration: `{_fmt(payload.get('motion_config'))}`",
        f"- Runtime report hash: `{_fmt(payload.get('run_sha256'))}`",
        "",
        "## Frame Quality",
        "",
        "Only strictly `ACCEPTED` full-atom frames supplied detector evidence.",
        "Warned and rejected frames remained in the accounting and were not",
        "silently promoted.",
        "",
        "| Status | Frames |",
        "| --- | ---: |",
        f"| `ACCEPTED` | {_fmt(quality.get('ACCEPTED', 0))} |",
        f"| `ACCEPTED_WITH_WARNINGS` | {_fmt(quality.get('ACCEPTED_WITH_WARNINGS', 0))} |",
        f"| `REJECTED` | {_fmt(quality.get('REJECTED', 0))} |",
        "",
        "## Development Metrics",
        "",
        "The frozen primary endpoint is Top-3 DCC localization recall. These",
        "values are development evidence on the fixed cohort and are not sealed",
        "or externally replicated results.",
        "",
        "| Arm | DCC Top-3 | DCA Top-3 | Failure rate | False pockets / completed protein |",
        "| --- | ---: | ---: | ---: | ---: |",
        "| BioVoid static | "
        f"{_fmt(_value(static, 'top_k_dcc_recall', 3))} | "
        f"{_fmt(_value(static, 'top_k_dca_recall', 3))} | "
        f"{_fmt(static.get('failure_rate'))} | "
        f"{_fmt(static.get('false_pockets_per_completed_protein'))} |",
        "| BioVoid motion | "
        f"{_fmt(_value(motion, 'top_k_dcc_recall', 3))} | "
        f"{_fmt(_value(motion, 'top_k_dca_recall', 3))} | "
        f"{_fmt(motion.get('failure_rate'))} | "
        f"{_fmt(motion.get('false_pockets_per_completed_protein'))} |",
        "",
        "## Controls And Decision",
        "",
        f"- Zero-displacement null control: **{_fmt(null_control.get('status')).upper()}**",
        f"- Development integration decision: **{_fmt(decision.get('decision'))}**",
        f"- Top-3 DCC change: `{_fmt(decision.get('primary_improvement'))}`",
        f"- Decision reasons: `{_fmt(decision.get('reasons'))}`",
        "",
        "A `NOT_ELIGIBLE` decision is a valid scientific outcome: it means the",
        "motion layer did not satisfy the predeclared development gate. An",
        "`ELIGIBLE` development decision still does not promote motion output",
        "into the canonical product result; sealed evaluation and independent",
        "review remain separate gates.",
        "",
        "## Reproducibility Boundary",
        "",
        "The run used the exact preflight cohort, one short-lived worker per",
        "structure, a per-structure timeout, and checkpointed local runtime",
        "storage. Generated frame files are not part of the repository.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run_path = args.run if args.run.is_absolute() else REPO_ROOT / args.run
    output_path = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    report = build_report(_read(run_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(report, encoding="utf-8")
    temporary.replace(output_path)
    print(f"RI-4 public report: {output_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReportError as exc:
        print(f"RI-4 public report error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
