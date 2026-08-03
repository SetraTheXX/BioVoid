from __future__ import annotations

import pytest

from scripts.check_ri6_preflight import _validate_control_report, _validate_inventory
from scripts.materialize_ri6_source_inventory import (
    _build_search_request,
    _classify_entry_metadata,
)
from scripts.run_ri6_prospective_static import (
    _build_source_review_decision,
    _build_target_blind_input_manifest,
    _validate_prospective_output,
)
from scripts.close_ri6_without_claim import _build_closure_record, _validate_closure_record
from scripts.review_ri6_prospective_static import (
    _review_candidate,
    _source_component_decision,
)
from scripts.run_ri6_tem1_transfer_control import (
    RI6ContractError,
    _build_target_blind_manifest,
    _validate_target_blind_manifest,
)
from scripts.write_ri6_target_lock import _cryptobench_accessions, build_target_lock


def test_target_lock_is_exactly_disjoint_from_cryptobench() -> None:
    lock = build_target_lock({"A2RP81", "P18031"})

    assert lock["target"]["primary_uniprot_accessions"] == [
        "A0A5R8T042",
        "Q2PUH3",
        "Q9F663",
    ]
    assert lock["leakage_control"]["exact_accession_overlap"] == []
    assert lock["leakage_control"]["known_family_overlap"] == ["A2RP81"]
    assert "PER" in lock["target"]["excluded_subfamilies"]


def test_target_lock_rejects_exact_accession_leakage() -> None:
    with pytest.raises(RI6ContractError, match="CryptoBench"):
        build_target_lock({"Q9F663"})


def test_cryptobench_accessions_are_read_from_structured_fields(tmp_path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        '{"1ABC": [{"uniprot_id": "P12345-2"}, {"nested": {"uniprot_id": "Q9F663"}}]}',
        encoding="utf-8",
    )

    assert _cryptobench_accessions(dataset) == {"P12345-2", "Q9F663"}


def test_tem1_detector_manifest_contains_no_holo_or_ligand_fields() -> None:
    manifest = _build_target_blind_manifest(
        prepared_path="data/runtime/ri6/tem1/prepared/1JWP.pdb",
        prepared_sha256="a" * 64,
        preparation_config_sha256="b" * 64,
    )

    _validate_target_blind_manifest(manifest)
    encoded = str(manifest).lower()
    assert "1pzo" not in encoded
    assert "ligand" not in encoded
    assert manifest["structure_id"] == "1JWP"


def test_tem1_detector_manifest_rejects_evaluator_leakage() -> None:
    manifest = _build_target_blind_manifest(
        prepared_path="prepared.pdb",
        prepared_sha256="a" * 64,
        preparation_config_sha256="b" * 64,
    )
    manifest["holo_pdb_id"] = "1PZO"

    with pytest.raises(RI6ContractError, match="Evaluator field"):
        _validate_target_blind_manifest(manifest)


def test_control_report_rejects_prospective_or_discovery_claim() -> None:
    report = {
        "status": "completed_retrodiction_control",
        "scientific_scope": "prospective_discovery",
        "detector_target_blind": True,
        "evaluations": [{}, {}],
    }

    with pytest.raises(RI6ContractError, match="scope"):
        _validate_control_report(report, verify_hash=False)


def test_source_inventory_search_is_target_locked_and_metadata_only() -> None:
    request = _build_search_request(("Q9F663", "A0A5R8T042", "Q2PUH3"))

    assert request["return_type"] == "polymer_entity"
    assert request["request_options"]["results_content_type"] == ["experimental"]
    assert request["query"]["parameters"]["operator"] == "in"
    assert request["query"]["parameters"]["value"] == [
        "A0A5R8T042",
        "Q2PUH3",
        "Q9F663",
    ]


def test_source_inventory_never_auto_accepts_apo_metadata() -> None:
    record = _classify_entry_metadata(
        {
            "entry_id": "5UL8",
            "polymer_entity_id": "1",
            "uniprot_accessions": ["Q9F663"],
            "title": "Apo KPC-2 beta-lactamase crystal structure",
            "experimental_methods": ["X-RAY DIFFRACTION"],
            "resolution_angstrom": 1.15,
            "mutation_count": 0,
            "nonpolymer_entity_count": 2,
        }
    )

    assert record["preliminary_status"] == "review_required"
    assert record["title_apo_signal"] is True
    assert record["manual_review_required"] is True


def test_inventory_checker_rejects_auto_accepted_records() -> None:
    inventory = {
        "schema_version": "biovoid-ri6-source-inventory-v1",
        "status": "metadata_materialized_review_required",
        "source": {"coordinate_files_downloaded": False},
        "records": [{"entry_id": "5UL8", "preliminary_status": "eligible"}],
    }

    with pytest.raises(RI6ContractError, match="auto-accepted"):
        _validate_inventory(inventory, verify_hash=False)


def test_ri6_source_review_is_fixed_to_user_approved_5ul8() -> None:
    decision = _build_source_review_decision(user_approved=True)

    assert decision["source_id"] == "5UL8"
    assert decision["review_status"] == "user_approved_for_bounded_static_run"
    assert decision["independent_review_status"] == "pending"
    assert decision["interpretation_authorized"] is False


def test_ri6_prospective_input_manifest_is_target_blind() -> None:
    manifest = _build_target_blind_input_manifest(
        prepared_path="prepared/5UL8.pdb",
        prepared_sha256="a" * 64,
        preparation_config_sha256="b" * 64,
    )

    assert manifest["structure_id"] == "5UL8"
    assert manifest["motion_enabled"] is False
    _validate_target_blind_manifest(manifest)


def test_ri6_prospective_output_cannot_claim_discovery() -> None:
    output = {
        "schema_version": "biovoid-ri6-prospective-static-run-v1",
        "status": "completed_target_blind_static_run_interpretation_pending",
        "claim_boundary": "unvalidated_research_leads_only",
        "detector_target_blind": True,
        "motion_enabled": False,
        "independent_review_status": "pending",
        "candidate_budget": 10,
        "candidates": [],
    }

    _validate_prospective_output(output, verify_hash=False)


def test_ri6_can_close_bounded_phase_without_scientific_claim() -> None:
    closure = _build_closure_record(
        run_sha256="a" * 64,
        raw_pocket_count=112,
        candidate_count=10,
    )

    _validate_closure_record(closure, verify_hash=False)
    assert closure["status"] == "ri6_v1_closed_without_scientific_claim"
    assert closure["scientific_interpretation_authorized"] is False
    assert closure["next_gate"] == "independent_candidate_review"


def test_internal_review_rejects_source_with_active_site_sulfate() -> None:
    decision = _source_component_decision(
        {"component": "SO4", "minimum_core_distance_angstrom": 2.609}
    )

    assert decision == "source_rejected_active_site_occupancy"


def test_internal_review_never_accepts_candidate_from_rejected_source() -> None:
    review = _review_candidate(
        rank=4,
        pocket_id="BV-TEST",
        volume=100.0,
        residues=("A:LEU:91",),
        minimum_core_distance_angstrom=8.0,
        source_eligible=False,
    )

    assert review["decision"] == "rejected_source_active_site_occupancy"
