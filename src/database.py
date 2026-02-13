"""
Bio-Void Hunter: Cryptic Pocket Atlas Database (Phase 5.2)
============================================================

Production-grade SQLite database for storing, querying, and managing
discovered cryptic pockets at scale.

Key Features:
- Normalized schema (proteins + pockets + docking_results)
- B-tree indexes on bio_score, druggable, pdb_id for fast queries
- Batch insert (100-protein chunks) for high-throughput crawling
- Full CRUD API + advanced filtering + statistics
- Backup/restore with gzip compression
- JSON metadata storage for geometry & score components
- Data Lake integration (visual archive paths)

Capacity: 10M+ cavity records (~6M cavities → ~600K elite pockets)

Author: Bio-Void Hunter Team
Version: 0.8.0 (Phase 5.2)
"""

from __future__ import annotations

import gzip
import json
import logging
import shutil
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator, Sequence

LOGGER = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

DB_VERSION = 1
DEFAULT_DB_PATH = "data/atlas.db"
DEFAULT_BATCH_SIZE = 500
BACKUP_EXTENSION = ".bak.gz"

# Schema version tracking
SCHEMA_VERSION_KEY = "schema_version"


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class ProteinRecord:
    """Represents a protein entry in the atlas."""

    pdb_id: str
    resolution: float | None = None
    method: str | None = None
    total_cavities: int = 0
    druggable_cavities: int = 0
    high_score_count: int = 0
    medium_score_count: int = 0
    top_bio_score: float = 0.0
    analysis_runtime: float = 0.0
    n_frames: int = 0
    scoring_profile: str = "default"
    status: str = "success"
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PocketRecord:
    """Represents a single pocket/cavity discovery."""

    pdb_id: str
    pocket_id: int
    rank: int = 0
    bio_score: float = 0.0
    volume: float = 0.0
    center_x: float = 0.0
    center_y: float = 0.0
    center_z: float = 0.0
    radius_geom: float = 0.0
    radius_clear: float = 0.0
    merged_vertices: int = 0
    hydrophobic_ratio: float = 0.0
    polar_atoms: int = 0
    druggable: bool = False
    druggability_class: str = "low"
    enclosure_score: float = 0.0
    depth_score: float = 0.0
    volume_score: float = 0.0
    hydrophobicity_score: float = 0.0
    profile_used: str = "Default"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DockingRecord:
    """Represents a docking result for a pocket."""

    pdb_id: str
    pocket_id: int
    ligand_name: str = ""
    affinity: float = 0.0
    affinity_class: str = ""
    rmsd_lb: float = 0.0
    rmsd_ub: float = 0.0
    n_hbonds: int = 0
    n_hydrophobic: int = 0
    validated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# SCHEMA SQL
# ============================================================================

