"""Run a bounded, target-blind CryptoBench static pilot.

This pilot is deliberately separate from the full RI-3 development runner.
It consumes only the redacted RI-2 manifest and a bounded local preparation
report, runs the canonical BioVoid static detector one structure at a time,
and never computes DCC/DCA, reads evaluator coordinates, opens the sealed
split, runs NMA, or invokes external baselines.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.benchmark_v1 import phase6_frozen_protocol_v1  # noqa: E402


PILOT_MANIFEST_SCHEMA_VERSION = "biovoid-ri3-target-blind-static-pilot-manifest-v1"
PILOT_RUN_SCHEMA_VERSION = "biovoid-ri3-target-blind-static-pilot-run-v1"
MAX_PILOT_STRUCTURES = 10
FORBIDDEN_TOKENS = (
    "evaluator",
    "ground_truth",
    "holo",
    "ligand",
    "target_center",
    "target_residues",
    "hit_label",
)


class PilotRunError(RuntimeError):
    """Raised when the bounded static pilot contract cannot proceed."""


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _content_hash(payload: Mapping[str, Any], field: str) -> str:
    return _stable_hash({key: value for key, value in payload.items() if key != field})


def _required_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise PilotRunError(f"Missing mapping: {key}")
    return value


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PilotRunError(f"Missing text field: {key}")
    return value.strip()


def _normalize_structure_id(value: Any) -> str:
    text = str(value).strip().upper()
    if len(text) != 4 or not text.isalnum():
        raise PilotRunError(f"Invalid structure ID: {value!r}")
    return text


def _forbidden_paths(value: Any, path: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            allowed_boundary_key = normalized == "evaluator_fields_in_manifest"
            if not allowed_boundary_key and any(token in normalized for token in FORBIDDEN_TOKENS):
                paths.append(f"{path}.{key}")
            paths.extend(_forbidden_paths(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_forbidden_paths(child, f"{path}[{index}]"))
    return paths


def build_pilot_manifest(
    *,
    ri2_manifest: Mapping[str, Any],
    preparation_report: Mapping[str, Any],
    max_structures: int = MAX_PILOT_STRUCTURES,
) -> dict[str, Any]:
    """Build a deterministic target-blind manifest for at most ten structures."""

    if not isinstance(max_structures, int) or not 1 <= max_structures <= MAX_PILOT_STRUCTURES:
        raise PilotRunError("Pilot scope must contain at most 10 structures")
    if ri2_manifest.get("schema_version") != "biovoid-ri2-development-manifest-v1":
        raise PilotRunError("Unexpected RI-2 manifest schema")
    if preparation_report.get("schema_version") != "biovoid-ri3-preparation-preflight-v1":
        raise PilotRunError("Unexpected preparation report schema")
    if preparation_report.get("status") != "pass":
        raise PilotRunError("Preparation report is not pass")

    snapshot = _required_mapping(ri2_manifest, "snapshot")
    dataset_id = _required_text(snapshot, "dataset_id")
    snapshot_id = _required_text(snapshot, "snapshot_id")
    raw_records = preparation_report.get("records")
    if not isinstance(raw_records, list) or not raw_records:
        raise PilotRunError("Preparation report has no records")

    records_by_id: dict[str, Mapping[str, Any]] = {}
    for raw_record in raw_records:
        if not isinstance(raw_record, Mapping):
            raise PilotRunError("Preparation record is not an object")
        structure_id = _normalize_structure_id(raw_record.get("structure_id"))
        if structure_id in records_by_id:
            raise PilotRunError(f"Duplicate preparation record: {structure_id}")
        if raw_record.get("status") != "eligible":
            raise PilotRunError(f"Preparation record is not eligible: {structure_id}")
        records_by_id[structure_id] = raw_record

    selected_ids = tuple(sorted(records_by_id)[:max_structures])
    if not selected_ids:
        raise PilotRunError("No structures selected for pilot")
    raw_cases = ri2_manifest.get("cases")
    if not isinstance(raw_cases, list):
        raise PilotRunError("RI-2 manifest has no case list")
    selected_set = set(selected_ids)
    cases: list[dict[str, str]] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, Mapping):
            raise PilotRunError("RI-2 case is not an object")
        structure_id = _normalize_structure_id(raw_case.get("structure_id"))
        if structure_id not in selected_set:
            continue
        if raw_case.get("split") != "development":
            raise PilotRunError(f"Pilot case is outside development split: {structure_id}")
        case = {
            "case_id": _required_text(raw_case, "case_id"),
            "structure_id": structure_id,
            "family_id": _required_text(raw_case, "family_id"),
            "split": "development",
            "dataset_snapshot_id": _required_text(raw_case, "dataset_snapshot_id"),
        }
        if case["dataset_snapshot_id"] != snapshot_id:
            raise PilotRunError(f"Case snapshot differs from lock: {case['case_id']}")
        cases.append(case)
    cases.sort(key=lambda case: case["case_id"])
    if not cases:
        raise PilotRunError("Selected structures have no RI-2 case records")
    if {case["structure_id"] for case in cases} != selected_set:
        raise PilotRunError("At least one selected structure has no case record")
    if len({case["case_id"] for case in cases}) != len(cases):
        raise PilotRunError("Pilot case IDs are not unique")

    structures: list[dict[str, Any]] = []
    for structure_id in selected_ids:
        raw_record = records_by_id[structure_id]
        preparation = _required_mapping(raw_record, "preparation")
        if preparation.get("status") != "eligible":
            raise PilotRunError(f"Preparation is not eligible: {structure_id}")
        structures.append(
            {
                "structure_id": structure_id,
                "prepared_path": _required_text(preparation, "prepared_path"),
                "prepared_structure_sha256": _required_text(preparation, "prepared_sha256"),
                "preparation_config_sha256": _required_text(
                    preparation, "preparation_config_sha256"
                ),
                "preparation_report_sha256": _required_text(
                    preparation, "preparation_report_sha256"
                ),
                "protein_atom_count": int(preparation["protein_atom_count"]),
                "protein_residue_count": int(preparation["protein_residue_count"]),
                "warnings": list(preparation.get("warnings", [])),
            }
        )

    payload: dict[str, Any] = {
        "schema_version": PILOT_MANIFEST_SCHEMA_VERSION,
        "manifest_kind": "metadata_only_target_blind_static_pilot",
        "materialization_status": "prepared_local_only",
        "dataset_id": dataset_id,
        "snapshot_id": snapshot_id,
        "split": "development",
        "protocol": phase6_frozen_protocol_v1().to_manifest(),
        "scope": {
            "selection_rule": "lexicographically_first_eligible_prepared_structures",
            "max_structures": max_structures,
            "structure_ids": list(selected_ids),
            "structure_ids_sha256": _stable_hash(list(selected_ids)),
        },
        "structures": structures,
        "cases": cases,
        "structure_count": len(structures),
        "case_count": len(cases),
        "detector_boundary": {
            "target_blind": True,
            "evaluator_fields_in_manifest": False,
            "detector_receives": [
                "structure_id",
                "prepared_structure_sha256",
                "preparation_config_sha256",
                "prepared_full_atom_structure_path",
            ],
        },
        "manifest_sha256": None,
    }
    payload["manifest_sha256"] = _content_hash(payload, "manifest_sha256")
    validate_pilot_manifest(payload)
    return payload


def validate_pilot_manifest(payload: Mapping[str, Any]) -> None:
    """Validate pilot bounds, hash integrity, and detector redaction."""

    if payload.get("schema_version") != PILOT_MANIFEST_SCHEMA_VERSION:
        raise PilotRunError("Unexpected pilot manifest schema")
    if payload.get("manifest_kind") != "metadata_only_target_blind_static_pilot":
        raise PilotRunError("Unexpected pilot manifest kind")
    if payload.get("materialization_status") != "prepared_local_only":
        raise PilotRunError("Pilot manifest materialization status is unsafe")
    forbidden = _forbidden_paths(payload)
    if forbidden:
        raise PilotRunError("Pilot manifest contains forbidden fields: " + ", ".join(forbidden[:3]))
    if payload.get("manifest_sha256") != _content_hash(payload, "manifest_sha256"):
        raise PilotRunError("Pilot manifest hash does not match its content")
    scope = _required_mapping(payload, "scope")
    max_structures = scope.get("max_structures")
    structure_ids = scope.get("structure_ids")
    if not isinstance(max_structures, int) or not 1 <= max_structures <= MAX_PILOT_STRUCTURES:
        raise PilotRunError("Pilot scope must contain at most 10 structures")
    if not isinstance(structure_ids, list) or len(structure_ids) > max_structures:
        raise PilotRunError("Pilot manifest exceeds its bounded structure scope")
    normalized_ids = [_normalize_structure_id(value) for value in structure_ids]
    if normalized_ids != sorted(set(normalized_ids)):
        raise PilotRunError("Pilot structure IDs are not deterministic and unique")
    if scope.get("structure_ids_sha256") != _stable_hash(normalized_ids):
        raise PilotRunError("Pilot structure selection hash mismatch")
    structures = payload.get("structures")
    cases = payload.get("cases")
    if not isinstance(structures, list) or len(structures) != len(normalized_ids):
        raise PilotRunError("Pilot structure coverage does not match scope")
    if not isinstance(cases, list) or not cases:
        raise PilotRunError("Pilot case list is empty")
    if payload.get("structure_count") != len(structures) or payload.get("case_count") != len(cases):
        raise PilotRunError("Pilot coverage counts do not match payload")
    structure_keys: set[str] = set()
    for structure in structures:
        if not isinstance(structure, Mapping):
            raise PilotRunError("Pilot structure record is not an object")
        structure_id = _normalize_structure_id(structure.get("structure_id"))
        structure_keys.add(structure_id)
        for key in (
            "prepared_path",
            "prepared_structure_sha256",
            "preparation_config_sha256",
            "preparation_report_sha256",
        ):
            _required_text(structure, key)
    if structure_keys != set(normalized_ids):
        raise PilotRunError("Pilot structure IDs differ from scope")
    case_keys: set[str] = set()
    case_structures: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping):
            raise PilotRunError("Pilot case record is not an object")
        case_keys.add(_required_text(case, "case_id"))
        case_structures.add(_normalize_structure_id(case.get("structure_id")))
        if case.get("split") != "development":
            raise PilotRunError("Pilot case is outside development split")
    if len(case_keys) != len(cases) or case_structures != structure_keys:
        raise PilotRunError("Pilot case coverage is inconsistent")
    boundary = _required_mapping(payload, "detector_boundary")
    if boundary.get("target_blind") is not True:
        raise PilotRunError("Pilot detector boundary is not target-blind")
    if boundary.get("evaluator_fields_in_manifest") is not False:
        raise PilotRunError("Pilot detector boundary exposes evaluator fields")
    protocol = _required_mapping(payload, "protocol")
    if protocol != phase6_frozen_protocol_v1().to_manifest():
        raise PilotRunError("Pilot protocol differs from frozen runtime protocol")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _seal_run(payload: dict[str, Any]) -> None:
    payload["updated_at_utc"] = _utc_now()
    payload["run_sha256"] = _content_hash(payload, "run_sha256")


def build_pilot_run_skeleton(
    manifest: Mapping[str, Any],
    *,
    git_commit: str,
) -> dict[str, Any]:
    """Build the closed-control pilot run record before detector execution."""

    validate_pilot_manifest(manifest)
    if not isinstance(git_commit, str) or len(git_commit) != 40:
        raise PilotRunError("Pilot run requires a 40-character git commit")
    payload: dict[str, Any] = {
        "schema_version": PILOT_RUN_SCHEMA_VERSION,
        "status": "not_started",
        "manifest_sha256": manifest["manifest_sha256"],
        "git_commit": git_commit,
        "scope": manifest["scope"],
        "execution": {
            "resource_profile": "safe-16gb",
            "workers": 1,
            "max_structures": manifest["scope"]["max_structures"],
            "motion_enabled": False,
            "nma_started": False,
            "external_baselines_enabled": False,
            "sealed_evaluation_authorized": False,
        },
        "detector": {
            "name": "biovoid_static",
            "version": "canonical-static-v1",
            "ranking_contract": "canonical-static-v1-volume-descending",
            "score_used": False,
        },
        "evaluation": {
            "status": "deferred_missing_holo_coordinates",
            "dcc_dca_computed": False,
            "scientific_superiority_claim_authorized": False,
        },
        "claim_boundary": "unvalidated_target_blind_static_pilot",
        "records": {},
        "counts": {"completed": 0, "resource_blocked": 0, "failed": 0},
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "run_sha256": None,
    }
    payload["run_sha256"] = _content_hash(payload, "run_sha256")
    validate_pilot_run(payload, manifest)
    return payload


def validate_pilot_run(payload: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    """Validate pilot execution controls and detector-owned output redaction."""

    validate_pilot_manifest(manifest)
    if payload.get("schema_version") != PILOT_RUN_SCHEMA_VERSION:
        raise PilotRunError("Unexpected pilot run schema")
    if payload.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise PilotRunError("Pilot run is not bound to its manifest")
    if payload.get("run_sha256") != _content_hash(payload, "run_sha256"):
        raise PilotRunError("Pilot run hash does not match its content")
    if payload.get("status") not in {
        "not_started",
        "running",
        "partial",
        "complete",
        "complete_with_resource_blocks",
        "complete_with_failures",
    }:
        raise PilotRunError("Unexpected pilot run status")
    execution = _required_mapping(payload, "execution")
    if execution.get("resource_profile") != "safe-16gb" or execution.get("workers") != 1:
        raise PilotRunError("Pilot execution is outside safe-16gb single-worker policy")
    if execution.get("max_structures") != manifest["scope"]["max_structures"]:
        raise PilotRunError("Pilot execution bound differs from manifest scope")
    for key in ("motion_enabled", "nma_started", "external_baselines_enabled", "sealed_evaluation_authorized"):
        if execution.get(key) is not False:
            raise PilotRunError(f"Pilot execution control is open: {key}")
    if payload.get("claim_boundary") != "unvalidated_target_blind_static_pilot":
        raise PilotRunError("Pilot claim boundary is unsafe")
    evaluation = _required_mapping(payload, "evaluation")
    if evaluation.get("dcc_dca_computed") is not False:
        raise PilotRunError("Pilot unexpectedly computed DCC/DCA")
    records = payload.get("records")
    if not isinstance(records, Mapping):
        raise PilotRunError("Pilot records are missing")
    expected_ids = set(manifest["scope"]["structure_ids"])
    if not set(records).issubset(expected_ids):
        raise PilotRunError("Pilot record IDs differ from manifest scope")
    counts = {"completed": 0, "resource_blocked": 0, "failed": 0}
    from src.evaluator_format import assert_detector_payload_is_blind  # noqa: PLC0415

    for structure_id, record in records.items():
        if not isinstance(record, Mapping):
            raise PilotRunError(f"Pilot record is not an object: {structure_id}")
        status = record.get("status")
        if status not in counts:
            raise PilotRunError(f"Unexpected pilot record status: {structure_id}")
        counts[status] += 1
        detector_record = record.get("detector_record")
        if not isinstance(detector_record, Mapping):
            raise PilotRunError(f"Detector record is missing: {structure_id}")
        try:
            assert_detector_payload_is_blind(detector_record, path=f"records.{structure_id}")
        except ValueError as exc:
            raise PilotRunError(str(exc)) from exc
        expected_detector_status = {
            "completed": "completed",
            "resource_blocked": "unavailable",
            "failed": "failed",
        }[status]
        if detector_record.get("status") != expected_detector_status:
            raise PilotRunError(f"Detector status mismatch: {structure_id}")
        if record.get("nma_started") is not False or record.get("sealed_evaluation_authorized") is not False:
            raise PilotRunError(f"Pilot record control is open: {structure_id}")
    if payload.get("counts") != counts:
        raise PilotRunError("Pilot counts do not match records")
    if payload.get("status") in {
        "complete",
        "complete_with_resource_blocks",
        "complete_with_failures",
    } and set(records) != expected_ids:
        raise PilotRunError("Complete pilot is missing structure records")


DEFAULT_RI2_MANIFEST = REPO_ROOT / "data/runtime/ri2/cryptobench-development-manifest-v1.json"
DEFAULT_PREPARATION_REPORT = (
    REPO_ROOT / "data/runtime/ri3/cryptobench-preparation-pilot10-v1.json"
)
DEFAULT_MANIFEST = REPO_ROOT / "data/runtime/ri3/cryptobench-static-pilot-manifest-v1.json"
DEFAULT_RUN = REPO_ROOT / "data/runtime/ri3/cryptobench-static-pilot-run-v1.json"


def _resolve_repo_path(value: Path) -> Path:
    candidate = value if value.is_absolute() else REPO_ROOT / value
    return candidate.resolve()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PilotRunError(f"Required pilot input is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PilotRunError(f"Expected JSON object: {path}")
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PilotRunError("Unable to identify local git commit") from exc
    return result.stdout.strip()


def _record_counts(payload: Mapping[str, Any]) -> dict[str, int]:
    counts = {"completed": 0, "resource_blocked": 0, "failed": 0}
    records = payload.get("records", {})
    if isinstance(records, Mapping):
        for record in records.values():
            if isinstance(record, Mapping) and record.get("status") in counts:
                counts[str(record["status"])] += 1
    return counts


def _final_pilot_status(*, processed: int, expected: int, counts: Mapping[str, int]) -> str:
    if processed != expected:
        return "partial"
    if counts.get("failed", 0):
        return "complete_with_failures"
    if counts.get("resource_blocked", 0):
        return "complete_with_resource_blocks"
    return "complete"


def run_static_pilot(
    *,
    ri2_manifest_path: Path = DEFAULT_RI2_MANIFEST,
    preparation_report_path: Path = DEFAULT_PREPARATION_REPORT,
    manifest_path: Path = DEFAULT_MANIFEST,
    run_path: Path = DEFAULT_RUN,
    max_structures: int = MAX_PILOT_STRUCTURES,
    rebuild_manifest: bool = False,
) -> dict[str, Any]:
    """Run the local bounded static pilot without any network access."""

    ri2_manifest_path = _resolve_repo_path(ri2_manifest_path)
    preparation_report_path = _resolve_repo_path(preparation_report_path)
    manifest_path = _resolve_repo_path(manifest_path)
    run_path = _resolve_repo_path(run_path)
    if rebuild_manifest or not manifest_path.is_file():
        manifest = build_pilot_manifest(
            ri2_manifest=_read_json(ri2_manifest_path),
            preparation_report=_read_json(preparation_report_path),
            max_structures=max_structures,
        )
        _write_json_atomic(manifest_path, manifest)
    else:
        manifest = _read_json(manifest_path)
    validate_pilot_manifest(manifest)
    if int(manifest["scope"]["max_structures"]) != max_structures:
        raise PilotRunError("Existing pilot manifest bound differs from requested max_structures")

    if run_path.is_file():
        run = _read_json(run_path)
        validate_pilot_run(run, manifest)
        if run.get("status") == "complete" and not any(
            run.get("counts", {}).get(key, 0) for key in ("resource_blocked", "failed")
        ):
            return run
        if run.get("status") in {
            "complete",
            "complete_with_resource_blocks",
            "complete_with_failures",
        }:
            run["records"] = {
                structure_id: record
                for structure_id, record in run.get("records", {}).items()
                if record.get("status") == "completed"
            }
            run["counts"] = _record_counts(run)
    else:
        run = build_pilot_run_skeleton(manifest, git_commit=_git_commit())
    run["status"] = "running"
    run["git_commit"] = _git_commit()
    _seal_run(run)
    _write_json_atomic(run_path, run)

    from scripts.run_ri3_static_development import _run_record  # noqa: PLC0415
    from src.static_detector import static_detector_config_sha256  # noqa: PLC0415

    detector_config_sha256 = static_detector_config_sha256()
    structures = {item["structure_id"]: item for item in manifest["structures"]}
    for index, structure_id in enumerate(sorted(structures), start=1):
        if structure_id in run["records"]:
            continue
        print(f"[{index}/{len(structures)}] {structure_id}: static detector", flush=True)
        run["records"][structure_id] = _run_record(
            structures[structure_id],
            detector_config_sha256=detector_config_sha256,
        )
        run["counts"] = _record_counts(run)
        _seal_run(run)
        _write_json_atomic(run_path, run)
        print(
            "checkpoint "
            f"completed={run['counts']['completed']} "
            f"resource_blocked={run['counts']['resource_blocked']} "
            f"failed={run['counts']['failed']}",
            flush=True,
        )

    run["counts"] = _record_counts(run)
    run["status"] = _final_pilot_status(
        processed=len(run["records"]),
        expected=len(structures),
        counts=run["counts"],
    )
    _seal_run(run)
    validate_pilot_run(run, manifest)
    _write_json_atomic(run_path, run)
    print(
        f"RI-3 static pilot: {run['status']} "
        f"processed={len(run['records'])}/{len(structures)} "
        f"completed={run['counts']['completed']} "
        f"resource_blocked={run['counts']['resource_blocked']} "
        f"failed={run['counts']['failed']}"
    )
    print(f"pilot manifest: {manifest_path}")
    print(f"pilot run: {run_path}")
    print("DCC/DCA: deferred; holo coordinates are outside the detector boundary")
    print("NMA/sealed/external baselines: closed")
    return run


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ri2-manifest", type=Path, default=DEFAULT_RI2_MANIFEST)
    parser.add_argument("--preparation-report", type=Path, default=DEFAULT_PREPARATION_REPORT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--max-structures", type=int, default=MAX_PILOT_STRUCTURES)
    parser.add_argument("--rebuild-manifest", action="store_true")
    args = parser.parse_args()
    try:
        run = run_static_pilot(
            ri2_manifest_path=args.ri2_manifest,
            preparation_report_path=args.preparation_report,
            manifest_path=args.manifest,
            run_path=args.run,
            max_structures=args.max_structures,
            rebuild_manifest=args.rebuild_manifest,
        )
    except PilotRunError as exc:
        print(f"RI-3 static pilot error: {exc}", file=sys.stderr)
        return 2
    return 0 if run["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
