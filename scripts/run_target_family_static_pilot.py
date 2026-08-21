"""Run the bounded, target-blind PF00497 static smoke pilot.

The runner accepts a redacted metadata-only manifest produced by either
``build_target_family_manifest.py`` or the leakage-audited cohort checker. It
materializes the bounded apo structures,
prepares them with the canonical full-heavy-atom policy, runs
``canonical-static-v1`` one case at a time, and keeps a hard local disk quota.
It never reads the private pair inventory, downloads holo coordinates, starts
motion/NMA, invokes external baselines, or trains ML.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.fetcher import fetch_structure_input  # noqa: E402
from src.resources import (  # noqa: E402
    ResourceLimitError,
    SAFE_16GB,
    get_process_memory_snapshot,
)
from src.static_detector import detect_static_pockets  # noqa: E402
from src.structure_preparation import (  # noqa: E402
    PreparationConfig,
    StructureSource,
    load_structure_atoms,
    prepare_structure,
)
from src.target_family_manifest import (  # noqa: E402
    MAX_PILOT_CASES,
    validate_detector_manifest,
)


DEFAULT_MANIFEST = REPO_ROOT / "data/runtime/target-family/target-blind-static-pilot-v1.json"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/runtime/target-family/static-pilot-v1"
MAX_DISK_BYTES = 1_000_000_000
PILOT_RUN_SCHEMA_VERSION = "biovoid-target-family-static-pilot-run-v1"
FORBIDDEN_OUTPUT_TOKENS = ("holo", "ligand", "evaluator", "ground_truth")


class TargetFamilyPilotError(RuntimeError):
    """Raised when the bounded target-family pilot contract cannot proceed."""


class DiskQuotaExceeded(TargetFamilyPilotError):
    """Raised before/after a case when the local pilot directory exceeds its cap."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TargetFamilyPilotError(f"Expected a JSON object: {path}")
    return payload


def directory_size_bytes(root: Path) -> int:
    """Return regular-file bytes below ``root`` without following symlinks."""

    if not root.exists():
        return 0
    total = 0
    for directory, _, filenames in os.walk(root, followlinks=False):
        for filename in filenames:
            path = Path(directory) / filename
            try:
                if not path.is_symlink():
                    total += path.stat().st_size
            except FileNotFoundError:
                continue
    return total


def enforce_disk_quota(root: Path, max_disk_bytes: int) -> int:
    """Measure and enforce the pilot output quota."""

    if max_disk_bytes < 1:
        raise ValueError("max_disk_bytes must be positive")
    used = directory_size_bytes(root)
    if used > max_disk_bytes:
        raise DiskQuotaExceeded(f"Pilot disk quota exceeded: {used} bytes > {max_disk_bytes} bytes")
    return used


def build_pilot_run_skeleton(
    manifest: Mapping[str, Any],
    *,
    max_disk_bytes: int = MAX_DISK_BYTES,
) -> dict[str, Any]:
    """Build a target-blind run record before any coordinate is requested."""

    validate_detector_manifest(manifest)
    if max_disk_bytes < 1:
        raise ValueError("max_disk_bytes must be positive")
    case_count = int(manifest["constraints"]["case_count"])
    if not 1 <= case_count <= MAX_PILOT_CASES:
        raise TargetFamilyPilotError("Pilot manifest case count is outside the bounded range")
    payload: dict[str, Any] = {
        "schema_version": PILOT_RUN_SCHEMA_VERSION,
        "status": "not_started",
        "manifest_sha256": manifest["manifest_sha256"],
        "family_id": manifest["family_id"],
        "execution": {
            "resource_profile": SAFE_16GB.name,
            "workers": 1,
            "motion_enabled": False,
            "external_baselines_enabled": False,
            "max_disk_bytes": max_disk_bytes,
            "disk_quota_enforced": True,
        },
        "detector": {
            "version": "canonical-static-v1",
            "score_used": False,
            "ranking_contract": "canonical-static-v1-volume-descending",
        },
        "interpretation_status": "pending_independent_review",
        "claim_boundary": "unvalidated_static_method_smoke",
        "cases": {},
        "counts": {"completed": 0, "failed": 0, "resource_blocked": 0},
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
    }
    payload["run_sha256"] = _stable_hash(
        {key: value for key, value in payload.items() if key != "run_sha256"}
    )
    return payload


