from __future__ import annotations

from zipfile import ZipFile

from scripts.audit_pocketminer_source_catalog import (
    build_pocketminer_catalog,
    build_pocketminer_cohort_payload,
    parse_pocketminer_rows,
)
from src.target_family_cohort import build_target_blind_manifest


def _write_minimal_workbook(path) -> None:
    def cell(column: str, row: int, value: str) -> str:
        escaped = value.replace("&", "&amp;").replace("<", "&lt;")
        return f'<c r="{column}{row}" t="inlineStr"><is><t>{escaped}</t></is></c>'

    rows = [
        '<row r="1">' + cell("B", 1, "Novel cryptic pocket set") + "</row>",
        '<row r="2">' + cell("C", 2, "PDB ID") + cell("G", 2, "PDB ID") + "</row>",
        '<row r="3">'
        + cell("C", 3, "1AAA")
        + cell("E", 3, "A")
        + cell("G", 3, "1BBB")
        + cell("H", 3, "A")
        + cell("I", 3, "LIG")
        + cell("U", 3, "all-heavy-atom RMSD filtering")
        + cell("V", 3, "validation")
        + "</row>",
        '<row r="4">' + cell("B", 4, "Cryptosite proteins") + "</row>",
        '<row r="5">'
        + cell("C", 5, "2AAA")
        + cell("E", 5, "A")
        + cell("G", 5, "2BBB")
        + cell("H", 5, "A")
        + cell("I", 5, "LIG")
        + cell("U", 5, "cryptosite")
        + cell("V", 5, "validation")
        + "</row>",
    ]
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="validation_and_test_sets" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    relationships_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>" + "".join(rows) + "</sheetData></worksheet>"
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def test_parser_keeps_only_the_curated_novel_cryptic_section(tmp_path) -> None:
    workbook = tmp_path / "supplementary.xlsx"
    _write_minimal_workbook(workbook)

    rows = parse_pocketminer_rows(workbook)

    assert len(rows) == 1
    assert rows[0]["apo_pdb_id"] == "1AAA"
    assert rows[0]["label_provenance_class"] == "curated_experimental_apo_holo"


def test_parser_rejects_a_malformed_workbook(tmp_path) -> None:
    workbook = tmp_path / "supplementary.xlsx"
    workbook.write_bytes(b"not-an-xlsx")

    # The parser's public entry point must reject a malformed workbook before
    # any metadata or coordinate retrieval can be attempted.
    try:
        parse_pocketminer_rows(workbook)
    except ValueError as exc:
        assert "xlsx" in str(exc).lower()
    else:
        raise AssertionError("malformed workbook unexpectedly parsed")


def test_catalog_seals_predeclared_three_way_capacity_without_ranking_results() -> None:
    rows = [
        {
            "row_number": index,
            "apo_pdb_id": f"A{index:03d}",
            "apo_chain_id": "A",
            "holo_pdb_id": f"H{index:03d}",
            "holo_chain_id": "A",
            "ligand_code": "LIG",
            "label_provenance_class": "curated_experimental_apo_holo",
            "source_set": "validation" if index % 2 else "test",
        }
        for index in range(1, 13)
    ]
    metadata = {}
    for index in range(1, 13):
        for prefix in ("A", "H"):
            metadata[f"{prefix}{index:03d}"] = {
                "pdb_id": f"{prefix}{index:03d}",
                "chain_id": "A",
                "release_date": (
                    f"{2000 + index:04d}-01-01"
                    if index <= 6
                    else (
                        f"{2009 + index:04d}-01-01" if index <= 8 else f"{2020 + index:04d}-01-01"
                    )
                ),
                "uniprot_ids": [f"U{index}"],
                "sequence": chr(65 + index) * 100,
                "resource_proxy": {"status": "likely_within_static_atom_cap"},
            }

    report = build_pocketminer_catalog(
        rows,
        metadata,
        prior_structure_ids=set(),
        prior_uniprot_ids=set(),
        catalog_id="synthetic-pocketminer-v1",
        validation_cutoff="2010-01-01",
        temporal_cutoff="2020-01-01",
    )

    assert report["schema_version"] == "biovoid-ranking-source-catalog-v1"
    assert report["allocation"]["status"] == "sealed_metadata_only"
    assert report["allocation"]["ranking_outcome_used"] is False
    assert report["capacity"]["candidate_case_count"] == 12
    assert report["capacity"]["split_counts"] == {
        "development": 6,
        "validation": 2,
        "temporal": 2,
        "overflow": 2,
    }
    assert report["source"]["license"] == "MIT"
    assert len(report["source"]["rcsb_metadata_snapshot_sha256"]) == 64
    assert len(report["source"]["sequence_cluster_report_sha256"]) == 64
    assert report["boundary"]["coordinates_downloaded"] is False
    assert report["boundary"]["model_inference_started"] is False


