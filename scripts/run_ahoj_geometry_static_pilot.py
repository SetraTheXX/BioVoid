"""Run the bounded AHoJ development-only canonical static pilot.

The runner consumes only the sealed apo-only manifest and its completed
development preparation/preflight artifact.  It runs one case at a time,
retains every final merged pocket, and never opens the private evaluator
cohort or any held-out structure.
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

from src.resources import ResourceLimitError, SAFE_16GB, get_process_memory_snapshot  # noqa: E402
from src.static_detector import detect_static_pockets  # noqa: E402
from src.structure_preparation import load_structure_atoms  # noqa: E402
from scripts.seal_ahoj_geometry_cohort import (  # noqa: E402
    AhojMetadataResolutionError,
    _read_json,
)

DEFAULT_MANIFEST = (
    REPO_ROOT / "data/runtime/target-family/cohort-ahoj-geometry-v1/"
    "ahoj-geometry-detector-manifest-v1.json"
)
DEFAULT_PREFLIGHT = (
    REPO_ROOT / "data/runtime/target-family/cohort-ahoj-geometry-v1/"
    "development-materialization-v2/development-preflight-v2.json"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "data/runtime/target-family/cohort-ahoj-geometry-v1/static-development-pilot-v1"
)
MAX_DISK_BYTES = 1 * 1024**3
FORBIDDEN_OUTPUT_TOKENS = ("holo", "ligand", "evaluator", "ground_truth", "bio_score")


class AhojStaticPilotError(RuntimeError):
    """Raised when the sealed static pilot contract cannot proceed."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _directory_size_bytes(root: Path) -> int:
    total = 0
    if not root.exists():
        return total
    for directory, _, filenames in os.walk(root, followlinks=False):
        for filename in filenames:
            path = Path(directory) / filename
            if not path.is_symlink():
                total += path.stat().st_size
    return total