def validate_pilot_run(payload: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    """Validate static-only run provenance and evaluator redaction."""

    validate_detector_manifest(manifest)
    if payload.get("schema_version") != PILOT_RUN_SCHEMA_VERSION:
        raise TargetFamilyPilotError("Unexpected target-family pilot run schema")
    if payload.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise TargetFamilyPilotError("Pilot run is not bound to its target-blind manifest")
    execution = payload.get("execution")
    if not isinstance(execution, Mapping):
        raise TargetFamilyPilotError("Pilot run is missing execution controls")
    if execution.get("workers") != 1 or execution.get("motion_enabled") is not False:
        raise TargetFamilyPilotError("Pilot run violates single-worker static boundary")
    if execution.get("external_baselines_enabled") is not False:
        raise TargetFamilyPilotError("Pilot run unexpectedly enables external baselines")
    if not isinstance(execution.get("max_disk_bytes"), int) or execution["max_disk_bytes"] < 1:
        raise TargetFamilyPilotError("Pilot run has no positive disk quota")
    if payload.get("claim_boundary") != "unvalidated_static_method_smoke":
        raise TargetFamilyPilotError("Pilot run has an unsafe claim boundary")
    expected_hash = _stable_hash(
        {key: value for key, value in payload.items() if key != "run_sha256"}
    )
    if payload.get("run_sha256") != expected_hash:
        raise TargetFamilyPilotError("Pilot run hash does not match its content")
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True).casefold()
    for token in FORBIDDEN_OUTPUT_TOKENS:
        if token in encoded:
            raise TargetFamilyPilotError(f"Pilot run contains forbidden token: {token}")


def _seal_run(payload: dict[str, Any]) -> None:
    payload["updated_at_utc"] = _utc_now()
    payload["run_sha256"] = _stable_hash(
        {key: value for key, value in payload.items() if key != "run_sha256"}
    )


def _case_counts(payload: Mapping[str, Any]) -> dict[str, int]:
    counts = {"completed": 0, "failed": 0, "resource_blocked": 0}
    cases = payload.get("cases", {})
    if isinstance(cases, Mapping):
        for case in cases.values():
            if isinstance(case, Mapping) and case.get("status") in counts:
                counts[str(case["status"])] += 1
    return counts


def _relative_to_repo(path: Path) -> str:
    return str(path.resolve().relative_to(REPO_ROOT)).replace("\\", "/")


def _safe_error(exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}"
    for token in FORBIDDEN_OUTPUT_TOKENS:
        message = message.replace(token, "[redacted]").replace(token.upper(), "[redacted]")
    return message[:500]


def _run_case(
    case: Mapping[str, Any],
    *,
    output_root: Path,
    max_disk_bytes: int,
) -> dict[str, Any]:
    case_id = str(case["case_id"])
    structure_id = str(case["structure_id"]).upper()
    case_dir = output_root / "cases" / structure_id
    source_cache = output_root / "source-cache"
    preparation_dir = case_dir / "preparation"
    started = time.perf_counter()
    before = get_process_memory_snapshot()
    common: dict[str, Any] = {
        "case_id": case_id,
        "structure_id": structure_id,
        "status": "failed",
        "motion_enabled": False,
        "external_baselines_enabled": False,
        "score_used": False,
        "nma_started": False,
    }
    enforce_disk_quota(output_root, max_disk_bytes)
    source = StructureSource(
        provider="rcsb",
        identifier=structure_id,
        representation="asymmetric_unit",
    )
    try:
        fetched = fetch_structure_input(source, cache_dir=source_cache)
        enforce_disk_quota(output_root, max_disk_bytes)
        input_atoms = load_structure_atoms(fetched.path)
        if preparation_dir.exists():
            raise TargetFamilyPilotError(f"Preparation directory already exists: {preparation_dir}")
        preparation = prepare_structure(
            fetched.path,
            source,
            PreparationConfig(),
            preparation_dir,
            run_id=f"target-family-{structure_id.lower()}-static-v1",
            source_metadata={
                "provider": "RCSB PDB",
                "entry_id": structure_id,
                "representation": "asymmetric_unit",
                "metadata_only_selection": True,
            },
            analysis_config={
                "purpose": "target_family_static_smoke",
                "resource_profile": SAFE_16GB.name,
                "workers": 1,
                "motion_enabled": False,
                "external_baselines_enabled": False,
            },
        )
        enforce_disk_quota(output_root, max_disk_bytes)
        detection = detect_static_pockets(
            preparation.prepared_path,
            prepared_sha256=preparation.prepared_sha256,
            resource_profile=SAFE_16GB,
        )
        after = get_process_memory_snapshot()
        enforce_disk_quota(output_root, max_disk_bytes)
        common.update(
            {
                "status": "completed",
                "input_atom_count": len(input_atoms),
                "protein_atom_count": detection.protein_atom_count,
                "candidate_count": detection.candidate_count,
                "pocket_count": len(detection.pockets),
                "top_pockets": [pocket.to_portable_dict() for pocket in detection.pockets[:10]],
                "detector_warnings": list(detection.warnings),
                "detector_version": detection.detector_version,
                "detector_config_sha256": detection.config_sha256,
                "prepared_structure_sha256": preparation.prepared_sha256,
                "preparation_config_sha256": preparation.config_sha256,
                "prepared_path": _relative_to_repo(preparation.prepared_path),
                "runtime_seconds": round(time.perf_counter() - started, 6),
                "peak_rss_bytes": max(before.peak_rss_bytes, after.peak_rss_bytes),
            }
        )
    except ResourceLimitError as exc:
        common.update(
            {
                "status": "resource_blocked",
                "error": _safe_error(exc),
                "runtime_seconds": round(time.perf_counter() - started, 6),
                "peak_rss_bytes": before.peak_rss_bytes,
            }
        )
    except Exception as exc:  # noqa: BLE001 - failed cases remain visible in the denominator
        common.update(
            {
                "status": "failed",
                "error": _safe_error(exc),
                "runtime_seconds": round(time.perf_counter() - started, 6),
                "peak_rss_bytes": before.peak_rss_bytes,
            }
        )
    return common


