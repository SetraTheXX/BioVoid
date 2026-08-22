"""Run a separately labelled, RSS-guarded recovery arm for a blocked case.

The canonical target-family pilot remains bound to ``SAFE_16GB``.  This module
only retries a case that the canonical run recorded as ``resource_blocked``.
The detector still receives the same prepared apo structure and uses the same
``canonical-static-v1`` algorithm, but the resource profile and evidence class
are recorded as a non-canonical secondary recovery result.  One subprocess,
an operating-system RSS guard and a 10 GB disk quota keep the arm bounded.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_target_family_static_pilot import (  # noqa: E402
    DiskQuotaExceeded,
    directory_size_bytes,
    enforce_disk_quota,
)
from src.resources import (  # noqa: E402
    RI3_STATIC_RECOVERY,
    ResourceLimitError,
    get_process_memory_snapshot,
)
from src.static_detector import detect_static_pockets  # noqa: E402
from src.target_family_manifest import validate_detector_manifest  # noqa: E402


DEFAULT_MANIFEST = (
    REPO_ROOT / "data/runtime/target-family/cohort-detector-pfam-v1/"
    "target-family-cohort-detector-pfam-v1.json"
)
DEFAULT_PRIMARY_RUN = (
    REPO_ROOT / "data/runtime/target-family/static-pilot-pfam-v1-rerun-v2/"
    "target-family-static-pilot-run-v1.json"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/runtime/target-family/static-pilot-recovery-pfam-v1"
RECOVERY_MAX_DISK_BYTES = 10_000_000_000
RECOVERY_RSS_LIMIT_BYTES = 3 * 1024**3
RECOVERY_TIMEOUT_SECONDS = 180
RECOVERY_RUN_SCHEMA_VERSION = "biovoid-target-family-static-recovery-v1"
FORBIDDEN_OUTPUT_TOKENS = ("holo", "ligand", "evaluator", "ground_truth")


class RecoveryContractError(RuntimeError):
    """Raised when the secondary recovery contract is not satisfied."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RecoveryContractError(f"Required local file is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RecoveryContractError(f"Expected a JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _profile_sha256() -> str:
    return _stable_hash(asdict(RI3_STATIC_RECOVERY))


def _seal(payload: dict[str, Any]) -> None:
    payload["updated_at_utc"] = _utc_now()
    payload["run_sha256"] = _stable_hash(
        {key: value for key, value in payload.items() if key != "run_sha256"}
    )


def build_recovery_run_skeleton(
    *,
    manifest_sha256: str,
    primary_run_sha256: str,
    structure_id: str,
    max_disk_bytes: int = RECOVERY_MAX_DISK_BYTES,
    rss_limit_bytes: int = RECOVERY_RSS_LIMIT_BYTES,
) -> dict[str, Any]:
    """Build the separately labelled recovery evidence record."""

    if len(manifest_sha256) != 64 or len(primary_run_sha256) != 64:
        raise ValueError("manifest and primary run hashes must be SHA-256 values")
    if max_disk_bytes < 1 or max_disk_bytes > RECOVERY_MAX_DISK_BYTES:
        raise ValueError(f"max_disk_bytes must be between 1 and {RECOVERY_MAX_DISK_BYTES}")
    if rss_limit_bytes < 1 or rss_limit_bytes > RECOVERY_RSS_LIMIT_BYTES:
        raise ValueError(f"rss_limit_bytes must be between 1 and {RECOVERY_RSS_LIMIT_BYTES}")
    normalized_structure_id = str(structure_id).strip().upper()
    if len(normalized_structure_id) != 4 or not normalized_structure_id.isalnum():
        raise ValueError("structure_id must be a four-character PDB ID")
    payload: dict[str, Any] = {
        "schema_version": RECOVERY_RUN_SCHEMA_VERSION,
        "status": "not_started",
        "manifest_sha256": manifest_sha256,
        "primary_run_sha256": primary_run_sha256,
        "structure_id": normalized_structure_id,
        "execution": {
            "profile": RI3_STATIC_RECOVERY.name,
            "profile_sha256": _profile_sha256(),
            "workers": 1,
            "motion_enabled": False,
            "external_baselines_enabled": False,
            "canonical_static_result": False,
            "rss_limit_bytes": rss_limit_bytes,
            "max_disk_bytes": max_disk_bytes,
            "timeout_seconds": RECOVERY_TIMEOUT_SECONDS,
            "coordinate_files_downloaded": False,
        },
        "detector": {
            "version": "canonical-static-v1",
            "ranking_contract": "canonical-static-v1-volume-descending",
            "score_used": False,
        },
        "interpretation_status": "pending_independent_review",
        "claim_boundary": "secondary_resource_recovery_only",
        "result": None,
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
    }
    _seal(payload)
    return payload


def validate_recovery_run(payload: Mapping[str, Any]) -> None:
    """Validate the recovery record's resource and scientific boundaries."""

    if payload.get("schema_version") != RECOVERY_RUN_SCHEMA_VERSION:
        raise RecoveryContractError("Unexpected recovery run schema")
    execution = payload.get("execution")
    if not isinstance(execution, Mapping):
        raise RecoveryContractError("Recovery run is missing execution controls")
    if execution.get("profile") != RI3_STATIC_RECOVERY.name:
        raise RecoveryContractError("Recovery run has an unexpected resource profile")
    if execution.get("workers") != 1 or execution.get("motion_enabled") is not False:
        raise RecoveryContractError("Recovery run violates the single-worker static boundary")
    if execution.get("external_baselines_enabled") is not False:
        raise RecoveryContractError("Recovery run unexpectedly enables external baselines")
    if execution.get("canonical_static_result") is not False:
        raise RecoveryContractError("Recovery output cannot be promoted to canonical evidence")
    if execution.get("coordinate_files_downloaded") is not False:
        raise RecoveryContractError("Recovery arm must reuse existing prepared coordinates")
    rss_limit = execution.get("rss_limit_bytes")
    disk_limit = execution.get("max_disk_bytes")
    if not isinstance(rss_limit, int) or not 1 <= rss_limit <= RECOVERY_RSS_LIMIT_BYTES:
        raise RecoveryContractError("Recovery RSS limit is outside the bounded range")
    if not isinstance(disk_limit, int) or not 1 <= disk_limit <= RECOVERY_MAX_DISK_BYTES:
        raise RecoveryContractError("Recovery disk limit is outside the bounded range")
    if payload.get("claim_boundary") != "secondary_resource_recovery_only":
        raise RecoveryContractError("Recovery claim boundary is unsafe")
    expected_hash = _stable_hash(
        {key: value for key, value in payload.items() if key != "run_sha256"}
    )
    if payload.get("run_sha256") != expected_hash:
        raise RecoveryContractError("Recovery run hash mismatch")
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True).casefold()
    for token in FORBIDDEN_OUTPUT_TOKENS:
        if token in serialized:
            raise RecoveryContractError(f"Recovery output contains forbidden token: {token}")


