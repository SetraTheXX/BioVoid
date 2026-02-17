from pathlib import Path

import numpy as np
import pytest
import biotite.structure.io.pdb as pdb

from src.frame_reconstruction import reconstruct_all_atom_frame_from_ca
from src.multiframe import analyze_structure_file


TEMPLATE_PDB = Path("data/raw_pdb/1cbs.pdb")
FRAME_PDB = Path("data/frames/1cbs/frame_010.pdb")


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


@pytest.mark.skipif(
    not TEMPLATE_PDB.exists() or not FRAME_PDB.exists(),
    reason="1CBS template/frame data not available",
)
def test_reconstruct_all_atom_frame_preserves_structure_and_moves_atoms(tmp_path):
    out_pdb = tmp_path / "1cbs_reconstructed.pdb"
    stats = reconstruct_all_atom_frame_from_ca(
        template_pdb=TEMPLATE_PDB,
        ca_frame_pdb=FRAME_PDB,
        output_pdb=out_pdb,
    )

    assert out_pdb.exists()
    assert stats.residues_mapped > 0
    assert stats.mapping_coverage > 0.90

    template = pdb.PDBFile.read(str(TEMPLATE_PDB)).get_structure()[0]
    reconstructed = pdb.PDBFile.read(str(out_pdb)).get_structure()[0]
    frame = pdb.PDBFile.read(str(FRAME_PDB)).get_structure()[0]

    assert len(reconstructed) == len(template)

    non_ca = np.where(template.atom_name != "CA")[0]
    assert len(non_ca) > 0
    displacement = np.linalg.norm(
        reconstructed.coord[non_ca] - template.coord[non_ca], axis=1
    )
    assert float(np.max(displacement)) > 0.0

    rec_ca = _ca_map(reconstructed)
    frame_ca = _ca_map(frame)
    shared = sorted(set(rec_ca) & set(frame_ca))
    assert len(shared) > 0
    errors = [
        float(np.linalg.norm(rec_ca[k] - frame_ca[k]))
        for k in shared
    ]
    assert float(np.mean(errors)) < 1e-4


@pytest.mark.skipif(
    not TEMPLATE_PDB.exists() or not FRAME_PDB.exists(),
    reason="1CBS template/frame data not available",
)
def test_reconstructed_frame_runs_heavy_atom_voronoi_pipeline(tmp_path):
    out_pdb = tmp_path / "1cbs_reconstructed.pdb"
    reconstruct_all_atom_frame_from_ca(
        template_pdb=TEMPLATE_PDB,
        ca_frame_pdb=FRAME_PDB,
        output_pdb=out_pdb,
    )

    pockets = analyze_structure_file(out_pdb, profile="default")
    assert isinstance(pockets, list)
    if pockets:
        assert "center" in pockets[0]
        assert "volume" in pockets[0]
