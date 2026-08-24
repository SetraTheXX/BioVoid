from __future__ import annotations

import json

import pytest


def test_metadata_session_retries_transient_rcsb_failures_only() -> None:
    from scripts.build_target_family_manifest import _metadata_session

    session = _metadata_session("BioVoid/test")
    try:
        retry = session.adapters["https://"].max_retries
        assert retry.total == 3
        assert retry.backoff_factor == 0.5
        assert set(retry.status_forcelist) == {429, 500, 502, 503, 504}
        assert set(retry.allowed_methods or ()) == {"GET", "POST"}
        assert retry.respect_retry_after_header is True
        assert session.headers["User-Agent"] == "BioVoid/test"
    finally:
        session.close()


from src.target_family_manifest import (
    NonPolymerComponent,
    RcsbMetadataRecord,
    build_detector_manifest,
    validate_detector_manifest,
    select_pilot_pairs,
)
from scripts.build_target_family_manifest import build_sequence_search_request


def _record(
    pdb_id: str,
    uniprot_id: str,
    *,
    resolution: float = 2.0,
    components: tuple[tuple[str, str], ...] = (),
    sequence_length: int = 265,
) -> RcsbMetadataRecord:
    return RcsbMetadataRecord(
        pdb_id=pdb_id,
        uniprot_ids=(uniprot_id,),
        family_id="SBP_bac_3",
        description="solute-binding protein",
        sequence_length=sequence_length,
        resolution_angstrom=resolution,
        experimental_method="X-RAY DIFFRACTION",
        nonpolymer_components=tuple(
            NonPolymerComponent(comp_id=comp_id, name=name) for comp_id, name in components
        ),
    )


def test_selects_deterministic_apo_holo_pairs_and_redacts_detector_manifest() -> None:
    records = (
        _record("4P0I", "P35120", components=(("EDO", "1,2-ETHANEDIOL"),)),
        _record("5OTA", "P35120", components=(("AQQ", "octopinic acid"),)),
        _record("2LAO", "P02911"),
        _record("1LAF", "P02911", components=(("ARG", "arginine"),)),
    )

    pairs = select_pilot_pairs(records, max_cases=10)
    manifest = build_detector_manifest(pairs)

    assert [pair.apo.pdb_id for pair in pairs] == ["2LAO", "4P0I"]
    assert [pair.holo.pdb_id for pair in pairs] == ["1LAF", "5OTA"]
    assert manifest["constraints"]["case_count"] == 2
    assert manifest["constraints"]["analysis_workers"] == 1
    assert manifest["constraints"]["include_motion"] is False
    serialized = json.dumps(manifest, sort_keys=True).casefold()
    assert "holo" not in serialized
    assert "ligand" not in serialized
    assert "5ota" not in serialized
    assert manifest["manifest_sha256"] == build_detector_manifest(pairs)["manifest_sha256"]


def test_selection_rejects_fragments_and_low_quality_records() -> None:
    records = (
        _record("1BAD", "P35120", sequence_length=126),
        _record("1LOW", "P35120", resolution=3.2),
        _record("1GOD", "P35120"),
        _record("1HOL", "P35120", components=(("AQQ", "octopinic acid"),)),
    )

    pairs = select_pilot_pairs(records, max_cases=10)

    assert len(pairs) == 1
    assert pairs[0].apo.pdb_id == "1GOD"
    assert pairs[0].holo.pdb_id == "1HOL"


def test_selection_requires_positive_case_limit() -> None:
    with pytest.raises(ValueError, match="max_cases"):
        select_pilot_pairs((), max_cases=0)


def test_validator_accepts_redacted_leakage_audited_cohort_manifest() -> None:
    payload = {
        "schema_version": "biovoid-target-family-cohort-detector-v1",
        "manifest_kind": "target_blind_cohort",
        "materialization_status": "metadata_only",
        "family_id": "PF00497",
        "split_strategy": "sequence_cluster_temporal_holdout_v1",
        "temporal_cutoff": "2018-01-01",
        "constraints": {
            "case_count": 3,
            "max_case_count": 10,
            "analysis_workers": 1,
            "include_motion": False,
            "safe_profile": "safe-16gb",
        },
        "boundary": "apo_structure_only_v1",
        "cases": [
            {
                "case_id": "PF00497:1AAA:dev",
                "structure_id": "1AAA",
                "family_id": "PF00497",
                "split": "development",
            },
            {
                "case_id": "PF00497:2BBB:val",
                "structure_id": "2BBB",
                "family_id": "PF00497",
                "split": "validation",
            },
            {
                "case_id": "PF00497:3CCC:test",
                "structure_id": "3CCC",
                "family_id": "PF00497",
                "split": "test",
            },
        ],
        "manifest_sha256": None,
    }
    encoded = json.dumps(
        {key: value for key, value in payload.items() if key != "manifest_sha256"},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    import hashlib

    payload["manifest_sha256"] = hashlib.sha256(encoded).hexdigest()

    validate_detector_manifest(payload)


def test_sequence_search_request_is_bounded_and_metadata_only() -> None:
    request = build_sequence_search_request(" AC D\nEF ", max_entries=10)

    assert request["return_type"] == "entry"
    assert request["request_options"]["paginate"] == {"start": 0, "rows": 10}
    assert request["query"]["parameters"]["value"] == "ACDEF"
    serialized = json.dumps(request, sort_keys=True).casefold()
    assert "files.rcsb.org" not in serialized
    assert "coordinate" not in serialized


def test_sequence_search_request_rejects_unbounded_result_limit() -> None:
    with pytest.raises(ValueError, match="max_entries"):
        build_sequence_search_request("ACDEF", max_entries=11_000)
