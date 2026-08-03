"""Build evaluator-only CryptoBench ground truth and score RI-3 static output.

The detector run is already complete and target-blind. This script is an
explicit evaluator arm: it may read the private CryptoBench metadata and
download representative holo structures into ignored runtime storage, but it
never modifies detector input or sealed data. It is checkpointed and bounded
to one network/alignment worker.
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

from src.benchmark_v1 import (  # noqa: E402
    BenchmarkCase,
    BenchmarkManifest,
    CaseEvaluation,
    EvaluatorGroundTruth,
    evaluate_case,
    evaluate_split,
    phase6_frozen_protocol_v1,
)
from src.cryptobench_adapter import build_target_sites  # noqa: E402
from src.evaluator_format import (  # noqa: E402
    DetectorEvaluationRecord,
    EvaluatorPocket,
)
from src.ground_truth_alignment import (  # noqa: E402
    AlignmentPolicy,
    ChainPair,
    GroundTruthAlignmentError,
    LigandSelector,
    build_aligned_ground_truth_from_files,
)


DEFAULT_METADATA_DIR = REPO_ROOT / "data/runtime/cryptobench-source/metadata"
DEFAULT_RUNTIME_MANIFEST = REPO_ROOT / "data/runtime/ri3/cryptobench-development-runtime-manifest-v1.json"
DEFAULT_STATIC_RUN = REPO_ROOT / "data/runtime/ri3/ri3-static-development-run-v1.json"
DEFAULT_HOLO_DIR = REPO_ROOT / "data/runtime/ri3/evaluator-holo"
DEFAULT_REPORT = REPO_ROOT / "data/runtime/ri3/ri3-static-development-evaluation-v1.json"
REPORT_SCHEMA_VERSION = "biovoid-ri3-static-development-evaluation-v1"
DEFAULT_BATCH_SIZE = 10
DEFAULT_PILOT_SIZE = 5
RCSB_DOWNLOAD_TEMPLATE = "https://files.rcsb.org/download/{structure_id}.cif"


class RI3EvaluationError(RuntimeError):
    """Raised when the evaluator contract cannot be satisfied."""


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
        raise RI3EvaluationError(f"Required runtime file is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RI3EvaluationError(f"Expected a JSON object: {path}")
    return payload


def _normalize_id(value: str) -> str:
    normalized = str(value).strip().upper()
    if len(normalized) != 4 or not normalized.isalnum():
        raise RI3EvaluationError(f"Invalid structure ID: {value!r}")
    return normalized


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_fingerprints() -> dict[str, str]:
    return {
        "evaluator_runner": _sha256_file(Path(__file__).resolve()),
        "ground_truth_alignment": _sha256_file(REPO_ROOT / "src/ground_truth_alignment.py"),
        "benchmark_protocol": _sha256_file(REPO_ROOT / "src/benchmark_v1.py"),
    }


def _validate_batch_size(value: int) -> int:
    if value < 1 or value > 10:
        raise RI3EvaluationError("RI-3 evaluator checkpoint batch size must be between 1 and 10")
    return value


def _load_sites(metadata_dir: Path) -> dict[str, Any]:
    dataset = _read_json(metadata_dir / "dataset.json")
    folds = _read_json(metadata_dir / "folds.json")
    development_ids = sorted(
        {
            _normalize_id(value)
            for fold_name in ("train-0", "train-1", "train-2")
            for value in folds.get(fold_name, [])
        }
    )
    dataset_by_id = {_normalize_id(key): value for key, value in dataset.items()}
    sites = build_target_sites(
        {structure_id: dataset_by_id[structure_id] for structure_id in development_ids},
        dataset_id="cryptobench",
        split="development",
    )
    return {site.case_id: site for site in sites}


def _load_manifest_cases(payload: Mapping[str, Any]) -> BenchmarkManifest:
    cases = tuple(BenchmarkCase(**case) for case in payload["benchmark_manifest"]["cases"])
    return BenchmarkManifest(cases=cases)


def _load_detector_records(
    static_run: Mapping[str, Any], *, expected_count: int = 663
) -> dict[str, DetectorEvaluationRecord]:
    if static_run.get("status") != "complete":
        raise RI3EvaluationError("Static RI-3 run is not complete")
    records: dict[str, DetectorEvaluationRecord] = {}
    for structure_id, raw in static_run.get("records", {}).items():
        detector_payload = raw.get("detector_record")
        if not isinstance(detector_payload, Mapping):
            raise RI3EvaluationError(f"Detector record is missing: {structure_id}")
        pockets = tuple(
            EvaluatorPocket(
                pocket_id=str(pocket["pocket_id"]),
                center=tuple(float(value) for value in pocket["center"]),
                volume=(float(pocket["volume"]) if pocket.get("volume") is not None else None),
                rank=int(pocket["rank"]),
                score=(float(pocket["score"]) if pocket.get("score") is not None else None),
                raw=dict(pocket.get("raw", {})),
            )
            for pocket in detector_payload.get("pockets", [])
        )
        normalized_id = _normalize_id(structure_id)
        records[normalized_id] = DetectorEvaluationRecord(
            schema_version=str(detector_payload["schema_version"]),
            detector=str(detector_payload["detector"]),
            structure_id=normalized_id,
            status=str(detector_payload["status"]),
            pockets=pockets,
            error=detector_payload.get("error"),
            provenance=dict(detector_payload.get("provenance") or {}),
        )
    if len(records) != expected_count:
        raise RI3EvaluationError(
            f"Expected {expected_count} detector records, found {len(records)}"
        )
    return records


def _load_prepared_path(manifest: Mapping[str, Any], structure_id: str) -> Path:
    for structure in manifest.get("structures", []):
        if _normalize_id(structure["structure_id"]) == structure_id:
            path = (REPO_ROOT / str(structure["prepared_path"])).resolve()
            if not path.is_file():
                raise RI3EvaluationError(f"Prepared structure is missing: {path}")
            return path
    raise RI3EvaluationError(f"Prepared structure is absent from manifest: {structure_id}")


def _split_chain_field(value: str) -> tuple[str, ...]:
    chains = tuple(part.strip() for part in str(value).split("-") if part.strip())
    if not chains:
        raise RI3EvaluationError(f"Chain field is empty: {value!r}")
    return chains


def _representative_chain_pairs(representative: Any) -> tuple[ChainPair, ...]:
    """Expand CryptoBench's hyphen-separated chain union for alignment."""
    apo_chains = _split_chain_field(representative.apo_chain)
    holo_chains = _split_chain_field(representative.holo_chain)
    if len(apo_chains) != len(holo_chains):
        raise GroundTruthAlignmentError(
            "Representative apo/holo chain unions have different lengths: "
            f"{representative.apo_chain!r} vs {representative.holo_chain!r}"
        )
    return tuple(
        ChainPair(apo_chain_id=apo_chain, holo_chain_id=holo_chain)
        for apo_chain, holo_chain in zip(apo_chains, holo_chains, strict=True)
    )


