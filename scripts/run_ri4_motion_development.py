"""Run the bounded, target-blind RI-4 motion development arm.

The motion layer is evaluated only after the RI-3 eligibility and RI-4
resource locks have been materialized. Each structure is handled by one
short-lived child process so a heavy eigensolver cannot accumulate memory
across the cohort. Holo-derived coordinates are loaded only by the parent
evaluation step and are never passed to the detector worker.

This is a development comparison. It never opens the sealed split and never
changes the canonical static ranking.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.benchmark_v1 import (  # noqa: E402
    BenchmarkCase,
    BenchmarkManifest,
    EvaluatorGroundTruth,
    assess_motion_integration,
    evaluate_split,
    phase6_frozen_protocol_v1,
)
from src.evaluator_format import (  # noqa: E402
    DetectorEvaluationRecord,
    EvaluatorPocket,
    adapt_biovoid_motion_pockets,
    assert_detector_payload_is_blind,
    failed_record,
    unavailable_record,
)
from src.motion_ensemble import (  # noqa: E402
    MotionEnsembleConfig,
    analyze_validated_motion_ensemble,
    generate_validated_motion_ensemble,
)
from src.resources import (  # noqa: E402
    ResourceLimitError,
    SAFE_16GB,
    get_available_memory_bytes,
    get_process_memory_snapshot,
)

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


DEFAULT_PREFLIGHT = REPO_ROOT / "data/runtime/ri4/ri4-development-motion-preflight-v1.json"
DEFAULT_RECOVERY = REPO_ROOT / (
    "data/runtime/ri3/ri3-static-development-evaluation-structural-recovery-v1.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "data/runtime/ri4/ri4-development-motion-run-v1.json"
DEFAULT_WORK_DIR = REPO_ROOT / "data/runtime/ri4/motion-work"
SCHEMA_VERSION = "biovoid-ri4-motion-development-v1"
DEFAULT_BATCH_SIZE = 3
DEFAULT_PILOT_SIZE = 3
DEFAULT_TIMEOUT_SECONDS = 900


class RI4RunError(RuntimeError):
    """Raised when the RI-4 development contract cannot be satisfied."""


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _normalize_structure_id(value: str) -> str:
    normalized = str(value).strip().upper()
    if len(normalized) != 4 or not normalized.isalnum():
        raise RI4RunError(f"Invalid structure ID: {value!r}")
    return normalized


def _validate_batch_size(value: int) -> int:
    if value < 1 or value > 10:
        raise RI4RunError("RI-4 checkpoint batch size must be between 1 and 10")
    return value


def _validate_timeout(value: int) -> int:
    if value < 30 or value > 3600:
        raise RI4RunError("RI-4 worker timeout must be between 30 and 3600 seconds")
    return value


def _source_fingerprints() -> dict[str, str]:
    return {
        "ri4_runner": _sha256_file(Path(__file__).resolve()),
        "motion_ensemble": _sha256_file(REPO_ROOT / "src/motion_ensemble.py"),
        "dynamics": _sha256_file(REPO_ROOT / "src/dynamics.py"),
        "frame_reconstruction": _sha256_file(REPO_ROOT / "src/frame_reconstruction.py"),
        "static_detector": _sha256_file(REPO_ROOT / "src/static_detector.py"),
        "evaluator_format": _sha256_file(REPO_ROOT / "src/evaluator_format.py"),
        "benchmark_protocol": _sha256_file(REPO_ROOT / "src/benchmark_v1.py"),
    }


def _load_motion_preflight(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if payload.get("schema_version") != "biovoid-ri4-development-motion-preflight-v1":
        raise RI4RunError("Unexpected RI-4 preflight schema")
    if payload.get("status") != "ready_for_opt_in_motion_pilot":
        raise RI4RunError("RI-4 preflight is not ready")
    if payload.get("boundaries", {}).get("motion_execution_started") is not False:
        raise RI4RunError("RI-4 preflight already records motion execution")
    case_ids = payload.get("motion_preflight_case_ids")
    structure_ids = payload.get("motion_preflight_structure_ids")
    if not isinstance(case_ids, list) or not case_ids:
        raise RI4RunError("RI-4 preflight has no exact case list")
    if not isinstance(structure_ids, list) or not structure_ids:
        raise RI4RunError("RI-4 preflight has no exact structure list")
    if len(case_ids) != int(payload.get("motion_preflight_case_count", 0)):
        raise RI4RunError("RI-4 preflight case count/list mismatch")
    if len(structure_ids) != int(payload.get("motion_preflight_structure_count", 0)):
        raise RI4RunError("RI-4 preflight structure count/list mismatch")
    if _stable_hash(sorted(str(item) for item in case_ids)) != payload.get(
        "motion_preflight_case_ids_sha256"
    ):
        raise RI4RunError("RI-4 preflight case-list hash mismatch")
    if _stable_hash(sorted(str(item) for item in structure_ids)) != payload.get(
        "motion_preflight_structure_ids_sha256"
    ):
        raise RI4RunError("RI-4 preflight structure-list hash mismatch")
    resource = payload.get("resource_profile", {})
    if resource.get("name") != SAFE_16GB.name or int(resource.get("max_heavy_jobs", 0)) != 1:
        raise RI4RunError("RI-4 preflight is not locked to safe-16gb one-heavy-job policy")
    return payload


def _selected_manifest(
    manifest_payload: Mapping[str, Any], preflight: Mapping[str, Any]
) -> tuple[BenchmarkManifest, tuple[str, ...], tuple[str, ...]]:
    if manifest_payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise RI4RunError("Unexpected RI-3 runtime manifest schema")
    _validate_manifest(manifest_payload)
    all_cases = tuple(
        BenchmarkCase(**case) for case in manifest_payload["benchmark_manifest"]["cases"]
    )
    case_by_id = {case.case_id.casefold(): case for case in all_cases}
    selected_case_ids = tuple(sorted(str(value) for value in preflight["motion_preflight_case_ids"]))
    missing_cases = [case_id for case_id in selected_case_ids if case_id.casefold() not in case_by_id]
    if missing_cases:
        raise RI4RunError("RI-4 preflight cases are absent from manifest")
    selected_cases = tuple(case_by_id[case_id.casefold()] for case_id in selected_case_ids)
    selected_structure_ids = tuple(
        sorted(_normalize_structure_id(value) for value in preflight["motion_preflight_structure_ids"])
    )
    derived_structure_ids = tuple(sorted({case.structure_id.upper() for case in selected_cases}))
    if selected_structure_ids != derived_structure_ids:
        raise RI4RunError("RI-4 preflight structure list differs from selected cases")
    if len(selected_cases) != int(preflight["motion_preflight_case_count"]):
        raise RI4RunError("RI-4 selected case count differs from preflight")
    if len(selected_structure_ids) != int(preflight["motion_preflight_structure_count"]):
        raise RI4RunError("RI-4 selected structure count differs from preflight")
    return BenchmarkManifest(cases=selected_cases), selected_case_ids, selected_structure_ids


def _load_truths(
    recovery: Mapping[str, Any], selected_case_ids: tuple[str, ...], manifest_sha256: str
) -> dict[str, EvaluatorGroundTruth]:
    if recovery.get("manifest_sha256") != manifest_sha256:
        raise RI4RunError("Evaluator recovery report does not match the runtime manifest")
    if recovery.get("protocol_sha256") != phase6_frozen_protocol_v1().protocol_sha256:
        raise RI4RunError("Evaluator recovery report protocol mismatch")
    selected = {case_id.casefold() for case_id in selected_case_ids}
    truths: dict[str, EvaluatorGroundTruth] = {}
    for case_id, raw in recovery.get("records", {}).items():
        if str(case_id).casefold() not in selected:
            continue
        if raw.get("status") != "completed_ground_truth" or not raw.get("ground_truth"):
            raise RI4RunError(f"Selected RI-4 case has no completed evaluator truth: {case_id}")
        truth = _ground_truth_from_payload(raw["ground_truth"])
        truths[truth.case_id.casefold()] = truth
    if set(truths) != selected:
        missing = sorted(selected - set(truths))
        raise RI4RunError("RI-4 evaluator truth is incomplete: " + ", ".join(missing[:5]))
    return truths


def _portable_static_pockets(record: DetectorEvaluationRecord) -> list[dict[str, Any]]:
    pockets: list[dict[str, Any]] = []
    for pocket in record.pockets:
        payload = dict(pocket.raw)
        payload.update(
            {
                "pocket_id": pocket.pocket_id,
                "center": list(pocket.center),
                "volume": pocket.volume,
                "rank": pocket.rank,
            }
        )
        assert_detector_payload_is_blind(payload, path="static_pocket")
        pockets.append(payload)
    return pockets


def _record_from_payload(payload: Mapping[str, Any]) -> DetectorEvaluationRecord:
    detector_payload = payload.get("detector_record")
    if not isinstance(detector_payload, Mapping):
        raise RI4RunError("RI-4 detector record is missing")
    pockets = tuple(
        EvaluatorPocket(
            pocket_id=str(raw["pocket_id"]),
            center=tuple(float(value) for value in raw["center"]),
            volume=float(raw["volume"]) if raw.get("volume") is not None else None,
            rank=int(raw["rank"]),
            score=float(raw["score"]) if raw.get("score") is not None else None,
            raw=dict(raw.get("raw", {})),
        )
        for raw in detector_payload.get("pockets", [])
    )
    return DetectorEvaluationRecord(
        schema_version=str(detector_payload["schema_version"]),
        detector=str(detector_payload["detector"]),
        structure_id=_normalize_structure_id(detector_payload["structure_id"]),
        status=str(detector_payload["status"]),
        pockets=pockets,
        error=detector_payload.get("error"),
        provenance=dict(detector_payload.get("provenance") or {}),
    )


def _null_motion_record(
    structure_id: str,
    static_record: DetectorEvaluationRecord,
) -> DetectorEvaluationRecord:
    """Build a zero-displacement control through the motion adapter only."""
    pockets: list[dict[str, Any]] = []
    for index, pocket in enumerate(static_record.pockets, start=1):
        payload = {
            "motion_pocket_id": f"NULL-{pocket.pocket_id}",
            "center": list(pocket.center),
            "volume_mean": pocket.volume,
            "rank": index,
            "ensemble_support": 1.0,
            "supported_sample_count": 1,
            "supported_modes": [],
            "mode_support": 0.0,
            "mode_diversity": 0.0,
            "bidirectional_support": False,
            "amplitude_range": [0.0, 0.0],
            "static_pocket_id": pocket.pocket_id,
            "static_relationship": "null_static_duplicate",
        }
        assert_detector_payload_is_blind(payload, path="null_motion_pocket")
        pockets.append(payload)
    return adapt_biovoid_motion_pockets(
        structure_id,
        pockets,
        provenance={
            "detector_version": "biovoid-motion-null-control-v1",
            "runtime_seconds": 0.0,
            "peak_rss_bytes": 0,
            "score_used": False,
        },
    )


def _worker_record(
    *,
    structure_id: str,
    prepared_path: Path,
    prepared_sha256: str,
    static_pockets_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    config = MotionEnsembleConfig()
    common = {
        "structure_id": structure_id,
        "prepared_structure_sha256": prepared_sha256,
        "prepared_path": str(prepared_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "detector_version": "biovoid-motion-v1",
        "motion_config": asdict(config),
        "resource_profile": SAFE_16GB.name,
        "workers": 1,
        "canonical_ranking_affected": False,
        "sealed_evaluation_authorized": False,
        "target_blind_detector_input": True,
    }
    before_peak = 0
    try:
        before = get_process_memory_snapshot()
        before_peak = before.peak_rss_bytes
        static_pockets = _read_json(static_pockets_path).get("pockets", [])
        if not isinstance(static_pockets, list):
            raise RI4RunError("Static pocket worker input must contain a list")
        assert_detector_payload_is_blind(static_pockets, path="worker_static_pockets")
        available_memory = get_available_memory_bytes()
        ensemble = generate_validated_motion_ensemble(
            prepared_path,
            output_dir,
            config,
            available_memory_bytes=available_memory,
        )
        evidence = analyze_validated_motion_ensemble(
            ensemble,
            static_pockets,
            prepared_sha256=prepared_sha256,
        )
        manifest_payload = _read_json(ensemble.manifest_path)
        manifest_sha256 = str(manifest_payload.get("manifest_sha256", ""))
        if len(manifest_sha256) != 64:
            raise RI4RunError("Motion manifest hash is missing")
        evidence.pop("ensemble_manifest", None)
        evidence["motion_manifest_sha256"] = manifest_sha256
        evidence["sample_quality_records"] = list(manifest_payload.get("samples", []))
        after = get_process_memory_snapshot()
        peak_rss = max(before.peak_rss_bytes, after.peak_rss_bytes)
        runtime_seconds = round(time.perf_counter() - started, 6)
        detector_record = adapt_biovoid_motion_pockets(
            structure_id,
            evidence["motion_pockets"],
            provenance={
                "detector_version": "biovoid-motion-v1",
                "motion_manifest_sha256": manifest_sha256,
                "motion_evidence_schema": evidence["schema_version"],
                "motion_evidence_policy": evidence["evidence_policy"],
                "quality_policy_version": manifest_payload["quality_policy_version"],
                "sampling_policy_version": manifest_payload["sampling_policy_version"],
                "rank_contract": "mode-support-then-ensemble-support",
                "score_used": False,
                "runtime_seconds": runtime_seconds,
                "peak_rss_bytes": peak_rss,
            },
        )
        return {
            **common,
            "status": "completed",
            "detector_record": asdict(detector_record),
            "motion_evidence": evidence,
            "quality_counts": dict(ensemble.quality_counts),
            "accepted_sample_count": len(ensemble.accepted_sample_ids),
            "requested_sample_count": len(ensemble.samples),
            "estimated_memory_bytes": ensemble.estimated_memory_bytes,
            "runtime_seconds": runtime_seconds,
            "peak_rss_bytes": peak_rss,
            "error": None,
        }
    except ResourceLimitError as exc:
        return {
            **common,
            "status": "resource_blocked",
            "detector_record": asdict(
                unavailable_record("biovoid_motion", structure_id, str(exc))
            ),
            "error": str(exc),
            "runtime_seconds": round(time.perf_counter() - started, 6),
            "peak_rss_bytes": before_peak,
        }
    except Exception as exc:  # noqa: BLE001 - failures remain in the denominator
        return {
            **common,
            "status": "failed",
            "detector_record": asdict(
                failed_record("biovoid_motion", structure_id, f"{type(exc).__name__}: {exc}")
            ),
            "error": f"{type(exc).__name__}: {exc}",
            "runtime_seconds": round(time.perf_counter() - started, 6),
            "peak_rss_bytes": before_peak,
        }
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def _run_worker(args: argparse.Namespace) -> int:
    result = _worker_record(
        structure_id=_normalize_structure_id(args.structure_id),
        prepared_path=Path(args.prepared).resolve(),
        prepared_sha256=str(args.prepared_sha256),
        static_pockets_path=Path(args.static_pocket_input).resolve(),
        output_dir=Path(args.output_dir).resolve(),
    )
    _write_json_atomic(Path(args.result_path).resolve(), result)
    return 0


def _initial_run_payload(
    *,
    preflight_path: Path,
    preflight: Mapping[str, Any],
    manifest: BenchmarkManifest,
    selected_case_ids: tuple[str, ...],
    selected_structure_ids: tuple[str, ...],
) -> dict[str, Any]:
    config = MotionEnsembleConfig()
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"ri4-motion-development-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "status": "not_started",
        "manifest_sha256": manifest.manifest_sha256,
        "original_runtime_manifest_sha256": preflight["runtime_manifest_sha256"],
        "preflight_sha256": _sha256_file(preflight_path),
        "cohort": {
            "case_count": len(selected_case_ids),
            "structure_count": len(selected_structure_ids),
            "case_ids": list(selected_case_ids),
            "structure_ids": list(selected_structure_ids),
            "case_ids_sha256": _stable_hash(list(selected_case_ids)),
            "structure_ids_sha256": _stable_hash(list(selected_structure_ids)),
        },
        "protocol_sha256": phase6_frozen_protocol_v1().protocol_sha256,
        "motion_config": asdict(config),
        "source_fingerprints": _source_fingerprints(),
        "execution": {
            "resource_profile": SAFE_16GB.name,
            "workers": 1,
            "max_heavy_jobs": 1,
            "checkpoint_batch_size": DEFAULT_BATCH_SIZE,
            "worker_timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
            "motion_execution_started": False,
            "canonical_ranking_affected": False,
            "sealed_evaluation_authorized": False,
        },
        "target_blind_detector_inputs": True,
        "records": {},
        "counts": {"completed": 0, "resource_blocked": 0, "failed": 0},
        "quality_counts": {"ACCEPTED": 0, "ACCEPTED_WITH_WARNINGS": 0, "REJECTED": 0},
        "null_control": {"status": "pending"},
        "results": {},
    }


def _record_counts(run: Mapping[str, Any]) -> dict[str, int]:
    counts = {"completed": 0, "resource_blocked": 0, "failed": 0}
    for raw in run.get("records", {}).values():
        status = str(raw.get("status", ""))
        if status in counts:
            counts[status] += 1
    return counts


def _quality_counts(run: Mapping[str, Any]) -> dict[str, int]:
    counts = {"ACCEPTED": 0, "ACCEPTED_WITH_WARNINGS": 0, "REJECTED": 0}
    for raw in run.get("records", {}).values():
        for status, count in raw.get("quality_counts", {}).items():
            if status in counts:
                counts[status] += int(count)
    return counts


def _motion_records(run: Mapping[str, Any]) -> dict[str, DetectorEvaluationRecord]:
    return {
        _normalize_structure_id(structure_id): _record_from_payload(raw)
        for structure_id, raw in run.get("records", {}).items()
    }


def _evaluate_results(
    *,
    run: dict[str, Any],
    selected_manifest: BenchmarkManifest,
    static_records: Mapping[str, DetectorEvaluationRecord],
    truths: Mapping[str, EvaluatorGroundTruth],
) -> None:
    selected_structures = {case.structure_id.upper() for case in selected_manifest.cases}
    scoped_static = {key: value for key, value in static_records.items() if key in selected_structures}
    motion_records = _motion_records(run)
    null_records = {
        structure_id: _null_motion_record(structure_id, scoped_static[structure_id])
        for structure_id in sorted(selected_structures)
        if structure_id in scoped_static
    }
    binding_centers: dict[str, tuple[tuple[float, float, float], ...]] = {}
    centers_by_structure: dict[str, set[tuple[float, float, float]]] = {}
    for case in selected_manifest.cases:
        truth = truths[case.case_id.casefold()]
        centers_by_structure.setdefault(case.structure_id.upper(), set()).add(truth.ligand_center)
    binding_centers = {
        structure_id: tuple(sorted(centers))
        for structure_id, centers in centers_by_structure.items()
    }
    protocol = phase6_frozen_protocol_v1()
    static_summary = evaluate_split(
        detector="biovoid_static",
        split="development",
        records=scoped_static,
        ground_truth=truths,
        binding_site_reference_centers=binding_centers,
        manifest=selected_manifest,
        protocol=protocol,
    )
    motion_summary = evaluate_split(
        detector="biovoid_motion",
        split="development",
        records=motion_records,
        ground_truth=truths,
        binding_site_reference_centers=binding_centers,
        manifest=selected_manifest,
        protocol=protocol,
    )
    null_summary = evaluate_split(
        detector="biovoid_motion",
        split="development",
        records=null_records,
        ground_truth=truths,
        binding_site_reference_centers=binding_centers,
        manifest=selected_manifest,
        protocol=protocol,
    )
    comparable_fields = (
        "target_denominator",
        "structure_denominator",
        "completed_targets",
        "failed_or_unavailable_targets",
        "completed_structures",
        "failed_or_unavailable_structures",
        "failure_rate",
        "target_failure_rate",
        "top_k_dcc_recall",
        "top_k_dca_recall",
        "false_pocket_denominator",
        "false_pocket_metric_status",
        "false_pockets_per_completed_protein",
    )
    null_differences = {
        field: {"static": static_summary.get(field), "null": null_summary.get(field)}
        for field in comparable_fields
        if static_summary.get(field) != null_summary.get(field)
    }
    run["null_control"] = {
        "status": "pass" if not null_differences else "fail",
        "description": "Zero-displacement static duplicate passed through the motion adapter",
        "differences": null_differences,
        "static_detector": "biovoid_static",
        "null_detector": "biovoid_motion",
    }
    run["results"] = {
        "static": static_summary,
        "motion": motion_summary,
        "null_control": null_summary,
        "integration_decision": assess_motion_integration(
            static_summary,
            motion_summary,
            protocol,
        ),
    }


def _finalize_run(
    run: dict[str, Any],
    *,
    selected_manifest: BenchmarkManifest,
    static_records: Mapping[str, DetectorEvaluationRecord],
    truths: Mapping[str, EvaluatorGroundTruth],
) -> None:
    run["counts"] = _record_counts(run)
    run["quality_counts"] = _quality_counts(run)
    run["results"] = {}
    if len(run["records"]) == int(run["cohort"]["structure_count"]):
        _evaluate_results(
            run=run,
            selected_manifest=selected_manifest,
            static_records=static_records,
            truths=truths,
        )
    else:
        run["null_control"] = {
            "status": "deferred_until_full_cohort",
            "description": "Pilot output is not a canonical or scientific comparison",
        }
    run["status"] = (
        "complete"
        if len(run["records"]) == int(run["cohort"]["structure_count"])
        else "partial"
    )
    run["updated_at_utc"] = _utc_now()


def _worker_failure(
    structure_id: str,
    prepared_sha256: str,
    reason: str,
    *,
    status: str = "failed",
    runtime_seconds: float = 0.0,
) -> dict[str, Any]:
    detector_record = (
        unavailable_record("biovoid_motion", structure_id, reason)
        if status == "resource_blocked"
        else failed_record("biovoid_motion", structure_id, reason)
    )
    return {
        "structure_id": structure_id,
        "prepared_structure_sha256": prepared_sha256,
        "detector_version": "biovoid-motion-v1",
        "motion_config": asdict(MotionEnsembleConfig()),
        "resource_profile": SAFE_16GB.name,
        "workers": 1,
        "canonical_ranking_affected": False,
        "sealed_evaluation_authorized": False,
        "target_blind_detector_input": True,
        "status": status,
        "detector_record": asdict(detector_record),
        "error": reason,
        "runtime_seconds": runtime_seconds,
        "peak_rss_bytes": 0,
    }


def _run_one_structure(
    *,
    structure_id: str,
    structure: Mapping[str, Any],
    static_record: DetectorEvaluationRecord,
    work_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    prepared_path = (REPO_ROOT / str(structure["prepared_path"])).resolve()
    if not prepared_path.is_file():
        raise RI4RunError(f"Prepared structure is missing: {prepared_path}")
    job_dir = work_dir / structure_id
    shutil.rmtree(job_dir, ignore_errors=True)
    job_dir.mkdir(parents=True, exist_ok=True)
    static_input = job_dir / "static_pockets.json"
    result_path = job_dir / "worker_result.json"
    output_dir = job_dir / "motion_ensemble"
    _write_json_atomic(static_input, {"pockets": _portable_static_pockets(static_record)})
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--structure-id",
        structure_id,
        "--prepared",
        str(prepared_path),
        "--prepared-sha256",
        str(structure["prepared_structure_sha256"]),
        "--static-pocket-input",
        str(static_input),
        "--output-dir",
        str(output_dir),
        "--result-path",
        str(result_path),
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(job_dir, ignore_errors=True)
        return _worker_failure(
            structure_id,
            str(structure["prepared_structure_sha256"]),
            f"worker_timeout_after_{timeout_seconds}s",
            runtime_seconds=round(time.perf_counter() - started, 6),
        )
    try:
        if not result_path.is_file():
            stderr = (completed.stderr or "").strip().replace("\r", " ").replace("\n", " ")
            detail = stderr[-500:] if stderr else f"worker_exit_code={completed.returncode}"
            return _worker_failure(
                structure_id,
                str(structure["prepared_structure_sha256"]),
                f"worker_no_result: {detail}",
                runtime_seconds=round(time.perf_counter() - started, 6),
            )
        record = _read_json(result_path)
        record["parent_worker_runtime_seconds"] = round(time.perf_counter() - started, 6)
        record["worker_exit_code"] = int(completed.returncode)
        if completed.returncode != 0 and record.get("status") == "completed":
            raise RI4RunError(f"Worker exited with code {completed.returncode}")
        return record
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--recovery-report", type=Path, default=DEFAULT_RECOVERY)
    parser.add_argument("--run", dest="run_path", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--all-structures", action="store_true")
    parser.add_argument("--max-structures", type=int, default=DEFAULT_PILOT_SIZE)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry prior failed/resource-blocked records with the current worker",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--structure-id", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--prepared", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--prepared-sha256", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--static-pocket-input", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--output-dir", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--result-path", default=None, help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.worker:
        required = (
            args.structure_id,
            args.prepared,
            args.prepared_sha256,
            args.static_pocket_input,
            args.output_dir,
            args.result_path,
        )
        if any(value is None for value in required):
            raise RI4RunError("RI-4 worker arguments are incomplete")
        return _run_worker(args)

    if args.workers != 1:
        raise RI4RunError("RI-4 uses exactly one heavy worker under safe-16gb")
    batch_size = _validate_batch_size(args.batch_size)
    timeout_seconds = _validate_timeout(args.timeout_seconds)
    if args.all_structures and args.max_structures != DEFAULT_PILOT_SIZE:
        raise RI4RunError("Use either --all-structures or --max-structures, not both")
    if not args.all_structures and args.max_structures < 1:
        raise RI4RunError("--max-structures must be positive")

    preflight_path = _resolve(args.preflight)
    manifest_path = _resolve(args.manifest)
    static_run_path = _resolve(args.static_run)
    recovery_path = _resolve(args.recovery_report)
    run_path = _resolve(args.run_path)
    work_dir = _resolve(args.work_dir)
    preflight = _load_motion_preflight(preflight_path)
    manifest_payload = _read_json(manifest_path)
    selected_manifest, selected_case_ids, selected_structure_ids = _selected_manifest(
        manifest_payload,
        preflight,
    )
    static_run = _read_json(static_run_path)
    if static_run.get("schema_version") != RUN_SCHEMA_VERSION:
        raise RI4RunError("Unexpected RI-3 static run schema")
    _validate_run(static_run, manifest_payload)
    static_records = _load_detector_records(static_run)
    static_structures = {
        _normalize_structure_id(key): raw for key, raw in static_run.get("records", {}).items()
    }
    structures = {
        _normalize_structure_id(item["structure_id"]): item
        for item in manifest_payload.get("structures", [])
    }
    for structure_id in selected_structure_ids:
        if structure_id not in static_records or static_records[structure_id].status != "completed":
            raise RI4RunError(f"RI-4 structure has no completed static record: {structure_id}")
        if structure_id not in structures or structure_id not in static_structures:
            raise RI4RunError(f"RI-4 structure is absent from runtime inputs: {structure_id}")
    truths = _load_truths(
        _read_json(recovery_path),
        selected_case_ids,
        manifest_payload["manifest_sha256"],
    )

    if run_path.is_file():
        run = _read_json(run_path)
        if run.get("schema_version") != SCHEMA_VERSION:
            raise RI4RunError("Existing RI-4 run has an unexpected schema")
        if run.get("preflight_sha256") != _sha256_file(preflight_path):
            raise RI4RunError("Existing RI-4 run belongs to a different preflight")
        if run.get("manifest_sha256") != selected_manifest.manifest_sha256:
            raise RI4RunError("Existing RI-4 run belongs to a different case manifest")
        if run.get("source_fingerprints") != _source_fingerprints():
            raise RI4RunError("RI-4 source code changed since the run was created")
    else:
        run = _initial_run_payload(
            preflight_path=preflight_path,
            preflight=preflight,
            manifest=selected_manifest,
            selected_case_ids=selected_case_ids,
            selected_structure_ids=selected_structure_ids,
        )
    if run.get("cohort", {}).get("case_ids") != list(selected_case_ids):
        raise RI4RunError("Existing RI-4 run case list differs from preflight")
    if run.get("cohort", {}).get("structure_ids") != list(selected_structure_ids):
        raise RI4RunError("Existing RI-4 run structure list differs from preflight")

    run["source_fingerprints"] = _source_fingerprints()
    run["execution"].update(
        {
            "checkpoint_batch_size": batch_size,
            "worker_timeout_seconds": timeout_seconds,
            "workers": 1,
            "motion_execution_started": True,
        }
    )
    run["status"] = "running"
    run["updated_at_utc"] = _utc_now()
    _write_json_atomic(run_path, run)

    existing = run.get("records", {})
    remaining = [
        structure_id
        for structure_id in selected_structure_ids
        if structure_id not in existing
        or (args.retry_failed and existing[structure_id].get("status") != "completed")
    ]
    selected = remaining if args.all_structures else remaining[: args.max_structures]
    work_dir.mkdir(parents=True, exist_ok=True)
    print(
        "RI-4 motion development: "
        f"selected={len(selected)} remaining={len(remaining)} "
        f"cohort={len(selected_structure_ids)} workers=1 profile={SAFE_16GB.name}",
        flush=True,
    )
    for index, structure_id in enumerate(selected, start=1):
        print(
            f"[{index}/{len(selected)}] {structure_id}: motion ensemble + accepted-frame detector",
            flush=True,
        )
        run["records"][structure_id] = _run_one_structure(
            structure_id=structure_id,
            structure=structures[structure_id],
            static_record=static_records[structure_id],
            work_dir=work_dir,
            timeout_seconds=timeout_seconds,
        )
        run["counts"] = _record_counts(run)
        run["quality_counts"] = _quality_counts(run)
        run["updated_at_utc"] = _utc_now()
        if index % batch_size == 0 or index == len(selected):
            _write_json_atomic(run_path, run)
            print(
                "checkpoint "
                f"completed={run['counts']['completed']} "
                f"resource_blocked={run['counts']['resource_blocked']} "
                f"failed={run['counts']['failed']}",
                flush=True,
            )

    _finalize_run(
        run,
        selected_manifest=selected_manifest,
        static_records=static_records,
        truths=truths,
    )
    run["source_fingerprints"] = _source_fingerprints()
    run["run_sha256"] = _stable_hash(
        {key: value for key, value in run.items() if key != "run_sha256"}
    )
    _write_json_atomic(run_path, run)
    print(
        f"RI-4 motion development: {run['status']} "
        f"processed={len(run['records'])}/{len(selected_structure_ids)} "
        f"completed={run['counts']['completed']} "
        f"resource_blocked={run['counts']['resource_blocked']} "
        f"failed={run['counts']['failed']}",
    )
    if run.get("results", {}).get("integration_decision"):
        decision = run["results"]["integration_decision"]
        print(
            "motion integration decision: "
            f"{decision['decision']} "
            f"top3_dcc_static={decision['static_primary_recall']} "
            f"top3_dcc_motion={decision['motion_primary_recall']}",
        )
    print(f"run report: {run_path}")
    print("canonical ranking: unchanged; sealed evaluation: closed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RI4RunError as exc:
        print(f"RI-4 runner error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