def _validate_manifest(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if manifest.get("schema_version") != "biovoid-ahoj-geometry-detector-manifest-v1":
        raise AhojStaticPilotError("unsupported AHoJ detector manifest schema")
    if manifest.get("manifest_kind") != "target_blind_apo_full_structure_manifest":
        raise AhojStaticPilotError("manifest is not target-blind full-structure")
    if manifest.get("materialization_status") != "metadata_only":
        raise AhojStaticPilotError("manifest must be metadata-only")
    if manifest.get("boundary") != "apo_full_structure_only_v1":
        raise AhojStaticPilotError("manifest is not apo full-structure only")
    constraints = manifest.get("constraints")
    cases = manifest.get("cases")
    if not isinstance(constraints, Mapping) or not isinstance(cases, list):
        raise AhojStaticPilotError("manifest constraints/cases are missing")
    if constraints.get("analysis_workers") != 1 or constraints.get("include_motion") is not False:
        raise AhojStaticPilotError("manifest violates one-worker static boundary")
    if constraints.get("full_heavy_atom_structure") is not True or len(cases) != 10:
        raise AhojStaticPilotError("manifest is not the sealed 10-case full-structure cohort")
    encoded = json.dumps(manifest, ensure_ascii=True).casefold()
    for token in FORBIDDEN_OUTPUT_TOKENS:
        if token in encoded:
            raise AhojStaticPilotError(f"manifest contains forbidden token: {token}")
    development = [
        case for case in cases if isinstance(case, Mapping) and case.get("split") == "development"
    ]
    if len(development) != 6:
        raise AhojStaticPilotError("static pilot requires exactly six development cases")
    return sorted(development, key=lambda case: str(case["case_id"]))


def _validate_preflight(
    preflight: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Mapping[str, Any]]:
    if preflight.get("schema_version") != "biovoid-ahoj-geometry-development-preflight-v1":
        raise AhojStaticPilotError("unsupported AHoJ development preflight schema")
    if preflight.get("status") != "ready_for_static_detector_gate":
        raise AhojStaticPilotError("development preflight is not ready")
    if preflight.get("detector_manifest_sha256") != manifest.get("manifest_sha256"):
        raise AhojStaticPilotError("preflight is not bound to detector manifest")
    if preflight.get("prepared_case_count") != 6 or preflight.get("resource_ready_case_count") != 6:
        raise AhojStaticPilotError("development preflight does not prove 6/6 readiness")
    cases = preflight.get("cases")
    if not isinstance(cases, list):
        raise AhojStaticPilotError("preflight cases are missing")
    indexed = {str(case.get("case_id")): case for case in cases if isinstance(case, Mapping)}
    for case in indexed.values():
        if case.get("status") != "prepared":
            raise AhojStaticPilotError("preflight contains a non-prepared case")
        if case.get("resource", {}).get("status") != "ready_for_static_detector_gate":
            raise AhojStaticPilotError("preflight contains a resource-blocked case")
        prepared_path = REPO_ROOT / str(case.get("prepared_path", ""))
        if not prepared_path.is_file():
            raise AhojStaticPilotError(f"prepared path is missing: {prepared_path}")
    return indexed


def _safe_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    for token in FORBIDDEN_OUTPUT_TOKENS:
        text = text.replace(token, "[redacted]").replace(token.upper(), "[redacted]")
    return text[:500]


def run_ahoj_static_pilot(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    preflight_path: Path = DEFAULT_PREFLIGHT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    max_disk_bytes: int = MAX_DISK_BYTES,
    user_approved: bool = False,
) -> dict[str, Any]:
    if not user_approved:
        raise AhojStaticPilotError("static pilot requires --approve-static-pilot")
    if not 1 <= max_disk_bytes <= MAX_DISK_BYTES:
        raise ValueError("max_disk_bytes must be between 1 byte and 1 GB")
    manifest = _read_json(manifest_path.resolve())
    preflight = _read_json(preflight_path.resolve())
    development_cases = _validate_manifest(manifest)
    prepared_by_case = _validate_preflight(preflight, manifest)
    if output_root.exists() and any(output_root.iterdir()):
        raise AhojStaticPilotError(f"pilot output root is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    if _directory_size_bytes(output_root) > max_disk_bytes:
        raise AhojStaticPilotError("pilot output quota exceeded before start")

    run: dict[str, Any] = {
        "schema_version": "biovoid-ahoj-geometry-static-pilot-v1",
        "status": "running",
        "manifest_sha256": manifest["manifest_sha256"],
        "preflight_sha256": preflight.get("report_sha256"),
        "family_id": manifest["family_id"],
        "execution": {
            "resource_profile": SAFE_16GB.name,
            "workers": 1,
            "motion_enabled": False,
            "external_baselines_enabled": False,
            "candidate_retention": "full_final_pocket_list",
            "max_disk_bytes": max_disk_bytes,
        },
        "detector": {
            "version": "canonical-static-v1",
            "score_used": False,
            "ranking_contract": "canonical-static-v1-volume-descending",
            "candidate_scope": "all_detected_pockets",
        },
        "claim_boundary": "unvalidated_static_method_diagnostic",
        "source_scope": "apo_only_full_heavy_atom_development",
        "cases": {},
        "counts": {"completed": 0, "failed": 0, "resource_blocked": 0},
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "run_sha256": None,
    }

    for manifest_case in development_cases:
        case_id = str(manifest_case["case_id"])
        prepared = prepared_by_case.get(case_id)
        started = time.perf_counter()
        before = get_process_memory_snapshot()
        result: dict[str, Any] = {
            "case_id": case_id,
            "structure_id": str(manifest_case["structure_id"]).upper(),
            "status": "failed",
            "score_used": False,
            "motion_enabled": False,
            "candidate_retention": "full_final_pocket_list",
        }
        try:
            if prepared is None:
                raise AhojStaticPilotError("prepared case missing")
            prepared_path = REPO_ROOT / str(prepared["prepared_path"])
            atoms = load_structure_atoms(prepared_path)
            detection = detect_static_pockets(
                prepared_path,
                prepared_sha256=str(prepared["prepared_sha256"]),
                resource_profile=SAFE_16GB,
            )
            after = get_process_memory_snapshot()
            result.update(
                {
                    "status": "completed",
                    "input_atom_count": len(atoms),
                    "protein_atom_count": detection.protein_atom_count,
                    "candidate_count": detection.candidate_count,
                    "pocket_count": len(detection.pockets),
                    "top_pockets": [pocket.to_portable_dict() for pocket in detection.pockets[:10]],
                    "all_pockets": [pocket.to_portable_dict() for pocket in detection.pockets],
                    "detector_warnings": list(detection.warnings),
                    "detector_version": detection.detector_version,
                    "detector_config_sha256": detection.config_sha256,
                    "prepared_structure_sha256": prepared["prepared_sha256"],
                    "prepared_path": str(prepared_path.resolve().relative_to(REPO_ROOT)).replace(
                        "\\", "/"
                    ),
                    "runtime_seconds": round(time.perf_counter() - started, 6),
                    "peak_rss_bytes": max(before.peak_rss_bytes, after.peak_rss_bytes),
                }
            )
        except ResourceLimitError as exc:
            result.update(
                {
                    "status": "resource_blocked",
                    "error": _safe_error(exc),
                    "runtime_seconds": round(time.perf_counter() - started, 6),
                    "peak_rss_bytes": before.peak_rss_bytes,
                }
            )
        except Exception as exc:  # noqa: BLE001 - case-level failures remain visible
            result.update(
                {
                    "status": "failed",
                    "error": _safe_error(exc),
                    "runtime_seconds": round(time.perf_counter() - started, 6),
                    "peak_rss_bytes": before.peak_rss_bytes,
                }
            )
        run["cases"][case_id] = result
        run["counts"] = {
            key: sum(item.get("status") == key for item in run["cases"].values())
            for key in ("completed", "failed", "resource_blocked")
        }
        if _directory_size_bytes(output_root) > max_disk_bytes:
            raise AhojStaticPilotError("pilot output quota exceeded")
        run["updated_at_utc"] = _utc_now()
        run["run_sha256"] = _stable_hash(
            {key: value for key, value in run.items() if key != "run_sha256"}
        )
        _write_json(output_root / "ahoj-geometry-static-pilot-v1.json", run)

    run["status"] = (
        "completed_target_blind_static_diagnostic"
        if run["counts"]["completed"] == 6
        else "completed_with_failures"
    )
    run["final_disk_bytes"] = _directory_size_bytes(output_root)
    run["updated_at_utc"] = _utc_now()
    run["run_sha256"] = _stable_hash(
        {key: value for key, value in run.items() if key != "run_sha256"}
    )
    _write_json(output_root / "ahoj-geometry-static-pilot-v1.json", run)
    print(
        f"AHoJ static pilot: {run['status']} completed={run['counts']['completed']} "
        f"failed={run['counts']['failed']} resource_blocked={run['counts']['resource_blocked']}"
    )
    print(f"pilot report: {output_root / 'ahoj-geometry-static-pilot-v1.json'}")
    print("evaluator/NMA/external-baseline/ML started: no")
    return run


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--max-disk-bytes", type=int, default=MAX_DISK_BYTES)
    parser.add_argument("--approve-static-pilot", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        run = run_ahoj_static_pilot(
            manifest_path=args.manifest,
            preflight_path=args.preflight,
            output_root=args.output_root,
            max_disk_bytes=args.max_disk_bytes,
            user_approved=args.approve_static_pilot,
        )
    except (AhojStaticPilotError, AhojMetadataResolutionError, OSError, ValueError) as exc:
        print(f"AHoJ static pilot error: {exc}", file=sys.stderr)
        return 2
    return 0 if run["status"] == "completed_target_blind_static_diagnostic" else 2


if __name__ == "__main__":
    raise SystemExit(main())