_SCHEMA_SQL = """
-- ============================================================
-- Bio-Void Hunter Atlas Database Schema v1
-- ============================================================

-- Metadata table for schema versioning
CREATE TABLE IF NOT EXISTS atlas_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Protein-level summary table
CREATE TABLE IF NOT EXISTS proteins (
    pdb_id              TEXT PRIMARY KEY,
    resolution          REAL,
    method              TEXT,
    total_cavities      INTEGER DEFAULT 0,
    druggable_cavities  INTEGER DEFAULT 0,
    high_score_count    INTEGER DEFAULT 0,
    medium_score_count  INTEGER DEFAULT 0,
    top_bio_score       REAL    DEFAULT 0.0,
    analysis_runtime    REAL    DEFAULT 0.0,
    n_frames            INTEGER DEFAULT 0,
    scoring_profile     TEXT    DEFAULT 'default',
    status              TEXT    DEFAULT 'success',
    error               TEXT,
    metadata_json       TEXT,
    created_at          TEXT    DEFAULT (datetime('now')),
    updated_at          TEXT    DEFAULT (datetime('now'))
);

-- Pocket (cavity) discovery table — the core of the Atlas
CREATE TABLE IF NOT EXISTS pockets (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    pdb_id                TEXT    NOT NULL,
    pocket_id             INTEGER NOT NULL,
    rank                  INTEGER DEFAULT 0,
    bio_score             REAL    DEFAULT 0.0,
    volume                REAL    DEFAULT 0.0,
    center_x              REAL    DEFAULT 0.0,
    center_y              REAL    DEFAULT 0.0,
    center_z              REAL    DEFAULT 0.0,
    radius_geom           REAL    DEFAULT 0.0,
    radius_clear          REAL    DEFAULT 0.0,
    merged_vertices       INTEGER DEFAULT 0,
    hydrophobic_ratio     REAL    DEFAULT 0.0,
    polar_atoms           INTEGER DEFAULT 0,
    druggable             INTEGER DEFAULT 0,
    druggability_class    TEXT    DEFAULT 'low',
    enclosure_score       REAL    DEFAULT 0.0,
    depth_score           REAL    DEFAULT 0.0,
    volume_score          REAL    DEFAULT 0.0,
    hydrophobicity_score  REAL    DEFAULT 0.0,
    profile_used          TEXT    DEFAULT 'Default',
    metadata_json         TEXT,
    created_at            TEXT    DEFAULT (datetime('now')),
    UNIQUE(pdb_id, pocket_id)
);

-- Docking results table
CREATE TABLE IF NOT EXISTS docking_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    pdb_id        TEXT    NOT NULL,
    pocket_id     INTEGER NOT NULL,
    ligand_name   TEXT,
    affinity      REAL    DEFAULT 0.0,
    affinity_class TEXT,
    rmsd_lb       REAL    DEFAULT 0.0,
    rmsd_ub       REAL    DEFAULT 0.0,
    n_hbonds      INTEGER DEFAULT 0,
    n_hydrophobic INTEGER DEFAULT 0,
    validated     INTEGER DEFAULT 0,
    metadata_json TEXT,
    created_at    TEXT    DEFAULT (datetime('now')),
    UNIQUE(pdb_id, pocket_id, ligand_name)
);

-- ============================================================
-- INDEXES (B-tree for fast queries)
-- ============================================================

-- Pocket queries
CREATE INDEX IF NOT EXISTS idx_pockets_pdb_id
    ON pockets(pdb_id);
CREATE INDEX IF NOT EXISTS idx_pockets_bio_score
    ON pockets(bio_score DESC);
CREATE INDEX IF NOT EXISTS idx_pockets_druggable
    ON pockets(druggable);
CREATE INDEX IF NOT EXISTS idx_pockets_druggability_class
    ON pockets(druggability_class);
CREATE INDEX IF NOT EXISTS idx_pockets_volume
    ON pockets(volume DESC);

-- Protein queries
CREATE INDEX IF NOT EXISTS idx_proteins_top_bio_score
    ON proteins(top_bio_score DESC);
CREATE INDEX IF NOT EXISTS idx_proteins_status
    ON proteins(status);

-- Docking queries
CREATE INDEX IF NOT EXISTS idx_docking_pdb_id
    ON docking_results(pdb_id);
CREATE INDEX IF NOT EXISTS idx_docking_affinity
    ON docking_results(affinity);
"""


# ============================================================================
# ATLAS DATABASE CLASS
# ============================================================================


