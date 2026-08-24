from __future__ import annotations

import json
from typing import Any


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class _FakeSession:
    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self.payloads = payloads
        self.urls: list[str] = []
        self.posts: list[dict[str, Any]] = []

    def get(self, url: str, *, timeout: int) -> _Response:
        assert timeout == 7
        self.urls.append(url)
        assert ".pdb" not in url and ".cif" not in url and ".mmcif" not in url
        return _Response(self.payloads[url])

    def post(self, url: str, *, json: dict[str, Any], timeout: int) -> _Response:
        assert timeout == 7
        self.posts.append(json)
        assert url == "https://search.rcsb.org/rcsbsearch/v2/query"
        return _Response({"total_count": 2, "result_set": [{"identifier": "A001"}, "B001"]})


def _entry(
    *,
    entity_ids: list[str],
    nonpolymer_ids: list[str],
    release: str,
    deposited_atom_count: int | None = None,
    deposited_model_count: int | None = None,
    polymer_instance_count: int | None = None,
    molecular_weight_kda: float | None = None,
) -> dict[str, Any]:
    entry_info: dict[str, Any] = {"resolution_combined": [2.0]}
    optional_fields = {
        "deposited_atom_count": deposited_atom_count,
        "deposited_model_count": deposited_model_count,
        "deposited_polymer_entity_instance_count": polymer_instance_count,
        "molecular_weight": molecular_weight_kda,
    }
    entry_info.update({key: value for key, value in optional_fields.items() if value is not None})
    return {
        "rcsb_entry_container_identifiers": {
            "polymer_entity_ids": entity_ids,
            "non_polymer_entity_ids": nonpolymer_ids,
        },
        "rcsb_entry_info": entry_info,
        "exptl": [{"method": "X-RAY DIFFRACTION"}],
        "struct": {"title": "test structure"},
        "rcsb_accession_info": {"initial_release_date": release},
    }


def _entity(uniprot: str, sequence: str) -> dict[str, Any]:
    return {
        "rcsb_polymer_entity_annotation": [{"type": "Pfam", "annotation_id": "PF00497"}],
        "rcsb_polymer_entity_container_identifiers": {"uniprot_ids": [uniprot]},
        "entity_poly": {
            "rcsb_entity_polymer_type": "Protein",
            "rcsb_sample_sequence_length": len(sequence),
            "pdbx_seq_one_letter_code_can": sequence,
        },
        "rcsb_polymer_entity": {"pdbx_description": "test protein"},
    }


def test_pfam_inventory_collects_metadata_without_coordinates() -> None:
    from scripts.build_target_family_pfam_inventory import collect_pfam_metadata_records

    payloads = {
        "https://data.rcsb.org/rest/v1/core/entry/A001": _entry(
            entity_ids=["1"], nonpolymer_ids=["1"], release="2020-01-01"
        ),
        "https://data.rcsb.org/rest/v1/core/nonpolymer_entity/A001/1": {
            "pdbx_entity_nonpoly": {"comp_id": "LIG", "name": "Test ligand"}
        },
        "https://data.rcsb.org/rest/v1/core/polymer_entity/A001/1": _entity("U1", "A" * 200),
        "https://data.rcsb.org/rest/v1/core/entry/B001": _entry(
            entity_ids=["1"], nonpolymer_ids=[], release="2019-01-01"
        ),
        "https://data.rcsb.org/rest/v1/core/polymer_entity/B001/1": _entity("U1", "A" * 200),
    }
    session = _FakeSession(payloads)

    records, source = collect_pfam_metadata_records(
        session, family_id="PF00497", max_entries=2, timeout=7
    )

    assert [record.pdb_id for record in records] == ["A001", "B001"]
    assert records[0].has_likely_ligand is True
    assert records[1].has_likely_ligand is False
    assert source["coordinate_files_downloaded"] is False
    assert source["query_kind"] == "pfam_annotation_exact_match"
    assert all(
        "polymer_entity" in url or "entry" in url or "nonpolymer" in url for url in session.urls
    )
    assert session.posts[0]["query"]["parameters"]["value"] == "PF00497"


def test_pfam_inventory_skips_ambiguous_multi_entity_entries() -> None:
    from scripts.build_target_family_pfam_inventory import collect_pfam_metadata_records

    payloads = {
        "https://data.rcsb.org/rest/v1/core/entry/A001": _entry(
            entity_ids=["1", "2"], nonpolymer_ids=[], release="2020-01-01"
        ),
        "https://data.rcsb.org/rest/v1/core/polymer_entity/A001/1": _entity("U1", "A" * 200),
        "https://data.rcsb.org/rest/v1/core/polymer_entity/A001/2": _entity("U2", "C" * 200),
        "https://data.rcsb.org/rest/v1/core/entry/B001": _entry(
            entity_ids=["1"], nonpolymer_ids=[], release="2019-01-01"
        ),
        "https://data.rcsb.org/rest/v1/core/polymer_entity/B001/1": _entity("U1", "A" * 200),
    }
    session = _FakeSession(payloads)

    records, source = collect_pfam_metadata_records(
        session, family_id="PF00497", max_entries=2, timeout=7
    )

    assert [record.pdb_id for record in records] == ["B001"]
    assert source["skipped_multi_entity_entry_count"] == 1


