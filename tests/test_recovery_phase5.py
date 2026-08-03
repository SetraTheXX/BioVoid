"""Phase 5 scoring, cache, and run-scoped Atlas recovery regressions."""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest


def _atom_coordinates() -> np.ndarray:
    rng = np.random.default_rng(20260729)
    return rng.normal(0.0, 6.0, size=(120, 3))


def _pocket(
    pocket_id: str,
    *,
    volume: float,
    hydrophobic_ratio: float,
    center: tuple[float, float, float],
) -> dict:
    return {
        "pocket_id": pocket_id,
        "id": pocket_id,
        "center": list(center),
        "volume": volume,
        "hydrophobic_ratio": hydrophobic_ratio,
        "enclosure": 0.72,
        "depth": 4.2,
        "vertices": [
            [-1.0, -1.0, -1.0],
            [1.0, -1.0, 1.0],
            [-1.0, 1.0, 1.0],
            [1.0, 1.0, -1.0],
        ],
        "merged_vertices": 4,
        "volume_convergence_delta": 0.04,
        "warnings": [],
    }


def test_scoring_contract_is_versioned_and_avoids_probability_language() -> None:
    from src.scoring import (
        SCORING_CONTRACT_VERSION,
        calculate_bio_score,
        get_profile_manifest,
    )

    pocket = _pocket(
        "BV-1",
        volume=620.0,
        hydrophobic_ratio=0.58,
        center=(0.0, 0.0, 0.0),
    )
    result = calculate_bio_score(pocket, _atom_coordinates(), profile="enzyme")
    manifest = get_profile_manifest("enzyme")

    assert result["scoring_contract_version"] == SCORING_CONTRACT_VERSION
    assert result["profile_manifest"] == manifest
    assert len(manifest["config_sha256"]) == 64
    assert manifest["weights"] == {
        "depth": 0.3,
        "enclosure": 0.35,
        "hydrophobicity": 0.2,
        "volume": 0.15,
    }
    assert result["heuristic_quality_tier"] in {"high", "medium", "low"}
    assert result["measurement_quality"]["tier"] in {
        "high",
        "medium",
        "low",
        "insufficient",
    }
    assert "confidence" not in result
    assert "drug_likeness" not in result
    assert result["score_semantics"] == "heuristic_ranking_not_probability"


def test_profile_reranking_reuses_measurements_without_geometry_recalculation() -> None:
    from src.scoring import rank_pockets, rerank_from_measurements

    coordinates = _atom_coordinates()
    pockets = [
        _pocket(
            "BV-HYDRO",
            volume=360.0,
            hydrophobic_ratio=0.95,
            center=(0.5, 0.0, 0.0),
        ),
        _pocket(
            "BV-VOLUME",
            volume=2100.0,
            hydrophobic_ratio=0.22,
            center=(1.0, 0.0, 0.0),
        ),
    ]
    enzyme_ranked = rank_pockets(copy.deepcopy(pockets), coordinates, profile="enzyme")
    frozen_measurements = {
        pocket["pocket_id"]: copy.deepcopy(pocket["scoring_measurements"])
        for pocket in enzyme_ranked
    }

    ppi_ranked = rerank_from_measurements(copy.deepcopy(enzyme_ranked), profile="ppi")

    assert {pocket["pocket_id"] for pocket in ppi_ranked} == {"BV-HYDRO", "BV-VOLUME"}
    assert all(
        pocket["scoring_measurements"] == frozen_measurements[pocket["pocket_id"]]
        for pocket in ppi_ranked
    )
    assert all(pocket["profile_used"] == "PPI" for pocket in ppi_ranked)
    assert all(
        pocket["static_score_contribution"]["total"] == pocket["bio_score"] for pocket in ppi_ranked
    )
    assert all(pocket["motion_score_contribution"] is None for pocket in ppi_ranked)


def test_pocket_fit_is_not_labeled_as_ligand_drug_likeness() -> None:
    from src.scoring import estimate_pocket_heuristic_fit

    pocket = _pocket(
        "BV-FIT",
        volume=700.0,
        hydrophobic_ratio=0.55,
        center=(0.0, 0.0, 0.0),
    )
    score = estimate_pocket_heuristic_fit(
        {
            **pocket,
            "score_components": {
                "enclosure_score": 0.8,
                "depth_score": 0.7,
            },
        }
    )

    assert 0.0 <= score <= 1.0


