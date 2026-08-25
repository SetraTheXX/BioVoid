"""Materialize and prepare only the sealed AHoJ development apo cases.

This is a bounded full-structure preparation/resource gate.  It downloads at
most six apo asymmetric-unit CIF files, prepares all protein chains with the
canonical heavy-atom policy, and never opens holo files or starts a detector,
evaluator, NMA, external baseline, or ML run.
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
from scripts.seal_ahoj_geometry_cohort import (  # noqa: E402
    AhojMetadataResolutionError,
    _read_json,
)

DEFAULT_COHORT = (
    REPO_ROOT / "local-private/research/geometry-data-source-catalog/ahoj-v1/"
    "ahoj-geometry-cohort-v1.json"
)
DEFAULT_DETECTOR_MANIFEST = (
    REPO_ROOT / "data/runtime/target-family/cohort-ahoj-geometry-v1/"
    "ahoj-geometry-detector-manifest-v1.json"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "data/runtime/target-family/cohort-ahoj-geometry-v1/development-materialization-v1"
)
DEFAULT_REPORT = DEFAULT_OUTPUT_ROOT / "development-preflight-v1.json"
MAX_DEVELOPMENT_CASES = 6
MAX_TOTAL_BYTES = 1 * 1024**3


class AhojDevelopmentMaterializationError(RuntimeError):
    """Raised when the bounded AHoJ development preparation contract is invalid."""


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
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != "biovoid-ahoj-geometry-detector-manifest-v1":
        raise AhojDevelopmentMaterializationError("unsupported AHoJ detector manifest schema")
    if manifest.get("materialization_status") != "metadata_only":
        raise AhojDevelopmentMaterializationError("detector manifest must be metadata-only")
    if manifest.get("boundary") != "apo_full_structure_only_v1":
        raise AhojDevelopmentMaterializationError(
            "detector manifest is not full-structure apo-only"
        )
    serialized = json.dumps(manifest, ensure_ascii=True).casefold()
    for forbidden in ("holo", "ligand", "evaluator", "ground_truth", "bio_score"):
        if forbidden in serialized:
            raise AhojDevelopmentMaterializationError(
                f"detector manifest contains forbidden evaluator token: {forbidden}"
            )
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 10:
        raise AhojDevelopmentMaterializationError("AHoJ detector manifest must contain 10 cases")
    if sum(case.get("split") == "development" for case in cases if isinstance(case, Mapping)) != 6:
        raise AhojDevelopmentMaterializationError(
            "AHoJ detector manifest must contain 6 development cases"
        )


def select_development_cases(
    cohort: Mapping[str, Any], manifest: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    _validate_manifest(manifest)
    raw_cases = cohort.get("cases")
    if not isinstance(raw_cases, list):
        raise AhojDevelopmentMaterializationError("private AHoJ cohort cases are missing")
    by_case_id = {str(case.get("case_id")): case for case in raw_cases if isinstance(case, Mapping)}
    selected: list[Mapping[str, Any]] = []
    for detector_case in manifest["cases"]:
        if detector_case.get("split") != "development":
            continue
        case = by_case_id.get(str(detector_case.get("case_id")))
        if case is None:
            raise AhojDevelopmentMaterializationError("detector case is absent from private cohort")
        if case.get("apo_structure_id") != detector_case.get("structure_id"):
            raise AhojDevelopmentMaterializationError("detector/private apo structure mismatch")
        if not isinstance(case.get("apo_chain_ids"), list) or not case["apo_chain_ids"]:
            raise AhojDevelopmentMaterializationError(
                "full-structure apo chain metadata is missing"
            )
        selected.append(case)
    if len(selected) != MAX_DEVELOPMENT_CASES:
        raise AhojDevelopmentMaterializationError("exactly six development cases are required")
    return sorted(selected, key=lambda case: str(case["apo_structure_id"]))


def materialize_ahoj_geometry_development(
    *,
    cohort_path: Path = DEFAULT_COHORT,
    detector_manifest_path: Path = DEFAULT_DETECTOR_MANIFEST,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    report_path: Path = DEFAULT_REPORT,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> dict[str, Any]:
    if not 1 <= max_total_bytes <= MAX_TOTAL_BYTES:
        raise AhojDevelopmentMaterializationError(
            "local output quota must be between 1 byte and 1 GB"
        )
    cohort = _read_json(cohort_path.resolve())
    manifest = _read_json(detector_manifest_path.resolve())
    cases = select_development_cases(cohort, manifest)
    if output_root.exists():
        raise AhojDevelopmentMaterializationError(
            f"output root already exists; refusing to overwrite: {output_root}"
        )
    raw_root = output_root / "raw_apo"
    prepared_root = output_root / "prepared"
    raw_root.mkdir(parents=True, exist_ok=False)
    prepared_root.mkdir(parents=True, exist_ok=False)

    total_bytes = 0
    results: list[dict[str, Any]] = []
    for case in cases:
        structure_id = str(case["apo_structure_id"]).upper()
        source = StructureSource(
            provider="rcsb", identifier=structure_id, representation="asymmetric_unit"
        )
        try:
            fetched = fetch_structure_input(source, cache_dir=raw_root)
            input_bytes = fetched.path.stat().st_size
            total_bytes += input_bytes
            if total_bytes > max_total_bytes:
                raise AhojDevelopmentMaterializationError("development output quota exceeded")
            case_dir = prepared_root / structure_id
            preparation = prepare_structure(
                fetched.path,
                source,
                PreparationConfig(chain_ids=None),
                case_dir,
                f"ahoj-geometry-development-{structure_id.lower()}",
                source_metadata=fetched.metadata,
                analysis_config={
                    "study": "ahoj-geometry-research-v1",
                    "split": "development",
                    "full_heavy_atom_structure": True,
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
            results.append(
                {
                    "case_id": case["case_id"],
                    "structure_id": structure_id,
                    "split": "development",
                    "selected_apo_chain_ids": preparation_report.get("selected_chains", []),
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
        except (FetchError, PreparationError, OSError, AhojDevelopmentMaterializationError) as exc:
            results.append(
                {
                    "case_id": case["case_id"],
                    "structure_id": structure_id,
                    "split": "development",
                    "status": "blocked",
                    "error": str(exc),
                }
            )

    prepared_count = sum(item.get("status") == "prepared" for item in results)
    resource_ready_count = sum(
        item.get("resource", {}).get("status") == "ready_for_static_detector_gate"
        for item in results
        if isinstance(item.get("resource"), Mapping)
    )
    report: dict[str, Any] = {
        "schema_version": "biovoid-ahoj-geometry-development-preflight-v1",
        "status": (
            "ready_for_static_detector_gate"
            if prepared_count == MAX_DEVELOPMENT_CASES
            and resource_ready_count == MAX_DEVELOPMENT_CASES
            else "blocked_development_preflight"
        ),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "cohort_manifest_sha256": _sha256_file(cohort_path.resolve()),
        "detector_manifest_sha256": manifest["manifest_sha256"],
        "constraints": {
            "case_count": MAX_DEVELOPMENT_CASES,
            "analysis_workers": 1,
            "safe_profile": SAFE_16GB.name,
            "max_total_bytes": max_total_bytes,
            "include_motion": False,
            "full_heavy_atom_structure": True,
        },
        "total_raw_bytes": total_bytes,
        "prepared_case_count": prepared_count,
        "resource_ready_case_count": resource_ready_count,
        "cases": results,
        "boundary": {
            "apo_only": True,
            "full_structure_preparation": True,
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
        f"AHoJ development preflight: {report['status']} prepared={prepared_count}/6 "
        f"resource_ready={resource_ready_count}/6 bytes={total_bytes}"
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
        materialize_ahoj_geometry_development(
            cohort_path=args.cohort,
            detector_manifest_path=args.detector_manifest,
            output_root=args.output_root,
            report_path=args.report,
            max_total_bytes=args.max_total_bytes,
        )
    except (AhojDevelopmentMaterializationError, OSError, ValueError) as exc:
        print(f"AHoJ development materialization error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
