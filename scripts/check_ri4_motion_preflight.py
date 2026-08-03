"""Verify that an RI-4 motion preflight remains bounded and claim-safe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PREFLIGHT = REPO_ROOT / "data/runtime/ri4/ri4-development-motion-preflight-v1.json"


class PreflightCheckError(RuntimeError):
    """Raised when an RI-4 preflight violates its declared boundary."""


def _read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightCheckError(f"Cannot read preflight: {path}") from exc
    if not isinstance(payload, dict):
        raise PreflightCheckError("Preflight must be a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    args = parser.parse_args()
    path = args.preflight if args.preflight.is_absolute() else REPO_ROOT / args.preflight
    payload = _read(path)
    if payload.get("schema_version") != "biovoid-ri4-development-motion-preflight-v1":
        raise PreflightCheckError("Preflight schema mismatch")
    if payload.get("status") != "ready_for_opt_in_motion_pilot":
        raise PreflightCheckError("Preflight is not ready")
    if int(payload.get("motion_preflight_case_count", 0)) < 1:
        raise PreflightCheckError("Preflight cohort is empty")
    case_ids = payload.get("motion_preflight_case_ids")
    structure_ids = payload.get("motion_preflight_structure_ids")
    if not isinstance(case_ids, list) or len(case_ids) != payload.get("motion_preflight_case_count"):
        raise PreflightCheckError("Preflight exact case list is missing or inconsistent")
    if not isinstance(structure_ids, list) or len(structure_ids) != payload.get("motion_preflight_structure_count"):
        raise PreflightCheckError("Preflight exact structure list is missing or inconsistent")
    import hashlib
    import json

    def stable_hash(value: object) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    if stable_hash(sorted(str(item) for item in case_ids)) != payload.get(
        "motion_preflight_case_ids_sha256"
    ):
        raise PreflightCheckError("Preflight case list hash mismatch")
    if stable_hash(sorted(str(item) for item in structure_ids)) != payload.get(
        "motion_preflight_structure_ids_sha256"
    ):
        raise PreflightCheckError("Preflight structure list hash mismatch")
    static_reference = payload.get("static_reference", {})
    if static_reference.get("target_denominator") != payload.get("motion_preflight_case_count"):
        raise PreflightCheckError("Static reference denominator differs from the motion cohort")
    if static_reference.get("failure_rate") != 0.0:
        raise PreflightCheckError("Static reference contains unavailable structures")
    resource = payload.get("resource_profile", {})
    if resource.get("name") != "safe-16gb" or int(resource.get("max_heavy_jobs", 0)) != 1:
        raise PreflightCheckError("Resource profile is not the safe one-heavy-job policy")
    boundaries = payload.get("boundaries", {})
    for key, expected in {
        "target_blind_detector_inputs": True,
        "motion_execution_started": False,
        "canonical_ranking_affected": False,
        "sealed_evaluation_authorized": False,
        "scientific_superiority_claim_authorized": False,
    }.items():
        if boundaries.get(key) is not expected:
            raise PreflightCheckError(f"Boundary mismatch: {key}")
    print(
        "RI-4 motion preflight: PASS "
        f"cases={payload['motion_preflight_case_count']} "
        f"structures={payload['motion_preflight_structure_count']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreflightCheckError as exc:
        print(f"RI-4 motion preflight check: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
