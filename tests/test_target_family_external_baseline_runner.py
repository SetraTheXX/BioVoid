from __future__ import annotations

from pathlib import Path

import pytest


def test_runner_requires_explicit_approval_before_reading_manifest(tmp_path: Path) -> None:
    from scripts.run_target_family_external_baseline import (
        TargetFamilyBaselineError,
        run_target_family_baseline,
    )

    with pytest.raises(TargetFamilyBaselineError, match="explicit user approval"):
        run_target_family_baseline(
            baseline="fpocket",
            manifest_path=tmp_path / "missing.json",
            work_root=tmp_path / "work",
            user_approved=False,
        )


def test_baseline_report_is_target_blind_and_claim_closed() -> None:
    from scripts.run_target_family_external_baseline import (
        BASELINE_RUN_SCHEMA_VERSION,
        build_initial_report,
        validate_baseline_report,
    )

    manifest = {
        "schema_version": "biovoid-target-family-baseline-input-v1",
        "manifest_sha256": "a" * 64,
    }
    report = build_initial_report(
        baseline="fpocket",
        manifest=manifest,
        image_id="sha256:" + "b" * 64,
    )

    validate_baseline_report(
        report,
        baseline="fpocket",
        manifest=manifest,
        image_id="sha256:" + "b" * 64,
    )
    assert report["schema_version"] == BASELINE_RUN_SCHEMA_VERSION
    assert report["runner"] == "target-family-external-baseline-v1"
    assert report["target_blind"] is True
    assert report["evaluator_opened"] is False
    assert report["sealed_evaluation_authorized"] is False
    assert report["resource_limits"]["workers"] == 1