def _download_holo(
    session: requests.Session,
    structure_id: str,
    destination_dir: Path,
) -> dict[str, Any]:
    destination_dir.mkdir(parents=True, exist_ok=True)
    path = destination_dir / f"{structure_id.lower()}.cif"
    if path.is_file() and path.stat().st_size > 0:
        return {
            "status": "cached",
            "structure_id": structure_id,
            "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
            "url": RCSB_DOWNLOAD_TEMPLATE.format(structure_id=structure_id),
        }
    url = RCSB_DOWNLOAD_TEMPLATE.format(structure_id=structure_id)
    response = session.get(url, timeout=(30, 120))
    response.raise_for_status()
    content = response.content
    if not content or b"_atom_site." not in content:
        raise RI3EvaluationError(f"RCSB response is not an atom-containing mmCIF: {structure_id}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
    return {
        "status": "downloaded",
        "structure_id": structure_id,
        "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "sha256": _sha256_file(path),
        "bytes": len(content),
        "url": url,
    }


def _ground_truth_result(
    *,
    site: Any,
    prepared_path: Path,
    holo_path: Path,
    policy: AlignmentPolicy = AlignmentPolicy(),
    provenance_label: str = "cryptobench-rcsb-representative-holo-v1",
) -> Any:
    representative = site.representative
    selector = LigandSelector(
        residue_name=representative.ligand_id,
        chain_id=representative.ligand_chain,
        residue_id=int(representative.ligand_index),
    )
    return build_aligned_ground_truth_from_files(
        case_id=site.case_id,
        structure_id=site.apo_pdb_id,
        prepared_apo_path=prepared_path,
        holo_path=holo_path,
        ligand=selector,
        chain_pairs=_representative_chain_pairs(representative),
        provenance_label=provenance_label,
        policy=policy,
        ligand_residues=site.apo_pocket_residues,
    )


def _ground_truth_from_payload(payload: Mapping[str, Any]) -> EvaluatorGroundTruth:
    return EvaluatorGroundTruth(
        case_id=str(payload["case_id"]),
        structure_id=str(payload["structure_id"]),
        coordinate_frame_sha256=str(payload["coordinate_frame_sha256"]),
        alignment_sha256=str(payload["alignment_sha256"]),
        ligand_center=tuple(float(value) for value in payload["ligand_center"]),
        ligand_atoms=tuple(
            tuple(float(value) for value in atom) for atom in payload["ligand_atoms"]
        ),
        ligand_residues=tuple(str(value) for value in payload.get("ligand_residues", [])),
        quality=str(payload.get("quality", "exact")),
        provenance=str(payload.get("provenance", "")),
    )


def _case_evaluation_payload(result: CaseEvaluation) -> dict[str, Any]:
    return asdict(result)


def _initial_report(manifest: Mapping[str, Any], static_run: Mapping[str, Any]) -> dict[str, Any]:
    protocol = phase6_frozen_protocol_v1()
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": f"ri3-static-evaluation-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "status": "not_started",
        "manifest_sha256": manifest["manifest_sha256"],
        "protocol_sha256": protocol.protocol_sha256,
        "static_run_git_commit": static_run.get("git_commit"),
        "source_fingerprints": _source_fingerprints(),
        "detector_target_blind": True,
        "sealed_evaluation_authorized": False,
        "holo_source": {
            "provider": "RCSB files.rcsb.org",
            "format": "mmCIF",
            "role": "evaluator-only representative holo coordinate source",
            "raw_files_ignored": True,
        },
        "records": {},
        "counts": {
            "completed_ground_truth": 0,
            "alignment_unavailable": 0,
            "download_failed": 0,
        },
        "summary": {
            "status": "not_ready",
            "dcc_dca_computed": False,
            "scientific_superiority_claim_authorized": False,
        },
    }


