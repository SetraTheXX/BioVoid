"""Synthetic coordinate-frame tests for evaluator-only holo ground truth."""

from __future__ import annotations

import json
import numpy as np
import pytest


def _protein_atoms(chain_id: str, coordinates: np.ndarray):
    from src.ground_truth_alignment import ProteinAlignmentAtom

    residue_names = ("ALA", "GLY", "SER", "THR")[: len(coordinates)]
    return tuple(
        ProteinAlignmentAtom(
            chain_id=chain_id,
            residue_id=index,
            insertion_code="",
            residue_name=residue_name,
            atom_name="CA",
            coordinate=tuple(float(value) for value in coordinate),
        )
        for index, (residue_name, coordinate) in enumerate(
            zip(residue_names, coordinates, strict=True),
            start=1,
        )
    )


def _alanine_atoms(chain_id: str, coordinates: np.ndarray):
    from src.ground_truth_alignment import ProteinAlignmentAtom

    return tuple(
        ProteinAlignmentAtom(
            chain_id=chain_id,
            residue_id=index,
            insertion_code="",
            residue_name="ALA",
            atom_name="CA",
            coordinate=tuple(float(value) for value in coordinate),
        )
        for index, coordinate in enumerate(coordinates, start=1)
    )


def _pdb_atom_line(
    serial: int,
    *,
    record: str,
    atom_name: str,
    residue_name: str,
    chain_id: str,
    residue_id: int,
    coordinate: np.ndarray,
    element: str,
) -> str:
    return (
        f"{record:<6}{serial:5d} {atom_name:>4s} {residue_name:>3s} "
        f"{chain_id:1s}{residue_id:4d}    "
        f"{coordinate[0]:8.3f}{coordinate[1]:8.3f}{coordinate[2]:8.3f}"
        f"{1.0:6.2f}{20.0:6.2f}          {element:>2s}"
    )


