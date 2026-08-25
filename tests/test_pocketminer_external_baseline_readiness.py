from __future__ import annotations

import hashlib

import pytest


def _fixture_payload(tmp_path):
    prepared = tmp_path / "prepared_detector.pdb"
    prepared.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n", encoding="utf-8"
    )
    digest = hashlib.sha256(prepared.read_bytes()).hexdigest()
    case_id = "pocketminer-v1:TEST:heldout"
    static = {
        "status": "completed",
        "retention": "full_final_pocket_list",
        "boundary": {
            "target_blind": True,
            "evaluator_started": False,
            "external_baseline_started": False,
            "holo_coordinates_opened": False,
            "ml_training_started": False,
        },
        "records": [
            {
                "case_id": case_id,
                "structure_id": "TEST",
                "status": "completed",
                "detector": {"prepared_structure_sha256": digest},
            }
        ],
    }
    preflight = {
        "status": "ready_for_static_detector_gate",
        "cases": [
            {
                "case_id": case_id,
                "structure_id": "TEST",
                "status": "prepared",
                "prepared_path": str(prepared),
                "prepared_sha256": digest,
                "split": "test",
            }
        ],
    }
    return static, preflight


def test_external_baseline_manifest_binds_static_and_preflight(monkeypatch, tmp_path) -> None:
    import scripts.check_pocketminer_external_baseline_readiness as readiness

    static, preflight = _fixture_payload(tmp_path)
    monkeypatch.setattr(readiness, "REPO_ROOT", tmp_path)

    manifest = readiness._build_manifest(static, preflight)

    assert manifest["boundary"] == "prepared_apo_only_v1"
    assert manifest["structures"][0]["split"] == "test"
    assert (
        manifest["structures"][0]["prepared_structure_sha256"]
        == preflight["cases"][0]["prepared_sha256"]
    )


def test_external_baseline_manifest_rejects_hash_drift(monkeypatch, tmp_path) -> None:
    import scripts.check_pocketminer_external_baseline_readiness as readiness

    static, preflight = _fixture_payload(tmp_path)
    preflight["cases"][0]["prepared_sha256"] = "0" * 64
    monkeypatch.setattr(readiness, "REPO_ROOT", tmp_path)

    with pytest.raises(readiness.PocketMinerBaselineReadinessError, match="hash binding"):
        readiness._build_manifest(static, preflight)


def test_external_baseline_probe_fails_closed_when_docker_is_missing(monkeypatch) -> None:
    import scripts.check_pocketminer_external_baseline_readiness as readiness

    def missing(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(readiness.subprocess, "run", missing)

    result = readiness._probe_docker("example:image")

    assert result["daemon"] == "unavailable"
    assert result["image"] == "example:image"
