"""
Test Suite for Phase 5.2: Cryptic Pocket Atlas Database
=========================================================

Tests for:
- AtlasDB initialization & schema creation
- CRUD operations (insert, query, delete)
- Batch insert performance
- Report ingestion (batch_insert_from_report)
- Advanced queries (score, druggable, elite, search)
- Statistics & counts
- Backup & restore (gzip)
- Data Lake helpers (visual archive paths, CSV export)
- Migration support

Author: Bio-Void Hunter Team
"""

from __future__ import annotations

import gzip
import json
import shutil
import time
from pathlib import Path

import pytest

from src.database import (
    DB_VERSION,
    AtlasDB,
    DockingRecord,
    PocketRecord,
    ProteinRecord,
)

# ============================================================================
# FIXTURES
# ============================================================================

TMP_DIR = Path("data/_test_atlas")


@pytest.fixture(autouse=True)
def _cleanup_db():
    """Create/clean test directory before and after each test."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    yield
    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR, ignore_errors=True)


@pytest.fixture
def db() -> AtlasDB:
    """Fresh AtlasDB instance for each test."""
    db_path = str(TMP_DIR / "test_atlas.db")
    atlas = AtlasDB(db_path=db_path)
    yield atlas
    atlas.close()


@pytest.fixture
def sample_pocket() -> dict:
    """Sample pocket record matching 1CBS report format."""
    return {
        "pdb_id": "1CBS",
        "pocket_id": 26,
        "rank": 1,
        "bio_score": 0.8577,
        "volume": 1563.18,
        "center": [18.83, 19.84, 19.98],
        "radius_geom": 1.2,
        "radius_clear": 4.99,
        "merged_vertices": 3,
        "hydrophobic_ratio": 1.0,
        "polar_atoms": 0,
        "druggable": True,
        "druggability_class": "high",
        "score_components": {
            "volume_score": 0.7701,
            "hydrophobicity_score": 1.0,
            "enclosure_score": 1.0,
            "depth_score": 0.6607,
        },
        "profile_used": "Default",
    }


@pytest.fixture
def sample_report() -> dict:
    """Minimal pipeline report matching 1cbs_report.json structure."""
    return {
        "pdb_id": "1CBS",
        "n_frames": 2,
        "scoring_profile": "default",
        "total_voids": 324,
        "total_cavities": 99,
        "druggable_cavities": 33,
        "high_druggability": 21,
        "medium_druggability": 55,
        "runtime_seconds": 11.73,
        "cavities": [
            {
                "id": 26,
                "rank": 1,
                "volume": 1563.18,
                "center": [18.83, 19.84, 19.98],
                "radius_geom": 1.2,
                "radius_clear": 4.99,
                "merged_vertices": 3,
                "hydrophobic_ratio": 1.0,
                "polar_atoms": 0,
                "druggable": True,
                "bio_score": 0.8577,
                "druggability_class": "high",
                "score_components": {
                    "volume_score": 0.7701,
                    "hydrophobicity_score": 1.0,
                    "enclosure_score": 1.0,
                    "depth_score": 0.6607,
                },
                "profile_used": "Default",
            },
            {
                "id": 11,
                "rank": 2,
                "volume": 2205.55,
                "center": [22.22, 22.34, 16.51],
                "radius_geom": 0.93,
                "radius_clear": 4.72,
                "merged_vertices": 5,
                "hydrophobic_ratio": 0.75,
                "polar_atoms": 0,
                "druggable": True,
                "bio_score": 0.8018,
                "druggability_class": "high",
                "score_components": {
                    "volume_score": 1.0,
                    "hydrophobicity_score": 0.75,
                    "enclosure_score": 1.0,
                    "depth_score": 0.4573,
                },
                "profile_used": "Default",
            },
            {
                "id": 99,
                "rank": 3,
                "volume": 120.0,
                "center": [10.0, 10.0, 10.0],
                "radius_geom": 0.8,
                "radius_clear": 3.5,
                "merged_vertices": 2,
                "hydrophobic_ratio": 0.3,
                "polar_atoms": 2,
                "druggable": False,
                "bio_score": 0.35,
                "druggability_class": "low",
                "score_components": {
                    "volume_score": 0.1,
                    "hydrophobicity_score": 0.3,
                    "enclosure_score": 0.5,
                    "depth_score": 0.2,
                },
                "profile_used": "Default",
            },
        ],
    }


# ============================================================================
# TEST: INITIALIZATION
# ============================================================================


class TestAtlasDBInit:
    def test_creates_db_file(self, db: AtlasDB):
        """Database file should be created on init."""
        assert db.db_path.exists()

    def test_schema_version(self, db: AtlasDB):
        """Schema version should match DB_VERSION."""
        assert db.get_schema_version() == DB_VERSION

    def test_tables_exist(self, db: AtlasDB):
        """All required tables should exist."""
        tables = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {t["name"] for t in tables}
        assert "proteins" in table_names
        assert "pockets" in table_names
        assert "docking_results" in table_names
        assert "atlas_meta" in table_names

    def test_indexes_exist(self, db: AtlasDB):
        """Key indexes should be created."""
        indexes = db.conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        idx_names = {i["name"] for i in indexes}
        assert "idx_pockets_bio_score" in idx_names
        assert "idx_pockets_druggable" in idx_names
        assert "idx_pockets_pdb_id" in idx_names

    def test_context_manager(self):
        """AtlasDB should work as a context manager."""
        db_path = str(TMP_DIR / "ctx_test.db")
        with AtlasDB(db_path=db_path) as atlas:
            atlas.insert_protein({"pdb_id": "1CBS"})
            assert atlas.count_proteins() == 1
        # Should be closed now
        assert atlas._conn is None


# ============================================================================
# TEST: INSERT OPERATIONS
# ============================================================================


class TestInsertOperations:
    def test_insert_protein(self, db: AtlasDB):
        """Insert and retrieve a protein record."""
        db.insert_protein(
            {
                "pdb_id": "1CBS",
                "resolution": 1.8,
                "method": "X-RAY DIFFRACTION",
                "total_cavities": 99,
                "druggable_cavities": 33,
                "top_bio_score": 0.8577,
            }
        )
        result = db.get_protein("1CBS")
        assert result is not None
        assert result["pdb_id"] == "1CBS"
        assert result["resolution"] == 1.8
        assert result["total_cavities"] == 99
        assert result["top_bio_score"] == 0.8577

    def test_insert_protein_upsert(self, db: AtlasDB):
        """Second insert should update existing record."""
        db.insert_protein({"pdb_id": "1CBS", "total_cavities": 50})
        db.insert_protein({"pdb_id": "1CBS", "total_cavities": 99})
        result = db.get_protein("1CBS")
        assert result is not None
        assert result["total_cavities"] == 99

    def test_insert_discovery(self, db: AtlasDB, sample_pocket: dict):
        """Insert and retrieve a pocket discovery."""
        row_id = db.insert_discovery(sample_pocket)
        assert row_id > 0

        result = db.get_pocket("1CBS", 26)
        assert result is not None
        assert result["bio_score"] == 0.8577
        assert result["volume"] == 1563.18
        assert result["druggable"] == 1  # SQLite stores as int
        assert result["druggability_class"] == "high"
        assert result["center_x"] == 18.83
        assert result["center_y"] == 19.84
        assert result["center_z"] == 19.98

    def test_insert_discovery_with_score_components(self, db: AtlasDB, sample_pocket: dict):
        """Score components should be extracted correctly."""
        db.insert_discovery(sample_pocket)
        result = db.get_pocket("1CBS", 26)
        assert result is not None
        assert result["volume_score"] == 0.7701
        assert result["enclosure_score"] == 1.0
        assert result["depth_score"] == 0.6607
        assert result["hydrophobicity_score"] == 1.0

    def test_insert_docking(self, db: AtlasDB):
        """Insert and query a docking result."""
        row_id = db.insert_docking(
            {
                "pdb_id": "1CBS",
                "pocket_id": 26,
                "ligand_name": "retinoic_acid",
                "affinity": -8.5,
                "affinity_class": "strong",
                "n_hbonds": 3,
                "validated": True,
            }
        )
        assert row_id > 0

    def test_case_insensitive_pdb_id(self, db: AtlasDB, sample_pocket: dict):
        """PDB IDs should be normalized to uppercase."""
        sample_pocket["pdb_id"] = "1cbs"
        db.insert_discovery(sample_pocket)
        result = db.get_pocket("1CBS", 26)
        assert result is not None
        assert result["pdb_id"] == "1CBS"


# ============================================================================
# TEST: BATCH INSERT
# ============================================================================


class TestBatchInsert:
    def test_batch_insert_discoveries(self, db: AtlasDB):
        """Batch insert should handle multiple records."""
        records = [
            {
                "pdb_id": "TEST",
                "pocket_id": i,
                "bio_score": 0.5 + (i * 0.01),
                "volume": 100 + i,
                "druggable": i % 2 == 0,
            }
            for i in range(100)
        ]
        count = db.batch_insert_discoveries(records)
        assert count == 100
        assert db.count_pockets() == 100

    def test_batch_insert_from_report(self, db: AtlasDB, sample_report: dict):
        """Report ingestion should create protein + pockets."""
        count = db.batch_insert_from_report(sample_report)
        assert count == 3  # 3 cavities in sample_report

        # Protein should exist
        protein = db.get_protein("1CBS")
        assert protein is not None
        assert protein["total_cavities"] == 99
        assert protein["druggable_cavities"] == 33

        # Pockets should exist
        pockets = db.get_pockets_for_protein("1CBS")
        assert len(pockets) == 3
        assert pockets[0]["rank"] == 1
        assert pockets[0]["bio_score"] == 0.8577

    def test_batch_insert_performance(self, db: AtlasDB):
        """10,000 records should insert in < 5 seconds."""
        records = [
            {
                "pdb_id": f"P{i:04d}",
                "pocket_id": j,
                "bio_score": 0.1 + (j * 0.05),
                "volume": 100 + j * 10,
                "druggable": j < 5,
                "druggability_class": "high" if j < 3 else "low",
            }
            for i in range(1000)
            for j in range(10)
        ]
        t0 = time.time()
        count = db.batch_insert_discoveries(records, batch_size=500)
        elapsed = time.time() - t0

        assert count == 10000
        assert elapsed < 5.0, f"Batch insert too slow: {elapsed:.2f}s"
        assert db.count_pockets() == 10000


# ============================================================================
# TEST: QUERY OPERATIONS
# ============================================================================


class TestQueryOperations:
    def _seed(self, db: AtlasDB):
        """Insert test data for query tests."""
        records = [
            {
                "pdb_id": "1CBS",
                "pocket_id": 1,
                "rank": 1,
                "bio_score": 0.85,
                "volume": 1500.0,
                "druggable": True,
                "druggability_class": "high",
            },
            {
                "pdb_id": "1CBS",
                "pocket_id": 2,
                "rank": 2,
                "bio_score": 0.72,
                "volume": 900.0,
                "druggable": True,
                "druggability_class": "high",
            },
            {
                "pdb_id": "1CBS",
                "pocket_id": 3,
                "rank": 3,
                "bio_score": 0.45,
                "volume": 200.0,
                "druggable": True,
                "druggability_class": "medium",
            },
            {
                "pdb_id": "1AKE",
                "pocket_id": 1,
                "rank": 1,
                "bio_score": 0.60,
                "volume": 800.0,
                "druggable": True,
                "druggability_class": "medium",
            },
            {
                "pdb_id": "1AKE",
                "pocket_id": 2,
                "rank": 2,
                "bio_score": 0.30,
                "volume": 150.0,
                "druggable": False,
                "druggability_class": "low",
            },
        ]
        db.batch_insert_discoveries(records)

    def test_query_by_score(self, db: AtlasDB):
        """Query by bio_score range."""
        self._seed(db)
        results = db.query_by_score(min_score=0.7)
        assert len(results) == 2
        assert results[0]["bio_score"] >= results[1]["bio_score"]

    def test_query_druggable(self, db: AtlasDB):
        """Query only druggable pockets."""
        self._seed(db)
        results = db.query_druggable()
        assert len(results) == 4
        assert all(r["druggable"] == 1 for r in results)

    def test_query_druggable_by_class(self, db: AtlasDB):
        """Filter druggable by druggability class."""
        self._seed(db)
        high = db.query_druggable(druggability_class="high")
        assert len(high) == 2
        medium = db.query_druggable(druggability_class="medium")
        assert len(medium) == 2

    def test_query_elite_pockets(self, db: AtlasDB):
        """Elite pockets: bio_score >= 0.6, druggable, volume >= 100."""
        self._seed(db)
        elite = db.query_elite_pockets(min_bio_score=0.6)
        assert len(elite) == 3  # 0.85, 0.72, 0.60
        assert all(r["bio_score"] >= 0.6 for r in elite)

    def test_search_pockets_multi_filter(self, db: AtlasDB):
        """Advanced search with multiple filters."""
        self._seed(db)
        results = db.search_pockets(
            pdb_id="1CBS",
            min_score=0.5,
            druggable_only=True,
        )
        assert len(results) == 2  # 0.85 and 0.72

    def test_search_pockets_volume_filter(self, db: AtlasDB):
        """Search with volume range filter."""
        self._seed(db)
        results = db.search_pockets(min_volume=500.0)
        assert len(results) == 3  # 1500, 900, 800

    def test_query_performance_10k(self, db: AtlasDB):
        """10,000 records should be queryable in < 1 second."""
        records = [
            {
                "pdb_id": f"P{i:04d}",
                "pocket_id": j,
                "bio_score": 0.1 + (j * 0.08),
                "volume": 100 + j * 50,
                "druggable": j >= 5,
                "druggability_class": "high" if j >= 7 else "medium",
            }
            for i in range(1000)
            for j in range(10)
        ]
        db.batch_insert_discoveries(records, batch_size=1000)

        t0 = time.time()
        results = db.query_by_score(min_score=0.7, limit=100)
        elapsed = time.time() - t0

        assert len(results) > 0
        assert elapsed < 1.0, f"Query too slow: {elapsed:.4f}s"

    def test_get_pockets_for_protein(self, db: AtlasDB):
        """Get all pockets ordered by rank."""
        self._seed(db)
        pockets = db.get_pockets_for_protein("1CBS")
        assert len(pockets) == 3
        assert pockets[0]["rank"] < pockets[1]["rank"]


# ============================================================================
# TEST: DELETE OPERATIONS
# ============================================================================


class TestDeleteOperations:
    def test_delete_protein_cascading(self, db: AtlasDB, sample_pocket: dict):
        """Deleting a protein should remove its pockets and docking."""
        db.insert_protein({"pdb_id": "1CBS", "total_cavities": 1})
        db.insert_discovery(sample_pocket)
        db.insert_docking(
            {
                "pdb_id": "1CBS",
                "pocket_id": 26,
                "ligand_name": "test",
                "affinity": -5.0,
            }
        )

        deleted = db.delete_protein("1CBS")
        assert deleted == 3  # 1 protein + 1 pocket + 1 docking

        assert db.get_protein("1CBS") is None
        assert db.get_pocket("1CBS", 26) is None

    def test_delete_pocket(self, db: AtlasDB, sample_pocket: dict):
        """Delete a specific pocket."""
        db.insert_discovery(sample_pocket)
        deleted = db.delete_pocket("1CBS", 26)
        assert deleted == 1
        assert db.get_pocket("1CBS", 26) is None


# ============================================================================
# TEST: STATISTICS
# ============================================================================


class TestStatistics:
    def test_counts(self, db: AtlasDB, sample_report: dict):
        """Count functions should return correct values."""
        db.batch_insert_from_report(sample_report)
        assert db.count_proteins() == 1
        assert db.count_pockets() == 3
        assert db.count_druggable() == 2  # 2 druggable in sample
        assert db.count_elite(min_bio_score=0.6) == 2

    def test_get_statistics(self, db: AtlasDB, sample_report: dict):
        """Statistics should include all expected fields."""
        db.batch_insert_from_report(sample_report)
        stats = db.get_statistics()

        assert stats["total_proteins"] == 1
        assert stats["total_pockets"] == 3
        assert stats["druggable_pockets"] == 2
        assert "avg_bio_score" in stats
        assert "class_distribution" in stats
        assert "high" in stats["class_distribution"]

    def test_empty_statistics(self, db: AtlasDB):
        """Statistics on empty DB should return zeros."""
        stats = db.get_statistics()
        assert stats["total_proteins"] == 0
        assert stats["total_pockets"] == 0


# ============================================================================
# TEST: BACKUP & RESTORE
# ============================================================================


class TestBackupRestore:
    def test_backup_creates_file(self, db: AtlasDB, sample_pocket: dict):
        """Backup should create a gzip file."""
        db.insert_discovery(sample_pocket)
        backup_path = db.backup()
        assert Path(backup_path).exists()
        assert backup_path.endswith(".bak.gz")

    def test_restore_data_integrity(self, db: AtlasDB, sample_pocket: dict):
        """Restored DB should contain same data."""
        db.insert_discovery(sample_pocket)
        backup_path = db.backup()

        # Delete original data
        db.delete_pocket("1CBS", 26)
        assert db.get_pocket("1CBS", 26) is None

        # Restore
        db.restore(backup_path)
        result = db.get_pocket("1CBS", 26)
        assert result is not None
        assert result["bio_score"] == 0.8577

    def test_backup_is_compressed(self, db: AtlasDB, sample_pocket: dict):
        """Backup file should be valid gzip."""
        db.insert_discovery(sample_pocket)
        backup_path = db.backup()
        with gzip.open(backup_path, "rb") as f:
            data = f.read()
        assert len(data) > 0


# ============================================================================
# TEST: DATA LAKE HELPERS
# ============================================================================


class TestDataLakeHelpers:
    def test_visual_archive_path(self, db: AtlasDB):
        """Visual archive paths should follow naming convention."""
        render = db.get_visual_archive_path("1CBS", "render")
        assert render.name == "1cbs_render.pml"
        assert render.parent.name == "results"

        view = db.get_visual_archive_path("1CBS", "view")
        assert view.name == "1cbs_view.html"

        report = db.get_visual_archive_path("1CBS", "report")
        assert report.name == "1cbs_report.json"

    def test_export_elite_csv(self, db: AtlasDB, sample_report: dict):
        """CSV export should create a valid file."""
        db.batch_insert_from_report(sample_report)
        csv_path = str(TMP_DIR / "elite.csv")
        count = db.export_elite_csv(output_path=csv_path, min_bio_score=0.6)
        assert count == 2  # 2 elite pockets
        content = Path(csv_path).read_text()
        assert "pdb_id" in content  # header
        assert "1CBS" in content


# ============================================================================
# TEST: DATA CLASSES
# ============================================================================


class TestDataClasses:
    def test_protein_record_defaults(self):
        rec = ProteinRecord(pdb_id="1CBS")
        assert rec.pdb_id == "1CBS"
        assert rec.total_cavities == 0
        assert rec.status == "success"

    def test_pocket_record_defaults(self):
        rec = PocketRecord(pdb_id="1CBS", pocket_id=1)
        assert rec.bio_score == 0.0
        assert rec.druggable is False

    def test_docking_record_defaults(self):
        rec = DockingRecord(pdb_id="1CBS", pocket_id=1)
        assert rec.affinity == 0.0
        assert rec.validated is False


# ============================================================================
# TEST: REAL DATA INTEGRATION
# ============================================================================


class TestRealDataIntegration:
    def test_load_1cbs_report(self, db: AtlasDB):
        """Load real 1CBS report JSON into the database."""
        report_path = Path("data/results/1cbs_report.json")
        if not report_path.exists():
            pytest.skip("1cbs_report.json not found")

        report = json.loads(report_path.read_text(encoding="utf-8"))
        count = db.batch_insert_from_report(report)
        assert count > 0

        protein = db.get_protein("1CBS")
        assert protein is not None
        assert protein["total_cavities"] == report["total_cavities"]

        pockets = db.get_pockets_for_protein("1CBS")
        assert len(pockets) == len(report["cavities"])

        # Top pocket should match
        top = pockets[0]
        assert top["rank"] == 1
        assert abs(top["bio_score"] - report["cavities"][0]["bio_score"]) < 0.001

    def test_acceptance_criteria(self, db: AtlasDB):
        """
        Acceptance criteria from progress.md:
            db.insert_discovery({'pdb_id': '1CBS', ...})
            results = db.query_by_score(min_score=0.7)
            assert len(results) > 0
        """
        db.insert_discovery(
            {
                "pdb_id": "1CBS",
                "pocket_id": 1,
                "bio_score": 0.85,
                "volume": 450.0,
            }
        )
        results = db.query_by_score(min_score=0.7)
        assert len(results) > 0
        assert results[0]["pdb_id"] == "1CBS"
