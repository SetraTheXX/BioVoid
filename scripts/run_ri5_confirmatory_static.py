"""Prepare, run, and evaluate the one-time RI-5 confirmatory static holdout."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_ri3_static_development import (  # noqa: E402
    _download_holo,
    _ground_truth_from_payload,
    _ground_truth_result,
    _load_detector_records,
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
from scripts.run_ri3_static_development import _run_record  # noqa: E402
from scripts.run_ri5_sealed_static import _member_lookup  # noqa: E402
from src.benchmark_v1 import (  # noqa: E402
    BenchmarkCase,
    BenchmarkManifest,
    evaluate_split,
    phase6_frozen_protocol_v1,
)
from src.confirmatory_holdout import (  # noqa: E402
    ConfirmatoryHoldoutError,
    EVALUATOR_SCHEMA_VERSION,
    LEDGER_SCHEMA_VERSION,
    authorize_confirmatory_holdout,
    validate_detector_source_lock,
)
from src.cryptobench_adapter import CryptoBenchObservation, CryptoBenchTargetSite  # noqa: E402
from src.evaluator_v3 import (  # noqa: E402
    EVALUATOR_V3_POLICY,
    classify_ineligibility,
    stable_hash,
)
from src.static_detector import static_detector_config_sha256  # noqa: E402


DEFAULT_RI1_LOCK = REPO_ROOT / "local-private/research/ri-1-lock-v1.json"
DEFAULT_MEMBER_INDEX = REPO_ROOT / "data/runtime/ri3/cryptobench-cif-member-index-v1.json"
DEFAULT_ROOT = REPO_ROOT / "data/runtime/ri5-confirmatory"
DEFAULT_SOURCE_LOCK = DEFAULT_ROOT / "confirmatory-source-lock-v1.json"
DEFAULT_EVALUATOR_LOCK = DEFAULT_ROOT / "confirmatory-evaluator-lock-v1.json"
DEFAULT_OPEN_CONTRACT = DEFAULT_ROOT / "confirmatory-open-contract-v1.json"
DEFAULT_LEDGER = DEFAULT_ROOT / "confirmatory-ledger-v1.json"
DEFAULT_PREPARATION = DEFAULT_ROOT / "confirmatory-preparation-v1.json"
DEFAULT_MANIFEST = DEFAULT_ROOT / "confirmatory-runtime-manifest-v1.json"
DEFAULT_STATIC_RUN = DEFAULT_ROOT / "confirmatory-static-run-v1.json"
DEFAULT_EVALUATION = DEFAULT_ROOT / "confirmatory-static-evaluation-v1.json"
DEFAULT_FPOCKET_REPORT = DEFAULT_ROOT / "external-baselines-v1/fpocket-confirmatory-v1.json"
DEFAULT_P2RANK_REPORT = DEFAULT_ROOT / "external-baselines-v1/p2rank-confirmatory-v1.json"
DEFAULT_MEMBER_DIR = DEFAULT_ROOT / "materialized-members"
DEFAULT_PREPARED_DIR = DEFAULT_ROOT / "prepared-holdout"
DEFAULT_HOLO_DIR = DEFAULT_ROOT / "evaluator-holo"
PREPARATION_SCHEMA = "biovoid-ri5-confirmatory-preparation-v1"
MANIFEST_SCHEMA = "biovoid-ri5-confirmatory-runtime-manifest-v1"
RUN_SCHEMA = "biovoid-ri5-confirmatory-static-run-v1"
EVALUATION_SCHEMA = "biovoid-ri5-confirmatory-static-evaluation-v1"


class ConfirmatoryRunError(RuntimeError):
    """Raised when confirmatory execution violates its frozen boundary."""


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfirmatoryRunError(f"Required runtime file is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConfirmatoryRunError(f"Expected JSON object: {path}")
    return payload


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _validate_open_contract(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != "biovoid-ri5-confirmatory-open-contract-v1":
        raise ConfirmatoryRunError("Unexpected confirmatory open-contract schema")
    if payload.get("status") != "ready_for_single_authorized_open":
        raise ConfirmatoryRunError("Confirmatory open contract is not ready")
    if payload.get("contains_evaluator_fields") is not False:
        raise ConfirmatoryRunError("Open contract contains evaluator fields")
    expected = stable_hash(
        {key: value for key, value in payload.items() if key != "open_contract_sha256"}
    )
    if payload.get("open_contract_sha256") != expected:
        raise ConfirmatoryRunError("Confirmatory open-contract hash mismatch")


def _preparation_report(
    source: Mapping[str, Any], records: Mapping[str, Mapping[str, Any]], ri1: Mapping[str, Any]
) -> dict[str, Any]:
    counts = Counter(str(record.get("status", "unknown")) for record in records.values())
    payload: dict[str, Any] = {
        "schema_version": PREPARATION_SCHEMA,
        "status": (
            "complete"
            if len(records) == source["structure_count"]
            and counts.get("eligible", 0) == source["structure_count"]
            else "partial"
        ),
        "source_lock_sha256": source["source_lock_sha256"],
        "snapshot_id": source["snapshot_id"],
        "source_fold": source["source_fold"],
        "structure_count": source["structure_count"],
        "archive": {
            "file_id": ri1["dataset"]["structure_archive"]["file_id"],
            "sha256": ri1["dataset"]["structure_archive"]["sha256"],
            "size": ri1["dataset"]["structure_archive"]["size"],
            "full_archive_downloaded": False,
            "materialization_mode": "http-range-local-header-and-member-data",
        },
        "counts": dict(sorted(counts.items())),
        "detector_started": False,
        "evaluator_opened": False,
        "records": [records[key] for key in sorted(records)],
        "updated_at_utc": _utc_now(),
    }
    payload["report_sha256"] = stable_hash(
        {key: value for key, value in payload.items() if key not in {"updated_at_utc", "report_sha256"}}
    )
    return payload


def _prepare(
    *,
    source: Mapping[str, Any],
    ri1: Mapping[str, Any],
    member_index: Path,
    report_path: Path,
    member_dir: Path,
    prepared_dir: Path,
    max_compressed_bytes: int,
) -> dict[str, Any]:
    lookup = _member_lookup(member_index)
    structures = {str(item["structure_id"]): item for item in source["structures"]}
    members = {}
    for structure_id in structures:
        member = lookup.get(f"cif-files/{structure_id.casefold()}.cif")
        if member is None:
            raise ConfirmatoryRunError(f"CIF member is missing from index: {structure_id}")
        if member.compressed_size > MAX_MEMBER_RANGE:
            raise ConfirmatoryRunError(f"CIF member exceeds safety limit: {structure_id}")
        members[structure_id] = member
    compressed_budget = sum(member.compressed_size for member in members.values())
    if compressed_budget > max_compressed_bytes:
        raise ConfirmatoryRunError(
            f"Confirmatory compressed budget exceeds safety limit: {compressed_budget}"
        )
    existing = _read(report_path) if report_path.is_file() else {"records": []}
    if report_path.is_file() and existing.get("schema_version") != PREPARATION_SCHEMA:
        raise ConfirmatoryRunError("Existing confirmatory preparation schema mismatch")
    records = {str(item["structure_id"]): item for item in existing.get("records", [])}
    pending = [key for key in sorted(structures) if records.get(key, {}).get("status") != "eligible"]
    print(
        f"RI-5 confirmatory preparation: structures={len(structures)} "
        f"compressed={compressed_budget / 1024 / 1024:.1f} MiB pending={len(pending)}",
        flush=True,
    )
    session = requests.Session()
    session.headers.update({"User-Agent": "BioVoid/0.1 RI-5 confirmatory preparation"})
    try:
        download_url, archive_size, archive, _ = _load_archive_context(session, ri1, member_index)
        for index, structure_id in enumerate(pending, start=1):
            member = members[structure_id]
            member_path = member_dir / f"{structure_id}.cif"
            base: dict[str, Any] = {
                "structure_id": structure_id,
                "status": "unavailable",
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
                    _, compressed_bytes = _materialize_member(
                        session, download_url, archive_size, member, member_path
                    )
                    records_for_preparation = [
                        {"apo_chain": "-".join(structures[structure_id]["selected_chains"])}
                    ]
                    prepared = _prepare_member(
                        member_path,
                        prepared_dir,
                        structure_id,
                        records_for_preparation,
                        snapshot_id=source["snapshot_id"],
                        archive=archive,
                        member=member,
                    )
                base.update(
                    {
                        "status": "eligible",
                        "compressed_bytes_read": compressed_bytes,
                        "preparation": prepared,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - every source remains accounted for
                base["error"] = f"{type(exc).__name__}: {exc}"
            records[structure_id] = base
            if index % 5 == 0 or index == len(pending):
                _write(report_path, _preparation_report(source, records, ri1))
                print(f"preparation checkpoint {index}/{len(pending)}", flush=True)
    finally:
        session.close()
    report = _preparation_report(source, records, ri1)
    _write(report_path, report)
    if report["status"] != "complete":
        raise ConfirmatoryRunError("Confirmatory preparation is incomplete")
    return report


def _runtime_manifest(source: Mapping[str, Any], preparation: Mapping[str, Any]) -> dict[str, Any]:
    prepared = {str(item["structure_id"]): item for item in preparation["records"]}
    structures = []
    for source_item in source["structures"]:
        structure_id = str(source_item["structure_id"])
        raw = prepared[structure_id]
        if raw.get("status") != "eligible":
            raise ConfirmatoryRunError(f"Preparation is not eligible: {structure_id}")
        prep = raw["preparation"]
        structures.append(
            {
                "structure_id": structure_id,
                "family_id": source_item["family_id"],
                "prepared_path": prep["prepared_path"],
                "prepared_structure_sha256": prep["prepared_sha256"],
                "preparation_config_sha256": prep["preparation_config_sha256"],
                "preparation_report_sha256": prep["preparation_report_sha256"],
                "protein_atom_count": prep["protein_atom_count"],
                "protein_residue_count": prep["protein_residue_count"],
                "warnings": prep.get("warnings", []),
            }
        )
    payload: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA,
        "status": "target_blind_ready",
        "source_lock_sha256": source["source_lock_sha256"],
        "snapshot_id": source["snapshot_id"],
        "source_fold": source["source_fold"],
        "benchmark_role": source["benchmark_role"],
        "structure_count": len(structures),
        "case_count": source["case_count"],
        "structures": structures,
        "detector_boundary": source["detector_boundary"],
        "protocol": phase6_frozen_protocol_v1().to_manifest(),
    }
    payload["manifest_sha256"] = stable_hash(payload)
    return payload


def _validate_manifest(payload: Mapping[str, Any], source: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != MANIFEST_SCHEMA or payload.get("status") != "target_blind_ready":
        raise ConfirmatoryRunError("Unexpected confirmatory runtime manifest")
    if payload.get("source_lock_sha256") != source.get("source_lock_sha256"):
        raise ConfirmatoryRunError("Runtime manifest and source lock differ")
    if payload.get("structure_count") != 222 or payload.get("case_count") != 265:
        raise ConfirmatoryRunError("Confirmatory manifest cohort drifted")
    expected = stable_hash({key: value for key, value in payload.items() if key != "manifest_sha256"})
    if payload.get("manifest_sha256") != expected:
        raise ConfirmatoryRunError("Confirmatory runtime manifest hash mismatch")
    encoded = json.dumps(payload, ensure_ascii=True).lower()
    for key in ("holo_pdb_id", "ligand", "apo_pocket_selection", "target_center"):
        if f'"{key}"' in encoded:
            raise ConfirmatoryRunError(f"Evaluator field leaked into runtime manifest: {key}")


def _resume_ledger(path: Path, open_contract: Mapping[str, Any]) -> dict[str, Any]:
    ledger = _read(path)
    if ledger.get("schema_version") != LEDGER_SCHEMA_VERSION or ledger.get("opened") is not True:
        raise ConfirmatoryRunError("Confirmatory ledger is invalid")
    for key in ("source_lock_sha256", "evaluator_lock_sha256", "evaluator_v3_lock_sha256"):
        if ledger.get(key) != open_contract.get(key):
            raise ConfirmatoryRunError(f"Confirmatory ledger differs from open contract: {key}")
    expected = stable_hash({key: value for key, value in ledger.items() if key != "ledger_sha256"})
    if ledger.get("ledger_sha256") != expected:
        raise ConfirmatoryRunError("Confirmatory ledger hash mismatch")
    return ledger


def _validate_completed_baseline(
    path: Path, *, tool: str, manifest_sha256: str
) -> dict[str, Any]:
    report = _read(path)
    if report.get("schema_version") != "biovoid-ri5-confirmatory-external-baseline-v1":
        raise ConfirmatoryRunError(f"Unexpected {tool} confirmatory baseline schema")
    if report.get("tool") != tool or report.get("status") != "complete":
        raise ConfirmatoryRunError(f"{tool} confirmatory baseline is incomplete")
    if report.get("manifest_sha256") != manifest_sha256:
        raise ConfirmatoryRunError(f"{tool} confirmatory baseline belongs to another manifest")
    if report.get("target_blind") is not True or report.get("evaluator_opened") is not False:
        raise ConfirmatoryRunError(f"{tool} confirmatory baseline crossed evaluator boundary")
    if len(report.get("records", {})) != 222:
        raise ConfirmatoryRunError(f"{tool} confirmatory baseline coverage drifted")
    expected = stable_hash({key: value for key, value in report.items() if key != "report_sha256"})
    if report.get("report_sha256") != expected:
        raise ConfirmatoryRunError(f"{tool} confirmatory baseline report hash mismatch")
    return report


def _run_static(
    manifest: Mapping[str, Any], ledger: Mapping[str, Any], run_path: Path
) -> dict[str, Any]:
    run = _read(run_path) if run_path.is_file() else {
        "schema_version": RUN_SCHEMA,
        "status": "not_started",
        "manifest_sha256": manifest["manifest_sha256"],
        "ledger_sha256": ledger["ledger_sha256"],
        "detector": {
            "name": "biovoid_static",
            "version": "canonical-static-v1",
            "config_sha256": static_detector_config_sha256(),
        },
        "execution": {
            "resource_profile": "safe-16gb",
            "workers": 1,
            "nma_started": False,
            "target_blind": True,
        },
        "records": {},
        "counts": {"completed": 0, "resource_blocked": 0, "failed": 0},
    }
    if run.get("manifest_sha256") != manifest["manifest_sha256"]:
        raise ConfirmatoryRunError("Static checkpoint belongs to another manifest")
    structures = {str(item["structure_id"]): item for item in manifest["structures"]}
    pending = [key for key in sorted(structures) if key not in run["records"]]
    for index, structure_id in enumerate(pending, start=1):
        print(f"[{index}/{len(pending)}] confirmatory static {structure_id}", flush=True)
        record = _run_record(
            structures[structure_id],
            detector_config_sha256=run["detector"]["config_sha256"],
        )
        record["confirmatory_ledger_authorized"] = True
        record["split"] = "validation"
        run["records"][structure_id] = record
        run["counts"] = dict(
            Counter(str(item.get("status", "unknown")) for item in run["records"].values())
        )
        if index % 5 == 0 or index == len(pending):
            _write(run_path, run)
            print(f"static checkpoint counts={run['counts']}", flush=True)
    run["status"] = "complete" if len(run["records"]) == len(structures) else "partial"
    run["updated_at_utc"] = _utc_now()
    _write(run_path, run)
    return run


def _site_from_payload(raw: Mapping[str, Any]) -> CryptoBenchTargetSite:
    representative = CryptoBenchObservation(**raw["representative"])
    return CryptoBenchTargetSite(
        case_id=str(raw["case_id"]),
        dataset_id=str(raw["dataset_id"]),
        split="validation",
        apo_pdb_id=str(raw["apo_pdb_id"]),
        family_id=str(raw["family_id"]),
        required_apo_chains=tuple(raw["required_apo_chains"]),
        apo_pocket_residues=tuple(raw["apo_pocket_residues"]),
        representative=representative,
        observation_count=int(raw["observation_count"]),
    )


def _ground_truth_payload(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the canonical evaluator ground truth from an alignment result record."""
    payload = raw.get("ground_truth")
    if not isinstance(payload, Mapping):
        raise ConfirmatoryRunError("Confirmatory evaluator ground truth is not an object")
    nested = payload.get("ground_truth")
    if isinstance(nested, Mapping):
        return nested
    return payload


