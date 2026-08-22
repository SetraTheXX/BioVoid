from __future__ import annotations

import json

import pytest

from scripts.run_target_family_static_pilot import (
    DEFAULT_FULL_OUTPUT_ROOT,
    DEFAULT_MANIFEST,
    DEFAULT_OUTPUT_ROOT,
    TargetFamilyPilotError,
    _seal_run,
    build_pilot_run_skeleton,
    enforce_disk_quota,
    DiskQuotaExceeded,
    validate_pilot_run,
)
from src.target_family_ranking import (
    CANDIDATE_RETENTION_FULL,
    CANDIDATE_RETENTION_TOP10,
    HELD_OUT_RANKING_CONTRACT,
)
from src.target_family_manifest import (
    NonPolymerComponent,
    PilotPair,
    RcsbMetadataRecord,
    build_detector_manifest,
)


def _record(
    pdb_id: str,
    *,
    components: tuple[tuple[str, str], ...] = (),
) -> RcsbMetadataRecord:
    return RcsbMetadataRecord(
        pdb_id=pdb_id,
        uniprot_ids=("P35120",),
        family_id="PF00497",
        description="solute-binding protein",
        sequence_length=265,
        resolution_angstrom=1.9,
        experimental_method="X-RAY DIFFRACTION",
        nonpolymer_components=tuple(
            NonPolymerComponent(comp_id=comp_id, name=name) for comp_id, name in components
        ),
    )


def _manifest() -> dict[str, object]:
    pair = PilotPair(
        case_id="PF00497:4P0I:test",
        family_id="PF00497",
        apo=_record("4P0I"),
        holo=_record("5OTA", components=(("OP1", "opine"),)),
    )
    return build_detector_manifest((pair,))


def test_pilot_run_skeleton_is_static_bounded_and_redacted() -> None:
    manifest = _manifest()
    payload = build_pilot_run_skeleton(manifest, max_disk_bytes=1_000_000_000)

    validate_pilot_run(payload, manifest)

    assert payload["execution"]["workers"] == 1
    assert payload["execution"]["motion_enabled"] is False
    assert payload["execution"]["candidate_retention"] == CANDIDATE_RETENTION_TOP10
    assert payload["detector"]["candidate_scope"] == "stored_top10"
    assert payload["detector"]["held_out_ranking_contract"] == HELD_OUT_RANKING_CONTRACT
    assert payload["execution"]["max_disk_bytes"] == 1_000_000_000
    serialized = json.dumps(payload, sort_keys=True).casefold()
    assert "holo" not in serialized
    assert "ligand" not in serialized
    assert "evaluator" not in serialized
    assert "ground_truth" not in serialized


def test_pilot_run_rejects_zero_disk_budget() -> None:
    with pytest.raises(ValueError, match="max_disk_bytes"):
        build_pilot_run_skeleton(_manifest(), max_disk_bytes=0)


def test_full_candidate_skeleton_is_explicit_and_separate() -> None:
    manifest = _manifest()
    payload = build_pilot_run_skeleton(
        manifest,
        max_disk_bytes=1_000_000_000,
        candidate_retention=CANDIDATE_RETENTION_FULL,
    )

    validate_pilot_run(payload, manifest)

    assert payload["execution"]["candidate_retention"] == CANDIDATE_RETENTION_FULL
    assert payload["detector"]["candidate_scope"] == "all_detected_pockets"
    assert DEFAULT_FULL_OUTPUT_ROOT.as_posix().endswith(
        "data/runtime/target-family/static-pilot-pfam-v1-full-candidates"
    )


def test_full_candidate_validation_requires_complete_case_storage() -> None:
    manifest = _manifest()
    payload = build_pilot_run_skeleton(
        manifest,
        candidate_retention=CANDIDATE_RETENTION_FULL,
    )
    case_id = manifest["cases"][0]["case_id"]
    payload["cases"][case_id] = {
        "status": "completed",
        "candidate_retention": CANDIDATE_RETENTION_FULL,
        "pocket_count": 2,
        "top_pockets": [{}, {}],
    }
    _seal_run(payload)

    with pytest.raises(TargetFamilyPilotError, match="full retention"):
        validate_pilot_run(payload, manifest)

    payload["cases"][case_id]["all_pockets"] = [{}, {}]
    _seal_run(payload)
    validate_pilot_run(payload, manifest)


def test_pilot_run_rejects_unknown_candidate_retention() -> None:
    with pytest.raises(ValueError, match="candidate_retention"):
        build_pilot_run_skeleton(_manifest(), candidate_retention="everything")


def test_disk_quota_fails_closed(tmp_path) -> None:
    (tmp_path / "payload.bin").write_bytes(b"x" * 32)

    with pytest.raises(DiskQuotaExceeded, match="disk quota"):
        enforce_disk_quota(tmp_path, max_disk_bytes=31)


def test_cli_defaults_point_to_current_pfam_cohort() -> None:
    assert DEFAULT_MANIFEST.as_posix().endswith(
        "data/runtime/target-family/cohort-detector-pfam-v1/"
        "target-family-cohort-detector-pfam-v1.json"
    )
    assert DEFAULT_OUTPUT_ROOT.as_posix().endswith(
        "data/runtime/target-family/static-pilot-pfam-v1"
    )
