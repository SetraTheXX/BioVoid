from __future__ import annotations


def test_external_record_adapts_normalized_p2rank_payload() -> None:
    from scripts.evaluate_pocketminer_external_baselines import _external_record

    report = {
        "records": {
            "TEST": {
                "detector_status": "completed",
                "detector_record": {
                    "status": "completed",
                    "detector": "p2rank",
                    "structure_id": "TEST",
                    "pockets": [
                        {
                            "center": [1.0, 2.0, 3.0],
                            "pocket_id": "p2rank-1",
                            "rank": 1,
                            "score": 4.2,
                            "volume": None,
                            "raw": {"center_x": 1.0, "center_y": 2.0, "center_z": 3.0},
                        }
                    ],
                    "provenance": {"target_blind": True},
                },
            }
        }
    }

    record = _external_record(report, "p2rank", "TEST")

    assert record.detector == "p2rank"
    assert record.structure_id == "TEST"
    assert record.pockets[0].center == (1.0, 2.0, 3.0)
    assert record.pockets[0].rank == 1


def test_external_summary_keeps_joint_and_metric_recall_separate() -> None:
    from scripts.evaluate_pocketminer_external_baselines import _summary

    records = [
        {
            "split": "validation",
            "case_evaluation": {
                "top_k_dcc_hits": {"1": True, "3": True, "5": True, "10": True},
                "top_k_dca_hits": {"1": True, "3": True, "5": True, "10": True},
                "top_k_joint_hits": {"1": True, "3": True, "5": True, "10": True},
                "best_dcc_rank": 1,
                "best_dca_rank": 1,
                "best_joint_rank": 1,
            },
        },
        {
            "split": "test",
            "case_evaluation": {
                "top_k_dcc_hits": {"1": False, "3": False, "5": False, "10": False},
                "top_k_dca_hits": {"1": True, "3": True, "5": True, "10": True},
                "top_k_joint_hits": {"1": False, "3": False, "5": False, "10": False},
                "best_dcc_rank": None,
                "best_dca_rank": 1,
                "best_joint_rank": None,
            },
        },
    ]

    summary = _summary(records)

    assert summary["top_k_dcc_recall"]["5"] == 0.5
    assert summary["top_k_dca_recall"]["5"] == 1.0
    assert summary["top_k_joint_recall"]["5"] == 0.5
    assert summary["candidate_universe_joint_recall"] == 0.5
