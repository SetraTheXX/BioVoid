#!/usr/bin/env python3
"""BioVoid local research pipeline for geometry-based protein pocket analysis."""

import argparse
import copy
import json
import logging
import sqlite3
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from src.atlas_v1 import ATLAS_SCHEMA_VERSION, AtlasPersistenceError, AtlasV1
from src.cache import (
    AnalysisCache,
    CacheIdentity,
    CacheWriteError,
    compute_code_identity,
    compute_environment_identity,
    hash_cache_payload,
    hash_file,
)
from src.config import PATHS, PIPELINE, RECOVERY
from src.fetcher import FetchError, FetchedStructure, fetch_structure_input
from src.dynamics import run_nma_simulation
from src.geometry import find_voids, extract_atom_coords
from src.cavities import find_cavities
from src.profiling import PipelineProfiler
from src.resources import SAFE_16GB, get_available_memory_bytes
from src.runtime import (
    StaleFrameError,
    create_run_workspace,
    require_full_atom_structure,
    validate_frame_manifest,
)
from src.scoring import (
    PRODUCT_RANKING_CONTRACT_VERSION,
    SCORE_SEMANTICS,
    SCORING_CONTRACT_VERSION,
    estimate_pocket_heuristic_fit,
    get_profile_manifest,
    rank_product_pockets,
)
from src.structure_preparation import (
    PreparationConfig,
    PreparationError,
    PreparationResult,
    StructureSource,
    prepare_structure,
)
from src.static_detector import (
    StaticDetectionResult,
    detect_static_pockets,
    static_detector_config_sha256,
)
from src.motion_ensemble import (
    MotionEnsembleConfig,
    MotionEnsembleResult,
    analyze_validated_motion_ensemble,
    generate_validated_motion_ensemble,
)
from src.ml.paths import pocket_classifier_path
from src.visualizer import BioVoidVisualizer
from src.docking import dock_elite_pockets, DockingError

logger = logging.getLogger("biovoid.pipeline")
PROJECT_ROOT = Path(__file__).resolve().parent


def resolve_project_path(path: str | Path) -> Path:
    """Resolve relative pipeline paths from the repository, not the shell cwd."""
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


class ExperimentalFeatureDisabledError(ValueError):
    """Raised when an experimental layer is requested without explicit opt-in."""


