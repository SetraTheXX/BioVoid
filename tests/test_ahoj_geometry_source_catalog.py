from __future__ import annotations

import csv

import pytest

from scripts.audit_ahoj_geometry_source_catalog import (
    AhojCatalogError,
    _pair_from_entry,
    _resource_proxy,
    load_query_candidates,
    select_query_candidates,
)


def _write_query_summary(path) -> None:
    fields = [
        "ahoj_query",
        "qstruct",
        "qchains3",
        "qlig",
        "qUNPs",
        "num_apo_pockets",
        "num_holo_pockets",
    ]
    rows = [
        {
            "ahoj_query": "2aaa A LIG 1",
            "qstruct": "2AAA",
            "qchains3": "A",
            "qlig": "LIG",
            "qUNPs": "U2",
            "num_apo_pockets": "1",
            "num_holo_pockets": "1",
        },
        {
            "ahoj_query": "2aab A LIG 1",
            "qstruct": "2AAB",
            "qchains3": "A",
            "qlig": "LIG",
            "qUNPs": "U2",
            "num_apo_pockets": "2",
            "num_holo_pockets": "1",
        },
        {
            "ahoj_query": "2aac A ATP 1",
            "qstruct": "2AAC",
            "qchains3": "A",
            "qlig": "ATP",
            "qUNPs": "U1",
            "num_apo_pockets": "1",
            "num_holo_pockets": "1",
        },
        {
            "ahoj_query": "2aad AB ATP 1",
            "qstruct": "2AAD",
            "qchains3": "AB",
            "qlig": "ATP",
            "qUNPs": "U0",
            "num_apo_pockets": "1",
            "num_holo_pockets": "1",
        },
        {
            "ahoj_query": "2aae A ATP 1",
            "qstruct": "2AAE",
            "qchains3": "A",
            "qlig": "ATP",
            "qUNPs": "U0",
            "num_apo_pockets": "0",
            "num_holo_pockets": "1",
        },
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_query_candidates_are_metadata_only_deduplicated_and_sorted(tmp_path) -> None:
    summary = tmp_path / "query_summaries.csv"
    _write_query_summary(summary)

    candidates = load_query_candidates(summary, prior_structure_ids={"2AAC"})

    assert [(item["uniprot_id"], item["query_ligand"]) for item in candidates] == [("U2", "LIG")]
    assert candidates[0]["query_structure_id"] == "2AAA"
    assert candidates[0]["query_chain_id"] == "A"


def test_query_candidates_reject_coordinate_like_input(tmp_path) -> None:
    summary = tmp_path / "query_summaries.pdb"
    summary.write_text("not metadata", encoding="utf-8")

    with pytest.raises(AhojCatalogError, match="coordinate-like"):
        load_query_candidates(summary, prior_structure_ids=set())


def test_resource_proxy_preserves_safe_16gb_cap() -> None:
    safe = _resource_proxy({"rcsb_entry_info": {"deposited_atom_count": 5000}})
    oversized = _resource_proxy({"rcsb_entry_info": {"deposited_atom_count": 5001}})
    unknown = _resource_proxy({})

    assert safe["status"] == "likely_within_static_atom_cap"
    assert oversized["status"] == "likely_above_static_atom_cap"
    assert unknown["status"] == "review_required"


def test_query_selection_round_robins_uniprot_and_skips_duplicate_structures() -> None:
    candidates = [
        {"uniprot_id": "U1", "query_structure_id": "1AAA"},
        {"uniprot_id": "U1", "query_structure_id": "1AAB"},
        {"uniprot_id": "U2", "query_structure_id": "1AAA"},
        {"uniprot_id": "U2", "query_structure_id": "1AAC"},
        {"uniprot_id": "U3", "query_structure_id": "1AAD"},
    ]

    selected = select_query_candidates(candidates, max_queries=4)

    assert [item["query_structure_id"] for item in selected] == [
        "1AAA",
        "1AAC",
        "1AAD",
        "1AAB",
    ]


def test_pair_selection_keeps_apo_and_holo_independent_and_excludes_prior() -> None:
    entry = {
        "entry_key": "1abc-A-LIG-1",
        "target_pdb_id": "1ABC",
        "target_chains": ["A"],
        "target_ligand": "LIG",
        "target_uniprot_ids": ["U1"],
        "found_apo_pdbids": ["1AAA", "1AAB"],
        "found_holo_pdbids": ["1AAC", "1AAD"],
        "num_apo_pdbids": 2,
        "num_holo_pdbids": 2,
    }

    pair = _pair_from_entry(entry, prior_structure_ids={"1AAA", "1AAC"})

    assert pair is not None
    assert pair["apo_structure_id"] == "1AAB"
    assert pair["holo_structure_id"] == "1AAD"
    assert pair["apo_candidate_structure_ids"] == ["1AAB"]
    assert pair["holo_candidate_structure_ids"] == ["1AAD"]


def test_pair_selection_returns_none_when_no_independent_pair_exists() -> None:
    entry = {
        "found_apo_pdbids": ["1AAA"],
        "found_holo_pdbids": ["1AAA"],
    }

    assert _pair_from_entry(entry, prior_structure_ids=set()) is None
