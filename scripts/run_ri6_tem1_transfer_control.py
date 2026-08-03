"""Run the bounded, target-blind TEM-1 transfer control for RI-6.

The detector arm receives only prepared apo-like 1JWP coordinates. The 1PZO
inhibitor coordinates are opened by the evaluator after the detector record is
written, so this control cannot be used to tune or steer pocket generation.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.benchmark_v1 import evaluate_case, phase6_frozen_protocol_v1  # noqa: E402
from src.evaluator_format import adapt_biovoid_pockets  # noqa: E402
from src.ground_truth_alignment import (  # noqa: E402
    AlignmentPolicy,
    ChainPair,
    LigandSelector,
    build_aligned_ground_truth_from_files,
)
from src.static_detector import detect_static_pockets  # noqa: E402
from src.structure_preparation import (  # noqa: E402
    PreparationConfig,
    StructureSource,
    prepare_structure,
)


DEFAULT_ROOT = REPO_ROOT / "data/runtime/ri6/tem1"
RCSB_DOWNLOAD = "https://files.rcsb.org/download/{structure_id}.cif"
FORBIDDEN_DETECTOR_FIELDS = {
    "holo_pdb_id",
    "holo_path",
    "ligand",
    "ligand_center",
    "target_center",
    "target_residues",
    "hit_label",
}


class RI6ContractError(RuntimeError):
    """Raised when the RI-6 target-blind or source-lock contract is violated."""


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


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


def _download(structure_id: str, destination: Path) -> None:
    if destination.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(RCSB_DOWNLOAD.format(structure_id=structure_id), timeout=60)
    response.raise_for_status()
    destination.write_bytes(response.content)


def _build_target_blind_manifest(
    *,
    prepared_path: str,
    prepared_sha256: str,
    preparation_config_sha256: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "biovoid-ri6-tem1-detector-input-v1",
        "control_id": "tem1-m182t-cryptic-site-retrodiction-v1",
        "structure_id": "1JWP",
        "prepared_path": prepared_path,
        "prepared_structure_sha256": prepared_sha256,
        "preparation_config_sha256": preparation_config_sha256,
        "detector_target_blind": True,
        "control_scope": "retrodiction_only_not_prospective_evidence",
    }
    payload["manifest_sha256"] = _stable_hash(payload)
    return payload


def _validate_target_blind_manifest(payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True).lower()
    for field in FORBIDDEN_DETECTOR_FIELDS:
        if f'"{field}"' in encoded:
            raise RI6ContractError(f"Evaluator field leaked into detector manifest: {field}")
    if "1pzo" in encoded or "cbt" in encoded:
        raise RI6ContractError("Evaluator structure or ligand leaked into detector manifest")
    if payload.get("detector_target_blind") is not True:
        raise RI6ContractError("Detector manifest is not explicitly target-blind")
    expected = _stable_hash({k: v for k, v in payload.items() if k != "manifest_sha256"})
    if payload.get("manifest_sha256") != expected:
        raise RI6ContractError("Detector manifest hash does not match its content")


def run_control(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    source_dir = root / "source"
    apo_source = source_dir / "1JWP.cif"
    holo_source = source_dir / "1PZO.cif"
    _download("1JWP", apo_source)

    prepared_root = root / "prepared"
    prepared_run = prepared_root / "tem1-1jwp-v1"
    if prepared_run.exists():
        raise RI6ContractError(
            f"Prepared run already exists; remove only the ignored RI-6 runtime to rerun: {prepared_run}"
        )
    preparation = prepare_structure(
        apo_source,
        StructureSource(
            provider="rcsb",
            identifier="1JWP",
            representation="asymmetric_unit",
        ),
        PreparationConfig(chain_ids=("A",)),
        prepared_run,
        "ri6-tem1-1jwp-v1",
        source_metadata={
            "rcsb_entry": "1JWP",
            "known_mutation": "M182T",
            "role": "retrodiction_control_not_prospective_target",
        },
    )
    manifest = _build_target_blind_manifest(
        prepared_path=str(preparation.prepared_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        prepared_sha256=preparation.prepared_sha256,
        preparation_config_sha256=preparation.config_sha256,
    )
    _validate_target_blind_manifest(manifest)
    _write_json(root / "tem1-detector-input-v1.json", manifest)

    result = detect_static_pockets(
        preparation.prepared_path,
        prepared_sha256=preparation.prepared_sha256,
    )
    detector_record = adapt_biovoid_pockets(
        structure_id="1JWP",
        pockets=[pocket.to_portable_dict() for pocket in result.pockets],
        provenance={
            "detector_input_manifest_sha256": manifest["manifest_sha256"],
            "prepared_structure_sha256": preparation.prepared_sha256,
            "detector_config_sha256": result.config_sha256,
        },
    )
    detector_payload = asdict(detector_record)
    detector_payload["detector_record_sha256"] = _stable_hash(detector_payload)
    _write_json(root / "tem1-detector-output-v1.json", detector_payload)

    # Evaluator information is intentionally materialized only after detector output is sealed.
    _download("1PZO", holo_source)
    truths = []
    evaluations = []
    protocol = phase6_frozen_protocol_v1()
    for residue_id in (300, 301):
        truth = build_aligned_ground_truth_from_files(
            case_id=f"tem1:1JWP:1PZO:CBT:{residue_id}",
            structure_id="1JWP",
            prepared_apo_path=preparation.prepared_path,
            holo_path=holo_source,
            ligand=LigandSelector(
                residue_name="CBT",
                chain_id="A",
                residue_id=residue_id,
            ),
            chain_pairs=(ChainPair(apo_chain_id="A", holo_chain_id="A"),),
            provenance_label="RCSB 1PZO evaluator-only CBT coordinates",
            policy=AlignmentPolicy(ambiguous_sequence_policy="structural_fit"),
        )
        evaluation = evaluate_case(detector_record, truth.ground_truth, protocol)
        truths.append(asdict(truth))
        evaluations.append(asdict(evaluation))

    report: dict[str, Any] = {
        "schema_version": "biovoid-ri6-tem1-transfer-control-v1",
        "status": "completed_retrodiction_control",
        "scientific_scope": "historical_mutant_pair_control_not_prospective_evidence",
        "apo": {"structure_id": "1JWP", "mutation": "M182T"},
        "holo_evaluator_only": {"structure_id": "1PZO", "ligand": "CBT"},
        "detector_target_blind": True,
        "detector_record_sha256": detector_payload["detector_record_sha256"],
        "ground_truth": truths,
        "evaluations": evaluations,
        "limitations": [
            "1JWP and 1PZO are historical TEM-1 mutant structures, not prospective targets.",
            "A single retrodiction pair cannot establish scientific validity or transferability.",
            "The canonical detector remains static; no motion or NMA evidence is used here.",
        ],
    }
    report["report_sha256"] = _stable_hash(report)
    _write_json(root / "tem1-transfer-control-v1.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    report = run_control(args.output_root.resolve())
    print(f"status={report['status']}")
    print(f"report_sha256={report['report_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
