"""Run a bounded secondary arm for RI-3 static records blocked by safe-16gb.

This runner is deliberately separate from the canonical RI-3 static run. It
retries only structures that the primary run recorded as resource-blocked,
uses one subprocess at a time, and records every guard decision. The detector
never receives evaluator fields, and successful recovery records are not
promoted to the canonical result by this script.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping

import psutil

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evaluator_format import (  # noqa: E402
    adapt_biovoid_pockets,
    failed_record,
    unavailable_record,
)
from src.resources import (  # noqa: E402
    RI3_STATIC_RECOVERY,
    ResourceLimitError,
    SAFE_16GB,
    get_process_memory_snapshot,
)
from src.static_detector import detect_static_pockets  # noqa: E402


DEFAULT_PRIMARY_RUN = REPO_ROOT / "data/runtime/ri3/ri3-static-development-run-v1.json"
DEFAULT_MANIFEST = REPO_ROOT / "data/runtime/ri3/cryptobench-development-runtime-manifest-v1.json"
DEFAULT_RECOVERY_RUN = REPO_ROOT / "data/runtime/ri3/ri3-static-resource-recovery-v1.json"
DEFAULT_WORK_DIR = REPO_ROOT / "data/runtime/ri3/resource-recovery-work"
RUN_SCHEMA_VERSION = "biovoid-ri3-static-resource-recovery-v1"
DEFAULT_PILOT_SIZE = 3
DEFAULT_BATCH_SIZE = 10
DEFAULT_TIMEOUT_SECONDS = 180
RSS_LIMIT_BYTES = 3 * 1024**3


class RI3RecoveryError(RuntimeError):
    """Raised when a recovery evidence contract cannot be satisfied."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RI3RecoveryError(f"Required local runtime file is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RI3RecoveryError(f"Expected a JSON object: {path}")
    return payload


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _profile_hash() -> str:
    return _stable_hash(asdict(RI3_STATIC_RECOVERY))


def _source_fingerprints() -> dict[str, str]:
    return {
        "recovery_runner": _sha256_file(Path(__file__).resolve()),
        "static_detector": _sha256_file(REPO_ROOT / "src/static_detector.py"),
        "resources": _sha256_file(REPO_ROOT / "src/resources.py"),
        "evaluator_format": _sha256_file(REPO_ROOT / "src/evaluator_format.py"),
    }


def _validate_inputs(primary: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    if primary.get("schema_version") != "biovoid-ri3-static-development-run-v1":
        raise RI3RecoveryError("Unexpected primary RI-3 static run schema")
    if primary.get("status") != "complete":
        raise RI3RecoveryError("Primary RI-3 static run must be complete before recovery")
    if primary.get("counts", {}).get("failed", 0):
        raise RI3RecoveryError("Primary RI-3 static run contains detector failures")
    if manifest.get("schema_version") != "biovoid-ri3-target-blind-runtime-manifest-v1":
        raise RI3RecoveryError("Unexpected target-blind manifest schema")
    structures = manifest.get("structures", [])
    if len(structures) != 663:
        raise RI3RecoveryError("Expected 663 target-blind structures")
    if primary.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise RI3RecoveryError("Primary run and target-blind manifest hashes differ")
    blocked = [
        record
        for record in primary.get("records", {}).values()
        if record.get("status") == "resource_blocked"
    ]
    if len(blocked) != 170:
        raise RI3RecoveryError(f"Expected 170 primary resource-blocked records, found {len(blocked)}")


def _structure_map(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["structure_id"]): dict(item) for item in manifest["structures"]}


def _blocked_map(primary: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(structure_id): dict(record)
        for structure_id, record in primary["records"].items()
        if record.get("status") == "resource_blocked"
    }


def _classify(primary_record: Mapping[str, Any]) -> str:
    atom_count = int(primary_record.get("protein_atom_count_preflight", 0))
    if atom_count > SAFE_16GB.max_static_atoms:
        return "primary_atom_limit"
    return "primary_memory_preflight"


def _base_record(
    structure: Mapping[str, Any],
    primary_record: Mapping[str, Any],
    *,
    status: str,
    error: str | None = None,
    runtime_seconds: float = 0.0,
    peak_rss_bytes: int = 0,
) -> dict[str, Any]:
    structure_id = str(structure["structure_id"])
    atom_count = int(structure["protein_atom_count"])
    payload: dict[str, Any] = {
        "structure_id": structure_id,
        "status": status,
        "recovery_eligible": atom_count <= RI3_STATIC_RECOVERY.max_static_atoms,
        "primary_block_class": _classify(primary_record),
        "primary_block_error": str(primary_record.get("error", "")),
        "prepared_structure_sha256": structure["prepared_structure_sha256"],
        "preparation_config_sha256": structure["preparation_config_sha256"],
        "prepared_path": str(structure["prepared_path"]).replace("\\", "/"),
        "protein_atom_count_preflight": atom_count,
        "execution_profile": RI3_STATIC_RECOVERY.name,
        "execution_profile_sha256": _profile_hash(),
        "canonical_static_result": False,
        "score_used": False,
        "nma_started": False,
        "sealed_evaluation_authorized": False,
        "detector_version": "canonical-static-v1",
        "ranking_contract": "canonical-static-v1-volume-descending",
        "runtime_seconds": round(runtime_seconds, 6),
        "peak_rss_bytes": peak_rss_bytes,
    }
    if error:
        payload["error"] = error
    return payload


