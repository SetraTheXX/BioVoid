"""Tests for new modules added in Sprint 1-5 + A/B/C groups."""

from pathlib import Path

import numpy as np
import pytest

from src.benchmark import (
    benchmark_single,
    compute_distance,
)
from src.cache import AnalysisCache
from src.comparison import compare_pockets, find_similar_pockets
from src.config import API, PATHS, PIPELINE
from src.ml.dataset import SplitConfig, assign_labels, check_leakage
from src.ml.features import ALL_FEATURE_NAMES, extract_batch, extract_features, normalize_features
from src.profiling import PipelineProfiler, StepTimer
from src.scoring import (
    CustomProfile,
    calculate_confidence,
    calculate_novelty_score,
    calculate_sphericity,
    get_profile,
)


class TestConfig:
    def test_paths_defaults(self):
        assert PATHS.data_root == Path("data")
        assert PATHS.atlas_db == Path("data/atlas.db")

    def test_pipeline_defaults(self):
        assert PIPELINE.n_frames == 80
        assert PIPELINE.n_modes == 10
        assert PIPELINE.profile == "default"
        assert "enzyme" in PIPELINE.scoring_profiles

    def test_api_defaults(self):
        assert API.host == "127.0.0.1"
        assert API.port == 8000


class TestProfiler:
    def test_step_timer(self):
        with StepTimer("test") as t:
            pass
        assert t.elapsed_ms >= 0
        assert t.success

    def test_pipeline_profiler(self):
        p = PipelineProfiler()
        p.start_pipeline()
        p.start("step1")
        p.stop("step1")
        p.start("step2")
        p.stop("step2")
        s = p.summary()
        assert s["n_steps"] == 2
        assert s["bottleneck"] is not None

    def test_format_table(self):
        p = PipelineProfiler()
        p.start("a")
        p.stop("a")
        table = p.format_table()
        assert "TOTAL" in table


class TestCache:
    def test_put_get(self, tmp_path):
        cache = AnalysisCache(tmp_path / "cache")
        cache.put("TEST", {"result": 42})
        result = cache.get("TEST")
        assert result == {"result": 42}

    def test_miss(self, tmp_path):
        cache = AnalysisCache(tmp_path / "cache")
        assert cache.get("NONEXISTENT") is None

    def test_invalidate(self, tmp_path):
        cache = AnalysisCache(tmp_path / "cache")
        cache.put("TEST", {"x": 1})
        cache.invalidate("TEST")
        assert cache.get("TEST") is None

    def test_stats(self, tmp_path):
        cache = AnalysisCache(tmp_path / "cache")
        cache.put("A", {"a": 1})
        cache.get("A")
        cache.get("B")
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1


class TestComparison:
    def _pocket(self, vol=0.8, hydro=0.6, encl=0.7, depth=0.5, spher=0.6):
        return {
            "score_components": {
                "volume_score": vol,
                "hydrophobicity_score": hydro,
                "enclosure_score": encl,
                "depth_score": depth,
                "sphericity": spher,
            }
        }

    def test_identical_pockets(self):
        p = self._pocket()
        r = compare_pockets(p, p)
        assert r.cosine_similarity > 0.99
        assert r.composite_similarity > 0.95

    def test_different_pockets(self):
        pa = self._pocket(0.9, 0.9, 0.9, 0.9, 0.9)
        pb = self._pocket(0.1, 0.1, 0.1, 0.1, 0.1)
        r = compare_pockets(pa, pb)
        assert r.composite_similarity < r.cosine_similarity

    def test_find_similar(self):
        query = self._pocket()
        cands = [self._pocket(0.75, 0.55, 0.65, 0.45, 0.55), self._pocket(0.1, 0.1, 0.1, 0.1, 0.1)]
        results = find_similar_pockets(query, cands, top_n=2)
        assert len(results) == 2
        assert results[0]["composite_similarity"] > results[1]["composite_similarity"]


class TestBenchmark:
    def test_compute_distance(self):
        d = compute_distance([0, 0, 0], [3, 4, 0])
        assert abs(d - 5.0) < 0.01

    def test_benchmark_single_hit(self):
        pockets = [{"center": [10, 10, 10], "bio_score": 0.8}]
        r = benchmark_single("TEST", [10, 10, 10], pockets, tolerance=8.0)
        assert r.hit

    def test_benchmark_single_miss(self):
        pockets = [{"center": [100, 100, 100], "bio_score": 0.3}]
        r = benchmark_single("TEST", [0, 0, 0], pockets, tolerance=8.0)
        assert not r.hit


class TestScoringV2:
    def test_sphericity_default(self):
        cavity = {"vertices": [[0, 0, 0]]}
        s = calculate_sphericity(cavity)
        assert 0 <= s <= 1

    def test_custom_profile(self):
        p = get_profile(
            "custom",
            custom_weights={"volume": 0.5, "hydrophobicity": 0.2, "enclosure": 0.2, "depth": 0.1},
        )
        assert isinstance(p, CustomProfile)

    def test_novelty_score(self):
        cavity = {
            "center": [10, 10, 10],
            "bio_score": 0.7,
            "score_components": {"depth_score": 0.8, "enclosure_score": 0.7},
        }
        n = calculate_novelty_score(cavity)
        assert 0 <= n <= 1

    def test_confidence(self):
        cavity = {"vertices": list(range(10)), "volume": 500, "hydrophobic_ratio": 0.6}
        metrics = {"volume": 0.8, "hydrophobicity": 0.6, "enclosure": 0.7, "depth": 0.5}
        c = calculate_confidence(cavity, metrics)
        assert "overall" in c
        assert 0 <= c["overall"] <= 1


class TestMLFeatures:
    def test_extract_features(self):
        pocket = {
            "volume": 500,
            "hydrophobic_ratio": 0.6,
            "score_components": {"volume_score": 0.8},
        }
        f = extract_features(pocket)
        assert len(f) == len(ALL_FEATURE_NAMES)
        assert f.dtype == np.float64

    def test_extract_batch(self):
        pockets = [{"volume": 300}, {"volume": 500}]
        X = extract_batch(pockets)
        assert X.shape == (2, len(ALL_FEATURE_NAMES))

    def test_normalize_standard(self):
        X = np.array([[1, 2], [3, 4], [5, 6]], dtype=float)
        X_norm, stats = normalize_features(X, method="standard")
        assert abs(X_norm.mean()) < 0.01


class TestMLDataset:
    def test_assign_labels(self):
        pockets = [
            {"bio_score": 0.8, "druggable": True},
            {"bio_score": 0.2, "druggable": False},
            {"bio_score": 0.5, "druggable": False},
        ]
        labels = assign_labels(pockets)
        assert labels[0] == 1
        assert labels[1] == 0
        assert labels[2] == -1

    def test_leakage_detection(self):
        leaks = check_leakage({"A", "B"}, {"B", "C"}, {"D"})
        assert len(leaks) == 1

    def test_split_config_validation(self):
        with pytest.raises(ValueError):
            SplitConfig(train_ratio=0.5, val_ratio=0.5, test_ratio=0.5)
