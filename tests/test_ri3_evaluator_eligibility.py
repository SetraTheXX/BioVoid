from __future__ import annotations

import pytest

from scripts.freeze_ri3_evaluator_eligibility import classify_residual_error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("GroundTruthAlignmentError: Chain 'AAA' has no C-alpha atoms", "missing_calpha_chain"),
        (
            "GroundTruthAlignmentError: Representative apo/holo chain unions have different lengths: 'A' vs 'B'",
            "chain_union_mismatch",
        ),
        (
            "GroundTruthAlignmentError: Exact ligand selector matched no atoms in the holo structure",
            "ligand_selector_mismatch",
        ),
        (
            "GroundTruthAlignmentError: Sequence identity 0.857 is below 0.900",
            "sequence_identity_below_threshold",
        ),
        (
            "GroundTruthAlignmentError: Sequence alignment candidate count exceeds the recovery safety limit (128)",
            "alignment_candidate_limit",
        ),
        (
            "GroundTruthAlignmentError: Structural sequence alignment tie remains within the recovery tolerance",
            "structural_alignment_tie",
        ),
        (
            "GroundTruthAlignmentError: No structurally valid sequence alignment candidate met the recovery policy",
            "no_valid_structural_mapping",
        ),
        (
            "GroundTruthAlignmentError: Protein alignment RMSD 17.409 A exceeds 8.000 A",
            "global_fit_rmsd_exceeds_limit",
        ),
    ],
)
def test_classify_known_residuals(error: str, expected: str) -> None:
    assert classify_residual_error(error) == expected


def test_unknown_residual_stops_the_freeze() -> None:
    assert classify_residual_error("ValueError: unrelated failure") == "unexpected_evaluator_error"