def _safe_error(error: str) -> str:
    message = str(error)
    for token in FORBIDDEN_OUTPUT_TOKENS:
        message = message.replace(token, "[redacted]")
        message = message.replace(token.upper(), "[redacted]")
    return message[:500]


def _worker_result(prepared_path: Path, prepared_sha256: str) -> dict[str, Any]:
    before = get_process_memory_snapshot()
    started = time.perf_counter()
    try:
        detection = detect_static_pockets(
            prepared_path,
            prepared_sha256=prepared_sha256,
            resource_profile=RI3_STATIC_RECOVERY,
        )
        after = get_process_memory_snapshot()
        return {
            "status": "completed",
            "execution_profile": RI3_STATIC_RECOVERY.name,
            "canonical_static_result": False,
            "score_used": False,
            "motion_enabled": False,
            "nma_started": False,
            "detector_version": detection.detector_version,
            "detector_config_sha256": detection.config_sha256,
            "prepared_structure_sha256": prepared_sha256,
            "protein_atom_count": detection.protein_atom_count,
            "candidate_count": detection.candidate_count,
            "pocket_count": len(detection.pockets),
            "top_pockets": [pocket.to_portable_dict() for pocket in detection.pockets[:10]],
            "detector_warnings": list(detection.warnings),
            "runtime_seconds": round(time.perf_counter() - started, 6),
            "peak_rss_bytes": max(before.peak_rss_bytes, after.peak_rss_bytes),
        }
    except ResourceLimitError as exc:
        return {
            "status": "resource_blocked",
            "execution_profile": RI3_STATIC_RECOVERY.name,
            "canonical_static_result": False,
            "motion_enabled": False,
            "nma_started": False,
            "error": _safe_error(str(exc)),
            "runtime_seconds": round(time.perf_counter() - started, 6),
            "peak_rss_bytes": before.peak_rss_bytes,
        }
    except Exception as exc:  # noqa: BLE001 - worker returns a bounded failure record
        return {
            "status": "failed",
            "execution_profile": RI3_STATIC_RECOVERY.name,
            "canonical_static_result": False,
            "motion_enabled": False,
            "nma_started": False,
            "error": _safe_error(f"{type(exc).__name__}: {exc}"),
            "runtime_seconds": round(time.perf_counter() - started, 6),
            "peak_rss_bytes": before.peak_rss_bytes,
        }


