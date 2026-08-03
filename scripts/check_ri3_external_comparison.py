"""Check the local RI-3 external comparison boundary and coverage."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.benchmark_v1 import phase6_frozen_protocol_v1  # noqa: E402

DEFAULT_COMPARISON = REPO_ROOT / "data/runtime/ri3/ri3-static-external-comparison-v1.json"
DEFAULT_FPOCKET = REPO_ROOT / (
    "data/runtime/ri3/external-baselines-v1/fpocket-development-v1.json"
)
DEFAULT_P2RANK = REPO_ROOT / (
    "data/runtime/ri3/external-baselines-v1/p2rank-development-v1.json"
)
DEFAULT_ELIGIBILITY = REPO_ROOT / "data/runtime/ri3/ri3-development-evaluator-eligibility-v1.json"


class ComparisonCheckError(RuntimeError):
    """Raised when a comparison report violates its safety contract."""


def _read(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComparisonCheckError(f"Cannot read {path}") from exc
    if not isinstance(payload, dict):
        raise ComparisonCheckError(f"Expected JSON object: {path}")
    return payload


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, default=DEFAULT_COMPARISON)
    parser.add_argument("--fpocket", type=Path, default=DEFAULT_FPOCKET)
    parser.add_argument("--p2rank", type=Path, default=DEFAULT_P2RANK)
    parser.add_argument("--eligibility", type=Path, default=DEFAULT_ELIGIBILITY)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    comparison = _read(_resolve(args.comparison))
    if comparison.get("schema_version") != "biovoid-ri3-static-external-comparison-v1":
        raise ComparisonCheckError("Comparison schema mismatch")
    if comparison.get("status") != "complete_relocked_development_comparison":
        raise ComparisonCheckError("Comparison is not complete")
    if comparison.get("scientific_superiority_claim_authorized") is not False:
        raise ComparisonCheckError("Comparison claim boundary is open")
    if comparison.get("sealed_evaluation_authorized") is not False:
        raise ComparisonCheckError("Sealed boundary is open")
    if comparison.get("target_blind_detector_inputs") is not True:
        raise ComparisonCheckError("Target-blind boundary is missing")
    if comparison.get("protocol_sha256") != phase6_frozen_protocol_v1().protocol_sha256:
        raise ComparisonCheckError("Comparison protocol hash mismatch")
    coverage = comparison.get("coverage", {})
    eligibility = _read(_resolve(args.eligibility))
    if eligibility.get("schema_version") != "biovoid-ri3-development-evaluator-eligibility-v1":
        raise ComparisonCheckError("Evaluator eligibility schema mismatch")
    if comparison.get("evaluator_eligibility_lock_sha256") != _sha256_file(
        _resolve(args.eligibility)
    ):
        raise ComparisonCheckError("Comparison eligibility lock hash mismatch")
    if coverage.get("original_case_count") != 825:
        raise ComparisonCheckError("Expected 825 original development cases")
    available = int(coverage.get("available_ground_truth_case_count", 0))
    if available != eligibility.get("eligible_case_count"):
        raise ComparisonCheckError("Comparison cohort differs from evaluator eligibility")
    if available < 500:
        raise ComparisonCheckError("Available comparison subset is unexpectedly small")
    for detector in ("biovoid_static", "fpocket", "p2rank"):
        result = comparison.get("results", {}).get(detector)
        if not isinstance(result, dict):
            raise ComparisonCheckError(f"Missing result for {detector}")
        if result.get("target_denominator") != available:
            raise ComparisonCheckError(f"{detector} denominator differs from comparison subset")
        dcc_recall = result.get("top_k_dcc_recall", {})
        if 3 not in dcc_recall and "3" not in dcc_recall:
            raise ComparisonCheckError(f"{detector} Top-3 result is missing")
    for path, tool in ((_resolve(args.fpocket), "fpocket"), (_resolve(args.p2rank), "p2rank")):
        report = _read(path)
        if report.get("status") != "complete" or len(report.get("records", {})) != 663:
            raise ComparisonCheckError(f"{tool} baseline is not complete at 663 structures")
        if report.get("counts", {}).get("failed") != 0:
            raise ComparisonCheckError(f"{tool} baseline contains failed structures")
    print(
        "RI-3 external comparison boundary: PASS "
        f"subset={available} residual={coverage.get('residual_unavailable_case_count')}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ComparisonCheckError as exc:
        print(f"RI-3 external comparison check: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
