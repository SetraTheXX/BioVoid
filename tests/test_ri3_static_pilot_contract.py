from __future__ import annotations

import pytest

from scripts.run_ri3_static_pilot import (
    MAX_PILOT_STRUCTURES,
    PilotRunError,
    build_pilot_manifest,
    build_pilot_run_skeleton,
    _final_pilot_status,
    validate_pilot_manifest,
    validate_pilot_run,
)


def _ri2_manifest() -> dict:
    return {
        "schema_version": "biovoid-ri2-development-manifest-v1",
        "snapshot": {
            "dataset_id": "cryptobench",
            "snapshot_id": "cryptobench-osf-pz4a9-test",
        },
        "cases": [
            {
                "case_id": "cryptobench:1abc:case-a",
                "structure_id": "1ABC",
                "family_id": "P12345",
                "split": "development",
                "dataset_snapshot_id": "cryptobench-osf-pz4a9-test",
            },
            {
                "case_id": "cryptobench:2def:case-b",
                "structure_id": "2DEF",
                "family_id": "Q99999",
                "split": "development",
                "dataset_snapshot_id": "cryptobench-osf-pz4a9-test",
            },
        ],
    }


def _preparation_report() -> dict:
    def record(structure_id: str) -> dict:
        return {
            "structure_id": structure_id,
            "status": "eligible",
            "preparation": {
                "status": "eligible",
                "prepared_path": f"data/runtime/ri3/pilot10-prepared/{structure_id.lower()}/prepared_detector.pdb",
                "prepared_sha256": "a" * 64,
                "preparation_config_sha256": "b" * 64,
                "preparation_report_sha256": "c" * 64,
                "protein_atom_count": 100,
                "protein_residue_count": 10,
                "warnings": [],
            },
        }

    return {
        "schema_version": "biovoid-ri3-preparation-preflight-v1",
        "status": "pass",
        "coverage": {"selected_structures": 2, "eligible": 2, "ineligible": 0, "unavailable": 0},
        "records": [record("1ABC"), record("2DEF")],
    }


def test_pilot_manifest_is_bounded_target_blind_and_hash_valid() -> None:
    payload = build_pilot_manifest(
        ri2_manifest=_ri2_manifest(),
        preparation_report=_preparation_report(),
        max_structures=MAX_PILOT_STRUCTURES,
    )

    validate_pilot_manifest(payload)

    assert payload["structure_count"] == 2
    assert payload["case_count"] == 2
    assert payload["scope"]["max_structures"] == MAX_PILOT_STRUCTURES
    assert payload["detector_boundary"]["target_blind"] is True
    assert payload["detector_boundary"]["evaluator_fields_in_manifest"] is False


def test_pilot_manifest_rejects_more_than_safe_bound() -> None:
    with pytest.raises(PilotRunError, match="at most 10"):
        build_pilot_manifest(
            ri2_manifest=_ri2_manifest(),
            preparation_report=_preparation_report(),
            max_structures=MAX_PILOT_STRUCTURES + 1,
        )


def test_pilot_manifest_rejects_evaluator_field() -> None:
    payload = build_pilot_manifest(
        ri2_manifest=_ri2_manifest(),
        preparation_report=_preparation_report(),
        max_structures=MAX_PILOT_STRUCTURES,
    )
    payload["structures"][0]["ligand"] = "ATP"
    with pytest.raises(PilotRunError, match="forbidden"):
        validate_pilot_manifest(payload)


def test_pilot_run_skeleton_closes_evaluation_and_is_hash_valid() -> None:
    manifest = build_pilot_manifest(
        ri2_manifest=_ri2_manifest(),
        preparation_report=_preparation_report(),
        max_structures=MAX_PILOT_STRUCTURES,
    )
    payload = build_pilot_run_skeleton(manifest, git_commit="a" * 40)

    validate_pilot_run(payload, manifest)

    assert payload["execution"]["workers"] == 1
    assert payload["execution"]["nma_started"] is False
    assert payload["execution"]["sealed_evaluation_authorized"] is False
    assert payload["evaluation"]["dcc_dca_computed"] is False


def test_pilot_status_distinguishes_resource_block_from_success() -> None:
    assert (
        _final_pilot_status(
            processed=10, expected=10, counts={"completed": 10, "resource_blocked": 0, "failed": 0}
        )
        == "complete"
    )
    assert (
        _final_pilot_status(
            processed=10, expected=10, counts={"completed": 0, "resource_blocked": 10, "failed": 0}
        )
        == "complete_with_resource_blocks"
    )
    assert (
        _final_pilot_status(
            processed=10, expected=10, counts={"completed": 9, "resource_blocked": 0, "failed": 1}
        )
        == "complete_with_failures"
    )
