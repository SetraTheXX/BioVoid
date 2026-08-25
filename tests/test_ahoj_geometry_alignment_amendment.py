from __future__ import annotations

import pytest

from scripts.seal_ahoj_geometry_alignment_amendment import (
    build_alignment_amendment,
    AhojAlignmentAmendmentError,
)


def _resolution_case(apo: str, holo: str, *, release: str, ratio: float = 1.0) -> dict:
    apo_length = 100
    holo_length = round(apo_length * ratio)
    return {
        "apo_structure_id": apo,
        "holo_structure_id": holo,
        "apo_release_date": release,
        "holo_release_date": release,
        "apo_entity": {"status": "resolved", "chain_ids": ["A"], "sequence_length": apo_length},
        "holo_entity": {"status": "resolved", "chain_ids": ["A"], "sequence_length": holo_length},
        "chain_mapping_status": "resolved",
        "label_status": "independent_external_biolip2_site_assignment_v1",
        "overlap_reasons": [],
        "holo_ligand_chain_ids": ["A"],
        "resource_proxy": {"status": "likely_within_static_atom_cap"},
        "sequence_cluster_id": f"cluster-{apo}",
        "uniprot_id": f"U-{apo}",
        "ligand_code": "LIG",
    }


def test_alignment_amendment_replaces_only_the_incompatible_validation_case() -> None:
    ids = ["1AAA", "1AAB", "1AAC", "1AAD", "1AAE", "1AAF"]
    resolution_cases = [_resolution_case(apo, f"{apo[:3]}B", release="2016-01-01") for apo in ids]
    resolution_cases.extend(
        [
            _resolution_case("6EHF", "6EHG", release="2019-01-01"),
            _resolution_case("6J6F", "5FB7", release="2019-02-01", ratio=0.50),
            _resolution_case("8BCL", "8BCM", release="2021-01-01"),
            _resolution_case("8SBN", "8SBO", release="2021-02-01"),
            _resolution_case("6IRX", "6IRY", release="2018-01-01"),
        ]
    )
    v1_cases = []
    for apo in ids:
        v1_cases.append(
            {
                "apo_structure_id": apo,
                "holo_structure_id": f"{apo[:3]}B",
                "split": "development",
            }
        )
    v1_cases.extend(
        [
            {"apo_structure_id": "6EHF", "holo_structure_id": "6EHG", "split": "validation"},
            {"apo_structure_id": "6J6F", "holo_structure_id": "5FB7", "split": "validation"},
            {"apo_structure_id": "8BCL", "holo_structure_id": "8BCM", "split": "temporal"},
            {"apo_structure_id": "8SBN", "holo_structure_id": "8SBO", "split": "temporal"},
        ]
    )

    cohort, manifest = build_alignment_amendment(
        {"decision": "PASS", "cases": resolution_cases},
        {"cases": v1_cases},
    )

    assert cohort["amendment_rule"]["replacement_apo"] == "6IRX"
    assert sum(case["split"] == "development" for case in cohort["cases"]) == 6
    assert sum(case["split"] == "validation" for case in cohort["cases"]) == 2
    assert sum(case["split"] == "temporal" for case in cohort["cases"]) == 2
    assert {case["structure_id"] for case in manifest["cases"]} >= {"6EHF", "6IRX"}
    assert not any(
        token in str(manifest).casefold()
        for token in ("holo", "ligand", "evaluator", "ground_truth", "bio_score")
    )


def test_alignment_amendment_rejects_missing_temporal_reservation() -> None:
    resolution_cases = [
        *[
            _resolution_case(f"{index:04d}", f"{index:04d}", release="2016-01-01")
            for index in range(1, 7)
        ],
        _resolution_case("6EHF", "6EHG", release="2019-01-01"),
        _resolution_case("6J6F", "5FB7", release="2019-02-01", ratio=0.50),
    ]
    v1_cases = [
        *[
            {
                "apo_structure_id": f"{index:04d}",
                "holo_structure_id": f"{index:04d}",
                "split": "development",
            }
            for index in range(1, 7)
        ],
        {"apo_structure_id": "6EHF", "holo_structure_id": "6EHG", "split": "validation"},
        {"apo_structure_id": "6J6F", "holo_structure_id": "5FB7", "split": "validation"},
    ]

    with pytest.raises(AhojAlignmentAmendmentError, match="6/2/2"):
        build_alignment_amendment(
            {"decision": "PASS", "cases": resolution_cases},
            {"cases": v1_cases},
        )