class AtlasDB:
    """
    SQLite-based Cryptic Pocket Atlas database.

    Provides full CRUD operations, batch insert, advanced queries,
    statistics, and backup/restore for large-scale pocket discovery data.

    Args:
        db_path: Path to SQLite database file.
        batch_size: Default batch size for bulk inserts.

    Usage:
        db = AtlasDB('data/atlas.db')
        db.insert_discovery({'pdb_id': '1CBS', 'pocket_id': 1, ...})
        results = db.query_by_score(min_score=0.7)
        db.close()
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        batch_size: int = DEFAULT_BATCH_SIZE,
        check_same_thread: bool = True,
    ):
        self.db_path = Path(db_path)
        self.batch_size = batch_size
        self._check_same_thread = check_same_thread
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._connect()
        self._init_schema()

    # ----------------------------------------------------------------
    # CONNECTION MANAGEMENT
    # ----------------------------------------------------------------

    def _connect(self) -> None:
        """Open SQLite connection with optimized pragmas."""
        self._conn = sqlite3.connect(
            str(self.db_path),
            timeout=30,
            isolation_level=None,  # autocommit; we manage txns manually
            check_same_thread=self._check_same_thread,
        )
        self._conn.row_factory = sqlite3.Row
        # Performance pragmas
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA cache_size = -64000")  # 64 MB
        self._conn.execute("PRAGMA temp_store = MEMORY")
        self._conn.execute("PRAGMA mmap_size = 268435456")  # 256 MB

    def _init_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        assert self._conn is not None
        self._conn.executescript(_SCHEMA_SQL)
        # Set schema version
        self._conn.execute(
            "INSERT OR IGNORE INTO atlas_meta (key, value) VALUES (?, ?)",
            (SCHEMA_VERSION_KEY, str(DB_VERSION)),
        )
        self._conn.commit()

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """Context manager for atomic transactions."""
        assert self._conn is not None
        cursor = self._conn.cursor()
        cursor.execute("BEGIN")
        try:
            yield cursor
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    @property
    def conn(self) -> sqlite3.Connection:
        """Active connection (reconnects if needed)."""
        if self._conn is None:
            self._connect()
            self._init_schema()
        assert self._conn is not None
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "AtlasDB":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ================================================================
    # INSERT OPERATIONS
    # ================================================================

    def insert_protein(self, record: dict[str, Any]) -> None:
        """
        Insert or update a protein-level summary record.

        Args:
            record: Dict with keys matching proteins table columns.
                    Required: 'pdb_id'.
        """
        pdb_id = record["pdb_id"].upper().strip()
        metadata = record.get("metadata") or record.get("metadata_json")
        if isinstance(metadata, dict):
            metadata = json.dumps(metadata, default=str)

        self.conn.execute(
            """
            INSERT INTO proteins (
                pdb_id, resolution, method, total_cavities,
                druggable_cavities, high_score_count, medium_score_count,
                top_bio_score, analysis_runtime, n_frames,
                scoring_profile, status, error, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pdb_id) DO UPDATE SET
                resolution         = excluded.resolution,
                method             = excluded.method,
                total_cavities     = excluded.total_cavities,
                druggable_cavities = excluded.druggable_cavities,
                high_score_count   = excluded.high_score_count,
                medium_score_count = excluded.medium_score_count,
                top_bio_score      = excluded.top_bio_score,
                analysis_runtime   = excluded.analysis_runtime,
                n_frames           = excluded.n_frames,
                scoring_profile    = excluded.scoring_profile,
                status             = excluded.status,
                error              = excluded.error,
                metadata_json      = excluded.metadata_json,
                updated_at         = datetime('now')
            """,
            (
                pdb_id,
                record.get("resolution"),
                record.get("method"),
                record.get("total_cavities", 0),
                record.get("druggable_cavities", 0),
                record.get("high_score_count", 0),
                record.get("medium_score_count", 0),
                record.get("top_bio_score", 0.0),
                record.get("analysis_runtime", 0.0),
                record.get("n_frames", 0),
                record.get("scoring_profile", "default"),
                record.get("status", "success"),
                record.get("error"),
                metadata,
            ),
        )

    def insert_discovery(self, record: dict[str, Any]) -> int:
        """
        Insert a single pocket/cavity discovery.

        Args:
            record: Dict with pocket data. Required: 'pdb_id', 'pocket_id'.

        Returns:
            Row ID of the inserted record.
        """
        pdb_id = record["pdb_id"].upper().strip()
        pocket_id = record["pocket_id"]

        # Extract center coordinates (supports list/tuple/ndarray/string)
        center = record.get("center", [0.0, 0.0, 0.0])
        if isinstance(center, (list, tuple)) and len(center) >= 3:
            cx, cy, cz = center[0], center[1], center[2]
        elif isinstance(center, str):
            raw = center.strip().replace(",", " ")
            if raw.startswith("[") and raw.endswith("]"):
                raw = raw[1:-1]
            parts = [p for p in raw.split() if p]
            if len(parts) >= 3:
                cx, cy, cz = parts[0], parts[1], parts[2]
            else:
                cx = record.get("center_x", 0.0)
                cy = record.get("center_y", 0.0)
                cz = record.get("center_z", 0.0)
        elif hasattr(center, "__len__") and not isinstance(center, (bytes, bytearray)):
            try:
                if len(center) >= 3:
                    cx, cy, cz = center[0], center[1], center[2]
                else:
                    cx = record.get("center_x", 0.0)
                    cy = record.get("center_y", 0.0)
                    cz = record.get("center_z", 0.0)
            except Exception:
                cx = record.get("center_x", 0.0)
                cy = record.get("center_y", 0.0)
                cz = record.get("center_z", 0.0)
        else:
            cx = record.get("center_x", 0.0)
            cy = record.get("center_y", 0.0)
            cz = record.get("center_z", 0.0)

        try:
            cx = float(cx)
            cy = float(cy)
            cz = float(cz)
        except Exception:
            cx, cy, cz = 0.0, 0.0, 0.0

        # Extract score components
        sc = record.get("score_components", {})
        metadata_input = record.get("metadata") or record.get("metadata_json")
        metadata: str | None = None
        metadata_dict: dict[str, Any] | None = None

        if isinstance(metadata_input, dict):
            metadata_dict = dict(metadata_input)
        elif isinstance(metadata_input, str):
            metadata = metadata_input
            try:
                parsed = json.loads(metadata_input)
                if isinstance(parsed, dict):
                    metadata_dict = parsed
            except Exception:
                metadata_dict = None

        is_zero_center = abs(cx) < 1e-12 and abs(cy) < 1e-12 and abs(cz) < 1e-12
        if is_zero_center:
            if metadata_dict is None:
                metadata_dict = {}
                if metadata:
                    metadata_dict["legacy_metadata_raw"] = metadata
            metadata_dict["invalid_center"] = 1
            metadata_dict.setdefault("invalid_center_reason", "zero_center_on_write")
            metadata_dict.setdefault("center_guard_mode", "soft_warning")
            metadata = json.dumps(metadata_dict, default=str)
            LOGGER.warning(
                "Soft-guard: [0,0,0] center detected for %s pocket_id=%s. "
                "Marked metadata invalid_center=1.",
                pdb_id,
                pocket_id,
            )
        elif metadata_dict is not None:
            metadata = json.dumps(metadata_dict, default=str)

        cursor = self.conn.execute(
            """
            INSERT INTO pockets (
                pdb_id, pocket_id, rank, bio_score, volume,
                center_x, center_y, center_z,
                radius_geom, radius_clear, merged_vertices,
                hydrophobic_ratio, polar_atoms, druggable,
                druggability_class, enclosure_score, depth_score,
                volume_score, hydrophobicity_score, profile_used,
                metadata_json
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?
            )
            ON CONFLICT(pdb_id, pocket_id) DO UPDATE SET
                rank               = excluded.rank,
                bio_score          = excluded.bio_score,
                volume             = excluded.volume,
                center_x           = excluded.center_x,
                center_y           = excluded.center_y,
                center_z           = excluded.center_z,
                radius_geom        = excluded.radius_geom,
                radius_clear       = excluded.radius_clear,
                merged_vertices    = excluded.merged_vertices,
                hydrophobic_ratio  = excluded.hydrophobic_ratio,
                polar_atoms        = excluded.polar_atoms,
                druggable          = excluded.druggable,
                druggability_class = excluded.druggability_class,
                enclosure_score    = excluded.enclosure_score,
                depth_score        = excluded.depth_score,
                volume_score       = excluded.volume_score,
                hydrophobicity_score = excluded.hydrophobicity_score,
                profile_used       = excluded.profile_used,
                metadata_json      = excluded.metadata_json
            """,
            (
                pdb_id,
                pocket_id,
                record.get("rank", 0),
                record.get("bio_score", 0.0),
                record.get("volume", 0.0),
                cx,
                cy,
                cz,
                record.get("radius_geom", 0.0),
                record.get("radius_clear", 0.0),
                record.get("merged_vertices", 0),
                record.get("hydrophobic_ratio", 0.0),
                record.get("polar_atoms", 0),
                int(record.get("druggable", False)),
                record.get("druggability_class", "low"),
                sc.get("enclosure_score", record.get("enclosure_score", 0.0)),
                sc.get("depth_score", record.get("depth_score", 0.0)),
                sc.get("volume_score", record.get("volume_score", 0.0)),
                sc.get(
                    "hydrophobicity_score",
                    record.get("hydrophobicity_score", 0.0),
                ),
                record.get("profile_used", "Default"),
                metadata,
            ),
        )
        return cursor.lastrowid or 0

    def insert_docking(self, record: dict[str, Any]) -> int:
        """
        Insert a docking result for a pocket.

        Args:
            record: Dict with docking data. Required: 'pdb_id', 'pocket_id'.

        Returns:
            Row ID of the inserted record.
        """
        pdb_id = record["pdb_id"].upper().strip()
        metadata = record.get("metadata") or record.get("metadata_json")
        if isinstance(metadata, dict):
            metadata = json.dumps(metadata, default=str)

        cursor = self.conn.execute(
            """
            INSERT INTO docking_results (
                pdb_id, pocket_id, ligand_name, affinity,
                affinity_class, rmsd_lb, rmsd_ub,
                n_hbonds, n_hydrophobic, validated, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pdb_id, pocket_id, ligand_name) DO UPDATE SET
                affinity       = excluded.affinity,
                affinity_class = excluded.affinity_class,
                rmsd_lb        = excluded.rmsd_lb,
                rmsd_ub        = excluded.rmsd_ub,
                n_hbonds       = excluded.n_hbonds,
                n_hydrophobic  = excluded.n_hydrophobic,
                validated      = excluded.validated,
                metadata_json  = excluded.metadata_json
            """,
            (
                pdb_id,
                record["pocket_id"],
                record.get("ligand_name", ""),
                record.get("affinity", 0.0),
                record.get("affinity_class", ""),
                record.get("rmsd_lb", 0.0),
                record.get("rmsd_ub", 0.0),
                record.get("n_hbonds", 0),
                record.get("n_hydrophobic", 0),
                int(record.get("validated", False)),
                metadata,
            ),
        )
        return cursor.lastrowid or 0

    # ================================================================
    # BATCH INSERT
    # ================================================================

    def batch_insert_discoveries(
        self,
        records: Sequence[dict[str, Any]],
        batch_size: int | None = None,
    ) -> int:
        """
        Insert multiple pocket discoveries in batches for performance.

        Args:
            records: List of pocket record dicts.
            batch_size: Chunk size (default: self.batch_size).

        Returns:
            Number of records inserted.
        """
        bs = batch_size or self.batch_size
        total = 0
        for i in range(0, len(records), bs):
            chunk = records[i : i + bs]
            with self._transaction():
                for rec in chunk:
                    self.insert_discovery(rec)
                    total += 1
        return total

    def batch_insert_from_report(self, report: dict[str, Any]) -> int:
        """
        Insert all cavities from a pipeline report JSON.

        This is the primary integration point with the crawler output.
        Expects the same structure as 1cbs_report.json.

        Args:
            report: Full pipeline report dict (pdb_id, cavities list, etc.).

        Returns:
            Number of pockets inserted.
        """
        pdb_id = report["pdb_id"]

        # Insert protein-level summary
        self.insert_protein(
            {
                "pdb_id": pdb_id,
                "total_cavities": report.get("total_cavities", 0),
                "druggable_cavities": report.get("druggable_cavities", 0),
                "high_score_count": report.get("high_druggability", 0),
                "medium_score_count": report.get("medium_druggability", 0),
                "top_bio_score": report.get("cavities", [{}])[0].get(
                    "bio_score", 0.0
                )
                if report.get("cavities")
                else 0.0,
                "analysis_runtime": report.get("runtime_seconds", 0.0),
                "n_frames": report.get("n_frames", 0),
                "scoring_profile": report.get("scoring_profile", "default"),
                "status": "success",
            }
        )

        # Insert each cavity as a pocket
        cavities = report.get("cavities", [])
        count = 0
        with self._transaction():
            for cav in cavities:
                self.insert_discovery(
                    {
                        "pdb_id": pdb_id,
                        "pocket_id": cav.get("id", count),
                        "rank": cav.get("rank", 0),
                        "bio_score": cav.get("bio_score", 0.0),
                        "volume": cav.get("volume", 0.0),
                        "center": cav.get("center", [0.0, 0.0, 0.0]),
                        "radius_geom": cav.get("radius_geom", 0.0),
                        "radius_clear": cav.get("radius_clear", 0.0),
                        "merged_vertices": cav.get("merged_vertices", 0),
                        "hydrophobic_ratio": cav.get(
                            "hydrophobic_ratio", 0.0
                        ),
                        "polar_atoms": cav.get("polar_atoms", 0),
                        "druggable": cav.get("druggable", False),
                        "druggability_class": cav.get(
                            "druggability_class", "low"
                        ),
                        "score_components": cav.get("score_components", {}),
                        "profile_used": cav.get("profile_used", "Default"),
                    }
                )
                count += 1

        return count

    # ================================================================
    # QUERY OPERATIONS
    # ================================================================

    def get_protein(self, pdb_id: str) -> dict[str, Any] | None:
        """Get a protein record by PDB ID."""
        row = self.conn.execute(
            "SELECT * FROM proteins WHERE pdb_id = ?",
            (pdb_id.upper().strip(),),
        ).fetchone()
        return dict(row) if row else None

    def get_pocket(
        self, pdb_id: str, pocket_id: int
    ) -> dict[str, Any] | None:
        """Get a specific pocket by PDB ID and pocket ID."""
        row = self.conn.execute(
            "SELECT * FROM pockets WHERE pdb_id = ? AND pocket_id = ?",
            (pdb_id.upper().strip(), pocket_id),
        ).fetchone()
        return dict(row) if row else None

    def get_pockets_for_protein(
        self, pdb_id: str
    ) -> list[dict[str, Any]]:
        """Get all pockets for a given protein, ordered by rank."""
        rows = self.conn.execute(
            "SELECT * FROM pockets WHERE pdb_id = ? ORDER BY rank ASC",
            (pdb_id.upper().strip(),),
        ).fetchall()
        return [dict(r) for r in rows]

    def query_by_score(
        self,
        min_score: float = 0.0,
        max_score: float = 1.0,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Query pockets by bio_score range.

        Args:
            min_score: Minimum bio_score (inclusive).
            max_score: Maximum bio_score (inclusive).
            limit: Max results to return.
            offset: Pagination offset.

        Returns:
            List of pocket dicts, ordered by bio_score DESC.
        """
        rows = self.conn.execute(
            """
            SELECT * FROM pockets
            WHERE bio_score >= ? AND bio_score <= ?
            ORDER BY bio_score DESC
            LIMIT ? OFFSET ?
            """,
            (min_score, max_score, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def query_druggable(
        self,
        druggability_class: str | None = None,
        min_volume: float = 0.0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Query druggable pockets with optional filters.

        Args:
            druggability_class: 'high', 'medium', or None for all druggable.
            min_volume: Minimum pocket volume (Å³).
            limit: Max results.

        Returns:
            List of druggable pocket dicts.
        """
        if druggability_class:
            rows = self.conn.execute(
                """
                SELECT * FROM pockets
                WHERE druggable = 1
                  AND druggability_class = ?
                  AND volume >= ?
                ORDER BY bio_score DESC
                LIMIT ?
                """,
                (druggability_class, min_volume, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM pockets
                WHERE druggable = 1 AND volume >= ?
                ORDER BY bio_score DESC
                LIMIT ?
                """,
                (min_volume, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def query_elite_pockets(
        self,
        min_bio_score: float = 0.6,
        min_volume: float = 100.0,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """
        Find elite pockets: high bio_score + druggable + volume threshold.

        This is the primary discovery query for the Atlas.
        """
        rows = self.conn.execute(
            """
            SELECT * FROM pockets
            WHERE druggable = 1
              AND bio_score >= ?
              AND volume >= ?
            ORDER BY bio_score DESC
            LIMIT ?
            """,
            (min_bio_score, min_volume, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def search_pockets(
        self,
        pdb_id: str | None = None,
        min_score: float | None = None,
        max_score: float | None = None,
        druggable_only: bool = False,
        druggability_class: str | None = None,
        min_volume: float | None = None,
        max_volume: float | None = None,
        profile: str | None = None,
        order_by: str = "bio_score DESC",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Advanced pocket search with multiple filters.

        All filters are optional and combined with AND logic.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if pdb_id:
            conditions.append("pdb_id = ?")
            params.append(pdb_id.upper().strip())
        if min_score is not None:
            conditions.append("bio_score >= ?")
            params.append(min_score)
        if max_score is not None:
            conditions.append("bio_score <= ?")
            params.append(max_score)
        if druggable_only:
            conditions.append("druggable = 1")
        if druggability_class:
            conditions.append("druggability_class = ?")
            params.append(druggability_class)
        if min_volume is not None:
            conditions.append("volume >= ?")
            params.append(min_volume)
        if max_volume is not None:
            conditions.append("volume <= ?")
            params.append(max_volume)
        if profile:
            conditions.append("profile_used = ?")
            params.append(profile)

        where = " AND ".join(conditions) if conditions else "1=1"
        # Sanitize order_by to prevent SQL injection
        allowed_orders = {
            "bio_score DESC",
            "bio_score ASC",
            "volume DESC",
            "volume ASC",
            "rank ASC",
            "rank DESC",
            "created_at DESC",
            "created_at ASC",
        }
        if order_by not in allowed_orders:
            order_by = "bio_score DESC"

        sql = f"""
            SELECT * FROM pockets
            WHERE {where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ================================================================
    # DELETE OPERATIONS
    # ================================================================

    def delete_protein(self, pdb_id: str) -> int:
        """
        Delete a protein and all its pockets + docking results.

        Returns:
            Total number of rows deleted.
        """
        pid = pdb_id.upper().strip()
        deleted = 0
        with self._transaction() as cur:
            cur.execute(
                "DELETE FROM docking_results WHERE pdb_id = ?", (pid,)
            )
            deleted += cur.rowcount
            cur.execute("DELETE FROM pockets WHERE pdb_id = ?", (pid,))
            deleted += cur.rowcount
            cur.execute("DELETE FROM proteins WHERE pdb_id = ?", (pid,))
            deleted += cur.rowcount
        return deleted

    def delete_pocket(self, pdb_id: str, pocket_id: int) -> int:
        """Delete a specific pocket and its docking results."""
        pid = pdb_id.upper().strip()
        deleted = 0
        with self._transaction() as cur:
            cur.execute(
                "DELETE FROM docking_results WHERE pdb_id = ? AND pocket_id = ?",
                (pid, pocket_id),
            )
            deleted += cur.rowcount
            cur.execute(
                "DELETE FROM pockets WHERE pdb_id = ? AND pocket_id = ?",
                (pid, pocket_id),
            )
            deleted += cur.rowcount
        return deleted

    # ================================================================
    # STATISTICS & COUNTS
    # ================================================================

    def count_proteins(self) -> int:
        """Total number of proteins in the atlas."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM proteins"
        ).fetchone()
        return row["cnt"] if row else 0

    def count_pockets(self) -> int:
        """Total number of pockets in the atlas."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM pockets"
        ).fetchone()
        return row["cnt"] if row else 0

    def count_druggable(self) -> int:
        """Total number of druggable pockets."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM pockets WHERE druggable = 1"
        ).fetchone()
        return row["cnt"] if row else 0

    def count_elite(self, min_bio_score: float = 0.6) -> int:
        """Count elite pockets above score threshold."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM pockets "
            "WHERE druggable = 1 AND bio_score >= ?",
            (min_bio_score,),
        ).fetchone()
        return row["cnt"] if row else 0

    def get_statistics(self) -> dict[str, Any]:
        """
        Comprehensive atlas statistics.

        Returns:
            Dict with counts, averages, and distribution data.
        """
        stats: dict[str, Any] = {
            "total_proteins": self.count_proteins(),
            "total_pockets": self.count_pockets(),
            "druggable_pockets": self.count_druggable(),
            "elite_pockets": self.count_elite(),
        }

        # Score distribution
        row = self.conn.execute(
            """
            SELECT
                AVG(bio_score) AS avg_score,
                MIN(bio_score) AS min_score,
                MAX(bio_score) AS max_score,
                AVG(volume) AS avg_volume
            FROM pockets
            """
        ).fetchone()
        if row and row["avg_score"] is not None:
            stats.update(
                {
                    "avg_bio_score": round(row["avg_score"], 4),
                    "min_bio_score": round(row["min_score"], 4),
                    "max_bio_score": round(row["max_score"], 4),
                    "avg_volume": round(row["avg_volume"], 2),
                }
            )

        # Druggability class distribution
        rows = self.conn.execute(
            """
            SELECT druggability_class, COUNT(*) AS cnt
            FROM pockets
            GROUP BY druggability_class
            """
        ).fetchall()
        stats["class_distribution"] = {
            r["druggability_class"]: r["cnt"] for r in rows
        }

        return stats

    # ================================================================
    # BACKUP & RESTORE
    # ================================================================

    def backup(self, backup_path: str | None = None) -> str:
        """
        Create a gzip-compressed backup of the database.

        Args:
            backup_path: Target backup file path. Defaults to
                         {db_path}.bak.gz

        Returns:
            Path to the backup file.
        """
        if backup_path is None:
            backup_path = str(self.db_path) + BACKUP_EXTENSION

        # Ensure all changes are flushed
        self.conn.execute("PRAGMA wal_checkpoint(FULL)")

        with open(str(self.db_path), "rb") as f_in:
            with gzip.open(backup_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        return backup_path

    def restore(self, backup_path: str) -> None:
        """
        Restore database from a gzip-compressed backup.

        Args:
            backup_path: Path to the .bak.gz file.
        """
        self.close()

        with gzip.open(backup_path, "rb") as f_in:
            with open(str(self.db_path), "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        self._connect()
        self._init_schema()

    # ================================================================
    # DATA LAKE HELPERS
    # ================================================================

    def get_visual_archive_path(
        self, pdb_id: str, file_type: str = "render"
    ) -> Path:
        """
        Get the expected path for visual archive files.

        Args:
            pdb_id: PDB identifier.
            file_type: 'render' (.pml), 'view' (.html), or 'report' (.json).

        Returns:
            Path object for the archive file.
        """
        pid = pdb_id.lower().strip()
        ext_map = {
            "render": f"{pid}_render.pml",
            "view": f"{pid}_view.html",
            "report": f"{pid}_report.json",
        }
        filename = ext_map.get(file_type, f"{pid}_{file_type}")
        return Path("data/results") / filename

    def export_elite_csv(
        self,
        output_path: str = "data/results/elite_pockets.csv",
        min_bio_score: float = 0.6,
    ) -> int:
        """
        Export elite pockets to CSV for external analysis.

        Returns:
            Number of rows exported.
        """
        rows = self.query_elite_pockets(min_bio_score=min_bio_score, limit=999999)
        if not rows:
            return 0

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # CSV header
        columns = [
            "pdb_id",
            "pocket_id",
            "rank",
            "bio_score",
            "volume",
            "druggability_class",
            "hydrophobic_ratio",
            "enclosure_score",
            "depth_score",
        ]
        lines = [",".join(columns)]
        for r in rows:
            vals = [str(r.get(c, "")) for c in columns]
            lines.append(",".join(vals))

        Path(output_path).write_text("\n".join(lines), encoding="utf-8")
        return len(rows)

    # ================================================================
    # MIGRATION SUPPORT
    # ================================================================

    def get_schema_version(self) -> int:
        """Get current schema version."""
        try:
            row = self.conn.execute(
                "SELECT value FROM atlas_meta WHERE key = ?",
                (SCHEMA_VERSION_KEY,),
            ).fetchone()
            return int(row["value"]) if row else 0
        except sqlite3.OperationalError:
            return 0

    def migrate(self) -> None:
        """
        Run any pending migrations.

        Currently at v1 — future versions will add migration steps here.
        """
        current = self.get_schema_version()
        if current < DB_VERSION:
            # Re-apply schema (CREATE IF NOT EXISTS is idempotent)
            self._init_schema()
            self.conn.execute(
                "UPDATE atlas_meta SET value = ? WHERE key = ?",
                (str(DB_VERSION), SCHEMA_VERSION_KEY),
            )
            self.conn.commit()
