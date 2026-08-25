"""Materialize only the sealed AHoJ validation/temporal apo structures.

This is the target-blind held-out preparation gate after development policy A
was selected.  It downloads at most four apo asymmetric-unit CIFs, prepares
full heavy-atom structures, and never opens holo labels or starts a detector,
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

from scripts.seal_ahoj_geometry_cohort import _read_json  # noqa: E402
from src.fetcher import FetchError, fetch_structure_input  # noqa: E402
from src.resources import ResourceLimitError, SAFE_16GB, get_available_memory_bytes  # noqa: E402
from src.structure_preparation import (  # noqa: E402
    PreparationConfig,
    PreparationError,
    StructureSource,
    prepare_structure,
)


DEFAULT_COHORT = (
    REPO_ROOT
    / "local-private/research/geometry-data-source-catalog/ahoj-v1/ahoj-geometry-cohort-v1.json"
)
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "data/runtime/target-family/cohort-ahoj-geometry-v1/ahoj-geometry-detector-manifest-v1.json"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "data/runtime/target-family/cohort-ahoj-geometry-v1/heldout-materialization-v1"
)
DEFAULT_REPORT = DEFAULT_OUTPUT_ROOT / "heldout-preflight-v1.json"
MAX_HELDOUT_CASES = 4
MAX_TOTAL_BYTES = 1 * 1024**3


class AhojHeldoutMaterializationError(RuntimeError):
    """Raised when the sealed held-out preparation contract is invalid."""


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


def _validate_manifest(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if manifest.get("schema_version") != "biovoid-ahoj-geometry-detector-manifest-v1":
        raise AhojHeldoutMaterializationError("unsupported AHoJ detector manifest schema")
    if manifest.get("boundary") != "apo_full_structure_only_v1":
        raise AhojHeldoutMaterializationError("held-out manifest is not apo full-structure only")
    constraints = manifest.get("constraints")
    cases = manifest.get("cases")
    if not isinstance(constraints, Mapping) or not isinstance(cases, list):
        raise AhojHeldoutMaterializationError("manifest constraints/cases are missing")
    if constraints.get("analysis_workers") != 1 or constraints.get("include_motion") is not False:
        raise AhojHeldoutMaterializationError("held-out manifest violates worker/motion boundary")
    selected = [
        case
        for case in cases
        if isinstance(case, Mapping) and case.get("split") in {"validation", "test"}
    ]
    if len(selected) != MAX_HELDOUT_CASES:
        raise AhojHeldoutMaterializationError("held-out manifest must contain 2 validation + 2 test cases")
    return sorted(selected, key=lambda case: str(case["case_id"]))


def _select_private_cases(
    cohort: Mapping[str, Any], manifest_cases: list[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    private_cases = cohort.get("cases")
    if not isinstance(private_cases, list):
        raise AhojHeldoutMaterializationError("private cohort cases are missing")
    by_id = {str(case.get("case_id")): case for case in private_cases if isinstance(case, Mapping)}
    selected: list[Mapping[str, Any]] = []
    for manifest_case in manifest_cases:
        case_id = str(manifest_case["case_id"])
        private_case = by_id.get(case_id)
        if private_case is None or private_case.get("split") not in {"validation", "temporal"}:
            raise AhojHeldoutMaterializationError(f"private held-out case missing: {case_id}")
        expected_split = "temporal" if manifest_case.get("split") == "test" else "validation"
        if private_case.get("split") != expected_split:
            raise AhojHeldoutMaterializationError(f"held-out split mismatch: {case_id}")
        if str(private_case.get("apo_structure_id")).upper() != str(
            manifest_case.get("structure_id")
        ).upper():
            raise AhojHeldoutMaterializationError(f"held-out apo structure mismatch: {case_id}")
        selected.append(private_case)
    return sorted(selected, key=lambda case: str(case["apo_structure_id"]))


def materialize_ahoj_geometry_heldout(
    *,
    cohort_path: Path = DEFAULT_COHORT,
    manifest_path: Path = DEFAULT_MANIFEST,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    report_path: Path = DEFAULT_REPORT,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> dict[str, Any]:
    if not 1 <= max_total_bytes <= MAX_TOTAL_BYTES:
        raise AhojHeldoutMaterializationError("local output quota must be between 1 byte and 1 GB")
    cohort = _read_json(cohort_path.resolve())
    manifest = _read_json(manifest_path.resolve())
    manifest_cases = _validate_manifest(manifest)
    cases = _select_private_cases(cohort, manifest_cases)
    if output_root.exists() and any(output_root.iterdir()):
        raise AhojHeldoutMaterializationError(f"output root is not empty: {output_root}")
    raw_root = output_root / "raw_apo"
    prepared_root = output_root / "prepared"
    raw_root.mkdir(parents=True, exist_ok=False)
    prepared_root.mkdir(parents=True, exist_ok=False)
    total_bytes = 0
    results: list[dict[str, Any]] = []
    for case in cases:
        structure_id = str(case["apo_structure_id"]).upper()
        manifest_case = next(item for item in manifest_cases if item["case_id"] == case["case_id"])
        split = "temporal" if manifest_case["split"] == "test" else "validation"
        source = StructureSource(provider="rcsb", identifier=structure_id, representation="asymmetric_unit")
        try:
            fetched = fetch_structure_input(source, cache_dir=raw_root)
            input_bytes = fetched.path.stat().st_size
            total_bytes += input_bytes
            if total_bytes > max_total_bytes:
                raise AhojHeldoutMaterializationError("held-out output quota exceeded")
            case_dir = prepared_root / structure_id
            preparation = prepare_structure(
                fetched.path,
                source,
                PreparationConfig(chain_ids=None),
                case_dir,
                f"ahoj-geometry-heldout-{structure_id.lower()}",
                source_metadata=fetched.metadata,
                analysis_config={
                    "study": "ahoj-geometry-research-v1",
                    "split": split,
                    "heldout": True,
                    "full_heavy_atom_structure": True,
                    "motion_enabled": False,
                    "detector_started": False,
                    "evaluator_started": False,
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
                    "status": "ready_for_heldout_static_gate",
                    "available_memory_bytes": available_memory,
                    "estimated_static_bytes": estimate,
                }
            except ResourceLimitError as exc:
                resource = {"status": "blocked_safe_16gb", "reason": str(exc)}
            results.append(
                {
                    "case_id": case["case_id"],
                    "structure_id": structure_id,
                    "split": split,
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
        except (FetchError, PreparationError, OSError, AhojHeldoutMaterializationError) as exc:
            results.append(
                {
                    "case_id": case["case_id"],
                    "structure_id": structure_id,
                    "split": split,
                    "status": "blocked",
                    "error": str(exc)[:500],
                }
            )
    prepared_count = sum(item.get("status") == "prepared" for item in results)
    resource_ready_count = sum(
        item.get("resource", {}).get("status") == "ready_for_heldout_static_gate"
        for item in results
        if isinstance(item.get("resource"), Mapping)
    )
    report: dict[str, Any] = {
        "schema_version": "biovoid-ahoj-geometry-heldout-preflight-v1",
        "status": (
            "ready_for_heldout_static_gate"
            if prepared_count == MAX_HELDOUT_CASES and resource_ready_count == MAX_HELDOUT_CASES
            else "blocked_heldout_preflight"
        ),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "cohort_sha256": _sha256_file(cohort_path.resolve()),
        "detector_manifest_sha256": manifest.get("manifest_sha256"),
        "constraints": {
            "case_count": MAX_HELDOUT_CASES,
            "split_counts": {"validation": 2, "temporal": 2},
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
        "report_sha256": None,
    }
    report["report_sha256"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    _write_json(report_path.resolve(), report)
    print(
        f"AHoJ held-out preflight: {report['status']} prepared={prepared_count}/4 "
        f"resource_ready={resource_ready_count}/4 bytes={total_bytes}"
    )
    print(f"preflight report: {report_path}")
    print("holo/detector/evaluator/model/NMA/ML started: no")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-total-bytes", type=int, default=MAX_TOTAL_BYTES)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        report = materialize_ahoj_geometry_heldout(
            cohort_path=args.cohort,
            manifest_path=args.manifest,
            output_root=args.output_root,
            report_path=args.report,
            max_total_bytes=args.max_total_bytes,
        )
    except (AhojHeldoutMaterializationError, OSError, ValueError) as exc:
        print(f"AHoJ held-out materialization error: {exc}", file=sys.stderr)
        return 2
    return 0 if report["status"] == "ready_for_heldout_static_gate" else 2


if __name__ == "__main__":
    raise SystemExit(main())
