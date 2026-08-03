"""Run the protocol-frozen RI-5 sealed BioVoid static evaluation.

The sealed split is opened only after an explicit command-line authorization,
an exact source/preparation audit, a family-disjointness check, and creation of
the one-way local ledger. Detector workers receive prepared apo structures and
structure-level hashes only. Holo coordinates are loaded later by the parent
evaluator and remain in ignored runtime storage.

This runner evaluates the canonical static arm. The RI-4 motion arm remains
experimental and was not eligible for canonical integration, so it is not
silently promoted by the sealed run.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_ri3_static_development import (  # noqa: E402
    _download_holo,
    _ground_truth_from_payload,
    _ground_truth_result,
    _representative_chain_pairs,
)
from scripts.materialize_ri3_preflight import (  # noqa: E402
    DEFAULT_MAX_COMPRESSED_BYTES,
    MAX_MEMBER_RANGE,
    MaterializationError,
    _load_archive_context,
    _materialize_member,
    _prepare_member,
    _reuse_preparation,
)
from scripts.run_ri3_static_development import (  # noqa: E402
    _run_record,
)
from src.benchmark_v1 import (  # noqa: E402
    BenchmarkCase,
    BenchmarkManifest,
    EvaluatorGroundTruth,
    SealedHoldoutLedger,
    evaluate_case,
    evaluate_split,
    phase6_frozen_protocol_v1,
)
from src.cryptobench_adapter import build_target_sites  # noqa: E402
from src.cryptobench_archive import ZipMember, member_map  # noqa: E402
from src.evaluator_format import DetectorEvaluationRecord, EvaluatorPocket  # noqa: E402
from src.static_detector import static_detector_config_sha256  # noqa: E402


DEFAULT_METADATA_DIR = REPO_ROOT / "data/runtime/cryptobench-source/metadata"
DEFAULT_LOCK = REPO_ROOT / "local-private/research/ri-1-lock-v1.json"
DEFAULT_MEMBER_INDEX = REPO_ROOT / "data/runtime/ri3/cryptobench-cif-member-index-v1.json"
DEFAULT_ROOT = REPO_ROOT / "data/runtime/ri5"
DEFAULT_PREPARATION_REPORT = DEFAULT_ROOT / "sealed-preparation-v1.json"
DEFAULT_MANIFEST = DEFAULT_ROOT / "sealed-runtime-manifest-v1.json"
DEFAULT_LEDGER = DEFAULT_ROOT / "sealed-holdout-ledger-v1.json"
DEFAULT_RUN = DEFAULT_ROOT / "sealed-static-run-v1.json"
DEFAULT_EVALUATION = DEFAULT_ROOT / "sealed-static-evaluation-v1.json"
DEFAULT_MEMBER_DIR = DEFAULT_ROOT / "materialized-members"
DEFAULT_PREPARED_DIR = DEFAULT_ROOT / "prepared-sealed"
DEFAULT_HOLO_DIR = DEFAULT_ROOT / "evaluator-holo"
DEFAULT_BATCH_SIZE = 5
DEFAULT_MAX_CASES = 222
SCHEMA_VERSION = "biovoid-ri5-sealed-static-run-v1"
MANIFEST_SCHEMA_VERSION = "biovoid-ri5-target-blind-runtime-manifest-v1"
PREPARATION_SCHEMA_VERSION = "biovoid-ri5-sealed-preparation-v1"
EVALUATION_SCHEMA_VERSION = "biovoid-ri5-sealed-static-evaluation-v1"
RCSB_DOWNLOAD_TEMPLATE = "https://files.rcsb.org/download/{structure_id}.cif"


class RI5RunError(RuntimeError):
    """Raised when the sealed evaluation contract cannot be satisfied."""


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RI5RunError(f"Required runtime file is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RI5RunError(f"Expected a JSON object: {path}")
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


def _normalize_id(value: str) -> str:
    normalized = str(value).strip().upper()
    if len(normalized) != 4 or not normalized.isalnum():
        raise RI5RunError(f"Invalid structure ID: {value!r}")
    return normalized


def _verified_json(path: Path, expected_sha256: str) -> dict[str, Any]:
    payload = _read_json(path)
    actual = _sha256_file(path)
    if actual != expected_sha256:
        raise RI5RunError(f"Locked metadata hash mismatch: {path}")
    return payload


def _sealed_ids(folds: Mapping[str, Any]) -> tuple[str, ...]:
    raw = folds.get("test")
    if not isinstance(raw, list):
        raise RI5RunError("Locked folds.json has no test list")
    ids = tuple(sorted(_normalize_id(value) for value in raw))
    if len(ids) != 222 or len(set(ids)) != len(ids):
        raise RI5RunError(f"Expected 222 unique sealed structures, found {len(ids)}")
    other = {
        _normalize_id(value)
        for fold in ("train-0", "train-1", "train-2", "train-3")
        for value in folds.get(fold, [])
    }
    overlap = sorted(set(ids) & other)
    if overlap:
        raise RI5RunError("Sealed structure IDs overlap another fold: " + ", ".join(overlap))
    return ids


def _source_inputs(
    metadata_dir: Path,
    lock_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], tuple[str, ...]]:
    lock = _read_json(lock_path)
    metadata_files = lock["dataset"]["metadata_files"]
    dataset = _verified_json(metadata_dir / "dataset.json", metadata_files["dataset.json"]["sha256"])
    folds = _verified_json(metadata_dir / "folds.json", metadata_files["folds.json"]["sha256"])
    sealed_ids = _sealed_ids(folds)
    missing = sorted(set(sealed_ids) - {_normalize_id(value) for value in dataset})
    if missing:
        raise RI5RunError("Sealed metadata is missing structures: " + ", ".join(missing))
    return lock, dataset, folds, sealed_ids


def _member_lookup(index_path: Path) -> dict[str, ZipMember]:
    index = _read_json(index_path)
    members = []
    for raw in index.get("members", []):
        members.append(
            ZipMember(
                name=str(raw["name"]),
                compression_method=int(raw["compression_method"]),
                flags=int(raw["flags"]),
                crc32=int(str(raw["crc32"]), 16),
                compressed_size=int(raw["compressed_size"]),
                uncompressed_size=int(raw["uncompressed_size"]),
                local_header_offset=int(raw["local_header_offset"]),
            )
        )
    return dict(member_map(tuple(members)))


def _load_preparation_records(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    payload = _read_json(path)
    if payload.get("schema_version") != PREPARATION_SCHEMA_VERSION:
        raise RI5RunError("Existing RI-5 preparation report has an unexpected schema")
    records: dict[str, dict[str, Any]] = {}
    for raw in payload.get("records", []):
        structure_id = _normalize_id(raw.get("structure_id", ""))
        records[structure_id] = raw
    return records


def _preparation_report(
    *,
    lock: Mapping[str, Any],
    sealed_ids: tuple[str, ...],
    records: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    counts = Counter(str(record.get("status", "unknown")) for record in records.values())
    payload: dict[str, Any] = {
        "schema_version": PREPARATION_SCHEMA_VERSION,
        "status": "complete" if len(records) == len(sealed_ids) and counts.get("eligible") == len(sealed_ids) else "partial",
        "split": "sealed",
        "snapshot_id": lock["dataset"]["snapshot_id"],
        "structure_count": len(sealed_ids),
        "structure_ids_sha256": _stable_hash(list(sealed_ids)),
        "archive": {
            "file_id": lock["dataset"]["structure_archive"]["file_id"],
            "sha256": lock["dataset"]["structure_archive"]["sha256"],
            "size": lock["dataset"]["structure_archive"]["size"],
            "full_archive_downloaded": False,
            "materialization_mode": "http-range-local-header-and-member-data",
        },
        "counts": dict(sorted(counts.items())),
        "sealed_evaluation_authorized": False,
        "records": [records[key] for key in sorted(records)],
        "updated_at_utc": _utc_now(),
    }
    payload["report_sha256"] = _stable_hash(
        {key: value for key, value in payload.items() if key not in {"updated_at_utc", "report_sha256"}}
    )
    return payload


def _prepare_sealed_inputs(
    *,
    lock: Mapping[str, Any],
    dataset: Mapping[str, Any],
    sealed_ids: tuple[str, ...],
    member_index_path: Path,
    report_path: Path,
    member_dir: Path,
    prepared_dir: Path,
    max_compressed_bytes: int,
) -> dict[str, Any]:
    lookup = _member_lookup(member_index_path)
    selected_members: dict[str, ZipMember] = {}
    for structure_id in sealed_ids:
        member = lookup.get(f"cif-files/{structure_id.casefold()}.cif")
        if member is None:
            raise RI5RunError(f"CIF member is missing from index: {structure_id}")
        if member.compressed_size > MAX_MEMBER_RANGE:
            raise RI5RunError(f"CIF member exceeds per-member safety limit: {structure_id}")
        selected_members[structure_id] = member
    compressed_budget = sum(member.compressed_size for member in selected_members.values())
    if compressed_budget > max_compressed_bytes:
        raise RI5RunError(
            f"Selected sealed compressed bytes exceed safety budget: {compressed_budget} > {max_compressed_bytes}"
        )

    records = _load_preparation_records(report_path)
    pending = [structure_id for structure_id in sealed_ids if records.get(structure_id, {}).get("status") != "eligible"]
    print(
        f"RI-5 preparation: {len(sealed_ids)} structures; "
        f"compressed member budget={compressed_budget / (1024 * 1024):.1f} MiB; pending={len(pending)}",
        flush=True,
    )
    session = requests.Session()
    session.headers.update({"User-Agent": "BioVoid/0.1 RI-5 sealed preparation"})
    try:
        download_url, archive_size, archive, _ = _load_archive_context(
            session, lock, member_index_path
        )
        for index, structure_id in enumerate(pending, start=1):
            member = selected_members[structure_id]
            member_path = member_dir / f"{structure_id}.cif"
            base: dict[str, Any] = {
                "structure_id": structure_id,
                "split": "sealed",
                "member": {
                    "name": member.name,
                    "crc32": f"{member.crc32:08x}",
                    "compressed_size": member.compressed_size,
                    "uncompressed_size": member.uncompressed_size,
                },
            }
            try:
                prepared = _reuse_preparation(member_path, prepared_dir, structure_id, member)
                compressed_bytes = 0
                if prepared is None:
                    input_sha256, compressed_bytes = _materialize_member(
                        session, download_url, archive_size, member, member_path
                    )
                    prepared = _prepare_member(
                        member_path,
                        prepared_dir,
                        structure_id,
                        dataset[structure_id.casefold()],
                        snapshot_id=lock["dataset"]["snapshot_id"],
                        archive=archive,
                        member=member,
                    )
                base.update(
                    {
                        "status": "eligible",
                        "compressed_bytes_read": compressed_bytes,
                        "source_file_sha256": prepared["input_sha256"],
                        "preparation": prepared,
                    }
                )
            except (MaterializationError, OSError, requests.RequestException, ValueError) as exc:
                base.update({"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"})
            records[structure_id] = base
            print(
                f"[{index}/{len(pending)}] {structure_id}: {base['status']}",
                flush=True,
            )
            _write_json_atomic(report_path, _preparation_report(lock=lock, sealed_ids=sealed_ids, records=records))
    finally:
        session.close()

    report = _preparation_report(lock=lock, sealed_ids=sealed_ids, records=records)
    _write_json_atomic(report_path, report)
    if report["status"] != "complete":
        raise RI5RunError("RI-5 preparation did not produce an eligible record for every sealed structure")
    return report


def _build_runtime_manifest(
    *,
    lock: Mapping[str, Any],
    dataset: Mapping[str, Any],
    sealed_ids: tuple[str, ...],
    preparation: Mapping[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    prep_by_id = {
        _normalize_id(raw["structure_id"]): raw for raw in preparation.get("records", [])
    }
    scoped_dataset = {
        structure_id.casefold(): dataset[structure_id.casefold()] for structure_id in sealed_ids
    }
    sites = build_target_sites(scoped_dataset, dataset_id="cryptobench", split="sealed")
    cases: list[BenchmarkCase] = []
    structures: list[dict[str, Any]] = []
    for structure_id in sealed_ids:
        raw = prep_by_id[structure_id]
        prep = raw.get("preparation", {})
        if raw.get("status") != "eligible" or prep.get("status") != "eligible":
            raise RI5RunError(f"Sealed preparation is not eligible: {structure_id}")
        structures.append(
            {
                "structure_id": structure_id,
                "prepared_path": prep["prepared_path"],
                "prepared_structure_sha256": prep["prepared_sha256"],
                "preparation_config_sha256": prep["preparation_config_sha256"],
                "preparation_report_sha256": prep["preparation_report_sha256"],
                "protein_atom_count": prep["protein_atom_count"],
                "protein_residue_count": prep["protein_residue_count"],
                "warnings": prep.get("warnings", []),
            }
        )
    prep_by_id = {item["structure_id"]: item for item in structures}
    for site in sites:
        prepared = prep_by_id[site.apo_pdb_id]
        cases.append(
            BenchmarkCase(
                case_id=site.case_id,
                structure_id=site.apo_pdb_id,
                family_id=site.family_id,
                split="sealed",
                prepared_structure_sha256=prepared["prepared_structure_sha256"],
                preparation_config_sha256=prepared["preparation_config_sha256"],
            )
        )
    manifest = BenchmarkManifest(cases=tuple(cases))
    protocol = phase6_frozen_protocol_v1()
    payload: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset_id": "cryptobench",
        "split": "sealed",
        "snapshot_id": lock["dataset"]["snapshot_id"],
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
            "holo_coordinates_in_manifest": False,
        },
        "sealed_split": {
            "case_rows_opened_after_explicit_authorization": True,
            "raw_structures_ignored": True,
            "source_archive_full_downloaded": False,
        },
    }
    payload["manifest_sha256"] = _stable_hash(payload)
    _write_json_atomic(manifest_path, payload)
    return payload


def _validate_target_blind_manifest(manifest: Mapping[str, Any]) -> None:
    expected = _stable_hash({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    if manifest.get("manifest_sha256") != expected:
        raise RI5RunError("RI-5 runtime manifest hash mismatch")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise RI5RunError("Unexpected RI-5 runtime manifest schema")
    if manifest.get("split") != "sealed" or manifest.get("structure_count") != 222:
        raise RI5RunError("RI-5 manifest does not describe the locked sealed cohort")
    if manifest.get("detector_boundary", {}).get("evaluator_fields_in_manifest") is not False:
        raise RI5RunError("Evaluator fields are not excluded from the detector manifest")
    forbidden = {
        "holo_pdb_id",
        "holo_chain",
        "ligand",
        "ligand_center",
        "ligand_atoms",
        "target_center",
        "target_residues",
        "hit_label",
        "apo_pocket_selection",
    }
    encoded = json.dumps(manifest, ensure_ascii=True).lower()
    for key in forbidden:
        if f'"{key}"' in encoded:
            raise RI5RunError(f"Evaluator field leaked into RI-5 detector manifest: {key}")


def _family_audit(
    dataset: Mapping[str, Any],
    folds: Mapping[str, Any],
    sealed_ids: tuple[str, ...],
) -> dict[str, Any]:
    def families(ids: list[Any]) -> set[str]:
        sites = build_target_sites(
            {str(value).casefold(): dataset[str(value).casefold()] for value in ids},
            dataset_id="cryptobench",
            split="development",
        )
        return {site.family_id for site in sites}

    train_ids = [value for fold in ("train-0", "train-1", "train-2") for value in folds.get(fold, [])]
    validation_ids = list(folds.get("train-3", []))
    sealed_families = families(list(sealed_ids))
    train_families = families(train_ids)
    validation_families = families(validation_ids)
    return {
        "schema_version": "biovoid-ri5-leakage-audit-v1",
        "dataset_snapshot_id": "cryptobench-osf-pz4a9-20260801",
        "sealed_structure_count": len(sealed_ids),
        "sealed_family_count": len(sealed_families),
        "development_family_count": len(train_families),
        "validation_family_count": len(validation_families),
        "sealed_vs_development_overlap": sorted(sealed_families & train_families),
        "sealed_vs_validation_overlap": sorted(sealed_families & validation_families),
        "canonical_static_training_data": "none_geometry_only",
        "motion_training_data": "none_experimental_nma_only",
        "pocketminer_sealed_arm": "not_run_deferred",
        "historical_holdout_used": False,
        "detector_evaluator_boundary": "target_blind_manifest_then_parent_evaluator",
        "status": "pass" if not sealed_families & (train_families | validation_families) else "fail",
    }


def _authorize_ledger(
    *,
    ledger_path: Path,
    manifest: Mapping[str, Any],
    explicit_user_authorization: bool,
) -> dict[str, Any]:
    protocol = phase6_frozen_protocol_v1()
    benchmark_manifest = BenchmarkManifest(
        cases=tuple(BenchmarkCase(**raw) for raw in manifest["benchmark_manifest"]["cases"])
    )
    if manifest["protocol"]["protocol_sha256"] != protocol.protocol_sha256:
        raise RI5RunError("RI-5 protocol hash differs from executable frozen protocol")
    ledger = SealedHoldoutLedger(ledger_path)
    return ledger.authorize_once(
        protocol=protocol,
        manifest=benchmark_manifest,
        explicit_user_authorization=explicit_user_authorization,
    )


def _resume_ledger(*, ledger_path: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    ledger = _read_json(ledger_path)
    if ledger.get("schema_version") != "sealed-holdout-ledger-v1":
        raise RI5RunError("Existing sealed ledger has an unexpected schema")
    if ledger.get("opened") is not True:
        raise RI5RunError("Existing sealed ledger is not open")
    if ledger.get("manifest_sha256") != manifest.get("benchmark_manifest", {}).get("manifest_sha256"):
        raise RI5RunError("Existing sealed ledger belongs to another manifest")
    if ledger.get("protocol_sha256") != phase6_frozen_protocol_v1().protocol_sha256:
        raise RI5RunError("Existing sealed ledger belongs to another protocol")
    return ledger


def _parse_detector_records(run: Mapping[str, Any]) -> dict[str, DetectorEvaluationRecord]:
    records: dict[str, DetectorEvaluationRecord] = {}
    for structure_id, raw in run.get("records", {}).items():
        detector = raw.get("detector_record")
        if not isinstance(detector, Mapping):
            raise RI5RunError(f"Missing sealed detector record: {structure_id}")
        pockets = tuple(
            EvaluatorPocket(
                pocket_id=str(item["pocket_id"]),
                center=tuple(float(value) for value in item["center"]),
                volume=float(item["volume"]) if item.get("volume") is not None else None,
                rank=int(item["rank"]),
                score=float(item["score"]) if item.get("score") is not None else None,
                raw=dict(item.get("raw", {})),
            )
            for item in detector.get("pockets", [])
        )
        normalized = _normalize_id(structure_id)
        records[normalized] = DetectorEvaluationRecord(
            schema_version=str(detector["schema_version"]),
            detector=str(detector["detector"]),
            structure_id=normalized,
            status=str(detector["status"]),
            pockets=pockets,
            error=detector.get("error"),
            provenance=dict(detector.get("provenance") or {}),
        )
    if len(records) != 222:
        raise RI5RunError(f"Expected 222 sealed detector records, found {len(records)}")
    return records


def _stored_ground_truth_payload(record: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = record.get("ground_truth")
    if not isinstance(payload, Mapping):
        raise RI5RunError("Sealed evaluator record has no ground-truth payload")
    nested = payload.get("ground_truth")
    if "case_id" not in payload and isinstance(nested, Mapping):
        return nested
    return payload


def _initial_run(manifest: Mapping[str, Any], ledger: Mapping[str, Any]) -> dict[str, Any]:
    protocol = phase6_frozen_protocol_v1()
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"ri5-sealed-static-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "status": "not_started",
        "manifest_sha256": manifest["manifest_sha256"],
        "protocol_sha256": protocol.protocol_sha256,
        "ledger_sha256": _stable_hash(ledger),
        "detector": {
            "name": "biovoid_static",
            "version": "canonical-static-v1",
            "config_sha256": static_detector_config_sha256(),
            "ranking_contract": "canonical-static-v1-volume-descending",
        },
        "execution": {
            "resource_profile": "safe-16gb",
            "workers": 1,
            "nma_started": False,
            "sealed_evaluation_authorized": True,
            "target_blind_detector_inputs": True,
        },
        "records": {},
        "counts": {"completed": 0, "resource_blocked": 0, "failed": 0},
        "evaluation": {"status": "deferred_until_detector_complete"},
    }


def _record_counts(run: Mapping[str, Any]) -> dict[str, int]:
    counts = {"completed": 0, "resource_blocked": 0, "failed": 0}
    for raw in run.get("records", {}).values():
        status = str(raw.get("status", ""))
        if status in counts:
            counts[status] += 1
    return counts


def _run_static_arm(
    *,
    manifest: Mapping[str, Any],
    ledger: Mapping[str, Any],
    run_path: Path,
    batch_size: int,
) -> dict[str, Any]:
    _validate_target_blind_manifest(manifest)
    run = _read_json(run_path) if run_path.is_file() else _initial_run(manifest, ledger)
    if run.get("manifest_sha256") != manifest["manifest_sha256"]:
        raise RI5RunError("Existing RI-5 run belongs to another manifest")
    if run.get("protocol_sha256") != phase6_frozen_protocol_v1().protocol_sha256:
        raise RI5RunError("Existing RI-5 run belongs to another protocol")
    structures = {str(item["structure_id"]): item for item in manifest["structures"]}
    remaining = [key for key in sorted(structures) if key not in run.get("records", {})]
    for index, structure_id in enumerate(remaining, start=1):
        print(f"[{index}/{len(remaining)}] {structure_id}: sealed static detector", flush=True)
        record = _run_record(
            structures[structure_id],
            detector_config_sha256=run["detector"]["config_sha256"],
        )
        record["sealed_evaluation_authorized"] = True
        record["split"] = "sealed"
        run["records"][structure_id] = record
        run["counts"] = _record_counts(run)
        run["updated_at_utc"] = _utc_now()
        if index % batch_size == 0 or index == len(remaining):
            _write_json_atomic(run_path, run)
            print(f"checkpoint counts={run['counts']}", flush=True)
    run["counts"] = _record_counts(run)
    run["status"] = "complete" if len(run["records"]) == len(structures) else "partial"
    run["updated_at_utc"] = _utc_now()
    _write_json_atomic(run_path, run)
    if run["status"] != "complete":
        raise RI5RunError("RI-5 static arm ended without a terminal record for every structure")
    return run


def _evaluate_static_arm(
    *,
    manifest: Mapping[str, Any],
    run: Mapping[str, Any],
    ledger_path: Path,
    dataset: Mapping[str, Any],
    sealed_ids: tuple[str, ...],
    holo_dir: Path,
    evaluation_path: Path,
    batch_size: int,
) -> dict[str, Any]:
    sites = build_target_sites(
        {structure_id.casefold(): dataset[structure_id.casefold()] for structure_id in sealed_ids},
        dataset_id="cryptobench",
        split="sealed",
    )
    if len(sites) != int(manifest["case_count"]):
        raise RI5RunError("Sealed target-site count differs from the runtime manifest")
    report = _read_json(evaluation_path) if evaluation_path.is_file() else {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "status": "not_started",
        "manifest_sha256": manifest["manifest_sha256"],
        "protocol_sha256": phase6_frozen_protocol_v1().protocol_sha256,
        "detector_target_blind": True,
        "sealed_evaluation_authorized": True,
        "records": {},
    }
    if report.get("manifest_sha256") != manifest["manifest_sha256"]:
        raise RI5RunError("Existing sealed evaluation belongs to another manifest")
    structures = {str(item["structure_id"]): item for item in manifest["structures"]}
    session = requests.Session()
    session.headers.update({"User-Agent": "BioVoid/0.1 RI-5 sealed evaluator"})
    try:
        pending = [site for site in sites if site.case_id not in report["records"]]
        for index, site in enumerate(pending, start=1):
            prepared_path = (REPO_ROOT / str(structures[site.apo_pdb_id]["prepared_path"])).resolve()
            item: dict[str, Any] = {
                "case_id": site.case_id,
                "structure_id": site.apo_pdb_id,
                "representative_holo_id": site.representative.holo_pdb_id,
                "status": "alignment_unavailable",
                "ground_truth": None,
            }
            try:
                download = _download_holo(session, site.representative.holo_pdb_id, holo_dir)
                truth = _ground_truth_result(
                    site=site,
                    prepared_path=prepared_path,
                    holo_path=(REPO_ROOT / download["path"]).resolve(),
                    provenance_label="cryptobench-rcsb-sealed-representative-holo-v1",
                )
                item.update({"status": "completed_ground_truth", "download": download, "ground_truth": asdict(truth)})
            except Exception as exc:  # noqa: BLE001 - every sealed case stays accounted for
                item["error"] = f"{type(exc).__name__}: {exc}"
            report["records"][site.case_id] = item
            if index % batch_size == 0 or index == len(pending):
                report["status"] = "running"
                report["updated_at_utc"] = _utc_now()
                _write_json_atomic(evaluation_path, report)
                print(f"evaluator checkpoint {index}/{len(pending)}", flush=True)
    finally:
        session.close()

    complete = [raw for raw in report["records"].values() if raw.get("status") == "completed_ground_truth"]
    if len(complete) != len(sites):
        report["status"] = "partial"
        benchmark_manifest = BenchmarkManifest(
            cases=tuple(BenchmarkCase(**raw) for raw in manifest["benchmark_manifest"]["cases"])
        )
        truths = {
            case_id.casefold(): _ground_truth_from_payload(_stored_ground_truth_payload(raw))
            for case_id, raw in report["records"].items()
            if raw.get("status") == "completed_ground_truth" and raw.get("ground_truth")
        }
        detector_records = _parse_detector_records(run)
        centers_by_structure: dict[str, set[tuple[float, float, float]]] = {}
        for truth in truths.values():
            centers_by_structure.setdefault(truth.structure_id.upper(), set()).add(truth.ligand_center)
        binding_centers = {
            structure_id: tuple(sorted(centers))
            for structure_id, centers in centers_by_structure.items()
        }
        partial_cases = [
            case for case in benchmark_manifest.cases if case.case_id.casefold() in truths
        ]
        partial_evaluations = [
            evaluate_case(
                detector_records[case.structure_id.upper()],
                truths[case.case_id.casefold()],
                phase6_frozen_protocol_v1(),
                false_pocket_reference_centers=binding_centers.get(case.structure_id.upper()),
            )
            for case in partial_cases
        ]
        denominator = len(partial_evaluations)
        partial_metrics = {
            "denominator": denominator,
            "top_k_dcc_recall": {
                str(k): round(
                    sum(result.top_k_dcc_hits[k] for result in partial_evaluations) / denominator,
                    8,
                )
                for k in phase6_frozen_protocol_v1().top_k
            }
            if denominator
            else {},
            "top_k_dca_recall": {
                str(k): round(
                    sum(result.top_k_dca_hits[k] for result in partial_evaluations) / denominator,
                    8,
                )
                for k in phase6_frozen_protocol_v1().top_k
            }
            if denominator
            else {},
        }
        error_categories = Counter(
            str(raw.get("error", "unknown")).split(": ", 1)[-1]
            for raw in report["records"].values()
            if raw.get("status") != "completed_ground_truth"
        )
        report["summary"] = {
            "status": "partial_evaluator_coverage_not_for_claim",
            "completed_ground_truth": len(complete),
            "expected_cases": len(sites),
            "alignment_unavailable": len(sites) - len(complete),
            "residual_error_categories": dict(error_categories.most_common()),
            "partial_metrics_on_alignment_available_cases": partial_metrics,
            "scientific_superiority_claim_authorized": False,
        }
        report["updated_at_utc"] = _utc_now()
        report["report_sha256"] = _stable_hash(
            {key: value for key, value in report.items() if key != "report_sha256"}
        )
        _write_json_atomic(evaluation_path, report)
        return report

    truths = {
        case_id.casefold(): _ground_truth_from_payload(_stored_ground_truth_payload(raw))
        for case_id, raw in report["records"].items()
    }
    benchmark_manifest = BenchmarkManifest(
        cases=tuple(BenchmarkCase(**raw) for raw in manifest["benchmark_manifest"]["cases"])
    )
    detector_records = _parse_detector_records(run)
    centers_by_structure: dict[str, set[tuple[float, float, float]]] = {}
    for case in benchmark_manifest.cases:
        centers_by_structure.setdefault(case.structure_id.upper(), set()).add(
            truths[case.case_id.casefold()].ligand_center
        )
    binding_centers = {key: tuple(sorted(value)) for key, value in centers_by_structure.items()}
    summary = evaluate_split(
        detector="biovoid_static",
        split="sealed",
        records=detector_records,
        ground_truth=truths,
        binding_site_reference_centers=binding_centers,
        manifest=benchmark_manifest,
        protocol=phase6_frozen_protocol_v1(),
        sealed_ledger_path=ledger_path,
    )
    report["status"] = "complete"
    report["summary"] = {
        "status": "complete_sealed_static_evaluation",
        "protocol_result": summary,
        "scientific_superiority_claim_authorized": False,
        "motion_canonical_integration": "not_eligible_from_ri4_development",
    }
    report["updated_at_utc"] = _utc_now()
    report["report_sha256"] = _stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    _write_json_atomic(evaluation_path, report)
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize-sealed", action="store_true")
    parser.add_argument("--resume-sealed", action="store_true")
    parser.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA_DIR)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--member-index", type=Path, default=DEFAULT_MEMBER_INDEX)
    parser.add_argument("--preparation-report", type=Path, default=DEFAULT_PREPARATION_REPORT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--run", dest="run_path", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--evaluation", type=Path, default=DEFAULT_EVALUATION)
    parser.add_argument("--member-dir", type=Path, default=DEFAULT_MEMBER_DIR)
    parser.add_argument("--prepared-dir", type=Path, default=DEFAULT_PREPARED_DIR)
    parser.add_argument("--holo-dir", type=Path, default=DEFAULT_HOLO_DIR)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-compressed-bytes", type=int, default=DEFAULT_MAX_COMPRESSED_BYTES)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--static-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.batch_size < 1 or args.batch_size > 10:
        raise RI5RunError("--batch-size must be between 1 and 10")
    if not args.authorize_sealed and not args.resume_sealed:
        raise RI5RunError("RI-5 requires --authorize-sealed after explicit user authorization")
    if args.prepare_only and args.static_only:
        raise RI5RunError("Use only one of --prepare-only and --static-only")
    lock, dataset, folds, sealed_ids = _source_inputs(args.metadata_dir, args.lock)
    preparation = _prepare_sealed_inputs(
        lock=lock,
        dataset=dataset,
        sealed_ids=sealed_ids,
        member_index_path=args.member_index,
        report_path=args.preparation_report,
        member_dir=args.member_dir,
        prepared_dir=args.prepared_dir,
        max_compressed_bytes=args.max_compressed_bytes,
    )
    if args.prepare_only:
        print("RI-5 preparation complete; sealed ledger remains closed")
        return 0
    manifest = _build_runtime_manifest(
        lock=lock,
        dataset=dataset,
        sealed_ids=sealed_ids,
        preparation=preparation,
        manifest_path=args.manifest,
    )
    _validate_target_blind_manifest(manifest)
    audit = _family_audit(dataset, folds, sealed_ids)
    audit_path = args.manifest.with_name("sealed-leakage-audit-v1.json")
    _write_json_atomic(audit_path, audit)
    if audit["status"] != "pass":
        raise RI5RunError("RI-5 family leakage audit failed")
    ledger = (
        _resume_ledger(ledger_path=args.ledger, manifest=manifest)
        if args.resume_sealed
        else _authorize_ledger(
            ledger_path=args.ledger,
            manifest=manifest,
            explicit_user_authorization=args.authorize_sealed,
        )
    )
    if args.static_only:
        run = _run_static_arm(
            manifest=manifest,
            ledger=ledger,
            run_path=args.run_path,
            batch_size=args.batch_size,
        )
        print(f"RI-5 static arm: {run['status']} counts={run['counts']}")
        return 0
    run = _run_static_arm(
        manifest=manifest,
        ledger=ledger,
        run_path=args.run_path,
        batch_size=args.batch_size,
    )
    report = _evaluate_static_arm(
        manifest=manifest,
        run=run,
        ledger_path=args.ledger,
        dataset=dataset,
        sealed_ids=sealed_ids,
        holo_dir=args.holo_dir,
        evaluation_path=args.evaluation,
        batch_size=args.batch_size,
    )
    print(
        "RI-5 sealed static evaluation: "
        f"{report['status']} cases={manifest['case_count']} structures={manifest['structure_count']}"
    )
    print("canonical motion integration: unchanged; no superiority claim authorized")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RI5RunError as exc:
        print(f"RI-5 runner error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
