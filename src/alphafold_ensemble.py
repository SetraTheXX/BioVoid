"""
Bio-Void Hunter: AlphaFold Ensemble Generator
================================================

Generates conformational ensembles from AlphaFold predicted structures
and runs BioVoid analysis on each member.

Strategy:
    1. Fetch AlphaFold structure by UniProt ID
    2. Generate NMA-based conformational ensemble with varying amplitudes
    3. Analyze each ensemble member for cryptic pockets
    4. Aggregate consensus pockets across ensemble

This mimics the Meller et al. (2023) approach of using AlphaFold
to pre-sample cryptic pocket conformations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import PIPELINE

logger = logging.getLogger(__name__)


@dataclass
class EnsembleConfig:
    """Configuration for ensemble generation.

    Uses 3 amplitude levels (2.0, 3.0, 5.0) by default for better
    multi-amplitude sampling across conformational space.
    """

    n_modes: int = 10
    n_frames_per_amplitude: int = 10
    amplitudes: tuple[float, ...] = (2.0, 3.0, 5.0)
    profile: str = "default"
    consensus_min_support: int = 3
    cluster_distance: float = 4.0

    @property
    def total_frames(self) -> int:
        return self.n_frames_per_amplitude * len(self.amplitudes)


def fetch_alphafold_structure(uniprot_id: str) -> Path:
    """Download AlphaFold predicted structure."""
    from .fetcher import fetch_pdb

    return fetch_pdb(uniprot_id, source="alphafold")


def generate_ensemble(
    pdb_path: str | Path,
    config: EnsembleConfig = EnsembleConfig(),
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Generate conformational ensemble from a single structure using NMA.

    Varies amplitude across normal modes to explore different
    conformational states, simulating AlphaFold-like ensemble diversity.
    """
    from .dynamics import run_nma_simulation

    pdb_path = str(pdb_path)
    if output_dir is None:
        output_dir = Path(pdb_path).parent / "ensemble"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_frame_dirs: list[str] = []
    amplitude_metadata: list[dict[str, Any]] = []

    for amp_idx, amplitude in enumerate(config.amplitudes):
        amp_dir = output_dir / f"amp_{amp_idx:02d}_{amplitude:.1f}"

        try:
            result = run_nma_simulation(
                pdb_path=pdb_path,
                n_modes=config.n_modes,
                n_frames=config.n_frames_per_amplitude,
                output_dir=str(amp_dir),
            )
            all_frame_dirs.append(result["output_dir"])
            amplitude_metadata.append(
                {
                    "amplitude_index": amp_idx,
                    "amplitude": amplitude,
                    "n_frames": config.n_frames_per_amplitude,
                    "output_dir": result["output_dir"],
                    "n_atoms": result.get("n_atoms", 0),
                }
            )
            logger.info(
                "Ensemble amplitude %.1f: %d frames generated",
                amplitude,
                config.n_frames_per_amplitude,
            )
        except Exception as e:
            logger.warning("Ensemble amplitude %.1f failed: %s", amplitude, e)
            amplitude_metadata.append(
                {
                    "amplitude_index": amp_idx,
                    "amplitude": amplitude,
                    "error": str(e),
                }
            )

    return {
        "source_pdb": pdb_path,
        "output_dir": str(output_dir),
        "total_amplitudes": len(config.amplitudes),
        "successful_amplitudes": len(all_frame_dirs),
        "total_frames": sum(m.get("n_frames", 0) for m in amplitude_metadata if "error" not in m),
        "frame_dirs": all_frame_dirs,
        "amplitude_metadata": amplitude_metadata,
    }


