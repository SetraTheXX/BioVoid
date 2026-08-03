"""Run the bounded, target-blind RI-3 BioVoid static development arm.

This runner deliberately does not fetch holo structures, build external
baselines, run NMA, or open the sealed split. It materializes a target-blind
runtime manifest from the already verified local preparation and executes the
canonical static detector one structure at a time. All output is local,
ignored runtime evidence below ``data/runtime/ri3``.
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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.benchmark_v1 import (  # noqa: E402
    BenchmarkCase,
    BenchmarkManifest,
    phase6_frozen_protocol_v1,
)
from src.cryptobench_adapter import build_target_sites  # noqa: E402
from src.evaluator_format import (  # noqa: E402
    adapt_biovoid_pockets,
    failed_record,
    unavailable_record,
)
from src.resources import (  # noqa: E402
    ResourceLimitError,
    SAFE_16GB,
    get_process_memory_snapshot,
)
from src.static_detector import (  # noqa: E402
    detect_static_pockets,
    static_detector_config_sha256,
)


DEFAULT_METADATA_DIR = REPO_ROOT / "data/runtime/cryptobench-source/metadata"
DEFAULT_PREPARATION_REPORT = REPO_ROOT / "data/runtime/ri3/cryptobench-preparation-preflight-v1.json"
DEFAULT_MANIFEST = REPO_ROOT / "data/runtime/ri3/cryptobench-development-runtime-manifest-v1.json"
DEFAULT_RUN = REPO_ROOT / "data/runtime/ri3/ri3-static-development-run-v1.json"
RUN_SCHEMA_VERSION = "biovoid-ri3-static-development-run-v1"
MANIFEST_SCHEMA_VERSION = "biovoid-ri3-target-blind-runtime-manifest-v1"
DEFAULT_BATCH_SIZE = 10
DEFAULT_PILOT_SIZE = 3


class RI3RunError(RuntimeError):
    """Raised when an RI-3 runtime contract cannot be satisfied."""


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
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


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RI3RunError(f"Required local runtime file is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RI3RunError(f"Expected a JSON object: {path}")
    return payload


def _normalize_id(value: str) -> str:
    normalized = str(value).strip().upper()
    if len(normalized) != 4 or not normalized.isalnum():
        raise RI3RunError(f"Invalid structure ID: {value!r}")
    return normalized


def _development_ids(folds: Mapping[str, Any]) -> tuple[str, ...]:
    raw_ids = [
        value
        for fold_name in ("train-0", "train-1", "train-2")
        for value in folds.get(fold_name, [])
    ]
    normalized = tuple(sorted(_normalize_id(value) for value in raw_ids))
    if len(normalized) != len(set(normalized)):
        raise RI3RunError("Development folds contain duplicate structure IDs")
    if len(normalized) != 663:
        raise RI3RunError(f"Expected 663 development structures, found {len(normalized)}")
    return normalized


def _preparation_records(report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if report.get("schema_version") != "biovoid-ri3-preparation-preflight-v1":
        raise RI3RunError("Unexpected RI-3 preparation report schema")
    records: dict[str, dict[str, Any]] = {}
    for raw_record in report.get("records", []):
        structure_id = _normalize_id(raw_record.get("structure_id", ""))
        if structure_id in records:
            raise RI3RunError(f"Duplicate preparation record: {structure_id}")
        records[structure_id] = raw_record
    if len(records) != 663:
        raise RI3RunError(f"Expected 663 preparation records, found {len(records)}")
    return records


def _target_blind_manifest(
    *,
    metadata_dir: Path = DEFAULT_METADATA_DIR,
    preparation_report_path: Path = DEFAULT_PREPARATION_REPORT,
) -> dict[str, Any]:
    """Build a target-blind manifest from verified local preparation evidence."""
    dataset = _read_json(metadata_dir / "dataset.json")
    folds = _read_json(metadata_dir / "folds.json")
    if not all(isinstance(value, list) for value in dataset.values()):
        raise RI3RunError("CryptoBench dataset metadata has an unexpected shape")

    development_ids = _development_ids(folds)
    dataset_by_id = {
        _normalize_id(structure_id): observations
        for structure_id, observations in dataset.items()
    }
    missing_metadata = sorted(set(development_ids) - set(dataset_by_id))
    if missing_metadata:
        raise RI3RunError("Development metadata is missing: " + ", ".join(missing_metadata))

    preparations = _preparation_records(_read_json(preparation_report_path))
    missing_preparation = sorted(set(development_ids) - set(preparations))
    if missing_preparation:
        raise RI3RunError(
            "Development preparation is missing: " + ", ".join(missing_preparation)
        )

    sites = build_target_sites(
        {structure_id: dataset_by_id[structure_id] for structure_id in development_ids},
        dataset_id="cryptobench",
        split="development",
    )
    cases: list[BenchmarkCase] = []
    structures: list[dict[str, Any]] = []
    for structure_id in development_ids:
        record = preparations[structure_id]
        preparation = record.get("preparation", {})
        if record.get("status") != "eligible" or preparation.get("status") != "eligible":
            raise RI3RunError(f"Preparation record is not eligible: {structure_id}")
        structures.append(
            {
                "structure_id": structure_id,
                "prepared_path": preparation["prepared_path"],
                "prepared_structure_sha256": preparation["prepared_sha256"],
                "preparation_config_sha256": preparation["preparation_config_sha256"],
                "preparation_report_sha256": preparation["preparation_report_sha256"],
                "protein_atom_count": preparation["protein_atom_count"],
                "protein_residue_count": preparation["protein_residue_count"],
                "warnings": preparation.get("warnings", []),
            }
        )

    preparation_by_id = {item["structure_id"]: item for item in structures}
    for site in sites:
        prepared = preparation_by_id[site.apo_pdb_id]
        cases.append(
            BenchmarkCase(
                case_id=site.case_id,
                structure_id=site.apo_pdb_id,
                family_id=site.family_id,
                split="development",
                prepared_structure_sha256=prepared["prepared_structure_sha256"],
                preparation_config_sha256=prepared["preparation_config_sha256"],
            )
        )
    manifest = BenchmarkManifest(cases=tuple(cases))
    protocol = phase6_frozen_protocol_v1()
    payload: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset_id": "cryptobench",
        "split": "development",
        "protocol": protocol.to_manifest(),
        "benchmark_manifest": manifest.to_manifest(),
        "structures": structures,
        "structure_count": len(structures),
        "case_count": len(cases),
        "detector_boundary": {
            "target_blind": True,
            "detector_receives": [
                "structure_id",
                "prepared_structure_sha256",
                "preparation_config_sha256",
                "prepared_full_atom_structure_path",
            ],
            "evaluator_fields_in_manifest": False,
        },
    }
    payload["manifest_sha256"] = _stable_hash(payload)
    return payload


def _validate_manifest(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise RI3RunError("Unexpected target-blind runtime manifest schema")
    expected = _stable_hash(
        {key: value for key, value in payload.items() if key != "manifest_sha256"}
    )
    if payload.get("manifest_sha256") != expected:
        raise RI3RunError("Target-blind runtime manifest hash does not match its content")
    if payload.get("structure_count") != 663 or payload.get("case_count") != 825:
        raise RI3RunError("Unexpected development manifest coverage")
    protocol = payload.get("protocol")
    if not isinstance(protocol, Mapping) or not protocol.get("protocol_sha256"):
        raise RI3RunError("Frozen protocol is missing from the runtime manifest")
    benchmark_manifest = payload.get("benchmark_manifest")
    if not isinstance(benchmark_manifest, Mapping):
        raise RI3RunError("Benchmark manifest is missing from the runtime manifest")
    if len(payload.get("structures", [])) != 663:
        raise RI3RunError("Structure inputs are missing from the runtime manifest")
    if payload.get("detector_boundary", {}).get("evaluator_fields_in_manifest") is not False:
        raise RI3RunError("Evaluator fields are not explicitly excluded from the manifest")
    forbidden = {
        "holo_pdb_id",
        "holo_chain",
        "ligand",
        "ligand_center",
        "target_center",
        "target_residues",
        "hit_label",
    }
    encoded = json.dumps(payload, ensure_ascii=True).lower()
    for key in forbidden:
        if f'"{key}"' in encoded:
            raise RI3RunError(f"Evaluator field leaked into target-blind manifest: {key}")


def _validate_batch_size(value: int) -> int:
    if value < 1 or value > 10:
        raise RI3RunError("RI-3 checkpoint batch size must be between 1 and 10")
    return value


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
        raise RI3RunError("Unable to identify the local git commit") from exc
    return result.stdout.strip()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_fingerprints() -> dict[str, str]:
    return {
        "static_runner": _sha256_file(Path(__file__).resolve()),
        "static_detector": _sha256_file(REPO_ROOT / "src/static_detector.py"),
        "evaluator_format": _sha256_file(REPO_ROOT / "src/evaluator_format.py"),
    }


def _record_statuses(payload: Mapping[str, Any]) -> dict[str, int]:
    counts = {"completed": 0, "resource_blocked": 0, "failed": 0}
    for record in payload.get("records", {}).values():
        status = str(record.get("status", ""))
        if status in counts:
            counts[status] += 1
    return counts


def _run_record(
    structure: Mapping[str, Any],
    *,
    detector_config_sha256: str,
) -> dict[str, Any]:
    structure_id = str(structure["structure_id"])
    started = time.perf_counter()
    before = get_process_memory_snapshot()
    atom_count = int(structure["protein_atom_count"])
    prepared_path = (REPO_ROOT / str(structure["prepared_path"])).resolve()
    common = {
        "structure_id": structure_id,
        "prepared_structure_sha256": structure["prepared_structure_sha256"],
        "preparation_config_sha256": structure["preparation_config_sha256"],
        "prepared_path": str(prepared_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "protein_atom_count_preflight": atom_count,
        "preparation_warnings": list(structure.get("warnings", [])),
        "detector_version": "canonical-static-v1",
        "detector_config_sha256": detector_config_sha256,
        "ranking_contract": "canonical-static-v1-volume-descending",
        "score_used": False,
        "nma_started": False,
        "sealed_evaluation_authorized": False,
    }
    if atom_count > SAFE_16GB.max_static_atoms:
        return {
            **common,
            "status": "resource_blocked",
            "detector_record": asdict(
                unavailable_record(
                    "biovoid_static",
                    structure_id,
                    f"safe-16gb static atom limit exceeded: {atom_count} > "
                    f"{SAFE_16GB.max_static_atoms}",
                )
            ),
            "error": f"protein_atom_count={atom_count} exceeds safe-16gb max_static_atoms="
            f"{SAFE_16GB.max_static_atoms}",
            "runtime_seconds": round(time.perf_counter() - started, 6),
            "peak_rss_bytes": before.peak_rss_bytes,
        }
    if not prepared_path.is_file():
        raise RI3RunError(f"Prepared detector structure is missing: {prepared_path}")

    try:
        detection = detect_static_pockets(
            prepared_path,
            prepared_sha256=str(structure["prepared_structure_sha256"]),
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
            },
        )
        after = get_process_memory_snapshot()
        return {
            **common,
            "status": "completed",
            "detector_record": asdict(detector_record),
            "candidate_count": detection.candidate_count,
            "pocket_count": len(detection.pockets),
            "detector_warnings": list(detection.warnings),
            "detector_atom_count": detection.protein_atom_count,
            "runtime_seconds": round(time.perf_counter() - started, 6),
            "peak_rss_bytes": max(before.peak_rss_bytes, after.peak_rss_bytes),
        }
    except ResourceLimitError as exc:
        return {
            **common,
            "status": "resource_blocked",
            "detector_record": asdict(unavailable_record("biovoid_static", structure_id, str(exc))),
            "error": str(exc),
            "runtime_seconds": round(time.perf_counter() - started, 6),
            "peak_rss_bytes": before.peak_rss_bytes,
        }
    except Exception as exc:  # noqa: BLE001 - failed records stay in the denominator
        return {
            **common,
            "status": "failed",
            "detector_record": asdict(
                failed_record("biovoid_static", structure_id, f"{type(exc).__name__}: {exc}")
            ),
            "error": f"{type(exc).__name__}: {exc}",
            "runtime_seconds": round(time.perf_counter() - started, 6),
            "peak_rss_bytes": before.peak_rss_bytes,
        }


def _initial_run_payload(manifest: Mapping[str, Any], *, git_commit: str) -> dict[str, Any]:
    protocol = manifest["protocol"]
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": f"ri3-static-development-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "status": "not_started",
        "git_commit": git_commit,
        "source_fingerprints": _source_fingerprints(),
        "manifest_sha256": manifest["manifest_sha256"],
        "protocol_sha256": protocol["protocol_sha256"],
        "detector": {
            "name": "biovoid_static",
            "version": "canonical-static-v1",
            "config_sha256": static_detector_config_sha256(),
            "ranking_contract": "canonical-static-v1-volume-descending",
        },
        "execution": {
            "resource_profile": "safe-16gb",
            "workers": 1,
            "checkpoint_batch_size": DEFAULT_BATCH_SIZE,
            "nma_started": False,
            "sealed_evaluation_authorized": False,
        },
        "external_baselines": {
            "fpocket": "unavailable_exact_local_environment",
            "p2rank": "unavailable_exact_local_environment",
            "pocketminer": "deferred_unavailable",
        },
        "evaluation": {
            "status": "deferred_missing_holo_coordinates",
            "dcc_dca_computed": False,
            "scientific_superiority_claim_authorized": False,
            "reason": (
                "The locked local metadata contains evaluator selectors but no holo coordinates; "
                "no target coordinates are passed to the detector or fabricated for evaluation."
            ),
        },
        "records": {},
        "counts": {"completed": 0, "resource_blocked": 0, "failed": 0},
    }


def _validate_run(payload: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != RUN_SCHEMA_VERSION:
        raise RI3RunError("Unexpected RI-3 static run schema")
    if payload.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise RI3RunError("Run manifest hash differs from the runtime manifest")
    if payload.get("protocol_sha256") != manifest.get("protocol", {}).get("protocol_sha256"):
        raise RI3RunError("Run protocol hash differs from the frozen protocol")
    if payload.get("execution", {}).get("workers") != 1:
        raise RI3RunError("RI-3 static runner is single-worker only")
    if payload.get("execution", {}).get("nma_started") is not False:
        raise RI3RunError("NMA flag is not closed")
    if payload.get("execution", {}).get("sealed_evaluation_authorized") is not False:
        raise RI3RunError("Sealed evaluation flag is not closed")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--preparation-report", type=Path, default=DEFAULT_PREPARATION_REPORT)
    parser.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA_DIR)
    parser.add_argument("--run", dest="run_path", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--build-manifest", action="store_true")
    parser.add_argument("--all-development", action="store_true")
    parser.add_argument("--max-structures", type=int, default=DEFAULT_PILOT_SIZE)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--workers", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.workers != 1:
        raise RI3RunError("Use exactly one worker for the safe-16gb RI-3 static arm")
    batch_size = _validate_batch_size(args.batch_size)
    if args.all_development and args.max_structures != DEFAULT_PILOT_SIZE:
        raise RI3RunError("Use either --all-development or --max-structures, not both")
    if not args.all_development and args.max_structures < 1:
        raise RI3RunError("--max-structures must be positive")

    manifest_path = args.manifest if args.manifest.is_absolute() else REPO_ROOT / args.manifest
    if args.build_manifest or not manifest_path.is_file():
        manifest = _target_blind_manifest(
            metadata_dir=args.metadata_dir,
            preparation_report_path=args.preparation_report,
        )
        _write_json_atomic(manifest_path, manifest)
    else:
        manifest = _read_json(manifest_path)
    _validate_manifest(manifest)

    run_path = args.run_path if args.run_path.is_absolute() else REPO_ROOT / args.run_path
    if run_path.is_file():
        run = _read_json(run_path)
        _validate_run(run, manifest)
    else:
        run = _initial_run_payload(manifest, git_commit=_git_commit())
    current_fingerprints = _source_fingerprints()
    previous_fingerprints = run.get("source_fingerprints")
    if previous_fingerprints is not None and previous_fingerprints != current_fingerprints:
        raise RI3RunError("Runner/detector source changed since the static run was created")
    run["source_fingerprints"] = current_fingerprints
    run["git_commit"] = _git_commit()
    run["execution"]["checkpoint_batch_size"] = batch_size
    run["status"] = "running"
    run["updated_at_utc"] = _utc_now()

    structures = {item["structure_id"]: item for item in manifest["structures"]}
    structure_ids = tuple(sorted(structures))
    remaining = [structure_id for structure_id in structure_ids if structure_id not in run["records"]]
    selected = remaining if args.all_development else remaining[: args.max_structures]
    detector_config_sha256 = run["detector"]["config_sha256"]
    for index, structure_id in enumerate(selected, start=1):
        print(f"[{index}/{len(selected)}] {structure_id}: static detector", flush=True)
        run["records"][structure_id] = _run_record(
            structures[structure_id],
            detector_config_sha256=detector_config_sha256,
        )
        run["counts"] = _record_statuses(run)
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

    total = len(structure_ids)
    processed = len(run["records"])
    run["counts"] = _record_statuses(run)
    run["status"] = "complete" if processed == total else "partial"
    run["updated_at_utc"] = _utc_now()
    _write_json_atomic(run_path, run)
    print(
        f"RI-3 static development run: {run['status']} "
        f"processed={processed}/{total} "
        f"completed={run['counts']['completed']} "
        f"resource_blocked={run['counts']['resource_blocked']} "
        f"failed={run['counts']['failed']}",
    )
    print(f"run report: {run_path}")
    print("DCC/DCA: deferred; holo coordinates are not present in the locked local snapshot")
    print("NMA/sealed: closed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RI3RunError as exc:
        print(f"RI-3 runner error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
