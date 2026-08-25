"""Run the canonical static detector on the sealed development apo subset.

The command consumes the frozen apo-only detector manifest and the successful
development preparation preflight. It runs one case at a time with the
unchanged `safe-16gb` profile, retains every final merged pocket, and writes a
target-blind static artifact. Validation/temporal rows, holo data, evaluator
labels, NMA, external baselines, and ML are not opened.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.resources import ResourceLimitError, SAFE_16GB  # noqa: E402
from src.runtime import CanonicalInputError  # noqa: E402
from src.static_detector import detect_static_pockets  # noqa: E402
from src.target_family_cohort import (  # noqa: E402
    CohortContractError,
    validate_target_blind_manifest,
)


DEFAULT_MANIFEST = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/pocketminer-detector-manifest-v1.json"
)
DEFAULT_PREFLIGHT = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/development-materialization-v1/"
    "development-preflight-v1.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "data/runtime/ranking-study/pocketminer-v1/development-static-v1/"
    "pocketminer-development-static-v1.json"
)


class PocketMinerStaticRunError(RuntimeError):
    """Raised when the target-blind static run contract cannot be satisfied."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PocketMinerStaticRunError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PocketMinerStaticRunError(f"JSON must be an object: {path}")
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


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    try:
        validate_target_blind_manifest(manifest)
    except CohortContractError as exc:
        raise PocketMinerStaticRunError(str(exc)) from exc
    serialized = json.dumps(manifest, ensure_ascii=True).casefold()
    if any(token in serialized for token in ("holo", "ligand", "evaluator", "ground_truth")):
        raise PocketMinerStaticRunError("detector manifest contains evaluator data")


def _development_preflight_index(preflight: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if preflight.get("status") != "ready_for_static_detector_gate":
        raise PocketMinerStaticRunError("development preflight is not ready")
    cases = preflight.get("cases")
    if not isinstance(cases, list):
        raise PocketMinerStaticRunError("development preflight cases are missing")
    indexed: dict[str, Mapping[str, Any]] = {}
    for case in cases:
        if not isinstance(case, Mapping) or case.get("status") != "prepared":
            raise PocketMinerStaticRunError("development preflight contains blocked cases")
        structure_id = str(case.get("structure_id", "")).upper()
        prepared_path = Path(str(case.get("prepared_path", "")))
        prepared_sha256 = str(case.get("prepared_sha256", ""))
        if not structure_id or not prepared_path.is_file() or len(prepared_sha256) != 64:
            raise PocketMinerStaticRunError(
                f"prepared development input is incomplete: {structure_id}"
            )
        indexed[structure_id] = case
    if len(indexed) != 6:
        raise PocketMinerStaticRunError("static development run requires six prepared cases")
    return indexed


def run_pocketminer_development_static(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    preflight_path: Path = DEFAULT_PREFLIGHT,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path.resolve())
    preflight = _read_json(preflight_path.resolve())
    _validate_manifest(manifest)
    prepared = _development_preflight_index(preflight)
    development_cases = [
        case
        for case in manifest.get("cases", [])
        if isinstance(case, Mapping) and case.get("split") == "development"
    ]
    if len(development_cases) != 6:
        raise PocketMinerStaticRunError("detector manifest must contain six development cases")
    if output_path.exists():
        raise PocketMinerStaticRunError(f"refusing to overwrite static output: {output_path}")

    records: list[dict[str, Any]] = []
    for manifest_case in sorted(development_cases, key=lambda item: str(item["structure_id"])):
        structure_id = str(manifest_case["structure_id"]).upper()
        preflight_case = prepared.get(structure_id)
        if preflight_case is None:
            raise PocketMinerStaticRunError(f"preflight missing manifest case: {structure_id}")
        prepared_path = Path(str(preflight_case["prepared_path"]))
        prepared_sha256 = str(preflight_case["prepared_sha256"])
        started = time.perf_counter()
        try:
            result = detect_static_pockets(
                prepared_path,
                prepared_sha256=prepared_sha256,
                resource_profile=SAFE_16GB,
            )
            records.append(
                {
                    "case_id": manifest_case["case_id"],
                    "structure_id": structure_id,
                    "split": "development",
                    "status": "completed",
                    "runtime_seconds": round(time.perf_counter() - started, 3),
                    "detector": {
                        "version": result.detector_version,
                        "config_sha256": result.config_sha256,
                        "atom_policy_version": result.atom_policy_version,
                        "radius_provenance": result.radius_provenance,
                        "surface_model": result.surface_model,
                        "volume_method": result.volume_method,
                        "prepared_structure_sha256": result.prepared_structure_sha256,
                        "protein_atom_count": result.protein_atom_count,
                        "raw_voronoi_candidate_count": result.candidate_count,
                        "final_pocket_count": len(result.pockets),
                        "warnings": list(result.warnings),
                        "retention": "full_final_pocket_list",
                        "raw_voronoi_list_retained": False,
                    },
                    "final_pockets": [pocket.to_portable_dict() for pocket in result.pockets],
                }
            )
        except (CanonicalInputError, ResourceLimitError, OSError, ValueError) as exc:
            records.append(
                {
                    "case_id": manifest_case["case_id"],
                    "structure_id": structure_id,
                    "split": "development",
                    "status": "blocked",
                    "runtime_seconds": round(time.perf_counter() - started, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                    "final_pockets": [],
                }
            )

    completed = sum(record["status"] == "completed" for record in records)
    report: dict[str, Any] = {
        "schema_version": "biovoid-pocketminer-development-static-v1",
        "status": "completed" if completed == 6 else "blocked_cases_present",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "manifest_sha256": manifest["manifest_sha256"],
        "manifest_path": str(manifest_path),
        "preflight_report_sha256": _sha256_file(preflight_path.resolve()),
        "detector": "biovoid_static",
        "ranking_policy": "canonical-volume-v1",
        "retention": "full_final_pocket_list",
        "case_count": len(records),
        "completed_case_count": completed,
        "records": records,
        "boundary": {
            "target_blind": True,
            "holo_coordinates_opened": False,
            "evaluator_started": False,
            "motion_enabled": False,
            "external_baseline_started": False,
            "ml_training_started": False,
        },
    }
    report["report_sha256"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    _write_json(output_path.resolve(), report)
    print(f"PocketMiner development static: {report['status']} completed={completed}/6")
    print(f"static report: {output_path}")
    print("holo/evaluator/NMA/external baseline/ML started: no")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        run_pocketminer_development_static(
            manifest_path=args.manifest,
            preflight_path=args.preflight,
            output_path=args.output,
        )
    except (PocketMinerStaticRunError, OSError) as exc:
        print(f"PocketMiner development static error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
