from __future__ import annotations

import json

import pytest

from scripts.run_ri5_confirmatory_static import (
    ConfirmatoryRunError,
    _ground_truth_payload,
    _validate_completed_baseline,
)
from scripts.evaluate_ri3_static_development import _load_detector_records
from scripts.evaluate_ri5_confirmatory_comparison import _metric_at_rank
from src.confirmatory_holdout import (
    ConfirmatoryHoldoutError,
    authorize_confirmatory_holdout,
    build_confirmatory_locks,
    validate_detector_source_lock,
)
from src.evaluator_v3 import stable_hash


def _record(*, family: str, holo: str = "2XYZ") -> dict[str, object]:
    return {
        "uniprot_id": family,
        "holo_pdb_id": holo,
        "holo_chain": "A",
        "apo_chain": "A",
        "ligand": "LIG",
        "ligand_index": "201",
        "ligand_chain": "A",
        "apo_pocket_selection": ["A_10", "A_11"],
        "holo_pocket_selection": ["A_10", "A_11"],
        "pRMSD": 3.0,
        "is_main_holo_structure": True,
    }


def test_confirmatory_source_lock_excludes_evaluator_fields() -> None:
    dataset = {"1abc": [_record(family="P00001")]}
    folds = {"train-0": [], "train-1": [], "train-2": [], "train-3": ["1abc"], "test": []}
    source, evaluator = build_confirmatory_locks(
        dataset,
        folds,
        snapshot_id="snapshot-v1",
        evaluator_v3_lock_sha256="a" * 64,
        expected_structure_count=1,
        expected_case_count=1,
    )

    validate_detector_source_lock(source, expected_structure_count=1, expected_case_count=1)
    encoded_source = json.dumps(source).lower()
    assert "holo_pdb_id" not in encoded_source
    assert '"ligand"' not in encoded_source
    assert "apo_pocket_selection" not in encoded_source
    assert evaluator["case_count"] == 1


def test_confirmatory_lock_rejects_family_overlap() -> None:
    dataset = {
        "1abc": [_record(family="P00001")],
        "2abc": [_record(family="P00001", holo="3XYZ")],
    }
    folds = {"train-0": ["2abc"], "train-1": [], "train-2": [], "train-3": ["1abc"], "test": []}
    with pytest.raises(ConfirmatoryHoldoutError, match="family overlap"):
        build_confirmatory_locks(
            dataset,
            folds,
            snapshot_id="snapshot-v1",
            evaluator_v3_lock_sha256="a" * 64,
            expected_structure_count=1,
            expected_case_count=1,
        )


def test_confirmatory_ledger_opens_once(tmp_path) -> None:
    path = tmp_path / "ledger.json"
    payload = authorize_confirmatory_holdout(
        path,
        source_lock_sha256="a" * 64,
        evaluator_lock_sha256="b" * 64,
        evaluator_v3_lock_sha256="c" * 64,
        protocol_sha256="d" * 64,
        explicit_user_authorization=True,
    )
    assert payload["opened"] is True
    with pytest.raises(ConfirmatoryHoldoutError, match="already been opened"):
        authorize_confirmatory_holdout(
            path,
            source_lock_sha256="a" * 64,
            evaluator_lock_sha256="b" * 64,
            evaluator_v3_lock_sha256="c" * 64,
            protocol_sha256="d" * 64,
            explicit_user_authorization=True,
        )


def test_evaluator_gate_requires_complete_blind_baseline(tmp_path) -> None:
    path = tmp_path / "fpocket.json"
    report = {
        "schema_version": "biovoid-ri5-confirmatory-external-baseline-v1",
        "status": "complete",
        "tool": "fpocket",
        "manifest_sha256": "a" * 64,
        "target_blind": True,
        "evaluator_opened": False,
        "records": {f"S{index:03d}": {} for index in range(222)},
    }
    report["report_sha256"] = stable_hash(report)
    path.write_text(json.dumps(report), encoding="utf-8")

    loaded = _validate_completed_baseline(path, tool="fpocket", manifest_sha256="a" * 64)
    assert len(loaded["records"]) == 222

    report["evaluator_opened"] = True
    report["report_sha256"] = stable_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ConfirmatoryRunError, match="crossed evaluator boundary"):
        _validate_completed_baseline(path, tool="fpocket", manifest_sha256="a" * 64)


def test_ground_truth_payload_unwraps_alignment_result() -> None:
    canonical = {"case_id": "case-a", "structure_id": "1ABC"}
    assert _ground_truth_payload({"ground_truth": {**canonical}}) == canonical
    assert (
        _ground_truth_payload(
            {"ground_truth": {"ground_truth": canonical, "fit_rmsd_angstrom": 1.2}}
        )
        == canonical
    )


def test_detector_loader_accepts_confirmatory_cohort_size() -> None:
    run = {
        "status": "complete",
        "records": {
            "1ABC": {
                "detector_record": {
                    "schema_version": "detector-v1",
                    "detector": "biovoid_static",
                    "status": "completed",
                    "pockets": [],
                    "provenance": {},
                }
            }
        },
    }
    assert _load_detector_records(run, expected_count=1)["1ABC"].detector == "biovoid_static"


def test_comparison_reads_numeric_or_json_string_metric_keys() -> None:
    assert _metric_at_rank({"top_k_dcc_recall": {3: 0.4}}, "top_k_dcc_recall", 3) == 0.4
    assert _metric_at_rank({"top_k_dcc_recall": {"3": 0.5}}, "top_k_dcc_recall", 3) == 0.5
