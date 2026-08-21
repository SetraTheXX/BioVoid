from __future__ import annotations

import json

import pytest

from scripts.run_target_family_static_pilot import (
    DEFAULT_MANIFEST,
    DEFAULT_OUTPUT_ROOT,
    build_pilot_run_skeleton,
    enforce_disk_quota,
    DiskQuotaExceeded,
    validate_pilot_run,
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
    assert payload["execution"]["max_disk_bytes"] == 1_000_000_000
    serialized = json.dumps(payload, sort_keys=True).casefold()
    assert "holo" not in serialized
    assert "ligand" not in serialized
    assert "evaluator" not in serialized
    assert "ground_truth" not in serialized


def test_pilot_run_rejects_zero_disk_budget() -> None:
    with pytest.raises(ValueError, match="max_disk_bytes"):
        build_pilot_run_skeleton(_manifest(), max_disk_bytes=0)


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
