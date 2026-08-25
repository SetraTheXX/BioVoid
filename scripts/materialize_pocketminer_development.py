"""Materialize and prepare only the sealed PocketMiner development apo cases.

This is a bounded preparation/resource preflight. It downloads at most six
apo asymmetric-unit structures under the local quota, selects the declared
apo chain, and never opens holo data or starts the pocket detector, evaluator,
NMA, external baselines, or ML.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.fetcher import FetchError, fetch_structure_input  # noqa: E402
from src.resources import (  # noqa: E402
    ResourceLimitError,
    SAFE_16GB,
    get_available_memory_bytes,
)
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
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/development-materialization-v1"
)
DEFAULT_REPORT = DEFAULT_OUTPUT_ROOT / "development-preflight-v1.json"
MAX_DEVELOPMENT_CASES = 6
MAX_TOTAL_BYTES = 1 * 1024**3


class PocketMinerMaterializationError(RuntimeError):
    """Raised when the bounded development preparation contract is invalid."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PocketMinerMaterializationError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PocketMinerMaterializationError(f"JSON must be an object: {path}")
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


def select_development_cases(
    cohort: Mapping[str, Any], detector_manifest: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    """Join the redacted development IDs to private chain metadata."""

    try:
        validate_target_blind_manifest(detector_manifest)
    except CohortContractError as exc:
        raise PocketMinerMaterializationError(str(exc)) from exc
    if detector_manifest.get("materialization_status") != "metadata_only":
        raise PocketMinerMaterializationError("detector manifest is not metadata-only")
    if "holo" in json.dumps(detector_manifest, ensure_ascii=True).casefold():
        raise PocketMinerMaterializationError("detector manifest contains holo data")
    private_cases = cohort.get("cases")
    if not isinstance(private_cases, list):
        raise PocketMinerMaterializationError("private cohort cases are missing")
    by_case_id = {
        str(case.get("case_id")): case for case in private_cases if isinstance(case, Mapping)
    }
    development: list[Mapping[str, Any]] = []
    for case in detector_manifest.get("cases", []):
        if not isinstance(case, Mapping) or case.get("split") != "development":
            continue
        private_case = by_case_id.get(str(case.get("case_id")))
        if private_case is None:
            raise PocketMinerMaterializationError(
                f"detector case missing from private cohort: {case.get('case_id')}"
            )
        if private_case.get("apo_structure_id") != case.get("structure_id"):
            raise PocketMinerMaterializationError("detector/private apo ID mismatch")
        if not private_case.get("apo_chain_id"):
            raise PocketMinerMaterializationError("development case lacks apo chain ID")
        development.append(private_case)
    if len(development) != MAX_DEVELOPMENT_CASES:
        raise PocketMinerMaterializationError(
            f"development materialization requires exactly {MAX_DEVELOPMENT_CASES} cases"
        )
    return sorted(development, key=lambda case: str(case["apo_structure_id"]))


def materialize_pocketminer_development(
    *,
    cohort_path: Path = DEFAULT_COHORT,
    detector_manifest_path: Path = DEFAULT_DETECTOR_MANIFEST,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    report_path: Path = DEFAULT_REPORT,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> dict[str, Any]:
    if max_total_bytes <= 0 or max_total_bytes > MAX_TOTAL_BYTES:
        raise PocketMinerMaterializationError("local output quota must be between 1 byte and 1 GB")
    cohort = _read_json(cohort_path.resolve())
    detector_manifest = _read_json(detector_manifest_path.resolve())
    cases = select_development_cases(cohort, detector_manifest)
    raw_root = output_root / "raw_apo"
    prepared_root = output_root / "prepared"
    if output_root.exists():
        raise PocketMinerMaterializationError(
            f"output root already exists; refusing to overwrite: {output_root}"
        )
    raw_root.mkdir(parents=True, exist_ok=False)
    prepared_root.mkdir(parents=True, exist_ok=False)

    case_results: list[dict[str, Any]] = []
    total_bytes = 0
    for case in cases:
        structure_id = str(case["apo_structure_id"]).upper()
        chain_id = str(case["apo_chain_id"])
        source = StructureSource(
            provider="rcsb",
            identifier=structure_id,
            representation="asymmetric_unit",
        )
        try:
            fetched = fetch_structure_input(source, cache_dir=raw_root)
            input_bytes = fetched.path.stat().st_size
            total_bytes += input_bytes
            if total_bytes > max_total_bytes:
                raise PocketMinerMaterializationError("development output quota exceeded")
            case_dir = prepared_root / structure_id
            preparation = prepare_structure(
                fetched.path,
                source,
                PreparationConfig(chain_ids=(chain_id,)),
                case_dir,
                f"pocketminer-development-{structure_id.lower()}",
                source_metadata=fetched.metadata,
                analysis_config={
                    "study": "pocketminer-ranking-policy-v1",
                    "split": "development",
                    "motion_enabled": False,
                    "detector_started": False,
                },
            )
            preparation_report = _read_json(preparation.report_path)
            atom_count = int(preparation_report["counts"]["protein_atoms_selected"])
            try:
                available_memory = get_available_memory_bytes()
                estimate = SAFE_16GB.validate_static_request(
                    atom_count=atom_count,
                    available_memory_bytes=available_memory,
                )
                resource = {
                    "status": "ready_for_static_detector_gate",
                    "available_memory_bytes": available_memory,
                    "estimated_static_bytes": estimate,
                }
            except ResourceLimitError as exc:
                resource = {
                    "status": "blocked_safe_16gb",
                    "reason": str(exc),
                }
            case_results.append(
                {
                    "case_id": case["case_id"],
                    "structure_id": structure_id,
                    "split": "development",
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
                    "split": "development",
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
        "schema_version": "biovoid-pocketminer-development-preflight-v1",
        "status": (
            "ready_for_static_detector_gate"
            if prepared_count == MAX_DEVELOPMENT_CASES
            and resource_ready_count == MAX_DEVELOPMENT_CASES
            else "blocked_development_preflight"
        ),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "cohort_manifest_sha256": _sha256_file(cohort_path.resolve()),
        "detector_manifest_sha256": detector_manifest["manifest_sha256"],
        "constraints": {
            "case_count": MAX_DEVELOPMENT_CASES,
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
        f"PocketMiner development preflight: {report['status']} "
        f"prepared={prepared_count}/{MAX_DEVELOPMENT_CASES} "
        f"resource_ready={resource_ready_count}/{MAX_DEVELOPMENT_CASES} "
        f"bytes={total_bytes}"
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
        materialize_pocketminer_development(
            cohort_path=args.cohort,
            detector_manifest_path=args.detector_manifest,
            output_root=args.output_root,
            report_path=args.report,
            max_total_bytes=args.max_total_bytes,
        )
    except (PocketMinerMaterializationError, OSError) as exc:
        print(f"PocketMiner development preflight error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
