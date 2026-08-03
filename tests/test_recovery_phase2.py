"""Phase 2 deterministic structure preparation and provenance tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError


def _atom_line(
    serial: int,
    atom_name: str,
    res_name: str,
    chain_id: str,
    res_id: int,
    x: float,
    *,
    record: str = "ATOM",
    altloc: str = "",
    occupancy: float = 1.0,
    element: str | None = None,
) -> str:
    resolved_element = element or atom_name.strip()[0]
    return (
        f"{record:<6}{serial:5d} {atom_name:>4s}{altloc[:1]:1s}{res_name:>3s} "
        f"{chain_id[:1]:1s}{res_id:4d}    {x:8.3f}{0.0:8.3f}{0.0:8.3f}"
        f"{occupancy:6.2f}{20.0:6.2f}          {resolved_element:>2s}"
    )


def _synthetic_mixed_pdb(*, reverse_atoms: bool = False) -> str:
    lines: list[str] = []
    serial = 1
    for residue in range(1, 13):
        for atom_name in ("N", "CA", "C", "O", "CB"):
            if residue == 2 and atom_name == "CB":
                lines.append(
                    _atom_line(
                        serial,
                        atom_name,
                        "ALA",
                        "A",
                        residue,
                        999.0,
                        altloc="B",
                        occupancy=0.25,
                    )
                )
                serial += 1
                lines.append(
                    _atom_line(
                        serial,
                        atom_name,
                        "ALA",
                        "A",
                        residue,
                        2.5,
                        altloc="A",
                        occupancy=0.75,
                    )
                )
            else:
                lines.append(
                    _atom_line(
                        serial,
                        atom_name,
                        "ALA",
                        "A",
                        residue,
                        float(serial),
                    )
                )
            serial += 1

    lines.extend(
        [
            _atom_line(
                serial - 1,
                "P",
                "DA",
                "N",
                1,
                3.0,
                record="ATOM",
                element="P",
            ),
            _atom_line(serial, "O", "HOH", "A", 101, 4.0, record="HETATM", element="O"),
            _atom_line(
                serial + 1,
                "ZN",
                "ZN",
                "A",
                201,
                5.0,
                record="HETATM",
                element="ZN",
            ),
            _atom_line(
                serial + 2,
                "C1",
                "LIG",
                "A",
                301,
                6.0,
                record="HETATM",
                element="C",
            ),
        ]
    )
    if reverse_atoms:
        lines.reverse()
    return "\n".join(["HEADER    PHASE2 SYNTHETIC", *lines, "END", ""])


def test_structure_source_and_preparation_config_are_strictly_typed() -> None:
    from src.api.models import JobOptions
    from src.structure_preparation import PreparationConfig, StructureSource

    source = StructureSource(
        provider="rcsb",
        identifier="1cbs",
        representation="biological_assembly",
        assembly_id="1",
    )
    assert source.identifier == "1CBS"
    assert source.assembly_id == "1"

    config = PreparationConfig(chain_ids=("B", "A", "A"))
    assert config.chain_ids == ("A", "B")
    assert config.detector_atom_policy == "protein_heavy_atoms_only"

    with pytest.raises(ValidationError):
        StructureSource(
            provider="rcsb",
            identifier="1CBS",
            representation="biological_assembly",
        )
    with pytest.raises(ValidationError):
        PreparationConfig(altloc_policy="first_seen")
    with pytest.raises(ValidationError):
        PreparationConfig.model_validate({"known_ligand_center": [1.0, 2.0, 3.0]})
    alphafold_options = JobOptions(
        structure_source="alphafold",
        representation="predicted_model",
        assembly_id=None,
    )
    assert alphafold_options.structure_source == "alphafold"
    with pytest.raises(ValidationError):
        JobOptions(structure_source="alphafold", representation="biological_assembly")


def test_preparation_is_deterministic_and_isolates_nonprotein_context(tmp_path: Path) -> None:
    from src.structure_preparation import (
        PreparationConfig,
        StructureSource,
        prepare_structure,
    )

    first_input = tmp_path / "first.pdb"
    second_input = tmp_path / "second.pdb"
    first_input.write_text(_synthetic_mixed_pdb(), encoding="ascii")
    second_input.write_text(_synthetic_mixed_pdb(reverse_atoms=True), encoding="ascii")
    source = StructureSource(
        provider="local",
        identifier="SYNTHETIC",
        representation="local",
        local_path=first_input,
    )
    config = PreparationConfig()

    first = prepare_structure(
        input_path=first_input,
        source=source,
        config=config,
        output_dir=tmp_path / "run-one",
        run_id="run-one",
    )
    second = prepare_structure(
        input_path=second_input,
        source=source.model_copy(update={"local_path": second_input}),
        config=config,
        output_dir=tmp_path / "run-two",
        run_id="run-two",
    )

    assert first.prepared_sha256 == second.prepared_sha256
    prepared = first.prepared_path.read_text(encoding="ascii")
    assert "HOH" not in prepared
    assert " LIG " not in prepared
    assert " ZN " not in prepared
    assert " DA " not in prepared
    assert " 999.000" not in prepared
    assert "   2.500" in prepared

    context = first.context_path.read_text(encoding="ascii")
    assert " ZN " in context
    assert " LIG " not in context

    report = json.loads(first.report_path.read_text(encoding="utf-8"))
    assert report["counts"]["water_removed"] == 1
    assert report["counts"]["ligand_removed"] == 1
    assert report["counts"]["nonprotein_polymer_atoms_removed"] == 1
    assert report["counts"]["metal_context_preserved"] == 1
    assert report["detector_atom_policy"] == "protein_heavy_atoms_only"
    assert report["context_components"][0]["reason"] == "preserved_metal_context_only"


def test_same_input_and_config_produce_stable_hashes_and_manifest(tmp_path: Path) -> None:
    from src.structure_preparation import (
        PreparationConfig,
        StructureSource,
        prepare_structure,
    )

    input_path = tmp_path / "input.pdb"
    input_path.write_text(_synthetic_mixed_pdb(), encoding="ascii")
    source = StructureSource(
        provider="local",
        identifier="SYNTHETIC",
        representation="local",
        local_path=input_path,
    )
    config = PreparationConfig()

    first = prepare_structure(input_path, source, config, tmp_path / "one", "run-one")
    second = prepare_structure(input_path, source, config, tmp_path / "two", "run-two")

    assert first.input_sha256 == second.input_sha256
    assert first.prepared_sha256 == second.prepared_sha256
    assert first.config_sha256 == second.config_sha256
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["hashes"]["input_sha256"] == first.input_sha256
    assert manifest["hashes"]["prepared_sha256"] == first.prepared_sha256
    assert manifest["hashes"]["preparation_config_sha256"] == first.config_sha256
    assert manifest["analysis_run_id"] == "run-one"
    assert manifest["evaluator_target_included"] is False
    assert manifest["software"]["biovoid_version"]
    assert manifest["software"]["python_version"]
    assert "commit" in manifest["software"]["git"]


def test_preparation_rejects_missing_backbone_and_ca_only_inputs(tmp_path: Path) -> None:
    from src.structure_preparation import (
        PreparationConfig,
        PreparationError,
        StructureSource,
        prepare_structure,
    )

    source = StructureSource(
        provider="local",
        identifier="BROKEN",
        representation="local",
        local_path=tmp_path / "broken.pdb",
    )
    missing = tmp_path / "broken.pdb"
    missing.write_text(
        "\n".join(_atom_line(i, "CA", "ALA", "A", i, float(i)) for i in range(1, 13)) + "\nEND\n",
        encoding="ascii",
    )
    with pytest.raises(PreparationError, match="C-alpha-only"):
        prepare_structure(missing, source, PreparationConfig(), tmp_path / "out", "broken")

    partial = tmp_path / "partial.pdb"
    partial.write_text(
        "\n".join(
            _atom_line(i, "N" if i % 2 else "CA", "ALA", "A", i, float(i)) for i in range(1, 25)
        )
        + "\nEND\n",
        encoding="ascii",
    )
    with pytest.raises(PreparationError, match="missing backbone"):
        prepare_structure(
            partial,
            source.model_copy(update={"local_path": partial}),
            PreparationConfig(
                max_missing_backbone_fraction=0.1,
                min_protein_atoms=4,
            ),
            tmp_path / "partial-out",
            "partial",
        )


def test_representation_is_part_of_provenance_and_run_identity(tmp_path: Path) -> None:
    from src.structure_preparation import (
        PreparationConfig,
        StructureSource,
        prepare_structure,
    )

    input_path = tmp_path / "input.pdb"
    input_path.write_text(_synthetic_mixed_pdb(), encoding="ascii")
    config = PreparationConfig()
    asymmetric = StructureSource(
        provider="rcsb",
        identifier="1CBS",
        representation="asymmetric_unit",
    )
    assembly = StructureSource(
        provider="rcsb",
        identifier="1CBS",
        representation="biological_assembly",
        assembly_id="1",
    )

    first = prepare_structure(input_path, asymmetric, config, tmp_path / "asym", "run-asym")
    second = prepare_structure(input_path, assembly, config, tmp_path / "assembly", "run-assembly")
    first_manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    second_manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))

    assert first_manifest["analysis_run_id"] != second_manifest["analysis_run_id"]
    assert first_manifest["source"]["representation"] == "asymmetric_unit"
    assert second_manifest["source"]["representation"] == "biological_assembly"


def test_fetch_contract_uses_rcsb_assembly_mmcif_and_alphafold_api_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.fetcher import fetch_structure_input
    from src.structure_preparation import StructureSource

    calls: list[str] = []

    class Response:
        def __init__(self, *, content: bytes = b"", payload=None):
            self.content = content
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, **_kwargs):
        calls.append(url)
        if "/core/assembly/" in url:
            return Response(payload={"rcsb_id": "1CBS-1"})
        if url.endswith("1cbs-assembly1.cif"):
            return Response(content=b"data_1CBS\n")
        if "/api/prediction/" in url:
            return Response(
                payload=[
                    {
                        "modelEntityId": "AF-P40763-2-F1",
                        "uniprotAccession": "P40763-2",
                        "pdbUrl": "https://example.test/isoform-model_v6.pdb",
                        "sequenceStart": 1,
                        "sequenceEnd": 720,
                        "uniprotSequence": "A" * 720,
                        "latestVersion": 6,
                    },
                    {
                        "modelEntityId": "AF-P40763-F1",
                        "uniprotAccession": "P40763",
                        "pdbUrl": "https://example.test/AF-P40763-F1-model_v6.pdb",
                        "cifUrl": "https://example.test/model_v6.cif",
                        "paeDocUrl": "https://example.test/pae_v6.json",
                        "globalMetricValue": 84.88,
                        "sequenceStart": 1,
                        "sequenceEnd": 770,
                        "uniprotSequence": "A" * 770,
                        "latestVersion": 6,
                    },
                ]
            )
        if url.endswith("model_v6.pdb"):
            return Response(content=_synthetic_mixed_pdb().encode("ascii"))
        raise AssertionError(url)

    monkeypatch.setattr("src.fetcher.requests.get", fake_get)
    rcsb = fetch_structure_input(
        StructureSource(
            provider="rcsb",
            identifier="1CBS",
            representation="biological_assembly",
            assembly_id="1",
        ),
        cache_dir=tmp_path,
    )
    alphafold = fetch_structure_input(
        StructureSource(
            provider="alphafold",
            identifier="P40763",
            representation="predicted_model",
        ),
        cache_dir=tmp_path,
    )

    assert rcsb.path.name == "1cbs-assembly1.cif"
    assert rcsb.metadata["rcsb_id"] == "1CBS-1"
    assert alphafold.metadata["latest_version"] == 6
    assert alphafold.metadata["model_entity_id"] == "AF-P40763-F1"
    assert alphafold.metadata["fragmented_model"] is False
    assert alphafold.metadata["pae_url"].endswith("pae_v6.json")
    assert any(url.endswith("1cbs-assembly1.cif") for url in calls)
    assert any("/api/prediction/P40763" in url for url in calls)
    assert not any("model_v4" in url for url in calls)


def test_pipeline_prepares_before_detector_and_emits_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import main
    from main import BioVoidPipeline
    from src.fetcher import FetchedStructure
    from src.structure_preparation import StructureSource

    raw = tmp_path / "raw.pdb"
    raw.write_text(_synthetic_mixed_pdb(), encoding="ascii")
    source = StructureSource(
        provider="local",
        identifier="SYNTHETIC",
        representation="local",
        local_path=raw,
    )
    monkeypatch.setattr(
        main,
        "fetch_structure_input",
        lambda *_args, **_kwargs: FetchedStructure(path=raw, metadata={"source": "test"}),
    )
    observed: dict[str, str] = {}

    class FakeDetection:
        candidate_count = 0
        pockets = ()

    def fake_detect_static_pockets(path, **_kwargs):
        observed["path"] = path
        return FakeDetection()

    monkeypatch.setattr(main, "detect_static_pockets", fake_detect_static_pockets)
    pipeline = BioVoidPipeline(
        "SYNTHETIC",
        output_dir=str(tmp_path / "runs"),
        structure_source=source,
    )
    pipeline._fetch_structure()
    pipeline._prepare_structure()
    pipeline._scan_voids()

    assert pipeline.pdb_file is not None
    assert Path(pipeline.pdb_file).name == "prepared_detector.pdb"
    assert observed["path"] == pipeline.pdb_file
    assert pipeline.preparation_result is not None
    assert pipeline.preparation_result.report_path.is_file()
    assert pipeline.preparation_result.manifest_path.is_file()


@pytest.mark.integration
def test_real_rcsb_biological_assembly_preparation(tmp_path: Path) -> None:
    from src.fetcher import fetch_structure_input
    from src.structure_preparation import (
        PreparationConfig,
        StructureSource,
        prepare_structure,
    )

    source = StructureSource(
        provider="rcsb",
        identifier="1BRF",
        representation="biological_assembly",
        assembly_id="1",
    )
    fetched = fetch_structure_input(source, cache_dir=tmp_path / "raw")
    result = prepare_structure(
        fetched.path,
        source,
        PreparationConfig(),
        tmp_path / "prepared",
        "real-1brf-assembly1",
        source_metadata=fetched.metadata,
    )
    repeated = prepare_structure(
        fetched.path,
        source,
        PreparationConfig(),
        tmp_path / "prepared-repeat",
        "real-1brf-assembly1-repeat",
        source_metadata=fetched.metadata,
    )
    report = json.loads(result.report_path.read_text(encoding="utf-8"))

    assert result.prepared_path.is_file()
    assert repeated.prepared_sha256 == result.prepared_sha256
    assert report["counts"]["protein_atoms_selected"] >= 50
    assert report["counts"]["protein_residues_selected"] >= 10
    assert report["source"]["representation"] == "biological_assembly"
