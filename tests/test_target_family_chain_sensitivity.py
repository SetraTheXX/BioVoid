from __future__ import annotations

import json

import pytest

from scripts.run_target_family_chain_sensitivity import (
    ChainSensitivityError,
    build_sensitivity_run_skeleton,
    validate_sensitivity_run,
)
from src.target_family_manifest import (
    NonPolymerComponent,
    PilotPair,
    RcsbMetadataRecord,
    build_detector_manifest,
)


def _record(pdb_id: str, *, ligand: bool = False) -> RcsbMetadataRecord:
    return RcsbMetadataRecord(
        pdb_id=pdb_id,
        uniprot_ids=("P35120",),
        family_id="PF00497",
        description="bounded sensitivity test",
        sequence_length=265,
        resolution_angstrom=1.9,
        experimental_method="X-RAY DIFFRACTION",
        nonpolymer_components=(NonPolymerComponent(comp_id="OP1", name="test ligand"),)
        if ligand
        else (),
    )


def _manifest() -> dict[str, object]:
    return build_detector_manifest(
        (
            PilotPair(
                case_id="PF00497:4P0I:test",
                family_id="PF00497",
                apo=_record("4P0I"),
                holo=_record("5OTA", ligand=True),
            ),
        )
    )


def test_sensitivity_skeleton_is_secondary_and_target_blind() -> None:
    manifest = _manifest()
    payload = build_sensitivity_run_skeleton(manifest, max_disk_bytes=1_000_000_000)

    validate_sensitivity_run(payload, manifest)

    assert payload["target_blind"] is True
    assert payload["canonical_static_result"] is False
    assert payload["execution"]["workers"] == 1
    assert payload["execution"]["motion_enabled"] is False
    assert payload["execution"]["nma_started"] is False
    assert payload["execution"]["candidate_retention"] == "full"
    serialized = json.dumps(payload, sort_keys=True).casefold()
    assert "holo" not in serialized
    assert "ligand" not in serialized
    assert "evaluator" not in serialized
    assert "ground_truth" not in serialized


def test_sensitivity_requires_its_secondary_profile() -> None:
    manifest = _manifest()
    payload = build_sensitivity_run_skeleton(manifest)
    payload["canonical_static_result"] = True

    with pytest.raises(ChainSensitivityError, match="cannot be canonical"):
        validate_sensitivity_run(payload, manifest)


def test_sensitivity_rejects_forbidden_output_token() -> None:
    manifest = _manifest()
    payload = build_sensitivity_run_skeleton(manifest)
    payload["chain_id"] = "holo"

    with pytest.raises(ChainSensitivityError, match="forbidden token"):
        validate_sensitivity_run(payload, manifest)
