from __future__ import annotations

import pytest


def _record(
    pdb_id: str,
    group: str,
    *,
    ligand: bool,
    length: int = 238,
    resolution: float = 2.0,
    method: str = "X-RAY DIFFRACTION",
) -> dict:
    return {
        "pdb_id": pdb_id,
        "uniprot_ids": [group],
        "family_id": "PF00497",
        "sequence_length": length,
        "resolution_angstrom": resolution,
        "experimental_method": method,
        "likely_ligand_components": [{"comp_id": "ARG"}] if ligand else [],
    }


def _inventory() -> dict:
    records = [
        _record("A001", "U1", ligand=False),
        _record("B001", "U1", ligand=True),
        _record("A002", "U2", ligand=False, resolution=2.7),
        _record("B002", "U2", ligand=True, resolution=2.6),
        _record("A003", "U3", ligand=False, length=126),
        _record("B003", "U3", ligand=True, length=126),
        _record("A004", "U4", ligand=False, method="ELECTRON MICROSCOPY"),
        _record("B004", "U4", ligand=True),
        _record("A005", "U5", ligand=False, resolution=3.2),
        _record("B005", "U5", ligand=True),
    ]
    return {
        "schema_version": "biovoid-target-family-metadata-inventory-v1",
        "family_id": "PF00497",
        "record_count": len(records),
        "records": records,
    }


def test_metadata_candidate_audit_separates_strict_and_relaxed_policies() -> None:
    from scripts.audit_target_family_metadata_candidates import audit_metadata_candidates

    report = audit_metadata_candidates(_inventory())

    assert report["status"] == "candidate_inventory_only"
    assert report["strict"]["eligible_group_count"] == 4
    assert report["relaxed_length_120"]["eligible_group_count"] == 5
    assert report["strict"]["paired_group_count"] == 2
    assert report["relaxed_length_120"]["paired_group_count"] == 3
    assert report["strict"]["selected_pair_count"] == 2
    assert report["sequence_clusters"] == "not_materialized"
    assert report["contact_labels"] == "not_materialized"
    assert report["coordinates_downloaded"] is False


def test_metadata_candidate_audit_rejects_wrong_inventory_schema() -> None:
    from scripts.audit_target_family_metadata_candidates import (
        MetadataCandidateAuditError,
        audit_metadata_candidates,
    )

    payload = _inventory()
    payload["schema_version"] = "wrong"

    with pytest.raises(MetadataCandidateAuditError, match="schema"):
        audit_metadata_candidates(payload)


def test_metadata_candidate_audit_accepts_builder_source_family_field() -> None:
    from scripts.audit_target_family_metadata_candidates import audit_metadata_candidates

    payload = _inventory()
    payload.pop("family_id")
    payload["source"] = {"family_id": "PF00497"}

    report = audit_metadata_candidates(payload)

    assert report["family_id"] == "PF00497"


def test_metadata_candidate_audit_excludes_missing_resolution_without_failing() -> None:
    from scripts.audit_target_family_metadata_candidates import audit_metadata_candidates

    payload = _inventory()
    payload["records"][0]["resolution_angstrom"] = None

    report = audit_metadata_candidates(payload)

    assert report["record_count"] == len(payload["records"])
    assert report["strict"]["eligible_record_count"] == 5
