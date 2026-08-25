from __future__ import annotations

from scripts.audit_ranking_cohort_feasibility import (
    assess_ranking_cohort_feasibility,
)


def _record(
    pdb_id: str,
    uniprot: str,
    *,
    ligand: bool,
    release: str,
    resolution: float = 2.0,
) -> dict:
    return {
        "pdb_id": pdb_id,
        "family_id": "PFTEST",
        "uniprot_ids": [uniprot],
        "experimental_method": "X-RAY DIFFRACTION",
        "sequence_length": 220,
        "resolution_angstrom": resolution,
        "release_date": release,
        "likely_ligand_components": ([{"comp_id": "LIG"}] if ligand else []),
        "resource_proxy": {
            "status": "likely_within_static_atom_cap",
            "authoritative_resource_gate": False,
            "coordinates_required_for_authoritative_gate": True,
        },
    }


def _inventory() -> dict:
    records = [
        _record("A001", "U1", ligand=False, release="2020-01-01"),
        _record("H001", "U1", ligand=True, release="2020-02-01"),
        _record("A002", "U2", ligand=False, release="2020-01-01"),
        _record("H002", "U2", ligand=True, release="2020-02-01"),
        _record("A003", "U3", ligand=False, release="2020-01-01"),
        _record("H003", "U3", ligand=True, release="2020-02-01"),
        _record("A004", "U4", ligand=False, release="2020-01-01"),
        _record("H004", "U4", ligand=True, release="2020-02-01"),
    ]
    return {
        "schema_version": "biovoid-target-family-metadata-inventory-v1",
        "family_id": "PFTEST",
        "inventory_sha256": "a" * 64,
        "records": records,
    }


def _clusters() -> dict:
    records = []
    for index in range(1, 5):
        records.extend(
            [
                {
                    "pdb_id": f"A{index:03d}",
                    "sequence_cluster_id": f"C{index}",
                    "uniprot_ids": [f"U{index}"],
                },
                {
                    "pdb_id": f"H{index:03d}",
                    "sequence_cluster_id": f"C{index}",
                    "uniprot_ids": [f"U{index}"],
                },
            ]
        )
    return {
        "schema_version": "biovoid-target-family-sequence-clusters-v1",
        "status": "sequence_materialized_review_required",
        "family_id": "PFTEST",
        "records": records,
    }


def test_presealed_allocation_excludes_prior_pairs_and_reports_no_go() -> None:
    report = assess_ranking_cohort_feasibility(
        _inventory(),
        _clusters(),
        prior_pair_payload={
            "pairs": [
                {
                    "apo_pdb_id": "A001",
                    "holo_pdb_id": "H001",
                    "uniprot_group": "U1",
                }
            ]
        },
        prior_cohort_payload={"cases": []},
        ri3_manifest_payload={"structures": []},
        catalog_id="synthetic-v1",
        validation_cutoff="2025-01-01",
        temporal_cutoff="2030-01-01",
    )

    assert report["decision"] == "NO_GO"
    assert report["capacity"]["metadata_pair_count"] == 4
    assert report["capacity"]["new_metadata_pair_count"] == 3
    assert report["capacity"]["new_labeled_case_count"] == 0
    assert report["split_allocation"]["status"] == "sealed_metadata_only"
    assert report["split_allocation"]["counts"] == {
        "development": 3,
        "validation": 0,
        "temporal": 0,
        "overflow": 0,
    }


def test_independent_labeled_pool_stays_diagnostic_when_heldout_is_short() -> None:
    inventory = _inventory()
    clusters = _clusters()
    for index in range(5, 7):
        inventory["records"].extend(
            [
                _record(f"A{index:03d}", f"U{index}", ligand=False, release="2020-01-01"),
                _record(f"H{index:03d}", f"U{index}", ligand=True, release="2020-02-01"),
            ]
        )
        clusters["records"].extend(
            [
                {
                    "pdb_id": f"A{index:03d}",
                    "sequence_cluster_id": f"C{index}",
                    "uniprot_ids": [f"U{index}"],
                },
                {
                    "pdb_id": f"H{index:03d}",
                    "sequence_cluster_id": f"C{index}",
                    "uniprot_ids": [f"U{index}"],
                },
            ]
        )
    report = assess_ranking_cohort_feasibility(
        inventory,
        clusters,
        prior_pair_payload={"pairs": []},
        prior_cohort_payload={"cases": []},
        independent_label_payload={
            "cases": [
                {
                    "apo_structure_id": f"A{index:03d}",
                    "holo_structure_id": f"H{index:03d}",
                    "uniprot_group_id": f"U{index}",
                    "sequence_cluster_id": f"C{index}",
                    "label_source": "holo_ligand_contact_v1",
                    "label_quality": "exact",
                }
                for index in range(1, 7)
            ]
        },
        ri3_manifest_payload={"structures": []},
        catalog_id="synthetic-v2",
        validation_cutoff="2025-01-01",
        temporal_cutoff="2030-01-01",
    )

    assert report["decision"] == "DIAGNOSTIC_ONLY"
    assert report["capacity"]["new_labeled_case_count"] == 6
    assert report["split_allocation"]["counts"]["development"] == 6
    assert report["capacity"]["heldout_labeled_case_count"] == 0
