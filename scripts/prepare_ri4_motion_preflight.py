"""Create a fixed, resource-safe RI-4 development motion cohort without running NMA."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_ri3_static_development import (  # noqa: E402
    _ground_truth_from_payload,
    _load_detector_records,
    _read_json,
)
from scripts.run_ri3_static_development import (  # noqa: E402
    DEFAULT_MANIFEST,
    DEFAULT_RUN,
    MANIFEST_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    _validate_manifest,
    _validate_run,
)
from src.dynamics import load_ca_atoms  # noqa: E402
from src.motion_ensemble import MotionEnsembleConfig  # noqa: E402
from src.resources import SAFE_16GB, ResourceLimitError  # noqa: E402
from src.benchmark_v1 import (  # noqa: E402
    BenchmarkCase,
    BenchmarkManifest,
    evaluate_split,
    phase6_frozen_protocol_v1,
)


DEFAULT_ELIGIBILITY = REPO_ROOT / "data/runtime/ri3/ri3-development-evaluator-eligibility-v1.json"
DEFAULT_RECOVERY = REPO_ROOT / (
    "data/runtime/ri3/ri3-static-development-evaluation-structural-recovery-v1.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "data/runtime/ri4/ri4-development-motion-preflight-v1.json"
SCHEMA_VERSION = "biovoid-ri4-development-motion-preflight-v1"


class RI4PreflightError(RuntimeError):
    """Raised when an RI-4 pilot cohort cannot be fixed safely."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def build_motion_preflight(
    manifest: Mapping[str, Any],
    static_run: Mapping[str, Any],
    eligibility: Mapping[str, Any],
    recovery: Mapping[str, Any],
) -> dict[str, Any]:
    """Intersect locked evaluator eligibility with static and NMA resource eligibility."""
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise RI4PreflightError("Unexpected RI-3 manifest schema")
    _validate_manifest(manifest)
    if static_run.get("schema_version") != RUN_SCHEMA_VERSION:
        raise RI4PreflightError("Unexpected RI-3 static run schema")
    _validate_run(static_run, manifest)
    if eligibility.get("schema_version") != "biovoid-ri3-development-evaluator-eligibility-v1":
        raise RI4PreflightError("Unexpected evaluator eligibility schema")
    if eligibility.get("status") != "locked_development_evaluator_eligibility":
        raise RI4PreflightError("Evaluator eligibility is not locked")
    decisions = eligibility.get("policy_decisions", {})
    if decisions.get("ri4_preflight_authorized") is not True:
        raise RI4PreflightError("Evaluator eligibility does not authorize RI-4 preflight")
    if eligibility.get("runtime_manifest_sha256") != manifest.get("manifest_sha256"):
        raise RI4PreflightError("Eligibility and runtime manifest hashes differ")
    if recovery.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise RI4PreflightError("Recovery and runtime manifest hashes differ")

    all_cases = [
        case
        for case in manifest["benchmark_manifest"]["cases"]
        if case["split"] == "development"
    ]
    excluded_case_ids = {
        str(item["case_id"]).casefold() for item in eligibility.get("excluded_cases", [])
    }
    evaluator_cases = [case for case in all_cases if case["case_id"].casefold() not in excluded_case_ids]
    if len(evaluator_cases) != int(eligibility.get("eligible_case_count", 0)):
        raise RI4PreflightError("Evaluator cohort size does not match eligibility lock")

    structures = {str(item["structure_id"]).upper(): item for item in manifest["structures"]}
    config = MotionEnsembleConfig()
    nominal_available_memory = SAFE_16GB.soft_memory_budget_bytes + SAFE_16GB.minimum_available_memory_bytes
    selected_case_ids: list[str] = []
    selected_structure_ids: set[str] = set()
    exclusions: list[dict[str, str]] = []
    structure_status: dict[str, str] = {}
    for case in evaluator_cases:
        case_id = str(case["case_id"])
        structure_id = str(case["structure_id"]).upper()
        record = static_run["records"].get(structure_id)
        if not isinstance(record, Mapping) or record.get("status") != "completed":
            exclusions.append({"case_id": case_id, "reason_code": "static_not_completed"})
            structure_status[structure_id] = "static_not_completed"
            continue
        structure = structures.get(structure_id)
        if structure is None:
            raise RI4PreflightError(f"Structure missing from manifest: {structure_id}")
        prepared = (REPO_ROOT / str(structure["prepared_path"])).resolve()
        if not prepared.is_file():
            raise RI4PreflightError(f"Prepared structure is missing: {prepared}")
        try:
            _coordinates, ca_count = load_ca_atoms(str(prepared))
            SAFE_16GB.validate_motion_request(
                atom_count=ca_count,
                samples_per_mode=config.samples_per_mode,
                mode_count=config.n_modes,
                available_memory_bytes=nominal_available_memory,
                solver=config.solver,
            )
        except (ResourceLimitError, ValueError) as exc:
            exclusions.append(
                {
                    "case_id": case_id,
                    "reason_code": "motion_resource_ineligible",
                    "detail": str(exc),
                }
            )
            structure_status[structure_id] = "motion_resource_ineligible"
            continue
        selected_case_ids.append(case_id)
        selected_structure_ids.add(structure_id)
        structure_status[structure_id] = "motion_preflight_eligible"

    if not selected_case_ids:
        raise RI4PreflightError("No static-complete, motion-safe evaluator cases remain")
    truths = {
        str(case_id).casefold(): _ground_truth_from_payload(raw["ground_truth"])
        for case_id, raw in recovery.get("records", {}).items()
        if raw.get("status") == "completed_ground_truth" and raw.get("ground_truth")
    }
    selected_cases = tuple(
        BenchmarkCase(**case)
        for case in all_cases
        if str(case["case_id"]) in set(selected_case_ids)
    )
    if len(selected_cases) != len(selected_case_ids):
        raise RI4PreflightError("Could not rebuild the fixed motion cohort")
    static_reference = evaluate_split(
        detector="biovoid_static",
        split="development",
        records=_load_detector_records(static_run),
        ground_truth=truths,
        manifest=BenchmarkManifest(cases=selected_cases),
        protocol=phase6_frozen_protocol_v1(),
    )
    if static_reference["failure_rate"] != 0.0:
        raise RI4PreflightError("RI-4 cohort must have a completed static reference")
    exclusion_counts = dict(sorted(Counter(item["reason_code"] for item in exclusions).items()))
    config_payload = asdict(config)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "ready_for_opt_in_motion_pilot",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "runtime_manifest_sha256": manifest["manifest_sha256"],
        "static_run_status": static_run["status"],
        "evaluator_eligibility_lock_sha256": eligibility["eligibility_lock_sha256"],
        "evaluator_eligible_case_count": len(evaluator_cases),
        "motion_preflight_case_count": len(selected_case_ids),
        "motion_preflight_structure_count": len(selected_structure_ids),
        # The hash prevents silent cohort drift; the exact lists make a
        # resumed RI-4 run independently reproducible.
        "motion_preflight_case_ids": sorted(selected_case_ids),
        "motion_preflight_structure_ids": sorted(selected_structure_ids),
        "motion_preflight_case_ids_sha256": _stable_hash(sorted(selected_case_ids)),
        "motion_preflight_structure_ids_sha256": _stable_hash(sorted(selected_structure_ids)),
        "static_reference": static_reference,
        "exclusion_counts": exclusion_counts,
        "exclusions": exclusions,
        "motion_config": config_payload,
        "resource_profile": {
            "name": SAFE_16GB.name,
            "max_nma_atoms": SAFE_16GB.max_nma_atoms,
            "max_heavy_jobs": SAFE_16GB.max_heavy_jobs,
            "max_motion_modes": SAFE_16GB.max_motion_modes,
            "max_samples_per_mode": SAFE_16GB.max_samples_per_mode,
            "max_motion_samples": SAFE_16GB.max_motion_samples,
            "nominal_preflight_available_memory_bytes": nominal_available_memory,
        },
        "boundaries": {
            "target_blind_detector_inputs": True,
            "motion_execution_started": False,
            "canonical_ranking_affected": False,
            "sealed_evaluation_authorized": False,
            "scientific_superiority_claim_authorized": False,
        },
    }
    payload["preflight_sha256"] = _stable_hash(payload)
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--eligibility", type=Path, default=DEFAULT_ELIGIBILITY)
    parser.add_argument("--recovery-report", type=Path, default=DEFAULT_RECOVERY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    manifest_path = _resolve(args.manifest)
    static_path = _resolve(args.static_run)
    eligibility_path = _resolve(args.eligibility)
    recovery_path = _resolve(args.recovery_report)
    output_path = _resolve(args.output)
    payload = build_motion_preflight(
        _read_json(manifest_path),
        _read_json(static_path),
        _read_json(eligibility_path),
        _read_json(recovery_path),
    )
    payload["source_sha256"] = {
        "static_run": _sha256_file(static_path),
        "evaluator_eligibility": _sha256_file(eligibility_path),
        "recovery_report": _sha256_file(recovery_path),
    }
    payload["preflight_sha256"] = _stable_hash(
        {key: value for key, value in payload.items() if key != "preflight_sha256"}
    )
    _write_json_atomic(output_path, payload)
    print(
        "RI-4 motion preflight: READY "
        f"cases={payload['motion_preflight_case_count']} "
        f"structures={payload['motion_preflight_structure_count']} "
        f"exclusions={payload['exclusion_counts']}"
    )
    print("No NMA, frame reconstruction, or detector execution was started.")
    print(f"preflight: {output_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RI4PreflightError as exc:
        print(f"RI-4 motion preflight error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