def _evaluate(
    *,
    manifest: Mapping[str, Any],
    run: Mapping[str, Any],
    ledger: Mapping[str, Any],
    evaluator_lock_path: Path,
    holo_dir: Path,
    evaluation_path: Path,
) -> dict[str, Any]:
    evaluator_lock = _read(evaluator_lock_path)
    if evaluator_lock.get("schema_version") != EVALUATOR_SCHEMA_VERSION:
        raise ConfirmatoryRunError("Unexpected confirmatory evaluator-lock schema")
    expected_evaluator_hash = stable_hash(
        {key: value for key, value in evaluator_lock.items() if key != "evaluator_lock_sha256"}
    )
    if evaluator_lock.get("evaluator_lock_sha256") != expected_evaluator_hash:
        raise ConfirmatoryRunError("Confirmatory evaluator-lock hash mismatch")
    if evaluator_lock["evaluator_lock_sha256"] != ledger["evaluator_lock_sha256"]:
        raise ConfirmatoryRunError("Evaluator lock is not bound to the open ledger")
    sites = tuple(_site_from_payload(raw) for raw in evaluator_lock["cases"])
    structures = {str(item["structure_id"]): item for item in manifest["structures"]}
    report = _read(evaluation_path) if evaluation_path.is_file() else {
        "schema_version": EVALUATION_SCHEMA,
        "status": "not_started",
        "manifest_sha256": manifest["manifest_sha256"],
        "ledger_sha256": ledger["ledger_sha256"],
        "evaluator_lock_sha256": evaluator_lock["evaluator_lock_sha256"],
        "alignment_policy": asdict(EVALUATOR_V3_POLICY),
        "detector_target_blind": True,
        "records": {},
    }
    if report.get("manifest_sha256") != manifest["manifest_sha256"]:
        raise ConfirmatoryRunError("Evaluator checkpoint belongs to another manifest")
    session = requests.Session()
    session.headers.update({"User-Agent": "BioVoid/0.1 RI-5 confirmatory evaluator"})
    try:
        pending = [site for site in sites if site.case_id not in report["records"]]
        for index, site in enumerate(pending, start=1):
            item: dict[str, Any] = {
                "case_id": site.case_id,
                "structure_id": site.apo_pdb_id,
                "status": "evaluator_ineligible",
                "ground_truth": None,
            }
            try:
                download = _download_holo(session, site.representative.holo_pdb_id, holo_dir)
                truth = _ground_truth_result(
                    site=site,
                    prepared_path=(REPO_ROOT / structures[site.apo_pdb_id]["prepared_path"]).resolve(),
                    holo_path=(REPO_ROOT / download["path"]).resolve(),
                    policy=EVALUATOR_V3_POLICY,
                    provenance_label="cryptobench-ri5-confirmatory-evaluator-v3",
                )
                item.update(
                    {
                        "status": "completed_ground_truth",
                        "ground_truth": asdict(truth),
                        "download": download,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - every case remains visible
                error = f"{type(exc).__name__}: {exc}"
                item["error"] = error
                item["reason_code"] = classify_ineligibility(error)
            report["records"][site.case_id] = item
            if index % 5 == 0 or index == len(pending):
                report["status"] = "running"
                _write(evaluation_path, report)
                print(f"evaluator checkpoint {index}/{len(pending)}", flush=True)
    finally:
        session.close()

    eligible = {
        case_id: raw
        for case_id, raw in report["records"].items()
        if raw.get("status") == "completed_ground_truth"
    }
    ineligible = {
        case_id: raw
        for case_id, raw in report["records"].items()
        if raw.get("status") == "evaluator_ineligible"
    }
    if len(eligible) + len(ineligible) != len(sites):
        raise ConfirmatoryRunError("Confirmatory evaluator has non-terminal cases")
    benchmark_cases = []
    site_map = {site.case_id: site for site in sites}
    for case_id in sorted(eligible):
        site = site_map[case_id]
        structure = structures[site.apo_pdb_id]
        benchmark_cases.append(
            BenchmarkCase(
                case_id=case_id,
                structure_id=site.apo_pdb_id,
                family_id=site.family_id,
                split="validation",
                prepared_structure_sha256=structure["prepared_structure_sha256"],
                preparation_config_sha256=structure["preparation_config_sha256"],
            )
        )
    eligible_manifest = BenchmarkManifest(cases=tuple(benchmark_cases))
    truths = {
        case_id.casefold(): _ground_truth_from_payload(_ground_truth_payload(raw))
        for case_id, raw in eligible.items()
    }
    detector_records = _load_detector_records(run, expected_count=222)
    centers: dict[str, set[tuple[float, float, float]]] = {}
    for truth in truths.values():
        centers.setdefault(truth.structure_id.upper(), set()).add(truth.ligand_center)
    summary = evaluate_split(
        detector="biovoid_static",
        split="validation",
        records=detector_records,
        ground_truth=truths,
        binding_site_reference_centers={key: tuple(sorted(value)) for key, value in centers.items()},
        manifest=eligible_manifest,
        protocol=phase6_frozen_protocol_v1(),
    )
    report["status"] = "complete"
    report["summary"] = {
        "status": "complete_local_blinded_static_confirmation",
        "planned_cases": len(sites),
        "evaluator_eligible": len(eligible),
        "evaluator_ineligible": len(ineligible),
        "ineligible_reason_counts": dict(
            sorted(Counter(str(raw.get("reason_code")) for raw in ineligible.values()).items())
        ),
        "protocol_result": summary,
        "external_replication": False,
        "scientific_superiority_claim_authorized": False,
        "motion_started": False,
    }
    report["updated_at_utc"] = _utc_now()
    report["report_sha256"] = stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    _write(evaluation_path, report)
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize-confirmatory", action="store_true")
    parser.add_argument("--resume-confirmatory", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--evaluate-only", action="store_true")
    parser.add_argument("--ri1-lock", type=Path, default=DEFAULT_RI1_LOCK)
    parser.add_argument("--member-index", type=Path, default=DEFAULT_MEMBER_INDEX)
    parser.add_argument("--source-lock", type=Path, default=DEFAULT_SOURCE_LOCK)
    parser.add_argument("--evaluator-lock", type=Path, default=DEFAULT_EVALUATOR_LOCK)
    parser.add_argument("--open-contract", type=Path, default=DEFAULT_OPEN_CONTRACT)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--preparation", type=Path, default=DEFAULT_PREPARATION)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--evaluation", type=Path, default=DEFAULT_EVALUATION)
    parser.add_argument("--fpocket-report", type=Path, default=DEFAULT_FPOCKET_REPORT)
    parser.add_argument("--p2rank-report", type=Path, default=DEFAULT_P2RANK_REPORT)
    parser.add_argument("--member-dir", type=Path, default=DEFAULT_MEMBER_DIR)
    parser.add_argument("--prepared-dir", type=Path, default=DEFAULT_PREPARED_DIR)
    parser.add_argument("--holo-dir", type=Path, default=DEFAULT_HOLO_DIR)
    parser.add_argument("--max-compressed-bytes", type=int, default=DEFAULT_MAX_COMPRESSED_BYTES)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    mode_count = sum((args.prepare_only, args.static_only, args.evaluate_only))
    if mode_count > 1:
        raise ConfirmatoryRunError("Choose only one execution mode")
    source = _read(args.source_lock)
    validate_detector_source_lock(source)
    open_contract = _read(args.open_contract)
    _validate_open_contract(open_contract)
    ri1 = _read(args.ri1_lock)
    preparation = _prepare(
        source=source,
        ri1=ri1,
        member_index=args.member_index,
        report_path=args.preparation,
        member_dir=args.member_dir,
        prepared_dir=args.prepared_dir,
        max_compressed_bytes=args.max_compressed_bytes,
    )
    manifest = _runtime_manifest(source, preparation)
    _validate_manifest(manifest, source)
    _write(args.manifest, manifest)
    if args.prepare_only:
        print("RI-5 confirmatory preparation complete; ledger remains closed")
        return 0
    if not args.authorize_confirmatory and not args.resume_confirmatory:
        raise ConfirmatoryRunError("Confirmatory execution requires explicit authorization or resume")
    ledger = (
        _resume_ledger(args.ledger, open_contract)
        if args.resume_confirmatory
        else authorize_confirmatory_holdout(
            args.ledger,
            source_lock_sha256=open_contract["source_lock_sha256"],
            evaluator_lock_sha256=open_contract["evaluator_lock_sha256"],
            evaluator_v3_lock_sha256=open_contract["evaluator_v3_lock_sha256"],
            protocol_sha256=phase6_frozen_protocol_v1().protocol_sha256,
            explicit_user_authorization=args.authorize_confirmatory,
        )
    )
    if args.evaluate_only:
        run = _read(args.static_run)
        if run.get("status") != "complete":
            raise ConfirmatoryRunError("Static arm must complete before evaluator opens")
        baselines = {
            "fpocket": _validate_completed_baseline(
                args.fpocket_report,
                tool="fpocket",
                manifest_sha256=manifest["manifest_sha256"],
            ),
            "p2rank": _validate_completed_baseline(
                args.p2rank_report,
                tool="p2rank",
                manifest_sha256=manifest["manifest_sha256"],
            ),
        }
        report = _evaluate(
            manifest=manifest,
            run=run,
            ledger=ledger,
            evaluator_lock_path=args.evaluator_lock,
            holo_dir=args.holo_dir,
            evaluation_path=args.evaluation,
        )
        report["baseline_report_sha256"] = {
            tool: baseline["report_sha256"] for tool, baseline in baselines.items()
        }
        report["report_sha256"] = stable_hash(
            {key: value for key, value in report.items() if key != "report_sha256"}
        )
        _write(args.evaluation, report)
        print(
            "RI-5 confirmatory evaluator complete: "
            f"eligible={report['summary']['evaluator_eligible']} "
            f"ineligible={report['summary']['evaluator_ineligible']}"
        )
        return 0
    run = _run_static(manifest, ledger, args.static_run)
    print(f"RI-5 confirmatory static: {run['status']} counts={run['counts']}")
    if args.static_only:
        return 0
    raise ConfirmatoryRunError(
        "Run external baselines before opening evaluator; resume with --evaluate-only"
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ConfirmatoryRunError, ConfirmatoryHoldoutError, MaterializationError) as exc:
        print(f"RI-5 confirmatory error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