def _child_rss_bytes(pid: int) -> int:
    """Read a child RSS without adding psutil to the project dependencies."""

    if os.name != "nt":
        # The supported local profile is Windows-first.  On POSIX, the
        # detector's own resource preflight remains active; no psutil
        # dependency is introduced solely for this optional parent guard.
        return 0

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("page_fault_count", ctypes.c_ulong),
            ("peak_working_set_size", ctypes.c_size_t),
            ("working_set_size", ctypes.c_size_t),
            ("quota_peak_paged_pool_usage", ctypes.c_size_t),
            ("quota_paged_pool_usage", ctypes.c_size_t),
            ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
            ("quota_non_paged_pool_usage", ctypes.c_size_t),
            ("pagefile_usage", ctypes.c_size_t),
            ("peak_pagefile_usage", ctypes.c_size_t),
        ]

    win_dll = getattr(ctypes, "WinDLL", None)
    if win_dll is None:
        return 0
    kernel32 = win_dll("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000 | 0x0010, False, pid)
    if not handle:
        return 0
    try:
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(ProcessMemoryCounters)
        kernel32.K32GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.c_ulong,
        ]
        kernel32.K32GetProcessMemoryInfo.restype = ctypes.c_int
        if not kernel32.K32GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return 0
        return int(counters.working_set_size)
    finally:
        kernel32.CloseHandle(handle)


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _run_guarded_worker(
    *,
    prepared_path: Path,
    prepared_sha256: str,
    worker_output: Path,
    rss_limit_bytes: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--prepared-path",
        str(prepared_path),
        "--prepared-sha256",
        prepared_sha256,
        "--worker-output",
        str(worker_output),
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    started = time.perf_counter()
    peak_rss = 0
    while process.poll() is None:
        current_rss = _child_rss_bytes(process.pid)
        peak_rss = max(peak_rss, current_rss)
        if current_rss > rss_limit_bytes:
            _terminate(process)
            return {
                "status": "resource_blocked",
                "execution_profile": RI3_STATIC_RECOVERY.name,
                "canonical_static_result": False,
                "motion_enabled": False,
                "nma_started": False,
                "error": "recovery_rss_limit_exceeded",
                "peak_rss_bytes": peak_rss,
                "runtime_seconds": round(time.perf_counter() - started, 6),
            }
        if time.perf_counter() - started > timeout_seconds:
            _terminate(process)
            return {
                "status": "resource_blocked",
                "execution_profile": RI3_STATIC_RECOVERY.name,
                "canonical_static_result": False,
                "motion_enabled": False,
                "nma_started": False,
                "error": "recovery_timeout_exceeded",
                "peak_rss_bytes": peak_rss,
                "runtime_seconds": round(time.perf_counter() - started, 6),
            }
        time.sleep(0.25)
    if process.returncode != 0 or not worker_output.is_file():
        return {
            "status": "failed",
            "execution_profile": RI3_STATIC_RECOVERY.name,
            "canonical_static_result": False,
            "motion_enabled": False,
            "nma_started": False,
            "error": "recovery_worker_failed",
            "peak_rss_bytes": peak_rss,
            "runtime_seconds": round(time.perf_counter() - started, 6),
        }
    result = _read_json(worker_output)
    result["parent_peak_rss_bytes"] = peak_rss
    result["peak_rss_bytes"] = max(int(result.get("peak_rss_bytes", 0)), peak_rss)
    return result


def _validate_primary_run(primary: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    if primary.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise RecoveryContractError("Primary run and target-blind manifest hashes differ")
    if primary.get("schema_version") != "biovoid-target-family-static-pilot-run-v1":
        raise RecoveryContractError("Unexpected primary static pilot schema")
    cases = primary.get("cases")
    if not isinstance(cases, Mapping):
        raise RecoveryContractError("Primary static pilot has no case records")


def run_recovery(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    primary_run_path: Path = DEFAULT_PRIMARY_RUN,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    max_disk_bytes: int = RECOVERY_MAX_DISK_BYTES,
    rss_limit_bytes: int = RECOVERY_RSS_LIMIT_BYTES,
    timeout_seconds: int = RECOVERY_TIMEOUT_SECONDS,
    user_approved: bool = False,
) -> dict[str, Any]:
    """Retry the primary run's blocked case in one guarded subprocess."""

    if not user_approved:
        raise RecoveryContractError("Recovery requires explicit user approval")
    if timeout_seconds < 1 or timeout_seconds > RECOVERY_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be between 1 and {RECOVERY_TIMEOUT_SECONDS}")
    manifest = _read_json(manifest_path.resolve())
    validate_detector_manifest(manifest)
    primary = _read_json(primary_run_path.resolve())
    _validate_primary_run(primary, manifest)
    cases = primary["cases"]
    blocked = [
        record
        for record in cases.values()
        if isinstance(record, Mapping) and record.get("status") == "resource_blocked"
    ]
    if len(blocked) != 1:
        raise RecoveryContractError(
            f"Expected exactly one primary resource-blocked case, found {len(blocked)}"
        )
    primary_record = dict(blocked[0])
    structure_id = str(primary_record["structure_id"]).upper()
    manifest_cases = {
        str(case["structure_id"]).upper(): case
        for case in manifest["cases"]
        if isinstance(case, Mapping)
    }
    if structure_id not in manifest_cases:
        raise RecoveryContractError(
            f"Blocked structure is absent from target-blind manifest: {structure_id}"
        )
    prepared_path_value = primary_record.get("prepared_path")
    if prepared_path_value:
        prepared_path = (REPO_ROOT / str(prepared_path_value)).resolve()
    else:
        # A primary resource preflight can happen before its record has a
        # prepared_path field.  Derive only the runner-owned deterministic
        # location; never search arbitrary files or fetch another structure.
        prepared_path = (
            primary_run_path.resolve().parent
            / "cases"
            / structure_id
            / "preparation"
            / "prepared_detector.pdb"
        ).resolve()
    try:
        prepared_path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise RecoveryContractError("Prepared path escapes the repository root") from exc
    if not prepared_path.is_file():
        raise RecoveryContractError(f"Prepared structure is missing: {prepared_path}")
    prepared_sha256 = str(
        primary_record.get("prepared_structure_sha256") or _sha256_file(prepared_path)
    )
    actual_prepared_sha256 = _sha256_file(prepared_path)
    if prepared_sha256 != actual_prepared_sha256:
        raise RecoveryContractError("Prepared structure hash differs from the primary record")
    if output_root.exists() and any(output_root.iterdir()):
        raise RecoveryContractError(f"Recovery output root is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    enforce_disk_quota(output_root, max_disk_bytes)
    run = build_recovery_run_skeleton(
        manifest_sha256=str(manifest["manifest_sha256"]),
        primary_run_sha256=_sha256_file(primary_run_path.resolve()),
        structure_id=structure_id,
        max_disk_bytes=max_disk_bytes,
        rss_limit_bytes=rss_limit_bytes,
    )
    run["status"] = "running"
    run["execution"]["started_disk_bytes"] = directory_size_bytes(output_root)
    run["execution"]["timeout_seconds"] = timeout_seconds
    run["primary_block_reason"] = "safe-16gb_resource_blocked"
    _seal(run)
    run_path = output_root / "target-family-static-recovery-v1.json"
    _write_json(run_path, run)

    worker_output = output_root / "worker-result.json"
    result = _run_guarded_worker(
        prepared_path=prepared_path,
        prepared_sha256=prepared_sha256,
        worker_output=worker_output,
        rss_limit_bytes=rss_limit_bytes,
        timeout_seconds=timeout_seconds,
    )
    result["structure_id"] = structure_id
    result["case_id"] = str(manifest_cases[structure_id]["case_id"])
    result["prepared_path"] = str(prepared_path.relative_to(REPO_ROOT)).replace("\\", "/")
    result["primary_block_reason"] = "safe-16gb_resource_blocked"
    result["canonical_static_result"] = False
    run["result"] = result
    run["status"] = (
        "completed_secondary_resource_recovery"
        if result.get("status") == "completed"
        else str(result.get("status", "failed"))
    )
    for _ in range(3):
        _seal(run)
        validate_recovery_run(run)
        _write_json(run_path, run)
        actual_disk_bytes = enforce_disk_quota(output_root, max_disk_bytes)
        if run["execution"].get("final_disk_bytes") == actual_disk_bytes:
            break
        run["execution"]["final_disk_bytes"] = actual_disk_bytes
    else:  # pragma: no cover - JSON size should converge after one update
        raise RecoveryContractError("Recovery final disk accounting did not converge")
    return run


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--primary-run", type=Path, default=DEFAULT_PRIMARY_RUN)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--max-disk-bytes", type=int, default=RECOVERY_MAX_DISK_BYTES)
    parser.add_argument("--rss-limit-bytes", type=int, default=RECOVERY_RSS_LIMIT_BYTES)
    parser.add_argument("--timeout-seconds", type=int, default=RECOVERY_TIMEOUT_SECONDS)
    parser.add_argument("--approve-recovery", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--prepared-path", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--prepared-sha256", help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.worker:
        if not args.prepared_path or not args.prepared_sha256 or not args.worker_output:
            raise SystemExit("Worker arguments are incomplete")
        result = _worker_result(args.prepared_path.resolve(), str(args.prepared_sha256))
        _write_json(args.worker_output.resolve(), result)
        return 0
    if not args.approve_recovery:
        raise SystemExit("Pass --approve-recovery after explicit user authorization")
    run = run_recovery(
        manifest_path=args.manifest,
        primary_run_path=args.primary_run,
        output_root=args.output_root,
        max_disk_bytes=args.max_disk_bytes,
        rss_limit_bytes=args.rss_limit_bytes,
        timeout_seconds=args.timeout_seconds,
        user_approved=True,
    )
    print(f"status={run['status']}")
    print(f"structure_id={run['structure_id']}")
    print(f"profile={run['execution']['profile']}")
    print(f"disk_bytes={run['execution']['final_disk_bytes']}")
    print(f"run_sha256={run['run_sha256']}")
    return 0 if run["status"] == "completed_secondary_resource_recovery" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RecoveryContractError, DiskQuotaExceeded) as exc:
        print(f"recovery error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
