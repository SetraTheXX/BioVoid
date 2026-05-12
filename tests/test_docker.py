"""
Tests for Bio-Void Hunter Phase 4: Targeted Docking Module
============================================================

Test coverage:
- GridBox calculation (Smart Grid sizing)
- PDBQT preparation (receptor + ligand)
- Vina output parsing (stdout + file)
- DockingResult data model
- Fragment library + chemical probing
- Error handling
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.docking import (
    AFFINITY_GOOD,
    AFFINITY_STRONG,
    AFFINITY_WEAK,
    FRAGMENT_LIBRARY,
    # Constants
    GRID_BUFFER,
    GRID_MAX_SIZE,
    GRID_MIN_SIZE,
    HBOND_DISTANCE_MAX,
    HBOND_DISTANCE_MIN,
    RETINOIC_ACID_SMILES,
    VDW_DISTANCE_MAX,
    # Exceptions
    DockingError,
    DockingPose,
    DockingResult,
    # Data classes
    GridBox,
    Interaction,
    InteractionReport,
    PDBQTError,
    # Classes
    VinaDocking,
    VinaNotFoundError,
    analyze_interactions,
    # Functions
    dock_nma_frames,
    parse_vina_output_file,
    validate_known_ligand,
)
from src.docking.interactions import _extract_pose_atoms, _parse_pdbqt_atoms

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def sample_pocket():
    """Typical cavity dict from scoring pipeline."""
    return {
        "id": 1,
        "rank": 1,
        "center": [10.5, 22.3, 15.7],
        "radius_geom": 8.5,
        "volume": 450.0,
        "bio_score": 0.72,
    }


@pytest.fixture
def small_pocket():
    """Small cavity that triggers GRID_MIN_SIZE."""
    return {
        "id": 2,
        "rank": 2,
        "center": [5.0, 5.0, 5.0],
        "radius_geom": 3.0,
        "bio_score": 0.45,
    }


@pytest.fixture
def large_pocket():
    """Large cavity that triggers GRID_MAX_SIZE."""
    return {
        "id": 3,
        "rank": 3,
        "center": [30.0, 40.0, 50.0],
        "radius_geom": 20.0,
        "bio_score": 0.80,
    }


@pytest.fixture
def numpy_pocket():
    """Pocket with numpy array center."""
    return {
        "id": 4,
        "rank": 4,
        "center": np.array([10.5, 22.3, 15.7]),
        "radius_geom": 8.5,
        "bio_score": 0.60,
    }


@pytest.fixture
def sample_pdb_content():
    """Minimal PDB file content for receptor preparation."""
    return """HEADER    TEST PROTEIN
ATOM      1  N   ALA A   1       1.000   2.000   3.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       2.000   3.000   4.000  1.00  0.00           C
ATOM      3  C   ALA A   1       3.000   4.000   5.000  1.00  0.00           C
ATOM      4  O   ALA A   1       4.000   5.000   6.000  1.00  0.00           O
ATOM      5  CB  ALA A   1       5.000   6.000   7.000  1.00  0.00           C
ATOM      6  H   ALA A   1       0.500   1.500   2.500  1.00  0.00           H
HETATM    7  O   HOH A 101      10.000  10.000  10.000  1.00  0.00           O
ATOM      8  SG  CYS A   2       6.000   7.000   8.000  1.00  0.00           S
END
"""


@pytest.fixture
def sample_vina_stdout():
    """Typical Vina stdout with docking results."""
    return """AutoDock Vina v1.2.7
#################################################################
# If you used AutoDock Vina in your work, please cite:          #
#                                                               #
# J. Eberhardt, D. Santos-Martins, A.F. Tillack, and S. Forli  #
# AutoDock Vina 1.2.0: New Docking Methods, Expanded Force     #
# Field, and Python Bindings, J. Chem. Inf. Model. (2021)      #
# DOI 10.1021/acs.jcim.1c00203                                 #
#################################################################

Reading input ... done.
Setting up the scoring function ... done.
Analyzing the binding site ... done.
Using random seed: 1234567890
Performing search ... done.
Refining results ... done.

mode |   affinity | dist from best mode
     | (kcal/mol) | rmsd l.b.| rmsd u.b.
-----+------------+----------+----------
   1         -7.2      0.000      0.000
   2         -6.8      1.234      2.345
   3         -6.5      2.456      3.567
   4         -5.9      3.789      4.890
   5         -5.2      4.567      5.678
Writing output ... done.
"""


@pytest.fixture
def sample_vina_output_pdbqt():
    """Minimal Vina output PDBQT file content."""
    return """MODEL 1
