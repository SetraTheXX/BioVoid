"""
Bio-Void Hunter: Frame Reconstruction Utilities
===============================================

P1.1.3 support utilities for reconstructing all-atom/heavy-atom structures
from CA-only NMA frames.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import biotite.structure.io.pdb as pdb


@dataclass(frozen=True)
class ReconstructionStats:
    """Quality metrics for CA->all-atom frame reconstruction."""

    atoms_total: int
    residues_total: int
    residues_mapped: int
    mapping_coverage: float
    mean_ca_displacement: float
    max_ca_displacement: float


def _load_first_model(pdb_file: str | Path):
    """Load first model from PDB as AtomArray."""
    path = Path(pdb_file)
    if not path.exists():
        raise FileNotFoundError(f"PDB file not found: {path}")
    pdb_obj = pdb.PDBFile.read(str(path))
    return pdb_obj.get_structure()[0]


def _residue_key(structure, atom_index: int) -> tuple[str, int, str, str]:
    """Stable residue identity key for coordinate mapping."""
    chain_id = str(structure.chain_id[atom_index])
    res_id = int(structure.res_id[atom_index])
    ins_code = ""
    if hasattr(structure, "ins_code"):
        ins_code = str(structure.ins_code[atom_index]).strip()
    res_name = str(structure.res_name[atom_index])
    return (chain_id, res_id, ins_code, res_name)


def _extract_ca_map(structure) -> dict[tuple[str, int, str, str], np.ndarray]:
    """Map residue key -> CA coordinates."""
    ca_indices = np.where(structure.atom_name == "CA")[0]
    ca_map: dict[tuple[str, int, str, str], np.ndarray] = {}
    for idx in ca_indices:
        key = _residue_key(structure, int(idx))
        if key in ca_map:
            continue
        ca_map[key] = np.asarray(structure.coord[int(idx)], dtype=float)
    return ca_map


def reconstruct_all_atom_frame_from_ca(
    template_pdb: str | Path,
    ca_frame_pdb: str | Path,
    output_pdb: str | Path,
) -> ReconstructionStats:
    """
    Reconstruct an all-atom frame by transferring CA displacements per residue.

    Args:
        template_pdb: Original full-atom protein structure.
        ca_frame_pdb: CA-only NMA frame.
        output_pdb: Destination PDB path for reconstructed structure.

    Returns:
        ReconstructionStats for mapping quality.
    """
    template = _load_first_model(template_pdb)
    frame_ca = _load_first_model(ca_frame_pdb)

    template_ca_map = _extract_ca_map(template)
    frame_ca_map = _extract_ca_map(frame_ca)
    if not template_ca_map:
        raise ValueError("Template structure has no CA atoms.")
    if not frame_ca_map:
        raise ValueError("CA frame has no CA atoms.")

    displacement_map: dict[tuple[str, int, str, str], np.ndarray] = {}
    displacement_norms: list[float] = []
    for key, base_coord in template_ca_map.items():
        if key not in frame_ca_map:
            continue
        disp = np.asarray(frame_ca_map[key] - base_coord, dtype=float)
        displacement_map[key] = disp
        displacement_norms.append(float(np.linalg.norm(disp)))

    reconstructed = template.copy()
    for idx in range(len(reconstructed)):
        key = _residue_key(reconstructed, int(idx))
        if key in displacement_map:
            reconstructed.coord[int(idx)] = (
                reconstructed.coord[int(idx)] + displacement_map[key]
            )

    output_path = Path(output_pdb)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out = pdb.PDBFile()
    out.set_structure(reconstructed)
    out.write(str(output_path))

    residues_total = len(template_ca_map)
    residues_mapped = len(displacement_map)
    coverage = residues_mapped / max(1, residues_total)
    mean_disp = float(np.mean(displacement_norms)) if displacement_norms else 0.0
    max_disp = float(np.max(displacement_norms)) if displacement_norms else 0.0

    return ReconstructionStats(
        atoms_total=int(len(reconstructed)),
        residues_total=int(residues_total),
        residues_mapped=int(residues_mapped),
        mapping_coverage=float(round(coverage, 6)),
        mean_ca_displacement=float(round(mean_disp, 6)),
        max_ca_displacement=float(round(max_disp, 6)),
    )


def stats_to_dict(stats: ReconstructionStats) -> dict[str, Any]:
    """Serialize ReconstructionStats for logs/report payloads."""
    return {
        "atoms_total": stats.atoms_total,
        "residues_total": stats.residues_total,
        "residues_mapped": stats.residues_mapped,
        "mapping_coverage": stats.mapping_coverage,
        "mean_ca_displacement": stats.mean_ca_displacement,
        "max_ca_displacement": stats.max_ca_displacement,
    }
