from pathlib import Path

import biotite.structure.io.pdb as pdb
import numpy as np
import pytest

pytestmark = pytest.mark.scientific

from src.frame_reconstruction import reconstruct_all_atom_frame_from_ca
from src.multiframe import analyze_structure_file


def _pdb_line(
    serial: int,
    atom_name: str,
    residue_id: int,
    coordinate: np.ndarray,
) -> str:
    element = atom_name[0]
    return (
        f"ATOM  {serial:5d} {atom_name:^4s} ALA A{residue_id:4d}    "
        f"{coordinate[0]:8.3f}{coordinate[1]:8.3f}{coordinate[2]:8.3f}"
        f"  1.00 20.00          {element:>2s}\n"
    )


def _write_hermetic_reconstruction_fixture(tmp_path: Path) -> tuple[Path, Path]:
    template_path = tmp_path / "template.pdb"
    frame_path = tmp_path / "ca_frame.pdb"
    template_lines: list[str] = []
    frame_lines: list[str] = []
    serial = 1
    frame_serial = 1
    translation = np.asarray([0.20, 0.10, -0.10])
    offsets = {
        "N": np.asarray([-1.10, -0.20, 0.00]),
        "CA": np.asarray([0.00, 0.00, 0.00]),
        "C": np.asarray([1.20, 0.10, 0.00]),
        "O": np.asarray([1.80, 0.80, 0.10]),
        "CB": np.asarray([-0.10, 1.40, 0.80]),
    }
    for residue_id in range(1, 16):
        angle = residue_id * 1.17
        ca = np.asarray(
            [
                7.0 * np.cos(angle),
                7.0 * np.sin(angle),
                1.35 * residue_id,
            ]
        )
        for atom_name, offset in offsets.items():
            template_lines.append(_pdb_line(serial, atom_name, residue_id, ca + offset))
            serial += 1
        frame_lines.append(_pdb_line(frame_serial, "CA", residue_id, ca + translation))
        frame_serial += 1
    template_path.write_text("".join(template_lines) + "END\n", encoding="ascii")
    frame_path.write_text("".join(frame_lines) + "END\n", encoding="ascii")
    return template_path, frame_path


def _residue_key(structure, idx: int) -> tuple[str, int, str, str]:
    ins_code = ""
    if hasattr(structure, "ins_code"):
        ins_code = str(structure.ins_code[idx]).strip()
    return (
        str(structure.chain_id[idx]),
        int(structure.res_id[idx]),
        ins_code,
        str(structure.res_name[idx]),
    )


def _ca_map(structure):
    out = {}
    ca_idx = np.where(structure.atom_name == "CA")[0]
    for i in ca_idx:
        key = _residue_key(structure, int(i))
        out[key] = np.asarray(structure.coord[int(i)], dtype=float)
    return out


def test_reconstruct_all_atom_frame_preserves_structure_and_moves_atoms(tmp_path):
    template_pdb, frame_pdb = _write_hermetic_reconstruction_fixture(tmp_path)
    out_pdb = tmp_path / "reconstructed.pdb"
    stats = reconstruct_all_atom_frame_from_ca(
        template_pdb=template_pdb,
        ca_frame_pdb=frame_pdb,
        output_pdb=out_pdb,
    )

    assert out_pdb.exists()
    assert stats.residues_mapped == stats.residues_total == 15
    assert stats.mapping_coverage == 1.0

    template = pdb.PDBFile.read(str(template_pdb)).get_structure()[0]
    reconstructed = pdb.PDBFile.read(str(out_pdb)).get_structure()[0]
    frame = pdb.PDBFile.read(str(frame_pdb)).get_structure()[0]

    assert len(reconstructed) == len(template)

    non_ca = np.where(template.atom_name != "CA")[0]
    displacement = np.linalg.norm(
        reconstructed.coord[non_ca] - template.coord[non_ca],
        axis=1,
    )
    assert float(np.max(displacement)) > 0.0

    rec_ca = _ca_map(reconstructed)
    frame_ca = _ca_map(frame)
    shared = sorted(set(rec_ca) & set(frame_ca))
    assert len(shared) == 15
    errors = [float(np.linalg.norm(rec_ca[key] - frame_ca[key])) for key in shared]
    assert float(np.mean(errors)) < 1e-4


def test_reconstructed_frame_runs_heavy_atom_voronoi_pipeline(tmp_path):
    template_pdb, frame_pdb = _write_hermetic_reconstruction_fixture(tmp_path)
    out_pdb = tmp_path / "reconstructed.pdb"
    reconstruct_all_atom_frame_from_ca(
        template_pdb=template_pdb,
        ca_frame_pdb=frame_pdb,
        output_pdb=out_pdb,
    )

    pockets = analyze_structure_file(out_pdb, profile="default")
    assert isinstance(pockets, list)
    if pockets:
        assert "center" in pockets[0]
        assert "volume" in pockets[0]