REMARK VINA RESULT:    -7.2      0.000      0.000
ATOM      1  C1  LIG A   1       1.000   2.000   3.000  1.00  0.00     0.000 C
ENDMDL
MODEL 2
REMARK VINA RESULT:    -6.8      1.234      2.345
ATOM      1  C1  LIG A   1       2.000   3.000   4.000  1.00  0.00     0.000 C
ENDMDL
MODEL 3
REMARK VINA RESULT:    -6.5      2.456      3.567
ATOM      1  C1  LIG A   1       3.000   4.000   5.000  1.00  0.00     0.000 C
ENDMDL
"""


# ============================================================================
# TEST GRID BOX CALCULATION
# ============================================================================


class TestGridBox:
    """Tests for Smart Grid Box calculation."""

    def test_grid_box_normal_pocket(self, sample_pocket):
        """Normal pocket → size = radius*2 + buffer, clamped."""
        # radius=8.5 → raw=8.5*2+6=23.0, within [20,30]
        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = Path(".")
        grid = docker.calculate_grid_box(sample_pocket)

        assert grid.center_x == 10.5
        assert grid.center_y == 22.3
        assert grid.center_z == 15.7
        assert grid.size_x == 23.0  # 8.5*2+6=23
        assert grid.size_y == 23.0
        assert grid.size_z == 23.0

    def test_grid_box_small_pocket_clamp(self, small_pocket):
        """Small pocket → clamped to GRID_MIN_SIZE=20."""
        # radius=3.0 → raw=3*2+6=12 → clamp to 20
        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = Path(".")
        grid = docker.calculate_grid_box(small_pocket)

        assert grid.size_x == GRID_MIN_SIZE
        assert grid.size_y == GRID_MIN_SIZE
        assert grid.size_z == GRID_MIN_SIZE

    def test_grid_box_large_pocket_clamp(self, large_pocket):
        """Large pocket → clamped to GRID_MAX_SIZE=30."""
        # radius=20 → raw=20*2+6=46 → clamp to 30
        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = Path(".")
        grid = docker.calculate_grid_box(large_pocket)

        assert grid.size_x == GRID_MAX_SIZE
        assert grid.size_y == GRID_MAX_SIZE
        assert grid.size_z == GRID_MAX_SIZE

    def test_grid_box_numpy_center(self, numpy_pocket):
        """Numpy array center handled correctly."""
        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = Path(".")
        grid = docker.calculate_grid_box(numpy_pocket)

        assert grid.center_x == pytest.approx(10.5, abs=0.001)
        assert grid.center_y == pytest.approx(22.3, abs=0.001)
        assert grid.center_z == pytest.approx(15.7, abs=0.001)

    def test_grid_box_missing_center_default(self):
        """Missing center defaults to origin."""
        pocket = {"radius_geom": 5.0}
        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = Path(".")
        grid = docker.calculate_grid_box(pocket)

        assert grid.center_x == 0.0
        assert grid.center_y == 0.0
        assert grid.center_z == 0.0

    def test_grid_box_to_vina_args(self, sample_pocket):
        """to_vina_args() produces correct CLI arguments."""
        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = Path(".")
        grid = docker.calculate_grid_box(sample_pocket)
        args = grid.to_vina_args()

        assert "--center_x" in args
        assert "--size_x" in args
        assert len(args) == 12  # 6 params * 2 (key + value)

    def test_grid_box_to_dict(self):
        """GridBox.to_dict() produces correct dictionary."""
        grid = GridBox(1.0, 2.0, 3.0, 20.0, 20.0, 20.0)
        d = grid.to_dict()

        assert d["center_x"] == 1.0
        assert d["size_x"] == 20.0
        assert len(d) == 6

    def test_grid_box_formula(self):
        """Verify formula: size = max(MIN, min(MAX, radius*2 + BUFFER))."""
        test_cases = [
            (5.0, 20.0),  # 5*2+6=16 → clamp to 20
            (7.0, 20.0),  # 7*2+6=20 → exact MIN
            (8.5, 23.0),  # 8.5*2+6=23 → in range
            (10.0, 26.0),  # 10*2+6=26 → in range
            (12.0, 30.0),  # 12*2+6=30 → exact MAX
            (15.0, 30.0),  # 15*2+6=36 → clamp to 30
        ]
        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = Path(".")

        for radius, expected_size in test_cases:
            pocket = {"center": [0, 0, 0], "radius_geom": radius}
            grid = docker.calculate_grid_box(pocket)
            assert grid.size_x == pytest.approx(expected_size, abs=0.1), (
                f"radius={radius}: expected {expected_size}, got {grid.size_x}"
            )


# ============================================================================
# TEST PDBQT PREPARATION
# ============================================================================


class TestPDBQTPreparation:
    """Tests for receptor and ligand PDBQT conversion."""

    def test_receptor_pdbqt_creation(self, sample_pdb_content, tmp_path):
        """PDB → PDBQT conversion produces valid output."""
        pdb_file = tmp_path / "test.pdb"
        pdb_file.write_text(sample_pdb_content)
        output_file = tmp_path / "test_receptor.pdbqt"

        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = tmp_path

        result_path = docker.prepare_receptor(str(pdb_file), str(output_file))

        assert Path(result_path).exists()
        content = Path(result_path).read_text()
        lines = content.strip().split("\n")
        assert len(lines) > 0

    def test_receptor_strips_waters(self, sample_pdb_content, tmp_path):
        """Water molecules (HOH) are stripped from PDBQT."""
        pdb_file = tmp_path / "test.pdb"
        pdb_file.write_text(sample_pdb_content)

        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = tmp_path

        result_path = docker.prepare_receptor(str(pdb_file))
        content = Path(result_path).read_text()

        assert "HOH" not in content

    def test_receptor_strips_hydrogens(self, sample_pdb_content, tmp_path):
        """Hydrogen atoms are stripped from PDBQT."""
        pdb_file = tmp_path / "test.pdb"
        pdb_file.write_text(sample_pdb_content)

        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = tmp_path

        result_path = docker.prepare_receptor(str(pdb_file))
        content = Path(result_path).read_text()

        # Hydrogen line should not be present
        for line in content.strip().split("\n"):
            if line.startswith("ATOM") or line.startswith("HETATM"):
                element = line[76:78].strip() if len(line) >= 78 else ""
                assert element != "H", f"Hydrogen found: {line}"

    def test_receptor_ad4_atom_types(self, sample_pdb_content, tmp_path):
        """AD4 atom types assigned correctly."""
        pdb_file = tmp_path / "test.pdb"
        pdb_file.write_text(sample_pdb_content)

        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = tmp_path

        result_path = docker.prepare_receptor(str(pdb_file))
        content = Path(result_path).read_text()
        lines = [l for l in content.strip().split("\n") if l.startswith("ATOM")]

        # Should have N→NA, C→C, O→OA, S→SA
        assert len(lines) >= 4  # N, CA, C, O, CB, SG (no H, no HOH)

    def test_receptor_pdb_not_found(self, tmp_path):
        """Missing PDB raises PDBQTError."""
        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = tmp_path

        with pytest.raises(PDBQTError, match="PDB file not found"):
            docker.prepare_receptor(str(tmp_path / "nonexistent.pdb"))

    def test_receptor_empty_pdb(self, tmp_path):
        """PDB with no valid atoms produces minimal PDBQT (no ATOM lines)."""
        pdb_file = tmp_path / "empty.pdb"
        pdb_file.write_text("HEADER EMPTY\nEND\n")

        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = tmp_path

        result_path = docker.prepare_receptor(str(pdb_file))
        content = Path(result_path).read_text()
        atom_lines = [l for l in content.splitlines() if l.startswith("ATOM")]
        assert len(atom_lines) == 0

    def test_ad4_type_mapping(self):
        """AD4 atom type mapping covers common elements."""
        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = Path(".")

        assert docker._get_ad4_atom_type("C") == "C"
        assert docker._get_ad4_atom_type("N") == "NA"
        assert docker._get_ad4_atom_type("O") == "OA"
        assert docker._get_ad4_atom_type("S") == "SA"
        assert docker._get_ad4_atom_type("P") == "P"
        assert docker._get_ad4_atom_type("Zn") == "Zn"
        assert docker._get_ad4_atom_type("FE") == "Fe"

    def test_ligand_from_smiles_benzene(self, tmp_path):
        """Benzene SMILES → PDBQT via Meeko."""
        try:
            from meeko import MoleculePreparation
            from rdkit.Chem import MolFromSmiles
        except ImportError:
            pytest.skip("RDKit/Meeko not installed")

        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = tmp_path

        result = docker.prepare_ligand_from_smiles("c1ccccc1", name="benzene")
        assert Path(result).exists()
        content = Path(result).read_text()
        assert "ATOM" in content or "ROOT" in content

    def test_ligand_invalid_smiles(self, tmp_path):
        """Invalid SMILES raises PDBQTError."""
        try:
            from meeko import MoleculePreparation
            from rdkit.Chem import MolFromSmiles
        except ImportError:
            pytest.skip("RDKit/Meeko not installed")

        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = tmp_path

        with pytest.raises(PDBQTError, match="Invalid SMILES"):
            docker.prepare_ligand_from_smiles("INVALID_SMILES_STRING")


# ============================================================================
# TEST VINA OUTPUT PARSING
# ============================================================================


class TestVinaOutputParsing:
    """Tests for parsing Vina stdout and output files."""

    def test_parse_stdout_normal(self, sample_vina_stdout):
        """Parse typical Vina stdout with 5 modes."""
        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = Path(".")

        poses = docker._parse_vina_stdout(sample_vina_stdout)

        assert len(poses) == 5
        assert poses[0].mode == 1
        assert poses[0].affinity == pytest.approx(-7.2, abs=0.01)
        assert poses[0].rmsd_lb == pytest.approx(0.0, abs=0.001)
        assert poses[1].affinity == pytest.approx(-6.8, abs=0.01)
        assert poses[4].affinity == pytest.approx(-5.2, abs=0.01)

    def test_parse_stdout_empty(self):
        """Empty stdout → empty poses list."""
        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = Path(".")

        poses = docker._parse_vina_stdout("")
        assert len(poses) == 0

    def test_parse_stdout_no_results(self):
        """Vina stdout without results table."""
        output = "AutoDock Vina v1.2.7\nSome error occurred\n"
        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = Path(".")

        poses = docker._parse_vina_stdout(output)
        assert len(poses) == 0

    def test_parse_output_file(self, sample_vina_output_pdbqt, tmp_path):
        """Parse Vina output PDBQT file with REMARK lines."""
        out_file = tmp_path / "output.pdbqt"
        out_file.write_text(sample_vina_output_pdbqt)

        poses = parse_vina_output_file(str(out_file))

        assert len(poses) == 3
        assert poses[0].affinity == pytest.approx(-7.2, abs=0.01)
        assert poses[1].affinity == pytest.approx(-6.8, abs=0.01)
        assert poses[2].affinity == pytest.approx(-6.5, abs=0.01)
        assert poses[0].rmsd_lb == 0.0
        assert poses[1].rmsd_lb == pytest.approx(1.234, abs=0.001)

    def test_parse_output_file_nonexistent(self, tmp_path):
        """Nonexistent file → empty list."""
        poses = parse_vina_output_file(str(tmp_path / "nope.pdbqt"))
        assert len(poses) == 0


# ============================================================================
# TEST DOCKING RESULT
# ============================================================================


class TestDockingResult:
    """Tests for DockingResult data model."""

    def test_result_druggable_strong(self):
        """Affinity < -8.0 → strong, druggable."""
        result = DockingResult(
            pocket_id=1,
            pocket_rank=1,
            ligand_name="test",
            ligand_smiles="C",
            grid_box={},
            best_affinity=-8.5,
            success=True,
        )
        assert result.is_druggable is True
        assert result.affinity_class == "strong"

    def test_result_druggable_good(self):
        """Affinity -6.0 to -8.0 → good, druggable."""
        result = DockingResult(
            pocket_id=1,
            pocket_rank=1,
            ligand_name="test",
            ligand_smiles="C",
            grid_box={},
            best_affinity=-7.0,
            success=True,
        )
        assert result.is_druggable is True
        assert result.affinity_class == "good"

    def test_result_not_druggable_weak(self):
        """Affinity -4.0 to -6.0 → weak, not druggable."""
        result = DockingResult(
            pocket_id=1,
            pocket_rank=1,
            ligand_name="test",
            ligand_smiles="C",
            grid_box={},
            best_affinity=-5.0,
            success=True,
        )
        assert result.is_druggable is False
        assert result.affinity_class == "weak"

    def test_result_not_druggable_none(self):
        """Affinity > -4.0 → none, not druggable."""
        result = DockingResult(
            pocket_id=1,
            pocket_rank=1,
            ligand_name="test",
            ligand_smiles="C",
            grid_box={},
            best_affinity=-2.0,
            success=True,
        )
        assert result.is_druggable is False
        assert result.affinity_class == "none"

    def test_result_boundary_good(self):
        """Exact -6.0 boundary: threshold uses < so -6.0 is weak, not druggable."""
        result = DockingResult(
            pocket_id=1,
            pocket_rank=1,
            ligand_name="test",
            ligand_smiles="C",
            grid_box={},
            best_affinity=-6.0,
            success=True,
        )
        assert result.is_druggable is False  # -6.0 is not < AFFINITY_GOOD (-6.0)
        assert result.affinity_class == "weak"  # -6.0 < AFFINITY_WEAK (-4.0)

    def test_result_to_dict(self):
        """to_dict() produces complete dictionary."""
        pose = DockingPose(mode=1, affinity=-7.2, rmsd_lb=0.0, rmsd_ub=0.0)
        result = DockingResult(
            pocket_id=1,
            pocket_rank=1,
            ligand_name="benzene",
            ligand_smiles="c1ccccc1",
            grid_box={"center_x": 10.0},
            poses=[pose],
            best_affinity=-7.2,
            success=True,
        )
        d = result.to_dict()

        assert d["pocket_id"] == 1
        assert d["best_affinity"] == -7.2
        assert d["is_druggable"] is True
        assert d["affinity_class"] == "good"
        assert d["n_poses"] == 1
        assert len(d["poses"]) == 1
        assert d["error"] is None

    def test_result_failed(self):
        """Failed docking result."""
        result = DockingResult(
            pocket_id=1,
            pocket_rank=1,
            ligand_name="test",
            ligand_smiles="C",
            grid_box={},
            success=False,
            error="Vina crashed",
        )
        assert result.success is False
        assert result.error == "Vina crashed"
        assert result.is_druggable is False


# ============================================================================
# TEST CONSTANTS & FRAGMENT LIBRARY
# ============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_grid_constants(self):
        """Grid sizing constants are valid."""
        assert GRID_BUFFER == 6.0
        assert GRID_MIN_SIZE == 20.0
        assert GRID_MAX_SIZE == 30.0
        assert GRID_MIN_SIZE < GRID_MAX_SIZE

    def test_affinity_thresholds(self):
        """Affinity thresholds are ordered correctly."""
        assert AFFINITY_STRONG < AFFINITY_GOOD < AFFINITY_WEAK < 0

    def test_fragment_library(self):
        """Fragment library has required types and fields."""
        assert "hydrophobic" in FRAGMENT_LIBRARY
        assert "polar" in FRAGMENT_LIBRARY
        assert "mixed" in FRAGMENT_LIBRARY

        for _frag_type, frag in FRAGMENT_LIBRARY.items():
            assert "name" in frag
            assert "smiles" in frag
            assert "description" in frag
            assert len(frag["smiles"]) > 0

    def test_fragment_smiles_valid(self):
        """Fragment SMILES strings valid in RDKit."""
        try:
            from rdkit.Chem import MolFromSmiles
        except ImportError:
            pytest.skip("RDKit not installed")

        for frag_type, frag in FRAGMENT_LIBRARY.items():
            mol = MolFromSmiles(frag["smiles"])
            assert mol is not None, f"Invalid SMILES for {frag_type}: {frag['smiles']}"


# ============================================================================
# TEST VINA WRAPPER (MOCKED)
# ============================================================================


class TestVinaDockingMocked:
    """Tests for VinaDocking with mocked subprocess."""

    @patch("subprocess.run")
    def test_vina_init_success(self, mock_run, tmp_path):
        """VinaDocking init with successful Vina verification."""
        mock_run.return_value = MagicMock(
            stdout="AutoDock Vina v1.2.7",
            stderr="",
            returncode=0,
        )
        vina_bin = tmp_path / "vina.exe"
        vina_bin.write_text("dummy")

        docker = VinaDocking(
            vina_bin=str(vina_bin),
            output_dir=str(tmp_path / "output"),
        )
        assert docker.vina_version == "1.2.7"

    @patch("src.docking.vina_wrapper.subprocess.run")
    def test_run_docking_success(self, mock_run, tmp_path, sample_vina_stdout):
        """Successful docking run with mocked Vina."""
        mock_run.return_value = MagicMock(
            stdout=sample_vina_stdout,
            stderr="",
            returncode=0,
        )

        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = tmp_path / "vina.exe"
            docker.output_dir = tmp_path
            docker.exhaustiveness = 8
            docker.num_modes = 9
            docker.energy_range = 3.0

        # Create dummy PDBQT files
        receptor = tmp_path / "receptor.pdbqt"
        receptor.write_text("ATOM dummy receptor")
        ligand = tmp_path / "ligand.pdbqt"
        ligand.write_text("ATOM dummy ligand")

        grid = GridBox(10.0, 20.0, 30.0, 22.0, 22.0, 22.0)

        poses = docker.run_docking(receptor, ligand, grid, "test_dock")

        assert len(poses) == 5
        assert poses[0].affinity == pytest.approx(-7.2, abs=0.01)

    @patch("src.docking.vina_wrapper.subprocess.run")
    def test_run_docking_timeout(self, mock_run, tmp_path):
        """Docking timeout → DockingError raised."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="vina", timeout=300)

        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = tmp_path / "vina.exe"
            docker.output_dir = tmp_path
            docker.exhaustiveness = 8
            docker.num_modes = 9
            docker.energy_range = 3.0

        receptor = tmp_path / "receptor.pdbqt"
        receptor.write_text("ATOM dummy")
        ligand = tmp_path / "ligand.pdbqt"
        ligand.write_text("ATOM dummy")

        grid = GridBox(0, 0, 0, 20, 20, 20)
        with pytest.raises(DockingError, match="timed out"):
            docker.run_docking(receptor, ligand, grid)

    @patch("src.docking.vina_wrapper.subprocess.run")
    def test_run_docking_failure(self, mock_run, tmp_path):
        """Docking failure → DockingError raised with stderr."""
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="Error: receptor file corrupt",
            returncode=1,
        )

        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = tmp_path / "vina.exe"
            docker.output_dir = tmp_path
            docker.exhaustiveness = 8
            docker.num_modes = 9
            docker.energy_range = 3.0

        receptor = tmp_path / "receptor.pdbqt"
        receptor.write_text("ATOM dummy")
        ligand = tmp_path / "ligand.pdbqt"
        ligand.write_text("ATOM dummy")

        grid = GridBox(0, 0, 0, 20, 20, 20)
        with pytest.raises(DockingError, match="receptor file corrupt"):
            docker.run_docking(receptor, ligand, grid)


