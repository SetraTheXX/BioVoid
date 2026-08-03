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
import hashlib
import json

from .config import PIPELINE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnsembleConfig:
    """Configuration for ensemble generation.

    Uses 3 amplitude levels (2.0, 3.0, 5.0) by default for better
    multi-amplitude sampling across conformational space.
    """

    n_modes: int = 10
    n_frames_per_amplitude: int = 4
    amplitudes: tuple[float, ...] = (2.0, 3.0, 5.0)
    profile: str = "default"
    consensus_min_support: int = 3
    cluster_distance: float = 4.0

    @property
    def total_samples(self) -> int:
        return self.n_modes * self.n_frames_per_amplitude * len(self.amplitudes)

    @property
    def total_frames(self) -> int:
        """Legacy alias retained for API compatibility."""
        return self.total_samples


def fetch_alphafold_structure(uniprot_id: str) -> Path:
    """Download AlphaFold predicted structure."""
    from .fetcher import fetch_pdb

    return fetch_pdb(uniprot_id, source="alphafold")


def generate_ensemble(
    pdb_path: str | Path,
    config: EnsembleConfig | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Generate conformational ensemble from a single structure using NMA.

    Varies amplitude across normal modes to explore different
    conformational states, simulating AlphaFold-like ensemble diversity.
    """
    from .motion_ensemble import MotionEnsembleConfig, generate_validated_motion_ensemble
    from .resources import get_available_memory_bytes

    config = config or EnsembleConfig()
    pdb_path = str(pdb_path)
    if output_dir is None:
        output_dir = Path(pdb_path).parent / "ensemble"
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"AlphaFold motion output directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    all_frame_dirs: list[str] = []
    amplitude_metadata: list[dict[str, Any]] = []

    for amp_idx, amplitude in enumerate(config.amplitudes):
        amp_dir = output_dir / f"amp_{amp_idx:02d}_{amplitude:.1f}"

        try:
            result = generate_validated_motion_ensemble(
                pdb_path,
                amp_dir,
                MotionEnsembleConfig(
                    n_modes=config.n_modes,
                    samples_per_mode=config.n_frames_per_amplitude,
                    maximum_amplitude=amplitude,
                ),
                available_memory_bytes=get_available_memory_bytes(),
            )
            accepted_dir = result.output_dir / "accepted_frames"
            all_frame_dirs.append(str(accepted_dir))
            amplitude_metadata.append(
                {
                    "amplitude_index": amp_idx,
                    "amplitude": amplitude,
                    "mode_count": config.n_modes,
                    "samples_per_mode": config.n_frames_per_amplitude,
                    "total_samples": len(result.samples),
                    "accepted_samples": len(result.accepted_sample_ids),
                    "output_dir": str(accepted_dir),
                    "manifest": str(result.manifest_path),
                }
            )
            logger.info(
                "Ensemble amplitude %.1f: %d/%d full-atom samples accepted",
                amplitude,
                len(result.accepted_sample_ids),
                len(result.samples),
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
        "total_samples": sum(
            m.get("total_samples", 0) for m in amplitude_metadata if "error" not in m
        ),
        "accepted_samples": sum(
            m.get("accepted_samples", 0) for m in amplitude_metadata if "error" not in m
        ),
        "total_frames": sum(
            m.get("accepted_samples", 0) for m in amplitude_metadata if "error" not in m
        ),
        "frame_dirs": all_frame_dirs,
        "amplitude_metadata": amplitude_metadata,
        "status": "experimental",
        "canonical_ranking_affected": False,
    }


def analyze_ensemble(
    ensemble_result: dict[str, Any],
    config: EnsembleConfig | None = None,
) -> dict[str, Any]:
    """
    Run BioVoid cavity analysis on all ensemble members across all
    amplitude levels and aggregate results into a single consensus.

    Accepted samples from all amplitudes are pooled and aggregated with mode
    boundaries intact.
    """
    from .motion_ensemble import aggregate_motion_pockets
    from .static_detector import detect_static_pockets

    config = config or EnsembleConfig()
    observations: list[dict[str, Any]] = []
    accepted_samples: list[dict[str, Any]] = []
    frame_stats: list[dict[str, Any]] = []
    frame_errors: list[dict[str, str]] = []
    source_hash = hashlib.sha256(Path(ensemble_result["source_pdb"]).read_bytes()).hexdigest()

    for amplitude in ensemble_result.get("amplitude_metadata", []):
        if "error" in amplitude:
            continue
        manifest = json.loads(Path(amplitude["manifest"]).read_text(encoding="utf-8"))
        manifest_samples = list(manifest["samples"])
        samples = {
            sample["sample_id"]: sample
            for sample in manifest_samples
            if sample["quality_status"] == "ACCEPTED"
        }
        accepted_samples.extend(manifest_samples)
        manifest_root = Path(amplitude["manifest"]).parent
        accepted_frame_files = [
            manifest_root / sample["frame_file"]
            for sample in manifest_samples
            if sample["used_for_pocket_detection"] and sample["frame_file"]
        ]
        for frame_file in accepted_frame_files:
            try:
                sample_id = frame_file.stem.removeprefix("frame_")
                detection = detect_static_pockets(frame_file, prepared_sha256=source_hash)
                pockets = [pocket.to_portable_dict() for pocket in detection.pockets]
                observations.append({"sample": samples[sample_id], "pockets": pockets})
                frame_stats.append(
                    {
                        "frame": frame_file.name,
                        "dir": str(frame_file.parent),
                        "n_pockets": len(pockets),
                        "sample_id": sample_id,
                    }
                )
            except Exception as e:
                logger.warning("Frame analysis failed for %s: %s", frame_file, e)
                frame_errors.append({"frame": str(frame_file), "error": str(e)})

    if not observations:
        return {
            "consensus_pockets": [],
            "consensus_stats": {},
            "frame_stats": frame_stats,
            "frame_errors": frame_errors,
            "total_frames_analyzed": 0,
            "status": "experimental_no_evidence",
            "canonical_ranking_affected": False,
        }

    motion_result = aggregate_motion_pockets(
        observations,
        accepted_samples,
        (),
        cluster_distance=config.cluster_distance,
    )
    return {
        **motion_result,
        "consensus_pockets": motion_result["motion_pockets"],
        "consensus_stats": {
            "accepted_samples": motion_result["accepted_sample_count"],
            "accepted_modes": motion_result["accepted_mode_count"],
        },
        "frame_stats": frame_stats,
        "frame_errors": frame_errors,
        "total_frames_analyzed": len(observations),
        "total_consensus_pockets": len(motion_result["motion_pockets"]),
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
    5. Return mode-aware experimental evidence
    """
    if config is None:
        config = EnsembleConfig(amplitudes=PIPELINE.alphafold_amplitudes)

    logger.info("AlphaFold ensemble pipeline for %s", uniprot_id)

    raw_pdb_path = fetch_alphafold_structure(uniprot_id)
    logger.info("AlphaFold structure: %s", raw_pdb_path)

    if output_dir is None:
        output_dir = Path("data/runtime/experimental/alphafold") / uniprot_id.upper()

    from .runtime import create_run_workspace
    from .structure_preparation import PreparationConfig, StructureSource, prepare_structure

    workspace = create_run_workspace(output_dir)
    preparation = prepare_structure(
        raw_pdb_path,
        StructureSource(
            provider="alphafold",
            identifier=uniprot_id,
            representation="predicted_model",
        ),
        PreparationConfig(),
        workspace.path / "preparation",
        workspace.run_id,
        analysis_config={
            "layer": "experimental_motion",
            "n_modes": config.n_modes,
            "samples_per_mode": config.n_frames_per_amplitude,
            "amplitudes": list(config.amplitudes),
        },
    )
    ensemble = generate_ensemble(preparation.prepared_path, config, workspace.path / "motion")
    logger.info(
        "Ensemble: %d accepted samples across %d amplitudes",
        ensemble["accepted_samples"],
        ensemble["successful_amplitudes"],
    )

    analysis = analyze_ensemble(ensemble, config)
    logger.info(
        "Analysis: %d motion candidates from %d accepted samples",
        analysis["total_consensus_pockets"],
        analysis["total_frames_analyzed"],
    )

    return {
        "uniprot_id": uniprot_id.upper(),
        "alphafold_pdb": str(raw_pdb_path),
        "prepared_pdb": str(preparation.prepared_path),
        "preparation_manifest": str(preparation.manifest_path),
        "ensemble": ensemble,
        "analysis": analysis,
        "config": {
            "n_modes": config.n_modes,
            "amplitudes": list(config.amplitudes),
            "n_frames_per_amplitude": config.n_frames_per_amplitude,
            "n_frames_semantics": "legacy_alias_for_samples_per_mode",
            "total_samples": config.total_samples,
            "profile": config.profile,
        },
    }
