"""Evaluate the bounded CryptoBench static pilot in an evaluator-only arm.

This command is intentionally separate from detector execution. It may read
private CryptoBench observations and download representative holo mmCIF files,
but those files never enter the detector manifest or static run. Results are
diagnostic-only for the bounded pilot and do not authorize a scientific claim.
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
    _ground_truth_result,
)
from scripts.run_ri3_static_pilot import (  # noqa: E402
    DEFAULT_MANIFEST as DEFAULT_PILOT_MANIFEST,
    DEFAULT_RUN as DEFAULT_PILOT_RUN,
    PilotRunError,
    validate_pilot_manifest,
    validate_pilot_run,
)
from src.benchmark_v1 import (  # noqa: E402
    BenchmarkCase,
    BenchmarkManifest,
    evaluate_case,
    phase6_frozen_protocol_v1,
)
from src.cryptobench_adapter import build_target_sites  # noqa: E402
from src.cryptobench_manifest import _opaque_case_id  # noqa: E402
from src.evaluator_format import DetectorEvaluationRecord, EvaluatorPocket  # noqa: E402
from src.ground_truth_alignment import GroundTruthAlignmentError  # noqa: E402


DEFAULT_METADATA_DIR = REPO_ROOT / "data/runtime/cryptobench-source/metadata"
DEFAULT_HOLO_DIR = REPO_ROOT / "data/runtime/ri3/pilot-evaluator-holo"
DEFAULT_REPORT = REPO_ROOT / "data/runtime/ri3/cryptobench-static-pilot-evaluation-v1.json"
REPORT_SCHEMA_VERSION = "biovoid-ri3-static-pilot-evaluation-v1"
MAX_PILOT_CASES = 20


class PilotEvaluationError(RuntimeError):
    """Raised when the bounded evaluator contract cannot proceed."""


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _resolve_repo_path(value: Path) -> Path:
    candidate = value if value.is_absolute() else REPO_ROOT / value
    return candidate.resolve()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PilotEvaluationError(f"Required evaluator file is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PilotEvaluationError(f"Expected a JSON object: {path}")
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _normalize_id(value: Any) -> str:
    normalized = str(value).strip().upper()
    if len(normalized) != 4 or not normalized.isalnum():
        raise PilotEvaluationError(f"Invalid structure ID: {value!r}")
    return normalized


def build_pilot_evaluator_scope(
    *,
    pilot_manifest: Mapping[str, Any],
    dataset: Mapping[str, Any],
) -> tuple[BenchmarkManifest, dict[str, Any]]:
    """Build evaluator cases/sites from the exact pilot structure boundary."""

    validate_pilot_manifest(pilot_manifest)
    selected_ids = tuple(
        _normalize_id(value) for value in pilot_manifest["scope"]["structure_ids"]
    )
    dataset_by_id = {_normalize_id(key): value for key, value in dataset.items()}
    missing = sorted(set(selected_ids) - set(dataset_by_id))
    if missing:
        raise PilotEvaluationError("Pilot metadata is missing: " + ", ".join(missing))
    sites = build_target_sites(
        {structure_id: dataset_by_id[structure_id] for structure_id in selected_ids},
        dataset_id="cryptobench",
        split="development",
    )
    sites_by_structure: dict[str, list[Any]] = {}
    for site in sites:
        sites_by_structure.setdefault(site.apo_pdb_id.upper(), []).append(site)
    redacted_cases_by_structure: dict[str, list[Mapping[str, Any]]] = {}
    for raw_case in pilot_manifest["cases"]:
        structure_id = _normalize_id(raw_case["structure_id"])
        redacted_cases_by_structure.setdefault(structure_id, []).append(raw_case)
    sites_by_case: dict[str, Any] = {}
    for structure_id, raw_cases in redacted_cases_by_structure.items():
        structure_sites = sites_by_structure.get(structure_id, [])
        if len(raw_cases) != len(structure_sites):
            raise PilotEvaluationError(
                f"Pilot case/site count differs for {structure_id}: "
                f"{len(raw_cases)} vs {len(structure_sites)}"
            )
        expected_sites = {_opaque_case_id(site): site for site in structure_sites}
        raw_case_ids = {str(raw_case["case_id"]) for raw_case in raw_cases}
        if raw_case_ids != set(expected_sites):
            missing = sorted(set(expected_sites) - raw_case_ids)
            unexpected = sorted(raw_case_ids - set(expected_sites))
            raise PilotEvaluationError(
                f"Pilot opaque case IDs differ for {structure_id}: "
                f"missing={missing[:3]} unexpected={unexpected[:3]}"
            )
        for raw_case in raw_cases:
            site = expected_sites[str(raw_case["case_id"])]
            if str(raw_case["family_id"]).casefold() != site.family_id.casefold():
                raise PilotEvaluationError(f"Pilot family mismatch: {raw_case['case_id']}")
            sites_by_case[str(raw_case["case_id"])] = site
    structure_inputs = {
        _normalize_id(item["structure_id"]): item for item in pilot_manifest["structures"]
    }
    case_rows: list[BenchmarkCase] = []
    for raw_case in pilot_manifest["cases"]:
        structure_id = _normalize_id(raw_case["structure_id"])
        structure = structure_inputs.get(structure_id)
        if structure is None:
            raise PilotEvaluationError(f"Pilot structure input is missing: {structure_id}")
        case_id = str(raw_case["case_id"])
        site = sites_by_case.get(case_id)
        if site is None:
            raise PilotEvaluationError(f"Pilot evaluator case is absent from metadata: {case_id}")
        if site.apo_pdb_id != structure_id:
            raise PilotEvaluationError(f"Pilot case structure mismatch: {case_id}")
        case_rows.append(
            BenchmarkCase(
                case_id=case_id,
                structure_id=structure_id,
                family_id=str(raw_case["family_id"]),
                split="development",
                prepared_structure_sha256=str(structure["prepared_structure_sha256"]),
                preparation_config_sha256=str(structure["preparation_config_sha256"]),
            )
        )
    manifest = BenchmarkManifest(cases=tuple(sorted(case_rows, key=lambda case: case.case_id)))
    return manifest, sites_by_case


def _load_detector_records(
    static_run: Mapping[str, Any],
    *,
    expected_structure_ids: set[str],
) -> dict[str, DetectorEvaluationRecord]:
    if static_run.get("status") not in {"complete", "complete_with_resource_blocks"}:
        raise PilotEvaluationError("Static pilot run is not complete")
    records: dict[str, DetectorEvaluationRecord] = {}
    for raw_id, raw_record in static_run.get("records", {}).items():
        structure_id = _normalize_id(raw_id)
        detector_payload = raw_record.get("detector_record")
        if not isinstance(detector_payload, Mapping):
            raise PilotEvaluationError(f"Detector record is missing: {structure_id}")
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
        records[structure_id] = DetectorEvaluationRecord(
            schema_version=str(detector_payload["schema_version"]),
            detector=str(detector_payload["detector"]),
            structure_id=structure_id,
            status=str(detector_payload["status"]),
            pockets=pockets,
            error=detector_payload.get("error"),
            provenance=dict(detector_payload.get("provenance") or {}),
        )
    if set(records) != expected_structure_ids:
        raise PilotEvaluationError("Static pilot structure IDs differ from evaluator scope")
    return records


def _initial_report(
    *,
    pilot_manifest: Mapping[str, Any],
    static_run: Mapping[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "not_started",
        "manifest_sha256": pilot_manifest["manifest_sha256"],
        "static_run_sha256": static_run["run_sha256"],
        "protocol_sha256": phase6_frozen_protocol_v1().protocol_sha256,
        "detector_target_blind": True,
        "detector_inputs_unchanged": True,
        "sealed_evaluation_authorized": False,
        "scope": pilot_manifest["scope"],
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
            "detector_unavailable": 0,
        },
        "summary": {
            "status": "not_ready",
            "diagnostic_only": True,
            "dcc_dca_computed": False,
            "scientific_superiority_claim_authorized": False,
        },
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "report_sha256": None,
    }
    payload["report_sha256"] = _stable_hash(
        {key: value for key, value in payload.items() if key != "report_sha256"}
    )
    return payload


def _validate_report(report: Mapping[str, Any], pilot_manifest: Mapping[str, Any]) -> None:
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise PilotEvaluationError("Unexpected pilot evaluator report schema")
    if report.get("manifest_sha256") != pilot_manifest.get("manifest_sha256"):
        raise PilotEvaluationError("Evaluator report manifest hash mismatch")
    if report.get("protocol_sha256") != phase6_frozen_protocol_v1().protocol_sha256:
        raise PilotEvaluationError("Evaluator report protocol hash mismatch")
    for key in ("detector_target_blind", "detector_inputs_unchanged"):
        if report.get(key) is not True:
            raise PilotEvaluationError(f"Evaluator boundary flag is not closed: {key}")
    if report.get("sealed_evaluation_authorized") is not False:
        raise PilotEvaluationError("Sealed evaluation flag is open")
    expected_hash = _stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    if report.get("report_sha256") != expected_hash:
        raise PilotEvaluationError("Evaluator report hash mismatch")


def _counts(report: Mapping[str, Any]) -> dict[str, int]:
    result = {
        "completed_ground_truth": 0,
        "alignment_unavailable": 0,
        "download_failed": 0,
        "detector_unavailable": 0,
    }
    for record in report.get("records", {}).values():
        if isinstance(record, Mapping) and record.get("status") in result:
            result[str(record["status"])] += 1
    return result


def _diagnostic_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    available = [
        record
        for record in report.get("records", {}).values()
        if isinstance(record, Mapping)
        and record.get("status") == "completed_ground_truth"
        and isinstance(record.get("case_evaluation"), Mapping)
    ]
    denominator = len(available)

    def hit(record: Mapping[str, Any], metric: str, k: int) -> bool:
        evaluation = record.get("case_evaluation")
        if not isinstance(evaluation, Mapping):
            return False
        hits = evaluation.get(metric)
        if not isinstance(hits, Mapping):
            return False
        return bool(hits.get(k, hits.get(str(k), False)))

    dcc = {
        str(k): round(
            sum(hit(record, "top_k_dcc_hits", k) for record in available)
            / denominator
            if denominator
            else 0.0,
            8,
        )
        for k in (1, 3, 5)
    }
    dca = {
        str(k): round(
            sum(hit(record, "top_k_dca_hits", k) for record in available)
            / denominator
            if denominator
            else 0.0,
            8,
        )
        for k in (1, 3, 5)
    }
    return {
        "status": "diagnostic_only_not_for_claim",
        "diagnostic_only": True,
        "ground_truth_available_case_count": denominator,
        "top_k_dcc_recall_on_available_ground_truth": dcc,
        "top_k_dca_recall_on_available_ground_truth": dca,
        "scientific_superiority_claim_authorized": False,
    }


def run_pilot_evaluator(
    *,
    metadata_dir: Path = DEFAULT_METADATA_DIR,
    pilot_manifest_path: Path = DEFAULT_PILOT_MANIFEST,
    static_run_path: Path = DEFAULT_PILOT_RUN,
    holo_dir: Path = DEFAULT_HOLO_DIR,
    report_path: Path = DEFAULT_REPORT,
    max_cases: int | None = None,
) -> dict[str, Any]:
    """Download evaluator-only holo files and compute bounded DCC/DCA metrics."""

    metadata_dir = _resolve_repo_path(metadata_dir)
    pilot_manifest_path = _resolve_repo_path(pilot_manifest_path)
    static_run_path = _resolve_repo_path(static_run_path)
    holo_dir = _resolve_repo_path(holo_dir)
    report_path = _resolve_repo_path(report_path)
    pilot_manifest = _read_json(pilot_manifest_path)
    static_run = _read_json(static_run_path)
    validate_pilot_manifest(pilot_manifest)
    try:
        validate_pilot_run(static_run, pilot_manifest)
    except PilotRunError as exc:
        raise PilotEvaluationError(str(exc)) from exc
    dataset = _read_json(metadata_dir / "dataset.json")
    benchmark_manifest, sites = build_pilot_evaluator_scope(
        pilot_manifest=pilot_manifest,
        dataset=dataset,
    )
    expected_ids = set(pilot_manifest["scope"]["structure_ids"])
    detector_records = _load_detector_records(static_run, expected_structure_ids=expected_ids)
    structures = {
        _normalize_id(item["structure_id"]): item for item in pilot_manifest["structures"]
    }
    prepared_paths = {
        structure_id: _resolve_repo_path(Path(structure["prepared_path"]))
        for structure_id, structure in structures.items()
    }
    if any(not path.is_file() for path in prepared_paths.values()):
        missing = [structure_id for structure_id, path in prepared_paths.items() if not path.is_file()]
        raise PilotEvaluationError("Prepared detector input is missing: " + ", ".join(missing))

    if report_path.is_file():
        report = _read_json(report_path)
        _validate_report(report, pilot_manifest)
    else:
        report = _initial_report(pilot_manifest=pilot_manifest, static_run=static_run)
    pending = [case.case_id for case in benchmark_manifest.cases if case.case_id not in report["records"]]
    if max_cases is not None:
        if not 1 <= max_cases <= MAX_PILOT_CASES:
            raise PilotEvaluationError("--max-cases must be between 1 and 20")
        pending = pending[:max_cases]
    report["status"] = "running"
    report["updated_at_utc"] = _utc_now()
    session = requests.Session()
    session.headers.update({"User-Agent": "BioVoid/0.1 RI-3 static pilot evaluator"})
    try:
        for index, case_id in enumerate(pending, start=1):
            case = next(item for item in benchmark_manifest.cases if item.case_id == case_id)
            site = sites[case_id]
            structure_id = case.structure_id.upper()
            started = time.perf_counter()
            print(f"[{index}/{len(pending)}] {case_id} ({structure_id}) evaluator", flush=True)
            detector_record = detector_records[structure_id]
            record: dict[str, Any] = {
                "case_id": case_id,
                "structure_id": structure_id,
                "status": "detector_unavailable",
                "ground_truth": None,
                "error": None,
            }
            if detector_record.status != "completed":
                record["error"] = detector_record.error or "static detector output unavailable"
            else:
                try:
                    download = _download_holo(
                        session,
                        site.representative.holo_pdb_id.upper(),
                        holo_dir,
                    )
                    record["holo_source"] = download
                    alignment = _ground_truth_result(
                        site=site,
                        prepared_path=prepared_paths[structure_id],
                        holo_path=_resolve_repo_path(Path(download["path"])),
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
                    record["case_evaluation"] = asdict(
                        evaluate_case(
                            detector_record,
                            alignment.ground_truth,
                            phase6_frozen_protocol_v1(),
                        )
                    )
                except GroundTruthAlignmentError as exc:
                    record["status"] = "alignment_unavailable"
                    record["error"] = f"{type(exc).__name__}: {exc}"
                except (requests.RequestException, OSError, ValueError, KeyError) as exc:
                    record["status"] = "download_failed"
                    record["error"] = f"{type(exc).__name__}: {exc}"
            record["runtime_seconds"] = round(time.perf_counter() - started, 6)
            report["records"][case_id] = record
            report["counts"] = _counts(report)
            report["updated_at_utc"] = _utc_now()
            _write_json_atomic(report_path, report)
            print(f"checkpoint counts={report['counts']}", flush=True)
    finally:
        session.close()

    report["counts"] = _counts(report)
    report["summary"] = _diagnostic_summary(report)
    report["status"] = "complete" if len(report["records"]) == len(benchmark_manifest.cases) else "partial"
    report["updated_at_utc"] = _utc_now()
    report["report_sha256"] = _stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    _validate_report(report, pilot_manifest)
    _write_json_atomic(report_path, report)
    print(
        f"RI-3 pilot evaluator: {report['status']} cases={len(report['records'])}/{len(benchmark_manifest.cases)} "
        f"ground_truth={report['counts']['completed_ground_truth']} "
        f"alignment_unavailable={report['counts']['alignment_unavailable']} "
        f"download_failed={report['counts']['download_failed']} "
        f"detector_unavailable={report['counts']['detector_unavailable']}"
    )
    print(f"diagnostic summary: {report['summary']['status']}")
    print("scientific claim authorization: closed")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_PILOT_MANIFEST)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_PILOT_RUN)
    parser.add_argument("--holo-dir", type=Path, default=DEFAULT_HOLO_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-cases", type=int, default=None)
    args = parser.parse_args()
    try:
        run_pilot_evaluator(
            metadata_dir=args.metadata_dir,
            pilot_manifest_path=args.manifest,
            static_run_path=args.static_run,
            holo_dir=args.holo_dir,
            report_path=args.report,
            max_cases=args.max_cases,
        )
    except PilotEvaluationError as exc:
        print(f"RI-3 pilot evaluator error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
