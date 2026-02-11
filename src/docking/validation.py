"""
Bio-Void Hunter: Docking Validation
=====================================

Validation utilities for known ligand redocking
and NMA frame docking consistency.

Extracted from docker.py during Faz 6 pre-refactoring.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .vina_wrapper import (
    VinaDocking,
    DEFAULT_EXHAUSTIVENESS,
    AFFINITY_GOOD,
)
from .interactions import InteractionReport, analyze_interactions

logger = logging.getLogger(__name__)

# 1CBS: Cellular Retinoic Acid Binding Protein + Retinoic Acid
RETINOIC_ACID_SMILES = 'CC1=C(C(CCC1)(C)C)/C=C/C(=C/C=C/C(=C/C(=O)O)/C)/C'

# Known 1CBS binding site center (approximate from crystal structure)
CBS_KNOWN_CENTER = [20.0, 28.0, 12.0]
CBS_KNOWN_RADIUS = 9.0


def validate_known_ligand(pdb_path: str,
                          ligand_smiles: str = RETINOIC_ACID_SMILES,
                          pocket_center: Optional[List[float]] = None,
                          pocket_radius: Optional[float] = None,
                          vina_bin: str = 'tools/vina/vina.exe',
                          output_dir: str = 'data/docking',
                          exhaustiveness: int = 16,
                          ) -> Dict[str, Any]:
    """
    Validate docking accuracy using a known protein-ligand complex.

    Docks the known ligand back into its binding site and measures:
    - Binding affinity (target: < -6.0 kcal/mol)
    - Success of redocking (poses found)
    - Interaction analysis

    Args:
        pdb_path: Path to protein PDB file
        ligand_smiles: SMILES of known ligand
        pocket_center: Known binding site center [x, y, z]
        pocket_radius: Known binding site radius
        vina_bin: Path to Vina binary
        output_dir: Output directory
        exhaustiveness: Search thoroughness (higher for validation)

    Returns:
        Validation report dict
    """
    if pocket_center is None:
        pocket_center = CBS_KNOWN_CENTER
    if pocket_radius is None:
        pocket_radius = CBS_KNOWN_RADIUS

    docker = VinaDocking(
        vina_bin=vina_bin,
        output_dir=output_dir,
        exhaustiveness=exhaustiveness,
    )

    known_pocket = {
        'id': 0,
        'rank': 0,
        'center': pocket_center,
        'radius_geom': pocket_radius,
    }

    receptor_pdbqt = docker.prepare_receptor(pdb_path)

    result = docker.dock_pocket(
        known_pocket, receptor_pdbqt,
        ligand_smiles=ligand_smiles,
        ligand_name='known_ligand',
    )

    interaction_report = InteractionReport()
    docked_output = docker.output_dir / "pocket0_known_ligand_out.pdbqt"
    if docked_output.exists():
        interaction_report = analyze_interactions(
            receptor_pdbqt, docked_output, pose_index=0
        )

    validation = {
        'protein': str(pdb_path),
        'ligand_smiles': ligand_smiles,
        'grid_box': result.grid_box,
        'best_affinity': result.best_affinity,
        'affinity_class': result.affinity_class,
        'is_druggable': result.is_druggable,
        'n_poses': len(result.poses),
        'success': result.success,
        'error': result.error,
        'affinity_target_met': result.best_affinity < AFFINITY_GOOD,
        'interactions': interaction_report.to_dict(),
        'poses': [asdict(p) for p in result.poses],
    }

    report_path = Path(output_dir) / 'validation_report.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w') as f:
        json.dump(validation, f, indent=2, default=str)

    logger.info(
        f"Validation: affinity={result.best_affinity:.1f} kcal/mol, "
        f"druggable={result.is_druggable}, "
        f"H-bonds={interaction_report.n_hbonds}, "
        f"contacts={len(interaction_report.contact_residues)}"
    )

    return validation


def dock_nma_frames(frames_dir: str,
                    pocket: Dict[str, Any],
                    ligand_smiles: str,
                    ligand_name: str = 'probe',
                    frame_indices: Optional[List[int]] = None,
                    n_sample: int = 5,
                    vina_bin: str = 'tools/vina/vina.exe',
                    output_dir: str = 'data/docking',
                    exhaustiveness: int = DEFAULT_EXHAUSTIVENESS,
                    ) -> Dict[str, Any]:
    """
    Dock a ligand across multiple NMA conformational frames.

    Validates that cryptic pockets remain accessible across the
    conformational ensemble, and checks docking consistency.

    Args:
        frames_dir: Directory with NMA frame PDB files (frame_XXX.pdb)
        pocket: Cavity dict with center and radius
        ligand_smiles: SMILES of ligand to dock
        ligand_name: Human-readable name
        frame_indices: Specific frame indices to dock
        n_sample: Number of frames to sample
        vina_bin: Path to Vina binary
        output_dir: Output directory
        exhaustiveness: Search thoroughness

    Returns:
        NMA docking report dict
    """
    frames_path = Path(frames_dir)
    if not frames_path.exists():
        return {'error': f"Frames directory not found: {frames_dir}",
                'success': False}

    frame_files = sorted(frames_path.glob('frame_*.pdb'))
    if not frame_files:
        return {'error': f"No frame_*.pdb files in {frames_dir}",
                'success': False}

    if frame_indices is None:
        total = len(frame_files)
        if total <= n_sample:
            selected = list(range(total))
        else:
            selected = [int(i * (total - 1) / (n_sample - 1))
                        for i in range(n_sample)]
    else:
        selected = [i for i in frame_indices if i < len(frame_files)]

    docker = VinaDocking(
        vina_bin=vina_bin,
        output_dir=output_dir,
        exhaustiveness=exhaustiveness,
    )

    frame_results: List[Dict[str, Any]] = []
    affinities: List[float] = []
    n_success = 0

    for idx in selected:
        frame_file = frame_files[idx]
        frame_name = frame_file.stem

        logger.info(f"NMA docking: {frame_name}")

        try:
            receptor_pdbqt = docker.prepare_receptor(
                str(frame_file),
                output_path=str(
                    docker.output_dir / f"{frame_name}_receptor.pdbqt"
                ),
            )

            result = docker.dock_pocket(
                pocket, receptor_pdbqt,
                ligand_smiles=ligand_smiles,
                ligand_name=f"{ligand_name}_{frame_name}",
            )

            frame_result = {
                'frame': frame_name,
                'frame_index': idx,
                'affinity': result.best_affinity,
                'n_poses': len(result.poses),
                'success': result.success,
                'error': result.error,
            }
            frame_results.append(frame_result)

            if result.success:
                n_success += 1
                affinities.append(result.best_affinity)

        except Exception as e:
            frame_results.append({
                'frame': frame_name,
                'frame_index': idx,
                'success': False,
                'error': str(e),
            })

    consistency = n_success / len(selected) if selected else 0.0
    mean_affinity = float(np.mean(affinities)) if affinities else 0.0
    std_affinity = float(np.std(affinities)) if len(affinities) > 1 else 0.0

    nma_report = {
        'frames_dir': str(frames_dir),
        'pocket_id': pocket.get('id', 0),
        'ligand_smiles': ligand_smiles,
        'n_frames_total': len(frame_files),
        'n_frames_docked': len(selected),
        'n_successful': n_success,
        'consistency': round(consistency, 3),
        'mean_affinity': round(mean_affinity, 2),
        'std_affinity': round(std_affinity, 2),
        'pocket_stable': consistency >= 0.6,
        'frame_results': frame_results,
        'success': True,
    }

    report_path = Path(output_dir) / 'nma_docking_report.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w') as f:
        json.dump(nma_report, f, indent=2, default=str)

    logger.info(
        f"NMA docking: {n_success}/{len(selected)} frames successful, "
        f"consistency={consistency:.0%}, "
        f"mean_affinity={mean_affinity:.1f} +/- {std_affinity:.1f}"
    )

    return nma_report