# ============================================================================
# TEST DOCKING POSE
# ============================================================================


class TestDockingPose:
    """Tests for DockingPose data class."""

    def test_pose_creation(self):
        """DockingPose stores values correctly."""
        pose = DockingPose(mode=1, affinity=-7.2, rmsd_lb=0.0, rmsd_ub=0.0)
        assert pose.mode == 1
        assert pose.affinity == -7.2
        assert pose.rmsd_lb == 0.0
        assert pose.rmsd_ub == 0.0

    def test_pose_sorting(self):
        """Poses can be sorted by affinity."""
        poses = [
            DockingPose(3, -5.5, 2.0, 3.0),
            DockingPose(1, -7.2, 0.0, 0.0),
            DockingPose(2, -6.8, 1.0, 2.0),
        ]
        sorted_poses = sorted(poses, key=lambda p: p.affinity)
        assert sorted_poses[0].affinity == -7.2
        assert sorted_poses[-1].affinity == -5.5


# ============================================================================
# TEST ERROR HANDLING
# ============================================================================


class TestErrorHandling:
    """Tests for exception hierarchy."""

    def test_docking_error_hierarchy(self):
        """DockingError is base for all docking errors."""
        assert issubclass(VinaNotFoundError, DockingError)
        assert issubclass(PDBQTError, DockingError)

    @patch.object(VinaDocking, "_resolve_vina_path")
    def test_vina_not_found(self, mock_resolve, tmp_path):
        """VinaNotFoundError when binary missing."""
        mock_resolve.side_effect = VinaNotFoundError("Vina binary not found")
        with pytest.raises((VinaNotFoundError, DockingError)):
            VinaDocking(
                vina_bin=str(tmp_path / "nonexistent_vina_binary"),
                output_dir=str(tmp_path / "out"),
            )

    @patch("src.docking.vina_wrapper.subprocess.run")
    def test_receptor_missing(self, mock_run, tmp_path):
        """Missing receptor → DockingError (Vina returns error)."""
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="Receptor file not found",
            returncode=1,
        )
        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = tmp_path
            docker.exhaustiveness = 8
            docker.num_modes = 9
            docker.energy_range = 3.0

        grid = GridBox(0, 0, 0, 20, 20, 20)
        ligand = tmp_path / "ligand.pdbqt"
        ligand.write_text("ATOM dummy")

        with pytest.raises(DockingError, match="Receptor"):
            docker.run_docking(tmp_path / "missing.pdbqt", ligand, grid)

    @patch("src.docking.vina_wrapper.subprocess.run")
    def test_ligand_missing(self, mock_run, tmp_path):
        """Missing ligand → DockingError (Vina returns error)."""
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="Ligand file not found",
            returncode=1,
        )
        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = Path("dummy")
            docker.output_dir = tmp_path
            docker.exhaustiveness = 8
            docker.num_modes = 9
            docker.energy_range = 3.0

        grid = GridBox(0, 0, 0, 20, 20, 20)
        receptor = tmp_path / "receptor.pdbqt"
        receptor.write_text("ATOM dummy")

        with pytest.raises(DockingError, match="Ligand"):
            docker.run_docking(receptor, tmp_path / "missing.pdbqt", grid)


