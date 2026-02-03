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

import numpy as np
import time
from pathlib import Path
from typing import List, Tuple, Optional
import biotite.structure.io.pdb as pdb
import biotite.structure as struc


# ============================================================================
# CONSTANTS (From literature - DO NOT CHANGE!)
# ============================================================================

DEFAULT_CUTOFF = 15.0  # Angstrom (Atilgan et al. 2001)
DEFAULT_GAMMA = 1.0    # Spring constant (standard)
MIN_ATOMS = 50         # Minimum protein size
MAX_ATOMS = 5000       # Maximum for consumer hardware


# ============================================================================
# 1. STRUCTURE LOADING (Refactored from test_nma_math.py:25-50)
# ============================================================================

def load_ca_atoms(pdb_path: str) -> Tuple[np.ndarray, int]:
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
    ca_filter = (structure.atom_name == "CA")
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

def build_anm_hessian(coords: np.ndarray, cutoff: float = DEFAULT_CUTOFF, 
                      gamma: float = DEFAULT_GAMMA) -> np.ndarray:
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
                i_start, i_end = 3*i, 3*(i+1)
                j_start, j_end = 3*j, 3*(j+1)
                
                hessian[i_start:i_end, j_start:j_end] -= sub_matrix
                hessian[j_start:j_end, i_start:i_end] -= sub_matrix
                
                hessian[i_start:i_end, i_start:i_end] += sub_matrix
                hessian[j_start:j_end, j_start:j_end] += sub_matrix
    
    return hessian


# ============================================================================
# 3. NORMAL MODES (Refactored from test_nma_math.py:118-145)
# ============================================================================

def calculate_normal_modes(hessian: np.ndarray, n_modes: int = 10) -> Tuple[np.ndarray, np.ndarray]:
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
    # Eigenvalue decomposition
    eigenvalues, eigenvectors = np.linalg.eigh(hessian)
    
    # Skip first 6 trivial modes (translation + rotation)
    eigenvalues = eigenvalues[6:6+n_modes]
    eigenvectors = eigenvectors[:, 6:6+n_modes]
    
    return eigenvalues, eigenvectors


# ============================================================================
# 4. CONFORMATION GENERATION (Refactored from phase1_integration_test.py:143-161)
# ============================================================================

def generate_conformations(coords: np.ndarray, eigenvectors: np.ndarray,
                          n_frames: int = 10, amplitude: float = 3.0) -> List[np.ndarray]:
    """
    Generate protein conformations along normal modes.
    
    Refactored from: phase1_integration_test.py lines 143-161
    
    Uses sinusoidal motion along each mode to create "breathing" effect.
    
    Args:
        coords: Original CA coordinates (N x 3)
        eigenvectors: Normal mode eigenvectors (3N x n_modes)
        n_frames: Frames per mode
        amplitude: Maximum displacement (Angstrom)
        
    Returns:
        conformations: List of coordinate arrays
    """
    n_atoms = len(coords)
    n_modes = eigenvectors.shape[1]
    conformations = []
    
    for mode_idx in range(n_modes):
        # Get mode vector and reshape to (N, 3)
        mode = eigenvectors[:, mode_idx].reshape(n_atoms, 3)
        
        for frame in range(n_frames):
            # Sinusoidal motion along mode
            t = (frame / n_frames) * 2 * np.pi
            displacement = amplitude * np.sin(t) * mode
            new_coords = coords + displacement
            conformations.append(new_coords)
    
    return conformations


# ============================================================================
# 5. PDB FILE SAVING
# ============================================================================

def save_frames_as_pdb(conformations: List[np.ndarray], 
                       template_pdb: str,
                       output_dir: Path) -> List[Path]:
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
    ca_filter = (template.atom_name == "CA")
    ca_template = template[ca_filter]
    
    saved_files = []
    
    for i, coords in enumerate(conformations):
        # Create new structure with updated coordinates
        frame = ca_template.copy()
        frame.coord = coords
        
        # Save as PDB
        frame_path = output_dir / f"frame_{i+1:03d}.pdb"
        pdb_out = pdb.PDBFile()
        pdb_out.set_structure(frame)
        pdb_out.write(str(frame_path))
        
        saved_files.append(frame_path)
    
    return saved_files


# ============================================================================
# 6. MAIN SIMULATION FUNCTION
# ============================================================================

