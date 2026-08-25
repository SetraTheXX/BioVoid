"""Phase 4 experimental motion-aware recovery regressions."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


def _write_full_atom_chain(path: Path, residues: int = 60) -> None:
    lines: list[str] = []
    serial = 1
    for residue in range(1, residues + 1):
        base = (residue - 1) * 3.8
        atoms = (
            ("N", "N", (base, 0.00, 0.00)),
            ("CA", "C", (base + 1.45, 0.20, 0.00)),
            ("C", "C", (base + 2.90, 0.00, 0.10)),
            ("O", "O", (base + 3.35, -0.85, 0.10)),
            ("CB", "C", (base + 1.45, 1.55, 0.30)),
        )
        for atom_name, element, coord in atoms:
            lines.append(
                f"ATOM  {serial:5d} {atom_name:>4s} ALA A{residue:4d}    "
                f"{coord[0]:8.3f}{coord[1]:8.3f}{coord[2]:8.3f}  1.00 20.00"
                f"          {element:>2s}"
            )
            serial += 1
    path.write_text("\n".join(lines) + "\nTER\nEND\n", encoding="ascii")


def _template_ca_coordinates(path: Path) -> np.ndarray:
    import biotite.structure.io.pdb as pdb

    structure = pdb.PDBFile.read(str(path)).get_structure()[0]
    return np.asarray(structure.coord[structure.atom_name == "CA"], dtype=float)


def test_mode_samples_have_explicit_semantics_and_no_reference_duplicates() -> None:
    from src.dynamics import generate_mode_samples

    coordinates = np.arange(18, dtype=float).reshape(6, 3)
    eigenvalues = np.asarray([0.2, 0.4], dtype=float)
    eigenvectors = np.zeros((18, 2), dtype=float)
    eigenvectors[0, 0] = 1.0
    eigenvectors[4, 1] = 1.0

    samples = generate_mode_samples(
        coordinates,
        eigenvalues,
        eigenvectors,
        samples_per_mode=4,
        maximum_amplitude=2.0,
    )

    assert len(samples) == 8
    assert len({sample.sample_id for sample in samples}) == 8
    assert {sample.mode_id for sample in samples} == {7, 8}
    assert all(sample.direction in {-1, 1} for sample in samples)
    assert all(sample.amplitude > 0 for sample in samples)
    assert all(sample.reference_duplicate is False for sample in samples)
    assert all(not np.array_equal(sample.coordinates, coordinates) for sample in samples)
    for mode_id in {7, 8}:
        directions = {sample.direction for sample in samples if sample.mode_id == mode_id}
        assert directions == {-1, 1}


def test_nma_manifest_reports_modes_samples_and_unique_files(
    tmp_path: Path,
) -> None:
    from src.dynamics import run_nma_simulation

    template = tmp_path / "template.pdb"
    output = tmp_path / "ca-samples"
    _write_full_atom_chain(template)

    result = run_nma_simulation(
        str(template),
        n_modes=2,
        n_frames=4,
        amplitude=0.5,
        output_dir=output,
        save_frames=True,
        verbose=False,
    )
    manifest = json.loads((output / "nma_manifest.json").read_text(encoding="utf-8"))

    assert result["total_samples"] == 8
    assert result["samples_per_mode"] == 4
    assert len(result["sample_manifest"]) == 8
    assert len(result["saved_files"]) == 8
    assert len({path.name for path in result["saved_files"]}) == 8
    assert manifest["total_samples"] == 8
    assert manifest["mode_count"] == 2
    assert manifest["samples_per_mode"] == 4
    assert all("mode_id" in sample for sample in manifest["samples"])
    assert all("phase_radians" in sample for sample in manifest["samples"])


def test_reconstruction_quality_accepts_smooth_motion_and_preserves_identity(
    tmp_path: Path,
) -> None:
    from src.frame_reconstruction import (
        FrameStatus,
        reconstruct_and_validate_frame,
    )

    template = tmp_path / "template.pdb"
    output = tmp_path / "accepted.pdb"
    _write_full_atom_chain(template)
    target = _template_ca_coordinates(template)
    target[:, 1] += 0.08 * np.sin(np.linspace(0.0, 2.0 * math.pi, len(target)))

    result = reconstruct_and_validate_frame(
        template,
        target,
        output_pdb=output,
        reconstruction_method="residue_rigid_translation_v1",
    )

    assert result.quality.status is FrameStatus.ACCEPTED
    assert result.quality.atom_identities_preserved is True
    assert result.quality.atom_count_preserved is True
    assert result.quality.ca_target_max_error < 1e-6
    assert result.quality.chain_break_count == 0
    assert result.quality.reconstruction_method == "residue_rigid_translation_v1"
    assert result.quality.minimization_applied is False
    assert output.is_file()


def test_reconstruction_quality_rejects_broken_backbone_and_does_not_persist(
    tmp_path: Path,
) -> None:
    from src.frame_reconstruction import (
        FrameStatus,
        reconstruct_and_validate_frame,
    )

    template = tmp_path / "template.pdb"
    output = tmp_path / "rejected.pdb"
    _write_full_atom_chain(template)
    target = _template_ca_coordinates(template)
    target[1::2, 1] += 4.0

    result = reconstruct_and_validate_frame(
        template,
        target,
        output_pdb=output,
        reconstruction_method="residue_rigid_translation_v1",
    )

    assert result.quality.status is FrameStatus.REJECTED
    assert result.quality.chain_break_count > 0 or result.quality.bond_geometry_max_deviation > 0.35
    assert result.quality.reasons
    assert output.exists() is False


def test_motion_aggregation_uses_only_accepted_samples_and_mode_evidence() -> None:
    from src.motion_ensemble import aggregate_motion_pockets

    accepted = [
        {
            "sample_id": "m007-neg",
            "mode_id": 7,
            "direction": -1,
            "amplitude": 0.5,
            "quality_status": "ACCEPTED",
        },
        {
            "sample_id": "m007-pos",
            "mode_id": 7,
            "direction": 1,
            "amplitude": 0.5,
            "quality_status": "ACCEPTED",
        },
        {
            "sample_id": "m008-pos",
            "mode_id": 8,
            "direction": 1,
            "amplitude": 1.0,
            "quality_status": "ACCEPTED",
        },
    ]
    observations = [
        {
            "sample": accepted[0],
            "pockets": [
                {
                    "pocket_id": "p1",
                    "center": [0.0, 0.0, 0.0],
                    "volume": 80.0,
                    "residues": ["A:ALA:1", "A:ALA:2"],
                }
            ],
        },
        {
            "sample": accepted[1],
            "pockets": [
                {
                    "pocket_id": "p2",
                    "center": [0.4, 0.1, 0.0],
                    "volume": 90.0,
                    "residues": ["A:ALA:1", "A:ALA:2"],
                }
            ],
        },
        {
            "sample": accepted[2],
            "pockets": [
                {
                    "pocket_id": "p3",
                    "center": [0.3, -0.1, 0.2],
                    "volume": 100.0,
                    "residues": ["A:ALA:1", "A:ALA:2", "A:ALA:3"],
                }
            ],
        },
        {
            "sample": {
                "sample_id": "warned",
                "mode_id": 9,
                "direction": 1,
                "amplitude": 1.0,
                "quality_status": "ACCEPTED_WITH_WARNINGS",
            },
            "pockets": [{"center": [0.0, 0.0, 0.0], "volume": 999.0}],
        },
    ]
    static = [
        {
            "pocket_id": "BV-STATIC",
            "center": [0.2, 0.0, 0.0],
            "volume": 70.0,
            "residues": ["A:ALA:1", "A:ALA:2"],
        }
    ]

    result = aggregate_motion_pockets(observations, accepted, static)

    assert result["accepted_sample_count"] == 3
    assert len(result["motion_pockets"]) == 1
    pocket = result["motion_pockets"][0]
    assert pocket["ensemble_support"] == 1.0
    assert pocket["supported_modes"] == [7, 8]
    assert pocket["mode_support"] == 1.0
    assert pocket["mode_diversity"] == 0.9
    assert pocket["bidirectional_support"] is True
    assert pocket["static_pocket_id"] == "BV-STATIC"
    assert pocket["volume_mean"] < 200.0
    assert "persistence" not in json.dumps(result).lower()
    assert "flicker" not in json.dumps(result).lower()


def test_motion_manifest_is_deterministic_and_persists_only_accepted_frames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.motion_ensemble as motion
    from src.dynamics import ModeSample
    from src.frame_reconstruction import (
        FrameQualityReport,
        FrameStatus,
        ReconstructionResult,
        ReconstructionStats,
    )

    template = tmp_path / "template.pdb"
    _write_full_atom_chain(template)
    coords = _template_ca_coordinates(template)
    samples = [
        ModeSample(
            sample_id="m007-neg",
            mode_id=7,
            eigenvalue=0.2,
            direction=-1,
            phase_radians=-math.pi / 2,
            amplitude=0.5,
            amplitude_fraction=1.0,
            coordinates=coords,
            reference_duplicate=False,
        ),
        ModeSample(
            sample_id="m007-pos",
            mode_id=7,
            eigenvalue=0.2,
            direction=1,
            phase_radians=math.pi / 2,
            amplitude=0.5,
            amplitude_fraction=1.0,
            coordinates=coords,
            reference_duplicate=False,
        ),
    ]
    monkeypatch.setattr(
        motion,
        "run_nma_simulation",
        lambda *_args, **_kwargs: {
            "samples": samples,
            "sample_manifest": [sample.to_metadata() for sample in samples],
            "total_samples": 2,
            "n_atoms": len(coords),
            "params": {"solver": "dense"},
        },
    )

    def fake_reconstruct(_template, _coords, *, output_pdb, sample_metadata, **_kwargs):
        accepted = sample_metadata["direction"] == -1
        if accepted:
            Path(output_pdb).write_text("END\n", encoding="ascii")
        quality = FrameQualityReport.synthetic(
            status=FrameStatus.ACCEPTED if accepted else FrameStatus.ACCEPTED_WITH_WARNINGS,
            reconstruction_method="residue_rigid_translation_v1",
        )
        return ReconstructionResult(
            stats=ReconstructionStats.synthetic(),
            quality=quality,
            output_path=Path(output_pdb) if accepted else None,
        )

    monkeypatch.setattr(motion, "reconstruct_and_validate_frame", fake_reconstruct)

    result = motion.generate_validated_motion_ensemble(
        template,
        tmp_path / "motion",
        motion.MotionEnsembleConfig(n_modes=1, samples_per_mode=2, maximum_amplitude=0.5),
        available_memory_bytes=12 * 1024**3,
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert result.accepted_sample_ids == ("m007-neg",)
    assert len(result.accepted_frame_files) == 1
    assert manifest["quality_counts"] == {
        "ACCEPTED": 1,
        "ACCEPTED_WITH_WARNINGS": 1,
        "REJECTED": 0,
    }
    assert manifest["canonical_evidence_policy"] == "accepted_only"
    assert manifest["samples"][1]["used_for_pocket_detection"] is False


def test_small_motion_ensemble_runs_end_to_end_offline(tmp_path: Path) -> None:
    from src.motion_ensemble import MotionEnsembleConfig, generate_validated_motion_ensemble

    template = tmp_path / "template.pdb"
    _write_full_atom_chain(template)
    result = generate_validated_motion_ensemble(
        template,
        tmp_path / "motion",
        MotionEnsembleConfig(
            n_modes=1,
            samples_per_mode=2,
            maximum_amplitude=0.05,
            solver="dense",
        ),
        available_memory_bytes=12 * 1024**3,
    )

    assert result.quality_counts["ACCEPTED"] == 2
    assert len(result.accepted_frame_files) == 2
    assert all(path.is_file() for path in result.accepted_frame_files)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert all(len(sample["reconstruction_candidates"]) == 2 for sample in manifest["samples"])

    repeated = generate_validated_motion_ensemble(
        template,
        tmp_path / "motion-repeat",
        MotionEnsembleConfig(
            n_modes=1,
            samples_per_mode=2,
            maximum_amplitude=0.05,
            solver="dense",
        ),
        available_memory_bytes=12 * 1024**3,
    )
    repeated_manifest = json.loads(repeated.manifest_path.read_text(encoding="utf-8"))
    assert repeated.accepted_sample_ids == result.accepted_sample_ids
    assert repeated_manifest["manifest_sha256"] == manifest["manifest_sha256"]


def test_alphafold_amplitudes_reach_motion_generator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.motion_ensemble as motion
    from src.alphafold_ensemble import EnsembleConfig, generate_ensemble

    template = tmp_path / "template.pdb"
    _write_full_atom_chain(template)
    observed_amplitudes: list[float] = []

    def fake_generate(_template, output_dir, config, **_kwargs):
        observed_amplitudes.append(config.maximum_amplitude)
        root = Path(output_dir)
        (root / "accepted_frames").mkdir(parents=True)
        return SimpleNamespace(
            output_dir=root,
            manifest_path=root / "motion_manifest.json",
            samples=tuple({} for _ in range(config.n_modes * config.samples_per_mode)),
            accepted_sample_ids=tuple(
                f"sample-{index}" for index in range(config.n_modes * config.samples_per_mode)
            ),
        )

    monkeypatch.setattr(motion, "generate_validated_motion_ensemble", fake_generate)
    result = generate_ensemble(
        template,
        EnsembleConfig(
            n_modes=2,
            n_frames_per_amplitude=2,
            amplitudes=(0.4, 0.8),
        ),
        tmp_path / "alphafold-motion",
    )

    assert observed_amplitudes == [0.4, 0.8]
    assert result["total_samples"] == 8
    assert result["accepted_samples"] == 8


def test_alphafold_no_evidence_result_reports_zero_consensus_pockets(tmp_path: Path) -> None:
    from src.alphafold_ensemble import EnsembleConfig, analyze_ensemble

    source = tmp_path / "source.pdb"
    source.write_text("END\n", encoding="utf-8")

    result = analyze_ensemble(
        {
            "source_pdb": str(source),
            "amplitude_metadata": [{"amplitude": 2.0, "error": "resource blocked"}],
        },
        EnsembleConfig(n_modes=1, n_frames_per_amplitude=1, amplitudes=(2.0,)),
    )

    assert result["status"] == "experimental_no_evidence"
    assert result["total_frames_analyzed"] == 0
    assert result["total_consensus_pockets"] == 0


def test_sparse_memory_estimate_is_lower_and_safe_profile_limits_sampling() -> None:
    from src.resources import (
        ResourceLimitError,
        SAFE_16GB,
        estimate_hessian_bytes,
        estimate_sparse_hessian_bytes,
    )

    assert estimate_sparse_hessian_bytes(1000) < estimate_hessian_bytes(1000)
    SAFE_16GB.validate_motion_request(
        atom_count=1000,
        samples_per_mode=4,
        mode_count=8,
        available_memory_bytes=12 * 1024**3,
    )
    with pytest.raises(ResourceLimitError):
        SAFE_16GB.validate_motion_request(
            atom_count=1000,
            samples_per_mode=40,
            mode_count=8,
            available_memory_bytes=12 * 1024**3,
        )


def test_sparse_hessian_matches_dense_reference() -> None:
    from src.dynamics import build_anm_hessian, build_anm_hessian_sparse

    coordinates = np.asarray([[0.0, 0.0, 0.0], [3.8, 0.2, 0.0], [7.4, -0.1, 0.4], [11.0, 0.3, 0.2]])
    dense = build_anm_hessian(coordinates, cutoff=8.0)
    sparse = build_anm_hessian_sparse(coordinates, cutoff=8.0)

    assert np.allclose(sparse.toarray(), dense)


def test_api_rejects_motion_sampling_above_safe_profile() -> None:
    from pydantic import ValidationError

    from src.api.models import JobOptions

    with pytest.raises(ValidationError):
        JobOptions(mode="motion_aware", n_frames=9)
    with pytest.raises(ValidationError):
        JobOptions(mode="motion_aware", n_frames=8)
    assert JobOptions(mode="static", n_frames=20).n_frames == 20


def test_pipeline_keeps_static_result_separate_when_motion_is_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import main
    from main import BioVoidPipeline

    template = tmp_path / "template.pdb"
    _write_full_atom_chain(template)
    fake_detection = SimpleNamespace(candidate_count=2, pockets=())
    monkeypatch.setattr(main, "detect_static_pockets", lambda *_args, **_kwargs: fake_detection)
    monkeypatch.setattr(
        main,
        "find_voids",
        lambda *_args, **_kwargs: pytest.fail("legacy motion detector must not replace static"),
    )

    pipeline = BioVoidPipeline(
        "TEST",
        output_dir=str(tmp_path / "runs"),
        multiframe=True,
        allow_experimental=True,
    )
    pipeline.pdb_file = str(template)
    pipeline.preparation_result = SimpleNamespace(prepared_sha256="a" * 64)
    pipeline._scan_voids()

    assert pipeline.static_detection is fake_detection
    assert len(pipeline.voids) == 2
