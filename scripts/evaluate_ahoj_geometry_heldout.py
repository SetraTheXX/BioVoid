"""Evaluate the locked AHoJ policy once on validation and temporal/test rows.

The held-out apo static artifact is already complete and target-blind.  This
command opens only the reserved four holo structures, aligns evaluator labels
to the prepared apo frame, and measures the unchanged A policy with the
frozen DCC/DCA protocol.  It performs no tuning and does not open any further
source, motion/NMA, external baseline, or ML path.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_ahoj_geometry_static_development import (  # noqa: E402
    ALIGNMENT_POLICY,
    PROTOCOL,
    _alignment_candidates,
    _directory_size_bytes,
    _relative,
    _safe_error,
    _source_pair_index,
)
from scripts.seal_ahoj_geometry_cohort import _read_json  # noqa: E402
from src.benchmark_v1 import evaluate_case  # noqa: E402
from src.evaluator_format import adapt_biovoid_pockets  # noqa: E402
from src.fetcher import FetchError, fetch_structure_input  # noqa: E402
from src.structure_preparation import StructureSource  # noqa: E402


DEFAULT_COHORT = (
    REPO_ROOT
    / "local-private/research/geometry-data-source-catalog/ahoj-v1/ahoj-geometry-cohort-v1.json"
)
DEFAULT_SOURCE_CATALOG = (
    REPO_ROOT
    / "local-private/research/geometry-data-source-catalog/ahoj-v1/"
    "ahoj-geometry-source-catalog-v1.json"
)
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "data/runtime/target-family/cohort-ahoj-geometry-v1/ahoj-geometry-detector-manifest-v1.json"
)
DEFAULT_STATIC_RUN = (
    REPO_ROOT
    / "data/runtime/target-family/cohort-ahoj-geometry-v1/heldout-static-pilot-v1/"
    "ahoj-geometry-heldout-static-pilot-v1.json"
)
DEFAULT_POLICY_SELECTION = (
    REPO_ROOT
    / "local-private/research/geometry-data-source-catalog/ahoj-v1/"
    "evaluator-development-v3/ahoj-geometry-ranking-policy-selection-v1.json"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "local-private/research/geometry-data-source-catalog/ahoj-v1/heldout-evaluator-v1"
)
DEFAULT_HOLO_ROOT = DEFAULT_OUTPUT_ROOT / "holo"
DEFAULT_REPORT = DEFAULT_OUTPUT_ROOT / "ahoj-geometry-heldout-evaluation-v1.json"
MAX_CASES = 4
MAX_DISK_BYTES = 1 * 1024**3
REPORT_SCHEMA_VERSION = "biovoid-ahoj-geometry-heldout-evaluation-v1"


class AhojHeldoutEvaluationError(RuntimeError):
    """Raised when the locked held-out evaluator contract is invalid."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _validate_inputs(
    cohort: Mapping[str, Any],
    manifest: Mapping[str, Any],
    static_run: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    if cohort.get("schema_version") != "biovoid-ahoj-geometry-cohort-v1":
        raise AhojHeldoutEvaluationError("unsupported AHoJ cohort schema")
    if cohort.get("evaluator_started") is not False:
        raise AhojHeldoutEvaluationError("held-out evaluator state was already opened")
    if manifest.get("schema_version") != "biovoid-ahoj-geometry-detector-manifest-v1":
        raise AhojHeldoutEvaluationError("unsupported AHoJ detector manifest schema")
    if static_run.get("schema_version") != "biovoid-ahoj-geometry-heldout-static-pilot-v1":
        raise AhojHeldoutEvaluationError("unsupported held-out static schema")
    if static_run.get("status") != "completed_locked_policy_heldout_static":
        raise AhojHeldoutEvaluationError("held-out static run is not complete")
    if static_run.get("execution", {}).get("ranking_policy") != "A-canonical-volume-v1":
        raise AhojHeldoutEvaluationError("held-out static run is not locked to policy A")
    if static_run.get("execution", {}).get("candidate_retention") != "full_final_pocket_list":
        raise AhojHeldoutEvaluationError("held-out static run lacks full final-pocket retention")
    if selection.get("schema_version") != "biovoid-ahoj-geometry-ranking-policy-selection-v1":
        raise AhojHeldoutEvaluationError("unsupported policy selection report")
    if selection.get("status") != "development_policy_selected_shadow_only":
        raise AhojHeldoutEvaluationError("development policy selection is not complete")
    if selection.get("selected_policy_id") != "A-canonical-volume-v1":
        raise AhojHeldoutEvaluationError("held-out policy is not the selected A baseline")
    if selection.get("boundary", {}).get("validation_labels_opened") is not False:
        raise AhojHeldoutEvaluationError("validation labels were opened before policy lock")
    cases = cohort.get("cases")
    manifest_cases = manifest.get("cases")
    static_cases = static_run.get("cases")
    if not isinstance(cases, list) or not isinstance(manifest_cases, list) or not isinstance(static_cases, Mapping):
        raise AhojHeldoutEvaluationError("held-out cohort/manifest/static cases are missing")
    private_by_id = {str(case.get("case_id")): case for case in cases if isinstance(case, Mapping)}
    selected_manifest = [
        case
        for case in manifest_cases
        if isinstance(case, Mapping) and case.get("split") in {"validation", "test"}
    ]
    if len(selected_manifest) != MAX_CASES:
        raise AhojHeldoutEvaluationError("exactly four validation/test manifest cases are required")
    selected: list[Mapping[str, Any]] = []
    for manifest_case in sorted(selected_manifest, key=lambda item: str(item["case_id"])):
        case_id = str(manifest_case["case_id"])
        private_case = private_by_id.get(case_id)
        if private_case is None:
            raise AhojHeldoutEvaluationError(f"private held-out case missing: {case_id}")
        expected_split = "temporal" if manifest_case.get("split") == "test" else "validation"
        if private_case.get("split") != expected_split:
            raise AhojHeldoutEvaluationError(f"held-out split mismatch: {case_id}")
        static_case = static_cases.get(case_id)
        if not isinstance(static_case, Mapping) or static_case.get("status") != "completed":
            raise AhojHeldoutEvaluationError(f"held-out static case unavailable: {case_id}")
        if not isinstance(static_case.get("all_pockets"), list) or not static_case["all_pockets"]:
            raise AhojHeldoutEvaluationError(f"held-out full pocket list missing: {case_id}")
        selected.append(private_case)
    return selected, {str(key): value for key, value in static_cases.items()}


