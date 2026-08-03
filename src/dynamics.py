"""
Bio-Void Hunter: NMA Dynamics Engine
=====================================
Normal Mode Analysis (NMA) based protein dynamics simulation.

This module generates protein "breathing" conformations using the
Anisotropic Network Model (ANM) approach.

REFACTORED FROM: scripts/test_nma_math.py (PROVEN & VALIDATED CODE)
DO NOT MODIFY THE MATHEMATICS - ONLY THE STRUCTURE!

References:
- Atilgan et al. (2001) "Anisotropy of Fluctuation Dynamics of Proteins"
- Bahar et al. (1997) "Direct evaluation of thermal fluctuations in proteins"
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import biotite.structure.io.pdb as pdb
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import eigsh
from scipy.spatial import cKDTree

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS (From literature - DO NOT CHANGE!)
# ============================================================================

DEFAULT_CUTOFF = 15.0  # Angstrom (Atilgan et al. 2001)
DEFAULT_GAMMA = 1.0  # Spring constant (standard)
MIN_ATOMS = 50  # Minimum protein size
MAX_ATOMS = 5000  # Maximum for consumer hardware
NMA_SAMPLING_POLICY_VERSION = "nma-mode-sampling-v1"
SPARSE_SOLVER_ATOM_THRESHOLD = 250


@dataclass(frozen=True)
class ModeSample:
    """One independent displacement sample from one normal mode."""

    sample_id: str
    mode_id: int
    eigenvalue: float
    direction: int
    phase_radians: float
    amplitude: float
    amplitude_fraction: float
    coordinates: np.ndarray
    reference_duplicate: bool = False

    def to_metadata(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "mode_id": self.mode_id,
            "eigenvalue": round(float(self.eigenvalue), 12),
            "direction": self.direction,
            "phase_radians": round(float(self.phase_radians), 12),
            "amplitude": round(float(self.amplitude), 8),
            "amplitude_fraction": round(float(self.amplitude_fraction), 8),
            "reference_duplicate": self.reference_duplicate,
        }


# ============================================================================
# 1. STRUCTURE LOADING (Refactored from test_nma_math.py:25-50)
# ============================================================================


def load_ca_atoms(pdb_path: str) -> tuple[np.ndarray, int]:
    """
    Load PDB and extract CA (alpha-carbon) atoms.

    Refactored from: test_nma_math.py lines 25-50

    Args:
        pdb_path: Path to PDB file

    Returns:
        coords: CA atom coordinates (N x 3)
        n_atoms: Number of CA atoms
    """
    pdb_file = pdb.PDBFile.read(pdb_path)
    structure = pdb_file.get_structure()[0]  # First model

    # Filter CA atoms (standard for NMA)
    ca_filter = structure.atom_name == "CA"
    ca_atoms = structure[ca_filter]

    coords = ca_atoms.coord
    n_atoms = len(coords)

    # Validation
    if n_atoms < MIN_ATOMS:
        raise ValueError(f"Too few atoms: {n_atoms} (min: {MIN_ATOMS})")
    if n_atoms > MAX_ATOMS:
        raise ValueError(f"Too many atoms: {n_atoms} (max: {MAX_ATOMS})")

    return coords, n_atoms


# ============================================================================
# 2. HESSIAN MATRIX (Refactored from test_nma_math.py:57-111)
# ============================================================================


def build_anm_hessian(
    coords: np.ndarray, cutoff: float = DEFAULT_CUTOFF, gamma: float = DEFAULT_GAMMA
) -> np.ndarray:
    """
    Build Anisotropic Network Model (ANM) Hessian matrix.

    Refactored from: test_nma_math.py lines 57-111
    MATH IS IDENTICAL - DO NOT MODIFY!

    ANM Principle:
    - Atoms within cutoff distance are connected by springs
    - Each spring has force constant gamma (typically 1.0)
    - Hessian matrix is 3N x 3N (N = number of atoms)

    Args:
        coords: CA atom coordinates (N x 3)
        cutoff: Interaction cutoff distance (Angstrom)
        gamma: Spring force constant

    Returns:
        hessian: 3N x 3N Hessian matrix
    """
    n_atoms = len(coords)
    n_dof = 3 * n_atoms  # Degrees of freedom

    # Initialize empty Hessian
    hessian = np.zeros((n_dof, n_dof))

    # Build Hessian for all atom pairs
    for i in range(n_atoms):
        for j in range(i + 1, n_atoms):
            # Distance vector
            diff = coords[i] - coords[j]
            dist = np.linalg.norm(diff)

            # Add spring if within cutoff
            if dist < cutoff:
                # Normalized direction vector
                unit_vec = diff / dist

                # 3x3 sub-matrix (outer product)
                sub_matrix = gamma * np.outer(unit_vec, unit_vec)

                # Add to Hessian (symmetric)
                i_start, i_end = 3 * i, 3 * (i + 1)
                j_start, j_end = 3 * j, 3 * (j + 1)

                hessian[i_start:i_end, j_start:j_end] -= sub_matrix
                hessian[j_start:j_end, i_start:i_end] -= sub_matrix

                hessian[i_start:i_end, i_start:i_end] += sub_matrix
                hessian[j_start:j_end, j_start:j_end] += sub_matrix

    return hessian


def build_anm_hessian_sparse(
    coords: np.ndarray,
    cutoff: float = DEFAULT_CUTOFF,
    gamma: float = DEFAULT_GAMMA,
) -> sparse.csr_matrix:
    """Build the same ANM Hessian as a sparse CSR matrix."""
    coordinates = np.asarray(coords, dtype=float)
    n_atoms = len(coordinates)
    hessian = sparse.lil_matrix((3 * n_atoms, 3 * n_atoms), dtype=float)
    pairs = sorted(cKDTree(coordinates).query_pairs(cutoff))

    for i, j in pairs:
        diff = coordinates[i] - coordinates[j]
        distance = float(np.linalg.norm(diff))
        if distance <= 1e-12:
            continue
        unit_vector = diff / distance
        block = gamma * np.outer(unit_vector, unit_vector)
        i_slice = slice(3 * i, 3 * (i + 1))
        j_slice = slice(3 * j, 3 * (j + 1))
        hessian[i_slice, j_slice] -= block
        hessian[j_slice, i_slice] -= block
        hessian[i_slice, i_slice] += block
        hessian[j_slice, j_slice] += block
    return hessian.tocsr()


# ============================================================================
# 3. NORMAL MODES (Refactored from test_nma_math.py:118-145)
# ============================================================================


def calculate_normal_modes(
    hessian: np.ndarray | sparse.spmatrix,
    n_modes: int = 10,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Calculate eigenvalues and eigenvectors of Hessian matrix.

    Refactored from: test_nma_math.py lines 118-145
    MATH IS IDENTICAL - DO NOT MODIFY!

    First 6 modes are "trivial" (translation + rotation) and are skipped.

    Args:
        hessian: Hessian matrix
        n_modes: Number of modes to calculate (excluding trivial)

    Returns:
        eigenvalues: Mode frequencies (n_modes,)
        eigenvectors: Mode shapes (3N x n_modes)
    """
    if n_modes < 1:
        raise ValueError("n_modes must be positive")

    if sparse.issparse(hessian):
        requested = n_modes + 6
        if requested >= hessian.shape[0]:
            raise ValueError("Sparse eigensolver request exceeds Hessian dimensions")
        eigenvalues, eigenvectors = eigsh(
            hessian,
            k=requested,
            which="SM",
            tol=1e-8,
            v0=np.linspace(1.0, 2.0, hessian.shape[0], dtype=float),
        )
        order = np.argsort(eigenvalues)
        eigenvalues = eigenvalues[order]
        eigenvectors = eigenvectors[:, order]
    else:
        eigenvalues, eigenvectors = np.linalg.eigh(hessian)

    # Skip first 6 trivial modes (translation + rotation)
    eigenvalues = eigenvalues[6 : 6 + n_modes]
    eigenvectors = eigenvectors[:, 6 : 6 + n_modes]
    for mode_index in range(eigenvectors.shape[1]):
        pivot = int(np.argmax(np.abs(eigenvectors[:, mode_index])))
        if eigenvectors[pivot, mode_index] < 0:
            eigenvectors[:, mode_index] *= -1.0

    return eigenvalues, eigenvectors


