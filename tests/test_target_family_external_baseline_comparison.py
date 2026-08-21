from __future__ import annotations


def test_target_family_baseline_loader_accepts_only_blind_detector_records() -> None:
    from scripts.evaluate_target_family_external_baselines import (
        _load_target_family_baseline_records,
    )

    payload = {
        "schema_version": "biovoid-target-family-external-baseline-v1",
        "tool": "fpocket",
        "target_blind": True,
        "evaluator_opened": False,
        "manifest_sha256": "a" * 64,
        "status": "complete",
        "records": {
            "6MLD": {
                "detector_status": "completed",
                "detector_record": {
                    "schema_version": "pocket-evaluator-input-v1",
                    "detector": "fpocket",
                    "structure_id": "6MLD",
                    "status": "completed",
                    "pockets": [
                        {
                            "pocket_id": "fp-1",
                            "center": [1.0, 2.0, 3.0],
                            "volume": 10.0,
                            "rank": 1,
                            "score": 0.5,
                            "raw": {},
                        }
                    ],
                    "error": None,
                    "provenance": {"target_blind": True},
                },
            }
        },
    }

    records = _load_target_family_baseline_records(payload, detector="fpocket")

    assert records["6MLD"].detector == "fpocket"
    assert records["6MLD"].pockets[0].center == (1.0, 2.0, 3.0)
