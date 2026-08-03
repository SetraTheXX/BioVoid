from __future__ import annotations

import copy

import pytest

from src.benchmark_v1 import BenchmarkContractError
from src.cryptobench_manifest import (
    build_manifest_payload,
    validate_manifest_payload,
)
from src.cryptobench_adapter import family_group_id


def _record(*, uniprot_id: str = "P12345", ligand: str = "ATP") -> dict:
    return {
        "uniprot_id": uniprot_id,
        "holo_pdb_id": "9ZZZ",
        "holo_chain": "A",
        "apo_chain": "A",
        "ligand": ligand,
        "ligand_index": "1",
        "ligand_chain": "A",
        "apo_pocket_selection": ["A_10", "A_11", "A_12"],
        "holo_pocket_selection": ["A_10", "A_11", "A_12"],
        "pRMSD": 2.1,
        "is_main_holo_structure": True,
    }


def _lock() -> dict:
    return {
        "dataset": {
            "dataset_id": "cryptobench",
            "snapshot_id": "cryptobench-osf-pz4a9-test",
            "osf_node_id": "pz4a9",
            "osf_storage_path": "/cryptobench/",
            "source_repository": "https://example.invalid/source",
            "source_repository_commit": "a" * 40,
            "metadata_files": {
                "dataset.json": {"sha256": "b" * 64},
                "folds.json": {"sha256": "c" * 64},
            },
            "split_allocation": {
                "development": ["train-0"],
                "validation": ["train-1"],
                "sealed": ["test"],
            },
        }
    }


def _inventory() -> list[dict]:
    return [
        {
            "file_id": "archive",
            "kind": "file",
            "name": "cif-files.zip",
            "path": "/cryptobench/cryptobench-dataset/auxiliary-data/cif-files.zip",
            "size": 100,
            "sha256": "d" * 64,
            "date_modified": "2026-01-01T00:00:00Z",
            "api_locator": "https://example.invalid/archive",
        }
    ]


def _manifest() -> dict:
    return build_manifest_payload(
        lock_payload=_lock(),
        dataset={"1abc": [_record()]},
        folds={"train-0": ["1abc"], "train-1": [], "test": []},
        source_inventory=_inventory(),
        api_root="https://example.invalid/api",
        api_retrieved_utc="2026-08-01T00:00:00+00:00",
        generated_at_utc="2026-08-01T00:00:01+00:00",
    )


def test_ri2_manifest_is_target_blind_and_hash_valid() -> None:
    payload = _manifest()
    validate_manifest_payload(payload)
    case = payload["cases"][0]
    assert case["split"] == "development"
    assert case["eligibility"]["status"] == "planned"
    assert case["preparation"]["prepared_structure_sha256"] is None
    assert "holo_pdb_id" not in case["source"]
    assert payload["integrity"]["sealed_case_records_closed"] is True


def test_multi_component_structure_uses_connected_family_group() -> None:
    payload = build_manifest_payload(
        lock_payload=_lock(),
        dataset={"1abc": [_record(uniprot_id="P12345"), _record(uniprot_id="Q99999")]},
        folds={"train-0": ["1abc"], "train-1": [], "test": []},
        source_inventory=_inventory(),
        api_root="https://example.invalid/api",
        api_retrieved_utc="2026-08-01T00:00:00+00:00",
        generated_at_utc="2026-08-01T00:00:01+00:00",
    )
    assert payload["coverage"]["ineligible_case_count"] == 0
    assert payload["coverage"]["planned_case_count"] == 1
    assert payload["cases"][0]["eligibility"]["status"] == "planned"
    assert payload["cases"][0]["family_id"] == family_group_id(["P12345", "Q99999"])


def test_hyphenated_family_components_are_normalized_before_grouping() -> None:
    assert family_group_id(["p12345-q99999", "P12345"]) == "P12345+Q99999"


def test_forbidden_evaluator_field_is_rejected() -> None:
    payload = _manifest()
    payload["cases"][0]["source"]["holo_accession"] = "9ZZZ"
    payload["manifest_sha256"] = "0" * 64
    with pytest.raises(BenchmarkContractError, match="Evaluator or target fields"):
        validate_manifest_payload(payload)


def test_manifest_hash_cannot_be_changed_without_rebuild() -> None:
    payload = _manifest()
    tampered = copy.deepcopy(payload)
    tampered["cases"][0]["family_id"] = "TAMPERED"
    with pytest.raises(BenchmarkContractError, match="content hash"):
        validate_manifest_payload(tampered)
