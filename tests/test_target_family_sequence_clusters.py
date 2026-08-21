from __future__ import annotations

import json
from typing import Any

import pytest


class _Response:
    def __init__(self, payload: dict[str, Any], *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeSession:
    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self.payloads = payloads
        self.urls: list[str] = []

    def get(self, url: str, *, timeout: int) -> _Response:
        assert timeout == 7
        self.urls.append(url)
        assert "/core/entry/" in url or "/core/polymer_entity/" in url
        assert not url.endswith((".pdb", ".cif", ".mmcif"))
        try:
            return _Response(self.payloads[url])
        except KeyError as exc:
            raise AssertionError(f"unexpected metadata URL: {url}") from exc


def _inventory(*records: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "biovoid-target-family-metadata-inventory-v1",
        "source": {"family_id": "PF00497"},
        "record_count": len(records),
        "records": list(records),
    }


def _record(pdb_id: str, uniprot: str, length: int = 4) -> dict[str, Any]:
    return {
        "pdb_id": pdb_id,
        "family_id": "PF00497",
        "uniprot_ids": [uniprot],
        "sequence_length": length,
    }


def _entity(sequence: str, uniprot: str, *, protein_type: str = "Protein") -> dict[str, Any]:
    return {
        "entity_poly": {
            "rcsb_entity_polymer_type": protein_type,
            "pdbx_seq_one_letter_code_can": sequence,
        },
        "rcsb_polymer_entity_container_identifiers": {"uniprot_ids": [uniprot]},
    }


def test_materializer_matches_expected_uniprot_before_using_sequence() -> None:
    from scripts.materialize_target_family_sequence_clusters import (
        materialize_sequence_clusters,
    )

    payloads = {
        "https://data.rcsb.org/rest/v1/core/entry/TEST": {
            "rcsb_entry_container_identifiers": {"polymer_entity_ids": ["1", "2"]}
        },
        "https://data.rcsb.org/rest/v1/core/polymer_entity/TEST/1": _entity("AAAA", "OTHER"),
        "https://data.rcsb.org/rest/v1/core/polymer_entity/TEST/2": _entity("ACDE", "U1"),
    }
    session = _FakeSession(payloads)

    report = materialize_sequence_clusters(
        _inventory(_record("TEST", "U1")), session=session, timeout=7
    )

    assert report["status"] == "sequence_materialized_review_required"
    assert report["cluster_count"] == 1
    assert report["records"][0]["entity_id"] == "2"
    assert report["records"][0]["sequence_length"] == 4
    assert report["records"][0]["sequence_sha256"]
    assert report["coordinates_downloaded"] is False
    assert report["detector_started"] is False
    assert '"sequence":' not in json.dumps(report)
    assert session.urls == [
        "https://data.rcsb.org/rest/v1/core/entry/TEST",
        "https://data.rcsb.org/rest/v1/core/polymer_entity/TEST/1",
        "https://data.rcsb.org/rest/v1/core/polymer_entity/TEST/2",
    ]


def test_materializer_rejects_missing_matching_protein_entity() -> None:
    from scripts.materialize_target_family_sequence_clusters import (
        SequenceClusterMaterializationError,
        materialize_sequence_clusters,
    )

    payloads = {
        "https://data.rcsb.org/rest/v1/core/entry/TEST": {
            "rcsb_entry_container_identifiers": {"polymer_entity_ids": ["1"]}
        },
        "https://data.rcsb.org/rest/v1/core/polymer_entity/TEST/1": _entity(
            "ACDE", "U1", protein_type="DNA"
        ),
    }

    with pytest.raises(SequenceClusterMaterializationError, match="matching protein"):
        materialize_sequence_clusters(
            _inventory(_record("TEST", "U1")),
            session=_FakeSession(payloads),
            timeout=7,
        )


def test_sequence_clusters_use_global_identity_and_deterministic_ids() -> None:
    from scripts.materialize_target_family_sequence_clusters import (
        cluster_sequence_records,
        global_sequence_identity,
    )

    records = [
        {"pdb_id": "A001", "sequence": "A" * 20},
        {"pdb_id": "A002", "sequence": "A" * 19 + "C"},
        {"pdb_id": "A003", "sequence": "C" * 20},
    ]

    assert global_sequence_identity(
        records[0]["sequence"], records[1]["sequence"]
    ) == pytest.approx(0.95)
    clustered = cluster_sequence_records(records, identity_threshold=0.90)

    assert clustered["cluster_count"] == 2
    assert (
        clustered["records"][0]["sequence_cluster_id"]
        == clustered["records"][1]["sequence_cluster_id"]
    )
    assert (
        clustered["records"][0]["sequence_cluster_id"]
        != clustered["records"][2]["sequence_cluster_id"]
    )
    assert clustered["method"]["linkage"] == "single_linkage_connected_components"
    assert clustered["review_required"] is True


def test_materializer_enforces_bounded_inventory() -> None:
    from scripts.materialize_target_family_sequence_clusters import (
        SequenceClusterMaterializationError,
        materialize_sequence_clusters,
    )

    payload = _inventory(*[_record(f"A{i:03d}", "U1") for i in range(3)])
    with pytest.raises(SequenceClusterMaterializationError, match="maximum record bound"):
        materialize_sequence_clusters(payload, session=_FakeSession({}), max_records=2)


def test_metadata_api_rejects_coordinate_urls() -> None:
    from scripts.materialize_target_family_sequence_clusters import (
        SequenceClusterMaterializationError,
        _api_json,
    )

    with pytest.raises(SequenceClusterMaterializationError, match="coordinate URL"):
        _api_json(_FakeSession({}), "https://example.test/structure.pdb", timeout=7)


def test_materializer_output_is_json_serializable() -> None:
    from scripts.materialize_target_family_sequence_clusters import cluster_sequence_records

    clustered = cluster_sequence_records(
        [{"pdb_id": "A001", "sequence": "ACDE"}], identity_threshold=0.9
    )
    json.dumps(clustered, sort_keys=True)