def _cache_identity(**overrides):
    from src.cache import CacheIdentity, hash_cache_payload

    values = {
        "source_identifier": "TEST",
        "raw_input_sha256": "1" * 64,
        "prepared_structure_sha256": "2" * 64,
        "preparation_config_sha256": "3" * 64,
        "detector_config_sha256": "4" * 64,
        "motion_config_sha256": hash_cache_payload({"motion": "disabled"}),
        "model_sha256": hash_cache_payload({"model": "disabled"}),
        "code_identity_sha256": "5" * 64,
        "environment_identity_sha256": "6" * 64,
        "benchmark_cache_policy": "not_benchmark",
    }
    values.update(overrides)
    return CacheIdentity(**values)


def test_content_addressed_cache_key_covers_scientific_identity(tmp_path: Path) -> None:
    from src.cache import AnalysisCache

    cache = AnalysisCache(tmp_path / "cache")
    baseline = _cache_identity()
    variants = [
        _cache_identity(prepared_structure_sha256="a" * 64),
        _cache_identity(detector_config_sha256="b" * 64),
        _cache_identity(motion_config_sha256="c" * 64),
        _cache_identity(model_sha256="d" * 64),
        _cache_identity(code_identity_sha256="e" * 64),
        _cache_identity(environment_identity_sha256="f" * 64),
    ]

    assert len({baseline.key, *(identity.key for identity in variants)}) == 7
    cache.put(baseline, {"core": {"pockets": [1, 2]}})
    assert cache.get(baseline) == {"core": {"pockets": [1, 2]}}
    assert all(cache.get(identity) is None for identity in variants)


def test_cache_rejects_tampered_or_incomplete_entries(tmp_path: Path) -> None:
    from src.cache import AnalysisCache

    cache = AnalysisCache(tmp_path / "cache")
    identity = _cache_identity()
    cache.put(identity, {"value": 7})
    entry_path = cache.cache_dir / f"{identity.key}.json"
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    entry["result"]["value"] = 99
    entry_path.write_text(json.dumps(entry), encoding="utf-8")

    assert cache.get(identity) is None
    assert cache.last_event["status"] == "invalid"


def _atlas_report(run_id: str, pockets: list[dict]) -> dict:
    return {
        "run_id": run_id,
        "pdb_id": "TEST",
        "structure_source": {
            "provider": "local",
            "identifier": "TEST",
            "representation": "local",
        },
        "runtime_seconds": 0.2,
        "total_cavities": len(pockets),
        "cavities": pockets,
        "provenance": {
            "input_sha256": "1" * 64,
            "prepared_sha256": "2" * 64,
            "preparation_config_sha256": "3" * 64,
            "preparation_report_sha256": "4" * 64,
            "code_identity_sha256": "5" * 64,
            "environment_identity_sha256": "6" * 64,
        },
        "static_detector": {
            "detector_version": "canonical-static-v1",
            "detector_config_sha256": "7" * 64,
            "atom_policy_version": "protein-heavy-bondi-v1",
        },
        "scoring": {
            "contract_version": "heuristic-pocket-ranking-v1",
            "profile_manifest": {
                "profile_id": "default",
                "config_sha256": "8" * 64,
            },
        },
        "motion_aware": {
            "status": "experimental",
            "canonical_ranking_affected": False,
            "motion_pockets": [],
        },
        "validation_status": "recovery_unvalidated",
        "canonical_eligible": False,
    }


def _atlas_pocket(local_id: str, rank: int, volume: float) -> dict:
    return {
        "id": local_id,
        "pocket_id": local_id,
        "rank": rank,
        "center": [float(rank), 2.0, 3.0],
        "volume": volume,
        "radius_geom": 2.0,
        "radius_clear": 1.5,
        "merged_vertices": 4,
        "hydrophobic_ratio": 0.5,
        "polar_atoms": 2,
        "bio_score": 0.7,
        "heuristic_quality_tier": "high",
        "druggability_class": "high",
        "druggable": True,
        "score_components": {
            "volume_score": 0.5,
            "hydrophobicity_score": 0.5,
            "enclosure_score": 0.7,
            "depth_score": 0.6,
        },
        "scoring_measurements": {
            "schema_version": "pocket-scoring-measurements-v1",
            "raw_measurements": {"volume": volume},
            "normalized_metrics": {
                "volume": 0.5,
                "hydrophobicity": 0.5,
                "enclosure": 0.7,
                "depth": 0.6,
            },
        },
    }


