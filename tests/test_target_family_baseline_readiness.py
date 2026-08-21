from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _manifest() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "biovoid-target-family-static-pilot-v1",
        "manifest_kind": "target_blind_static_pilot",
        "materialization_status": "metadata_only",
        "family_id": "PF00497",
        "selection_policy": {
            "one_case_per_uniprot_group": True,
            "metadata_only_selection": True,
            "quality_filter_version": "test-v1",
        },
        "constraints": {
            "case_count": 2,
            "max_case_count": 10,
            "batch_size": 2,
            "analysis_workers": 1,
            "include_motion": False,
            "safe_profile": "safe-16gb",
        },
        "boundary": "apo_structure_only_v1",
        "cases": [
            {
                "case_id": "PF00497:6MLD:test6",
                "structure_id": "6MLD",
                "family_id": "PF00497",
                "split": "development",
            },
            {
                "case_id": "PF00497:4P0I:test4",
                "structure_id": "4P0I",
                "family_id": "PF00497",
                "split": "development",
            },
        ],
        "manifest_sha256": None,
    }
    encoded = json.dumps(
        {key: value for key, value in payload.items() if key != "manifest_sha256"},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    payload["manifest_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return payload


def test_build_baseline_manifest_uses_recovery_input_without_evaluator_fields(
    tmp_path: Path,
) -> None:
    from scripts.check_target_family_baseline_readiness import (
        build_baseline_input_manifest,
        validate_baseline_input_manifest,
    )

    static_root = tmp_path / "data" / "runtime" / "target-family" / "static-pilot-v1"
    case6 = static_root / "cases" / "6MLD" / "preparation" / "prepared_detector.pdb"
    case4 = static_root / "cases" / "4P0I" / "preparation" / "prepared_detector.pdb"
    case6.parent.mkdir(parents=True)
    case4.parent.mkdir(parents=True)
    case6.write_text("ATOM 6MLD\n", encoding="ascii")
    case4.write_text("ATOM 4P0I\n", encoding="ascii")
    sha6 = hashlib.sha256(case6.read_bytes()).hexdigest()
    sha4 = hashlib.sha256(case4.read_bytes()).hexdigest()

    static_run = {
        "schema_version": "biovoid-target-family-static-pilot-run-v1",
        "manifest_sha256": _manifest()["manifest_sha256"],
        "run_sha256": "primary-hash",
        "cases": {
            "PF00497:6MLD:test6": {
                "status": "completed",
                "structure_id": "6MLD",
                "prepared_path": "data/runtime/target-family/static-pilot-v1/cases/6MLD/"
                "preparation/prepared_detector.pdb",
                "prepared_structure_sha256": sha6,
            },
            "PF00497:4P0I:test4": {
                "status": "resource_blocked",
                "structure_id": "4P0I",
            },
        },
    }
    recovery_run = {
        "schema_version": "biovoid-target-family-static-recovery-v1",
        "manifest_sha256": _manifest()["manifest_sha256"],
        "primary_run_sha256": "primary-hash",
        "structure_id": "4P0I",
        "status": "completed_secondary_resource_recovery",
        "result": {
            "status": "completed",
            "prepared_structure_sha256": sha4,
        },
    }

    payload = build_baseline_input_manifest(
        _manifest(),
        static_run,
        recovery_run,
        repo_root=tmp_path,
        prepared_root=static_root,
    )

    validate_baseline_input_manifest(payload)
    assert [item["structure_id"] for item in payload["structures"]] == ["6MLD", "4P0I"]
    assert payload["boundary"] == "prepared_apo_only_v1"
    assert payload["detector_boundary"]["target_annotations_present"] is False
    assert payload["structures"][1]["prepared_path"].endswith(
        "4P0I/preparation/prepared_detector.pdb"
    )
    assert "ligand" not in str(payload).casefold()


def test_validate_baseline_manifest_rejects_evaluator_field() -> None:
    from scripts.check_target_family_baseline_readiness import (
        validate_baseline_input_manifest,
    )

    payload = {
        "schema_version": "biovoid-target-family-baseline-input-v1",
        "manifest_kind": "target_blind_external_baseline",
        "status": "ready",
        "boundary": "prepared_apo_only_v1",
        "detector_boundary": {"target_blind": True, "target_annotations_present": False},
        "constraints": {
            "case_count": 1,
            "max_case_count": 10,
            "analysis_workers": 1,
            "motion_enabled": False,
        },
        "structures": [{"structure_id": "6MLD", "prepared_path": "ligand.pdb"}],
        "manifest_sha256": "not-computed",
    }

    with pytest.raises(ValueError, match="forbidden evaluator token"):
        validate_baseline_input_manifest(payload)


def test_docker_probe_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.check_target_family_baseline_readiness import _docker_probe

    calls: list[list[str]] = []

    class Result:
        returncode = 1
        stdout = ""
        stderr = "daemon unavailable"

    monkeypatch.setattr(
        "scripts.check_target_family_baseline_readiness.shutil.which", lambda _: "docker"
    )
    monkeypatch.setattr(
        "scripts.check_target_family_baseline_readiness.subprocess.run",
        lambda command, **_: calls.append(command) or Result(),
    )

    report = _docker_probe({"fpocket": {"image": "biovoid-fpocket-ri3:test"}})

    assert report["daemon_status"] == "daemon_unavailable"
    assert report["side_effects"] == {"pull": False, "build": False, "run": False}
    assert all(command[1:2] != ["pull"] for command in calls)
    assert all(command[1:2] != ["build"] for command in calls)
    assert all(command[1:2] != ["run"] for command in calls)
