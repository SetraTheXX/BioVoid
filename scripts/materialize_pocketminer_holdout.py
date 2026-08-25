"""Prepare only the pre-sealed PocketMiner validation and temporal/test apo rows.

This is an apo-only, one-worker resource preflight.  It joins the redacted
detector manifest with the ignored private chain metadata, downloads at most
four structures, and never opens holo labels or starts detector/evaluator,
motion, external baselines, or ML.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.fetcher import FetchError, fetch_structure_input  # noqa: E402
from src.resources import ResourceLimitError, SAFE_16GB, get_available_memory_bytes  # noqa: E402
from src.structure_preparation import (  # noqa: E402
    PreparationConfig,
    PreparationError,
    StructureSource,
    prepare_structure,
)
from src.target_family_cohort import (  # noqa: E402
    CohortContractError,
    validate_target_blind_manifest,
)


DEFAULT_COHORT = (
    REPO_ROOT / "local-private/research/ranking-study-source-catalog/pocketminer-v1/"
    "pocketminer-cohort-v1.json"
)
DEFAULT_DETECTOR_MANIFEST = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/pocketminer-detector-manifest-v1.json"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/heldout-materialization-v1"
)
DEFAULT_REPORT = DEFAULT_OUTPUT_ROOT / "heldout-preflight-v1.json"
MAX_TOTAL_BYTES = 1 * 1024**3
HELDOUT_SPLITS = frozenset({"validation", "test"})
EXPECTED_CASES = 4


class PocketMinerHoldoutMaterializationError(RuntimeError):
    """Raised when the held-out apo-only preflight is invalid."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PocketMinerHoldoutMaterializationError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PocketMinerHoldoutMaterializationError(f"JSON must be an object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _select_cases(
    cohort: Mapping[str, Any], detector_manifest: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    try:
        validate_target_blind_manifest(detector_manifest)
    except CohortContractError as exc:
        raise PocketMinerHoldoutMaterializationError(str(exc)) from exc
    if detector_manifest.get("materialization_status") != "metadata_only":
        raise PocketMinerHoldoutMaterializationError("detector manifest is not metadata-only")
    if "holo" in json.dumps(detector_manifest, ensure_ascii=True).casefold():
        raise PocketMinerHoldoutMaterializationError("detector manifest contains holo data")
    private_cases = cohort.get("cases")
    if not isinstance(private_cases, list):
        raise PocketMinerHoldoutMaterializationError("private cohort cases are missing")
    by_case_id = {
        str(case.get("case_id")): case for case in private_cases if isinstance(case, Mapping)
    }
    selected: list[Mapping[str, Any]] = []
    for manifest_case in detector_manifest.get("cases", []):
        if (
            not isinstance(manifest_case, Mapping)
            or manifest_case.get("split") not in HELDOUT_SPLITS
        ):
            continue
        private_case = by_case_id.get(str(manifest_case.get("case_id")))
        if private_case is None:
            raise PocketMinerHoldoutMaterializationError(
                f"detector case missing from private cohort: {manifest_case.get('case_id')}"
            )
        if private_case.get("apo_structure_id") != manifest_case.get("structure_id"):
            raise PocketMinerHoldoutMaterializationError("detector/private apo ID mismatch")
        if not private_case.get("apo_chain_id"):
            raise PocketMinerHoldoutMaterializationError("held-out case lacks apo chain ID")
        selected.append(private_case)
    if len(selected) != EXPECTED_CASES:
        raise PocketMinerHoldoutMaterializationError(
            f"held-out materialization requires exactly {EXPECTED_CASES} cases"
        )
    if {str(case.get("split")) for case in selected} != HELDOUT_SPLITS:
        raise PocketMinerHoldoutMaterializationError(
            "validation and temporal/test splits are incomplete"
        )
    return sorted(
        selected, key=lambda case: (str(case.get("split")), str(case["apo_structure_id"]))
    )


def materialize_pocketminer_holdout(
    *,
    cohort_path: Path = DEFAULT_COHORT,
    detector_manifest_path: Path = DEFAULT_DETECTOR_MANIFEST,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    report_path: Path = DEFAULT_REPORT,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> dict[str, Any]:
    if max_total_bytes <= 0 or max_total_bytes > MAX_TOTAL_BYTES:
        raise PocketMinerHoldoutMaterializationError(
            "local output quota must be between 1 byte and 1 GB"
        )
    cohort = _read_json(cohort_path.resolve())
    detector_manifest = _read_json(detector_manifest_path.resolve())
    cases = _select_cases(cohort, detector_manifest)
    if output_root.exists():
        raise PocketMinerHoldoutMaterializationError(
            f"output root already exists; refusing to overwrite: {output_root}"
        )
    raw_root = output_root / "raw_apo"
    prepared_root = output_root / "prepared"
    raw_root.mkdir(parents=True, exist_ok=False)
    prepared_root.mkdir(parents=True, exist_ok=False)

    case_results: list[dict[str, Any]] = []
    total_bytes = 0
    for case in cases:
        structure_id = str(case["apo_structure_id"]).upper()
        chain_id = str(case["apo_chain_id"])
        split = str(case["split"])
        source = StructureSource(
            provider="rcsb", identifier=structure_id, representation="asymmetric_unit"
        )
        try:
            fetched = fetch_structure_input(source, cache_dir=raw_root)
            input_bytes = fetched.path.stat().st_size
            total_bytes += input_bytes
            if total_bytes > max_total_bytes:
                raise PocketMinerHoldoutMaterializationError("held-out output quota exceeded")
            preparation = prepare_structure(
                fetched.path,
                source,
                PreparationConfig(chain_ids=(chain_id,)),
                prepared_root / structure_id,
                f"pocketminer-heldout-{structure_id.lower()}",
                source_metadata=fetched.metadata,
                analysis_config={
                    "study": "pocketminer-ranking-policy-v1",
                    "split": split,
                    "motion_enabled": False,
                    "detector_started": False,
                },
            )
            preparation_report = _read_json(preparation.report_path)
            atom_count = int(preparation_report["counts"]["protein_atoms_selected"])
            try:
                available_memory = get_available_memory_bytes()
                estimate = SAFE_16GB.validate_static_request(
                    atom_count=atom_count, available_memory_bytes=available_memory
                )
                resource = {
                    "status": "ready_for_static_detector_gate",
                    "available_memory_bytes": available_memory,
                    "estimated_static_bytes": estimate,
                }
            except ResourceLimitError as exc:
                resource = {"status": "blocked_safe_16gb", "reason": str(exc)}
            case_results.append(
                {
                    "case_id": case["case_id"],
                    "structure_id": structure_id,
                    "split": split,
                    "apo_chain_id": chain_id,
                    "raw_path": str(fetched.path),
                    "prepared_path": str(preparation.prepared_path),
                    "input_bytes": input_bytes,
                    "protein_atoms_selected": atom_count,
                    "input_sha256": preparation.input_sha256,
                    "prepared_sha256": preparation.prepared_sha256,
                    "preparation_report_sha256": preparation.report_sha256,
                    "resource": resource,
                    "status": "prepared",
                }
            )
        except (FetchError, PreparationError, OSError) as exc:
            case_results.append(
                {
                    "case_id": case["case_id"],
                    "structure_id": structure_id,
                    "split": split,
                    "apo_chain_id": chain_id,
                    "status": "blocked",
                    "error": str(exc),
                }
            )

    prepared_count = sum(item.get("status") == "prepared" for item in case_results)
    resource_ready_count = sum(
        item.get("resource", {}).get("status") == "ready_for_static_detector_gate"
        for item in case_results
        if isinstance(item.get("resource"), Mapping)
    )
    report: dict[str, Any] = {
        "schema_version": "biovoid-pocketminer-heldout-preflight-v1",
        "status": (
            "ready_for_static_detector_gate"
            if prepared_count == EXPECTED_CASES and resource_ready_count == EXPECTED_CASES
            else "blocked_heldout_preflight"
        ),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "cohort_manifest_sha256": _sha256_file(cohort_path.resolve()),
        "detector_manifest_sha256": detector_manifest["manifest_sha256"],
        "constraints": {
            "case_count": EXPECTED_CASES,
            "split_counts": {
                "validation": sum(item["split"] == "validation" for item in case_results),
                "test_temporal": sum(item["split"] == "test" for item in case_results),
            },
            "analysis_workers": 1,
            "safe_profile": SAFE_16GB.name,
            "max_total_bytes": max_total_bytes,
            "include_motion": False,
        },
        "total_raw_bytes": total_bytes,
        "prepared_case_count": prepared_count,
        "resource_ready_case_count": resource_ready_count,
        "cases": case_results,
        "boundary": {
            "apo_only": True,
            "holo_coordinates_opened": False,
            "detector_started": False,
            "evaluator_started": False,
            "model_inference_started": False,
            "nma_started": False,
            "external_baseline_started": False,
            "ml_training_started": False,
        },
    }
    report["report_sha256"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    _write_json(report_path.resolve(), report)
    print(
        f"PocketMiner held-out preflight: {report['status']} "
        f"prepared={prepared_count}/{EXPECTED_CASES} "
        f"resource_ready={resource_ready_count}/{EXPECTED_CASES} bytes={total_bytes}"
    )
    print(f"preflight report: {report_path}")
    print("holo/detector/evaluator/model/NMA/ML started: no")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--detector-manifest", type=Path, default=DEFAULT_DETECTOR_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-total-bytes", type=int, default=MAX_TOTAL_BYTES)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        materialize_pocketminer_holdout(
            cohort_path=args.cohort,
            detector_manifest_path=args.detector_manifest,
            output_root=args.output_root,
            report_path=args.report,
            max_total_bytes=args.max_total_bytes,
        )
    except (PocketMinerHoldoutMaterializationError, OSError) as exc:
        print(f"PocketMiner held-out preflight error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
