"""Write a compact, claim-safe RI-5 report from ignored runtime evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVALUATION = REPO_ROOT / "data/runtime/ri5/sealed-static-evaluation-v1.json"
DEFAULT_RUN = REPO_ROOT / "data/runtime/ri5/sealed-static-run-v1.json"
DEFAULT_OUTPUT = REPO_ROOT / "local-private/research/ri-5-sealed-evaluation-report-v1.md"


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.8f}"
    return str(value)


def write_report(evaluation_path: Path, run_path: Path, output_path: Path) -> None:
    evaluation = _read(evaluation_path)
    run = _read(run_path)
    summary = evaluation.get("summary", {})
    partial = summary.get("partial_metrics_on_alignment_available_cases", {})
    errors = summary.get("residual_error_categories", {})
    lines = [
        "# RI-5 Sealed Static Evaluation Report v1",
        "",
        "Status: **RI-5 v1 closed without a scientific claim; evaluator coverage incomplete; primary claim NO-GO**",
        "",
        "This is a local, protocol-bound evaluation record. It is not a discovery,",
        "prediction guarantee, drug-discovery result, clinical result, or external",
        "replication. The canonical static arm was evaluated; RI-4 motion remained",
        "experimental and was not promoted into the canonical result.",
        "",
        "## Execution",
        "",
        f"- Static structures: `{len(run.get('records', {}))}`",
        f"- Static completed: `{run.get('counts', {}).get('completed')}`",
        f"- Static resource-blocked: `{run.get('counts', {}).get('resource_blocked')}`",
        f"- Static failures: `{run.get('counts', {}).get('failed')}`",
        "- Resource profile: `safe-16gb`, one worker",
        "- Detector input: prepared apo structure only; target-blind",
        "",
        "## Evaluator Coverage",
        "",
        f"- Target-site cases: `{summary.get('expected_cases')}`",
        f"- Alignment-available cases: `{summary.get('completed_ground_truth')}`",
        f"- Alignment-unavailable cases: `{summary.get('alignment_unavailable')}`",
        "",
        "The unavailable cases remain visible and were not silently removed or",
        "force-mapped. Because the locked evaluator coverage is incomplete, the",
        "sealed primary endpoint is not eligible for a scientific claim.",
        "",
        "## Diagnostic Subset",
        "",
        "The following values are descriptive only and use the alignment-available",
        "subset. They must not be read as full sealed-split recall.",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for metric, values in (
        ("Top-1 DCC recall", partial.get("top_k_dcc_recall", {}).get("1")),
        ("Top-3 DCC recall", partial.get("top_k_dcc_recall", {}).get("3")),
        ("Top-5 DCC recall", partial.get("top_k_dcc_recall", {}).get("5")),
        ("Top-1 DCA recall", partial.get("top_k_dca_recall", {}).get("1")),
        ("Top-3 DCA recall", partial.get("top_k_dca_recall", {}).get("3")),
        ("Top-5 DCA recall", partial.get("top_k_dca_recall", {}).get("5")),
    ):
        lines.append(f"| {metric} | `{_fmt(values)}` |")
    lines.extend(
        [
            "",
            "## Residual Coverage Reasons",
            "",
        ]
    )
    for reason, count in errors.items():
        lines.append(f"- `{reason}`: `{count}`")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "- Sealed static execution: **complete**",
            "- Evaluator coverage: **incomplete**",
            "- Full primary endpoint: **not eligible**",
            "- RI-5 phase disposition: **closed without claim**",
            "- Scientific superiority claim: **not authorized**",
            "- Canonical ranking changed: **no**",
            "",
            "The RI-5 v1 record is closed. The next valid step is a new versioned",
            "evaluator-eligibility policy and full development re-run if the project",
            "chooses to address alignment coverage. The existing sealed ledger must",
            "not be reused for a changed protocol or selectively re-admitted cases.",
            "",
        ]
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"RI-5 public report: {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, default=DEFAULT_EVALUATION)
    parser.add_argument("--run", dest="run_path", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    write_report(args.evaluation, args.run_path, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
