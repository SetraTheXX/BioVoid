from __future__ import annotations


def _label(case_id: str, structure_id: str) -> dict:
    return {
        "status": "completed_ground_truth",
        "ground_truth": {
            "case_id": case_id,
            "structure_id": structure_id,
            "coordinate_frame_sha256": "a" * 64,
            "alignment_sha256": "b" * 64,
            "ligand_center": [0.0, 0.0, 0.0],
            "ligand_atoms": [[0.0, 0.0, 0.0]],
            "ligand_residues": [],
            "quality": "exact",
            "provenance": "test",
        },
    }


def test_heldout_evaluation_uses_locked_a_without_retuning() -> None:
    from scripts.evaluate_pocketminer_heldout import _case_evaluation
    from src.benchmark_v1 import phase6_frozen_protocol_v1

    case_id = "pocketminer-v1:TEST:heldout"
    result = _case_evaluation(
        {
            "case_id": case_id,
            "structure_id": "TEST",
            "split": "test",
            "status": "completed",
            "final_pockets": [
                {"pocket_id": "far", "center": [8.0, 0.0, 0.0], "volume": 20.0, "enclosure": 0.2},
                {"pocket_id": "near", "center": [0.0, 0.0, 0.0], "volume": 10.0, "enclosure": 0.8},
            ],
        },
        _label(case_id, "TEST"),
        phase6_frozen_protocol_v1(),
    )

    assert result["locked_policy_id"] == "A-canonical-volume-v1"
    assert result["case_evaluation"]["best_joint_rank"] == 2
    assert result["case_evaluation"]["top_k_joint_hits"]["1"] is False
    assert result["case_evaluation"]["top_k_joint_hits"]["5"] is True
