"""Experimental motion ensemble generation and mode-aware pocket evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .dynamics import NMA_SAMPLING_POLICY_VERSION, load_ca_atoms, run_nma_simulation
from .frame_reconstruction import (
    FrameStatus,
    QUALITY_POLICY_VERSION,
    reconstruct_and_validate_frame,
)
from .resources import (
    SAFE_16GB,
    estimate_hessian_bytes,
    estimate_sparse_hessian_bytes,
)
from .static_detector import detect_static_pockets


MOTION_ENSEMBLE_SCHEMA_VERSION = "motion-ensemble-v1"
MOTION_EVIDENCE_POLICY = "accepted_only"


@dataclass(frozen=True)
class MotionEnsembleConfig:
    n_modes: int = 8
    samples_per_mode: int = 4
    maximum_amplitude: float = 1.5
    cutoff: float = 15.0
    gamma: float = 1.0
    solver: str = "auto"
    reconstruction_methods: tuple[str, ...] = (
        "residue_rigid_translation_v1",
        "backbone_blended_translation_v1",
    )

    def __post_init__(self) -> None:
        if self.n_modes < 1 or self.samples_per_mode < 1:
            raise ValueError("Motion mode and sample counts must be positive")
        if self.maximum_amplitude <= 0:
            raise ValueError("maximum_amplitude must be positive")
        if not self.reconstruction_methods:
            raise ValueError("At least one reconstruction method is required")


@dataclass(frozen=True)
class MotionEnsembleResult:
    output_dir: Path
    manifest_path: Path
    accepted_frame_files: tuple[Path, ...]
    accepted_sample_ids: tuple[str, ...]
    samples: tuple[dict[str, Any], ...]
    quality_counts: dict[str, int]
    estimated_memory_bytes: int


def _stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def generate_validated_motion_ensemble(
    template_pdb: str | Path,
    output_dir: str | Path,
    config: MotionEnsembleConfig | None = None,
    *,
    available_memory_bytes: int,
) -> MotionEnsembleResult:
    """Generate NMA samples in memory and persist only strictly accepted full-atom frames."""
    effective_config = config or MotionEnsembleConfig()
    root = Path(output_dir)
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"Motion output directory must be empty: {root}")
    accepted_dir = root / "accepted_frames"
    accepted_dir.mkdir(parents=True, exist_ok=True)

    _coordinates, atom_count = load_ca_atoms(str(template_pdb))
    estimated_memory = SAFE_16GB.validate_motion_request(
        atom_count=atom_count,
        samples_per_mode=effective_config.samples_per_mode,
        mode_count=effective_config.n_modes,
        available_memory_bytes=available_memory_bytes,
        solver=effective_config.solver,
    )
    nma_result = run_nma_simulation(
        str(template_pdb),
        n_modes=effective_config.n_modes,
        n_frames=effective_config.samples_per_mode,
        amplitude=effective_config.maximum_amplitude,
        cutoff=effective_config.cutoff,
        gamma=effective_config.gamma,
        save_frames=False,
        verbose=False,
        solver=effective_config.solver,
        return_hessian=False,
    )

    sample_records: list[dict[str, Any]] = []
    accepted_files: list[Path] = []
    accepted_ids: list[str] = []
    quality_counts = {status.value: 0 for status in FrameStatus}
    for sample in nma_result["samples"]:
        metadata = sample.to_metadata()
        candidate_results = []
        for method_index, method in enumerate(effective_config.reconstruction_methods):
            candidate_path = (
                root
                / "reconstruction_candidates"
                / f"{method_index:02d}_{method}"
                / f"frame_{sample.sample_id}.pdb"
            )
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_results.append(
                reconstruct_and_validate_frame(
                    template_pdb,
                    sample.coordinates,
                    output_pdb=candidate_path,
                    sample_metadata=metadata,
                    reconstruction_method=method,
                )
            )
        status_order = {
            FrameStatus.ACCEPTED: 0,
            FrameStatus.ACCEPTED_WITH_WARNINGS: 1,
            FrameStatus.REJECTED: 2,
        }
        reconstruction = min(
            candidate_results,
            key=lambda result: (
                status_order[result.quality.status],
                result.quality.bond_geometry_max_deviation,
                result.quality.introduced_clash_count,
                result.quality.maximum_atom_displacement,
                result.quality.reconstruction_method,
            ),
        )
        status = reconstruction.quality.status
        quality_counts[status.value] += 1
        selected_output = reconstruction.output_path
        used = status is FrameStatus.ACCEPTED and selected_output is not None
        if used:
            assert selected_output is not None
            accepted_path = accepted_dir / f"frame_{sample.sample_id}.pdb"
            selected_output.replace(accepted_path)
            accepted_files.append(accepted_path)
            accepted_ids.append(sample.sample_id)
        for candidate in candidate_results:
            if candidate.output_path is not None and candidate.output_path.exists():
                candidate.output_path.unlink()
        sample_records.append(
            {
                **metadata,
                "quality_status": status.value,
                "quality": reconstruction.quality.to_dict(),
                "reconstruction": asdict(reconstruction.stats),
                "reconstruction_candidates": [
                    {
                        "method": candidate.quality.reconstruction_method,
                        "status": candidate.quality.status.value,
                        "bond_geometry_max_deviation": (
                            candidate.quality.bond_geometry_max_deviation
                        ),
                        "introduced_clash_count": candidate.quality.introduced_clash_count,
                    }
                    for candidate in candidate_results
                ],
                "used_for_pocket_detection": used,
                "frame_file": (
                    str(Path("accepted_frames") / f"frame_{sample.sample_id}.pdb") if used else None
                ),
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": MOTION_ENSEMBLE_SCHEMA_VERSION,
        "sampling_policy_version": NMA_SAMPLING_POLICY_VERSION,
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "canonical_evidence_policy": MOTION_EVIDENCE_POLICY,
        "canonical_ranking_affected": False,
        "motion_layer_status": "experimental",
        "config": asdict(effective_config),
        "nma": {
            "n_atoms": nma_result["n_atoms"],
            "total_samples": nma_result["total_samples"],
            "solver": nma_result["params"]["solver"],
            "selected_solver_estimated_memory_bytes": estimated_memory,
            "dense_hessian_estimated_memory_bytes": estimate_hessian_bytes(atom_count),
            "sparse_hessian_estimated_memory_bytes": estimate_sparse_hessian_bytes(atom_count),
        },
        "quality_counts": quality_counts,
        "accepted_sample_ids": accepted_ids,
        "samples": sample_records,
    }
    manifest["manifest_sha256"] = _stable_hash(manifest)
    manifest_path = root / "motion_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return MotionEnsembleResult(
        output_dir=root,
        manifest_path=manifest_path,
        accepted_frame_files=tuple(accepted_files),
        accepted_sample_ids=tuple(accepted_ids),
        samples=tuple(sample_records),
        quality_counts=quality_counts,
        estimated_memory_bytes=estimated_memory,
    )


def _center(pocket: dict[str, Any]) -> np.ndarray:
    value = pocket.get("center", pocket.get("centroid"))
    coordinates = np.asarray(value, dtype=float)
    if coordinates.shape != (3,) or not np.all(np.isfinite(coordinates)):
        raise ValueError("Pocket center must contain three finite coordinates")
    return coordinates


def _residue_set(pocket: dict[str, Any]) -> set[str]:
    return {str(residue) for residue in pocket.get("residues", ())}


def _residue_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 1.0
    return len(left & right) / len(left | right)


def aggregate_motion_pockets(
    observations: Iterable[dict[str, Any]],
    accepted_samples: Iterable[dict[str, Any]],
    static_pockets: Iterable[dict[str, Any]],
    *,
    cluster_distance: float = 4.0,
    minimum_residue_jaccard: float = 0.25,
) -> dict[str, Any]:
    """Aggregate independent samples while preserving mode and direction evidence."""
    sample_records = [dict(sample) for sample in accepted_samples]
    accepted = [
        sample
        for sample in sample_records
        if sample.get("quality_status") == FrameStatus.ACCEPTED.value
    ]
    accepted_by_id = {str(sample["sample_id"]): sample for sample in accepted}
    accepted_modes = {int(sample["mode_id"]) for sample in accepted}
    requested_modes = {int(sample["mode_id"]) for sample in sample_records}
    clusters: list[dict[str, Any]] = []

    for observation in observations:
        sample = dict(observation.get("sample", {}))
        sample_id = str(sample.get("sample_id", ""))
        if sample_id not in accepted_by_id:
            continue
        canonical_sample = accepted_by_id[sample_id]
        for pocket in observation.get("pockets", ()):
            pocket_data = dict(pocket)
            pocket_center = _center(pocket_data)
            residues = _residue_set(pocket_data)
            selected = None
            selected_distance = float("inf")
            for cluster in clusters:
                distance = float(np.linalg.norm(pocket_center - cluster["center"]))
                similarity = _residue_similarity(residues, cluster["residues"])
                if (
                    distance <= cluster_distance
                    and similarity >= minimum_residue_jaccard
                    and distance < selected_distance
                ):
                    selected = cluster
                    selected_distance = distance
            if selected is None:
                selected = {
                    "center": pocket_center.copy(),
                    "residues": set(residues),
                    "observations": [],
                    "sample_ids": set(),
                }
                clusters.append(selected)
            if sample_id in selected["sample_ids"]:
                continue
            selected["sample_ids"].add(sample_id)
            selected["observations"].append((canonical_sample, pocket_data))
            centers = np.asarray(
                [_center(item[1]) for item in selected["observations"]], dtype=float
            )
            selected["center"] = np.mean(centers, axis=0)
            selected["residues"].update(residues)

    static = [dict(pocket) for pocket in static_pockets]
    motion_pockets: list[dict[str, Any]] = []
    accepted_count = len(accepted)
    for index, cluster in enumerate(clusters, start=1):
        entries = cluster["observations"]
        supported_modes = sorted({int(sample["mode_id"]) for sample, _pocket in entries})
        directions_by_mode: dict[int, set[int]] = {}
        sample_counts_by_mode: dict[int, int] = {}
        for sample, _pocket in entries:
            mode_id = int(sample["mode_id"])
            directions_by_mode.setdefault(mode_id, set()).add(int(sample["direction"]))
            sample_counts_by_mode[mode_id] = sample_counts_by_mode.get(mode_id, 0) + 1
        amplitudes = [float(sample["amplitude"]) for sample, _pocket in entries]
        volumes = [float(pocket.get("volume", 0.0)) for _sample, pocket in entries]
        center = np.asarray(cluster["center"], dtype=float)

        static_match: dict[str, Any] | None = None
        static_distance = float("inf")
        for candidate in static:
            distance = float(np.linalg.norm(center - _center(candidate)))
            similarity = _residue_similarity(cluster["residues"], _residue_set(candidate))
            if (
                distance <= cluster_distance
                and similarity >= minimum_residue_jaccard
                and distance < static_distance
            ):
                static_match = candidate
                static_distance = distance

        mode_fraction = len(supported_modes) / max(1, len(requested_modes))
        mode_probabilities = np.asarray(list(sample_counts_by_mode.values()), dtype=float)
        mode_probabilities /= np.sum(mode_probabilities)
        effective_mode_count = 1.0 / float(np.sum(mode_probabilities**2))
        mode_diversity = effective_mode_count / max(1, len(requested_modes))
        motion_pockets.append(
            {
                "motion_pocket_id": f"BV-MOTION-{index:04d}",
                "center": [round(float(value), 6) for value in center],
                "residues": sorted(cluster["residues"]),
                "ensemble_support": round(len(entries) / max(1, accepted_count), 6),
                "supported_sample_count": len(entries),
                "supported_modes": supported_modes,
                "mode_support": round(mode_fraction, 6),
                "mode_diversity": round(mode_diversity, 6),
                "bidirectional_support": any(
                    directions == {-1, 1} for directions in directions_by_mode.values()
                ),
                "amplitude_range": [
                    round(min(amplitudes), 6),
                    round(max(amplitudes), 6),
                ],
                "volume_mean": round(float(np.mean(volumes)), 6),
                "volume_min": round(float(np.min(volumes)), 6),
                "volume_max": round(float(np.max(volumes)), 6),
                "static_pocket_id": (
                    static_match.get("pocket_id", static_match.get("id"))
                    if static_match is not None
                    else None
                ),
                "static_center_distance": (
                    round(static_distance, 6) if static_match is not None else None
                ),
                "static_relationship": (
                    "static_linked" if static_match is not None else "motion_emergent_candidate"
                ),
            }
        )
    motion_pockets.sort(
        key=lambda pocket: (
            -pocket["mode_support"],
            -pocket["ensemble_support"],
            pocket["motion_pocket_id"],
        )
    )
    return {
        "schema_version": "motion-pocket-evidence-v1",
        "status": "experimental",
        "canonical_ranking_affected": False,
        "evidence_policy": MOTION_EVIDENCE_POLICY,
        "accepted_sample_count": accepted_count,
        "accepted_mode_count": len(accepted_modes),
        "requested_mode_count": len(requested_modes),
        "motion_pockets": motion_pockets,
    }


def analyze_validated_motion_ensemble(
    ensemble: MotionEnsembleResult,
    static_pockets: Iterable[dict[str, Any]],
    *,
    prepared_sha256: str,
) -> dict[str, Any]:
    """Run the canonical geometry detector independently on each accepted frame."""
    samples_by_id = {str(sample["sample_id"]): sample for sample in ensemble.samples}
    observations: list[dict[str, Any]] = []
    for frame in ensemble.accepted_frame_files:
        sample_id = frame.stem.removeprefix("frame_")
        detection = detect_static_pockets(frame, prepared_sha256=prepared_sha256)
        observations.append(
            {
                "sample": samples_by_id[sample_id],
                "pockets": [pocket.to_portable_dict() for pocket in detection.pockets],
            }
        )
    result = aggregate_motion_pockets(observations, ensemble.samples, static_pockets)
    result["ensemble_manifest"] = str(ensemble.manifest_path)
    result["quality_counts"] = dict(ensemble.quality_counts)
    return result