def _aggregate(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"case_count": len(records)}
    for metric in ("dcc", "dca"):
        for k in (1, 3, 5, 10):
            result[f"{metric}_top_{k}"] = sum(
                bool(record["decomposition"][f"top_k_{metric}_hits"][str(k)]) for record in records
            )
    result["joint_universe"] = sum(
        bool(record["decomposition"]["candidate_universe"]["joint_hit"]) for record in records
    )
    result["joint_top_1"] = sum(
        (record["decomposition"]["best_rank"]["joint"] or 10**9) <= 1 for record in records
    )
    result["joint_top_3"] = sum(
        (record["decomposition"]["best_rank"]["joint"] or 10**9) <= 3 for record in records
    )
    result["joint_top_5"] = sum(
        (record["decomposition"]["best_rank"]["joint"] or 10**9) <= 5 for record in records
    )
    result["joint_top_10"] = sum(
        (record["decomposition"]["best_rank"]["joint"] or 10**9) <= 10 for record in records
    )
    return result


def evaluate_ahoj_geometry_heldout(
    *,
    cohort_path: Path = DEFAULT_COHORT,
    source_catalog_path: Path = DEFAULT_SOURCE_CATALOG,
    manifest_path: Path = DEFAULT_MANIFEST,
    static_run_path: Path = DEFAULT_STATIC_RUN,
    policy_selection_path: Path = DEFAULT_POLICY_SELECTION,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    holo_root: Path = DEFAULT_HOLO_ROOT,
    report_path: Path = DEFAULT_REPORT,
    max_disk_bytes: int = MAX_DISK_BYTES,
    user_approved: bool = False,
) -> dict[str, Any]:
    if not user_approved:
        raise AhojHeldoutEvaluationError("held-out evaluator requires --approve-heldout-evaluator")
    if not 1 <= max_disk_bytes <= MAX_DISK_BYTES:
        raise ValueError("max_disk_bytes must be between 1 byte and 1 GB")
    cohort = _read_json(cohort_path.resolve())
    source_catalog = _read_json(source_catalog_path.resolve())
    manifest = _read_json(manifest_path.resolve())
    static_run = _read_json(static_run_path.resolve())
    selection = _read_json(policy_selection_path.resolve())
    cases, static_by_case = _validate_inputs(cohort, manifest, static_run, selection)
    source_by_apo = _source_pair_index(source_catalog)
    if output_root.exists() and any(output_root.iterdir()):
        raise AhojHeldoutEvaluationError(f"held-out evaluator output root is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    holo_root.mkdir(parents=True, exist_ok=True)
    if _directory_size_bytes(output_root) + _directory_size_bytes(holo_root) > max_disk_bytes:
        raise AhojHeldoutEvaluationError("held-out evaluator quota exceeded before start")

    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "running",
        "family_id": cohort.get("family_id"),
        "cohort_sha256": cohort.get("cohort_sha256"),
        "detector_manifest_sha256": manifest.get("manifest_sha256"),
        "static_run_sha256": static_run.get("run_sha256"),
        "policy_selection_sha256": _sha256_file(policy_selection_path.resolve()),
        "source_catalog_sha256": _sha256_file(source_catalog_path.resolve()),
        "selected_policy_id": "A-canonical-volume-v1",
        "alignment_policy": asdict(ALIGNMENT_POLICY),
        "protocol": PROTOCOL.to_manifest(),
        "execution": {
            "workers": 1,
            "case_count": MAX_CASES,
            "max_disk_bytes": max_disk_bytes,
            "validation_labels_opened": True,
            "temporal_labels_opened": True,
            "detector_rerun": False,
            "ranking_changed": False,
            "motion_enabled": False,
            "external_baselines_enabled": False,
            "ml_enabled": False,
        },
        "claim_boundary": "locked_policy_heldout_diagnostic_only",
        "records": {},
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "report_sha256": None,
    }
    for case in cases:
        case_id = str(case["case_id"])
        apo_id = str(case["apo_structure_id"]).upper()
        started = time.perf_counter()
        split = str(case["split"])
        record: dict[str, Any] = {
            "case_id": case_id,
            "structure_id": apo_id,
            "split": split,
            "status": "alignment_unavailable",
            "detector_arm": "canonical_static_v1_target_blind",
            "evaluator_arm": "ahoj_biolip2_site_assignment_v1",
            "selected_policy_id": "A-canonical-volume-v1",
        }
        try:
            source_pair = source_by_apo.get(apo_id)
            if source_pair is None:
                raise AhojHeldoutEvaluationError(f"source catalog pair missing for {apo_id}")
            static_case = static_by_case[case_id]
            prepared_path = (REPO_ROOT / str(static_case["prepared_path"])).resolve()
            holo_id = str(case["holo_structure_id"]).upper()
            holo_source = fetch_structure_input(
                StructureSource(provider="rcsb", identifier=holo_id, representation="asymmetric_unit"),
                cache_dir=holo_root,
            )
            holo_path = holo_source.path.resolve()
            if _directory_size_bytes(output_root) + _directory_size_bytes(holo_root) > max_disk_bytes:
                raise AhojHeldoutEvaluationError("held-out evaluator quota exceeded")
            alignments = _alignment_candidates(
                case=case,
                source_pair=source_pair,
                apo_path=prepared_path,
                holo_path=holo_path,
            )
            alignment, chain_pair, selector = alignments[0]
            detector = adapt_biovoid_pockets(
                apo_id,
                static_case["all_pockets"],
                provenance={
                    "source": "ahoj-geometry-heldout-static-pilot-v1",
                    "target_blind": True,
                    "candidate_retention": "full_final_pocket_list",
                    "shadow_policy_id": "A-canonical-volume-v1",
                    "score_used": False,
                },
            )
            evaluation = evaluate_case(detector, alignment.ground_truth, PROTOCOL)
            # Importing the development decomposition keeps the taxonomy identical
            # between development and held-out while leaving the policy locked.
            from scripts.evaluate_ahoj_geometry_static_development import (  # noqa: PLC0415
                decompose_case_evaluation,
            )

            decomposition = decompose_case_evaluation(evaluation, PROTOCOL)
            record.update(
                {
                    "status": "completed",
                    "holo_source": {
                        "structure_id": holo_id,
                        "path": _relative(holo_path),
                        "sha256": _sha256_file(holo_path),
                        "bytes": holo_path.stat().st_size,
                        "url": f"https://files.rcsb.org/download/{holo_id.lower()}.cif",
                    },
                    "ligand_selector": asdict(selector),
                    "chain_pair": asdict(chain_pair),
                    "alignment": {
                        "status": alignment.status,
                        "matched_residue_count": alignment.matched_residue_count,
                        "sequence_identity": alignment.sequence_identity,
                        "fit_rmsd_angstrom": alignment.fit_rmsd_angstrom,
                        "alignment_sha256": alignment.alignment_sha256,
                        "ground_truth_sha256": alignment.ground_truth_sha256,
                        "warnings": list(alignment.warnings),
                    },
                    "ground_truth": asdict(alignment.ground_truth),
                    "case_evaluation": asdict(evaluation),
                    "decomposition": decomposition,
                }
            )
            record["case_evaluation"]["dcc_by_rank"] = list(evaluation.dcc_by_rank)
            record["case_evaluation"]["dca_by_rank"] = list(evaluation.dca_by_rank)
        except FetchError as exc:
            record.update({"status": "holo_download_failed", "error": _safe_error(exc)})
        except (AhojHeldoutEvaluationError, OSError, ValueError, KeyError, TypeError) as exc:
            record.update({"status": "alignment_unavailable", "error": _safe_error(exc)})
        except Exception as exc:  # noqa: BLE001 - alignment failures remain visible per case
            record.update({"status": "alignment_unavailable", "error": _safe_error(exc)})
        record["runtime_seconds"] = round(time.perf_counter() - started, 6)
        report["records"][case_id] = record
        report["updated_at_utc"] = _utc_now()
        report["report_sha256"] = _stable_hash(
            {key: value for key, value in report.items() if key != "report_sha256"}
        )
        _write_json(report_path.resolve(), report)

    completed_records = [
        record for record in report["records"].values() if record.get("status") == "completed"
    ]
    report["counts"] = {
        "completed": len(completed_records),
        "alignment_unavailable": sum(
            record.get("status") == "alignment_unavailable" for record in report["records"].values()
        ),
        "holo_download_failed": sum(
            record.get("status") == "holo_download_failed" for record in report["records"].values()
        ),
    }
    report["summary"] = {"overall": _aggregate(completed_records)}
    for split in ("validation", "temporal"):
        report["summary"][split] = _aggregate(
            [record for record in completed_records if record.get("split") == split]
        )
    report["status"] = (
        "completed_locked_policy_heldout_evaluation"
        if len(completed_records) == MAX_CASES
        else "completed_with_alignment_or_download_failures"
    )
    report["final_disk_bytes"] = _directory_size_bytes(output_root) + _directory_size_bytes(holo_root)
    report["updated_at_utc"] = _utc_now()
    report["report_sha256"] = _stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    _write_json(report_path.resolve(), report)
    print(
        f"AHoJ held-out evaluator: {report['status']} completed={report['counts']['completed']} "
        f"alignment_unavailable={report['counts']['alignment_unavailable']} "
        f"holo_download_failed={report['counts']['holo_download_failed']}"
    )
    print(f"private held-out report: {report_path}")
    print("detector-rerun/ranking-retune/NMA/external-baseline/ML: no")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--source-catalog", type=Path, default=DEFAULT_SOURCE_CATALOG)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--static-run", type=Path, default=DEFAULT_STATIC_RUN)
    parser.add_argument("--policy-selection", type=Path, default=DEFAULT_POLICY_SELECTION)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--holo-root", type=Path, default=DEFAULT_HOLO_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-disk-bytes", type=int, default=MAX_DISK_BYTES)
    parser.add_argument("--approve-heldout-evaluator", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        report = evaluate_ahoj_geometry_heldout(
            cohort_path=args.cohort,
            source_catalog_path=args.source_catalog,
            manifest_path=args.manifest,
            static_run_path=args.static_run,
            policy_selection_path=args.policy_selection,
            output_root=args.output_root,
            holo_root=args.holo_root,
            report_path=args.report,
            max_disk_bytes=args.max_disk_bytes,
            user_approved=args.approve_heldout_evaluator,
        )
    except (AhojHeldoutEvaluationError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"AHoJ held-out evaluator error: {exc}", file=sys.stderr)
        return 2
    return 0 if report["status"] == "completed_locked_policy_heldout_evaluation" else 2


if __name__ == "__main__":
    raise SystemExit(main())
