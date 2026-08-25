from __future__ import annotations


def _label(case_id: str, structure_id: str, center: list[float]) -> dict:
    return {
        "status": "completed_ground_truth",
        "ground_truth": {
            "case_id": case_id,
            "structure_id": structure_id,
            "coordinate_frame_sha256": "a" * 64,
            "alignment_sha256": "b" * 64,
            "ligand_center": center,
            "ligand_atoms": [center],
            "ligand_residues": [],
            "quality": "exact",
            "provenance": "test",
        },
    }


def _static(case_id: str, structure_id: str, centers: list[list[float]]) -> dict:
    return {
        "case_id": case_id,
        "structure_id": structure_id,
        "status": "completed",
        "final_pockets": [
            {"pocket_id": f"pocket-{index}", "center": center, "volume": 10.0}
            for index, center in enumerate(centers, start=1)
        ],
    }


def test_development_evaluation_separates_ranking_from_detector_miss() -> None:
    from scripts.evaluate_pocketminer_development import _case_evaluation
    from src.benchmark_v1 import phase6_frozen_protocol_v1

    case_id = "pocketminer-v1:TEST:case"
    ranked_late = _case_evaluation(
        _static(case_id, "TEST", [[20.0, 0.0, 0.0], [0.0, 0.0, 0.0]]),
        _label(case_id, "TEST", [0.0, 0.0, 0.0]),
        phase6_frozen_protocol_v1(),
    )
    assert ranked_late["best_joint_rank"] == 2
    assert ranked_late["joint_candidate_universe_hit"] is True
    assert ranked_late["taxonomy"] == "top5_joint_hit"
    assert ranked_late["top_k"]["1"]["joint"] is False

    missed = _case_evaluation(
        _static(case_id, "TEST", [[20.0, 0.0, 0.0]]),
        _label(case_id, "TEST", [0.0, 0.0, 0.0]),
        phase6_frozen_protocol_v1(),
    )
    assert missed["joint_candidate_universe_hit"] is False
    assert missed["taxonomy"] == "detector_miss"
