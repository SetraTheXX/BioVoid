"""
Bio-Void Hunter: Dashboard Unit Tests (Phase 5.3)
===================================================

Tests for the Discovery Dashboard data helpers and chart builders.
We test the logic layer (data loading, KPI building, chart construction)
without requiring a running Streamlit server.

Test Categories:
1. DataLoading   — load_statistics, load_pocket_dataframe, load_elite
2. KPICards      — build_kpi_cards correctness
3. ChartBuilders — histogram, scatter, pie, 3D view, bar chart
4. CSVExport     — dataframe_to_csv
5. ProteinList   — load_protein_list
6. EdgeCases     — empty database, missing columns
7. Performance   — query and chart build times <2s

Author: Bio-Void Hunter Team
Version: 0.9.0 (Phase 5.3)
"""

import json
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.database import AtlasDB
from src.dashboard import (
    APP_TITLE,
    CLASS_COLORS,
    CLASS_LABELS,
    COLOR_DRUGGABLE,
    COLOR_NON_DRUGGABLE,
    DEFAULT_DB,
    PAGE_SIZE,
    build_3d_pocket_view,
    build_class_pie,
    build_kpi_cards,
    build_score_histogram,
    build_top_proteins_bar,
    build_volume_scatter,
    dataframe_to_csv,
    load_elite_dataframe,
    load_pocket_dataframe,
    load_protein_list,
    load_statistics,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary AtlasDB with sample data."""
    db_path = str(tmp_path / "test_atlas.db")
    db = AtlasDB(db_path)

    # Insert sample proteins
    for pdb_id in ["1CBS", "1AKE", "1PPM"]:
        db.insert_protein(
            {
                "pdb_id": pdb_id,
                "resolution": 2.0,
                "method": "X-RAY",
                "total_cavities": 30,
                "druggable_cavities": 5,
                "high_score_count": 2,
                "medium_score_count": 3,
                "top_bio_score": 0.85,
                "analysis_runtime": 1.5,
                "n_frames": 1,
            }
        )

    # Insert sample pockets
    for pdb_id in ["1CBS", "1AKE", "1PPM"]:
        for i in range(10):
            score = 0.3 + (i * 0.07)  # 0.3 to 0.93
            druggable = score > 0.55
            drug_class = (
                "high"
                if score > 0.75
                else "medium" if score > 0.55 else "low"
            )
            db.insert_discovery(
                {
                    "pdb_id": pdb_id,
                    "pocket_id": i + 1,
                    "rank": i + 1,
                    "bio_score": round(score, 4),
                    "volume": 100 + i * 50,
                    "center": [10.0 + i, 20.0 + i, 30.0 + i],
                    "radius_geom": 5.0,
                    "radius_clear": 3.0,
                    "merged_vertices": 50,
                    "hydrophobic_ratio": 0.4 + i * 0.05,
                    "polar_atoms": 10,
                    "druggable": druggable,
                    "druggability_class": drug_class,
                    "score_components": {
                        "enclosure_score": 0.5 + i * 0.04,
                        "depth_score": 0.3 + i * 0.06,
                        "volume_score": 0.4 + i * 0.05,
                        "hydrophobicity_score": 0.35 + i * 0.04,
                    },
                }
            )

    yield db
    db.close()


@pytest.fixture
def empty_db(tmp_path):
    """Create an empty AtlasDB."""
    db_path = str(tmp_path / "empty_atlas.db")
    db = AtlasDB(db_path)
    yield db
    db.close()


@pytest.fixture
def sample_df():
    """Sample pocket DataFrame for chart testing."""
    return pd.DataFrame(
        {
            "pdb_id": ["1CBS"] * 5,
            "pocket_id": [1, 2, 3, 4, 5],
            "rank": [1, 2, 3, 4, 5],
            "bio_score": [0.9, 0.75, 0.6, 0.4, 0.2],
            "volume": [500.0, 350.0, 250.0, 150.0, 80.0],
            "druggable": [1, 1, 1, 0, 0],
            "druggability_class": ["high", "high", "medium", "low", "low"],
            "center_x": [10.0, 15.0, 20.0, 25.0, 30.0],
            "center_y": [10.0, 15.0, 20.0, 25.0, 30.0],
            "center_z": [10.0, 15.0, 20.0, 25.0, 30.0],
            "hydrophobic_ratio": [0.7, 0.6, 0.5, 0.4, 0.3],
            "enclosure_score": [0.8, 0.7, 0.6, 0.5, 0.4],
            "depth_score": [0.7, 0.6, 0.5, 0.4, 0.3],
        }
    )


# ============================================================================
# DATA LOADING TESTS
# ============================================================================


class TestDataLoading:
    """Test data loading functions."""

    def test_load_statistics(self, tmp_db):
        stats = load_statistics(tmp_db)
        assert stats["total_proteins"] == 3
        assert stats["total_pockets"] == 30
        assert stats["druggable_pockets"] > 0
        assert "avg_bio_score" in stats
        assert "class_distribution" in stats

    def test_load_statistics_empty(self, empty_db):
        stats = load_statistics(empty_db)
        assert stats["total_proteins"] == 0
        assert stats["total_pockets"] == 0

    def test_load_pocket_dataframe_all(self, tmp_db):
        df = load_pocket_dataframe(tmp_db)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 30  # 3 proteins x 10 pockets
        assert "bio_score" in df.columns
        assert "pdb_id" in df.columns

    def test_load_pocket_dataframe_filtered_by_pdb(self, tmp_db):
        df = load_pocket_dataframe(tmp_db, pdb_id="1CBS")
        assert len(df) == 10
        assert all(df["pdb_id"] == "1CBS")

    def test_load_pocket_dataframe_filtered_by_score(self, tmp_db):
        df = load_pocket_dataframe(tmp_db, min_score=0.7)
        assert len(df) > 0
        assert all(df["bio_score"] >= 0.7)

    def test_load_pocket_dataframe_druggable_only(self, tmp_db):
        df = load_pocket_dataframe(tmp_db, druggable_only=True)
        assert len(df) > 0
        assert all(df["druggable"] == 1)

    def test_load_pocket_dataframe_class_filter(self, tmp_db):
        df = load_pocket_dataframe(tmp_db, druggability_class="high")
        assert len(df) > 0
        assert all(df["druggability_class"] == "high")

    def test_load_pocket_dataframe_volume_filter(self, tmp_db):
        df = load_pocket_dataframe(tmp_db, min_volume=300, max_volume=500)
        assert len(df) > 0
        assert all(df["volume"] >= 300)
        assert all(df["volume"] <= 500)

    def test_load_pocket_dataframe_sort(self, tmp_db):
        df = load_pocket_dataframe(tmp_db, order_by="volume DESC", limit=5)
        assert len(df) == 5
        volumes = df["volume"].tolist()
        assert volumes == sorted(volumes, reverse=True)

    def test_load_pocket_dataframe_empty(self, empty_db):
        df = load_pocket_dataframe(empty_db)
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_load_pocket_dataframe_no_match(self, tmp_db):
        df = load_pocket_dataframe(tmp_db, pdb_id="XXXX")
        assert df.empty

    def test_load_protein_list(self, tmp_db):
        proteins = load_protein_list(tmp_db)
        assert isinstance(proteins, list)
        assert len(proteins) == 3
        assert "1CBS" in proteins
        assert proteins == sorted(proteins)  # should be sorted

    def test_load_protein_list_empty(self, empty_db):
        proteins = load_protein_list(empty_db)
        assert proteins == []

    def test_load_elite_dataframe(self, tmp_db):
        df = load_elite_dataframe(tmp_db, min_bio_score=0.6, min_volume=100)
        assert len(df) > 0
        assert all(df["bio_score"] >= 0.6)
        assert all(df["druggable"] == 1)

    def test_load_elite_dataframe_strict(self, tmp_db):
        df = load_elite_dataframe(tmp_db, min_bio_score=0.95)
        # Few or none should pass very strict threshold
        assert isinstance(df, pd.DataFrame)


# ============================================================================
# KPI CARD TESTS
# ============================================================================


class TestKPICards:
    """Test KPI card builder."""

    def test_build_kpi_cards_basic(self):
        stats = {
            "total_proteins": 100,
            "total_pockets": 5000,
            "druggable_pockets": 1500,
            "elite_pockets": 300,
        }
        cards = build_kpi_cards(stats)
        assert len(cards) == 4
        assert cards[0]["label"] == "Toplam Protein"
        assert cards[0]["value"] == 100
        assert cards[1]["value"] == 5000
        assert cards[2]["value"] == 1500
        assert "%" in cards[2]["delta"]  # druggable percentage
        assert cards[3]["value"] == 300

    def test_build_kpi_cards_empty(self):
        cards = build_kpi_cards({})
        assert len(cards) == 4
        assert all(c["value"] == 0 for c in cards)

    def test_build_kpi_cards_percentage_calc(self):
        stats = {
            "total_proteins": 10,
            "total_pockets": 200,
            "druggable_pockets": 50,
            "elite_pockets": 10,
        }
        cards = build_kpi_cards(stats)
        # 50/200 = 25%
        assert "25.0%" in cards[2]["delta"]


# ============================================================================
# CHART BUILDER TESTS
# ============================================================================


class TestChartBuilders:
    """Test chart building functions."""

    def test_build_score_histogram(self, sample_df):
        fig = build_score_histogram(sample_df)
        assert fig is not None
        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 0
        assert "Bio-Score" in fig.layout.title.text

    def test_build_score_histogram_empty(self):
        fig = build_score_histogram(pd.DataFrame())
        assert fig is None

    def test_build_score_histogram_missing_column(self):
        df = pd.DataFrame({"volume": [1, 2, 3]})
        fig = build_score_histogram(df)
        assert fig is None

    def test_build_volume_scatter(self, sample_df):
        fig = build_volume_scatter(sample_df)
        assert fig is not None
        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 0

    def test_build_volume_scatter_empty(self):
        fig = build_volume_scatter(pd.DataFrame())
        assert fig is None

    def test_build_class_pie(self):
        stats = {
            "class_distribution": {"high": 100, "medium": 200, "low": 500}
        }
        fig = build_class_pie(stats)
        assert fig is not None
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert fig.data[0].type == "pie"

    def test_build_class_pie_empty(self):
        fig = build_class_pie({})
        assert fig is None

    def test_build_3d_pocket_view(self, sample_df):
        fig = build_3d_pocket_view(sample_df, title="Test 3D")
        assert fig is not None
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 1  # At least one trace
        assert fig.layout.title.text == "Test 3D"

    def test_build_3d_pocket_view_default_title(self, sample_df):
        fig = build_3d_pocket_view(sample_df)
        assert fig.layout.title.text == "3D Cep Konumları"

    def test_build_3d_pocket_view_empty(self):
        fig = build_3d_pocket_view(pd.DataFrame())
        assert fig is None

    def test_build_3d_pocket_view_missing_coords(self):
        df = pd.DataFrame({"bio_score": [0.5], "volume": [100]})
        fig = build_3d_pocket_view(df)
        assert fig is None

    def test_build_3d_pocket_view_only_druggable(self, sample_df):
        df_drug = sample_df[sample_df["druggable"] == 1].copy()
        fig = build_3d_pocket_view(df_drug)
        assert fig is not None
        # Should have only the druggable trace
        assert any("İlaçlanabilir" in t.name for t in fig.data)

    def test_build_3d_pocket_view_only_non_druggable(self, sample_df):
        df_non = sample_df[sample_df["druggable"] == 0].copy()
        fig = build_3d_pocket_view(df_non)
        assert fig is not None
        assert any("İlaçlanamaz" in t.name for t in fig.data)

    def test_build_top_proteins_bar(self, tmp_db):
        fig = build_top_proteins_bar(tmp_db, limit=5)
        assert fig is not None
        assert isinstance(fig, go.Figure)

    def test_build_top_proteins_bar_empty(self, empty_db):
        fig = build_top_proteins_bar(empty_db)
        assert fig is None


# ============================================================================
# CSV EXPORT TESTS
# ============================================================================


class TestCSVExport:
    """Test CSV export functionality."""

    def test_dataframe_to_csv(self, sample_df):
        csv = dataframe_to_csv(sample_df)
        assert isinstance(csv, str)
        lines = csv.strip().split("\n")
        assert len(lines) == 6  # header + 5 rows
        assert "pdb_id" in lines[0]
        assert "bio_score" in lines[0]

    def test_dataframe_to_csv_empty(self):
        csv = dataframe_to_csv(pd.DataFrame())
        assert isinstance(csv, str)
        # Empty DF produces just empty string or newline
        assert len(csv.strip()) == 0 or csv.strip() == ""


# ============================================================================
# CONSTANTS TESTS
# ============================================================================


class TestConstants:
    """Test module constants."""

    def test_app_title(self):
        assert "Bio-Void" in APP_TITLE

    def test_class_colors_complete(self):
        for cls in ["high", "medium", "low"]:
            assert cls in CLASS_COLORS

    def test_class_labels_complete(self):
        for cls in ["high", "medium", "low"]:
            assert cls in CLASS_LABELS

    def test_page_size(self):
        assert PAGE_SIZE > 0

    def test_default_db(self):
        assert DEFAULT_DB == "data/atlas.db"


# ============================================================================
# PERFORMANCE TESTS
# ============================================================================


class TestPerformance:
    """Test performance requirements."""

    def test_load_pocket_dataframe_speed(self, tmp_db):
        """Query should complete in <2s even with filters."""
        t0 = time.perf_counter()
        df = load_pocket_dataframe(
            tmp_db, min_score=0.3, druggable_only=True, limit=1000
        )
        elapsed = time.perf_counter() - t0
        assert elapsed < 2.0, f"Query too slow: {elapsed:.3f}s"

    def test_chart_build_speed(self, sample_df):
        """Chart building should complete in <2s."""
        t0 = time.perf_counter()
        build_score_histogram(sample_df)
        build_volume_scatter(sample_df)
        build_3d_pocket_view(sample_df)
        elapsed = time.perf_counter() - t0
        assert elapsed < 2.0, f"Charts too slow: {elapsed:.3f}s"

    def test_statistics_speed(self, tmp_db):
        """Statistics query should be fast."""
        t0 = time.perf_counter()
        stats = load_statistics(tmp_db)
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0, f"Stats too slow: {elapsed:.3f}s"

    def test_large_dataset_speed(self, tmp_path):
        """Test with 1000 pockets — should still be <2s for loading + chart."""
        db_path = str(tmp_path / "large_atlas.db")
        db = AtlasDB(db_path)

        # Insert bulk data
        db.insert_protein(
            {
                "pdb_id": "BULK",
                "total_cavities": 1000,
                "druggable_cavities": 300,
                "top_bio_score": 0.95,
            }
        )
        for i in range(1000):
            score = (i % 100) / 100.0
            db.insert_discovery(
                {
                    "pdb_id": "BULK",
                    "pocket_id": i + 1,
                    "rank": i + 1,
                    "bio_score": score,
                    "volume": 50 + i * 2,
                    "center": [float(i), float(i * 2), float(i * 3)],
                    "druggable": score > 0.5,
                    "druggability_class": "high" if score > 0.7 else "low",
                    "score_components": {},
                }
            )

        t0 = time.perf_counter()
        df = load_pocket_dataframe(db, limit=1000)
        fig_3d = build_3d_pocket_view(df)
        elapsed = time.perf_counter() - t0

        assert len(df) == 1000
        assert fig_3d is not None
        assert elapsed < 2.0, f"Large dataset too slow: {elapsed:.3f}s"

        db.close()


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestIntegration:
    """End-to-end data flow tests."""

    def test_full_pipeline(self, tmp_db):
        """Test complete data flow: stats → df → charts."""
        # 1. Stats
        stats = load_statistics(tmp_db)
        assert stats["total_proteins"] > 0

        # 2. KPI cards
        cards = build_kpi_cards(stats)
        assert len(cards) == 4

        # 3. Pocket data
        df = load_pocket_dataframe(tmp_db)
        assert len(df) > 0

        # 4. Charts from data
        hist = build_score_histogram(df)
        assert hist is not None

        scatter = build_volume_scatter(df)
        assert scatter is not None

        view_3d = build_3d_pocket_view(df)
        assert view_3d is not None

        # 5. Pie from stats
        pie = build_class_pie(stats)
        assert pie is not None

        # 6. CSV export
        csv = dataframe_to_csv(df)
        assert len(csv) > 0

    def test_filter_chain(self, tmp_db):
        """Test chained filters produce valid results."""
        df = load_pocket_dataframe(
            tmp_db,
            pdb_id="1CBS",
            min_score=0.5,
            druggable_only=True,
            min_volume=200,
            order_by="bio_score DESC",
            limit=50,
        )
        if not df.empty:
            assert all(df["pdb_id"] == "1CBS")
            assert all(df["bio_score"] >= 0.5)
            assert all(df["druggable"] == 1)
            assert all(df["volume"] >= 200)
            scores = df["bio_score"].tolist()
            assert scores == sorted(scores, reverse=True)

    def test_elite_flow(self, tmp_db):
        """Test elite discovery flow."""
        df = load_elite_dataframe(tmp_db, min_bio_score=0.6)
        if not df.empty:
            fig = build_3d_pocket_view(df, title="Elite Test")
            assert fig is not None
            csv = dataframe_to_csv(df)
            assert "pdb_id" in csv

    def test_protein_list_then_detail(self, tmp_db):
        """Test protein list → detail flow."""
        proteins = load_protein_list(tmp_db)
        assert len(proteins) > 0

        # Pick first protein, load its pockets
        pdb_id = proteins[0]
        df = load_pocket_dataframe(tmp_db, pdb_id=pdb_id)
        assert len(df) > 0
        assert all(df["pdb_id"] == pdb_id)
