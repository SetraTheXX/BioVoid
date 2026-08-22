from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.target_family_cohort import (
    CohortContractError,
    assess_cohort_readiness,
    build_target_blind_manifest,
    validate_cohort_manifest,
    validate_target_blind_manifest,
)


def _case(
    index: int,
    *,
    split: str,
    group: str,
    cluster: str,
    apo_date: str = "2023-01-01",
    holo_date: str = "2023-06-01",
    label_source: str = "holo_ligand_contact_v1",
) -> dict[str, str]:
    return {
        "case_id": f"PF00497:CASE{index}",
        "apo_structure_id": f"A{index:03d}",
        "holo_structure_id": f"B{index:03d}",
        "family_id": "PF00497",
        "uniprot_group_id": group,
        "sequence_cluster_id": cluster,
        "split": split,
        "apo_release_date": apo_date,
        "holo_release_date": holo_date,
        "label_source": label_source,
    }


def _manifest(cases: list[dict[str, str]], *, cutoff: str = "2025-01-01") -> dict:
    return {
        "schema_version": "biovoid-target-family-cohort-v1",
        "manifest_kind": "private_target_family_cohort",
        "family_id": "PF00497",
        "split_strategy": "sequence_cluster_temporal_holdout_v1",
        "temporal_cutoff": cutoff,
        "cases": cases,
    }


def _valid_cases() -> list[dict[str, str]]:
    return [
        _case(1, split="development", group="U1", cluster="C1"),
        _case(2, split="development", group="U2", cluster="C2"),
        _case(3, split="development", group="U3", cluster="C3"),
        _case(4, split="validation", group="U4", cluster="C4"),
        _case(5, split="validation", group="U5", cluster="C5"),
        _case(
            6,
            split="test",
            group="U6",
            cluster="C6",
            apo_date="2025-02-01",
            holo_date="2025-03-01",
        ),
    ]


def test_valid_cohort_is_ready_and_redaction_is_target_blind() -> None:
    payload = _manifest(_valid_cases())

    validate_cohort_manifest(payload)
    report = assess_cohort_readiness(payload, minimum_cases=6)
    assert report["status"] == "ready_for_explicit_user_approval"
    assert report["sequence_cluster_overlap"] == {}
    assert report["uniprot_group_overlap"] == {}

    redacted = build_target_blind_manifest(payload)
    validate_target_blind_manifest(redacted)
    assert all("holo_structure_id" not in case for case in redacted["cases"])
    assert all("label_source" not in case for case in redacted["cases"])
    assert "holo" not in str(redacted).casefold()
    assert "ligand" not in str(redacted).casefold()


def test_heuristic_label_source_is_rejected() -> None:
    payload = _manifest(
        [
            _case(
                1,
                split="development",
                group="U1",
                cluster="C1",
                label_source="biovoid_bio_score",
            )
        ]
    )

    with pytest.raises(CohortContractError, match="independent label source"):
        validate_cohort_manifest(payload)


def test_sequence_cluster_overlap_is_rejected() -> None:
    cases = _valid_cases()
    cases[3]["sequence_cluster_id"] = cases[0]["sequence_cluster_id"]

    with pytest.raises(CohortContractError, match="sequence cluster overlap"):
        validate_cohort_manifest(_manifest(cases))


def test_two_case_cohort_is_explicitly_blocked_for_held_out_work() -> None:
    payload = _manifest(_valid_cases()[:2])

    report = assess_cohort_readiness(payload, minimum_cases=6)

    assert report["status"] == "blocked_insufficient_cohort"
    assert report["case_count"] == 2
    assert report["held_out_ready"] is False


def test_temporal_test_case_must_be_after_cutoff() -> None:
    cases = _valid_cases()
    cases[-1]["apo_release_date"] = "2024-12-31"

    with pytest.raises(CohortContractError, match="temporal cutoff"):
        validate_cohort_manifest(_manifest(cases))


def test_rcsb_timestamp_release_dates_are_accepted() -> None:
    cases = _valid_cases()
    for case in cases:
        case["apo_release_date"] += "T00:00:00.000+00:00"
        case["holo_release_date"] += "T00:00:00.000+00:00"

    validate_cohort_manifest(_manifest(cases))


def test_readiness_script_writes_only_report_and_redacted_manifest(tmp_path: Path) -> None:
    from scripts.check_target_family_cohort import check_target_family_cohort

    input_path = tmp_path / "private-cohort.json"
    readiness_path = tmp_path / "readiness.json"
    detector_path = tmp_path / "detector.json"
    input_path.write_text(json.dumps(_manifest(_valid_cases())), encoding="utf-8")

    report = check_target_family_cohort(
        input_path=input_path,
        readiness_output=readiness_path,
        detector_output=detector_path,
    )

    detector = json.loads(detector_path.read_text(encoding="utf-8"))
    assert report["status"] == "ready_for_explicit_user_approval"
    assert readiness_path.is_file()
    assert detector["manifest_kind"] == "target_blind_cohort"
    assert "holo" not in detector_path.read_text(encoding="utf-8").casefold()


def test_readiness_script_defaults_to_current_pfam_cohort() -> None:
    from scripts.check_target_family_cohort import (
        DEFAULT_DETECTOR_OUTPUT,
        DEFAULT_INPUT,
        DEFAULT_READINESS_OUTPUT,
    )

    assert DEFAULT_INPUT.as_posix().endswith(
        "local-private/research/target-family/cohort-pfam-v1.json"
    )
    assert DEFAULT_READINESS_OUTPUT.as_posix().endswith(
        "data/runtime/target-family/cohort-readiness-pfam-v1/"
        "target-family-cohort-readiness-pfam-v1.json"
    )
    assert DEFAULT_DETECTOR_OUTPUT.as_posix().endswith(
        "data/runtime/target-family/cohort-detector-pfam-v1/"
        "target-family-cohort-detector-pfam-v1.json"
    )
