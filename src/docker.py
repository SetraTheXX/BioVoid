"""
Bio-Void Hunter: Targeted Docking Module (Phase 4)
====================================================

AutoDock Vina wrapper with Smart Grid alignment, PDBQT preparation,
binding affinity analysis, and fragment-based chemical probing.

Key Features:
- Smart Grid Box: auto-sized from pocket center + radius_geom
- PDBQT Preparation: Meeko (ligand) + in-house (receptor)
- Fragment Library: hydrophobic, polar, mixed probes
- Result Parsing: binding affinity, RMSD, pose extraction
- Pipeline Integration: dock_elite_pockets() → JSON report

References:
- Trott & Olson (2010) "AutoDock Vina: improving speed and accuracy"
- McNutt et al. (2021) "GNINA: Molecular Docking with Deep Learning"
- Forli et al. (2016) "Computational protein–ligand docking"

Phase 4.1: VinaDocking class + Smart Grid + PDBQT
Phase 4.2: Binding Affinity Analysis + Fragment Probing

Author: Bio-Void Hunter Team
Version: 0.6.0 (Phase 4)
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

# Grid Box sizing (Angstrom)
GRID_BUFFER = 6.0          # 3 A each side for ligand rotation
GRID_MIN_SIZE = 20.0       # Minimum box dimension
GRID_MAX_SIZE = 30.0       # Maximum box dimension

# Vina parameters
DEFAULT_EXHAUSTIVENESS = 8
DEFAULT_NUM_MODES = 9
DEFAULT_ENERGY_RANGE = 3.0

# Binding affinity thresholds (kcal/mol)
AFFINITY_STRONG = -8.0     # Strong binder
AFFINITY_GOOD = -6.0       # Druggable threshold
AFFINITY_WEAK = -4.0       # Weak but detectable

# RMSD thresholds (Angstrom)
RMSD_EXCELLENT = 1.0
RMSD_ACCEPTABLE = 2.0

# Fragment library - SMILES for chemical probing
FRAGMENT_LIBRARY: Dict[str, Dict[str, str]] = {
    'hydrophobic': {
        'name': 'Benzene',
        'smiles': 'c1ccccc1',
        'description': 'Aromatic hydrophobic probe',
    },
    'polar': {
        'name': 'Acetamide',
        'smiles': 'CC(N)=O',
        'description': 'Polar H-bond donor/acceptor probe',
    },
    'mixed': {
        'name': 'Phenol',
        'smiles': 'Oc1ccccc1',
        'description': 'Mixed aromatic + H-bond probe',
    },
}


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class GridBox:
    """Docking search space definition."""
    center_x: float
    center_y: float
    center_z: float
    size_x: float
    size_y: float
    size_z: float

    def to_vina_args(self) -> List[str]:
        """Convert to Vina command-line arguments."""
        return [
            '--center_x', f'{self.center_x:.3f}',
            '--center_y', f'{self.center_y:.3f}',
            '--center_z', f'{self.center_z:.3f}',
            '--size_x', f'{self.size_x:.1f}',
            '--size_y', f'{self.size_y:.1f}',
            '--size_z', f'{self.size_z:.1f}',
        ]

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class DockingPose:
    """Single docking pose result."""
    mode: int
    affinity: float           # kcal/mol
    rmsd_lb: float            # lower bound RMSD
    rmsd_ub: float            # upper bound RMSD


@dataclass
class DockingResult:
    """Complete docking result for one ligand-pocket pair."""
    pocket_id: int
    pocket_rank: int
    ligand_name: str
    ligand_smiles: str
    grid_box: Dict[str, float]
    poses: List[DockingPose] = field(default_factory=list)
    best_affinity: float = 0.0
    best_rmsd_lb: float = 0.0
    success: bool = False
    error: Optional[str] = None

    @property
    def is_druggable(self) -> bool:
        """Binding affinity < -6.0 kcal/mol = druggable."""
        return self.best_affinity < AFFINITY_GOOD

    @property
    def affinity_class(self) -> str:
        if self.best_affinity <= AFFINITY_STRONG:
            return 'strong'
        elif self.best_affinity <= AFFINITY_GOOD:
            return 'good'
        elif self.best_affinity <= AFFINITY_WEAK:
            return 'weak'
        return 'none'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'pocket_id': self.pocket_id,
            'pocket_rank': self.pocket_rank,
            'ligand_name': self.ligand_name,
            'ligand_smiles': self.ligand_smiles,
            'grid_box': self.grid_box,
            'best_affinity': self.best_affinity,
            'best_rmsd_lb': self.best_rmsd_lb,
            'affinity_class': self.affinity_class,
            'is_druggable': self.is_druggable,
            'success': self.success,
            'n_poses': len(self.poses),
            'poses': [asdict(p) for p in self.poses],
            'error': self.error,
        }


# ============================================================================
# EXCEPTIONS
# ============================================================================

class DockingError(Exception):
    """Base exception for docking failures."""
    pass


class VinaNotFoundError(DockingError):
    """Vina binary not found or not executable."""
    pass


class PDBQTError(DockingError):
    """PDBQT preparation failure."""
    pass


# ============================================================================
# PHASE 4.1: VINA DOCKING ENGINE
# ============================================================================

class VinaDocking:
    """
    AutoDock Vina wrapper with Smart Grid alignment.

    Usage:
        docker = VinaDocking(vina_bin='tools/vina/vina.exe')
        grid = docker.calculate_grid_box(pocket)
        receptor_pdbqt = docker.prepare_receptor('protein.pdb')
        ligand_pdbqt = docker.prepare_ligand_from_smiles('c1ccccc1')
        result = docker.run_docking(receptor_pdbqt, ligand_pdbqt, grid)
    """

    def __init__(self,
                 vina_bin: str = 'tools/vina/vina.exe',
                 output_dir: str = 'data/docking',
                 exhaustiveness: int = DEFAULT_EXHAUSTIVENESS,
                 num_modes: int = DEFAULT_NUM_MODES,
                 energy_range: float = DEFAULT_ENERGY_RANGE):
        """
        Initialize Vina docking engine.

        Args:
            vina_bin: Path to Vina executable
            output_dir: Directory for docking output files
            exhaustiveness: Search thoroughness (higher = slower + better)
            num_modes: Maximum number of binding modes
            energy_range: Maximum energy difference from best mode (kcal/mol)
        """
        self.vina_bin = self._resolve_vina_path(vina_bin)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.exhaustiveness = exhaustiveness
        self.num_modes = num_modes
        self.energy_range = energy_range

        # Verify Vina is functional
        self._verify_vina()

    # ------------------------------------------------------------------
    # Vina binary management
    # ------------------------------------------------------------------

    def _resolve_vina_path(self, vina_bin: str) -> Path:
        """Resolve Vina binary path, checking multiple locations."""
        # Try direct path
        p = Path(vina_bin)
        if p.exists() and p.is_file():
            return p.resolve()

        # Try relative to workspace
        workspace = Path(__file__).parent.parent
        candidates = [
            workspace / vina_bin,
            workspace / 'tools' / 'vina' / 'vina.exe',
            workspace / 'tools' / 'vina' / 'vina',
        ]
        for c in candidates:
            if c.exists() and c.is_file():
                return c.resolve()

        # Try PATH
        which_result = shutil.which('vina')
        if which_result:
            return Path(which_result).resolve()

        raise VinaNotFoundError(
            f"Vina binary not found at '{vina_bin}' or in PATH. "
            "Install AutoDock Vina >= 1.2.5 and place in tools/vina/"
        )

    def _verify_vina(self):
        """Verify Vina binary is functional and check version."""
        try:
            result = subprocess.run(
                [str(self.vina_bin), '--version'],
                capture_output=True, text=True, timeout=10
            )
            version_str = result.stdout.strip() + result.stderr.strip()
            logger.info(f"Vina verified: {version_str}")

            # Extract version number
            match = re.search(r'v?(\d+\.\d+\.\d+)', version_str)
            if match:
                ver = match.group(1)
                major, minor, _patch = (int(x) for x in ver.split('.'))
                if (major, minor) < (1, 2):
                    logger.warning(
                        f"Vina version {ver} is old. v1.2.5+ recommended."
                    )
                self.vina_version = ver
            else:
                self.vina_version = 'unknown'

        except FileNotFoundError:
            raise VinaNotFoundError(
                f"Cannot execute Vina at '{self.vina_bin}'"
            )
        except subprocess.TimeoutExpired:
            raise VinaNotFoundError("Vina binary timed out on --version")

    # ------------------------------------------------------------------
    # Smart Grid Box
    # ------------------------------------------------------------------

    def calculate_grid_box(self, pocket: Dict[str, Any]) -> GridBox:
        """
        Calculate optimal docking grid box from pocket metadata.

        Formula: Box_Size = max(GRID_MIN, min(GRID_MAX, radius_geom * 2 + BUFFER))

        The 6A buffer (3A each side) allows ligand rotation within
        the search space - recommended by Vina documentation.

        Args:
            pocket: Cavity dict with 'center' and 'radius_geom'

        Returns:
            GridBox with center and size coordinates
        """
        center = pocket.get('center', [0, 0, 0])
        if isinstance(center, np.ndarray):
            center = center.tolist()

        radius = float(pocket.get('radius_geom', 10.0))

        # Smart sizing: radius * 2 + buffer, clamped to [MIN, MAX]
        raw_size = radius * 2.0 + GRID_BUFFER
        box_size = max(GRID_MIN_SIZE, min(GRID_MAX_SIZE, raw_size))

        return GridBox(
            center_x=round(center[0], 3),
            center_y=round(center[1], 3),
            center_z=round(center[2], 3),
            size_x=round(box_size, 1),
            size_y=round(box_size, 1),
            size_z=round(box_size, 1),
        )

    # ------------------------------------------------------------------
    # PDBQT Preparation
    # ------------------------------------------------------------------

    def prepare_receptor(self, pdb_path: str,
                         output_path: Optional[str] = None) -> Path:
        """
        Convert PDB to PDBQT format for Vina receptor.

        Strips waters, adds Gasteiger charges, assigns AD4 atom types.
        Uses a simplified approach for maximum compatibility.

        Args:
            pdb_path: Path to input PDB file
            output_path: Optional output PDBQT path

        Returns:
            Path to generated PDBQT file
        """
        pdb_file = Path(pdb_path)
        if not pdb_file.exists():
            raise PDBQTError(f"PDB file not found: {pdb_file}")

        if output_path is None:
            out_file = self.output_dir / f"{pdb_file.stem}_receptor.pdbqt"
        else:
            out_file = Path(output_path)

        out_file.parent.mkdir(parents=True, exist_ok=True)

        # Read PDB and convert to PDBQT
        lines = pdb_file.read_text().splitlines()
        pdbqt_lines = []

        for line in lines:
            if not (line.startswith('ATOM') or line.startswith('HETATM')):
                continue

            # Skip water molecules
            res_name = line[17:20].strip()
            if res_name in ('HOH', 'WAT', 'TIP', 'SOL'):
                continue

            # Skip hydrogen atoms
            atom_name = line[12:16].strip()
            element = line[76:78].strip() if len(line) >= 78 else ''
            if element == 'H' or (not element and atom_name.startswith('H')):
                continue

            # Determine AD4 atom type from element
            ad4_type = self._get_ad4_atom_type(
                element or atom_name[0], res_name
            )

            # Build PDBQT line (PDB + charge + type)
            pdbqt_line = line[:54]  # Coordinates
            # Pad to column 55 if needed
            pdbqt_line = pdbqt_line.ljust(54)
            # Add occupancy + B-factor (or keep original)
            if len(line) >= 66:
                pdbqt_line += line[54:66]
            else:
                pdbqt_line += '  1.00  0.00'
            # Gasteiger charge placeholder + AD4 type
            pdbqt_line += f'    +0.000 {ad4_type:<2s}'
            pdbqt_lines.append(pdbqt_line)

        if not pdbqt_lines:
            raise PDBQTError(f"No valid atoms found in {pdb_file}")

        out_file.write_text('\n'.join(pdbqt_lines) + '\n')
        logger.info(
            f"Receptor PDBQT: {out_file} ({len(pdbqt_lines)} atoms)"
        )
        return out_file

    def _get_ad4_atom_type(self, element: str,
                           res_name: str = '') -> str:
        """Map element to AutoDock 4 atom type."""
        ad4_map = {
            'C': 'C',
            'N': 'NA',   # N acceptor (general)
            'O': 'OA',   # O acceptor
            'S': 'SA',   # S acceptor
            'P': 'P',
            'F': 'F',
            'CL': 'Cl',
            'BR': 'Br',
            'I': 'I',
            'ZN': 'Zn',
            'FE': 'Fe',
            'MG': 'Mg',
            'MN': 'Mn',
            'CA': 'Ca',
        }
        elem_upper = element.upper().strip()
        return ad4_map.get(
            elem_upper,
            elem_upper[:2] if len(elem_upper) >= 2 else elem_upper
        )

    def prepare_ligand_from_smiles(self, smiles: str,
                                   name: str = 'ligand',
                                   output_path: Optional[str] = None,
                                   ) -> Path:
        """
        Convert SMILES to PDBQT using Meeko + RDKit.

        Pipeline: SMILES -> RDKit Mol -> 3D coords -> Meeko -> PDBQT

        Args:
            smiles: SMILES string of ligand
            name: Ligand name for file naming
            output_path: Optional output path

        Returns:
            Path to ligand PDBQT file
        """
        try:
            from rdkit.Chem import MolFromSmiles, AddHs, AllChem  # type: ignore
            from meeko import MoleculePreparation, PDBQTWriterLegacy  # type: ignore
        except ImportError as e:
            raise PDBQTError(
                f"RDKit/Meeko required for SMILES to PDBQT: {e}. "
                "Install: conda install -c conda-forge rdkit && pip install meeko"
            )

        if output_path is None:
            out_file = self.output_dir / f"{name}.pdbqt"
        else:
            out_file = Path(output_path)

        out_file.parent.mkdir(parents=True, exist_ok=True)

        # SMILES -> RDKit Mol
        mol = MolFromSmiles(smiles)
        if mol is None:
            raise PDBQTError(f"Invalid SMILES: '{smiles}'")

        # Add hydrogens and generate 3D coords
        mol = AddHs(mol)
        embed_result = AllChem.EmbedMolecule(mol, AllChem.ETKDGv3())  # type: ignore[attr-defined]
        if embed_result == -1:
            raise PDBQTError(f"3D embedding failed for '{smiles}'")

        AllChem.MMFFOptimizeMolecule(mol, maxIters=200)  # type: ignore[attr-defined]

        # Meeko preparation
        preparator = MoleculePreparation()
        mol_setups = preparator.prepare(mol)

        # Write PDBQT
        for setup in mol_setups:
            pdbqt_string, is_ok, error_msg = PDBQTWriterLegacy.write_string(
                setup
            )
            if is_ok:
                out_file.write_text(pdbqt_string)
                logger.info(f"Ligand PDBQT: {out_file}")
                return out_file
            else:
                raise PDBQTError(
                    f"Meeko PDBQT write failed: {error_msg}"
                )

        raise PDBQTError(f"No valid Meeko setup for '{smiles}'")
    # ------------------------------------------------------------------
    # Docking Execution
    # ------------------------------------------------------------------

    def run_docking(self,
                    receptor_pdbqt: str | Path,
                    ligand_pdbqt: str | Path,
                    grid_box: GridBox,
                    output_name: str = 'docking_out') -> DockingResult:
        """
        Run AutoDock Vina docking.

        Args:
            receptor_pdbqt: Path to receptor PDBQT
            ligand_pdbqt: Path to ligand PDBQT
            grid_box: Search space definition
            output_name: Base name for output files

        Returns:
            DockingResult with poses and binding affinities
        """
        receptor_pdbqt = Path(receptor_pdbqt)
        ligand_pdbqt = Path(ligand_pdbqt)
        output_pdbqt = self.output_dir / f"{output_name}.pdbqt"

        if not receptor_pdbqt.exists():
            raise DockingError(f"Receptor not found: {receptor_pdbqt}")
        if not ligand_pdbqt.exists():
            raise DockingError(f"Ligand not found: {ligand_pdbqt}")

        # Build Vina command
        cmd = [
            str(self.vina_bin),
            '--receptor', str(receptor_pdbqt),
            '--ligand', str(ligand_pdbqt),
            '--out', str(output_pdbqt),
            '--exhaustiveness', str(self.exhaustiveness),
            '--num_modes', str(self.num_modes),
            '--energy_range', str(self.energy_range),
        ] + grid_box.to_vina_args()

        logger.info(f"Running Vina: {' '.join(cmd)}")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 min timeout
            )

            # Parse stdout for results
            poses = self._parse_vina_stdout(proc.stdout + proc.stderr)

            if proc.returncode != 0 and not poses:
                return DockingResult(
                    pocket_id=0,
                    pocket_rank=0,
                    ligand_name=output_name,
                    ligand_smiles='',
                    grid_box=grid_box.to_dict(),
                    error=(
                        f"Vina returned code {proc.returncode}: "
                        f"{proc.stderr[:200]}"
                    ),
                )

            # Build result
            best_pose = poses[0] if poses else None
            return DockingResult(
                pocket_id=0,
                pocket_rank=0,
                ligand_name=output_name,
                ligand_smiles='',
                grid_box=grid_box.to_dict(),
                poses=poses,
                best_affinity=best_pose.affinity if best_pose else 0.0,
                best_rmsd_lb=best_pose.rmsd_lb if best_pose else 0.0,
                success=True,
            )

        except subprocess.TimeoutExpired:
            return DockingResult(
                pocket_id=0,
                pocket_rank=0,
                ligand_name=output_name,
                ligand_smiles='',
                grid_box=grid_box.to_dict(),
                error="Vina timed out (300s)",
            )

    def _parse_vina_stdout(self, output: str) -> List[DockingPose]:
        """
        Parse Vina stdout for binding modes.

        Vina output format:
        -----+------------+----------+----------
         mode |   affinity  | dist from best mode
              | (kcal/mol)  | rmsd l.b.| rmsd u.b.
        -----+------------+----------+----------
           1       -7.2          0.000     0.000
           2       -6.8          1.234     2.345
        """
        poses = []
        pattern = re.compile(
            r'^\s*(\d+)\s+([-.\d]+)\s+([-.\d]+)\s+([-.\d]+)',
            re.MULTILINE
        )

        for match in pattern.finditer(output):
            mode = int(match.group(1))
            affinity = float(match.group(2))
            rmsd_lb = float(match.group(3))
            rmsd_ub = float(match.group(4))
            poses.append(DockingPose(
                mode=mode,
                affinity=affinity,
                rmsd_lb=rmsd_lb,
                rmsd_ub=rmsd_ub,
            ))

        return poses

    # ------------------------------------------------------------------
    # High-level API
    # ------------------------------------------------------------------

    def dock_pocket(self,
                    pocket: Dict[str, Any],
                    receptor_pdbqt: str | Path,
                    ligand_smiles: str,
                    ligand_name: str = 'probe') -> DockingResult:
        """
        Dock a single ligand into a single pocket.

        Args:
            pocket: Cavity dict with 'center', 'radius_geom', 'rank', 'id'
            receptor_pdbqt: Prepared receptor PDBQT path
            ligand_smiles: SMILES of ligand to dock
            ligand_name: Human-readable ligand name

        Returns:
            DockingResult
        """
        pocket_id = pocket.get('id', 0)
        pocket_rank = pocket.get('rank', 0)

        # Calculate grid
        grid = self.calculate_grid_box(pocket)

        # Prepare ligand
        safe_name = re.sub(r'[^\w]', '_', ligand_name)
        ligand_pdbqt = self.prepare_ligand_from_smiles(
            ligand_smiles,
            name=f"pocket{pocket_id}_{safe_name}",
        )

        # Run docking
        output_name = f"pocket{pocket_id}_{safe_name}_out"
        result = self.run_docking(
            receptor_pdbqt, ligand_pdbqt, grid, output_name
        )

        # Enrich result with pocket info
        result.pocket_id = pocket_id
        result.pocket_rank = pocket_rank
        result.ligand_name = ligand_name
        result.ligand_smiles = ligand_smiles

        return result

    def probe_pocket(self,
                     pocket: Dict[str, Any],
                     receptor_pdbqt: str | Path,
                     fragments: Optional[Dict[str, Dict[str, str]]] = None,
                     ) -> List[DockingResult]:
        """
        Chemical probing: dock multiple fragment types into a pocket.

        Tests pocket character (hydrophobic/polar/mixed) using small
        molecular probes from the fragment library.

        Args:
            pocket: Cavity dict
            receptor_pdbqt: Prepared receptor PDBQT
            fragments: Custom fragment library (default: FRAGMENT_LIBRARY)

        Returns:
            List of DockingResults, one per fragment
        """
        if fragments is None:
            fragments = FRAGMENT_LIBRARY

        results = []
        for frag_type, frag_info in fragments.items():
            logger.info(
                f"Probing pocket {pocket.get('id', '?')} with "
                f"{frag_info['name']} ({frag_type})"
            )
            result = self.dock_pocket(
                pocket,
                receptor_pdbqt,
                ligand_smiles=frag_info['smiles'],
                ligand_name=f"{frag_type}_{frag_info['name']}",
            )
            results.append(result)

        return results


# ============================================================================
# PHASE 4.2: HIGH-LEVEL PIPELINE API
# ============================================================================

def dock_elite_pockets(cavities: List[Dict[str, Any]],
                       protein_pdb: str,
                       profile: str = 'default',
                       top_n: int = 5,
                       vina_bin: str = 'tools/vina/vina.exe',
                       output_dir: str = 'data/docking',
                       exhaustiveness: int = DEFAULT_EXHAUSTIVENESS,
                       ) -> Dict[str, Any]:
    """
    Dock fragment probes into the top-ranked pockets.

    Main pipeline entry point for Phase 4 integration.

    Args:
        cavities: Ranked cavities from rank_pockets()
        protein_pdb: Path to protein PDB file
        profile: Scoring profile used for ranking
        top_n: Number of top pockets to dock
        vina_bin: Path to Vina binary
        output_dir: Output directory
        exhaustiveness: Vina search thoroughness

    Returns:
        Dict with docking report:
        - 'protein': PDB path
        - 'profile': scoring profile
        - 'n_pockets_docked': int
        - 'results': List[DockingResult dicts]
        - 'summary': aggregate statistics
    """
    docker = VinaDocking(
        vina_bin=vina_bin,
        output_dir=output_dir,
        exhaustiveness=exhaustiveness,
    )

    # Prepare receptor once
    receptor_pdbqt = docker.prepare_receptor(protein_pdb)

    # Select top pockets (already ranked by bio_score)
    elite = cavities[:top_n]

    all_results: List[Dict[str, Any]] = []
    best_overall = 0.0
    druggable_count = 0

    for pocket in elite:
        pocket_id = pocket.get('id', 0)
        pocket_rank = pocket.get('rank', 0)
        bio_score = pocket.get('bio_score', 0.0)

        logger.info(
            f"Docking pocket #{pocket_rank} (id={pocket_id}, "
            f"bio_score={bio_score:.4f})"
        )

        # Chemical probing with 3 fragments
        probe_results = docker.probe_pocket(pocket, receptor_pdbqt)

        for r in probe_results:
            result_dict = r.to_dict()
            result_dict['bio_score'] = bio_score
            all_results.append(result_dict)

            if r.success and r.best_affinity < best_overall:
                best_overall = r.best_affinity
            if r.is_druggable:
                druggable_count += 1

    # Summary
    n_total = len(all_results)
    n_success = sum(1 for r in all_results if r.get('success', False))

    report = {
        'protein': str(protein_pdb),
        'profile': profile,
        'vina_version': docker.vina_version,
        'n_pockets_docked': len(elite),
        'n_fragment_docks': n_total,
        'n_successful': n_success,
        'n_druggable': druggable_count,
        'best_affinity': best_overall,
        'exhaustiveness': exhaustiveness,
        'results': all_results,
    }

    # Save report
    report_path = Path(output_dir) / 'docking_report.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)

    logger.info(
        f"Docking complete: {n_success}/{n_total} successful, "
        f"{druggable_count} druggable, best={best_overall:.1f} kcal/mol"
    )

    return report


def parse_vina_output_file(pdbqt_path: str) -> List[DockingPose]:
    """
    Parse a Vina output PDBQT file for pose data.

    Extracts affinity and RMSD from MODEL/REMARK lines.

    Args:
        pdbqt_path: Path to Vina output PDBQT

    Returns:
        List of DockingPose objects
    """
    path = Path(pdbqt_path)
    if not path.exists():
        return []

    content = path.read_text()
    poses = []

    # REMARK VINA RESULT:    -7.2      0.000      0.000
    pattern = re.compile(
        r'REMARK VINA RESULT:\s+([-.\d]+)\s+([-.\d]+)\s+([-.\d]+)'
    )

    mode = 0
    for match in pattern.finditer(content):
        mode += 1
        poses.append(DockingPose(
            mode=mode,
            affinity=float(match.group(1)),
            rmsd_lb=float(match.group(2)),
            rmsd_ub=float(match.group(3)),
        ))

    return poses


# ============================================================================
# PHASE 4.2: INTERACTION ANALYSIS
# ============================================================================

# H-bond criteria (distance-based, no PLIP dependency)
HBOND_DISTANCE_MAX = 3.5     # Angstrom: D-A max distance
HBOND_DISTANCE_MIN = 2.5     # Angstrom: D-A min distance
VDW_DISTANCE_MAX = 4.0       # Angstrom: Van der Waals contact

# H-bond donor/acceptor elements
HBOND_DONORS = {'N', 'O', 'S'}
HBOND_ACCEPTORS = {'N', 'O', 'S', 'F'}


@dataclass
class Interaction:
    """Single protein-ligand interaction."""
    interaction_type: str     # 'hbond', 'vdw', 'hydrophobic'
    protein_atom: str         # e.g. "ALA_A_42_N"
    ligand_atom: str          # e.g. "C1"
    distance: float           # Angstrom
    protein_residue: str      # e.g. "ALA42"
    protein_element: str      # e.g. "N"
    ligand_element: str       # e.g. "C"


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


def _parse_pdbqt_atoms(pdbqt_path: str | Path
                       ) -> List[Dict[str, Any]]:
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
            # Element: last 2 chars or derive from atom name
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


def analyze_interactions(receptor_pdbqt: str | Path,
                         docked_ligand_pdbqt: str | Path,
                         pose_index: int = 0,
                         ) -> InteractionReport:
    """
    Analyze protein-ligand interactions from docked output.

    Distance-based detection (no PLIP dependency):
    - H-bonds: donor/acceptor atoms within 2.5-3.5 Angstrom
    - VdW contacts: non-bonded atoms within 4.0 Angstrom
    - Hydrophobic: carbon-carbon contacts within 4.0 Angstrom

    Args:
        receptor_pdbqt: Path to receptor PDBQT
        docked_ligand_pdbqt: Path to Vina output PDBQT (may have multiple MODELs)
        pose_index: Which pose to analyze (0 = best)

    Returns:
        InteractionReport with classified interactions
    """
    rec_atoms = _parse_pdbqt_atoms(receptor_pdbqt)
    lig_atoms = _extract_pose_atoms(docked_ligand_pdbqt, pose_index)

    if not rec_atoms or not lig_atoms:
        return InteractionReport()

    # Build coordinate arrays for fast distance calculation
    rec_coords = np.array([[a['x'], a['y'], a['z']] for a in rec_atoms])
    lig_coords = np.array([[a['x'], a['y'], a['z']] for a in lig_atoms])

    interactions: List[Interaction] = []
    contact_residues_set: set[str] = set()

    # For each ligand atom, check distances to receptor atoms
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

            # Classify interaction
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


def _extract_pose_atoms(pdbqt_path: str | Path,
                        pose_index: int = 0,
                        ) -> List[Dict[str, Any]]:
    """Extract atoms from a specific MODEL in a multi-model PDBQT."""
    path = Path(pdbqt_path)
    if not path.exists():
        return []

    content = path.read_text()

    # Split by MODEL/ENDMDL
    models = re.split(r'MODEL\s+\d+', content)
    # Filter non-empty models (first split may be empty)
    models = [m for m in models if 'ATOM' in m or 'HETATM' in m]

    if not models:
        # Single model (no MODEL lines)
        return _parse_pdbqt_atoms(pdbqt_path)

    if pose_index >= len(models):
        pose_index = 0

    # Write selected model to temp and parse
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt',
                                     delete=False) as f:
        f.write(models[pose_index])
        tmp_path = f.name

    try:
        atoms = _parse_pdbqt_atoms(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return atoms


# ============================================================================
# PHASE 4.2: KNOWN LIGAND VALIDATION (1CBS)
# ============================================================================

# 1CBS: Cellular Retinoic Acid Binding Protein + Retinoic Acid
# Retinoic Acid SMILES (all-trans-retinoic acid)
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

    # Build pocket dict
    known_pocket = {
        'id': 0,
        'rank': 0,
        'center': pocket_center,
        'radius_geom': pocket_radius,
    }

    # Prepare receptor
    receptor_pdbqt = docker.prepare_receptor(pdb_path)

    # Dock known ligand
    result = docker.dock_pocket(
        known_pocket, receptor_pdbqt,
        ligand_smiles=ligand_smiles,
        ligand_name='known_ligand',
    )

    # Interaction analysis on the best pose
    interaction_report = InteractionReport()
    docked_output = docker.output_dir / "pocket0_known_ligand_out.pdbqt"
    if docked_output.exists():
        interaction_report = analyze_interactions(
            receptor_pdbqt, docked_output, pose_index=0
        )

    # Build validation report
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

    # Save validation report
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


# ============================================================================
# PHASE 4.2: NMA FRAME DOCKING VALIDATION
# ============================================================================

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
        frame_indices: Specific frame indices to dock (default: sampled)
        n_sample: Number of frames to sample if frame_indices not given
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

    # Find all frame files
    frame_files = sorted(frames_path.glob('frame_*.pdb'))
    if not frame_files:
        return {'error': f"No frame_*.pdb files in {frames_dir}",
                'success': False}

    # Select frame indices
    if frame_indices is None:
        total = len(frame_files)
        if total <= n_sample:
            selected = list(range(total))
        else:
            # Evenly spaced sampling
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
            # Prepare receptor for this frame
            receptor_pdbqt = docker.prepare_receptor(
                str(frame_file),
                output_path=str(
                    docker.output_dir / f"{frame_name}_receptor.pdbqt"
                ),
            )

            # Dock
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

    # Statistics
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
        'pocket_stable': consistency >= 0.6,   # 60%+ = stable
        'frame_results': frame_results,
        'success': True,
    }

    # Save
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
