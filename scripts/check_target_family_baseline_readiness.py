"""Check bounded target-family external-baseline readiness without running tools.

The checker materializes a target-blind manifest for the already prepared apo
inputs, validates the static/evaluator provenance, and probes Docker/images in
read-only mode.  It never pulls images, starts a container, downloads a
structure, opens evaluator coordinates, or authorizes a scientific claim.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_ri3_external_baseline import BASELINE_CONFIG  # noqa: E402
from scripts.run_target_family_static_pilot import (  # noqa: E402
    validate_pilot_run,
)
from scripts.run_target_family_static_recovery import (  # noqa: E402
    validate_recovery_run,
)
from scripts.evaluate_target_family_static_pilot import (  # noqa: E402
    validate_evaluation_report,
)
from src.target_family_manifest import validate_detector_manifest  # noqa: E402


BASELINE_INPUT_SCHEMA_VERSION = "biovoid-target-family-baseline-input-v1"
READINESS_SCHEMA_VERSION = "biovoid-target-family-baseline-readiness-v1"
DEFAULT_MANIFEST = (
    REPO_ROOT / "data/runtime/target-family/cohort-detector-pfam-v1/"
    "target-family-cohort-detector-pfam-v1.json"
)
DEFAULT_STATIC_RUN = (
    REPO_ROOT / "data/runtime/target-family/static-pilot-pfam-v1-rerun-v2/"
    "target-family-static-pilot-run-v1.json"
)
DEFAULT_RECOVERY_RUN = (
    REPO_ROOT / "data/runtime/target-family/static-pilot-recovery-pfam-v1/"
    "target-family-static-recovery-v1.json"
)
DEFAULT_EVALUATION_REPORT = (
    REPO_ROOT / "data/runtime/target-family/static-evaluation-pfam-v1-rerun-v2/"
    "target-family-static-evaluation-pfam-v1.json"
)
DEFAULT_PREPARED_ROOT = REPO_ROOT / "data/runtime/target-family/static-pilot-pfam-v1-rerun-v2"
DEFAULT_BASELINE_MANIFEST = (
    REPO_ROOT / "data/runtime/target-family/baseline-input-pfam-v1/"
    "target-family-baseline-input-pfam-v1.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "data/runtime/target-family/baseline-readiness-pfam-v1/"
    "target-family-baseline-readiness-pfam-v1.json"
)
TARGET_FAMILY_RUNNER = REPO_ROOT / "scripts/run_target_family_external_baseline.py"
MAX_CASES = 10
MAX_DISK_BYTES = 1_000_000_000
FORBIDDEN_TOKENS = ("holo", "ligand", "evaluator", "ground_truth")


class BaselineReadinessError(RuntimeError):
    """Raised when the bounded baseline contract cannot be inspected safely."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineReadinessError(f"Cannot read JSON runtime file: {path}") from exc
    if not isinstance(payload, dict):
        raise BaselineReadinessError(f"Expected a JSON object: {path}")
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(path: Path, *, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError as exc:
        raise BaselineReadinessError(f"Prepared input escapes repository root: {path}") from exc


def _resolve_prepared_path(raw_path: str, *, repo_root: Path) -> Path:
    path = Path(raw_path)
    resolved = (path if path.is_absolute() else repo_root / path).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise BaselineReadinessError(f"Prepared input escapes repository root: {resolved}") from exc
    if not resolved.is_file():
        raise BaselineReadinessError(f"Prepared apo input is missing: {resolved}")
    return resolved


def _expected_prepared_path(structure_id: str, *, prepared_root: Path) -> Path:
    return prepared_root / "cases" / structure_id.upper() / "preparation" / "prepared_detector.pdb"


def _case_input(
    case: Mapping[str, Any],
    *,
    static_run: Mapping[str, Any],
    recovery_run: Mapping[str, Any],
    repo_root: Path,
    prepared_root: Path,
) -> dict[str, Any]:
    case_id = str(case["case_id"])
    structure_id = str(case["structure_id"]).upper()
    static_cases = static_run.get("cases")
    if not isinstance(static_cases, Mapping):
        raise BaselineReadinessError("Static run cases are missing")
    primary = static_cases.get(case_id)
    if not isinstance(primary, Mapping):
        raise BaselineReadinessError(f"Static run is missing case: {case_id}")

    recovery_structure = str(recovery_run.get("structure_id", "")).upper()
    recovery_result = recovery_run.get("result")
    recovery_result_mapping = recovery_result if isinstance(recovery_result, Mapping) else {}
    recovery_complete = (
        recovery_structure == structure_id
        and recovery_run.get("status") == "completed_secondary_resource_recovery"
        and recovery_result_mapping.get("status") == "completed"
    )
    primary_complete = primary.get("status") == "completed"
    if not primary_complete and not recovery_complete:
        raise BaselineReadinessError(
            f"Case {structure_id} has neither a completed canonical nor recovery input"
        )

    raw_path = primary.get("prepared_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raw_path = _relative_path(
            _expected_prepared_path(structure_id, prepared_root=prepared_root), repo_root=repo_root
        )
    prepared_path = _resolve_prepared_path(raw_path, repo_root=repo_root)
    observed_sha = _sha256_file(prepared_path)
    expected_sha = primary.get("prepared_structure_sha256")
    if not (isinstance(expected_sha, str) and len(expected_sha) == 64):
        expected_sha = (
            recovery_result_mapping.get("prepared_structure_sha256") if recovery_complete else None
        )
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise BaselineReadinessError(f"Prepared input hash is missing: {structure_id}")
    if observed_sha != expected_sha:
        raise BaselineReadinessError(f"Prepared input hash mismatch: {structure_id}")

    return {
        "case_id": case_id,
        "structure_id": structure_id,
        "prepared_path": _relative_path(prepared_path, repo_root=repo_root),
        "prepared_structure_sha256": observed_sha,
    }


def validate_baseline_input_manifest(payload: Mapping[str, Any]) -> None:
    """Validate a target-blind prepared-apo manifest and its hash."""

    if payload.get("schema_version") != BASELINE_INPUT_SCHEMA_VERSION:
        raise ValueError("Unexpected target-family baseline input schema")
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True).casefold()
    for token in FORBIDDEN_TOKENS:
        if token in serialized:
            raise ValueError(f"Baseline input contains forbidden evaluator token: {token}")
    if payload.get("manifest_kind") != "target_blind_external_baseline":
        raise ValueError("Baseline input manifest is not target-blind")
    if payload.get("status") != "ready":
        raise ValueError("Baseline input manifest is not ready")
    if payload.get("boundary") != "prepared_apo_only_v1":
        raise ValueError("Baseline input boundary is not apo-only")
    detector_boundary = payload.get("detector_boundary")
    if (
        not isinstance(detector_boundary, Mapping)
        or detector_boundary.get("target_blind") is not True
    ):
        raise ValueError("Baseline input is not target-blind")
    if detector_boundary.get("target_annotations_present") is not False:
        raise ValueError("Baseline input contains target annotations")
    constraints = payload.get("constraints")
    if not isinstance(constraints, Mapping):
        raise ValueError("Baseline input constraints are missing")
    case_count = constraints.get("case_count")
    if not isinstance(case_count, int) or not 1 <= case_count <= MAX_CASES:
        raise ValueError("Baseline input case count is outside the bounded range")
    if constraints.get("max_case_count") != MAX_CASES or constraints.get("analysis_workers") != 1:
        raise ValueError("Baseline input resource boundary drifted")
    if constraints.get("motion_enabled") is not False:
        raise ValueError("Baseline input unexpectedly enables motion")
    structures = payload.get("structures")
    if not isinstance(structures, list) or len(structures) != case_count:
        raise ValueError("Baseline input structure count does not match constraints")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for structure in structures:
        if not isinstance(structure, Mapping):
            raise ValueError("Baseline input structure is not an object")
        structure_id = str(structure.get("structure_id", "")).upper()
        prepared_path = str(structure.get("prepared_path", ""))
        prepared_sha = structure.get("prepared_structure_sha256")
        if not structure_id or structure_id in seen_ids:
            raise ValueError("Baseline input structure IDs are not unique")
        if not prepared_path or prepared_path in seen_paths or Path(prepared_path).is_absolute():
            raise ValueError("Baseline input prepared paths are invalid")
        if ".." in Path(prepared_path).parts:
            raise ValueError("Baseline input prepared path escapes its root")
        if not isinstance(prepared_sha, str) or len(prepared_sha) != 64:
            raise ValueError("Baseline input prepared hash is invalid")
        seen_ids.add(structure_id)
        seen_paths.add(prepared_path)
    expected_hash = _stable_hash(
        {key: value for key, value in payload.items() if key != "manifest_sha256"}
    )
    if payload.get("manifest_sha256") != expected_hash:
        raise ValueError("Baseline input manifest hash mismatch")


