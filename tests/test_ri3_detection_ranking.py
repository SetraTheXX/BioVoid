from __future__ import annotations

from scripts.diagnose_ri3_detection_ranking import diagnose_artifacts


def _static_run() -> dict:
    pockets = [
        {"pocket_id": "BV-1", "rank": 1, "center": [0.0, 0.0, 0.0], "volume": 300.0},
        {"pocket_id": "BV-2", "rank": 2, "center": [1.0, 0.0, 0.0], "volume": 200.0},
        {"pocket_id": "BV-3", "rank": 3, "center": [2.0, 0.0, 0.0], "volume": 100.0},
    ]
    return {
        "records": {
            "TEST": {
                "structure_id": "TEST",
                "status": "completed",
                "candidate_count": 10,
                "pocket_count": 3,
                "detector_record": {"status": "completed", "pockets": pockets},
            }
        }
    }


def test_diagnostic_separates_final_list_and_metric_disagreement() -> None:
    evaluation = {
        "records": {
            "case:test": {
                "case_id": "case:test",
                "structure_id": "TEST",
                "status": "completed_ground_truth",
                "case_evaluation": {
                    "status": "completed",
                    "dcc_by_rank": [10.0, 8.0, 3.0],
                    "dca_by_rank": [10.0, 9.0, 8.0],
                },
            }
        }
    }

    report = diagnose_artifacts(_static_run(), evaluation, tolerance=4.0)

    assert report["retention_audit"]["all_completed_final_pockets_stored"] is True
    assert report["retention_audit"]["raw_voronoi_candidate_list_available"] is False
    assert report["summary"]["eligible_aligned_rows"] == 1
    assert report["summary"]["final_pocket_list_ceiling"]["dcc_any"] == {
        "hits": 1,
        "total": 1,
        "rate": 1.0,
    }
    assert report["summary"]["final_pocket_list_ceiling"]["dca_any"]["hits"] == 0
    assert report["summary"]["decision_signal"]["signal"] == "ranking_dominant_descriptive"
    assert report["summary"]["canonical_ranking_recall"]["dcc"]["3"]["hits"] == 1
    assert report["summary"]["canonical_ranking_recall"]["dca"]["3"]["hits"] == 0
    assert report["case_rows"][0]["taxonomy"] == "B_metric_disagreement"
    assert report["case_rows"][0]["best_dcc_rank"] == 3
    assert report["case_rows"][0]["best_dca_rank"] is None
