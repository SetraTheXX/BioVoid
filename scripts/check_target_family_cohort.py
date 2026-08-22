"""Validate a local leakage-audited target-family cohort without computation.

The input is private evaluator metadata.  The command writes only a compact
readiness report and an apo-only detector manifest under ignored runtime paths;
it never downloads coordinates, opens a structure file, or starts ML.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.target_family_cohort import (  # noqa: E402
    CohortContractError,
    assess_cohort_readiness,
    build_target_blind_manifest,
)


DEFAULT_INPUT = REPO_ROOT / "local-private/research/target-family/cohort-pfam-v1.json"
DEFAULT_READINESS_OUTPUT = (
    REPO_ROOT / "data/runtime/target-family/cohort-readiness-pfam-v1/"
    "target-family-cohort-readiness-pfam-v1.json"
)
DEFAULT_DETECTOR_OUTPUT = (
    REPO_ROOT / "data/runtime/target-family/cohort-detector-pfam-v1/"
    "target-family-cohort-detector-pfam-v1.json"
)


class CohortReadinessError(RuntimeError):
    """Raised when the local cohort cannot be loaded or validated."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CohortReadinessError(f"cannot read cohort metadata: {path}") from exc
    if not isinstance(payload, dict):
        raise CohortReadinessError("cohort metadata must be a JSON object")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def check_target_family_cohort(
    *,
    input_path: Path = DEFAULT_INPUT,
    readiness_output: Path = DEFAULT_READINESS_OUTPUT,
    detector_output: Path = DEFAULT_DETECTOR_OUTPUT,
    minimum_cases: int = 6,
) -> dict[str, Any]:
    """Validate metadata and materialize a redacted manifest only."""

    resolved_input = input_path.resolve()
    payload = _read_json(resolved_input)
    try:
        report = assess_cohort_readiness(payload, minimum_cases=minimum_cases)
        detector_manifest = build_target_blind_manifest(payload)
    except (CohortContractError, ValueError) as exc:
        raise CohortReadinessError(str(exc)) from exc
    readiness_payload = {
        **report,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "input_manifest_sha256": _sha256_file(resolved_input),
        "detector_manifest_sha256": detector_manifest["manifest_sha256"],
        "detector_manifest_written": True,
        "coordinates_downloaded": False,
        "ml_training_started": False,
    }
    _write_json(readiness_output.resolve(), readiness_payload)
    _write_json(detector_output.resolve(), detector_manifest)
    print(
        f"target-family cohort readiness: {report['status']} "
        f"cases={report['case_count']} held_out_ready={report['held_out_ready']}"
    )
    print(f"readiness report: {readiness_output}")
    print(f"detector manifest: {detector_output}")
    return readiness_payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--readiness-output", type=Path, default=DEFAULT_READINESS_OUTPUT)
    parser.add_argument("--detector-output", type=Path, default=DEFAULT_DETECTOR_OUTPUT)
    parser.add_argument("--minimum-cases", type=int, default=6)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        check_target_family_cohort(
            input_path=args.input,
            readiness_output=args.readiness_output,
            detector_output=args.detector_output,
            minimum_cases=args.minimum_cases,
        )
    except CohortReadinessError as exc:
        print(f"target-family cohort error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