def run_nma_simulation(pdb_path: str, 
                       n_modes: int = 10,
                       n_frames: int = 10,
                       amplitude: float = 3.0,
                       cutoff: float = DEFAULT_CUTOFF,
                       gamma: float = DEFAULT_GAMMA,
                       output_dir: Optional[Path] = None,
                       save_frames: bool = True,
                       verbose: bool = True) -> dict:
    """
    Run complete NMA simulation pipeline.
    
    This is the main entry point for the NMA dynamics engine.
    
    Args:
        pdb_path: Path to input PDB file
        n_modes: Number of normal modes to calculate
        n_frames: Frames per mode
        amplitude: Displacement amplitude (Angstrom)
        cutoff: ANM cutoff distance (Angstrom)
        gamma: Spring force constant
        output_dir: Directory for output frames (default: data/frames/{pdb_id}/)
        save_frames: Whether to save PDB files
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
    
    # 1. Load structure
    if verbose:
        print(f"\n{'='*60}")
        print(f"🧬 NMA DYNAMICS ENGINE")
        print(f"{'='*60}")
        print(f"\n1️⃣ Loading structure: {pdb_path}")
    
    start = time.time()
    coords, n_atoms = load_ca_atoms(pdb_path)
    timing['load'] = time.time() - start
    
    if verbose:
        print(f"   ✅ Loaded {n_atoms} CA atoms ({timing['load']:.2f}s)")
    
    # 2. Build Hessian
    if verbose:
        print(f"\n2️⃣ Building Hessian matrix ({3*n_atoms}x{3*n_atoms})...")
    
    start = time.time()
    hessian = build_anm_hessian(coords, cutoff=cutoff, gamma=gamma)
    timing['hessian'] = time.time() - start
    
    if verbose:
        print(f"   ✅ Hessian built ({timing['hessian']:.2f}s)")
    
    # 3. Calculate modes
    if verbose:
        print(f"\n3️⃣ Calculating {n_modes} normal modes...")
    
    start = time.time()
    eigenvalues, eigenvectors = calculate_normal_modes(hessian, n_modes=n_modes)
    timing['modes'] = time.time() - start
    
    if verbose:
        print(f"   ✅ Modes calculated ({timing['modes']:.2f}s)")
        print(f"   📊 Frequency range: {eigenvalues[0]:.4f} - {eigenvalues[-1]:.4f}")
    
    # 4. Generate conformations
    if verbose:
        total_frames = n_modes * n_frames
        print(f"\n4️⃣ Generating {total_frames} conformations ({n_modes} modes × {n_frames} frames)...")
    
    start = time.time()
    conformations = generate_conformations(coords, eigenvectors, n_frames=n_frames, amplitude=amplitude)
    timing['conformations'] = time.time() - start
    
    if verbose:
        print(f"   ✅ Generated {len(conformations)} frames ({timing['conformations']:.2f}s)")
    
    # 5. Save frames (optional)
    saved_files = []
    if save_frames:
        if output_dir is None:
            pdb_id = Path(pdb_path).stem.replace('pdb', '')
            project_root = Path(__file__).parent.parent
            output_dir = project_root / "data" / "frames" / pdb_id
        
        if verbose:
            print(f"\n5️⃣ Saving frames to {output_dir}...")
        
        start = time.time()
        saved_files = save_frames_as_pdb(conformations, pdb_path, output_dir)
        timing['save'] = time.time() - start
        
        if verbose:
            print(f"   ✅ Saved {len(saved_files)} PDB files ({timing['save']:.2f}s)")
    
    # Total time
    timing['total'] = time.time() - total_start
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"✅ NMA SIMULATION COMPLETE")
        print(f"   Total time: {timing['total']:.2f}s")
        print(f"   Atoms: {n_atoms} | Modes: {n_modes} | Frames: {len(conformations)}")
        print(f"{'='*60}")
    
    return {
        'coords': coords,
        'n_atoms': n_atoms,
        'eigenvalues': eigenvalues,
        'eigenvectors': eigenvectors,
        'hessian': hessian,  # For validation
        'conformations': conformations,
        'saved_files': saved_files,
        'output_dir': str(output_dir) if output_dir else None,
        'timing': timing,
        'params': {
            'cutoff': cutoff,
            'gamma': gamma,
            'n_modes': n_modes,
            'n_frames': n_frames,
            'amplitude': amplitude
        }
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