# ============================================================================
# TEST DOCK POCKET (INTEGRATION-LEVEL MOCK)
# ============================================================================


class TestDockPocket:
    """Tests for high-level dock_pocket and probe_pocket."""

    @patch("subprocess.run")
    def test_dock_pocket_enriches_result(
        self, mock_run, tmp_path, sample_pocket, sample_vina_stdout
    ):
        """dock_pocket enriches DockingResult with pocket info."""
        mock_run.return_value = MagicMock(
            stdout=sample_vina_stdout,
            stderr="",
            returncode=0,
        )

        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = tmp_path / "vina.exe"
            docker.output_dir = tmp_path
            docker.exhaustiveness = 8
            docker.num_modes = 9
            docker.energy_range = 3.0

        receptor = tmp_path / "receptor.pdbqt"
        receptor.write_text("ATOM dummy")

        # Mock ligand preparation
        with patch.object(
            docker, "prepare_ligand_from_smiles", return_value=tmp_path / "ligand.pdbqt"
        ):
            # Create the fake ligand file
            (tmp_path / "ligand.pdbqt").write_text("ATOM dummy")
            result = docker.dock_pocket(sample_pocket, receptor, "c1ccccc1", "benzene")

        assert result.pocket_id == 1
        assert result.pocket_rank == 1
        assert result.ligand_name == "benzene"
        assert result.ligand_smiles == "c1ccccc1"
        assert result.success is True

    @patch("subprocess.run")
    def test_probe_pocket_3_fragments(self, mock_run, tmp_path, sample_pocket, sample_vina_stdout):
        """probe_pocket runs 3 fragment docks."""
        mock_run.return_value = MagicMock(
            stdout=sample_vina_stdout,
            stderr="",
            returncode=0,
        )

        with patch.object(VinaDocking, "_verify_vina"):
            docker = VinaDocking.__new__(VinaDocking)
            docker.vina_path = tmp_path / "vina.exe"
            docker.output_dir = tmp_path
            docker.exhaustiveness = 8
            docker.num_modes = 9
            docker.energy_range = 3.0

        receptor = tmp_path / "receptor.pdbqt"
        receptor.write_text("ATOM dummy")

        with patch.object(
            docker, "prepare_ligand_from_smiles", return_value=tmp_path / "ligand.pdbqt"
        ):
            (tmp_path / "ligand.pdbqt").write_text("ATOM dummy")
            results = docker.probe_pocket(sample_pocket, receptor)

        assert len(results) == 3  # hydrophobic + polar + mixed