# ============================================================================
# 4. CONFORMATION GENERATION (Refactored from phase1_integration_test.py:143-161)
# ============================================================================


def generate_conformations(
    coords: np.ndarray, eigenvectors: np.ndarray, n_frames: int = 10, amplitude: float = 3.0
) -> list[np.ndarray]:
    """
    Generate protein conformations along normal modes.

    Refactored from: phase1_integration_test.py lines 143-161

    Produces independent non-reference displacement samples for each mode.

    Args:
        coords: Original CA coordinates (N x 3)
        eigenvectors: Normal mode eigenvectors (3N x n_modes)
        n_frames: Independent samples per mode
        amplitude: Maximum displacement (Angstrom)

    Returns:
        conformations: List of coordinate arrays
    """
    eigenvalues = np.zeros(eigenvectors.shape[1], dtype=float)
    return [
        sample.coordinates
        for sample in generate_mode_samples(
            coords,
            eigenvalues,
            eigenvectors,
            samples_per_mode=n_frames,
            maximum_amplitude=amplitude,
        )
    ]


def _signed_amplitude_levels(samples_per_mode: int) -> list[tuple[int, float]]:
    if samples_per_mode < 1:
        raise ValueError("samples_per_mode must be positive")
    negative_count = samples_per_mode // 2
    positive_count = samples_per_mode - negative_count
    levels: list[tuple[int, float]] = []
    if negative_count:
        levels.extend(
            (-1, float(level)) for level in np.linspace(1.0 / negative_count, 1.0, negative_count)
        )
    levels.extend(
        (1, float(level)) for level in np.linspace(1.0 / positive_count, 1.0, positive_count)
    )
    return levels


