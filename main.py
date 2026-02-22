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
Version: 1.0.0
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from src.cache import AnalysisCache
from src.config import PATHS, PIPELINE
from src.fetcher import fetch_pdb, FetchError
from src.dynamics import run_nma_simulation
from src.geometry import find_voids, extract_atom_coords
from src.cavities import find_cavities
from src.profiling import PipelineProfiler
from src.scoring import rank_pockets
from src.visualizer import BioVoidVisualizer
from src.docking import dock_elite_pockets, DockingError

logger = logging.getLogger("biovoid.pipeline")


class BioVoidPipeline:
    """Main orchestrator for Bio-Void Hunter pipeline"""
    
    def __init__(self, pdb_id: str,
                 n_frames: int = PIPELINE.n_frames,
                 verbose: bool = PIPELINE.verbose,
                 output_dir: str = str(PATHS.results),
                 profile: str = PIPELINE.profile,
                 dock: bool = PIPELINE.dock,
                 use_cache: bool = True,
                 multiframe: bool = False,
                 source: str = "rcsb"):
        self.pdb_id = pdb_id.upper()
        self.n_frames = n_frames
        self.multiframe = multiframe
        self.source = source
        self.verbose = verbose
        self.output_dir = Path(output_dir)
        self.profile = profile
        self.dock = dock
        self.use_cache = use_cache
        self.visualizer = BioVoidVisualizer(output_dir)
        self.profiler = PipelineProfiler()
        self.cache = AnalysisCache() if use_cache else None
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.pdb_file: Optional[str] = None
        self.frames_dir: Optional[str] = None
        self.voids: List[Dict] = []
        self.cavities: List[Dict] = []
        self.atom_coords: Optional[np.ndarray] = None
        self.docking_report: Optional[Dict] = None
        self.start_time: float = 0.0

    def _get_analysis_frame(self) -> str:
        """Resolve the PDB frame to use for analysis.
        Prefers middle NMA frame, falls back to first frame, then static PDB.
        """
        if self.frames_dir:
            middle = Path(self.frames_dir) / f"frame_{self.n_frames // 2:03d}.pdb"
            if middle.exists():
                return str(middle)
            first = Path(self.frames_dir) / "frame_001.pdb"
            if first.exists():
                return str(first)
        return self.pdb_file
    
    def run(self) -> Dict:
        """Execute complete pipeline with profiling and caching."""
        self.start_time = time.time()
        self.profiler.start_pipeline()

        if self.cache:
            cached = self.cache.get(self.pdb_id, self.n_frames, self.profile)
            if cached:
                logger.info("[CACHE] Hit for %s — returning cached result", self.pdb_id)
                return cached
        
        try:
            with self.profiler.step("fetch"):
                self._fetch_structure()
            
            with self.profiler.step("nma"):
                self._run_nma()
            
            with self.profiler.step("voronoi"):
                self._scan_voids()
            
            with self.profiler.step("cavity_merge"):
                self._merge_cavities()
            
            with self.profiler.step("scoring"):
                self._score_druggability()
            
            if self.multiframe and self.frames_dir:
                with self.profiler.step("multiframe_consensus"):
                    self._run_multiframe_consensus()
            
            with self.profiler.step("ml_rerank"):
                self._ml_rerank()
            
            if self.dock:
                with self.profiler.step("docking"):
                    self._run_docking()
            
            with self.profiler.step("report"):
                report = self._generate_report()
            
            with self.profiler.step("visualization"):
                self._visualize_results()
            
            self._save_report(report)
            self._save_to_atlas(report)
            
            if self.cache:
                self.cache.put(self.pdb_id, report, self.n_frames, self.profile)

            logger.info("\n%s", self.profiler.format_table())
            
            return report
            
        except Exception as e:
            logger.error("[PIPELINE] Failed: %s", e)
            raise
    
    def _fetch_structure(self):
        """Step 1: Fetch PDB structure"""
        logger.info("[FETCH] Fetching %s from %s...", self.pdb_id, self.source)
        
        try:
            self.pdb_file = fetch_pdb(self.pdb_id, source=self.source)
            logger.info("[FETCH] Structure saved: %s", self.pdb_file)
        except FetchError as e:
            logger.error("[FETCH] %s", e)
            raise
    
    def _run_nma(self):
        """Step 2: Generate conformational ensemble with NMA"""
        logger.info("[NMA] Generating %d conformational frames...", self.n_frames)
        
        try:
            result = run_nma_simulation(
                pdb_path=self.pdb_file,
                n_modes=10,
                n_frames=self.n_frames,
                output_dir=str(PATHS.frames / self.pdb_id.lower())
            )
            
            self.frames_dir = result['output_dir']
            logger.info("[NMA] Generated %d frames (%d atoms)",
                        self.n_frames, result['n_atoms'])
            
        except Exception as e:
            logger.warning("[NMA] Failed: %s — falling back to single structure", e)
            self.frames_dir = None
            self.n_frames = 1
    
    def _scan_voids(self):
        """Step 3: Scan for voids using Voronoi"""
        logger.info("[VORONOI] Scanning for void vertices...")
        
        frame_file = self._get_analysis_frame()
        self.voids = find_voids(frame_file, atom_type='heavy')
        
        logger.info("[VORONOI] %d void vertices found", len(self.voids))
    
    def _merge_cavities(self):
        """Step 4: Merge voids into cavities and filter"""
        logger.info("[CAVITY] Merging void vertices into cavities...")
        
        frame_file = self._get_analysis_frame()
        self.cavities = find_cavities(
            frame_file,
            merge=True,
            hydrophobic=True,
            atom_type='heavy'
        )
        
        for i, cavity in enumerate(self.cavities):
            cavity['id'] = i
        
        druggable_count = sum(1 for c in self.cavities if c.get('druggable', False))
        logger.info("[CAVITY] %d merged cavities, %d druggable",
                    len(self.cavities), druggable_count)
    
    def _score_druggability(self):
        """Step 5: Score and rank cavities for druggability (Phase 3)"""
        logger.info("[SCORING] Scoring %d cavities (profile: %s)...",
                    len(self.cavities), self.profile)
        
        frame_file = self._get_analysis_frame()
        self.atom_coords = extract_atom_coords(frame_file, atom_type='heavy')
        
        self.cavities = rank_pockets(
            self.cavities,
            self.atom_coords,
            profile=self.profile,
            top_n=None,
        )
        
        by_class = {}
        for c in self.cavities:
            cls = c.get('druggability_class', 'unknown')
            by_class[cls] = by_class.get(cls, 0) + 1
        
        logger.info("[SCORING] Druggability: %s",
                    ", ".join(f"{v} {k}" for k, v in by_class.items()))
        
        if self.cavities:
            top = self.cavities[0]
            logger.info("[SCORING] Top pocket: rank #%s | bio_score=%.4f | class=%s",
                        top.get('rank', '?'),
                        top.get('bio_score', 0),
                        top.get('druggability_class', '?'))
    
    def _run_multiframe_consensus(self):
        """Run multi-frame consensus analysis across all NMA frames."""
        if not self.frames_dir:
            return

        try:
            from src.multiframe import run_multiframe_consensus, ConsensusConfig

            config = ConsensusConfig(
                profile=self.profile,
                per_frame_top_n=20,
                min_support_frames=max(2, self.n_frames // 5),
                cluster_distance=4.0,
            )

            result = run_multiframe_consensus(self.frames_dir, config)
            consensus_pockets = result.get("consensus_pockets", [])

            if consensus_pockets:
                self.cavities = consensus_pockets
                for i, c in enumerate(self.cavities):
                    c["id"] = i

                logger.info(
                    "[CONSENSUS] %d consensus pockets from %d frames (of %d total clusters)",
                    len(consensus_pockets),
                    result.get("frames_analyzed", 0),
                    result.get("consensus_stats", {}).get("clusters_total", 0),
                )
            else:
                logger.info("[CONSENSUS] No consensus pockets found, keeping single-frame results")

        except Exception as e:
            logger.warning("[CONSENSUS] Multi-frame analysis failed: %s — keeping single-frame", e)

    def _ml_rerank(self):
        """Step 5c: ML-based reranking of scored cavities."""
        if not self.cavities:
            return

        try:
            from src.ml.features import extract_batch, ALL_FEATURE_NAMES
            from src.ml.classifier import load_model, predict

            model_path = self.output_dir.parent / "models" / "pocket_classifier.pkl"
            if not model_path.exists():
                logger.debug("[ML] No trained model found at %s — skipping rerank", model_path)
                return

            model_result = load_model(model_path)
            model = model_result["model"]

            X = extract_batch(self.cavities, ALL_FEATURE_NAMES)
            pred = predict(model, X)
            probas = pred.get("probabilities")

            if probas is not None and probas.ndim > 1:
                for i, cavity in enumerate(self.cavities):
                    cavity["ml_score"] = round(float(probas[i, 1]), 4)

                self.cavities.sort(
                    key=lambda c: c.get("ml_score", 0.0), reverse=True
                )
                for i, cavity in enumerate(self.cavities):
                    cavity["ml_rank"] = i + 1

                logger.info("[ML] Reranked %d cavities by ML score", len(self.cavities))
            else:
                logger.debug("[ML] No probability output — skipping rerank")

        except Exception as e:
            logger.debug("[ML] Rerank skipped: %s", e)

    def _run_docking(self):
        """Step 5b: Targeted docking validation (Phase 4)"""
        logger.info("[DOCKING] Starting targeted docking for top pockets...")
        
        pdb_for_dock = self._get_analysis_frame()
        try:
            self.docking_report = dock_elite_pockets(
                cavities=self.cavities,
                protein_pdb=pdb_for_dock,
                profile=self.profile,
                top_n=min(5, len(self.cavities)),
                output_dir=str(self.output_dir / 'docking'),
            )
            
            logger.info("[DOCKING] Complete: %d successful docks, %d druggable, best=%.1f kcal/mol",
                        self.docking_report.get('n_successful', 0),
                        self.docking_report.get('n_druggable', 0),
                        self.docking_report.get('best_affinity', 0.0))
                
        except DockingError as e:
            logger.warning("[DOCKING] Docking failed: %s", e)
            self.docking_report = None
        except Exception as e:
            logger.warning("[DOCKING] Unexpected docking error: %s", e)
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
        logger.info("[VISUALIZER] Generating 3D interactive reports...")
        
        viz_pdb = self._get_analysis_frame()

        html_path = self.visualizer.create_interactive_view(
            viz_pdb, self.cavities, self.pdb_id
        )
        logger.info("[VISUALIZER] Interactive view saved: %s", html_path)
        
        pml_path = self.visualizer.generate_pymol_script(
            viz_pdb, self.cavities, self.pdb_id
        )
        logger.info("[VISUALIZER] PyMOL render script saved: %s", pml_path)
    
    def _save_to_atlas(self, report: Dict):
        """Save results to Atlas database for dashboard visibility."""
        try:
            from src.database import AtlasDB, ProteinRecord, PocketRecord

            db_path = self.output_dir.parent / "atlas.db"
            with AtlasDB(str(db_path)) as db:
                protein = ProteinRecord(
                    pdb_id=self.pdb_id,
                    total_cavities=report.get("total_cavities", 0),
                    druggable_cavities=report.get("druggable_cavities", 0),
                    high_score_count=report.get("high_druggability", 0),
                    medium_score_count=report.get("medium_druggability", 0),
                    top_bio_score=max(
                        (c.get("bio_score", 0) for c in report.get("cavities", [])),
                        default=0.0,
                    ),
                    analysis_runtime=report.get("runtime_seconds", 0.0),
                    n_frames=self.n_frames,
                    scoring_profile=self.profile,
                )
                db.upsert_protein(protein)

                pockets = []
                for c in report.get("cavities", []):
                    center = c.get("center", [0, 0, 0])
                    sc = c.get("score_components", {})
                    pockets.append(PocketRecord(
                        pdb_id=self.pdb_id,
                        pocket_id=c.get("id", 0),
                        rank=c.get("rank", 0),
                        bio_score=c.get("bio_score", 0.0),
                        volume=c.get("volume", 0.0),
                        center_x=center[0] if len(center) > 0 else 0.0,
                        center_y=center[1] if len(center) > 1 else 0.0,
                        center_z=center[2] if len(center) > 2 else 0.0,
                        radius_geom=c.get("radius_geom", 0.0),
                        radius_clear=c.get("radius_clear", 0.0),
                        merged_vertices=c.get("merged_vertices", 0),
                        hydrophobic_ratio=c.get("hydrophobic_ratio", 0.0),
                        polar_atoms=c.get("polar_atoms", 0),
                        druggable=c.get("druggable", False),
                        druggability_class=c.get("druggability_class", "low"),
                        enclosure_score=sc.get("enclosure_score", 0.0),
                        depth_score=sc.get("depth_score", 0.0),
                        volume_score=sc.get("volume_score", 0.0),
                        hydrophobicity_score=sc.get("hydrophobicity_score", 0.0),
                        profile_used=c.get("profile_used", "Default"),
                    ))
                if pockets:
                    db.batch_insert_pockets(pockets)
                logger.info("[ATLAS] Saved %d pockets for %s", len(pockets), self.pdb_id)
        except Exception as e:
            logger.warning("[ATLAS] DB save failed: %s", e)

    def _save_report(self, report: Dict):
        """Step 7: Save JSON report to disk"""
        output_file = self.output_dir / f"{self.pdb_id.lower()}_report.json"
        
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info("Results saved to %s", output_file)


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
        default=PIPELINE.n_frames,
        help=f'Number of NMA frames to generate (default: {PIPELINE.n_frames})'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default=str(PATHS.results),
        help=f'Output directory for results (default: {PATHS.results})'
    )
    
    parser.add_argument(
        '--profile',
        type=str,
        default=PIPELINE.profile,
        choices=list(PIPELINE.scoring_profiles),
        help=f'Scoring profile for druggability (default: {PIPELINE.profile})'
    )
    
    parser.add_argument(
        '--dock',
        action='store_true',
        help='Enable Phase 4 targeted docking validation'
    )
    
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Disable result caching'
    )
    
    parser.add_argument(
        '--multiframe',
        action='store_true',
        help='Enable multi-frame consensus analysis (analyzes all NMA frames)'
    )
    
    parser.add_argument(
        '--source',
        type=str,
        default='rcsb',
        choices=['rcsb', 'alphafold'],
        help='Structure source: rcsb (PDB) or alphafold (UniProt ID)'
    )
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )
    
    pipeline = BioVoidPipeline(
        pdb_id=args.pdb_id,
        n_frames=args.n_frames,
        verbose=args.verbose,
        output_dir=args.output,
        profile=args.profile,
        dock=args.dock,
        use_cache=not args.no_cache,
        multiframe=args.multiframe,
        source=args.source,
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