def test_atlas_v1_preserves_multiple_runs_without_inheriting_old_pockets(
    tmp_path: Path,
) -> None:
    from src.atlas_v1 import AtlasV1

    first = _atlas_report(
        "run-first",
        [_atlas_pocket("BV-1", 1, 400.0), _atlas_pocket("BV-2", 2, 250.0)],
    )
    second = _atlas_report("run-second", [_atlas_pocket("BV-3", 1, 510.0)])

    with AtlasV1(tmp_path / "atlas-v1.sqlite") as atlas:
        first_result = atlas.persist_report(first)
        second_result = atlas.persist_report(second)
        runs = atlas.list_runs("TEST")
        second_pockets = atlas.get_run_pockets("run-second")

    assert first_result.detected_total == first_result.persisted_total == 2
    assert second_result.detected_total == second_result.persisted_total == 1
    assert {run["run_id"] for run in runs} == {"run-first", "run-second"}
    assert [pocket["pocket_id"] for pocket in second_pockets] == ["BV-3"]


def test_atlas_v1_rolls_back_entire_run_on_invalid_pocket(tmp_path: Path) -> None:
    from src.atlas_v1 import AtlasPersistenceError, AtlasV1

    valid = _atlas_pocket("BV-1", 1, 400.0)
    invalid = _atlas_pocket("BV-BAD", 2, 200.0)
    invalid["center"] = [1.0, 2.0]
    report = _atlas_report("run-rollback", [valid, invalid])

    with AtlasV1(tmp_path / "atlas-v1.sqlite") as atlas:
        with pytest.raises(AtlasPersistenceError):
            atlas.persist_report(report)
        assert atlas.get_run("run-rollback") is None
        assert atlas.get_run_pockets("run-rollback") == []


def test_atlas_v1_refuses_to_overwrite_existing_run(tmp_path: Path) -> None:
    from src.atlas_v1 import AtlasPersistenceError, AtlasV1

    report = _atlas_report("run-fixed", [_atlas_pocket("BV-1", 1, 400.0)])
    changed = _atlas_report("run-fixed", [_atlas_pocket("BV-9", 1, 900.0)])

    with AtlasV1(tmp_path / "atlas-v1.sqlite") as atlas:
        atlas.persist_report(report)
        with pytest.raises(AtlasPersistenceError):
            atlas.persist_report(changed)
        pockets = atlas.get_run_pockets("run-fixed")

    assert [pocket["pocket_id"] for pocket in pockets] == ["BV-1"]


def test_atlas_v1_keeps_distinct_preparation_configs_for_identical_output(
    tmp_path: Path,
) -> None:
    from src.atlas_v1 import AtlasV1

    first = _atlas_report("run-prep-a", [_atlas_pocket("BV-1", 1, 400.0)])
    second = _atlas_report("run-prep-b", [_atlas_pocket("BV-2", 1, 400.0)])
    second["provenance"]["preparation_config_sha256"] = "9" * 64
    second["provenance"]["preparation_report_sha256"] = "a" * 64

    with AtlasV1(tmp_path / "atlas-v1.sqlite") as atlas:
        atlas.persist_report(first)
        atlas.persist_report(second)
        prepared_count = atlas.conn.execute("SELECT COUNT(*) FROM prepared_structures").fetchone()[
            0
        ]
        run_preparation_ids = {row["prepared_structure_id"] for row in atlas.list_runs("TEST")}

    assert prepared_count == 2
    assert len(run_preparation_ids) == 2


def test_legacy_atlas_read_only_mode_rejects_writes(tmp_path: Path) -> None:
    from src.database import AtlasDB

    db_path = tmp_path / "legacy.sqlite"
    with AtlasDB(str(db_path), read_only=False) as atlas:
        atlas.insert_protein({"pdb_id": "TEST"})

    with AtlasDB(str(db_path), read_only=True) as atlas:
        assert atlas.get_protein("TEST") is not None
        with pytest.raises(sqlite3.OperationalError):
            atlas.insert_protein({"pdb_id": "OTHER"})


