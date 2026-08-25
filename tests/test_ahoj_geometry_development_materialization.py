from __future__ import annotations

from scripts.materialize_ahoj_geometry_development import select_development_cases


def test_development_materializer_selects_six_full_structure_cases() -> None:
    cohort_cases = [
        {
            "case_id": f"case-{index:02d}",
            "apo_structure_id": f"A{index:03d}",
            "apo_chain_ids": ["A", "B"],
        }
        for index in range(1, 11)
    ]
    manifest_cases = [
        {
            "case_id": f"case-{index:02d}",
            "structure_id": f"A{index:03d}",
            "family_id": "AHOJ-GEOMETRY-V1",
            "split": "development" if index <= 6 else ("validation" if index <= 8 else "test"),
        }
        for index in range(1, 11)
    ]
    manifest = {
        "schema_version": "biovoid-ahoj-geometry-detector-manifest-v1",
        "materialization_status": "metadata_only",
        "boundary": "apo_full_structure_only_v1",
        "cases": manifest_cases,
    }

    selected = select_development_cases({"cases": cohort_cases}, manifest)

    assert len(selected) == 6
    assert [case["apo_structure_id"] for case in selected] == [
        "A001",
        "A002",
        "A003",
        "A004",
        "A005",
        "A006",
    ]
