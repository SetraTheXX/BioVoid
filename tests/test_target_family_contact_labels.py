from __future__ import annotations

import json
from typing import Any


def _record(
    pdb_id: str,
    group: str,
    *,
    ligand: bool,
    release: str = "2017-01-01",
) -> dict[str, Any]:
    return {
        "pdb_id": pdb_id,
        "family_id": "PF00497",
        "uniprot_ids": [group],
        "sequence_length": 220,
        "resolution_angstrom": 2.0,
        "experimental_method": "X-RAY DIFFRACTION",
        "release_date": release,
        "likely_ligand_components": ([{"comp_id": "LIG", "name": "test ligand"}] if ligand else []),
    }


def test_strict_pair_builder_is_deterministic_and_private() -> None:
    from scripts.materialize_target_family_contact_labels import build_strict_pair_payload

    inventory = {
        "schema_version": "biovoid-target-family-metadata-inventory-v1",
        "source": {"family_id": "PF00497"},
        "records": [
            _record("A001", "U1", ligand=False),
            _record("B001", "U1", ligand=True),
        ],
    }

    pairs = build_strict_pair_payload(inventory, max_cases=10)

    assert pairs["schema_version"] == "biovoid-target-family-pilot-pairs-v1"
    assert pairs["pairs"][0]["case_id"] == "PF00497:A001:0ee3e3f0bfeec843"
    assert pairs["pairs"][0]["holo_components"][0]["comp_id"] == "LIG"
    assert pairs["status"] == "private_contact_label_review_required"
    assert "ground_truth" not in json.dumps(pairs).casefold()


def test_contact_label_report_skeleton_keeps_detector_closed() -> None:
    from scripts.materialize_target_family_contact_labels import build_contact_label_report

    report = build_contact_label_report(
        family_id="PF00497",
        pairs=[
            {
                "case_id": "PF00497:A001:case",
                "apo_pdb_id": "A001",
                "holo_pdb_id": "B001",
                "family_id": "PF00497",
                "uniprot_group": "U1",
                "holo_components": [{"comp_id": "LIG"}],
            }
        ],
        output_root="local-private/research/target-family/contact-labels-pfam-v1",
        max_cases=10,
        max_disk_bytes=1_000_000_000,
    )

    assert report["status"] == "not_started"
    assert report["evaluator_only"] is True
    assert report["detector_started"] is False
    assert report["benchmark_started"] is False
    assert report["ml_training_started"] is False
    assert report["execution"]["workers"] == 1
    assert report["execution"]["max_cases"] == 10
    assert report["records"] == {}
    assert report["coordinates_downloaded"] is False
    assert report["claims_authorized"] is False