def run_static_pilot(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    max_disk_bytes: int = MAX_DISK_BYTES,
    user_approved: bool = False,
) -> dict[str, Any]:
    """Run the approved, two-case target-blind static pilot."""

    if not user_approved:
        raise TargetFamilyPilotError(
            "Coordinate download requires explicit user approval for the static pilot"
        )
    if max_disk_bytes < 1 or max_disk_bytes > MAX_DISK_BYTES:
        raise ValueError(f"max_disk_bytes must be between 1 and {MAX_DISK_BYTES}")
    manifest = _read_json(manifest_path.resolve())
    validate_detector_manifest(manifest)
    if output_root.exists() and any(output_root.iterdir()):
        raise TargetFamilyPilotError(f"Pilot output root is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    enforce_disk_quota(output_root, max_disk_bytes)
    run = build_pilot_run_skeleton(manifest, max_disk_bytes=max_disk_bytes)
    run["status"] = "running"
    run["execution"]["started_disk_bytes"] = directory_size_bytes(output_root)
    _seal_run(run)
    run_path = output_root / "target-family-static-pilot-run-v1.json"
    _write_json(run_path, run)
    enforce_disk_quota(output_root, max_disk_bytes)

    for case in manifest["cases"]:
        if not isinstance(case, Mapping):
            raise TargetFamilyPilotError("Manifest case is not an object")
        result = _run_case(case, output_root=output_root, max_disk_bytes=max_disk_bytes)
        run["cases"][str(case["case_id"])] = result
        run["counts"] = _case_counts(run)
        run["execution"]["last_case_disk_bytes"] = directory_size_bytes(output_root)
        _seal_run(run)
        validate_pilot_run(run, manifest)
        _write_json(run_path, run)

    final_disk_bytes = enforce_disk_quota(output_root, max_disk_bytes)
    run["execution"]["final_disk_bytes"] = final_disk_bytes
    run["status"] = (
        "completed_target_blind_static_smoke"
        if run["counts"]["completed"] == len(manifest["cases"])
        else "completed_with_failures"
    )
    _seal_run(run)
    validate_pilot_run(run, manifest)
    _write_json(run_path, run)
    return run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--max-disk-bytes", type=int, default=MAX_DISK_BYTES)
    parser.add_argument(
        "--approve-static-pilot",
        action="store_true",
        help="Explicitly authorize coordinate download and the bounded static pilot.",
    )
    args = parser.parse_args()
    if not args.approve_static_pilot:
        raise SystemExit("Pass --approve-static-pilot after explicit user authorization")
    run = run_static_pilot(
        manifest_path=args.manifest,
        output_root=args.output_root,
        max_disk_bytes=args.max_disk_bytes,
        user_approved=True,
    )
    print(f"status={run['status']}")
    print(f"completed={run['counts']['completed']}")
    print(f"failed={run['counts']['failed']}")
    print(f"resource_blocked={run['counts']['resource_blocked']}")
    print(f"disk_bytes={run['execution']['final_disk_bytes']}")
    print(f"run_sha256={run['run_sha256']}")
    return 0 if run["status"] == "completed_target_blind_static_smoke" else 2


if __name__ == "__main__":
    main()