# ============================================================================
# TEST INTERACTION ANALYSIS (Phase 4.2)
# ============================================================================


class TestPDBQTAtomParsing:
    """Tests for _parse_pdbqt_atoms helper."""

    def test_parse_basic_atoms(self, tmp_path):
        """Parse ATOM/HETATM lines from PDBQT."""
        content = (
            "ATOM      1  N   ALA A   1       1.000   2.000   3.000"
            "  1.00  0.00           N\n"
            "ATOM      2  CA  ALA A   1       2.000   3.000   4.000"
            "  1.00  0.00           C\n"
            "HETATM    3  O   HOH A  99      10.000  20.000  30.000"
            "  1.00  0.00           O\n"
            "END\n"
        )
        pdbqt = tmp_path / "test.pdbqt"
        pdbqt.write_text(content)

        atoms = _parse_pdbqt_atoms(str(pdbqt))
        assert len(atoms) == 3
        assert atoms[0]["name"] == "N"
        assert atoms[0]["resName"] == "ALA"
        assert atoms[0]["resSeq"] == 1
        assert atoms[0]["x"] == pytest.approx(1.0)
        assert atoms[0]["y"] == pytest.approx(2.0)
        assert atoms[0]["z"] == pytest.approx(3.0)
        assert atoms[0]["element"] == "N"

    def test_parse_empty_file(self, tmp_path):
        """Empty file returns empty list."""
        pdbqt = tmp_path / "empty.pdbqt"
        pdbqt.write_text("REMARK test\nEND\n")
        atoms = _parse_pdbqt_atoms(str(pdbqt))
        assert atoms == []

    def test_parse_nonexistent_file(self):
        """Nonexistent file returns empty list."""
        atoms = _parse_pdbqt_atoms("/tmp/nonexistent_test_12345.pdbqt")
        assert atoms == []