class BioVoidPipeline:
    """Main orchestrator for Bio-Void Hunter pipeline"""

    def __init__(
        self,
        pdb_id: str,
        n_frames: int = PIPELINE.n_frames,
        verbose: bool = PIPELINE.verbose,
        output_dir: str = str(PATHS.runs),
        profile: str = PIPELINE.profile,
        dock: bool = PIPELINE.dock,
        use_ml: bool = PIPELINE.use_ml,
        use_cache: bool = True,
        multiframe: bool = PIPELINE.multiframe,
        source: str = "rcsb",
        allow_experimental: bool = False,
        atlas_db_path: str | Path = PATHS.atlas_db,
        cache_dir: str | Path = PATHS.cache,
        structure_source: StructureSource | None = None,
        preparation_config: PreparationConfig | None = None,
    ):
        requested_experimental = [
            name
            for name, enabled in (
                ("motion-aware multiframe", multiframe),
                ("ML reranking", use_ml),
                ("docking", dock),
            )
            if enabled
        ]
        if requested_experimental and not allow_experimental:
            raise ExperimentalFeatureDisabledError(
                "Experimental features require allow_experimental=True during recovery: "
                + ", ".join(requested_experimental)
            )

        self.pdb_id = pdb_id.upper()
        self.n_frames = n_frames
        self.multiframe = multiframe
        self.source = source
        if structure_source is None:
            if source == "alphafold":
                structure_source = StructureSource(
                    provider="alphafold",
                    identifier=self.pdb_id,
                    representation="predicted_model",
                )
            else:
                structure_source = StructureSource(
                    provider="rcsb",
                    identifier=self.pdb_id,
                    representation="biological_assembly",
                    assembly_id="1",
                )
        self.structure_source = structure_source
        self.preparation_config = preparation_config or PreparationConfig()
        self.verbose = verbose
        self.workspace = create_run_workspace(resolve_project_path(output_dir))
        self.run_id = self.workspace.run_id
        self.output_dir = self.workspace.path / "results"
        self.frames_output_dir = self.workspace.path / "frames"
        self.profile = profile
        self.dock = dock
        self.use_ml = use_ml
        self.allow_experimental = allow_experimental
        self.atlas_db_path = resolve_project_path(atlas_db_path)
        self.use_cache = use_cache
        self.visualizer = BioVoidVisualizer(str(self.output_dir))
        self.profiler = PipelineProfiler()
        self.cache = AnalysisCache(resolve_project_path(cache_dir)) if self.use_cache else None

        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.pdb_file: Optional[str] = None
        self.raw_structure_file: Optional[str] = None
        self.fetched_structure: FetchedStructure | None = None
        self.preparation_result: PreparationResult | None = None
        self.static_detection: StaticDetectionResult | None = None
        self.static_detector_metadata: Dict | None = None
        self.motion_ensemble: MotionEnsembleResult | None = None
        self.motion_result: Dict | None = None
        self.motion_error: str | None = None
        self.ml_status: dict[str, str] = {
            "requested": str(bool(self.use_ml)).lower(),
            "status": "disabled" if not self.use_ml else "not_checked",
        }
        self.cache_identity: CacheIdentity | None = None
        self.cache_status: Dict = {"status": "disabled" if not self.use_cache else "not_checked"}
        self.code_identity_sha256: str | None = None
        self.environment_identity_sha256: str | None = None
        self.frames_dir: Optional[str] = None
        self.frame_files: List[Path] = []
        self.voids: List[Dict] = []
        self.cavities: List[Dict] = []
        self.atom_coords: Optional[np.ndarray] = None
        self.docking_report: Optional[Dict] = None
        self.start_time: float = 0.0

    def _get_analysis_frame(self) -> str:
        """Return the prepared full-atom structure used by the canonical path."""
        if not self.pdb_file:
            raise RuntimeError("Structure input is not available")
        return self.pdb_file

    def run(self) -> Dict:
        """Execute the pipeline; cached cores still complete the run lifecycle."""
        self.start_time = time.time()
        self.profiler.start_pipeline()

        try:
            with self.profiler.step("fetch"):
                self._fetch_structure()

            with self.profiler.step("preparation"):
                self._prepare_structure()

            self.cache_identity = self._build_cache_identity()
            cached_core = self.cache.get(self.cache_identity) if self.cache else None
            if cached_core is not None:
                self._restore_analysis_core(cached_core)
                self.cache_status = dict(self.cache.last_event)
                logger.info("[CACHE] Reusing verified analysis core for %s", self.pdb_id)
            else:
                if self.cache:
                    self.cache_status = dict(self.cache.last_event)

                if self.multiframe:
                    with self.profiler.step("nma"):
                        self._run_nma()

                with self.profiler.step("voronoi"):
                    self._scan_voids()

                with self.profiler.step("cavity_merge"):
                    self._merge_cavities()

                if self.multiframe and self.motion_ensemble is not None:
                    with self.profiler.step("multiframe_consensus"):
                        self._run_multiframe_consensus()

                self._store_analysis_core()

            with self.profiler.step("scoring"):
                self._score_druggability()

            if self.use_ml:
                with self.profiler.step("ml_rerank"):
                    self._ml_rerank()

            if self.dock:
                with self.profiler.step("docking"):
                    self._run_docking()

            with self.profiler.step("report"):
                report = self._generate_report()

            with self.profiler.step("visualization"):
                self._visualize_results()

            report["atlas_persistence"] = self._save_to_atlas(report)
            self._save_report(report)

            logger.info("\n%s", self.profiler.format_table())

            return report

        except StaleFrameError:
            raise
        except Exception as e:
            logger.error("[PIPELINE] Failed: %s", e)
            raise

    def _fetch_structure(self):
        """Step 1: Fetch PDB structure"""
        logger.info(
            "[FETCH] Fetching %s from %s (%s)...",
            self.pdb_id,
            self.structure_source.provider,
            self.structure_source.representation,
        )

        try:
            self.fetched_structure = fetch_structure_input(self.structure_source)
            self.raw_structure_file = str(self.fetched_structure.path)
            logger.info("[FETCH] Raw structure available: %s", self.raw_structure_file)
        except FetchError as e:
            logger.error("[FETCH] %s", e)
            raise

    def _prepare_structure(self):
        """Step 2: Produce the only structure accepted by the detector."""
        if self.fetched_structure is None or self.raw_structure_file is None:
            raise PreparationError("Structure must be fetched before preparation")
        preparation_dir = self.workspace.path / "preparation"
        self.preparation_result = prepare_structure(
            input_path=self.raw_structure_file,
            source=self.structure_source,
            config=self.preparation_config,
            output_dir=preparation_dir,
            run_id=self.run_id,
            source_metadata=self.fetched_structure.metadata,
            analysis_config={
                "profile": self.profile,
                "n_frames": self.n_frames,
                "motion_aware": self.multiframe,
                "ml_reranking": self.use_ml,
                "docking": self.dock,
            },
        )
        self.pdb_file = str(self.preparation_result.prepared_path)
        logger.info(
            "[PREPARATION] Detector input ready: %s (sha256=%s)",
            self.pdb_file,
            self.preparation_result.prepared_sha256,
        )

    def _effective_motion_config(self) -> MotionEnsembleConfig:
        return MotionEnsembleConfig(
            n_modes=PIPELINE.n_modes,
            samples_per_mode=self.n_frames,
        )

    def _model_identity(self) -> str:
        if not self.use_ml:
            return hash_cache_payload({"ml_model": "disabled"})
        model_path = pocket_classifier_path()
        if model_path.is_file():
            return hash_file(model_path)
        return hash_cache_payload({"ml_model": "requested_but_unavailable"})

    def _build_cache_identity(self) -> CacheIdentity:
        if self.preparation_result is None:
            raise PreparationError("Cache identity requires completed structure preparation")
        self.code_identity_sha256 = compute_code_identity()
        self.environment_identity_sha256 = compute_environment_identity()
        motion_payload = (
            asdict(self._effective_motion_config()) if self.multiframe else {"motion": "disabled"}
        )
        return CacheIdentity(
            source_identifier=(
                f"{self.structure_source.provider}:"
                f"{self.structure_source.identifier}:"
                f"{self.structure_source.representation}"
            ),
            raw_input_sha256=self.preparation_result.input_sha256,
            prepared_structure_sha256=self.preparation_result.prepared_sha256,
            preparation_config_sha256=self.preparation_result.config_sha256,
            detector_config_sha256=static_detector_config_sha256(),
            motion_config_sha256=hash_cache_payload(motion_payload),
            model_sha256=self._model_identity(),
            code_identity_sha256=self.code_identity_sha256,
            environment_identity_sha256=self.environment_identity_sha256,
            benchmark_cache_policy="not_benchmark",
        )

    def _static_metadata(self) -> Dict:
        if self.static_detector_metadata is not None:
            return copy.deepcopy(self.static_detector_metadata)
        if self.static_detection is None:
            return {
                "detector_version": "canonical-static-v1",
                "detector_config_sha256": static_detector_config_sha256(),
                "atom_policy_version": "protein-heavy-bondi-v1",
                "radius_provenance": "not_executed",
                "surface_model": "not_executed",
                "volume_method": "not_executed",
                "protein_atom_count": 0,
                "candidate_count": len(self.voids),
                "warnings": ["static_detector_not_executed"],
            }
        return {
            "detector_version": self.static_detection.detector_version,
            "detector_config_sha256": self.static_detection.config_sha256,
            "atom_policy_version": self.static_detection.atom_policy_version,
            "radius_provenance": self.static_detection.radius_provenance,
            "surface_model": self.static_detection.surface_model,
            "volume_method": self.static_detection.volume_method,
            "protein_atom_count": self.static_detection.protein_atom_count,
            "candidate_count": self.static_detection.candidate_count,
            "warnings": list(self.static_detection.warnings),
        }

    def _analysis_core(self) -> Dict:
        motion_result = copy.deepcopy(self.motion_result)
        if isinstance(motion_result, dict):
            motion_result.pop("ensemble_manifest", None)
        return {
            "schema_version": "analysis-core-v1",
            "completion_status": "complete",
            "static_cavities": copy.deepcopy(self.cavities),
            "static_detector": self._static_metadata(),
            "candidate_count": len(self.voids),
            "motion_result": motion_result,
            "motion_error": self.motion_error,
        }

    def _restore_analysis_core(self, core: Dict) -> None:
        if (
            core.get("schema_version") != "analysis-core-v1"
            or core.get("completion_status") != "complete"
            or not isinstance(core.get("static_cavities"), list)
            or not isinstance(core.get("static_detector"), dict)
        ):
            raise RuntimeError("Cached analysis core is incomplete or incompatible")
        self.cavities = copy.deepcopy(core["static_cavities"])
        self.static_detector_metadata = copy.deepcopy(core["static_detector"])
        candidate_count = int(core.get("candidate_count", 0))
        self.voids = [{"candidate_index": index} for index in range(candidate_count)]
        self.motion_result = copy.deepcopy(core.get("motion_result"))
        self.motion_error = core.get("motion_error")

    def _store_analysis_core(self) -> None:
        if self.cache is None or self.cache_identity is None:
            return
        if self.motion_error:
            self.cache_status = {
                "status": "not_stored",
                "key": self.cache_identity.key,
                "reason": "experimental_motion_failed",
            }
            return
        try:
            self.cache.put(self.cache_identity, self._analysis_core())
            self.cache_status = dict(self.cache.last_event)
        except CacheWriteError as exc:
            self.cache_status = {
                "status": "write_failed",
                "key": self.cache_identity.key,
                "error": str(exc),
            }
            logger.error("[CACHE] %s", exc)

    def _run_nma(self):
        """Generate a quality-gated, experimental full-atom motion ensemble."""
        logger.info(
            "[NMA] Generating %d modes x %d independent samples...",
            PIPELINE.n_modes,
            self.n_frames,
        )

        try:
            self.motion_ensemble = generate_validated_motion_ensemble(
                self.pdb_file,
                self.workspace.path / "motion",
                self._effective_motion_config(),
                available_memory_bytes=get_available_memory_bytes(),
            )
            estimated_bytes = self.motion_ensemble.estimated_memory_bytes
            logger.info(
                "[RESOURCE] %s approved motion NMA: estimated_memory=%.2f GiB",
                SAFE_16GB.name,
                estimated_bytes / 1024**3,
            )
            self.frames_dir = str(self.motion_ensemble.output_dir / "accepted_frames")
            self.frame_files = list(self.motion_ensemble.accepted_frame_files)
            validate_frame_manifest(self.frames_dir, self.frame_files)
            logger.info(
                "[NMA] Accepted %d/%d reconstructed full-atom samples",
                len(self.frame_files),
                len(self.motion_ensemble.samples),
            )

        except StaleFrameError:
            raise
        except Exception as e:
            self.motion_ensemble = None
            self.frames_dir = None
            self.frame_files = []
            self.motion_error = f"{type(e).__name__}: {e}"
            logger.warning(
                "[NMA] Experimental motion layer failed; canonical static analysis continues: %s",
                e,
            )

    def _scan_voids(self):
        """Generate canonical candidates from the prepared static structure only."""
        logger.info("[GEOMETRY] Scanning for candidate empty-space centers...")

        frame_file = self._get_analysis_frame()
        require_full_atom_structure(frame_file)
        if self.preparation_result is None:
            raise PreparationError(
                "Canonical static detection requires a valid preparation report and run manifest"
            )
        self.static_detection = detect_static_pockets(
            frame_file,
            prepared_sha256=self.preparation_result.prepared_sha256,
        )
        self.voids = [
            {"candidate_index": index} for index in range(self.static_detection.candidate_count)
        ]

        logger.info("[GEOMETRY] %d candidate centers passed geometry policy", len(self.voids))

    def _merge_cavities(self):
        """Step 4: Merge voids into cavities and filter"""
        logger.info("[CAVITY] Merging void vertices into cavities...")

        if self.static_detection is None:
            raise RuntimeError("Canonical static detection must run before cavity conversion")
        self.cavities = [pocket.to_legacy_dict() for pocket in self.static_detection.pockets]

        for i, cavity in enumerate(self.cavities):
            cavity["id"] = i

        logger.info(
            "[CAVITY] %d merged cavities ready for heuristic scoring",
            len(self.cavities),
        )

    def _score_druggability(self):
        """Rank pockets from frozen detector measurements."""
        logger.info(
            "[SCORING] Scoring %d cavities (profile: %s)...", len(self.cavities), self.profile
        )

        frame_file = self._get_analysis_frame()
        self.atom_coords = extract_atom_coords(frame_file, atom_type="heavy")

        self.cavities = rank_product_pockets(
            self.cavities,
            self.atom_coords,
            profile=self.profile,
            top_n=None,
        )
        for cavity in self.cavities:
            cavity["druggable"] = bool(cavity["heuristic_shortlist"])

        by_class = {}
        for c in self.cavities:
            cls = c.get("heuristic_quality_tier", "unknown")
            by_class[cls] = by_class.get(cls, 0) + 1

        logger.info(
            "[SCORING] Heuristic tiers: %s",
            ", ".join(f"{v} {k}" for k, v in by_class.items()),
        )

        for cavity in self.cavities:
            cavity["pocket_fit_score"] = estimate_pocket_heuristic_fit(cavity)

        if self.cavities:
            top = self.cavities[0]
            logger.info(
                "[SCORING] Top pocket: rank #%s | bio_score=%.4f | tier=%s | fit=%.2f",
                top.get("rank", "?"),
                top.get("bio_score", 0),
                top.get("heuristic_quality_tier", "?"),
                top.get("pocket_fit_score", 0),
            )

    def _run_multiframe_consensus(self):
        """Build separate mode-aware evidence without replacing canonical pockets."""
        if self.motion_ensemble is None or self.preparation_result is None:
            return

        try:
            validate_frame_manifest(self.frames_dir, self.frame_files)
            self.motion_result = analyze_validated_motion_ensemble(
                self.motion_ensemble,
                self.cavities,
                prepared_sha256=self.preparation_result.prepared_sha256,
            )
            logger.info(
                "[MOTION] %d experimental pockets from %d accepted samples",
                len(self.motion_result.get("motion_pockets", [])),
                self.motion_result.get("accepted_sample_count", 0),
            )

        except Exception as e:
            self.motion_error = f"{type(e).__name__}: {e}"
            self.motion_result = None
            logger.warning(
                "[MOTION] Evidence analysis failed; canonical static result is unchanged: %s",
                e,
            )

    def _ml_rerank(self):
        """Step 5c: ML-based reranking of scored cavities."""
        if not self.cavities:
            self.ml_status = {"requested": "true", "status": "no_candidates"}
            return

        try:
            from src.ml.features import extract_batch, ALL_FEATURE_NAMES
            from src.ml.classifier import load_model, predict

            model_path = pocket_classifier_path()
            if not model_path.exists():
                self.ml_status = {
                    "requested": "true",
                    "status": "requested_model_unavailable",
                }
                logger.warning(
                    "[ML] Experimental reranking requested but the local model is unavailable."
                )
                return

            model_result = load_model(model_path, trusted=self.allow_experimental)
            model = model_result["model"]

            X = extract_batch(self.cavities, ALL_FEATURE_NAMES)
            pred = predict(model, X)
            probas = pred.get("probabilities")

            if probas is not None and probas.ndim > 1:
                for i, cavity in enumerate(self.cavities):
                    cavity["ml_score"] = round(float(probas[i, 1]), 4)

                ml_order = sorted(
                    range(len(self.cavities)),
                    key=lambda index: self.cavities[index].get("ml_score", 0.0),
                    reverse=True,
                )
                for ml_rank, index in enumerate(ml_order, start=1):
                    self.cavities[index]["ml_rank"] = ml_rank

                self.ml_status = {"requested": "true", "status": "applied_experimental"}
                logger.info(
                    "[ML] Computed an experimental ML order for %d cavities; canonical rank unchanged.",
                    len(self.cavities),
                )
            else:
                self.ml_status = {"requested": "true", "status": "invalid_model_output"}
                logger.warning("[ML] Experimental model returned no probability output.")

        except Exception as e:
            self.ml_status = {
                "requested": "true",
                "status": f"failed:{type(e).__name__}",
            }
            logger.warning("[ML] Experimental reranking failed: %s", type(e).__name__)

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
                output_dir=str(self.output_dir / "docking"),
            )

            logger.info(
                "[DOCKING] Complete: %d successful docks, %d druggable, best=%.1f kcal/mol",
                self.docking_report.get("n_successful", 0),
                self.docking_report.get("n_druggable", 0),
                self.docking_report.get("best_affinity", 0.0),
            )

        except DockingError as e:
            logger.warning("[DOCKING] Docking failed: %s", e)
            self.docking_report = None
        except Exception as e:
            logger.warning("[DOCKING] Unexpected docking error: %s", e)
            self.docking_report = None

    def _generate_report(self) -> Dict:
        """Step 6: Generate comprehensive JSON report"""
        runtime = time.time() - self.start_time

        shortlist_count = sum(
            1 for cavity in self.cavities if cavity.get("heuristic_shortlist", False)
        )

        # Count by druggability class (Phase 3)
        high_count = sum(1 for c in self.cavities if c.get("druggability_class") == "high")
        medium_count = sum(1 for c in self.cavities if c.get("druggability_class") == "medium")

        # Build cavity list for report
        cavity_list = []
        for i, cavity in enumerate(self.cavities):
            cavity_data = {
                "id": cavity.get("id", i),
                "rank": cavity.get("rank", i + 1),
                "volume": round(cavity["volume"], 2),
                "center": [round(x, 2) for x in cavity["center"]],
                "radius_geom": round(cavity["radius_geom"], 2),
                "radius_clear": round(cavity["radius_clear"], 2),
                "merged_vertices": cavity["merged_vertices"],
            }
            for raw_key in (
                "pocket_id",
                "center_method",
                "volume_method",
                "volume_resolution",
                "volume_convergence_delta",
                "surface_area",
                "surface_model",
                "depth",
                "depth_method",
                "minimum_surface_clearance",
                "enclosure_ray_length",
                "enclosure",
                "open_fraction",
                "residues",
                "prepared_structure_sha256",
                "detector_version",
                "detector_config_sha256",
                "atom_policy_version",
                "warnings",
                "validity",
            ):
                if raw_key in cavity:
                    cavity_data[raw_key] = cavity[raw_key]

            # Add hydrophobic data if available
            if "hydrophobic_ratio" in cavity:
                cavity_data["hydrophobic_ratio"] = round(cavity["hydrophobic_ratio"], 2)
                cavity_data["polar_atoms"] = cavity["polar_atoms"]
                cavity_data["druggable"] = cavity["druggable"]

            if "bio_score" in cavity:
                cavity_data["bio_score"] = cavity["bio_score"]
                cavity_data["druggability_class"] = cavity["druggability_class"]
                cavity_data["heuristic_quality_tier"] = cavity["heuristic_quality_tier"]
                cavity_data["score_components"] = cavity["score_components"]
                cavity_data["profile_used"] = cavity["profile_used"]
                cavity_data["scoring_measurements"] = cavity["scoring_measurements"]
                cavity_data["measurement_quality"] = cavity["measurement_quality"]
                cavity_data["profile_manifest"] = cavity["profile_manifest"]
                cavity_data["scoring_contract_version"] = cavity["scoring_contract_version"]
                cavity_data["score_semantics"] = cavity["score_semantics"]
                cavity_data["static_score_contribution"] = cavity["static_score_contribution"]
                cavity_data["motion_score_contribution"] = cavity["motion_score_contribution"]
                cavity_data["ranking_contract_version"] = cavity[
                    "ranking_contract_version"
                ]
                cavity_data["heuristic_shortlist"] = cavity[
                    "heuristic_shortlist"
                ]

            if "pocket_fit_score" in cavity:
                cavity_data["pocket_fit_score"] = cavity["pocket_fit_score"]

            if "ml_score" in cavity:
                cavity_data["ml_score"] = cavity["ml_score"]
            if "ml_rank" in cavity:
                cavity_data["ml_rank"] = cavity["ml_rank"]

            cavity_list.append(cavity_data)

        report = {
            "run_id": self.run_id,
            "run_workspace": str(self.workspace.path),
            "resource_profile": SAFE_16GB.name,
            "resource_usage": self.profiler.summary(),
            "pdb_id": self.pdb_id,
            "structure_source": self.structure_source.model_dump(mode="json"),
            "validation_status": RECOVERY.result_validation_status,
            "canonical_eligible": False,
            "canonical_static_path_ready": RECOVERY.canonical_static_ready,
            "recovery_mode": RECOVERY.mode,
            "feature_policy": {
                "motion_aware": RECOVERY.motion_aware,
                "ml_reranking": RECOVERY.ml_reranking,
                "docking": RECOVERY.docking,
            },
            "experimental_features_enabled": {
                "motion_aware": self.multiframe,
                "ml_reranking": self.use_ml,
                "docking": self.dock,
            },
            "experimental_feature_status": {
                "motion_aware": (
                    "enabled_experimental" if self.multiframe else "disabled"
                ),
                "ml_reranking": dict(self.ml_status),
                "docking": "enabled_experimental" if self.dock else "disabled",
            },
            "n_frames": self.n_frames,
            "n_frames_semantics": "legacy_alias_for_samples_per_mode",
            "motion_sampling": {
                "mode_count": PIPELINE.n_modes,
                "samples_per_mode": self.n_frames,
                "requested_sample_count": PIPELINE.n_modes * self.n_frames,
            },
            "scoring_profile": self.profile,
            "scoring": {
                "contract_version": SCORING_CONTRACT_VERSION,
                "profile_manifest": get_profile_manifest(self.profile),
                "score_semantics": SCORE_SEMANTICS,
                "motion_affects_canonical_score": False,
                "raw_measurements_stored_separately": True,
                "ranking_contract_version": PRODUCT_RANKING_CONTRACT_VERSION,
            },
            "docking_enabled": self.dock,
            "total_voids": len(self.voids),
            "total_cavities": len(self.cavities),
            "heuristic_shortlist_cavities": shortlist_count,
            "druggable_cavities": shortlist_count,
            "high_druggability": high_count,
            "medium_druggability": medium_count,
            "runtime_seconds": round(runtime, 2),
            "cavities": cavity_list,
        }

        if self.preparation_result is None:
            raise PreparationError("Cannot generate a report without valid structure preparation")
        report["preparation"] = json.loads(
            self.preparation_result.report_path.read_text(encoding="utf-8")
        )
        report["provenance"] = {
            "run_manifest": str(self.preparation_result.manifest_path),
            "prepared_structure_path": str(self.preparation_result.prepared_path),
            "input_sha256": self.preparation_result.input_sha256,
            "prepared_sha256": self.preparation_result.prepared_sha256,
            "preparation_config_sha256": self.preparation_result.config_sha256,
            "preparation_report_sha256": self.preparation_result.report_sha256,
            "detector_config_sha256": self.cache_identity.detector_config_sha256
            if self.cache_identity
            else static_detector_config_sha256(),
            "motion_config_sha256": self.cache_identity.motion_config_sha256
            if self.cache_identity
            else hash_cache_payload({"motion": "disabled"}),
            "model_sha256": self.cache_identity.model_sha256
            if self.cache_identity
            else self._model_identity(),
            "code_identity_sha256": self.code_identity_sha256 or compute_code_identity(),
            "environment_identity_sha256": self.environment_identity_sha256
            or compute_environment_identity(),
        }
        report["cache"] = {
            **self.cache_status,
            "enabled": self.cache is not None,
            "cache_key": self.cache_identity.key if self.cache_identity else None,
            "cached_layer": "unscored_analysis_core",
            "lifecycle_outputs_regenerated": True,
        }
        report["static_detector"] = self._static_metadata()
        if self.multiframe:
            if self.motion_result is not None:
                report["motion_aware"] = self.motion_result
            elif self.motion_ensemble is not None:
                report["motion_aware"] = {
                    "status": "experimental_no_evidence",
                    "canonical_ranking_affected": False,
                    "ensemble_manifest": str(self.motion_ensemble.manifest_path),
                    "quality_counts": dict(self.motion_ensemble.quality_counts),
                    "error": self.motion_error,
                }
            else:
                report["motion_aware"] = {
                    "status": "experimental_failed",
                    "canonical_ranking_affected": False,
                    "error": self.motion_error,
                }

        # Add docking results if available (Phase 4)
        if self.docking_report:
            report["docking"] = {
                "n_pockets_docked": self.docking_report.get("n_pockets_docked", 0),
                "n_successful": self.docking_report.get("n_successful", 0),
                "n_druggable": self.docking_report.get("n_druggable", 0),
                "best_affinity": self.docking_report.get("best_affinity", 0.0),
                "vina_version": self.docking_report.get("vina_version", "unknown"),
            }

        return report

    def _visualize_results(self):
        """Step 6: Visualize results using Hybrid Engine"""
        logger.info("[VISUALIZER] Generating 3D interactive reports...")

        viz_pdb = self._get_analysis_frame()

        html_path = self.visualizer.create_interactive_view(viz_pdb, self.cavities, self.pdb_id)
        logger.info("[VISUALIZER] Interactive view saved: %s", html_path)

        pml_path = self.visualizer.generate_pymol_script(viz_pdb, self.cavities, self.pdb_id)
        logger.info("[VISUALIZER] PyMOL render script saved: %s", pml_path)

    def _save_to_atlas(self, report: Dict) -> Dict:
        """Persist the complete run atomically and expose any failure."""
        try:
            with AtlasV1(self.atlas_db_path) as db:
                result = db.persist_report(report)
            logger.info(
                "[ATLAS] Persisted run %s (%d/%d pockets)",
                self.run_id,
                result.persisted_total,
                result.detected_total,
            )
            return result.to_dict()
        except (AtlasPersistenceError, OSError, sqlite3.Error) as exc:
            logger.error("[ATLAS] Run persistence failed: %s", exc)
            return {
                "status": "failed",
                "run_id": self.run_id,
                "schema_version": ATLAS_SCHEMA_VERSION,
                "error": str(exc),
            }

    def _save_report(self, report: Dict):
        """Step 7: Save JSON report to disk"""
        output_file = self.output_dir / f"{self.pdb_id.lower()}_report.json"

        with open(output_file, "w") as f:
            json.dump(report, f, indent=2)

        logger.info("Results saved to %s", output_file)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="BioVoid: local protein pocket analysis research pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --pdb-id 1cbs
  python main.py --pdb-id 1AKE --multiframe --allow-experimental --n-frames 4
  python main.py --pdb-id 1BCL --output data/runtime/runs
        """,
    )

    parser.add_argument(
        "--pdb-id", type=str, required=True, help="PDB ID to analyze (e.g., 1CBS, 1AKE)"
    )

    parser.add_argument(
        "--n-frames",
        type=int,
        default=PIPELINE.n_frames,
        help=(
            "Independent samples per NMA mode; legacy option name "
            f"(default: {PIPELINE.n_frames}, safe-16gb max: "
            f"{SAFE_16GB.max_samples_per_mode})"
        ),
    )

    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    parser.add_argument(
        "--output",
        type=str,
        default=str(PATHS.runs),
        help=f"Output directory for run workspaces (default: {PATHS.runs})",
    )

    parser.add_argument(
        "--profile",
        type=str,
        default=PIPELINE.profile,
        choices=list(PIPELINE.scoring_profiles),
        help=f"Heuristic scoring profile (default: {PIPELINE.profile})",
    )

    parser.add_argument(
        "--dock", action="store_true", help="Enable experimental targeted docking validation"
    )

    parser.add_argument("--use-ml", action="store_true", help="Enable experimental ML reranking")

    parser.add_argument(
        "--allow-experimental",
        action="store_true",
        help="Explicitly allow non-canonical experimental features",
    )

    parser.add_argument("--no-cache", action="store_true", help="Disable result caching")

    parser.add_argument(
        "--multiframe",
        action="store_true",
        help="Enable the experimental quality-gated motion ensemble",
    )

    parser.add_argument(
        "--source",
        type=str,
        default="rcsb",
        choices=["rcsb", "alphafold"],
        help="Structure source: rcsb (PDB) or alphafold (UniProt ID)",
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
        use_ml=args.use_ml,
        use_cache=not args.no_cache,
        multiframe=args.multiframe,
        source=args.source,
        allow_experimental=args.allow_experimental,
    )

    try:
        report = pipeline.run()

        # Print summary
        print("\n" + "=" * 70)
        print("PIPELINE SUMMARY")
        print("=" * 70)
        print(f"PDB ID: {report['pdb_id']}")
        print(f"Samples per mode: {report['n_frames']}")
        print(f"Profile: {report['scoring_profile']}")
        print(f"Voids: {report['total_voids']}")
        print(f"Cavities: {report['total_cavities']}")
        print(f"Heuristic shortlist: {report['heuristic_shortlist_cavities']}")
        print(f"High heuristic tier: {report['high_druggability']}")
        print(f"Medium heuristic tier: {report['medium_druggability']}")
        print(f"Runtime: {report['runtime_seconds']:.2f}s")
        print("=" * 70)

        return 0

    except Exception as e:
        print(f"\n❌ PIPELINE FAILED: {str(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