def analyze_ensemble(
    ensemble_result: dict[str, Any],
    config: EnsembleConfig = EnsembleConfig(),
) -> dict[str, Any]:
    """
    Run BioVoid cavity analysis on all ensemble members across all
    amplitude levels and aggregate results into a single consensus.

    Frames from all amplitudes (e.g. 2.0, 3.0, 5.0) are pooled,
    clustered by pocket center, and merged into consensus pockets
    with min_support_frames threshold.
    """
    from .multiframe import (
        ConsensusConfig,
        aggregate_consensus_pockets,
        analyze_pocket_persistence,
        analyze_structure_file,
        list_frame_files,
    )

    all_pockets: list[list[dict[str, Any]]] = []
    all_labels: list[str] = []
    frame_stats: list[dict[str, Any]] = []

    for frame_dir in ensemble_result.get("frame_dirs", []):
        frame_files = list_frame_files(frame_dir)
        for frame_file in frame_files:
            try:
                pockets = analyze_structure_file(frame_file, profile=config.profile)
                all_pockets.append(pockets)
                all_labels.append(frame_file.name)
                frame_stats.append(
                    {
                        "frame": frame_file.name,
                        "dir": frame_dir,
                        "n_pockets": len(pockets),
                        "n_druggable": sum(1 for p in pockets if p.get("druggable", False)),
                    }
                )
            except Exception as e:
                logger.warning("Frame analysis failed for %s: %s", frame_file, e)

    if not all_pockets:
        return {
            "consensus_pockets": [],
            "consensus_stats": {},
            "frame_stats": frame_stats,
            "total_frames_analyzed": 0,
        }

    consensus_config = ConsensusConfig(
        profile=config.profile,
        per_frame_top_n=20,
        min_support_frames=config.consensus_min_support,
        cluster_distance=config.cluster_distance,
    )

    consensus_pockets, consensus_stats = aggregate_consensus_pockets(
        per_frame_pockets=all_pockets,
        frame_labels=all_labels,
        config=consensus_config,
    )

    persistence = {}
    if consensus_pockets and all_labels:
        persistence = analyze_pocket_persistence(consensus_pockets, all_labels)

    return {
        "consensus_pockets": consensus_pockets,
        "consensus_stats": consensus_stats,
        "persistence": persistence,
        "frame_stats": frame_stats,
        "total_frames_analyzed": len(all_pockets),
        "total_consensus_pockets": len(consensus_pockets),
    }


def run_alphafold_ensemble_pipeline(
    uniprot_id: str,
    config: EnsembleConfig | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Complete AlphaFold ensemble pipeline:
    1. Fetch AlphaFold structure
    2. Generate NMA ensemble with 3 amplitude levels (2.0, 3.0, 5.0)
    3. Analyze all ensemble members across all amplitudes
    4. Aggregate results from all amplitudes into a single consensus
    5. Return consensus pockets with persistence data
    """
    if config is None:
        config = EnsembleConfig(amplitudes=PIPELINE.alphafold_amplitudes)

    logger.info("AlphaFold ensemble pipeline for %s", uniprot_id)

    pdb_path = fetch_alphafold_structure(uniprot_id)
    logger.info("AlphaFold structure: %s", pdb_path)

    if output_dir is None:
        output_dir = Path("data/alphafold_ensemble") / uniprot_id.upper()

    ensemble = generate_ensemble(pdb_path, config, output_dir)
    logger.info(
        "Ensemble: %d frames across %d amplitudes",
        ensemble["total_frames"],
        ensemble["successful_amplitudes"],
    )

    analysis = analyze_ensemble(ensemble, config)
    logger.info(
        "Analysis: %d consensus pockets from %d frames",
        analysis["total_consensus_pockets"],
        analysis["total_frames_analyzed"],
    )

    return {
        "uniprot_id": uniprot_id.upper(),
        "alphafold_pdb": str(pdb_path),
        "ensemble": ensemble,
        "analysis": analysis,
        "config": {
            "n_modes": config.n_modes,
            "amplitudes": list(config.amplitudes),
            "n_frames_per_amplitude": config.n_frames_per_amplitude,
            "total_frames": config.total_frames,
            "profile": config.profile,
        },
    }
