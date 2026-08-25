from __future__ import annotations

from typing import Any

from scripts.resolve_ahoj_geometry_metadata import (
    _chain_ids,
    _cluster_membership,
    _date_bucket,
    _matching_entity,
)


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class _Session:
    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self.payloads = payloads
        self.urls: list[str] = []

    def get(self, url: str, *, timeout: int) -> _Response:
        assert timeout == 7
        assert not any(suffix in url.casefold() for suffix in (".pdb", ".cif", ".mmcif"))
        self.urls.append(url)
        return _Response(self.payloads[url])


def _entity(*, uniprot: str = "U1", sequence: str = "ACDE") -> dict[str, Any]:
    return {
        "entity_poly": {
            "rcsb_entity_polymer_type": "Protein",
            "pdbx_seq_one_letter_code_can": sequence,
        },
        "rcsb_polymer_entity_container_identifiers": {
            "auth_asym_ids": ["A", "B"],
            "uniprot_ids": [uniprot],
        },
        "rcsb_cluster_membership": [{"identity": 90, "cluster_id": 123}],
    }


def test_matching_entity_resolves_uniprot_chain_and_sequence_hash(tmp_path) -> None:
    payloads = {
        "https://data.rcsb.org/rest/v1/core/entry/TEST": {
            "rcsb_entry_container_identifiers": {"polymer_entity_ids": ["1"]}
        },
        "https://data.rcsb.org/rest/v1/core/polymer_entity/TEST/1": _entity(),
    }
    session = _Session(payloads)

    result = _matching_entity(session, "TEST", "U1", cache_dir=tmp_path, timeout=7)

    assert result["status"] == "resolved"
    assert result["chain_ids"] == ["A", "B"]
    assert result["sequence_length"] == 4
    assert result["sequence_sha256"]
    assert "sequence" in result
    assert session.urls == list(payloads)


def test_matching_entity_marks_missing_or_ambiguous_entity_for_review(tmp_path) -> None:
    missing_payloads = {
        "https://data.rcsb.org/rest/v1/core/entry/TEST": {
            "rcsb_entry_container_identifiers": {"polymer_entity_ids": ["1"]}
        },
        "https://data.rcsb.org/rest/v1/core/polymer_entity/TEST/1": _entity(uniprot="OTHER"),
    }
    missing = _matching_entity(
        _Session(missing_payloads), "TEST", "U1", cache_dir=tmp_path / "missing", timeout=7
    )
    assert missing["status"] == "no_matching_entity"

    ambiguous_payloads = {
        "https://data.rcsb.org/rest/v1/core/entry/TEST": {
            "rcsb_entry_container_identifiers": {"polymer_entity_ids": ["1", "2"]}
        },
        "https://data.rcsb.org/rest/v1/core/polymer_entity/TEST/1": _entity(sequence="ACDE"),
        "https://data.rcsb.org/rest/v1/core/polymer_entity/TEST/2": _entity(sequence="ACDF"),
    }
    ambiguous = _matching_entity(
        _Session(ambiguous_payloads),
        "TEST",
        "U1",
        cache_dir=tmp_path / "ambiguous",
        timeout=7,
    )
    assert ambiguous["status"] == "ambiguous_matching_entities"


def test_date_buckets_are_frozen_for_the_source_contract() -> None:
    assert _date_bucket("2017-12-31T00:00:00Z") == "development"
    assert _date_bucket("2018-01-01T00:00:00Z") == "validation"
    assert _date_bucket("2020-12-31T00:00:00Z") == "validation"
    assert _date_bucket("2021-01-01T00:00:00Z") == "temporal"
    assert _date_bucket(None) is None


def test_chain_and_cluster_metadata_are_normalized() -> None:
    entity = {
        "rcsb_polymer_entity_container_identifiers": {"asym_ids": ["b", "A", "A"]},
        "rcsb_cluster_membership": [
            {"identity": 50, "cluster_id": 8},
            {"identity": 90, "cluster_id": 3},
            {"identity": "bad", "cluster_id": 4},
        ],
    }

    assert _chain_ids(entity) == ["A", "B"]
    assert _cluster_membership(entity) == [
        {"identity": 90, "cluster_id": 3},
        {"identity": 50, "cluster_id": 8},
    ]
