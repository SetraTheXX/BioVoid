"""Run the bounded RI-6 target-blind static arm for the approved 5UL8 source.

This is deliberately one structure, one process, and static-only. It creates
an ignored runtime candidate manifest for independent review; it does not read
holo coordinates, run NMA, call external baselines, or make a discovery claim.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_ri6_tem1_transfer_control import (  # noqa: E402
    RI6ContractError,
    _stable_hash,
    _validate_target_blind_manifest,
)
from src.static_detector import detect_static_pockets  # noqa: E402
from src.structure_preparation import (  # noqa: E402
    PreparationConfig,
    StructureSource,
    prepare_structure,
)


DEFAULT_ROOT = REPO_ROOT / "data/runtime/ri6/prospective-static"
RCSB_DOWNLOAD = "https://files.rcsb.org/download/5UL8.cif"
SOURCE_ID = "5UL8"
SOURCE_UNIPROT = "Q9F663"
OUTPUT_SCHEMA_VERSION = "biovoid-ri6-prospective-static-run-v1"
FORBIDDEN_FIELDS = {
    "holo_pdb_id",
    "holo_path",
    "ligand_center",
    "target_center",
    "target_residues",
    "hit_label",
}


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


def _build_source_review_decision(*, user_approved: bool) -> dict[str, Any]:
    if not user_approved:
        raise RI6ContractError("5UL8 requires explicit user approval before execution")
    return {
        "schema_version": "biovoid-ri6-source-review-decision-v1",
        "source_id": SOURCE_ID,
        "uniprot_accession": SOURCE_UNIPROT,
        "review_status": "user_approved_for_bounded_static_run",
        "review_basis": [
            "Frozen RI-6 target lock inclusion rules",
            "RCSB metadata-only inventory review",
            "Explicit user approval in the current task",
        ],
        "independent_review_status": "pending",
        "interpretation_authorized": False,
        "coordinate_download_authorized": True,
        "scope": "one target-blind static run only",
    }


def _build_target_blind_input_manifest(
    *,
    prepared_path: str,
    prepared_sha256: str,
    preparation_config_sha256: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "biovoid-ri6-prospective-detector-input-v1",
        "structure_id": SOURCE_ID,
        "prepared_path": prepared_path,
        "prepared_structure_sha256": prepared_sha256,
        "preparation_config_sha256": preparation_config_sha256,
        "detector_target_blind": True,
        "motion_enabled": False,
        "external_baselines_enabled": False,
        "evaluator_fields_in_manifest": False,
        "scope": "bounded_static_source_review_run",
    }
    payload["manifest_sha256"] = _stable_hash(payload)
    return payload


def _validate_prospective_output(
    payload: Mapping[str, Any], *, verify_hash: bool = True
) -> None:
    if verify_hash:
        expected = _stable_hash(
            {key: value for key, value in payload.items() if key != "run_sha256"}
        )
        if payload.get("run_sha256") != expected:
            raise RI6ContractError("RI-6 prospective output hash does not match its content")
    if payload.get("schema_version") != OUTPUT_SCHEMA_VERSION:
        raise RI6ContractError("Unexpected RI-6 prospective output schema")
    if payload.get("status") != "completed_target_blind_static_run_interpretation_pending":
        raise RI6ContractError("RI-6 prospective output is not review-pending")
    if payload.get("detector_target_blind") is not True:
        raise RI6ContractError("RI-6 prospective output is not target-blind")
    if payload.get("motion_enabled") is not False:
        raise RI6ContractError("RI-6 prospective output enabled motion unexpectedly")
    if payload.get("claim_boundary") != "unvalidated_research_leads_only":
        raise RI6ContractError("RI-6 prospective output has an unsafe claim boundary")
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True).lower()
    for field in FORBIDDEN_FIELDS:
        if f'"{field}"' in encoded:
            raise RI6ContractError(f"Evaluator field leaked into prospective output: {field}")
    if any(term in encoded for term in ("discovery", "drug candidate", "validated prediction")):
        raise RI6ContractError("Prospective output contains an unsupported scientific claim")
    if payload.get("independent_review_status") != "pending":
        raise RI6ContractError("Prospective output changed the independent review status")
    candidates = payload.get("candidates", [])
    if len(candidates) > int(payload.get("candidate_budget", 0)):
        raise RI6ContractError("Prospective candidate count exceeds its frozen budget")


def _download_source(destination: Path) -> None:
    if destination.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(RCSB_DOWNLOAD, timeout=60)
    response.raise_for_status()
    destination.write_bytes(response.content)


def run_prospective_static(
    *,
    output_root: Path = DEFAULT_ROOT,
    user_approved: bool = False,
) -> dict[str, Any]:
    decision = _build_source_review_decision(user_approved=user_approved)
    source_path = output_root / "source" / f"{SOURCE_ID}.cif"
    _download_source(source_path)
    prepared_run = output_root / "prepared" / "5ul8-static-v1"
    if prepared_run.exists():
        raise RI6ContractError(f"RI-6 run already exists: {prepared_run}")
    preparation = prepare_structure(
        source_path,
        StructureSource(
            provider="rcsb",
            identifier=SOURCE_ID,
            representation="asymmetric_unit",
        ),
        PreparationConfig(chain_ids=("A",)),
        prepared_run,
        "ri6-5ul8-static-v1",
        source_metadata={
            "provider": "RCSB PDB",
            "entry_id": SOURCE_ID,
            "uniprot_accession": SOURCE_UNIPROT,
            "source_review_status": decision["review_status"],
        },
        analysis_config={
            "phase": "RI-6",
            "motion_enabled": False,
            "external_baselines_enabled": False,
            "resource_profile": "safe-16gb",
            "heavy_concurrency": 1,
        },
    )
    input_manifest = _build_target_blind_input_manifest(
        prepared_path=str(preparation.prepared_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        prepared_sha256=preparation.prepared_sha256,
        preparation_config_sha256=preparation.config_sha256,
    )
    _validate_target_blind_manifest(input_manifest)
    _write_json(output_root / "source-review-decision-v1.json", decision)
    _write_json(output_root / "detector-input-v1.json", input_manifest)

    detection = detect_static_pockets(
        preparation.prepared_path,
        prepared_sha256=preparation.prepared_sha256,
    )
    candidates = [
        {
            "rank": rank,
            "pocket": pocket.to_portable_dict(),
            "selection_basis": "canonical detector rank; evaluator score not used",
        }
        for rank, pocket in enumerate(detection.pockets[:10], start=1)
    ]
    output: dict[str, Any] = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "status": "completed_target_blind_static_run_interpretation_pending",
        "source_id": SOURCE_ID,
        "source_uniprot_accession": SOURCE_UNIPROT,
        "source_review_status": decision["review_status"],
        "independent_review_status": "pending",
        "interpretation_authorized": False,
        "detector_target_blind": True,
        "motion_enabled": False,
        "external_baselines_enabled": False,
        "candidate_budget": 10,
        "detector_candidate_count": len(detection.pockets),
        "candidates": candidates,
        "detector_version": detection.detector_version,
        "detector_config_sha256": detection.config_sha256,
        "prepared_structure_sha256": preparation.prepared_sha256,
        "detector_input_manifest_sha256": input_manifest["manifest_sha256"],
        "claim_boundary": "unvalidated_research_leads_only",
        "limitations": [
            "One source only; no transferability or performance conclusion.",
            "Independent review has not interpreted candidate pocket coordinates.",
            "Canonical motion-aware arm remains disabled and not eligible.",
        ],
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    output["run_sha256"] = _stable_hash(output)
    _validate_prospective_output(output)
    _write_json(output_root / "ri6-prospective-static-run-v1.json", output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--approve-source",
        action="store_true",
        help="Use the current user's explicit approval for the bounded 5UL8 run",
    )
    args = parser.parse_args()
    output = run_prospective_static(
        output_root=args.output_root.resolve(),
        user_approved=args.approve_source,
    )
    print(f"status={output['status']}")
    print(f"detector_candidate_count={output['detector_candidate_count']}")
    print(f"candidate_count={len(output['candidates'])}")
    print(f"run_sha256={output['run_sha256']}")
    print("independent_review_status=pending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