def generate_mode_samples(
    coords: np.ndarray,
    eigenvalues: np.ndarray,
    eigenvectors: np.ndarray,
    *,
    samples_per_mode: int,
    maximum_amplitude: float,
) -> list[ModeSample]:
    """Generate independent bidirectional mode samples without reference duplicates."""
    coordinates = np.asarray(coords, dtype=float)
    values = np.asarray(eigenvalues, dtype=float)
    vectors = np.asarray(eigenvectors, dtype=float)
    if maximum_amplitude <= 0 or not np.isfinite(maximum_amplitude):
        raise ValueError("maximum_amplitude must be positive and finite")
    if vectors.shape != (coordinates.size, len(values)):
        raise ValueError("Eigenvector dimensions do not match coordinates/eigenvalues")

    samples: list[ModeSample] = []
    maximum_token = int(round(maximum_amplitude * 1000))
    for mode_index, eigenvalue in enumerate(values):
        mode_id = mode_index + 7
        mode_vector = vectors[:, mode_index].reshape(coordinates.shape)
        for direction, fraction in _signed_amplitude_levels(samples_per_mode):
            magnitude = maximum_amplitude * fraction
            signed_amplitude = direction * magnitude
            displaced = coordinates + signed_amplitude * mode_vector
            amplitude_token = int(round(magnitude * 1000))
            sample_id = (
                f"m{mode_id:03d}_{'neg' if direction < 0 else 'pos'}"
                f"_a{amplitude_token:05d}_max{maximum_token:05d}"
            )
            samples.append(
                ModeSample(
                    sample_id=sample_id,
                    mode_id=mode_id,
                    eigenvalue=float(eigenvalue),
                    direction=direction,
                    phase_radians=direction * np.pi / 2.0,
                    amplitude=float(magnitude),
                    amplitude_fraction=fraction,
                    coordinates=displaced,
                    reference_duplicate=bool(np.array_equal(displaced, coordinates)),
                )
            )
    return [sample for sample in samples if not sample.reference_duplicate]


# ============================================================================
# 5. PDB FILE SAVING
# ============================================================================


def save_frames_as_pdb(
    conformations: list[np.ndarray], template_pdb: str, output_dir: Path | str
) -> list[Path]:
    """
    Save conformations as PDB files.

    Args:
        conformations: List of coordinate arrays
        template_pdb: Original PDB file (for atom info)
        output_dir: Directory to save frames

    Returns:
        saved_files: List of saved file paths
    """
    # Convert to Path if string
    if isinstance(output_dir, str):
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Load template structure for atom names etc.
    pdb_file = pdb.PDBFile.read(template_pdb)
    template = pdb_file.get_structure()[0]
    ca_filter = template.atom_name == "CA"
    ca_template = template[ca_filter]

    saved_files = []

    for i, coords in enumerate(conformations):
        # Create new structure with updated coordinates
        frame = ca_template.copy()
        frame.coord = coords

        # Save as PDB
        frame_path = output_dir / f"frame_{i + 1:03d}.pdb"
        pdb_out = pdb.PDBFile()
        pdb_out.set_structure(frame)
        pdb_out.write(str(frame_path))

        saved_files.append(frame_path)

    return saved_files