def test_catalog_uses_chain_specific_metadata_for_same_entry() -> None:
    rows = [
        {
            "row_number": 1,
            "apo_pdb_id": "1AAA",
            "apo_chain_id": "A",
            "holo_pdb_id": "1AAA",
            "holo_chain_id": "B",
            "ligand_code": "LIG",
            "label_provenance_class": "curated_experimental_apo_holo",
            "source_set": "validation",
        }
    ]
    metadata = {
        "1AAA:A": {
            "pdb_id": "1AAA",
            "chain_id": "A",
            "release_date": "2001-01-01",
            "uniprot_ids": ["U1"],
            "sequence": "A" * 100,
            "resource_proxy": {"status": "likely_within_static_atom_cap"},
        },
        "1AAA:B": {
            "pdb_id": "1AAA",
            "chain_id": "B",
            "release_date": "2001-01-01",
            "uniprot_ids": ["U1"],
            "sequence": "A" * 100,
            "resource_proxy": {"status": "likely_within_static_atom_cap"},
        },
    }

    report = build_pocketminer_catalog(
        rows,
        metadata,
        prior_structure_ids=set(),
        prior_uniprot_ids=set(),
        catalog_id="synthetic-chain-specific-v1",
        validation_cutoff="2010-01-01",
        temporal_cutoff="2020-01-01",
    )

    candidate = report["candidates"][0]
    assert candidate["metadata_status"] == "complete"
    assert candidate["metadata_eligible_for_selection"] is False
    assert "holo_chain_mismatch" not in candidate["excluded_reasons"]
    assert "apo_holo_same_entry_not_supported" in candidate["excluded_reasons"]


def test_cohort_payload_redacts_temporal_label_as_test_split() -> None:
    report = {
        "schema_version": "biovoid-ranking-source-catalog-v1",
        "decision": "PASS",
        "catalog_id": "synthetic-pocketminer-v1",
        "report_sha256": "r" * 64,
        "allocation": {
            "assignments": [
                {"case_id": "case-dev", "split": "development"},
                {"case_id": "case-val", "split": "validation"},
                {"case_id": "case-temp", "split": "temporal"},
            ],
            "temporal_cutoff": "2020-01-01",
        },
        "candidates": [
            {
                "case_id": "case-dev",
                "apo_pdb_id": "1AAA",
                "apo_chain_id": "A",
                "holo_pdb_id": "1BBB",
                "holo_chain_id": "A",
                "uniprot_group_id": "U1",
                "sequence_cluster_id": "C1",
                "apo_release_date": "2001-01-01",
                "holo_release_date": "2001-01-02",
                "ligand_code": "LIG",
                "label_provenance_class": "curated_experimental_apo_holo",
                "metadata_eligible_for_selection": True,
            },
            {
                "case_id": "case-val",
                "apo_pdb_id": "2AAA",
                "apo_chain_id": "A",
                "holo_pdb_id": "2BBB",
                "holo_chain_id": "A",
                "uniprot_group_id": "U2",
                "sequence_cluster_id": "C2",
                "apo_release_date": "2015-01-01",
                "holo_release_date": "2015-01-02",
                "ligand_code": "LIG",
                "label_provenance_class": "curated_experimental_apo_holo",
                "metadata_eligible_for_selection": True,
            },
            {
                "case_id": "case-temp",
                "apo_pdb_id": "3AAA",
                "apo_chain_id": "A",
                "holo_pdb_id": "3BBB",
                "holo_chain_id": "A",
                "uniprot_group_id": "U3",
                "sequence_cluster_id": "C3",
                "apo_release_date": "2021-01-01",
                "holo_release_date": "2021-01-02",
                "ligand_code": "LIG",
                "label_provenance_class": "curated_experimental_apo_holo",
                "metadata_eligible_for_selection": True,
            },
        ],
    }

    cohort = build_pocketminer_cohort_payload(report, family_id="POCKETMINER")

    assert cohort["schema_version"] == "biovoid-target-family-cohort-v1"
    assert {case["split"] for case in cohort["cases"]} == {
        "development",
        "validation",
        "test",
    }
    assert all(case["label_source"] == "independent_annotation_v1" for case in cohort["cases"])
    detector_manifest = build_target_blind_manifest(cohort)
    assert all("holo" not in str(case["case_id"]).casefold() for case in detector_manifest["cases"])
