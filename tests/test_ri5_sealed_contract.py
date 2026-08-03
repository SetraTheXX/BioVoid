from __future__ import annotations

from scripts.check_ri5_sealed_static import _check_evaluation_integrity, _stable_hash
from scripts.run_ri5_sealed_static import _sealed_ids, _stored_ground_truth_payload


def test_stored_ground_truth_payload_unwraps_alignment_result() -> None:
    nested = {"case_id": "cryptobench:1ABC:case", "ligand_center": [0.0, 0.0, 0.0]}
    assert _stored_ground_truth_payload({"ground_truth": {"ground_truth": nested}}) == nested


def test_stored_ground_truth_payload_accepts_evaluator_ground_truth() -> None:
    payload = {"case_id": "cryptobench:1ABC:case", "ligand_center": [0.0, 0.0, 0.0]}
    assert _stored_ground_truth_payload({"ground_truth": payload}) == payload


def test_sealed_ids_rejects_cross_fold_overlap() -> None:
    sealed = [f"{index:04X}" for index in range(222)]
    try:
        _sealed_ids({"test": sealed, "train-0": [sealed[0]]})
    except RuntimeError as exc:
        assert "overlap" in str(exc)
    else:
        raise AssertionError("overlapping sealed and development IDs must fail")


def test_evaluation_integrity_requires_complete_accounting() -> None:
    records = {
        "case-1": {"status": "completed_ground_truth"},
        "case-2": {"status": "alignment_unavailable"},
    }
    payload = {
        "schema_version": "biovoid-ri5-sealed-static-evaluation-v1",
        "status": "partial",
        "detector_target_blind": True,
        "sealed_evaluation_authorized": True,
        "records": records,
        "summary": {
            "status": "partial_evaluator_coverage_not_for_claim",
            "completed_ground_truth": 1,
            "expected_cases": 2,
            "alignment_unavailable": 1,
            "scientific_superiority_claim_authorized": False,
        },
    }
    payload["report_sha256"] = _stable_hash(payload)

    try:
        _check_evaluation_integrity(payload)
    except RuntimeError as exc:
        assert "272" in str(exc)
    else:
        raise AssertionError("partial evaluator accounting must not pass with fewer than 272 rows")