def build_baseline_input_manifest(
    detector_manifest: Mapping[str, Any],
    static_run: Mapping[str, Any],
    recovery_run: Mapping[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
    prepared_root: Path = DEFAULT_PREPARED_ROOT,
    primary_run_file_sha256: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic, prepared-apo-only baseline input manifest."""

    validate_detector_manifest(detector_manifest)
    if static_run.get("manifest_sha256") != detector_manifest.get("manifest_sha256"):
        raise BaselineReadinessError("Static run is not bound to the detector manifest")
    if recovery_run:
        if recovery_run.get("manifest_sha256") != detector_manifest.get("manifest_sha256"):
            raise BaselineReadinessError("Recovery run is not bound to the detector manifest")
        expected_primary_hash = primary_run_file_sha256 or str(static_run.get("run_sha256", ""))
        if recovery_run.get("primary_run_sha256") != expected_primary_hash:
            raise BaselineReadinessError("Recovery run is not bound to the static run")
    cases = detector_manifest.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise BaselineReadinessError("Detector manifest is outside the bounded baseline range")
    structures: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, Mapping):
            raise BaselineReadinessError("Detector manifest case is not an object")
        item = _case_input(
            case,
            static_run=static_run,
            recovery_run=recovery_run,
            repo_root=repo_root,
            prepared_root=prepared_root,
        )
        structures.append(item)
    payload: dict[str, Any] = {
        "schema_version": BASELINE_INPUT_SCHEMA_VERSION,
        "manifest_kind": "target_blind_external_baseline",
        "status": "ready",
        "family_id": str(detector_manifest["family_id"]),
        "source_detector_manifest_sha256": detector_manifest["manifest_sha256"],
        "source_static_run_sha256": static_run.get("run_sha256"),
        "source_recovery_run_sha256": recovery_run.get("run_sha256"),
        "boundary": "prepared_apo_only_v1",
        "detector_boundary": {
            "target_blind": True,
            "target_annotations_present": False,
            "motion_enabled": False,
            "external_tools_receive_prepared_apo_only": True,
        },
        "constraints": {
            "case_count": len(structures),
            "max_case_count": MAX_CASES,
            "analysis_workers": 1,
            "motion_enabled": False,
            "max_disk_bytes": MAX_DISK_BYTES,
        },
        "structures": structures,
        "manifest_sha256": None,
    }
    payload["manifest_sha256"] = _stable_hash(
        {key: value for key, value in payload.items() if key != "manifest_sha256"}
    )
    validate_baseline_input_manifest(payload)
    return payload


def _docker_probe(images: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Probe Docker and pinned images without pull/build/run side effects."""

    executable = shutil.which("docker")
    result: dict[str, Any] = {
        "executable_found": executable is not None,
        "daemon_status": "not_checked",
        "images": {},
        "side_effects": {"pull": False, "build": False, "run": False},
    }
    if executable is None:
        result["daemon_status"] = "executable_missing"
        return result
    try:
        daemon = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["daemon_status"] = "daemon_probe_failed"
        result["daemon_error"] = type(exc).__name__
        return result
    if daemon.returncode != 0 or not daemon.stdout.strip():
        result["daemon_status"] = "daemon_unavailable"
        result["daemon_error"] = (daemon.stderr or daemon.stdout)[-500:].strip()
        return result
    result["daemon_status"] = "available"
    for name, config in images.items():
        image = str(config["image"])
        try:
            inspected = subprocess.run(
                ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["images"][name] = {"status": "probe_failed", "error": type(exc).__name__}
            continue
        result["images"][name] = (
            {"status": "available", "image": image, "image_id": inspected.stdout.strip()}
            if inspected.returncode == 0 and inspected.stdout.strip()
            else {"status": "missing", "image": image, "error": inspected.stderr[-500:].strip()}
        )
    return result


def _resource_check(*, repo_root: Path, case_count: int) -> dict[str, Any]:
    usage = shutil.disk_usage(repo_root)
    return {
        "status": "pass" if usage.free >= MAX_DISK_BYTES else "blocked_low_disk",
        "workers": 1,
        "max_cases": MAX_CASES,
        "selected_cases": case_count,
        "per_tool_memory": {name: config["memory"] for name, config in BASELINE_CONFIG.items()},
        "timeouts_seconds": {
            name: config["timeout_seconds"] for name, config in BASELINE_CONFIG.items()
        },
        "max_disk_bytes": MAX_DISK_BYTES,
        "free_bytes": usage.free,
    }


def build_readiness_report(
    detector_manifest: Mapping[str, Any],
    static_run: Mapping[str, Any],
    recovery_run: Mapping[str, Any],
    evaluation_report: Mapping[str, Any],
    *,
    docker_probe: Mapping[str, Any],
    repo_root: Path = REPO_ROOT,
    prepared_root: Path = DEFAULT_PREPARED_ROOT,
    primary_run_file_sha256: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the readiness report and target-blind baseline input manifest."""

    validate_detector_manifest(detector_manifest)
    validate_pilot_run(static_run, detector_manifest)
    recovery_contract = "not_required"
    if recovery_run:
        validate_recovery_run(recovery_run)
        if recovery_run.get("manifest_sha256") != detector_manifest.get("manifest_sha256"):
            raise BaselineReadinessError("Recovery manifest hash does not match detector manifest")
        recovery_contract = "pass"
    validate_evaluation_report(evaluation_report, detector_manifest)
    baseline_manifest = build_baseline_input_manifest(
        detector_manifest,
        static_run,
        recovery_run,
        repo_root=repo_root,
        prepared_root=prepared_root,
        primary_run_file_sha256=primary_run_file_sha256,
    )
    structures = baseline_manifest["structures"]
    policy_status = (
        "review_required"
        if evaluation_report.get("interpretation_status") == "pending_independent_review"
        else "review_recorded"
    )
    images = docker_probe.get("images", {})
    tools_available = (
        docker_probe.get("daemon_status") == "available"
        and all(item.get("status") == "available" for item in images.values())
        and set(images) == set(BASELINE_CONFIG)
    )
    resources = _resource_check(repo_root=repo_root, case_count=len(structures))
    hard_checks_pass = resources["status"] == "pass"
    runner_adapter_required = not TARGET_FAMILY_RUNNER.is_file()
    if not hard_checks_pass:
        status = "blocked_resource_budget"
    elif runner_adapter_required:
        status = "blocked_runner_adapter"
    elif not tools_available:
        status = "blocked_review_and_tooling"
    else:
        status = "ready_for_explicit_user_approval"
    report: dict[str, Any] = {
        "schema_version": READINESS_SCHEMA_VERSION,
        "status": status,
        "created_at_utc": _utc_now(),
        "current_gate": "G2-bounded-static-development-pilot",
        "target_family": detector_manifest["family_id"],
        "manifest_sha256": detector_manifest["manifest_sha256"],
        "baseline_input_manifest_sha256": baseline_manifest["manifest_sha256"],
        "checks": {
            "static_run_contract": "pass",
            "recovery_run_contract": recovery_contract,
            "evaluator_contract": "pass",
            "prepared_apo_inputs": "pass",
            "representative_chain_policy": policy_status,
            "resource_budget": resources["status"],
            "docker_images": "pass" if tools_available else "blocked",
            "runner_adapter": "blocked" if runner_adapter_required else "pass",
        },
        "docker_probe": dict(docker_probe),
        "resource_budget": resources,
        "baseline_tools": {
            name: {
                "version": config["version"],
                "commit": config["commit"],
                "image": config["image"],
                "memory": config["memory"],
                "timeout_seconds": config["timeout_seconds"],
            }
            for name, config in BASELINE_CONFIG.items()
        },
        "execution_boundary": {
            "target_blind": True,
            "workers": 1,
            "case_count": len(structures),
            "motion_enabled": False,
            "nma_started": False,
            "ml_training_started": False,
            "container_execution_started": False,
            "target_family_runner_adapter_required": runner_adapter_required,
            "ri3_runner_case_lock": 663,
            "user_approval_required": True,
            "claims_authorized": False,
        },
        "roadmap": {
            "current_gate": "G2-bounded-static-development-pilot",
            "purpose": "Prepare a reproducible, independent fpocket/P2Rank comparison without executing it.",
            "next_step": (
                "Record the representative-chain policy review and keep the bounded target-family result diagnostic-only; "
                "the target-family adapter is available, while the existing RI-3 runner remains locked to 663 cases."
            ),
            "status": "readiness_only_no_baseline_started",
        },
    }
    return report, baseline_manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--recovery-run", type=Path, default=DEFAULT_RECOVERY_RUN)
    parser.add_argument("--evaluation-report", type=Path, default=DEFAULT_EVALUATION_REPORT)
    parser.add_argument("--prepared-root", type=Path, default=DEFAULT_PREPARED_ROOT)
    parser.add_argument("--baseline-manifest", type=Path, default=DEFAULT_BASELINE_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    paths = {
        key: (value if value.is_absolute() else REPO_ROOT / value)
        for key, value in vars(args).items()
        if isinstance(value, Path)
    }
    manifest = _read_json(paths["manifest"])
    static_run = _read_json(paths["static_run"])
    recovery_run = _read_json(paths["recovery_run"]) if paths["recovery_run"].is_file() else {}
    evaluation_report = _read_json(paths["evaluation_report"])
    probe = _docker_probe(BASELINE_CONFIG)
    try:
        report, baseline_manifest = build_readiness_report(
            manifest,
            static_run,
            recovery_run,
            evaluation_report,
            docker_probe=probe,
            repo_root=REPO_ROOT,
            prepared_root=paths["prepared_root"],
            primary_run_file_sha256=_sha256_file(paths["static_run"]),
        )
    except (BaselineReadinessError, ValueError, KeyError) as exc:
        print(f"target-family baseline readiness: BLOCKED: {exc}", file=sys.stderr)
        return 2
    _write_json_atomic(paths["baseline_manifest"], baseline_manifest)
    _write_json_atomic(paths["output"], report)
    print(f"target-family baseline readiness: {report['status']}")
    print(f"baseline input manifest: {paths['baseline_manifest']}")
    print(f"readiness report: {paths['output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