class TestExtractPoseAtoms:
    """Tests for _extract_pose_atoms from multi-model PDBQT."""

    def test_extract_first_pose(self, tmp_path, sample_vina_output_pdbqt):
        """Extract atoms from first MODEL."""
        pdbqt = tmp_path / "output.pdbqt"
        pdbqt.write_text(sample_vina_output_pdbqt)

        atoms = _extract_pose_atoms(str(pdbqt), pose_index=0)
        assert len(atoms) >= 1
        assert atoms[0]["name"] == "C1"

    def test_extract_second_pose(self, tmp_path, sample_vina_output_pdbqt):
        """Extract atoms from second MODEL."""
        pdbqt = tmp_path / "output.pdbqt"
        pdbqt.write_text(sample_vina_output_pdbqt)

        atoms = _extract_pose_atoms(str(pdbqt), pose_index=1)
        assert len(atoms) >= 1
        # Second model has coords (2,3,4)
        assert atoms[0]["x"] == pytest.approx(2.0)

    def test_extract_out_of_range_falls_back(self, tmp_path, sample_vina_output_pdbqt):
        """pose_index beyond range defaults to 0."""
        pdbqt = tmp_path / "output.pdbqt"
        pdbqt.write_text(sample_vina_output_pdbqt)

        atoms = _extract_pose_atoms(str(pdbqt), pose_index=99)
        assert len(atoms) >= 1

    def test_extract_single_model(self, tmp_path):
        """Single-model PDBQT (no MODEL lines) still works."""
        content = (
            "ATOM      1  C1  LIG A   1       5.000   6.000   7.000  1.00  0.00     0.000 C\nEND\n"
        )
        pdbqt = tmp_path / "single.pdbqt"
        pdbqt.write_text(content)

        atoms = _extract_pose_atoms(str(pdbqt), pose_index=0)
        assert len(atoms) == 1
        assert atoms[0]["x"] == pytest.approx(5.0)


class TestInteractionAnalysis:
    """Tests for analyze_interactions function."""

    @pytest.fixture
    def hbond_setup(self, tmp_path):
        """Create receptor + ligand PDBQT with H-bond forming atoms."""
        # Receptor: ALA N at (0,0,0)
        receptor = (
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000"
            "  1.00  0.00           N\n"
            "ATOM      2  CA  ALA A   1      10.000  10.000  10.000"
            "  1.00  0.00           C\n"
            "END\n"
        )
        rec_path = tmp_path / "receptor.pdbqt"
        rec_path.write_text(receptor)

        # Ligand: O at (3.0, 0, 0) = 3.0 A from receptor N → H-bond
        ligand = (
            "ATOM      1  O1  LIG A   1       3.000   0.000   0.000  1.00  0.00           O\nEND\n"
        )
        lig_path = tmp_path / "ligand.pdbqt"
        lig_path.write_text(ligand)

        return rec_path, lig_path

    @pytest.fixture
    def vdw_setup(self, tmp_path):
        """Create receptor + ligand with Van der Waals contact."""
        # Receptor: C at (0,0,0)
        receptor = (
            "ATOM      1  CB  ALA A   5       0.000   0.000   0.000  1.00  0.00           C\nEND\n"
        )
        rec_path = tmp_path / "receptor.pdbqt"
        rec_path.write_text(receptor)

        # Ligand: C at (3.8, 0, 0) = 3.8 A → hydrophobic contact
        ligand = (
            "ATOM      1  C1  LIG A   1       3.800   0.000   0.000  1.00  0.00           C\nEND\n"
        )
        lig_path = tmp_path / "ligand.pdbqt"
        lig_path.write_text(ligand)

        return rec_path, lig_path

    def test_hbond_detected(self, hbond_setup):
        """N-O within 3.5 A detected as H-bond."""
        rec, lig = hbond_setup
        report = analyze_interactions(rec, lig)

        assert isinstance(report, InteractionReport)
        assert report.n_hbonds >= 1
        assert len(report.contact_residues) >= 1
        assert "ALA1" in report.contact_residues

    def test_hydrophobic_contact(self, vdw_setup):
        """C-C within 4.0 A detected as hydrophobic."""
        rec, lig = vdw_setup
        report = analyze_interactions(rec, lig)

        assert report.n_hydrophobic >= 1

    def test_no_interactions_far_apart(self, tmp_path):
        """Atoms > 4.0 A apart → no interactions."""
        receptor = (
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\nEND\n"
        )
        ligand = (
            "ATOM      1  O1  LIG A   1      50.000  50.000  50.000  1.00  0.00           O\nEND\n"
        )
        rec = tmp_path / "receptor.pdbqt"
        rec.write_text(receptor)
        lig = tmp_path / "ligand.pdbqt"
        lig.write_text(ligand)

        report = analyze_interactions(rec, lig)
        assert report.n_hbonds == 0
        assert report.n_vdw == 0
        assert report.n_hydrophobic == 0
        assert report.interactions == []

    def test_empty_receptor(self, tmp_path):
        """Missing receptor returns empty report."""
        lig = tmp_path / "ligand.pdbqt"
        lig.write_text("ATOM      1  O1  LIG A 1  3 0 0  1.00 0.00  O\nEND\n")

        report = analyze_interactions(tmp_path / "nonexistent.pdbqt", lig)
        assert report.n_hbonds == 0
        assert report.interactions == []

    def test_report_to_dict(self, hbond_setup):
        """InteractionReport.to_dict() produces valid JSON-serializable dict."""
        rec, lig = hbond_setup
        report = analyze_interactions(rec, lig)

        d = report.to_dict()
        assert "n_hbonds" in d
        assert "n_vdw" in d
        assert "n_hydrophobic" in d
        assert "contact_residues" in d
        assert "interactions" in d
        # Must be JSON-serializable
        json.dumps(d)

    def test_multimodel_pose_selection(self, tmp_path):
        """analyze_interactions with multi-model selects correct pose."""
        receptor = (
            "ATOM      1  N   ALA A   1       1.000   2.000   3.000  1.00  0.00           N\nEND\n"
        )
        rec = tmp_path / "receptor.pdbqt"
        rec.write_text(receptor)

        # Multi-model: pose 0 far away, pose 1 close
        ligand = (
            "MODEL 1\n"
            "REMARK VINA RESULT:    -5.0      0.000      0.000\n"
            "ATOM      1  N1  LIG A   1      50.000  50.000  50.000"
            "  1.00  0.00           N\n"
            "ENDMDL\n"
            "MODEL 2\n"
            "REMARK VINA RESULT:    -7.0      1.000      2.000\n"
            "ATOM      1  N1  LIG A   1       2.000   2.000   3.000"
            "  1.00  0.00           N\n"
            "ENDMDL\n"
        )
        lig = tmp_path / "ligand.pdbqt"
        lig.write_text(ligand)

        # Pose 0 = far → no contacts
        report0 = analyze_interactions(rec, lig, pose_index=0)
        assert report0.n_hbonds == 0

        # Pose 1 = close → contacts
        report1 = analyze_interactions(rec, lig, pose_index=1)
        assert len(report1.interactions) >= 1