def save_mode_samples_as_pdb(
    samples: list[ModeSample],
    template_pdb: str,
    output_dir: Path | str,
) -> list[Path]:
    """Persist CA-only diagnostic samples with collision-resistant labels."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    pdb_file = pdb.PDBFile.read(template_pdb)
    template = pdb_file.get_structure()[0]
    ca_template = template[template.atom_name == "CA"]
    saved: list[Path] = []
    for sample in samples:
        frame = ca_template.copy()
        frame.coord = sample.coordinates
        frame_path = root / f"frame_{sample.sample_id}.pdb"
        out = pdb.PDBFile()
        out.set_structure(frame)
        out.write(str(frame_path))
        saved.append(frame_path)
    return saved


# ============================================================================
# 6. MAIN SIMULATION FUNCTION
# ============================================================================


def run_nma_simulation(
    pdb_path: str,
    n_modes: int = 10,
    n_frames: int = 10,
    amplitude: float = 3.0,
    cutoff: float = DEFAULT_CUTOFF,
    gamma: float = DEFAULT_GAMMA,
    output_dir: Path | None = None,
    save_frames: bool = True,
    verbose: bool = True,
    solver: str = "auto",
    return_hessian: bool = True,
) -> dict[str, Any]:
    """
    Run complete NMA simulation pipeline.

    This is the main entry point for the NMA dynamics engine.

    Args:
        pdb_path: Path to input PDB file
        n_modes: Number of normal modes to calculate
        n_frames: Independent non-reference samples per mode (legacy parameter name)
        amplitude: Displacement amplitude (Angstrom)
        cutoff: ANM cutoff distance (Angstrom)
        gamma: Spring force constant
        output_dir: Run-scoped directory for diagnostic sample files. Required when saving.
        save_frames: Whether to save CA-only diagnostic sample files
        verbose: Print progress

    Returns:
        dict with keys:
        - coords: Original coordinates
        - eigenvalues: Mode frequencies
        - eigenvectors: Mode shapes
        - conformations: List of generated coordinates
        - saved_files: List of saved PDB paths (if save_frames=True)
        - timing: Performance metrics
    """
    timing = {}
    total_start = time.time()
    log = logger.info if verbose else logger.debug

    log("[NMA] Dynamics engine starting for %s", pdb_path)

    start = time.time()
    coords, n_atoms = load_ca_atoms(pdb_path)
    timing["load"] = time.time() - start
    log("[NMA] Loaded %d CA atoms (%.2fs)", n_atoms, timing["load"])

    if solver not in {"auto", "dense", "sparse"}:
        raise ValueError("solver must be auto, dense, or sparse")
    solver_used = (
        "sparse"
        if solver == "sparse" or (solver == "auto" and n_atoms >= SPARSE_SOLVER_ATOM_THRESHOLD)
        else "dense"
    )

    log(
        "[NMA] Building %s Hessian matrix (%dx%d)...",
        solver_used,
        3 * n_atoms,
        3 * n_atoms,
    )
    start = time.time()
    if solver_used == "sparse":
        hessian = build_anm_hessian_sparse(coords, cutoff=cutoff, gamma=gamma)
    else:
        hessian = build_anm_hessian(coords, cutoff=cutoff, gamma=gamma)
    timing["hessian"] = time.time() - start
    log("[NMA] Hessian built (%.2fs)", timing["hessian"])

    log("[NMA] Calculating %d normal modes...", n_modes)
    start = time.time()
    eigenvalues, eigenvectors = calculate_normal_modes(hessian, n_modes=n_modes)
    timing["modes"] = time.time() - start
    log(
        "[NMA] Modes calculated (%.2fs) — frequency range: %.4f - %.4f",
        timing["modes"],
        eigenvalues[0],
        eigenvalues[-1],
    )

    total_samples = n_modes * n_frames
    log(
        "[NMA] Generating %d independent samples (%d modes x %d samples)...",
        total_samples,
        n_modes,
        n_frames,
    )
    start = time.time()
    samples = generate_mode_samples(
        coords,
        eigenvalues,
        eigenvectors,
        samples_per_mode=n_frames,
        maximum_amplitude=amplitude,
    )
    conformations = [sample.coordinates for sample in samples]
    timing["conformations"] = time.time() - start
    log("[NMA] Generated %d samples (%.2fs)", len(conformations), timing["conformations"])

    saved_files = []
    if save_frames:
        if output_dir is None:
            raise ValueError("output_dir is required when save_frames=True")
        output_path = Path(output_dir)
        if output_path.exists() and any(output_path.iterdir()):
            raise ValueError(f"NMA output directory must be empty: {output_path}")

        log("[NMA] Saving diagnostic samples to %s...", output_dir)
        start = time.time()
        saved_files = save_mode_samples_as_pdb(samples, pdb_path, output_dir)
        manifest = {
            "schema_version": NMA_SAMPLING_POLICY_VERSION,
            "mode_count": len(eigenvalues),
            "samples_per_mode": n_frames,
            "total_samples": len(samples),
            "maximum_amplitude": amplitude,
            "solver": solver_used,
            "reference_duplicates_excluded": True,
            "samples": [sample.to_metadata() for sample in samples],
        }
        manifest["manifest_sha256"] = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        (output_path / "nma_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        timing["save"] = time.time() - start
        log("[NMA] Saved %d PDB files (%.2fs)", len(saved_files), timing["save"])

    timing["total"] = time.time() - total_start
    log(
        "[NMA] Simulation complete — %.2fs | Atoms: %d | Modes: %d | Samples: %d",
        timing["total"],
        n_atoms,
        n_modes,
        len(conformations),
    )

    return {
        "coords": coords,
        "n_atoms": n_atoms,
        "eigenvalues": eigenvalues,
        "eigenvectors": eigenvectors,
        "hessian": hessian if return_hessian else None,
        "conformations": conformations,
        "samples": samples,
        "sample_manifest": [sample.to_metadata() for sample in samples],
        "total_samples": len(samples),
        "samples_per_mode": n_frames,
        "saved_files": saved_files,
        "output_dir": str(output_dir) if output_dir else None,
        "timing": timing,
        "params": {
            "cutoff": cutoff,
            "gamma": gamma,
            "n_modes": n_modes,
            "n_frames": n_frames,
            "samples_per_mode": n_frames,
            "total_samples": len(samples),
            "amplitude": amplitude,
            "solver": solver_used,
            "sampling_policy_version": NMA_SAMPLING_POLICY_VERSION,
        },
    }


# ============================================================================
# VALIDATION HELPERS (Refactored from test_nma_math.py:152-264)
# ============================================================================


def validate_hessian(hessian: np.ndarray, n_atoms: int, cutoff: float, gamma: float) -> bool:
    """
    Validate Hessian matrix properties.

    Refactored from: test_nma_math.py validation functions
    """
    n_dof = 3 * n_atoms

    # Check symmetry
    if not np.allclose(hessian, hessian.T, atol=1e-10):
        raise ValueError("Hessian matrix is not symmetric!")

    # Check size
    if hessian.shape != (n_dof, n_dof):
        raise ValueError(f"Wrong Hessian size: {hessian.shape} (expected {(n_dof, n_dof)})")

    # Check cutoff range
    if not (12.0 <= cutoff <= 15.0):
        raise ValueError(f"Cutoff out of literature range: {cutoff} (expected 12-15 Å)")

    # Check gamma
    if gamma != 1.0:
        raise ValueError(f"Non-standard gamma: {gamma} (expected 1.0)")

    return True


def validate_eigenvalues(eigenvalues: np.ndarray) -> bool:
    """
    Validate eigenvalue properties.

    Refactored from: test_nma_math.py validation functions
    """
    # All eigenvalues must be positive (or zero for trivial modes)
    if not np.all(eigenvalues >= 0):
        raise ValueError(f"Negative eigenvalue found: {eigenvalues.min()}")

    # First mode should be lowest frequency
    if eigenvalues[0] != eigenvalues.min():
        raise ValueError("First mode is not lowest frequency!")

    # Should be in ascending order
    if not np.all(eigenvalues[:-1] <= eigenvalues[1:]):
        raise ValueError("Eigenvalues not in ascending order!")

    return True


def validate_trivial_modes(hessian: np.ndarray) -> bool:
    """
    Validate that first 6 modes are trivial (near-zero eigenvalues).

    Refactored from: test_nma_math.py lines 267-282
    """
    all_eigenvalues = np.linalg.eigvalsh(hessian)
    trivial_modes = all_eigenvalues[:6]
    max_trivial = np.max(np.abs(trivial_modes))

    if max_trivial >= 1e-6:
        raise ValueError(f"First 6 modes not trivial! (max: {max_trivial:.2e})")

    return True
