from __future__ import annotations

from src.evaluator_v3 import (
    EVALUATOR_V3_POLICY,
    build_development_eligibility_lock,
    classify_ineligibility,
    validate_development_eligibility_lock,
)


def test_evaluator_v3_is_ligand_independent_structural_fit() -> None:
    assert EVALUATOR_V3_POLICY.policy_version == "ground-truth-alignment-v3"
    assert EVALUATOR_V3_POLICY.ambiguous_sequence_policy == "structural_fit"
    assert EVALUATOR_V3_POLICY.maximum_alignment_candidates == 128
    assert EVALUATOR_V3_POLICY.maximum_alignment_combinations == 512
    assert EVALUATOR_V3_POLICY.structural_tie_rmsd_tolerance_angstrom == 0.001


def test_evaluator_v3_classifies_terminal_ineligibility() -> None:
    assert (
        classify_ineligibility(
            "GroundTruthAlignmentError: Protein alignment RMSD 12.1 A exceeds 8.0 A"
        )
        == "global_fit_rmsd_exceeds_limit"
    )
    assert (
        classify_ineligibility(
            "GroundTruthAlignmentError: Structural sequence alignment tie remains within the recovery tolerance"
        )
        == "structural_alignment_tie"
    )
    assert classify_ineligibility("unexpected") == "unclassified_evaluator_error"


def test_development_lock_accounts_for_every_case_and_hashes_content() -> None:
    recovery = {
        "schema_version": "development-recovery-test",
        "manifest_sha256": "a" * 64,
        "protocol_sha256": "b" * 64,
        "alignment_policy": {
            "policy_version": "ground-truth-alignment-v2-structural-recovery",
            "ambiguous_sequence_policy": "structural_fit",
            "maximum_alignment_candidates": 128,
            "maximum_alignment_combinations": 512,
            "minimum_matched_residues": 50,
            "minimum_sequence_identity": 0.9,
            "maximum_rmsd_angstrom": 8.0,
            "warning_rmsd_angstrom": 3.0,
            "structural_tie_rmsd_tolerance_angstrom": 0.001,
        },
        "records": {
            "case-a": {"status": "completed_ground_truth"},
            "case-b": {
                "status": "alignment_unavailable",
                "error": "GroundTruthAlignmentError: Chain 'A' has no C-alpha atoms",
            },
        },
    }
    payload = build_development_eligibility_lock(
        recovery,
        recovery_file_sha256="c" * 64,
        expected_case_count=2,
    )

    assert payload["eligible_case_count"] == 1
    assert payload["ineligible_case_count"] == 1
    assert payload["ineligible_reason_counts"] == {"missing_calpha_chain": 1}
    validate_development_eligibility_lock(payload, expected_case_count=2)