class TestInteractionDataClasses:
    """Tests for Interaction and InteractionReport data classes."""

    def test_interaction_creation(self):
        """Create Interaction instance."""
        i = Interaction(
            interaction_type="hbond",
            protein_atom="ALA_A_1_N",
            ligand_atom="O1",
            distance=2.9,
            protein_residue="ALA1",
            protein_element="N",
            ligand_element="O",
        )
        assert i.interaction_type == "hbond"
        assert i.distance == 2.9

    def test_interaction_report_defaults(self):
        """Default InteractionReport has zero counts."""
        r = InteractionReport()
        assert r.n_hbonds == 0
        assert r.n_vdw == 0
        assert r.n_hydrophobic == 0
        assert r.interactions == []
        assert r.contact_residues == []

    def test_interaction_report_to_dict_empty(self):
        """Empty report to_dict."""
        r = InteractionReport()
        d = r.to_dict()
        assert d["n_total"] == 0
        assert d["interactions"] == []


class TestInteractionConstants:
    """Tests for H-bond / VdW distance constants."""

    def test_hbond_distances(self):
        assert HBOND_DISTANCE_MIN < HBOND_DISTANCE_MAX
        assert HBOND_DISTANCE_MIN >= 2.0
        assert HBOND_DISTANCE_MAX <= 4.0

    def test_vdw_distance(self):
        assert VDW_DISTANCE_MAX >= HBOND_DISTANCE_MAX
        assert VDW_DISTANCE_MAX <= 5.0

    def test_retinoic_acid_smiles(self):
        """Retinoic acid SMILES is a valid, non-empty string."""
        assert isinstance(RETINOIC_ACID_SMILES, str)
        assert len(RETINOIC_ACID_SMILES) > 10
        assert "C" in RETINOIC_ACID_SMILES


# ============================================================================
# TEST KNOWN LIGAND VALIDATION (Phase 4.2)
# ============================================================================


class TestValidateKnownLigand:
    """Tests for validate_known_ligand function."""

    @patch("subprocess.run")
    def test_validation_returns_report(
        self, mock_run, tmp_path, sample_pdb_content, sample_vina_stdout
    ):
        """validate_known_ligand returns a complete validation dict."""
        mock_run.return_value = MagicMock(
            stdout=sample_vina_stdout,
            stderr="",
            returncode=0,
        )

        # Create PDB file
        pdb_file = tmp_path / "1cbs.pdb"
        pdb_file.write_text(sample_pdb_content)

        with (
            patch.object(VinaDocking, "_verify_vina"),
            patch.object(
                VinaDocking, "prepare_ligand_from_smiles", return_value=tmp_path / "ligand.pdbqt"
            ),
        ):
            (tmp_path / "ligand.pdbqt").write_text("ATOM dummy")
            report = validate_known_ligand(
                pdb_path=str(pdb_file),
                pocket_center=[1.0, 2.0, 3.0],
                pocket_radius=8.0,
                vina_bin=str(tmp_path / "vina.exe"),
                output_dir=str(tmp_path / "docking"),
                exhaustiveness=4,
            )

        assert "best_affinity" in report
        assert "n_poses" in report
        assert "interactions" in report
        assert "affinity_target_met" in report
        assert report["best_affinity"] == pytest.approx(-7.2)

    @patch("subprocess.run")
    def test_validation_saves_json(
        self, mock_run, tmp_path, sample_pdb_content, sample_vina_stdout
    ):
        """Validation report saved to disk."""
        mock_run.return_value = MagicMock(
            stdout=sample_vina_stdout,
            stderr="",
            returncode=0,
        )

        pdb_file = tmp_path / "test.pdb"
        pdb_file.write_text(sample_pdb_content)

        out_dir = tmp_path / "docking_out"

        with (
            patch.object(VinaDocking, "_verify_vina"),
            patch.object(
                VinaDocking, "prepare_ligand_from_smiles", return_value=tmp_path / "ligand.pdbqt"
            ),
        ):
            (tmp_path / "ligand.pdbqt").write_text("ATOM dummy")
            validate_known_ligand(
                pdb_path=str(pdb_file),
                pocket_center=[0, 0, 0],
                pocket_radius=10.0,
                vina_bin=str(tmp_path / "vina.exe"),
                output_dir=str(out_dir),
                exhaustiveness=4,
            )

        report_path = out_dir / "validation_report.json"
        assert report_path.exists()
        data = json.loads(report_path.read_text())
        assert "best_affinity" in data


# ============================================================================
# TEST NMA FRAME DOCKING (Phase 4.2)
# ============================================================================