def test_builder_recovers_known_holo_to_prepared_apo_transform() -> None:
    from src.ground_truth_alignment import (
        AlignmentPolicy,
        ChainPair,
        LigandAtom,
        build_aligned_ground_truth,
    )

    holo_coordinates = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 2.0, 0.0],
            [0.0, 0.0, 3.0],
        ]
    )
    expected_rotation = np.array(
        [
            [0.0, 1.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    expected_translation = np.array([5.0, -2.0, 3.0])
    apo_coordinates = holo_coordinates @ expected_rotation + expected_translation
    ligand_coordinates = np.array(
        [
            [0.5, 0.5, 0.5],
            [1.0, 0.5, 0.5],
        ]
    )

    result = build_aligned_ground_truth(
        case_id="cryptobench:1ABC:site-1",
        structure_id="1ABC",
        apo_atoms=_protein_atoms("A", apo_coordinates),
        holo_atoms=_protein_atoms("X", holo_coordinates),
        ligand_atoms=(
            LigandAtom("C1", "C", tuple(ligand_coordinates[0])),
            LigandAtom("N1", "N", tuple(ligand_coordinates[1])),
        ),
        chain_pairs=(ChainPair(apo_chain_id="A", holo_chain_id="X"),),
        prepared_structure_sha256="1" * 64,
        holo_structure_sha256="2" * 64,
        provenance_label="synthetic-rigid-transform",
        policy=AlignmentPolicy(
            minimum_matched_residues=4,
            minimum_sequence_identity=1.0,
            warning_rmsd_angstrom=0.5,
            maximum_rmsd_angstrom=1.0,
        ),
    )

    expected_ligand = ligand_coordinates @ expected_rotation + expected_translation
    assert result.status == "ACCEPTED"
    assert result.matched_residue_count == 4
    assert result.sequence_identity == 1.0
    assert result.fit_rmsd_angstrom < 1e-8
    assert np.allclose(result.rotation, expected_rotation, atol=1e-8)
    assert np.allclose(result.translation, expected_translation, atol=1e-8)
    assert np.allclose(result.ground_truth.ligand_atoms, expected_ligand, atol=1e-8)
    assert np.allclose(
        result.ground_truth.ligand_center,
        expected_ligand.mean(axis=0),
        atol=1e-8,
    )
    assert result.ground_truth.coordinate_frame_sha256 == "1" * 64
    assert result.ground_truth.alignment_sha256 == result.alignment_sha256
    assert len(result.alignment_sha256) == 64


def test_protein_alignment_is_independent_of_ligand_coordinates() -> None:
    from src.ground_truth_alignment import (
        AlignmentPolicy,
        ChainPair,
        LigandAtom,
        build_aligned_ground_truth,
    )

    coordinates = np.array(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [0.0, 2.0, 0.0],
            [0.0, 0.0, 2.0],
        ]
    )
    arguments = {
        "case_id": "cryptobench:1ABC:site-1",
        "structure_id": "1ABC",
        "apo_atoms": _protein_atoms("A", coordinates),
        "holo_atoms": _protein_atoms("X", coordinates),
        "chain_pairs": (ChainPair("A", "X"),),
        "prepared_structure_sha256": "1" * 64,
        "holo_structure_sha256": "2" * 64,
        "provenance_label": "synthetic-ligand-independence",
        "policy": AlignmentPolicy(
            minimum_matched_residues=4,
            minimum_sequence_identity=1.0,
            warning_rmsd_angstrom=0.5,
            maximum_rmsd_angstrom=1.0,
        ),
    }

    near = build_aligned_ground_truth(
        **arguments,
        ligand_atoms=(LigandAtom("C1", "C", (0.5, 0.5, 0.5)),),
    )
    far = build_aligned_ground_truth(
        **arguments,
        ligand_atoms=(LigandAtom("C1", "C", (100.0, -50.0, 25.0)),),
    )

    assert near.alignment_sha256 == far.alignment_sha256
    assert near.rotation == far.rotation
    assert near.translation == far.translation
    assert near.ground_truth.ligand_center != far.ground_truth.ligand_center


def test_builder_rejects_insufficient_or_ambiguous_ca_matches() -> None:
    from src.ground_truth_alignment import (
        AlignmentPolicy,
        ChainPair,
        GroundTruthAlignmentError,
        LigandAtom,
        build_aligned_ground_truth,
    )

    coordinates = np.array(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [0.0, 2.0, 0.0],
            [0.0, 0.0, 2.0],
        ]
    )
    policy = AlignmentPolicy(
        minimum_matched_residues=4,
        minimum_sequence_identity=1.0,
        warning_rmsd_angstrom=0.5,
        maximum_rmsd_angstrom=1.0,
    )
    arguments = {
        "case_id": "cryptobench:1ABC:site-1",
        "structure_id": "1ABC",
        "ligand_atoms": (LigandAtom("C1", "C", (0.5, 0.5, 0.5)),),
        "chain_pairs": (ChainPair("A", "X"),),
        "prepared_structure_sha256": "1" * 64,
        "holo_structure_sha256": "2" * 64,
        "provenance_label": "synthetic-rejection",
        "policy": policy,
    }

    with pytest.raises(GroundTruthAlignmentError, match="Only 3 residues"):
        build_aligned_ground_truth(
            **arguments,
            apo_atoms=_protein_atoms("A", coordinates[:3]),
            holo_atoms=_protein_atoms("X", coordinates[:3]),
        )

    apo_atoms = _protein_atoms("A", coordinates)
    with pytest.raises(GroundTruthAlignmentError, match="Ambiguous duplicate"):
        build_aligned_ground_truth(
            **arguments,
            apo_atoms=apo_atoms + (apo_atoms[0],),
            holo_atoms=_protein_atoms("X", coordinates),
        )


def test_file_builder_extracts_exact_ligand_and_binds_real_file_hashes(
    tmp_path,
) -> None:
    from src.ground_truth_alignment import (
        AlignmentPolicy,
        ChainPair,
        GroundTruthAlignmentError,
        LigandSelector,
        build_aligned_ground_truth_from_files,
    )

    holo_coordinates = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 2.0, 0.0],
            [0.0, 0.0, 3.0],
        ]
    )
    rotation = np.array(
        [
            [0.0, 1.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    translation = np.array([5.0, -2.0, 3.0])
    apo_coordinates = holo_coordinates @ rotation + translation
    ligand_coordinates = np.array([[0.5, 0.5, 0.5], [1.0, 0.5, 0.5]])
    residue_names = ("ALA", "GLY", "SER", "THR")

    apo_lines = [
        _pdb_atom_line(
            index,
            record="ATOM",
            atom_name="CA",
            residue_name=residue_name,
            chain_id="A",
            residue_id=index,
            coordinate=coordinate,
            element="C",
        )
        for index, (residue_name, coordinate) in enumerate(
            zip(residue_names, apo_coordinates, strict=True),
            start=1,
        )
    ]
    holo_lines = [
        _pdb_atom_line(
            index,
            record="ATOM",
            atom_name="CA",
            residue_name=residue_name,
            chain_id="X",
            residue_id=index,
            coordinate=coordinate,
            element="C",
        )
        for index, (residue_name, coordinate) in enumerate(
            zip(residue_names, holo_coordinates, strict=True),
            start=1,
        )
    ]
    holo_lines.extend(
        [
            _pdb_atom_line(
                10 + index,
                record="HETATM",
                atom_name=atom_name,
                residue_name="LIG",
                chain_id="Z",
                residue_id=900,
                coordinate=coordinate,
                element=element,
            )
            for index, (atom_name, element, coordinate) in enumerate(
                (
                    ("C1", "C", ligand_coordinates[0]),
                    ("N1", "N", ligand_coordinates[1]),
                ),
                start=1,
            )
        ]
    )
    holo_lines.extend(
        [
            _pdb_atom_line(
                20 + index,
                record="HETATM",
                atom_name=atom_name,
                residue_name="LIG",
                chain_id="Z",
                residue_id=901,
                coordinate=coordinate,
                element=element,
            )
            for index, (atom_name, element, coordinate) in enumerate(
                (
                    ("C1", "C", np.array([2.0, 0.5, 0.5])),
                    ("N1", "N", np.array([2.5, 0.5, 0.5])),
                ),
                start=1,
            )
        ]
    )
    prepared_path = tmp_path / "prepared.pdb"
    holo_path = tmp_path / "holo.pdb"
    prepared_path.write_text("\n".join([*apo_lines, "END", ""]), encoding="ascii")
    holo_path.write_text("\n".join([*holo_lines, "END", ""]), encoding="ascii")

    result = build_aligned_ground_truth_from_files(
        case_id="cryptobench:1ABC:site-1",
        structure_id="1ABC",
        prepared_apo_path=prepared_path,
        holo_path=holo_path,
        ligand=LigandSelector(
            residue_name="LIG",
            chain_id="Z",
            residue_id=900,
        ),
        chain_pairs=(ChainPair("A", "X"),),
        provenance_label="synthetic-file-boundary",
        policy=AlignmentPolicy(
            minimum_matched_residues=4,
            minimum_sequence_identity=1.0,
            warning_rmsd_angstrom=0.5,
            maximum_rmsd_angstrom=1.0,
        ),
    )

    expected_ligand = ligand_coordinates @ rotation + translation
    assert np.allclose(result.ground_truth.ligand_atoms, expected_ligand, atol=1e-3)
    assert result.ground_truth.coordinate_frame_sha256 == result.prepared_structure_sha256
    assert result.holo_structure_sha256 != result.prepared_structure_sha256
    provenance = json.loads(result.ground_truth.provenance)
    assert provenance["ligand_identity"] == {
        "chain_id": "Z",
        "insertion_code": "",
        "residue_id": 900,
        "residue_name": "LIG",
    }
    assert provenance["ground_truth_sha256"] == result.ground_truth_sha256

    multi_result = build_aligned_ground_truth_from_files(
        case_id="cryptobench:1ABC:multi-site",
        structure_id="1ABC",
        prepared_apo_path=prepared_path,
        holo_path=holo_path,
        ligand=LigandSelector(residue_name="LIG", chain_id="Z", residue_id=900),
        additional_ligands=(LigandSelector(residue_name="LIG", chain_id="Z", residue_id=901),),
        chain_pairs=(ChainPair("A", "X"),),
        provenance_label="synthetic-multi-ligand-boundary",
        policy=AlignmentPolicy(
            minimum_matched_residues=4,
            minimum_sequence_identity=1.0,
            warning_rmsd_angstrom=0.5,
            maximum_rmsd_angstrom=1.0,
        ),
    )

    assert len(multi_result.ground_truth.ligand_atoms) == 4
    multi_provenance = json.loads(multi_result.ground_truth.provenance)
    assert len(multi_provenance["ligand_identity"]["selectors"]) == 2

    with pytest.raises(GroundTruthAlignmentError, match="matched no atoms"):
        build_aligned_ground_truth_from_files(
            case_id="cryptobench:1ABC:missing",
            structure_id="1ABC",
            prepared_apo_path=prepared_path,
            holo_path=holo_path,
            ligand=LigandSelector(
                residue_name="LIG",
                chain_id="Z",
                residue_id=902,
            ),
            chain_pairs=(ChainPair("A", "X"),),
            provenance_label="synthetic-missing-ligand",
            policy=AlignmentPolicy(
                minimum_matched_residues=4,
                minimum_sequence_identity=1.0,
                warning_rmsd_angstrom=0.5,
                maximum_rmsd_angstrom=1.0,
            ),
        )


def test_alignment_quality_policy_warns_then_rejects_high_rmsd() -> None:
    from src.ground_truth_alignment import (
        AlignmentPolicy,
        ChainPair,
        GroundTruthAlignmentError,
        LigandAtom,
        build_aligned_ground_truth,
    )

    holo_coordinates = np.array(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [0.0, 2.0, 0.0],
            [0.0, 0.0, 2.0],
        ]
    )
    apo_coordinates = holo_coordinates.copy()
    apo_coordinates[-1] += np.array([1.0, 0.5, 0.0])
    arguments = {
        "case_id": "cryptobench:1ABC:site-1",
        "structure_id": "1ABC",
        "apo_atoms": _protein_atoms("A", apo_coordinates),
        "holo_atoms": _protein_atoms("X", holo_coordinates),
        "ligand_atoms": (LigandAtom("C1", "C", (0.5, 0.5, 0.5)),),
        "chain_pairs": (ChainPair("A", "X"),),
        "prepared_structure_sha256": "1" * 64,
        "holo_structure_sha256": "2" * 64,
        "provenance_label": "synthetic-quality-policy",
    }

    warning = build_aligned_ground_truth(
        **arguments,
        policy=AlignmentPolicy(
            minimum_matched_residues=4,
            minimum_sequence_identity=1.0,
            warning_rmsd_angstrom=0.1,
            maximum_rmsd_angstrom=2.0,
        ),
    )
    assert warning.status == "ACCEPTED_WITH_WARNINGS"
    assert "protein_alignment_rmsd_above_warning_threshold" in warning.warnings

    with pytest.raises(GroundTruthAlignmentError, match="exceeds"):
        build_aligned_ground_truth(
            **arguments,
            policy=AlignmentPolicy(
                minimum_matched_residues=4,
                minimum_sequence_identity=1.0,
                warning_rmsd_angstrom=0.05,
                maximum_rmsd_angstrom=0.1,
            ),
        )


def test_builder_rejects_non_unique_sequence_mapping() -> None:
    from src.ground_truth_alignment import (
        AlignmentPolicy,
        ChainPair,
        GroundTruthAlignmentError,
        LigandAtom,
        build_aligned_ground_truth,
    )

    apo_coordinates = np.array(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [0.0, 2.0, 0.0],
            [0.0, 0.0, 2.0],
        ]
    )
    holo_coordinates = apo_coordinates[:3]

    with pytest.raises(GroundTruthAlignmentError, match="Ambiguous sequence alignment"):
        build_aligned_ground_truth(
            case_id="cryptobench:1ABC:site-1",
            structure_id="1ABC",
            apo_atoms=_alanine_atoms("A", apo_coordinates),
            holo_atoms=_alanine_atoms("X", holo_coordinates),
            ligand_atoms=(LigandAtom("C1", "C", (0.5, 0.5, 0.5)),),
            chain_pairs=(ChainPair("A", "X"),),
            prepared_structure_sha256="1" * 64,
            holo_structure_sha256="2" * 64,
            provenance_label="synthetic-ambiguous-sequence",
            policy=AlignmentPolicy(
                minimum_matched_residues=3,
                minimum_sequence_identity=1.0,
                warning_rmsd_angstrom=0.5,
                maximum_rmsd_angstrom=2.0,
            ),
        )


def test_structural_recovery_selects_the_lowest_rmsd_mapping() -> None:
    from src.ground_truth_alignment import (
        AlignmentPolicy,
        ChainPair,
        LigandAtom,
        build_aligned_ground_truth,
    )

    apo_coordinates = np.array(
        [
            [0.0, 0.0, 0.0],
            [7.0, 1.0, 0.0],
            [1.0, 8.0, 1.0],
            [2.0, 2.0, 9.0],
            [9.0, 3.0, 4.0],
            [4.0, 11.0, 5.0],
        ]
    )
    # The second apo residue is absent in the holo structure. All residues
    # have the same sequence code, so sequence score alone cannot decide.
    holo_coordinates = apo_coordinates[[0, 2, 3, 4, 5]]

    result = build_aligned_ground_truth(
        case_id="cryptobench:1ABC:structural-recovery",
        structure_id="1ABC",
        apo_atoms=_alanine_atoms("A", apo_coordinates),
        holo_atoms=_alanine_atoms("X", holo_coordinates),
        ligand_atoms=(LigandAtom("C1", "C", (1.0, 1.0, 1.0)),),
        chain_pairs=(ChainPair(apo_chain_id="A", holo_chain_id="X"),),
        prepared_structure_sha256="1" * 64,
        holo_structure_sha256="2" * 64,
        provenance_label="synthetic-structural-recovery",
        policy=AlignmentPolicy(
            minimum_matched_residues=5,
            minimum_sequence_identity=1.0,
            warning_rmsd_angstrom=0.5,
            maximum_rmsd_angstrom=2.0,
            ambiguous_sequence_policy="structural_fit",
            policy_version="ground-truth-alignment-v2-structural-recovery",
        ),
    )

    assert result.fit_rmsd_angstrom < 1e-6
    assert "ambiguous_sequence_alignment_resolved_by_structural_fit" in result.warnings