def _validate_report(report: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise RI3EvaluationError("Unexpected RI-3 evaluator report schema")
    if report.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise RI3EvaluationError("Evaluator report manifest hash mismatch")
    if report.get("protocol_sha256") != phase6_frozen_protocol_v1().protocol_sha256:
        raise RI3EvaluationError("Evaluator report protocol hash mismatch")
    if report.get("detector_target_blind") is not True:
        raise RI3EvaluationError("Evaluator report does not preserve detector blindness")
    if report.get("sealed_evaluation_authorized") is not False:
        raise RI3EvaluationError("Sealed evaluation flag is not closed")


def _recompute_counts(report: Mapping[str, Any]) -> dict[str, int]:
    counts = {
        "completed_ground_truth": 0,
        "alignment_unavailable": 0,
        "download_failed": 0,
    }
    for record in report.get("records", {}).values():
        status = record.get("status")
        if status in counts:
            counts[status] += 1
    return counts


def _partial_diagnostics(report: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize accepted evaluator cases without treating them as a claim."""
    available = [
        raw
        for raw in report.get("records", {}).values()
        if raw.get("status") == "completed_ground_truth" and raw.get("case_evaluation")
    ]
    top_k = (1, 3, 5)
    denominator = len(available)
    dcc_recall = {
        str(k): round(
            sum(
                bool(
                    evaluation["case_evaluation"]["top_k_dcc_hits"].get(
                        str(k), evaluation["case_evaluation"]["top_k_dcc_hits"].get(k, False)
                    )
                )
                for evaluation in available
            )
            / denominator if denominator else 0.0,
            8,
        )
        for k in top_k
    }
    dca_recall = {
        str(k): round(
            sum(
                bool(
                    evaluation["case_evaluation"]["top_k_dca_hits"].get(
                        str(k), evaluation["case_evaluation"]["top_k_dca_hits"].get(k, False)
                    )
                )
                for evaluation in available
            )
            / denominator if denominator else 0.0,
            8,
        )
        for k in top_k
    }
    alignment_errors = Counter(
        str(raw.get("error", "")).split(": ", 1)[-1]
        for raw in report.get("records", {}).values()
        if raw.get("status") != "completed_ground_truth"
    )
    detector_status = Counter(
        raw["case_evaluation"]["status"] for raw in available if raw.get("case_evaluation")
    )
    return {
        "status": "diagnostic_only_not_for_claim",
        "ground_truth_available_case_count": len(available),
        "ground_truth_unavailable_case_count": 825 - len(available),
        "detector_case_status": dict(sorted(detector_status.items())),
        "top_k_dcc_recall_on_available_ground_truth": dcc_recall,
        "top_k_dca_recall_on_available_ground_truth": dca_recall,
        "alignment_error_categories": dict(alignment_errors.most_common()),
    }


def _finalize_summary(
    report: dict[str, Any],
    *,
    manifest: BenchmarkManifest,
    detector_records: Mapping[str, DetectorEvaluationRecord],
) -> None:
    if len(report.get("records", {})) != 825:
        report["summary"] = {
            "status": "partial_ground_truth_not_for_claim",
            "dcc_dca_computed": False,
            "scientific_superiority_claim_authorized": False,
            "diagnostic": _partial_diagnostics(report),
        }
        return
    missing = [
        case_id
        for case_id, raw in report["records"].items()
        if raw.get("status") != "completed_ground_truth"
    ]
    if missing:
        report["summary"] = {
            "status": "ground_truth_incomplete_not_for_claim",
            "dcc_dca_computed": False,
            "missing_case_count": len(missing),
            "scientific_superiority_claim_authorized": False,
            "diagnostic": _partial_diagnostics(report),
        }
        return
    truths = {
        case_id: _ground_truth_from_payload(raw["ground_truth"])
        for case_id, raw in report["records"].items()
    }
    result = evaluate_split(
        detector="biovoid_static",
        split="development",
        records=detector_records,
        ground_truth=truths,
        manifest=manifest,
        protocol=phase6_frozen_protocol_v1(),
    )
    report["summary"] = {
        "status": "complete_development_evaluation",
        "dcc_dca_computed": True,
        "scientific_superiority_claim_authorized": False,
        "protocol_result": result,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_RUNTIME_MANIFEST)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--holo-dir", type=Path, default=DEFAULT_HOLO_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--all-development", action="store_true")
    parser.add_argument("--max-cases", type=int, default=DEFAULT_PILOT_SIZE)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--retry-unavailable",
        action="store_true",
        help="Retry prior download/alignment failures with the current evaluator contract",
    )
    parser.add_argument(
        "--rerun-all",
        action="store_true",
        help="Rebuild every evaluator record with the current evaluator source",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    batch_size = _validate_batch_size(args.batch_size)
    if not args.all_development and args.max_cases < 1:
        raise RI3EvaluationError("--max-cases must be positive")
    manifest_path = args.manifest if args.manifest.is_absolute() else REPO_ROOT / args.manifest
    static_run_path = (
        args.static_run if args.static_run.is_absolute() else REPO_ROOT / args.static_run
    )
    report_path = args.report if args.report.is_absolute() else REPO_ROOT / args.report
    manifest = _read_json(manifest_path)
    static_run = _read_json(static_run_path)
    detector_records = _load_detector_records(static_run)
    _validate_report(_read_json(report_path), manifest) if report_path.is_file() else None
    report = _read_json(report_path) if report_path.is_file() else _initial_report(manifest, static_run)
    _validate_report(report, manifest)
    current_fingerprints = _source_fingerprints()
    previous_fingerprints = report.get("source_fingerprints")
    if previous_fingerprints is not None and previous_fingerprints != current_fingerprints:
        raise RI3EvaluationError("Evaluator source changed since the report was created")
    report["source_fingerprints"] = current_fingerprints

    sites = _load_sites(args.metadata_dir)
    benchmark_manifest = _load_manifest_cases(manifest)
    if len(sites) != 825:
        raise RI3EvaluationError(f"Expected 825 evaluator target sites, found {len(sites)}")
    prepared_paths = {
        structure_id: _load_prepared_path(manifest, structure_id)
        for structure_id in {site.apo_pdb_id for site in sites.values()}
    }
    if args.rerun_all:
        pending = [case.case_id for case in benchmark_manifest.cases]
    elif args.retry_unavailable:
        pending = [
            case.case_id
            for case in benchmark_manifest.cases
            if report["records"].get(case.case_id, {}).get("status")
            != "completed_ground_truth"
        ]
    else:
        pending = [
            case.case_id for case in benchmark_manifest.cases if case.case_id not in report["records"]
        ]
    selected = pending if args.all_development else pending[: args.max_cases]
    session = requests.Session()
    session.headers.update({"User-Agent": "BioVoid/0.1 RI-3 evaluator"})

    report["status"] = "running"
    report["updated_at_utc"] = _utc_now()
    for index, case_id in enumerate(selected, start=1):
        site = sites[case_id]
        structure_id = site.apo_pdb_id.upper()
        started = time.perf_counter()
        print(
            f"[{index}/{len(selected)}] {case_id} ({structure_id}) evaluator alignment",
            flush=True,
        )
        record: dict[str, Any] = {
            "case_id": case_id,
            "structure_id": structure_id,
            "representative_holo_id": site.representative.holo_pdb_id,
            "status": "download_failed",
            "ground_truth": None,
            "error": None,
        }
        try:
            download = _download_holo(
                session,
                site.representative.holo_pdb_id.upper(),
                args.holo_dir if args.holo_dir.is_absolute() else REPO_ROOT / args.holo_dir,
            )
            record["holo_source"] = download
            holo_path = (REPO_ROOT / download["path"]).resolve()
            alignment = _ground_truth_result(
                site=site,
                prepared_path=prepared_paths[structure_id],
                holo_path=holo_path,
            )
            record["status"] = "completed_ground_truth"
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
            case_result = evaluate_case(
                detector_records[structure_id],
                alignment.ground_truth,
                phase6_frozen_protocol_v1(),
            )
            record["case_evaluation"] = _case_evaluation_payload(case_result)
        except GroundTruthAlignmentError as exc:
            record["status"] = "alignment_unavailable"
            record["error"] = f"{type(exc).__name__}: {exc}"
        except (requests.RequestException, OSError, ValueError, KeyError) as exc:
            record["status"] = "download_failed"
            record["error"] = f"{type(exc).__name__}: {exc}"
        record["runtime_seconds"] = round(time.perf_counter() - started, 6)
        report["records"][case_id] = record
        report["counts"] = _recompute_counts(report)
        report["updated_at_utc"] = _utc_now()
        if index % batch_size == 0 or index == len(selected):
            _write_json_atomic(report_path, report)
            print(f"checkpoint counts={report['counts']}", flush=True)

    _finalize_summary(
        report,
        manifest=benchmark_manifest,
        detector_records=detector_records,
    )
    report["counts"] = _recompute_counts(report)
    report["status"] = "complete" if len(report["records"]) == 825 else "partial"
    report["updated_at_utc"] = _utc_now()
    _write_json_atomic(report_path, report)
    print(
        f"RI-3 evaluator: {report['status']} cases={len(report['records'])}/825 "
        f"ground_truth={report['counts']['completed_ground_truth']} "
        f"alignment_unavailable={report['counts']['alignment_unavailable']} "
        f"download_failed={report['counts']['download_failed']}",
    )
    print(f"evaluation report: {report_path}")
    print(f"summary: {report['summary']['status']}")
    print("sealed evaluation: closed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RI3EvaluationError as exc:
        print(f"RI-3 evaluator error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
