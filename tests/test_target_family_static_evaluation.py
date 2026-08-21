from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.evaluate_target_family_static_pilot import (
    DEFAULT_HOLO_DIR,
    DEFAULT_MANIFEST,
    DEFAULT_MAX_CASES,
    DEFAULT_PAIRS,
    DEFAULT_REPORT,
    DEFAULT_STATIC_RUN,
    EVALUATION_REPORT_SCHEMA_VERSION,
    TargetFamilyEvaluationError,
    _summary,
    _download_holo,
    _chain_pairs,
    build_evaluation_skeleton,
    enforce_workspace_quota,
    validate_evaluation_report,
)
from src.target_family_manifest import (
    NonPolymerComponent,
    PilotPair,
    RcsbMetadataRecord,
    build_detector_manifest,
)
from src.ground_truth_alignment import ChainPair
from src.structure_preparation import ParsedAtom


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


def test_evaluator_defaults_point_to_current_pfam_cohort() -> None:
    assert DEFAULT_MANIFEST.as_posix().endswith(
        "data/runtime/target-family/cohort-detector-pfam-v1/"
        "target-family-cohort-detector-pfam-v1.json"
    )
    assert DEFAULT_STATIC_RUN.as_posix().endswith(
        "data/runtime/target-family/static-pilot-pfam-v1-rerun-v2/"
        "target-family-static-pilot-run-v1.json"
    )
    assert DEFAULT_PAIRS.as_posix().endswith(
        "local-private/research/target-family/pilot-pairs-pfam-v1.json"
    )
    assert DEFAULT_HOLO_DIR.as_posix().endswith("local-private/research/target-family/holo-pfam-v1")
    assert DEFAULT_REPORT.as_posix().endswith(
        "data/runtime/target-family/static-evaluation-pfam-v1-rerun-v2/"
        "target-family-static-evaluation-pfam-v1.json"
    )
    assert DEFAULT_MAX_CASES == 6


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


def test_download_holo_resolves_relative_cache_root(tmp_path, monkeypatch) -> None:
    import scripts.evaluate_target_family_static_pilot as evaluator

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(evaluator, "REPO_ROOT", tmp_path)
    response = Mock(content=b"data_test\n_atom_site.id\n")
    response.raise_for_status.return_value = None
    session = Mock()
    session.get.return_value = response

    result = _download_holo(session, "1ABC", Path("holo"))

    assert result["path"] == "holo/1ABC.cif"
    assert (tmp_path / "holo/1ABC.cif").is_file()


def test_chain_policy_uses_one_representative_common_chain(monkeypatch) -> None:
    def atoms_for(*chains: str) -> tuple[ParsedAtom, ...]:
        return tuple(
            ParsedAtom(
                record="ATOM",
                atom_name="CA",
                altloc="",
                res_name="ALA",
                chain_id=chain,
                res_id=index,
                ins_code="",
                x=float(index),
                y=0.0,
                z=0.0,
                occupancy=1.0,
                b_factor=0.0,
                element="C",
            )
            for chain in chains
            for index in range(1, 52)
        )

    import scripts.evaluate_target_family_static_pilot as evaluator

    monkeypatch.setattr(
        evaluator,
        "load_structure_atoms",
        lambda path: atoms_for("A", "B") if Path(path).name == "apo" else atoms_for("A", "B"),
    )

    assert _chain_pairs(Path("apo"), Path("holo")) == (ChainPair("A", "A"),)


def test_evaluation_report_guard_accepts_diagnostic_skeleton() -> None:
    manifest = _manifest()
    payload = build_evaluation_skeleton(manifest, max_cases=2, max_disk_bytes=1)

    result = validate_evaluation_report(payload, manifest)

    assert result["status"] == "diagnostic_contract_valid"
    assert result["claim_authorized"] is False


def test_evaluation_report_guard_rejects_claim_ready_flags() -> None:
    manifest = _manifest()
    payload = build_evaluation_skeleton(manifest, max_cases=2, max_disk_bytes=1)
    payload["sealed_evaluation_authorized"] = True

    with pytest.raises(TargetFamilyEvaluationError, match="sealed evaluation"):
        validate_evaluation_report(payload, manifest)
