"""Recover evaluator alignments with an explicit structural tie-break policy.

The frozen RI-3 evaluator rejects non-unique sequence mappings. This bounded
secondary arm may resolve those mappings using protein C-alpha fit RMSD only;
ligand coordinates are used only after the protein transform is selected.
Recovered records remain diagnostic until the policy is separately re-locked.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
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
    DEFAULT_HOLO_DIR,
    DEFAULT_METADATA_DIR,
    DEFAULT_RUNTIME_MANIFEST,
    DEFAULT_STATIC_RUN,
    _case_evaluation_payload,
    _download_holo,
    _ground_truth_result,
    _load_detector_records,
    _load_manifest_cases,
    _load_prepared_path,
    _load_sites,
    _read_json,
    _utc_now,
)
from src.benchmark_v1 import evaluate_case, phase6_frozen_protocol_v1  # noqa: E402
from src.ground_truth_alignment import AlignmentPolicy, GroundTruthAlignmentError  # noqa: E402


DEFAULT_PRIMARY_REPORT = REPO_ROOT / "data/runtime/ri3/ri3-static-development-evaluation-v1.json"
DEFAULT_REPORT = REPO_ROOT / (
    "data/runtime/ri3/ri3-static-development-evaluation-structural-recovery-v1.json"
)
REPORT_SCHEMA_VERSION = "biovoid-ri3-static-development-evaluation-structural-recovery-v1"
RECOVERY_POLICY = AlignmentPolicy(
    policy_version="ground-truth-alignment-v2-structural-recovery",
    ambiguous_sequence_policy="structural_fit",
    maximum_alignment_candidates=128,
    maximum_alignment_combinations=512,
    structural_tie_rmsd_tolerance_angstrom=0.001,
)


class RecoveryError(RuntimeError):
    """Raised when the evaluator recovery contract cannot be satisfied."""


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


def _copy_json(value: Any) -> Any:
    return deepcopy(value)


def _initial_report(
    *,
    primary_report: Mapping[str, Any],
    static_run: Mapping[str, Any],
) -> dict[str, Any]:
    protocol = phase6_frozen_protocol_v1()
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": (
            "ri3-static-evaluator-structural-recovery-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        ),
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "status": "not_started",
        "primary_report_sha256": _sha256_file(DEFAULT_PRIMARY_REPORT),
        "manifest_sha256": primary_report["manifest_sha256"],
        "protocol_sha256": protocol.protocol_sha256,
        "static_run_git_commit": static_run.get("git_commit"),
        "alignment_policy": asdict(RECOVERY_POLICY),
        "detector_target_blind": True,
        "sealed_evaluation_authorized": False,
        "records": {},
        "counts": {
            "completed_ground_truth": 0,
            "alignment_unavailable": 0,
            "download_failed": 0,
            "structural_recovered": 0,
        },
        "summary": {
            "status": "not_ready",
            "frozen_protocol_preserved": True,
            "scientific_superiority_claim_authorized": False,
        },
    }


def _recompute_counts(report: Mapping[str, Any]) -> dict[str, int]:
    counts = {
        "completed_ground_truth": 0,
        "alignment_unavailable": 0,
        "download_failed": 0,
        "structural_recovered": 0,
    }
    for record in report.get("records", {}).values():
        status = record.get("status")
        if status in {"completed_ground_truth", "alignment_unavailable", "download_failed"}:
            counts[status] += 1
        if record.get("recovery", {}).get("resolved_by_structural_fit") is True:
            counts["structural_recovered"] += 1
    return counts


def _diagnostics(report: Mapping[str, Any]) -> dict[str, Any]:
    available = [
        record
        for record in report.get("records", {}).values()
        if record.get("status") == "completed_ground_truth"
        and record.get("case_evaluation")
    ]
    top_k = (1, 3, 5)

    def recall(metric: str, k: int) -> float:
        if not available:
            return 0.0
        return round(
            sum(
                bool(record["case_evaluation"][metric].get(str(k), False))
                for record in available
            )
            / len(available),
            8,
        )

    errors = Counter(
        str(record.get("error", "")).split(": ", 1)[-1]
        for record in report.get("records", {}).values()
        if record.get("status") != "completed_ground_truth"
    )
    return {
        "status": "diagnostic_only_not_for_claim",
        "ground_truth_available_case_count": len(available),
        "ground_truth_unavailable_case_count": len(report.get("records", {})) - len(available),
        "structural_recovered_case_count": report["counts"]["structural_recovered"],
        "top_k_dcc_recall_on_recovery_available_ground_truth": {
            str(k): recall("top_k_dcc_hits", k) for k in top_k
        },
        "top_k_dca_recall_on_recovery_available_ground_truth": {
            str(k): recall("top_k_dca_hits", k) for k in top_k
        },
        "residual_error_categories": dict(errors.most_common()),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_RUNTIME_MANIFEST)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--primary-report", type=Path, default=DEFAULT_PRIMARY_REPORT)
    parser.add_argument("--holo-dir", type=Path, default=DEFAULT_HOLO_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--all-unavailable", action="store_true")
    parser.add_argument("--max-cases", type=int, default=244)
    parser.add_argument("--batch-size", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.max_cases < 1 or args.batch_size < 1 or args.batch_size > 10:
        raise RecoveryError("max-cases must be positive and batch-size must be between 1 and 10")
    manifest_path = args.manifest if args.manifest.is_absolute() else REPO_ROOT / args.manifest
    static_run_path = args.static_run if args.static_run.is_absolute() else REPO_ROOT / args.static_run
    primary_path = (
        args.primary_report
        if args.primary_report.is_absolute()
        else REPO_ROOT / args.primary_report
    )
    report_path = args.report if args.report.is_absolute() else REPO_ROOT / args.report
    manifest = _read_json(manifest_path)
    static_run = _read_json(static_run_path)
    primary = _read_json(primary_path)
    if primary.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise RecoveryError("Primary evaluator report manifest hash mismatch")
    if primary.get("detector_target_blind") is not True:
        raise RecoveryError("Primary evaluator report is not target-blind")
    detector_records = _load_detector_records(static_run)
    report = (
        _read_json(report_path)
        if report_path.is_file()
        else _initial_report(primary_report=primary, static_run=static_run)
    )
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise RecoveryError("Unexpected structural recovery report schema")
    if report.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise RecoveryError("Recovery report manifest hash mismatch")
    if report.get("protocol_sha256") != phase6_frozen_protocol_v1().protocol_sha256:
        raise RecoveryError("Recovery report protocol hash mismatch")
    if report.get("alignment_policy") != asdict(RECOVERY_POLICY):
        raise RecoveryError("Recovery alignment policy changed after checkpoint")

    sites = _load_sites(args.metadata_dir if args.metadata_dir.is_absolute() else REPO_ROOT / args.metadata_dir)
    benchmark_manifest = _load_manifest_cases(manifest)
    if len(sites) != 825:
        raise RecoveryError(f"Expected 825 evaluator target sites, found {len(sites)}")
    prepared_paths = {
        structure_id: _load_prepared_path(manifest, structure_id)
        for structure_id in {site.apo_pdb_id for site in sites.values()}
    }

    if not report.get("records"):
        report["records"] = {
            case_id: _copy_json(raw) for case_id, raw in primary.get("records", {}).items()
        }
        for raw in report["records"].values():
            raw.setdefault("recovery", {})
    pending = [
        case.case_id
        for case in benchmark_manifest.cases
        if report["records"].get(case.case_id, {}).get("status") != "completed_ground_truth"
    ]
    selected = pending if args.all_unavailable else pending[: args.max_cases]
    session = requests.Session()
    session.headers.update({"User-Agent": "BioVoid/0.1 RI-3 evaluator structural recovery"})
    holo_dir = args.holo_dir if args.holo_dir.is_absolute() else REPO_ROOT / args.holo_dir

    report["status"] = "running"
    report["updated_at_utc"] = _utc_now()
    for index, case_id in enumerate(selected, start=1):
        site = sites[case_id]
        structure_id = site.apo_pdb_id.upper()
        started = time.perf_counter()
        print(
            f"[{index}/{len(selected)}] {case_id} ({structure_id}) structural recovery",
            flush=True,
        )
        record = report["records"].setdefault(
            case_id,
            {
                "case_id": case_id,
                "structure_id": structure_id,
                "representative_holo_id": site.representative.holo_pdb_id,
            },
        )
        record["recovery"] = {
            "policy_version": RECOVERY_POLICY.policy_version,
            "resolved_by_structural_fit": False,
        }
        try:
            download = _download_holo(session, site.representative.holo_pdb_id.upper(), holo_dir)
            record["holo_source"] = download
            alignment = _ground_truth_result(
                site=site,
                prepared_path=prepared_paths[structure_id],
                holo_path=(REPO_ROOT / download["path"]).resolve(),
                policy=RECOVERY_POLICY,
                provenance_label="cryptobench-rcsb-representative-holo-structural-recovery-v2",
            )
            record["status"] = "completed_ground_truth"
            record["error"] = None
            record["ground_truth"] = asdict(alignment.ground_truth)
            record["alignment"] = {
                "status": alignment.status,
                "matched_residue_count": alignment.matched_residue_count,
                "sequence_identity": alignment.sequence_identity,
                "fit_rmsd_angstrom": alignment.fit_rmsd_angstrom,
                "alignment_sha256": alignment.alignment_sha256,
                "ground_truth_sha256": alignment.ground_truth_sha256,
                "warnings": list(alignment.warnings),
            }
            record["recovery"]["resolved_by_structural_fit"] = any(
                warning == "ambiguous_sequence_alignment_resolved_by_structural_fit"
                for warning in alignment.warnings
            )
            record["case_evaluation"] = _case_evaluation_payload(
                evaluate_case(
                    detector_records[structure_id],
                    alignment.ground_truth,
                    phase6_frozen_protocol_v1(),
                )
            )
        except GroundTruthAlignmentError as exc:
            record["status"] = "alignment_unavailable"
            record["error"] = f"{type(exc).__name__}: {exc}"
            record["ground_truth"] = None
            record.pop("case_evaluation", None)
        except (requests.RequestException, OSError, ValueError, KeyError) as exc:
            record["status"] = "download_failed"
            record["error"] = f"{type(exc).__name__}: {exc}"
            record["ground_truth"] = None
            record.pop("case_evaluation", None)
        record["runtime_seconds"] = round(time.perf_counter() - started, 6)
        report["counts"] = _recompute_counts(report)
        report["updated_at_utc"] = _utc_now()
        if index % args.batch_size == 0 or index == len(selected):
            _write_json_atomic(report_path, report)
            print(f"checkpoint counts={report['counts']}", flush=True)

    report["counts"] = _recompute_counts(report)
    report["summary"] = {
        "status": "structural_recovery_diagnostic",
        "frozen_protocol_preserved": True,
        "scientific_superiority_claim_authorized": False,
        "diagnostic": _diagnostics(report),
    }
    report["status"] = "complete" if not [
        case_id
        for case_id in pending
        if report["records"].get(case_id, {}).get("status") != "completed_ground_truth"
    ] else "partial"
    report["updated_at_utc"] = _utc_now()
    _write_json_atomic(report_path, report)
    print(
        f"RI-3 structural evaluator recovery: {report['status']} "
        f"ground_truth={report['counts']['completed_ground_truth']} "
        f"structural_recovered={report['counts']['structural_recovered']} "
        f"alignment_unavailable={report['counts']['alignment_unavailable']}",
    )
    print(f"recovery report: {report_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RecoveryError as exc:
        print(f"RI-3 structural recovery error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
