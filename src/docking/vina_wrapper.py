"""
Bio-Void Hunter: Vina Docking Wrapper
======================================

AutoDock Vina wrapper with Smart Grid alignment, PDBQT preparation,
and fragment-based chemical probing.

Extracted from docker.py during Faz 6 pre-refactoring.
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

GRID_BUFFER = 6.0
GRID_MIN_SIZE = 20.0
GRID_MAX_SIZE = 30.0

DEFAULT_EXHAUSTIVENESS = 4
DEFAULT_NUM_MODES = 5
DEFAULT_ENERGY_RANGE = 3.0

AFFINITY_STRONG = -8.0
AFFINITY_GOOD = -6.0
AFFINITY_WEAK = -4.0

RMSD_EXCELLENT = 1.0
RMSD_ACCEPTABLE = 2.0

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
            '--center_x', str(round(self.center_x, 3)),
            '--center_y', str(round(self.center_y, 3)),
            '--center_z', str(round(self.center_z, 3)),
            '--size_x', str(round(self.size_x, 3)),
            '--size_y', str(round(self.size_y, 3)),
            '--size_z', str(round(self.size_z, 3)),
        ]

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class DockingPose:
    """Single docking pose result."""
    mode: int
    affinity: float
    rmsd_lb: float
    rmsd_ub: float


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
        return self.success and self.best_affinity < AFFINITY_GOOD

    @property
    def affinity_class(self) -> str:
        if not self.success:
            return 'failed'
        if self.best_affinity < AFFINITY_STRONG:
            return 'strong'
        if self.best_affinity < AFFINITY_GOOD:
            return 'good'
        if self.best_affinity < AFFINITY_WEAK:
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
            'is_druggable': self.is_druggable,
            'affinity_class': self.affinity_class,
            'success': self.success,
            'error': self.error,
            'n_poses': len(self.poses),
            'poses': [asdict(p) for p in self.poses],
        }


# ============================================================================
# EXCEPTIONS
# ============================================================================

class DockingError(Exception):
    """Base exception for docking failures."""


class VinaNotFoundError(DockingError):
    """Vina binary not found or not executable."""


class PDBQTError(DockingError):
    """PDBQT preparation failure."""


# ============================================================================
# VINA DOCKING ENGINE
# ============================================================================

class VinaDocking:
    """AutoDock Vina wrapper with Smart Grid alignment.

    Usage:
        docker = VinaDocking(vina_bin='tools/vina/vina.exe')
        grid = docker.calculate_grid_box(pocket)
        result = docker.dock_pocket(pocket, receptor_pdbqt, smiles)
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
            num_modes: Number of binding modes to generate
            energy_range: Max energy difference from best mode (kcal/mol)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.exhaustiveness = exhaustiveness
        self.num_modes = num_modes
        self.energy_range = energy_range

        self.vina_path = self._resolve_vina_path(vina_bin)
        self.vina_version = self._verify_vina()

    def _resolve_vina_path(self, vina_bin: str) -> Path:
        """Resolve Vina binary path, checking multiple locations."""
        candidates = [
            Path(vina_bin),
            Path('tools/vina/vina.exe'),
            Path('tools/vina/vina'),
        ]

        vina_in_path = shutil.which('vina')
        if vina_in_path:
            candidates.insert(0, Path(vina_in_path))

        for p in candidates:
            if p.exists() and p.is_file():
                return p.resolve()

        raise VinaNotFoundError(
            f"Vina binary not found. Tried: "
            f"{[str(c) for c in candidates]}"
        )

    def _verify_vina(self) -> str:
        """Verify Vina binary is functional and check version."""
        try:
            result = subprocess.run(
                [str(self.vina_path), '--version'],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = result.stdout + result.stderr
            version_match = re.search(
                r'(?:AutoDock Vina|vina)\s+v?(\d+\.\d+\.\d+)', output, re.I
            )
            version = version_match.group(1) if version_match else 'unknown'
            logger.info(f"Vina verified: v{version} at {self.vina_path}")
            return version
        except subprocess.TimeoutExpired:
            logger.warning("Vina version check timed out")
            return 'timeout'
        except Exception as e:
            logger.warning(f"Vina verification failed: {e}")
            return 'unverified'

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
        radius = pocket.get('radius_geom', 5.0)

        box_size = max(GRID_MIN_SIZE, min(GRID_MAX_SIZE, radius * 2 + GRID_BUFFER))

        return GridBox(
            center_x=float(center[0]),
            center_y=float(center[1]),
            center_z=float(center[2]),
            size_x=box_size,
            size_y=box_size,
            size_z=box_size,
        )

    def prepare_receptor(self, pdb_path: str,
                         output_path: Optional[str] = None) -> str:
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
        pdb = Path(pdb_path)
        if not pdb.exists():
            raise PDBQTError(f"PDB file not found: {pdb_path}")

        if output_path:
            out = Path(output_path)
        else:
            out = self.output_dir / f"{pdb.stem}_receptor.pdbqt"

        out.parent.mkdir(parents=True, exist_ok=True)

        lines = []
        for line in pdb.read_text().splitlines():
            if not (line.startswith('ATOM') or line.startswith('HETATM')):
                continue

            res_name = line[17:20].strip()
            if res_name in ('HOH', 'WAT', 'H2O', 'DOD', 'TIP'):
                continue

            atom_name = line[12:16].strip()
            if atom_name.startswith('H'):
                continue

            element = ''
            if len(line) >= 78:
                element = line[76:78].strip().upper()
            if not element:
                element = atom_name[0].upper()

            ad4_type = self._get_ad4_atom_type(element, res_name)

            pdbqt_line = line[:54]
            pdbqt_line += '  1.00  0.00'
            charge = '    +0.000'
            pdbqt_line += charge
            pdbqt_line = pdbqt_line.ljust(77)
            pdbqt_line += f" {ad4_type}"
            lines.append(pdbqt_line)

        out.write_text('\n'.join(lines) + '\n')
        logger.info(f"Receptor PDBQT: {out} ({len(lines)} atoms)")
        return str(out)

    def _get_ad4_atom_type(self, element: str,
                           res_name: str = '') -> str:
        """Map element to AutoDock 4 atom type."""
        mapping = {
            'C': 'C',
            'N': 'NA',
            'O': 'OA',
            'S': 'SA',
            'P': 'P',
            'F': 'F',
            'CL': 'Cl',
            'BR': 'Br',
            'I': 'I',
            'ZN': 'Zn',
            'FE': 'Fe',
            'MG': 'Mg',
            'CA': 'Ca',
            'MN': 'Mn',
            'CU': 'Cu',
            'NA': 'Na',
            'K': 'K',
        }
        return mapping.get(element.upper(), element[:2] if len(element) >= 2 else element)

    def prepare_ligand_from_smiles(self, smiles: str,
                                   name: str = 'ligand',
                                   output_path: Optional[str] = None,
                                   ) -> str:
        """
        Convert SMILES to PDBQT using Meeko + RDKit.

        Pipeline: SMILES -> RDKit Mol -> 3D coords -> Meeko -> PDBQT

        Args:
            smiles: SMILES string of ligand
            name: Ligand name for file naming
            output_path: Optional output PDBQT path

        Returns:
            Path to generated PDBQT file
        """
        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem, rdDistGeom
        except ImportError:
            raise PDBQTError("RDKit required: conda install -c conda-forge rdkit")

        try:
            from meeko import MoleculePreparation, PDBQTWriterLegacy
        except ImportError:
            raise PDBQTError("Meeko required: pip install meeko")

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise PDBQTError(f"Invalid SMILES: {smiles}")

        mol = Chem.AddHs(mol)
        params = rdDistGeom.ETKDGv3()
        params.randomSeed = 42
        success = AllChem.EmbedMolecule(mol, params)
        if success != 0:
            success = AllChem.EmbedMolecule(mol)
            if success != 0:
                raise PDBQTError(f"3D embedding failed for: {smiles}")

        try:
            AllChem.MMFFOptimizeMolecule(mol, maxIters=500)
        except Exception:
            try:
                AllChem.UFFOptimizeMolecule(mol, maxIters=500)
            except Exception:
                pass

        preparator = MoleculePreparation()
        mol_setups = preparator.prepare(mol)
        setup = list(mol_setups)[0]

        if output_path:
            out = Path(output_path)
        else:
            out = self.output_dir / f"{name}.pdbqt"
        out.parent.mkdir(parents=True, exist_ok=True)

        pdbqt_string, is_ok, err_msg = PDBQTWriterLegacy.write_string(setup)
        if not is_ok:
            raise PDBQTError(f"Meeko PDBQT conversion failed: {err_msg}")

        out.write_text(pdbqt_string)
        logger.info(f"Ligand PDBQT: {out}")
        return str(out)

    def run_docking(self,
                    receptor_pdbqt: str | Path,
                    ligand_pdbqt: str | Path,
                    grid_box: GridBox,
                    output_name: str = 'docking_out') -> List[DockingPose]:
        """
        Run AutoDock Vina docking.

        Args:
            receptor_pdbqt: Path to receptor PDBQT
            ligand_pdbqt: Path to ligand PDBQT
            grid_box: Search space definition
            output_name: Base name for output files

        Returns:
            List of DockingPose results sorted by affinity
        """
        out_path = self.output_dir / f"{output_name}_out.pdbqt"

        cmd = [
            str(self.vina_path),
            '--receptor', str(receptor_pdbqt),
            '--ligand', str(ligand_pdbqt),
            *grid_box.to_vina_args(),
            '--out', str(out_path),
            '--exhaustiveness', str(self.exhaustiveness),
            '--num_modes', str(self.num_modes),
            '--energy_range', str(self.energy_range),
        ]

        logger.info(f"Running Vina: {output_name}")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() or result.stdout.strip()
                raise DockingError(f"Vina failed (exit {result.returncode}): {error_msg}")

            return self._parse_vina_stdout(result.stdout)

        except subprocess.TimeoutExpired:
            raise DockingError(f"Vina timed out after 300s: {output_name}")

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
            r'^\s*(\d+)\s+(-?\d+\.?\d*)\s+(\d+\.?\d*)\s+(\d+\.?\d*)',
            re.MULTILINE
        )

        for match in pattern.finditer(output):
            poses.append(DockingPose(
                mode=int(match.group(1)),
                affinity=float(match.group(2)),
                rmsd_lb=float(match.group(3)),
                rmsd_ub=float(match.group(4)),
            ))

        return poses

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

        grid = self.calculate_grid_box(pocket)

        result = DockingResult(
            pocket_id=pocket_id,
            pocket_rank=pocket_rank,
            ligand_name=ligand_name,
            ligand_smiles=ligand_smiles,
            grid_box=grid.to_dict(),
        )

        try:
            ligand_pdbqt = self.prepare_ligand_from_smiles(
                ligand_smiles, name=f"pocket{pocket_id}_{ligand_name}"
            )

            output_name = f"pocket{pocket_id}_{ligand_name}"
            poses = self.run_docking(
                receptor_pdbqt, ligand_pdbqt, grid, output_name
            )

            result.poses = poses
            if poses:
                result.best_affinity = poses[0].affinity
                result.best_rmsd_lb = poses[0].rmsd_lb
                result.success = True

        except Exception as e:
            result.error = str(e)
            logger.warning(
                f"Docking failed for pocket {pocket_id}: {e}"
            )

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
            fragments: Fragment library (default: FRAGMENT_LIBRARY)

        Returns:
            List of DockingResult (one per fragment)
        """
        if fragments is None:
            fragments = FRAGMENT_LIBRARY

        results = []
        for frag_type, frag_info in fragments.items():
            result = self.dock_pocket(
                pocket,
                receptor_pdbqt,
                ligand_smiles=frag_info['smiles'],
                ligand_name=f"{frag_type}_{frag_info['name']}",
            )
            results.append(result)

        return results


# ============================================================================
# HIGH-LEVEL PIPELINE API
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
        Dict with docking report
    """
    docker = VinaDocking(
        vina_bin=vina_bin,
        output_dir=output_dir,
        exhaustiveness=exhaustiveness,
    )

    receptor_pdbqt = docker.prepare_receptor(protein_pdb)
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

        probe_results = docker.probe_pocket(pocket, receptor_pdbqt)

        for r in probe_results:
            result_dict = r.to_dict()
            result_dict['bio_score'] = bio_score
            all_results.append(result_dict)

            if r.success and r.best_affinity < best_overall:
                best_overall = r.best_affinity
            if r.is_druggable:
                druggable_count += 1

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
    """
    path = Path(pdbqt_path)
    if not path.exists():
        return []

    content = path.read_text()
    poses = []

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
