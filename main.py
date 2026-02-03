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
Version: 0.4.0 (Phase 2.5)
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# Core modules
from src.fetcher import fetch_pdb, FetchError
from src.dynamics import run_nma_simulation
from src.geometry import find_voids
from src.cavities import find_cavities
from src.visualizer import BioVoidVisualizer


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
                 verbose: bool = False, output_dir: str = "data/results"):
        self.pdb_id = pdb_id.upper()
        self.n_frames = n_frames
        self.verbose = verbose
        self.output_dir = Path(output_dir)
        self.logger = Logger(verbose)
        self.visualizer = BioVoidVisualizer(output_dir)
        
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Pipeline state
        self.pdb_file: Optional[str] = None
        self.frames_dir: Optional[str] = None
        self.voids: List[Dict] = []
        self.cavities: List[Dict] = []
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
            
            # Step 5: Generate report
            report = self._generate_report()
            
            # Step 6: Visualize Results (Phase 2.6)
            self._visualize_results()
            
            # Step 7: Save results
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
    
    def _generate_report(self) -> Dict:
        """Step 5: Generate comprehensive JSON report"""
        runtime = time.time() - self.start_time
        
        # Count druggable cavities
        druggable_count = sum(1 for c in self.cavities if c.get('druggable', False))
        
        # Build cavity list for report
        cavity_list = []
        for i, cavity in enumerate(self.cavities):
            cavity_data = {
                "id": i,
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
            
            cavity_list.append(cavity_data)
        
        report = {
            "pdb_id": self.pdb_id,
            "n_frames": self.n_frames,
            "total_voids": len(self.voids),
            "total_cavities": len(self.cavities),
            "druggable_cavities": druggable_count,
            "runtime_seconds": round(runtime, 2),
            "cavities": cavity_list
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
    
    args = parser.parse_args()
    
    # Run pipeline
    pipeline = BioVoidPipeline(
        pdb_id=args.pdb_id,
        n_frames=args.n_frames,
        verbose=args.verbose,
        output_dir=args.output
    )
    
    try:
        report = pipeline.run()
        
        # Print summary
        print("\n" + "=" * 70)
        print("PIPELINE SUMMARY")
        print("=" * 70)
        print(f"PDB ID: {report['pdb_id']}")
        print(f"Frames: {report['n_frames']}")
        print(f"Voids: {report['total_voids']}")
        print(f"Cavities: {report['total_cavities']}")
        print(f"Druggable: {report['druggable_cavities']}")
        print(f"Runtime: {report['runtime_seconds']:.2f}s")
        print("=" * 70)
        
        return 0
        
    except Exception as e:
        print(f"\n❌ PIPELINE FAILED: {str(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