def _worker_record(
    structure: Mapping[str, Any],
    primary_record: Mapping[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    before = get_process_memory_snapshot()
    prepared_path = (REPO_ROOT / str(structure["prepared_path"])).resolve()
    structure_id = str(structure["structure_id"])
    common = {
        "prepared_path": str(prepared_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "preparation_warnings": list(structure.get("warnings", [])),
    }
    if not prepared_path.is_file():
        return {
            **_base_record(
                structure,
                primary_record,
                status="failed",
                error=f"Prepared detector structure is missing: {prepared_path}",
                runtime_seconds=time.perf_counter() - started,
                peak_rss_bytes=before.peak_rss_bytes,
            ),
            **common,
        }
    try:
        detection = detect_static_pockets(
            prepared_path,
            prepared_sha256=str(structure["prepared_structure_sha256"]),
            resource_profile=RI3_STATIC_RECOVERY,
        )
        pockets = []
        for rank, pocket in enumerate(detection.pockets, start=1):
            portable = pocket.to_portable_dict()
            portable["rank"] = rank
            pockets.append(portable)
        detector_record = adapt_biovoid_pockets(
            structure_id,
            pockets,
            provenance={
                "detector_version": detection.detector_version,
                "detector_config_sha256": detection.config_sha256,
                "rank_contract": "canonical-static-v1-volume-descending",
                "volume_method": detection.volume_method,
                "surface_model": detection.surface_model,
                "score_used": False,
                "execution_profile": RI3_STATIC_RECOVERY.name,
                "canonical_static_result": False,
            },
        )
        after = get_process_memory_snapshot()
        return {
            **_base_record(
                structure,
                primary_record,
                status="completed",
                runtime_seconds=time.perf_counter() - started,
                peak_rss_bytes=max(before.peak_rss_bytes, after.peak_rss_bytes),
            ),
            **common,
            "detector_record": asdict(detector_record),
            "candidate_count": detection.candidate_count,
            "pocket_count": len(detection.pockets),
            "detector_warnings": list(detection.warnings),
            "detector_atom_count": detection.protein_atom_count,
        }
    except ResourceLimitError as exc:
        return {
            **_base_record(
                structure,
                primary_record,
                status="resource_blocked",
                error=str(exc),
                runtime_seconds=time.perf_counter() - started,
                peak_rss_bytes=before.peak_rss_bytes,
            ),
            **common,
            "detector_record": asdict(unavailable_record("biovoid_static", structure_id, str(exc))),
        }
    except Exception as exc:  # noqa: BLE001 - failed records remain in denominator
        error = f"{type(exc).__name__}: {exc}"
        return {
            **_base_record(
                structure,
                primary_record,
                status="failed",
                error=error,
                runtime_seconds=time.perf_counter() - started,
                peak_rss_bytes=before.peak_rss_bytes,
            ),
            **common,
            "detector_record": asdict(failed_record("biovoid_static", structure_id, error)),
        }


def _worker_main(args: argparse.Namespace) -> int:
    primary = _read_json(_resolve(args.primary_run))
    manifest = _read_json(_resolve(args.manifest))
    _validate_inputs(primary, manifest)
    structures = _structure_map(manifest)
    blocked = _blocked_map(primary)
    structure_id = str(args.worker_structure)
    if structure_id not in blocked or structure_id not in structures:
        raise RI3RecoveryError(f"Worker structure is not a primary blocked case: {structure_id}")
    record = _worker_record(structures[structure_id], blocked[structure_id])
    _write_json_atomic(_resolve(args.worker_output), record)
    return 0


def _guard_record(
    structure: Mapping[str, Any],
    primary_record: Mapping[str, Any],
    *,
    status: str,
    reason: str,
    runtime_seconds: float,
    peak_rss_bytes: int,
) -> dict[str, Any]:
    record = _base_record(
        structure,
        primary_record,
        status=status,
        error=reason,
        runtime_seconds=runtime_seconds,
        peak_rss_bytes=peak_rss_bytes,
    )
    record["detector_record"] = asdict(unavailable_record("biovoid_static", structure["structure_id"], reason))
    return record


def _run_guarded_worker(
    structure: Mapping[str, Any],
    primary_record: Mapping[str, Any],
    *,
    primary_path: Path,
    manifest_path: Path,
    work_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    structure_id = str(structure["structure_id"])
    output_path = work_dir / f"{structure_id}.json"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker-structure",
        structure_id,
        "--primary-run",
        str(primary_path),
        "--manifest",
        str(manifest_path),
        "--worker-output",
        str(output_path),
    ]
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    process_handle = psutil.Process(process.pid)
    peak_rss = 0
    guard_reason: str | None = None
    while process.poll() is None:
        try:
            current_rss = int(process_handle.memory_info().rss)
            peak_rss = max(peak_rss, current_rss)
        except psutil.Error:
            current_rss = peak_rss
        if current_rss > RSS_LIMIT_BYTES:
            guard_reason = (
                f"recovery RSS guard exceeded: {current_rss} > {RSS_LIMIT_BYTES} bytes"
            )
            process.kill()
            break
        if time.perf_counter() - started >= timeout_seconds:
            guard_reason = f"recovery timeout exceeded: {timeout_seconds} seconds"
            process.kill()
            break
        time.sleep(0.2)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)

    runtime = time.perf_counter() - started
    if guard_reason:
        return _guard_record(
            structure,
            primary_record,
            status="guard_terminated" if "RSS" in guard_reason else "timeout",
            reason=guard_reason,
            runtime_seconds=runtime,
            peak_rss_bytes=peak_rss,
        )
    if not output_path.is_file():
        return _guard_record(
            structure,
            primary_record,
            status="failed",
            reason=f"recovery worker exited without a record (exit_code={process.returncode})",
            runtime_seconds=runtime,
            peak_rss_bytes=peak_rss,
        )
    record = _read_json(output_path)
    record["parent_observed_peak_rss_bytes"] = peak_rss
    record["parent_observed_runtime_seconds"] = round(runtime, 6)
    record["peak_rss_bytes"] = max(int(record.get("peak_rss_bytes", 0)), peak_rss)
    return record


def _counts(records: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    values = {"completed": 0, "resource_blocked": 0, "failed": 0, "guard_terminated": 0, "timeout": 0}
    for record in records.values():
        status = str(record.get("status", ""))
        if status not in values:
            raise RI3RecoveryError(f"Unknown recovery record status: {status}")
        values[status] += 1
    return values


def _initial_payload(
    primary: Mapping[str, Any], manifest: Mapping[str, Any], *, primary_path: Path
) -> dict[str, Any]:
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": f"ri3-static-resource-recovery-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "status": "not_started",
        "primary_run_sha256": _sha256_file(primary_path),
        "manifest_sha256": manifest["manifest_sha256"],
        "source_fingerprints": _source_fingerprints(),
        "profile": {
            **asdict(RI3_STATIC_RECOVERY),
            "profile_sha256": _profile_hash(),
            "parent_rss_limit_bytes": RSS_LIMIT_BYTES,
            "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        },
        "execution": {
            "workers": 1,
            "checkpoint_batch_size": DEFAULT_BATCH_SIZE,
            "nma_started": False,
            "sealed_evaluation_authorized": False,
            "canonical_result_promotion": False,
        },
        "target_blind": True,
        "records": {},
        "counts": _counts({}),
    }


def _validate_resume(
    payload: Mapping[str, Any],
    primary: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    primary_path: Path,
) -> None:
    if payload.get("schema_version") != RUN_SCHEMA_VERSION:
        raise RI3RecoveryError("Unexpected recovery run schema")
    if payload.get("primary_run_sha256") != _sha256_file(primary_path):
        raise RI3RecoveryError("Primary run changed since recovery evidence was created")
    if payload.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise RI3RecoveryError("Recovery manifest hash differs from the target-blind manifest")
    if payload.get("profile", {}).get("profile_sha256") != _profile_hash():
        raise RI3RecoveryError("Recovery resource profile changed since the run was created")
    if payload.get("execution", {}).get("workers") != 1:
        raise RI3RecoveryError("Recovery runner is single-worker only")
    if payload.get("execution", {}).get("canonical_result_promotion") is not False:
        raise RI3RecoveryError("Recovery results cannot be promoted automatically")
    if payload.get("execution", {}).get("nma_started") is not False:
        raise RI3RecoveryError("NMA flag is not closed")
    if payload.get("execution", {}).get("sealed_evaluation_authorized") is not False:
        raise RI3RecoveryError("Sealed evaluation flag is not closed")
    if set(payload.get("records", {})) - set(_blocked_map(primary)):
        raise RI3RecoveryError("Recovery records contain non-blocked structures")


def _pilot_order(blocked: Mapping[str, Mapping[str, Any]]) -> list[str]:
    candidates = list(blocked)
    targets = (4000, 5001, RI3_STATIC_RECOVERY.max_static_atoms)
    selected: list[str] = []
    for target in targets:
        eligible = [
            structure_id
            for structure_id in candidates
            if int(blocked[structure_id].get("protein_atom_count_preflight", 0))
            <= RI3_STATIC_RECOVERY.max_static_atoms
            and structure_id not in selected
        ]
        if eligible:
            selected.append(
                min(
                    eligible,
                    key=lambda structure_id: abs(
                        int(blocked[structure_id]["protein_atom_count_preflight"]) - target
                    ),
                )
            )
    return selected + [structure_id for structure_id in sorted(candidates) if structure_id not in selected]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-run", type=Path, default=DEFAULT_PRIMARY_RUN)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--run", dest="run_path", type=Path, default=DEFAULT_RECOVERY_RUN)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--all-eligible", action="store_true")
    parser.add_argument("--max-structures", type=int, default=DEFAULT_PILOT_SIZE)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--worker-structure")
    parser.add_argument("--worker-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.worker_structure:
        if args.worker_output is None:
            raise RI3RecoveryError("Worker output path is required")
        return _worker_main(args)
    if args.timeout_seconds < 30 or args.timeout_seconds > 600:
        raise RI3RecoveryError("Recovery timeout must be between 30 and 600 seconds")
    if args.batch_size < 1 or args.batch_size > 10:
        raise RI3RecoveryError("Recovery checkpoint batch size must be between 1 and 10")
    if args.all_eligible and args.max_structures != DEFAULT_PILOT_SIZE:
        raise RI3RecoveryError("Use either --all-eligible or --max-structures, not both")
    if not args.all_eligible and args.max_structures < 1:
        raise RI3RecoveryError("--max-structures must be positive")

    primary_path = _resolve(args.primary_run)
    manifest_path = _resolve(args.manifest)
    primary = _read_json(primary_path)
    manifest = _read_json(manifest_path)
    _validate_inputs(primary, manifest)
    structures = _structure_map(manifest)
    blocked = _blocked_map(primary)
    run_path = _resolve(args.run_path)
    if run_path.is_file():
        run = _read_json(run_path)
        _validate_resume(run, primary, manifest, primary_path=primary_path)
    else:
        run = _initial_payload(primary, manifest, primary_path=primary_path)
    if run.get("source_fingerprints") != _source_fingerprints():
        raise RI3RecoveryError("Recovery source changed since the run was created")

    records = dict(run.get("records", {}))
    # Preserve a terminal record for cases that exceed the bounded recovery
    # profile without starting a subprocess for them.
    for structure_id, primary_record in blocked.items():
        if structure_id in records:
            continue
        if int(primary_record.get("protein_atom_count_preflight", 0)) > RI3_STATIC_RECOVERY.max_static_atoms:
            records[structure_id] = _base_record(
                structures[structure_id],
                primary_record,
                status="resource_blocked",
                error=(
                    f"{RI3_STATIC_RECOVERY.name} atom limit exceeded: "
                    f"{primary_record.get('protein_atom_count_preflight')} > "
                    f"{RI3_STATIC_RECOVERY.max_static_atoms}"
                ),
            )

    remaining = [structure_id for structure_id in blocked if structure_id not in records]
    ordered = _pilot_order({structure_id: blocked[structure_id] for structure_id in remaining})
    selected = ordered if args.all_eligible else ordered[: args.max_structures]
    run["status"] = "running"
    run["updated_at_utc"] = _utc_now()
    run["execution"]["checkpoint_batch_size"] = args.batch_size
    for index, structure_id in enumerate(selected, start=1):
        print(f"[{index}/{len(selected)}] {structure_id}: bounded recovery", flush=True)
        records[structure_id] = _run_guarded_worker(
            structures[structure_id],
            blocked[structure_id],
            primary_path=primary_path,
            manifest_path=manifest_path,
            work_dir=_resolve(args.work_dir),
            timeout_seconds=args.timeout_seconds,
        )
        run["records"] = records
        run["counts"] = _counts(records)
        run["updated_at_utc"] = _utc_now()
        if index % args.batch_size == 0 or index == len(selected):
            _write_json_atomic(run_path, run)
            print(f"checkpoint counts={json.dumps(run['counts'], sort_keys=True)}", flush=True)

    run["records"] = records
    run["counts"] = _counts(records)
    run["status"] = "complete" if len(records) == len(blocked) else "partial"
    run["updated_at_utc"] = _utc_now()
    _write_json_atomic(run_path, run)
    print(
        f"RI-3 resource recovery run: {run['status']} "
        f"processed={len(records)}/{len(blocked)} "
        f"counts={json.dumps(run['counts'], sort_keys=True)}"
    )
    print(f"recovery report: {run_path}")
    print("canonical promotion: disabled")
    print("NMA/sealed: closed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RI3RecoveryError as exc:
        print(f"RI-3 recovery runner error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
