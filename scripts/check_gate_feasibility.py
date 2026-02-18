#!/usr/bin/env python3
"""Gate feasibility pre-check for Phase 5.5 overlap target.

Stops gate execution early when configured overlap target is mathematically
above observed center-overlap upper bound.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
RED = "\033[31m"
RESET = "\033[0m"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_center_upper_bound(payload: dict[str, Any]) -> float | None:
    global_row = payload.get("global", {})
    candidates = [
        global_row.get("center_overlap_upper_bound"),
        global_row.get("center_only_overlap_upper_bound"),
        global_row.get("center_only_overlap_greedy"),
    ]
    for value in candidates:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def evaluate_feasibility(pre_reg_path: Path, benchmark_path: Path) -> dict[str, Any]:
    pre_reg = _load_json(pre_reg_path)
    benchmark = _load_json(benchmark_path)

    target = float(pre_reg.get("decision_gates", {}).get("min_fpocket_overlap", 0.40))
    upper_bound = _extract_center_upper_bound(benchmark)
    if upper_bound is None:
        return {
            "ok": False,
            "target_overlap": target,
            "center_overlap_upper_bound": None,
            "reason": "center_overlap_upper_bound_missing",
            "message": "CRITICAL: TARGET UNREACHABLE (missing center upper bound in benchmark).",
        }

    ok = target <= upper_bound
    if ok:
        message = (
            f"Feasibility PASS: target={target:.4f} <= center_upper_bound={upper_bound:.4f}"
        )
    else:
        message = (
            "CRITICAL: TARGET UNREACHABLE "
            f"(target={target:.4f} > center_upper_bound={upper_bound:.4f})"
        )

    return {
        "ok": ok,
        "target_overlap": target,
        "center_overlap_upper_bound": upper_bound,
        "reason": "ok" if ok else "target_exceeds_center_upper_bound",
        "message": message,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Phase 5.5 gate feasibility.")
    parser.add_argument(
        "--pre-reg",
        default="data/validation/pre_registered_config.json",
        help="Path to pre-registered gate config.",
    )
    parser.add_argument(
        "--benchmark-json",
        default="data/benchmark/fpocket_benchmark_v3.json",
        help="Path to benchmark JSON containing center overlap upper bound.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = evaluate_feasibility(ROOT / args.pre_reg, ROOT / args.benchmark_json)

    if result["ok"]:
        print(result["message"])
        return 0

    print(f"{RED}{result['message']}{RESET}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

