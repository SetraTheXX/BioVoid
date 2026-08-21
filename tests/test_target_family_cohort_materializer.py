from __future__ import annotations

import json
from typing import Any

import pytest

from src.target_family_cohort import build_target_blind_manifest, validate_cohort_manifest


def _case_id() -> str:
    return "PF00497:A001:case"


def _inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    case_id = _case_id()
    pairs = {
        "schema_version": "biovoid-target-family-pilot-pairs-v1",
        "pairs": [
            {
                "case_id": case_id,
                "family_id": "PF00497",
                "apo_pdb_id": "A001",
                "holo_pdb_id": "B001",
                "uniprot_group": "U1",
                "holo_components": [{"comp_id": "LIG", "name": "test ligand"}],
            }
        ],
    }
    inventory = {
        "schema_version": "biovoid-target-family-metadata-inventory-v1",
        "source": {"family_id": "PF00497"},
        "records": [
            {
                "pdb_id": "A001",
                "family_id": "PF00497",
                "uniprot_ids": ["U1"],
                "release_date": "2020-01-01",
                "sequence_length": 200,
            },
            {
                "pdb_id": "B001",
                "family_id": "PF00497",
                "uniprot_ids": ["U1"],
                "release_date": "2020-02-01",
                "sequence_length": 200,
            },
        ],
    }
    sequence_clusters = {
        "schema_version": "biovoid-target-family-sequence-clusters-v1",
        "family_id": "PF00497",
        "status": "sequence_materialized_review_required",
        "records": [
            {
                "pdb_id": "A001",
                "family_id": "PF00497",
                "uniprot_ids": ["U1"],
                "sequence_cluster_id": "scv1-a",
            },
            {
                "pdb_id": "B001",
                "family_id": "PF00497",
                "uniprot_ids": ["U1"],
                "sequence_cluster_id": "scv1-a",
            },
        ],
    }
    evaluator = {
        "records": {
            case_id: {
                "case_id": case_id,
                "structure_id": "A001",
                "status": "completed_ground_truth",
                "ligand_selector": {
                    "chain_id": "A",
                    "residue_id": 301,
                    "residue_name": "LIG",
                    "insertion_code": "",
                },
                "alignment": {
                    "status": "ACCEPTED",
                    "sequence_identity": 1.0,
                    "fit_rmsd_angstrom": 1.2,
                    "alignment_sha256": "b" * 64,
                    "warnings": [],
                },
                "case_evaluation": {"status": "completed", "score_used": False},
                "ground_truth": {
                    "case_id": case_id,
                    "structure_id": "A001",
                    "quality": "exact",
                    "ground_truth_sha256": "a" * 64,
                    "alignment_sha256": "b" * 64,
                    "coordinate_frame_sha256": "c" * 64,
                    "ligand_center": [1.0, 2.0, 3.0],
                    "ligand_atoms": [[1.0, 2.0, 3.0], [2.0, 3.0, 4.0]],
                    "ligand_residues": [],
                },
            }
        }
    }
    return pairs, inventory, sequence_clusters, evaluator


def test_materializer_builds_private_independent_label_cohort() -> None:
    from scripts.materialize_target_family_cohort import materialize_private_cohort

    pairs, inventory, sequence_clusters, evaluator = _inputs()
    cohort = materialize_private_cohort(
        pairs,
        inventory,
        sequence_clusters,
        evaluator,
        temporal_cutoff="2021-01-01",
    )

    validate_cohort_manifest(cohort)
    case = cohort["cases"][0]
    assert case["label_source"] == "holo_ligand_contact_v1"
    assert case["sequence_cluster_id"] == "scv1-a"
    assert case["split"] == "development"
    assert case["contact_label"]["ground_truth_sha256"] == "a" * 64
    assert case["contact_label"]["ligand_center"] == [1.0, 2.0, 3.0]
    assert cohort["contact_labels"] == "materialized_review_required"
    assert cohort["claims_authorized"] is False

    redacted = build_target_blind_manifest(cohort)
    serialized = json.dumps(redacted).casefold()
    assert "holo" not in serialized
    assert "ligand" not in serialized
    assert "ground_truth" not in serialized
    assert "contact_label" not in serialized


def test_materializer_rejects_heuristic_or_incomplete_evaluator_record() -> None:
    from scripts.materialize_target_family_cohort import (
        TargetFamilyCohortMaterializationError,
        materialize_private_cohort,
    )

    pairs, inventory, sequence_clusters, evaluator = _inputs()
    evaluator["records"][_case_id()]["case_evaluation"]["score_used"] = True

    with pytest.raises(TargetFamilyCohortMaterializationError, match="score"):
        materialize_private_cohort(
            pairs, inventory, sequence_clusters, evaluator, temporal_cutoff="2021-01-01"
        )


def test_materializer_rejects_missing_sequence_cluster() -> None:
    from scripts.materialize_target_family_cohort import (
        TargetFamilyCohortMaterializationError,
        materialize_private_cohort,
    )

    pairs, inventory, sequence_clusters, evaluator = _inputs()
    sequence_clusters["records"][0].pop("sequence_cluster_id")

    with pytest.raises(TargetFamilyCohortMaterializationError, match="sequence_cluster"):
        materialize_private_cohort(
            pairs, inventory, sequence_clusters, evaluator, temporal_cutoff="2021-01-01"
        )


def test_materializer_reads_ground_truth_digest_from_legacy_provenance() -> None:
    from scripts.materialize_target_family_cohort import materialize_private_cohort

    pairs, inventory, sequence_clusters, evaluator = _inputs()
    ground_truth = evaluator["records"][_case_id()]["ground_truth"]
    ground_truth.pop("ground_truth_sha256")
    ground_truth["provenance"] = json.dumps({"ground_truth_sha256": "a" * 64})

    cohort = materialize_private_cohort(
        pairs, inventory, sequence_clusters, evaluator, temporal_cutoff="2021-01-01"
    )

    assert cohort["cases"][0]["contact_label"]["ground_truth_sha256"] == "a" * 64
