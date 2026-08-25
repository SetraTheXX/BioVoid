from __future__ import annotations

import json

import pytest

from scripts.seal_ahoj_geometry_cohort import (
    AhojMetadataResolutionError,
    build_ahoj_cohort_payload,
    build_target_blind_detector_manifest,
)


def _resolution() -> dict:
    cases = []
    assignments = []
    for index, split in enumerate(
        ["development"] * 6 + ["validation"] * 2 + ["temporal"] * 2, start=1
    ):
        case_id = f"case-{index:02d}"
        cases.append(
            {
                "case_id": case_id,
                "apo_structure_id": f"A{index:03d}",
                "holo_structure_id": f"H{index:03d}",
                "uniprot_id": f"U{index:02d}",
                "sequence_cluster_id": f"C{index:02d}",
                "apo_release_date": "2017-01-01"
                if split == "development"
                else ("2019-01-01" if split == "validation" else "2022-01-01"),
                "holo_release_date": "2022-01-02",
                "ligand_code": "LIG",
                "apo_entity": {"chain_ids": ["A", "B"]},
                "holo_entity": {"chain_ids": ["A", "B"]},
                "holo_ligand_chain_ids": ["A"],
            }
        )
        assignments.append({"case_id": case_id, "split": split})
    return {
        "decision": "PASS",
        "label_policy": {"accepted": True},
        "cases": cases,
        "allocation": {
            "assignments": assignments,
            "development_cutoff": "2018-01-01",
            "temporal_cutoff": "2021-01-01",
        },
    }


def test_sealed_cohort_keeps_full_apo_chains_private() -> None:
    cohort = build_ahoj_cohort_payload(_resolution())
    manifest = build_target_blind_detector_manifest(cohort)

    assert cohort["schema_version"] == "biovoid-ahoj-geometry-cohort-v1"
    assert len(cohort["cases"]) == 10
    assert cohort["cases"][0]["apo_chain_ids"] == ["A", "B"]
    assert manifest["boundary"] == "apo_full_structure_only_v1"
    assert manifest["constraints"]["full_heavy_atom_structure"] is True
    assert {case["split"] for case in manifest["cases"]} == {
        "development",
        "validation",
        "test",
    }
    serialized = json.dumps(manifest, ensure_ascii=True).casefold()
    for forbidden in ("holo", "ligand", "evaluator", "ground_truth", "bio_score"):
        assert forbidden not in serialized


def test_cohort_sealing_requires_metadata_pass() -> None:
    resolution = _resolution()
    resolution["decision"] = "DIAGNOSTIC_ONLY"

    with pytest.raises(AhojMetadataResolutionError, match="must be PASS"):
        build_ahoj_cohort_payload(resolution)
