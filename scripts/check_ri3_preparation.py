"""Verify the ignored local RI-3 development preparation report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.materialize_ri3_preflight import (  # noqa: E402
    DEFAULT_REPORT,
    _canonical_hash,
)


class PreparationCheckError(RuntimeError):
    """Raised when the local preparation evidence violates its contract."""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--expected-eligible", type=int, default=663)
    return parser.parse_args()


def _resolve_ignored_path(value: str, runtime_root: Path) -> Path:
    path = (REPO_ROOT / value).resolve()
    try:
        path.relative_to(runtime_root.resolve())
    except ValueError as exc:
        raise PreparationCheckError(f"Path escapes RI-3 runtime root: {value}") from exc
    return path


def _check_report(payload: Mapping[str, Any], *, report_path: Path, expected: int) -> None:
    if payload.get("schema_version") != "biovoid-ri3-preparation-preflight-v1":
        raise PreparationCheckError("Unexpected preparation report schema")
    if payload.get("status") != "pass":
        raise PreparationCheckError("Preparation report is not pass")
    if payload.get("preflight_sha256") != _canonical_hash(payload):
        raise PreparationCheckError("Preparation report hash does not match its content")
    if payload.get("archive", {}).get("full_archive_downloaded") is not False:
        raise PreparationCheckError("Full archive download flag is not false")
    for key in ("detector_started", "nma_started", "sealed_evaluation_authorized"):
        if payload.get(key) is not False:
            raise PreparationCheckError(f"Forbidden execution flag is not false: {key}")

    coverage = payload.get("coverage", {})
    if coverage.get("selected_structures") != expected:
        raise PreparationCheckError("Unexpected selected structure count")
    if coverage.get("eligible") != expected or coverage.get("ineligible") != 0:
        raise PreparationCheckError("Preparation coverage is not fully eligible")
    if coverage.get("unavailable") != 0:
        raise PreparationCheckError("Preparation has unavailable members")

    runtime_root = (REPO_ROOT / "data/runtime/ri3").resolve()
    records = payload.get("records", [])
    if len(records) != expected:
        raise PreparationCheckError("Record count does not match selected structure count")
    forbidden_keys = {
        "holo_pdb_id",
        "holo_chain",
        "ligand",
        "ligand_center",
        "target_center",
        "target_residues",
        "hit_label",
    }
    for record in records:
        if record.get("status") != "eligible":
            raise PreparationCheckError("Non-eligible record present in pass report")
        if forbidden_keys.intersection(record):
            raise PreparationCheckError("Evaluator field leaked into preparation record")
        preparation = record.get("preparation", {})
        if preparation.get("status") != "eligible":
            raise PreparationCheckError("Record preparation status is not eligible")
        for field in ("member_path", "prepared_path"):
            path_value = preparation.get(field)
            if not isinstance(path_value, str):
                raise PreparationCheckError(f"Missing preparation path: {field}")
            path = _resolve_ignored_path(path_value, runtime_root)
            if not path.is_file():
                raise PreparationCheckError(f"Preparation file is missing: {path_value}")

    materialization = payload.get("materialization", {})
    compressed_total = sum(int(record["member"]["compressed_size"]) for record in records)
    uncompressed_total = sum(int(record["member"]["uncompressed_size"]) for record in records)
    if materialization.get("selected_member_compressed_bytes") != compressed_total:
        raise PreparationCheckError("Compressed member total is inconsistent")
    if materialization.get("selected_member_uncompressed_bytes") != uncompressed_total:
        raise PreparationCheckError("Uncompressed member total is inconsistent")
    if not report_path.is_file():
        raise PreparationCheckError("Preparation report path is missing")


def main() -> int:
    args = _parse_args()
    payload = json.loads(args.report.read_text(encoding="utf-8"))
    _check_report(payload, report_path=args.report, expected=args.expected_eligible)
    print("RI-3 preparation check: PASS")
    print(f"eligible structures: {args.expected_eligible}")
    print(f"preflight sha256: {payload['preflight_sha256']}")
    print("detector/NMA/sealed: not started/closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
