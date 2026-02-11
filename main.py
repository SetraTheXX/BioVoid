#!/usr/bin/env python3
"""
Bio-Void Hunter: Main Pipeline (Production Engine)
===================================================

Orchestrates the complete cryptic pocket discovery workflow:
1. Fetch PDB structure
2. Generate conformational ensemble (NMA)
3. Scan for voids (Voronoi)
4. Merge and analyze cavities
5. Filter druggable pockets
6. Generate JSON report

Author: Bio-Void Hunter Team
Version: 0.6.0 (Phase 4)
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

# Core modules
from src.fetcher import fetch_pdb, FetchError
from src.dynamics import run_nma_simulation
from src.geometry import find_voids
from src.cavities import find_cavities
from src.scoring import rank_pockets
from src.geometry import extract_atom_coords
from src.visualizer import BioVoidVisualizer
from src.docking import dock_elite_pockets, DockingError


class Logger:
    """Structured logging with tags"""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
    
    def info(self, tag: str, message: str):
        """Log info message with tag"""
        print(f"[INFO] [{tag}] {message}")
    
    def error(self, tag: str, message: str):
        """Log error message with tag"""
        print(f"[ERROR] [{tag}] {message}", file=sys.stderr)
    
    def success(self, message: str):
        """Log success message"""
        print(f"✅ SUCCESS: {message}")
    
    def warning(self, tag: str, message: str):
        """Log warning message"""
        print(f"⚠️  WARNING: [{tag}] {message}")


class BioVoidPipeline:
    """Main orchestrator for Bio-Void Hunter pipeline"""
    
    def __init__(self, pdb_id: str, n_frames: int = 50, 
                 verbose: bool = False, output_dir: str = "data/results",
                 profile: str = "default", dock: bool = False):
        self.pdb_id = pdb_id.upper()
        self.n_frames = n_frames
        self.verbose = verbose
        self.output_dir = Path(output_dir)
        self.profile = profile
        self.dock = dock
        self.logger = Logger(verbose)
        self.visualizer = BioVoidVisualizer(output_dir)
        
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Pipeline state
        self.pdb_file: Optional[str] = None
        self.frames_dir: Optional[str] = None
        self.voids: List[Dict] = []
        self.cavities: List[Dict] = []
        self.atom_coords: Optional[np.ndarray] = None
        self.docking_report: Optional[Dict] = None
        self.start_time: float = 0.0
    
    def run(self) -> Dict:
        """Execute complete pipeline"""
        self.start_time = time.time()
        
        try:
            # Step 1: Fetch PDB
            self._fetch_structure()
            
            # Step 2: Generate conformational ensemble (NMA)
            self._run_nma()
            
            # Step 3: Scan voids (Voronoi)
            self._scan_voids()
            
            # Step 4: Merge cavities
            self._merge_cavities()
            
            # Step 5: Score druggability (Phase 3)
            self._score_druggability()
            
            # Step 5b: Targeted Docking (Phase 4, optional)
            if self.dock:
                self._run_docking()
            
            # Step 6: Generate report
            report = self._generate_report()
            
            # Step 7: Visualize Results (Phase 2.6)
            self._visualize_results()
            
            # Step 8: Save results
            self._save_report(report)
            
            return report
            
        except Exception as e:
            self.logger.error("PIPELINE", f"Failed: {str(e)}")
            raise
    
    def _fetch_structure(self):
        """Step 1: Fetch PDB structure"""
        self.logger.info("FETCH", f"Fetching PDB {self.pdb_id}...")
        
        try:
            self.pdb_file = fetch_pdb(self.pdb_id)
            self.logger.info("FETCH", f"Structure saved: {self.pdb_file}")
        except FetchError as e:
            self.logger.error("FETCH", str(e))
            raise
    
    def _run_nma(self):
        """Step 2: Generate conformational ensemble with NMA"""
        self.logger.info("NMA", f"Generating {self.n_frames} conformational frames...")
        
        try:
            # Run NMA simulation
            result = run_nma_simulation(
                pdb_path=self.pdb_file,
                n_modes=10,
                n_frames=self.n_frames,
                output_dir=f"data/frames/{self.pdb_id.lower()}"
            )
            
            self.frames_dir = result['output_dir']
            n_atoms = result['n_atoms']
            
            self.logger.info("NMA", 
                f"Generated {self.n_frames} frames ({n_atoms} atoms)")
            
        except Exception as e:
            # Graceful fallback: Use static structure
            self.logger.warning("NMA", f"Failed: {str(e)}")
            self.logger.warning("NMA", "Falling back to single structure mode")
            
            # Use original PDB as single frame
            self.frames_dir = None
            self.n_frames = 1
    
    def _scan_voids(self):
        """Step 3: Scan for voids using Voronoi"""
        self.logger.info("VORONOI", "Scanning for void vertices...")
        
        # Determine which structure to analyze
        if self.frames_dir:
            # Use middle frame from NMA ensemble
            frame_file = Path(self.frames_dir) / f"frame_{self.n_frames//2:03d}.pdb"
            if not frame_file.exists():
                # Fallback to first frame
                frame_file = Path(self.frames_dir) / "frame_001.pdb"
        else:
            # Use static structure
            frame_file = self.pdb_file
        
        # Scan voids
        self.voids = find_voids(str(frame_file), atom_type='heavy')
        
        self.logger.info("VORONOI", 
            f"{len(self.voids)} void vertices found")
    
    def _merge_cavities(self):
        """Step 4: Merge voids into cavities and filter"""
        self.logger.info("CAVITY", "Merging void vertices into cavities...")
        
        # Determine structure file
        if self.frames_dir:
            frame_file = Path(self.frames_dir) / f"frame_{self.n_frames//2:03d}.pdb"
            if not frame_file.exists():
                frame_file = Path(self.frames_dir) / "frame_001.pdb"
        else:
            frame_file = self.pdb_file
        
        # Find and merge cavities with hydrophobic filtering
        self.cavities = find_cavities(
            str(frame_file),
            merge=True,
            hydrophobic=True,
            atom_type='heavy'
        )
        
        # Assign IDs to cavities (Important for later steps)
        for i, cavity in enumerate(self.cavities):
            cavity['id'] = i
        
        # Count druggable cavities
        druggable_count = sum(1 for c in self.cavities if c.get('druggable', False))
        
        self.logger.info("CAVITY", 
            f"{len(self.cavities)} merged cavities detected")
        self.logger.info("FILTER", 
            f"{druggable_count} druggable pockets remain")
    
    def _score_druggability(self):
        """Step 5: Score and rank cavities for druggability (Phase 3)"""
        self.logger.info("SCORING", 
            f"Scoring {len(self.cavities)} cavities (profile: {self.profile})...")
        
        # Get atom coordinates for depth/enclosure calculation
        if self.frames_dir:
            frame_file = Path(self.frames_dir) / f"frame_{self.n_frames//2:03d}.pdb"
            if not frame_file.exists():
                frame_file = Path(self.frames_dir) / "frame_001.pdb"
        else:
            frame_file = Path(self.pdb_file)
        
        self.atom_coords = extract_atom_coords(str(frame_file), atom_type='heavy')
        
        # Rank all cavities
        self.cavities = rank_pockets(
            self.cavities,
            self.atom_coords,
            profile=self.profile,
            top_n=None  # Keep all, just rank them
        )
        
        # Summary stats
        high = sum(1 for c in self.cavities 
                   if c.get('druggability_class') == 'high')
        medium = sum(1 for c in self.cavities 
                     if c.get('druggability_class') == 'medium')
        low = sum(1 for c in self.cavities 
                  if c.get('druggability_class') == 'low')
        
        self.logger.info("SCORING", 
            f"Druggability: {high} high, {medium} medium, {low} low")
        
        if len(self.cavities) > 0:
            top = self.cavities[0]
            self.logger.info("SCORING", 
                f"Top pocket: rank #{top.get('rank', '?')} | "
                f"bio_score={top.get('bio_score', 0):.4f} | "
                f"class={top.get('druggability_class', '?')}")
    
    def _run_docking(self):
        """Step 5b: Targeted docking validation (Phase 4)"""
        self.logger.info("DOCKING", 
            f"Starting targeted docking for top pockets...")
        
        # Determine PDB file to use
        if self.frames_dir:
            frame_file = Path(self.frames_dir) / f"frame_{self.n_frames//2:03d}.pdb"
            if not frame_file.exists():
                frame_file = Path(self.frames_dir) / "frame_001.pdb"
            pdb_for_dock = str(frame_file)
        else:
            pdb_for_dock = self.pdb_file
        
        try:
            self.docking_report = dock_elite_pockets(
                cavities=self.cavities,
                protein_pdb=pdb_for_dock,
                profile=self.profile,
                top_n=min(5, len(self.cavities)),
                output_dir=str(self.output_dir / 'docking'),
            )
            
            n_dock = self.docking_report.get('n_successful', 0)
            n_drug = self.docking_report.get('n_druggable', 0)
            best = self.docking_report.get('best_affinity', 0.0)
            
            self.logger.info("DOCKING",
                f"Complete: {n_dock} successful docks, "
                f"{n_drug} druggable, best={best:.1f} kcal/mol")
                
        except DockingError as e:
            self.logger.warning("DOCKING", f"Docking failed: {e}")
            self.docking_report = None
        except Exception as e:
            self.logger.warning("DOCKING", f"Unexpected docking error: {e}")
            self.docking_report = None
    
    def _generate_report(self) -> Dict:
        """Step 6: Generate comprehensive JSON report"""
        runtime = time.time() - self.start_time
        
        # Count druggable cavities
        druggable_count = sum(1 for c in self.cavities if c.get('druggable', False))
        
        # Count by druggability class (Phase 3)
        high_count = sum(1 for c in self.cavities 
                        if c.get('druggability_class') == 'high')
        medium_count = sum(1 for c in self.cavities 
                          if c.get('druggability_class') == 'medium')
        
        # Build cavity list for report
        cavity_list = []
        for i, cavity in enumerate(self.cavities):
            cavity_data = {
                "id": cavity.get('id', i),
                "rank": cavity.get('rank', i + 1),
                "volume": round(cavity['volume'], 2),
                "center": [round(x, 2) for x in cavity['center']],
                "radius_geom": round(cavity['radius_geom'], 2),
                "radius_clear": round(cavity['radius_clear'], 2),
                "merged_vertices": cavity['merged_vertices']
            }
            
            # Add hydrophobic data if available
            if 'hydrophobic_ratio' in cavity:
                cavity_data['hydrophobic_ratio'] = round(cavity['hydrophobic_ratio'], 2)
                cavity_data['polar_atoms'] = cavity['polar_atoms']
                cavity_data['druggable'] = cavity['druggable']
            
            # Add scoring data (Phase 3)
            if 'bio_score' in cavity:
                cavity_data['bio_score'] = cavity['bio_score']
                cavity_data['druggability_class'] = cavity['druggability_class']
                cavity_data['score_components'] = cavity['score_components']
                cavity_data['profile_used'] = cavity['profile_used']
            
            cavity_list.append(cavity_data)
        
        report = {
            "pdb_id": self.pdb_id,
            "n_frames": self.n_frames,
            "scoring_profile": self.profile,
            "docking_enabled": self.dock,
            "total_voids": len(self.voids),
            "total_cavities": len(self.cavities),
            "druggable_cavities": druggable_count,
            "high_druggability": high_count,
            "medium_druggability": medium_count,
            "runtime_seconds": round(runtime, 2),
            "cavities": cavity_list
        }
        
        # Add docking results if available (Phase 4)
        if self.docking_report:
            report['docking'] = {
                'n_pockets_docked': self.docking_report.get('n_pockets_docked', 0),
                'n_successful': self.docking_report.get('n_successful', 0),
                'n_druggable': self.docking_report.get('n_druggable', 0),
                'best_affinity': self.docking_report.get('best_affinity', 0.0),
                'vina_version': self.docking_report.get('vina_version', 'unknown'),
            }
        
        return report
    
    def _visualize_results(self):
        """Step 6: Visualize results using Hybrid Engine"""
        self.logger.info("VISUALIZER", "Generating 3D interactive reports...")
        
        # Determine the PDB file to use for visualization
        # Ideally use the frame where calculation happened, or original PDB
        viz_pdb = self.pdb_file
        if self.frames_dir:
             middle_frame = Path(self.frames_dir) / f"frame_{self.n_frames//2:03d}.pdb"
             if middle_frame.exists():
                 viz_pdb = str(middle_frame)

        # Generate Interactive HTML
        html_path = self.visualizer.create_interactive_view(
            viz_pdb, self.cavities, self.pdb_id
        )
        self.logger.info("VISUALIZER", f"Interactive view saved: {html_path}")
        
        # Generate PyMOL Script
        pml_path = self.visualizer.generate_pymol_script(
            viz_pdb, self.cavities, self.pdb_id
        )
        self.logger.info("VISUALIZER", f"PyMOL render script saved: {pml_path}")
    
    def _save_report(self, report: Dict):
        """Step 7: Save JSON report to disk"""
        output_file = self.output_dir / f"{self.pdb_id.lower()}_report.json"
        
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        self.logger.success(f"Results saved to {output_file}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Bio-Void Hunter: Cryptic Pocket Discovery Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --pdb-id 1cbs --n-frames 50
  python main.py --pdb-id 1AKE --n-frames 100 --verbose
  python main.py --pdb-id 1BCL --n-frames 100 --output results/bcl
        """
    )
    
    parser.add_argument(
        '--pdb-id',
        type=str,
        required=True,
        help='PDB ID to analyze (e.g., 1CBS, 1AKE)'
    )
    
    parser.add_argument(
        '--n-frames',
        type=int,
        default=50,
        help='Number of NMA frames to generate (default: 50)'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default='data/results',
        help='Output directory for results (default: data/results)'
    )
    
    parser.add_argument(
        '--profile',
        type=str,
        default='default',
        choices=['enzyme', 'ppi', 'gpcr', 'default'],
        help='Scoring profile for druggability (default: default)'
    )
    
    parser.add_argument(
        '--dock',
        action='store_true',
        help='Enable Phase 4 targeted docking validation'
    )
    
    args = parser.parse_args()
    
    # Run pipeline
    pipeline = BioVoidPipeline(
        pdb_id=args.pdb_id,
        n_frames=args.n_frames,
        verbose=args.verbose,
        output_dir=args.output,
        profile=args.profile,
        dock=args.dock
    )
    
    try:
        report = pipeline.run()
        
        # Print summary
        print("\n" + "=" * 70)
        print("PIPELINE SUMMARY")
        print("=" * 70)
        print(f"PDB ID: {report['pdb_id']}")
        print(f"Frames: {report['n_frames']}")
        print(f"Profile: {report['scoring_profile']}")
        print(f"Voids: {report['total_voids']}")
        print(f"Cavities: {report['total_cavities']}")
        print(f"Druggable: {report['druggable_cavities']}")
        print(f"High Score: {report['high_druggability']}")
        print(f"Medium Score: {report['medium_druggability']}")
        print(f"Runtime: {report['runtime_seconds']:.2f}s")
        print("=" * 70)
        
        return 0
        
    except Exception as e:
        print(f"\n❌ PIPELINE FAILED: {str(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
