"""
Bio-Void Hunter: Interaction Analysis
=======================================

Distance-based protein-ligand interaction detection.
H-bonds, VdW contacts, hydrophobic interactions.

Extracted from docker.py during Faz 6 pre-refactoring.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

# H-bond criteria (distance-based, no PLIP dependency)
HBOND_DISTANCE_MAX = 3.5
HBOND_DISTANCE_MIN = 2.5
VDW_DISTANCE_MAX = 4.0

HBOND_DONORS = {'N', 'O', 'S'}
HBOND_ACCEPTORS = {'N', 'O', 'S', 'F'}


@dataclass
class Interaction:
    """Single protein-ligand interaction."""
    interaction_type: str
    protein_atom: str
    ligand_atom: str
    distance: float
    protein_residue: str
    protein_element: str
    ligand_element: str


@dataclass
class InteractionReport:
    """Complete interaction analysis for a docking result."""
    n_hbonds: int = 0
    n_vdw: int = 0
    n_hydrophobic: int = 0
    interactions: List[Interaction] = field(default_factory=list)
    contact_residues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'n_hbonds': self.n_hbonds,
            'n_vdw': self.n_vdw,
            'n_hydrophobic': self.n_hydrophobic,
            'n_total': len(self.interactions),
            'contact_residues': self.contact_residues,
            'interactions': [
                {
                    'type': i.interaction_type,
                    'protein_atom': i.protein_atom,
                    'ligand_atom': i.ligand_atom,
                    'distance': round(i.distance, 2),
                    'residue': i.protein_residue,
                }
                for i in self.interactions
            ],
        }


def _parse_pdbqt_atoms(pdbqt_path: str | Path) -> List[Dict[str, Any]]:
    """
    Extract atom coordinates and metadata from a PDBQT file.

    Returns list of dicts with keys:
        serial, name, resName, chainID, resSeq, x, y, z, element
    """
    path = Path(pdbqt_path)
    if not path.exists():
        return []

    atoms = []
    for line in path.read_text().splitlines():
        if not (line.startswith('ATOM') or line.startswith('HETATM')):
            continue
        try:
            atom = {
                'serial': int(line[6:11].strip()),
                'name': line[12:16].strip(),
                'resName': line[17:20].strip(),
                'chainID': line[21:22].strip() or 'A',
                'resSeq': int(line[22:26].strip()),
                'x': float(line[30:38].strip()),
                'y': float(line[38:46].strip()),
                'z': float(line[46:54].strip()),
            }
            if len(line) >= 78:
                atom['element'] = line[77:79].strip().upper()
            elif len(line) >= 77:
                atom['element'] = line[76:78].strip().upper()
            else:
                atom['element'] = atom['name'][0].upper()
            atoms.append(atom)
        except (ValueError, IndexError):
            continue

    return atoms


def _extract_pose_atoms(pdbqt_path: str | Path,
                        pose_index: int = 0) -> List[Dict[str, Any]]:
    """Extract atoms from a specific MODEL in a multi-model PDBQT."""
    path = Path(pdbqt_path)
    if not path.exists():
        return []

    content = path.read_text()

    models = re.split(r'MODEL\s+\d+', content)
    models = [m for m in models if 'ATOM' in m or 'HETATM' in m]

    if not models:
        return _parse_pdbqt_atoms(pdbqt_path)

    if pose_index >= len(models):
        pose_index = 0

    with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt',
                                     delete=False) as f:
        f.write(models[pose_index])
        tmp_path = f.name

    try:
        atoms = _parse_pdbqt_atoms(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return atoms


def analyze_interactions(receptor_pdbqt: str | Path,
                         docked_ligand_pdbqt: str | Path,
                         pose_index: int = 0) -> InteractionReport:
    """
    Analyze protein-ligand interactions from docked output.

    Distance-based detection (no PLIP dependency):
    - H-bonds: donor/acceptor atoms within 2.5-3.5 Angstrom
    - VdW contacts: non-bonded atoms within 4.0 Angstrom
    - Hydrophobic: carbon-carbon contacts within 4.0 Angstrom

    Args:
        receptor_pdbqt: Path to receptor PDBQT
        docked_ligand_pdbqt: Path to Vina output PDBQT
        pose_index: Which pose to analyze (0 = best)

    Returns:
        InteractionReport with classified interactions
    """
    rec_atoms = _parse_pdbqt_atoms(receptor_pdbqt)
    lig_atoms = _extract_pose_atoms(docked_ligand_pdbqt, pose_index)

    if not rec_atoms or not lig_atoms:
        return InteractionReport()

    rec_coords = np.array([[a['x'], a['y'], a['z']] for a in rec_atoms])
    lig_coords = np.array([[a['x'], a['y'], a['z']] for a in lig_atoms])

    interactions: List[Interaction] = []
    contact_residues_set: set[str] = set()

    for li, latom in enumerate(lig_atoms):
        lcoord = lig_coords[li]
        dists = np.linalg.norm(rec_coords - lcoord, axis=1)

        for ri in np.where(dists < VDW_DISTANCE_MAX)[0]:
            ratom = rec_atoms[ri]
            dist = float(dists[ri])

            r_elem = ratom['element']
            l_elem = latom['element']
            residue_label = f"{ratom['resName']}{ratom['resSeq']}"
            protein_label = (
                f"{ratom['resName']}_{ratom['chainID']}_"
                f"{ratom['resSeq']}_{ratom['name']}"
            )

            if (HBOND_DISTANCE_MIN <= dist <= HBOND_DISTANCE_MAX
                    and (r_elem in HBOND_DONORS or r_elem in HBOND_ACCEPTORS)
                    and (l_elem in HBOND_DONORS or l_elem in HBOND_ACCEPTORS)):
                itype = 'hbond'
            elif r_elem == 'C' and l_elem == 'C' and dist <= VDW_DISTANCE_MAX:
                itype = 'hydrophobic'
            else:
                itype = 'vdw'

            interactions.append(Interaction(
                interaction_type=itype,
                protein_atom=protein_label,
                ligand_atom=latom['name'],
                distance=dist,
                protein_residue=residue_label,
                protein_element=r_elem,
                ligand_element=l_elem,
            ))
            contact_residues_set.add(residue_label)

    n_hbonds = sum(1 for i in interactions if i.interaction_type == 'hbond')
    n_vdw = sum(1 for i in interactions if i.interaction_type == 'vdw')
    n_hydro = sum(1 for i in interactions if i.interaction_type == 'hydrophobic')

    return InteractionReport(
        n_hbonds=n_hbonds,
        n_vdw=n_vdw,
        n_hydrophobic=n_hydro,
        interactions=interactions,
        contact_residues=sorted(contact_residues_set),
    )
