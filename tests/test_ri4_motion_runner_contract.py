"""Contract tests for the bounded RI-4 development runner."""

from __future__ import annotations

from src.evaluator_format import DetectorEvaluationRecord, EvaluatorPocket
from scripts.run_ri4_motion_development import (
    _null_motion_record,
    _stable_hash,
    _validate_batch_size,
    _validate_timeout,
)


def _static_record() -> DetectorEvaluationRecord:
    return DetectorEvaluationRecord(
        schema_version="pocket-evaluator-input-v1",
        detector="biovoid_static",
        structure_id="1ABC",
        status="completed",
        pockets=(
            EvaluatorPocket(
                pocket_id="BV-STATIC-1",
                center=(1.0, 2.0, 3.0),
                volume=42.0,
                rank=1,
                score=None,
                raw={"pocket_id": "BV-STATIC-1", "center": [1.0, 2.0, 3.0]},
            ),
        ),
    )


def test_null_motion_control_preserves_static_geometry() -> None:
    record = _null_motion_record("1ABC", _static_record())

    assert record.detector == "biovoid_motion"
    assert record.status == "completed"
    assert len(record.pockets) == 1
    assert record.pockets[0].center == (1.0, 2.0, 3.0)
    assert record.pockets[0].volume == 42.0
    assert record.pockets[0].raw["static_relationship"] == "null_static_duplicate"
    assert "ground_truth" not in str(record)
    assert "ligand_center" not in str(record)


def test_ri4_resource_bounds_are_explicit() -> None:
    assert _validate_batch_size(1) == 1
    assert _validate_batch_size(10) == 10
    assert _validate_timeout(30) == 30
    assert _validate_timeout(3600) == 3600


def test_ri4_hash_is_order_stable() -> None:
    assert _stable_hash({"b": 2, "a": 1}) == _stable_hash({"a": 1, "b": 2})
