"""Offline synthetic tests for the ANM dynamics engine."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from src.dynamics import (
    DEFAULT_CUTOFF,
    DEFAULT_GAMMA,
    build_anm_hessian,
    calculate_normal_modes,
    generate_conformations,
    load_ca_atoms,
    run_nma_simulation,
    validate_eigenvalues,
    validate_hessian,
)


@pytest.fixture
def synthetic_ca_pdb(tmp_path: Path) -> Path:
    path = tmp_path / "synthetic-ca.pdb"
    lines = []
    for index in range(1, 61):
        x = (index - 1) * 1.5
        y = ((index - 1) % 3) * 0.25
        z = ((index - 1) % 5) * 0.15
        lines.append(
            f"ATOM  {index:5d}  CA  ALA A{index:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C"
        )
    path.write_text("\n".join(lines) + "\nTER\nEND\n", encoding="ascii")
    return path


def test_load_ca_atoms_from_synthetic_fixture(synthetic_ca_pdb: Path) -> None:
    coords, atom_count = load_ca_atoms(str(synthetic_ca_pdb))

    assert atom_count == 60
    assert coords.shape == (60, 3)
    assert np.isfinite(coords).all()


@pytest.mark.scientific
def test_hessian_scientific_invariants(synthetic_ca_pdb: Path) -> None:
    coords, atom_count = load_ca_atoms(str(synthetic_ca_pdb))
    hessian = build_anm_hessian(coords)

    assert hessian.shape == (3 * atom_count, 3 * atom_count)
    assert np.allclose(hessian, hessian.T, atol=1e-10)
    assert np.allclose(hessian.sum(axis=0), 0.0, atol=1e-8)
    assert validate_hessian(hessian, atom_count, DEFAULT_CUTOFF, DEFAULT_GAMMA)


@pytest.mark.scientific
def test_normal_modes_are_finite_and_nonnegative(synthetic_ca_pdb: Path) -> None:
    coords, _ = load_ca_atoms(str(synthetic_ca_pdb))
    eigenvalues, eigenvectors = calculate_normal_modes(build_anm_hessian(coords), n_modes=5)

    assert eigenvalues.shape == (5,)
    assert eigenvectors.shape == (180, 5)
    assert np.isfinite(eigenvectors).all()
    assert validate_eigenvalues(eigenvalues)


def test_conformation_generation_is_deterministic() -> None:
    coords = np.arange(18, dtype=float).reshape(6, 3)
    eigenvectors = np.zeros((18, 2), dtype=float)
    eigenvectors[0, 0] = 1.0
    eigenvectors[4, 1] = 1.0

    first = generate_conformations(coords, eigenvectors, n_frames=4, amplitude=2.0)
    second = generate_conformations(coords, eigenvectors, n_frames=4, amplitude=2.0)

    assert len(first) == 8
    for left, right in zip(first, second, strict=True):
        assert np.array_equal(left, right)


def test_simulation_writes_only_to_temporary_directory(
    synthetic_ca_pdb: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "frames"

    result = run_nma_simulation(
        str(synthetic_ca_pdb),
        n_modes=2,
        n_frames=3,
        output_dir=output,
        save_frames=True,
        verbose=False,
    )

    assert len(result["conformations"]) == 6
    assert len(result["saved_files"]) == 6
    assert {path.parent for path in result["saved_files"]} == {output}
    assert all(path.is_file() for path in result["saved_files"])


@pytest.mark.performance
def test_small_synthetic_nma_performance(synthetic_ca_pdb: Path) -> None:
    started = time.monotonic()
    run_nma_simulation(
        str(synthetic_ca_pdb),
        n_modes=3,
        n_frames=3,
        save_frames=False,
        verbose=False,
    )
    assert time.monotonic() - started < 5.0