def test_pipeline_cache_hit_still_completes_run_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from main import BioVoidPipeline
    from src.structure_preparation import PreparationResult

    calls = {
        "scan": 0,
        "merge": 0,
        "score": 0,
        "report": 0,
        "visualize": 0,
        "atlas": 0,
        "save": 0,
    }

    def fake_fetch(pipeline: BioVoidPipeline) -> None:
        pipeline.raw_structure_file = str(tmp_path / "raw.pdb")

    def fake_prepare(pipeline: BioVoidPipeline) -> None:
        preparation_dir = pipeline.workspace.path / "preparation"
        preparation_dir.mkdir(parents=True, exist_ok=True)
        prepared = preparation_dir / "prepared.pdb"
        context = preparation_dir / "context.json"
        report = preparation_dir / "report.json"
        manifest = preparation_dir / "manifest.json"
        for path in (prepared, context, report, manifest):
            path.write_text("{}\n", encoding="utf-8")
        pipeline.pdb_file = str(prepared)
        pipeline.preparation_result = PreparationResult(
            prepared_path=prepared,
            context_path=context,
            report_path=report,
            manifest_path=manifest,
            input_sha256="1" * 64,
            prepared_sha256="2" * 64,
            config_sha256="3" * 64,
            report_sha256="4" * 64,
        )

    def fake_scan(pipeline: BioVoidPipeline) -> None:
        calls["scan"] += 1
        pipeline.voids = [{"candidate_index": 0}]
        pipeline.static_detector_metadata = {
            "detector_version": "canonical-static-v1",
            "detector_config_sha256": pipeline.cache_identity.detector_config_sha256,
            "atom_policy_version": "protein-heavy-bondi-v1",
            "candidate_count": 1,
            "warnings": [],
        }

    def fake_merge(pipeline: BioVoidPipeline) -> None:
        calls["merge"] += 1
        pipeline.cavities = [
            _pocket(
                "BV-CACHED",
                volume=500.0,
                hydrophobic_ratio=0.5,
                center=(0.0, 0.0, 0.0),
            )
        ]

    def fake_score(pipeline: BioVoidPipeline) -> None:
        calls["score"] += 1

    def fake_report(pipeline: BioVoidPipeline) -> dict:
        calls["report"] += 1
        return {
            "run_id": pipeline.run_id,
            "pdb_id": pipeline.pdb_id,
            "cache_status": pipeline.cache_status["status"],
        }

    def fake_visualize(_pipeline: BioVoidPipeline) -> None:
        calls["visualize"] += 1

    def fake_atlas(_pipeline: BioVoidPipeline, _report: dict) -> dict:
        calls["atlas"] += 1
        return {"status": "completed"}

    def fake_save(_pipeline: BioVoidPipeline, _report: dict) -> None:
        calls["save"] += 1

    monkeypatch.setattr(BioVoidPipeline, "_fetch_structure", fake_fetch)
    monkeypatch.setattr(BioVoidPipeline, "_prepare_structure", fake_prepare)
    monkeypatch.setattr(BioVoidPipeline, "_scan_voids", fake_scan)
    monkeypatch.setattr(BioVoidPipeline, "_merge_cavities", fake_merge)
    monkeypatch.setattr(BioVoidPipeline, "_score_druggability", fake_score)
    monkeypatch.setattr(BioVoidPipeline, "_generate_report", fake_report)
    monkeypatch.setattr(BioVoidPipeline, "_visualize_results", fake_visualize)
    monkeypatch.setattr(BioVoidPipeline, "_save_to_atlas", fake_atlas)
    monkeypatch.setattr(BioVoidPipeline, "_save_report", fake_save)

    cache_dir = tmp_path / "cache"
    first = BioVoidPipeline(
        "TEST",
        output_dir=str(tmp_path / "runs"),
        cache_dir=cache_dir,
    )
    first_report = first.run()
    second = BioVoidPipeline(
        "TEST",
        output_dir=str(tmp_path / "runs"),
        cache_dir=cache_dir,
    )
    second_report = second.run()

    assert first_report["cache_status"] == "stored"
    assert second_report["cache_status"] == "hit"
    assert first_report["run_id"] != second_report["run_id"]
    assert calls == {
        "scan": 1,
        "merge": 1,
        "score": 2,
        "report": 2,
        "visualize": 2,
        "atlas": 2,
        "save": 2,
    }


def test_cached_core_drops_run_local_motion_manifest(tmp_path: Path) -> None:
    from main import BioVoidPipeline

    pipeline = BioVoidPipeline(
        "TEST",
        output_dir=str(tmp_path / "runs"),
        use_cache=False,
    )
    pipeline.static_detector_metadata = {
        "detector_version": "canonical-static-v1",
        "detector_config_sha256": "1" * 64,
        "atom_policy_version": "protein-heavy-bondi-v1",
    }
    pipeline.motion_result = {
        "status": "experimental",
        "ensemble_manifest": str(tmp_path / "old-run" / "motion.json"),
        "motion_pockets": [],
    }

    core = pipeline._analysis_core()

    assert "ensemble_manifest" not in core["motion_result"]
    assert pipeline.motion_result["ensemble_manifest"].endswith("motion.json")


def test_pipeline_exposes_atlas_persistence_failure(tmp_path: Path) -> None:
    from main import BioVoidPipeline

    pipeline = BioVoidPipeline(
        "TEST",
        output_dir=str(tmp_path / "runs"),
        atlas_db_path=tmp_path / "atlas-v1.sqlite",
        use_cache=False,
    )

    result = pipeline._save_to_atlas({"run_id": pipeline.run_id})

    assert result["status"] == "failed"
    assert result["run_id"] == pipeline.run_id
    assert result["error"]