class TestDockNMAFrames:
    """Tests for dock_nma_frames function."""

    @pytest.fixture
    def nma_frames_dir(self, tmp_path):
        """Create temporary directory with fake NMA frame PDB files."""
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        pdb_content = (
            "ATOM      1  N   ALA A   1       1.000   2.000   3.000"
            "  1.00  0.00           N\n"
            "ATOM      2  CA  ALA A   1       2.000   3.000   4.000"
            "  1.00  0.00           C\n"
            "END\n"
        )
        for i in range(10):
            (frames_dir / f"frame_{i:03d}.pdb").write_text(pdb_content)
        return frames_dir

    def test_nonexistent_dir(self):
        """Nonexistent frames dir returns error."""
        result = dock_nma_frames(
            frames_dir="/tmp/nonexistent_nma_test_99999",
            pocket={"id": 0, "center": [0, 0, 0], "radius_geom": 5.0},
            ligand_smiles="c1ccccc1",
        )
        assert result["success"] is False
        assert "error" in result

    def test_empty_frames_dir(self, tmp_path):
        """Empty frames dir returns error."""
        empty_dir = tmp_path / "empty_frames"
        empty_dir.mkdir()

        result = dock_nma_frames(
            frames_dir=str(empty_dir),
            pocket={"id": 0, "center": [0, 0, 0], "radius_geom": 5.0},
            ligand_smiles="c1ccccc1",
        )
        assert result["success"] is False

    @patch("subprocess.run")
    def test_nma_docking_sampled(self, mock_run, nma_frames_dir, sample_pocket, sample_vina_stdout):
        """NMA docking samples n_sample frames from directory."""
        mock_run.return_value = MagicMock(
            stdout=sample_vina_stdout,
            stderr="",
            returncode=0,
        )

        with (
            patch.object(VinaDocking, "_verify_vina"),
            patch.object(
                VinaDocking,
                "prepare_ligand_from_smiles",
                return_value=nma_frames_dir.parent / "ligand.pdbqt",
            ),
        ):
            (nma_frames_dir.parent / "ligand.pdbqt").write_text("ATOM dummy")
            report = dock_nma_frames(
                frames_dir=str(nma_frames_dir),
                pocket=sample_pocket,
                ligand_smiles="c1ccccc1",
                n_sample=3,
                vina_bin=str(nma_frames_dir.parent / "vina.exe"),
                output_dir=str(nma_frames_dir.parent / "docking"),
            )

        assert report["success"] is True
        assert report["n_frames_total"] == 10
        assert report["n_frames_docked"] == 3
        assert "consistency" in report
        assert "mean_affinity" in report
        assert "pocket_stable" in report

    @patch("subprocess.run")
    def test_nma_docking_specific_indices(
        self, mock_run, nma_frames_dir, sample_pocket, sample_vina_stdout
    ):
        """NMA docking with explicit frame indices."""
        mock_run.return_value = MagicMock(
            stdout=sample_vina_stdout,
            stderr="",
            returncode=0,
        )

        with (
            patch.object(VinaDocking, "_verify_vina"),
            patch.object(
                VinaDocking,
                "prepare_ligand_from_smiles",
                return_value=nma_frames_dir.parent / "ligand.pdbqt",
            ),
        ):
            (nma_frames_dir.parent / "ligand.pdbqt").write_text("ATOM dummy")
            report = dock_nma_frames(
                frames_dir=str(nma_frames_dir),
                pocket=sample_pocket,
                ligand_smiles="c1ccccc1",
                frame_indices=[0, 4, 9],
                vina_bin=str(nma_frames_dir.parent / "vina.exe"),
                output_dir=str(nma_frames_dir.parent / "docking"),
            )

        assert report["n_frames_docked"] == 3
        assert len(report["frame_results"]) == 3
        # Check frame names match indices
        frames = [r["frame"] for r in report["frame_results"]]
        assert "frame_000" in frames
        assert "frame_004" in frames
        assert "frame_009" in frames

    @patch("subprocess.run")
    def test_nma_report_saved(self, mock_run, nma_frames_dir, sample_pocket, sample_vina_stdout):
        """NMA docking saves JSON report to disk."""
        mock_run.return_value = MagicMock(
            stdout=sample_vina_stdout,
            stderr="",
            returncode=0,
        )

        out_dir = nma_frames_dir.parent / "dock_out"

        with (
            patch.object(VinaDocking, "_verify_vina"),
            patch.object(
                VinaDocking,
                "prepare_ligand_from_smiles",
                return_value=nma_frames_dir.parent / "ligand.pdbqt",
            ),
        ):
            (nma_frames_dir.parent / "ligand.pdbqt").write_text("ATOM dummy")
            dock_nma_frames(
                frames_dir=str(nma_frames_dir),
                pocket=sample_pocket,
                ligand_smiles="c1ccccc1",
                n_sample=2,
                vina_bin=str(nma_frames_dir.parent / "vina.exe"),
                output_dir=str(out_dir),
            )

        report_path = out_dir / "nma_docking_report.json"
        assert report_path.exists()
        data = json.loads(report_path.read_text())
        assert "consistency" in data

    @patch("subprocess.run")
    def test_consistency_calculation(
        self, mock_run, nma_frames_dir, sample_pocket, sample_vina_stdout
    ):
        """Consistency = successful / total docked."""
        mock_run.return_value = MagicMock(
            stdout=sample_vina_stdout,
            stderr="",
            returncode=0,
        )

        with (
            patch.object(VinaDocking, "_verify_vina"),
            patch.object(
                VinaDocking,
                "prepare_ligand_from_smiles",
                return_value=nma_frames_dir.parent / "ligand.pdbqt",
            ),
        ):
            (nma_frames_dir.parent / "ligand.pdbqt").write_text("ATOM dummy")
            report = dock_nma_frames(
                frames_dir=str(nma_frames_dir),
                pocket=sample_pocket,
                ligand_smiles="c1ccccc1",
                n_sample=5,
                vina_bin=str(nma_frames_dir.parent / "vina.exe"),
                output_dir=str(nma_frames_dir.parent / "docking"),
            )

        # All should succeed with mock → consistency = 1.0
        assert report["consistency"] == pytest.approx(1.0)
        assert report["pocket_stable"] is True
