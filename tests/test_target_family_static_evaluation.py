from __future__ import annotations

import json

import pytest

from scripts.evaluate_target_family_static_pilot import (
    EVALUATION_REPORT_SCHEMA_VERSION,
    _summary,
    build_evaluation_skeleton,
    enforce_workspace_quota,
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
        holo=_record("4POW", components=(("OP1", "opine"),)),
    )
    return build_detector_manifest((pair,))


def test_evaluation_skeleton_keeps_evaluator_separate_and_bounded() -> None:
    payload = build_evaluation_skeleton(_manifest(), max_cases=2, max_disk_bytes=10_000_000_000)

    assert payload["schema_version"] == EVALUATION_REPORT_SCHEMA_VERSION
    assert payload["detector_target_blind"] is True
    assert payload["evaluator_only"] is True
    assert payload["sealed_evaluation_authorized"] is False
    assert payload["execution"]["motion_enabled"] is False
    assert payload["execution"]["external_baselines_enabled"] is False
    assert payload["execution"]["workers"] == 1
    assert payload["execution"]["max_cases"] == 2
    assert payload["execution"]["max_disk_bytes"] == 10_000_000_000
    assert payload["claim_boundary"] == "diagnostic_dcc_dca_only"
    assert payload["roadmap"]["current_gate"] == "G2-bounded-static-development-pilot"
    assert "4P0I" in payload["roadmap"]["next_step"]


def test_evaluation_skeleton_rejects_unbounded_cases() -> None:
    with pytest.raises(ValueError, match="max_cases"):
        build_evaluation_skeleton(_manifest(), max_cases=11, max_disk_bytes=1)


def test_evaluation_skeleton_is_json_serializable_without_detector_target_tokens() -> None:
    payload = build_evaluation_skeleton(_manifest(), max_cases=2, max_disk_bytes=1)
    serialized = json.dumps(payload, sort_keys=True)

    assert '"ground_truth":' not in serialized.casefold()
    assert "ligand" not in serialized.casefold()


def test_summary_handles_unavailable_case_without_evaluation_payload() -> None:
    summary = _summary(
        {
            "records": {
                "PF00497:4P0I:test": {
                    "case_id": "PF00497:4P0I:test",
                    "case_evaluation": None,
                    "detector_arm": "unavailable",
                }
            }
        }
    )

    assert summary["dcc_dca_computed"] is False
    assert summary["ground_truth_available_case_count"] == 0


def test_workspace_quota_counts_report_and_holo_roots(tmp_path) -> None:
    report_root = tmp_path / "report"
    holo_root = tmp_path / "holo"
    report_root.mkdir()
    holo_root.mkdir()
    (report_root / "report.json").write_bytes(b"x" * 7)
    (holo_root / "4POW.cif").write_bytes(b"y" * 5)

    assert enforce_workspace_quota(report_root, holo_root, 12) == 12
    with pytest.raises(RuntimeError, match="workspace quota"):
        enforce_workspace_quota(report_root, holo_root, 11)