def test_pfam_inventory_payload_is_source_only_and_hashable() -> None:
    from scripts.build_target_family_pfam_inventory import (
        build_pfam_inventory_payload,
        collect_pfam_metadata_records,
    )

    payloads = {
        "https://data.rcsb.org/rest/v1/core/entry/A001": _entry(
            entity_ids=["1"], nonpolymer_ids=[], release="2020-01-01"
        ),
        "https://data.rcsb.org/rest/v1/core/polymer_entity/A001/1": _entity("U1", "A" * 200),
        "https://data.rcsb.org/rest/v1/core/entry/B001": _entry(
            entity_ids=["1"], nonpolymer_ids=["1"], release="2021-01-01"
        ),
        "https://data.rcsb.org/rest/v1/core/nonpolymer_entity/B001/1": {
            "pdbx_entity_nonpoly": {"comp_id": "LIG", "name": "Test ligand"}
        },
        "https://data.rcsb.org/rest/v1/core/polymer_entity/B001/1": _entity("U1", "A" * 200),
    }
    session = _FakeSession(payloads)
    records, source = collect_pfam_metadata_records(
        session, family_id="PF00497", max_entries=2, timeout=7
    )
    payload = build_pfam_inventory_payload(records, source, family_id="PF00497")

    assert payload["schema_version"] == "biovoid-target-family-metadata-inventory-v1"
    assert payload["source"]["query_kind"] == "pfam_annotation_exact_match"
    assert payload["record_count"] == 2
    assert payload["pilot_pair_count"] == 1
    assert "inventory_sha256" in payload
    assert ".pdb" not in json.dumps(payload).casefold()


def test_pfam_inventory_adds_non_authoritative_resource_proxy_screen() -> None:
    from scripts.build_target_family_pfam_inventory import (
        build_pfam_inventory_payload,
        collect_pfam_metadata_records,
    )

    payloads = {
        "https://data.rcsb.org/rest/v1/core/entry/A001": _entry(
            entity_ids=["1"],
            nonpolymer_ids=[],
            release="2020-01-01",
            deposited_atom_count=4200,
            deposited_model_count=1,
            polymer_instance_count=2,
            molecular_weight_kda=48.5,
        ),
        "https://data.rcsb.org/rest/v1/core/polymer_entity/A001/1": _entity("U1", "A" * 200),
        "https://data.rcsb.org/rest/v1/core/entry/B001": _entry(
            entity_ids=["1"],
            nonpolymer_ids=["1"],
            release="2021-01-01",
            deposited_atom_count=7600,
            deposited_model_count=1,
            polymer_instance_count=4,
            molecular_weight_kda=97.0,
        ),
        "https://data.rcsb.org/rest/v1/core/nonpolymer_entity/B001/1": {
            "pdbx_entity_nonpoly": {"comp_id": "LIG", "name": "Test ligand"}
        },
        "https://data.rcsb.org/rest/v1/core/polymer_entity/B001/1": _entity("U1", "A" * 200),
    }
    session = _FakeSession(payloads)
    records, source = collect_pfam_metadata_records(
        session, family_id="PF00497", max_entries=2, timeout=7
    )

    assert records[0].deposited_atom_count == 4200
    assert records[0].deposited_polymer_entity_instance_count == 2
    assert records[0].molecular_weight_kda == 48.5

    payload = build_pfam_inventory_payload(records, source, family_id="PF00497")
    by_id = {record["pdb_id"]: record for record in payload["records"]}

    assert by_id["A001"]["resource_proxy"]["status"] == "likely_within_static_atom_cap"
    assert by_id["B001"]["resource_proxy"]["status"] == "likely_above_static_atom_cap"
    assert payload["resource_proxy_summary"] == {
        "schema_version": "biovoid-target-family-resource-proxy-v1",
        "profile": "safe-16gb",
        "max_static_atoms": 5000,
        "record_status_counts": {
            "likely_within_static_atom_cap": 1,
            "likely_above_static_atom_cap": 1,
            "review_required": 0,
        },
        "strict_pair_apo_status_counts": {
            "likely_within_static_atom_cap": 1,
            "likely_above_static_atom_cap": 0,
            "review_required": 0,
        },
        "authoritative_resource_gate": False,
        "coordinates_required_for_authoritative_gate": True,
    }
