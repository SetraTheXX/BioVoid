"""Run-scoped, append-only Atlas v1 persistence for recovery results."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator

from .config import PATHS


ATLAS_SCHEMA_VERSION = "atlas-run-scoped-v1"
DEFAULT_ATLAS_V1_PATH = PATHS.atlas_db


class AtlasPersistenceError(RuntimeError):
    """Raised when a complete analysis run cannot be persisted atomically."""


@dataclass(frozen=True)
class AtlasPersistenceResult:
    run_id: str
    detected_total: int
    persisted_total: int
    observation_total: int
    status: str = "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "detected_total": self.detected_total,
            "persisted_total": self.persisted_total,
            "observation_total": self.observation_total,
            "schema_version": ATLAS_SCHEMA_VERSION,
        }


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS atlas_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS structures (
    structure_sha256 TEXT PRIMARY KEY,
    source_provider TEXT NOT NULL,
    source_identifier TEXT NOT NULL,
    representation TEXT NOT NULL,
    source_metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS prepared_structures (
    prepared_structure_id TEXT PRIMARY KEY,
    prepared_sha256 TEXT NOT NULL,
    structure_sha256 TEXT NOT NULL,
    preparation_config_sha256 TEXT NOT NULL,
    preparation_report_sha256 TEXT NOT NULL,
    preparation_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(
        structure_sha256,
        prepared_sha256,
        preparation_config_sha256,
        preparation_report_sha256
    ),
    FOREIGN KEY(structure_sha256) REFERENCES structures(structure_sha256)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id TEXT PRIMARY KEY,
    pdb_id TEXT NOT NULL,
    prepared_structure_id TEXT NOT NULL,
    prepared_sha256 TEXT NOT NULL,
    detector_version TEXT NOT NULL,
    detector_config_sha256 TEXT NOT NULL,
    scoring_contract_version TEXT NOT NULL,
    scoring_profile_sha256 TEXT NOT NULL,
    motion_config_sha256 TEXT,
    code_identity_sha256 TEXT NOT NULL,
    environment_identity_sha256 TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    canonical_eligible INTEGER NOT NULL,
    status TEXT NOT NULL,
    detected_total INTEGER NOT NULL,
    persisted_total INTEGER NOT NULL DEFAULT 0,
    runtime_seconds REAL NOT NULL DEFAULT 0.0,
    run_manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    FOREIGN KEY(prepared_structure_id)
        REFERENCES prepared_structures(prepared_structure_id)
);

CREATE TABLE IF NOT EXISTS pockets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    pdb_id TEXT NOT NULL,
    pocket_local_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    center_x REAL NOT NULL,
    center_y REAL NOT NULL,
    center_z REAL NOT NULL,
    volume REAL NOT NULL,
    radius_geom REAL NOT NULL DEFAULT 0.0,
    radius_clear REAL NOT NULL DEFAULT 0.0,
    merged_vertices INTEGER NOT NULL DEFAULT 0,
    hydrophobic_ratio REAL NOT NULL DEFAULT 0.0,
    polar_atoms INTEGER NOT NULL DEFAULT 0,
    bio_score REAL NOT NULL DEFAULT 0.0,
    heuristic_quality_tier TEXT NOT NULL,
    druggable INTEGER NOT NULL DEFAULT 0,
    profile_used TEXT NOT NULL,
    raw_measurements_json TEXT NOT NULL,
    score_components_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(run_id, pocket_local_id),
    FOREIGN KEY(run_id) REFERENCES analysis_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pocket_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    pocket_local_id TEXT,
    layer TEXT NOT NULL,
    sample_id TEXT,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(run_id, observation_id),
    FOREIGN KEY(run_id) REFERENCES analysis_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS models (
    model_sha256 TEXT PRIMARY KEY,
    model_type TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS benchmark_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    protocol_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(run_id) REFERENCES analysis_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_atlas_runs_pdb ON analysis_runs(pdb_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_atlas_pockets_run ON pockets(run_id, rank);
CREATE INDEX IF NOT EXISTS idx_atlas_pockets_score ON pockets(bio_score DESC);
CREATE INDEX IF NOT EXISTS idx_atlas_pockets_pdb ON pockets(pdb_id);
CREATE INDEX IF NOT EXISTS idx_atlas_observations_run ON pocket_observations(run_id, layer);
"""


def _json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _required_hash(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, ""))
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise AtlasPersistenceError(f"{key} must be a lowercase SHA-256 digest")
    return value


def _center(pocket: dict[str, Any]) -> tuple[float, float, float]:
    value = pocket.get("center")
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise AtlasPersistenceError("Pocket center must contain exactly three coordinates")
    center = (float(value[0]), float(value[1]), float(value[2]))
    if not all(math.isfinite(coordinate) for coordinate in center):
        raise AtlasPersistenceError("Pocket center coordinates must be finite")
    return center


class AtlasV1:
    """SQLite Atlas that never overwrites a completed analysis run."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_ATLAS_V1_PATH,
        *,
        check_same_thread: bool = True,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.db_path),
            timeout=30,
            isolation_level=None,
            check_same_thread=check_same_thread,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = FULL")
        self._conn.executescript(_SCHEMA_SQL)
        existing = self._conn.execute(
            "SELECT value FROM atlas_meta WHERE key = 'schema_version'"
        ).fetchone()
        if existing is not None and existing["value"] != ATLAS_SCHEMA_VERSION:
            self.close()
            raise AtlasPersistenceError(
                f"Atlas schema mismatch: expected {ATLAS_SCHEMA_VERSION}, found {existing['value']}"
            )
        self._conn.execute(
            "INSERT OR IGNORE INTO atlas_meta(key, value) VALUES('schema_version', ?)",
            (ATLAS_SCHEMA_VERSION,),
        )

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()

    def __enter__(self) -> "AtlasV1":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        cursor = self._conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            yield cursor
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def persist_report(self, report: dict[str, Any]) -> AtlasPersistenceResult:
        """Persist structure, preparation, run, pockets, and observations atomically."""
        try:
            return self._persist_report(report)
        except AtlasPersistenceError:
            raise
        except (KeyError, TypeError, ValueError, sqlite3.Error) as exc:
            raise AtlasPersistenceError(f"Atlas run persistence failed: {exc}") from exc

    def _persist_report(self, report: dict[str, Any]) -> AtlasPersistenceResult:
        run_id = str(report["run_id"]).strip()
        pdb_id = str(report["pdb_id"]).upper().strip()
        if not run_id or not pdb_id:
            raise AtlasPersistenceError("run_id and pdb_id are required")
        provenance = dict(report.get("provenance", {}))
        source = dict(report.get("structure_source", {}))
        static = dict(report.get("static_detector", {}))
        scoring = dict(report.get("scoring", {}))
        profile_manifest = dict(scoring.get("profile_manifest", {}))
        input_sha256 = _required_hash(provenance, "input_sha256")
        prepared_sha256 = _required_hash(provenance, "prepared_sha256")
        preparation_config_sha256 = _required_hash(provenance, "preparation_config_sha256")
        preparation_report_sha256 = _required_hash(provenance, "preparation_report_sha256")
        prepared_structure_id = hashlib.sha256(
            (
                f"{input_sha256}:{prepared_sha256}:"
                f"{preparation_config_sha256}:{preparation_report_sha256}"
            ).encode("ascii")
        ).hexdigest()
        detector_config_sha256 = _required_hash(static, "detector_config_sha256")
        scoring_profile_sha256 = _required_hash(profile_manifest, "config_sha256")
        code_identity_sha256 = _required_hash(provenance, "code_identity_sha256")
        environment_identity_sha256 = _required_hash(provenance, "environment_identity_sha256")
        cavities = list(report.get("cavities", ()))
        detected_total = int(report.get("total_cavities", len(cavities)))

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT OR IGNORE INTO structures(
                    structure_sha256, source_provider, source_identifier,
                    representation, source_metadata_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    input_sha256,
                    str(source.get("provider", "unknown")),
                    str(source.get("identifier", pdb_id)),
                    str(source.get("representation", "unknown")),
                    _json(source),
                ),
            )
            cursor.execute(
                """
                INSERT OR IGNORE INTO prepared_structures(
                    prepared_structure_id, prepared_sha256, structure_sha256,
                    preparation_config_sha256, preparation_report_sha256,
                    preparation_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    prepared_structure_id,
                    prepared_sha256,
                    input_sha256,
                    preparation_config_sha256,
                    preparation_report_sha256,
                    _json(report.get("preparation", {})),
                ),
            )
            cursor.execute(
                """
                INSERT INTO analysis_runs(
                    run_id, pdb_id, prepared_structure_id, prepared_sha256,
                    detector_version,
                    detector_config_sha256, scoring_contract_version,
                    scoring_profile_sha256, motion_config_sha256,
                    code_identity_sha256, environment_identity_sha256,
                    validation_status, canonical_eligible, status,
                    detected_total, persisted_total, runtime_seconds,
                    run_manifest_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    run_id,
                    pdb_id,
                    prepared_structure_id,
                    prepared_sha256,
                    str(static.get("detector_version", "unknown")),
                    detector_config_sha256,
                    str(scoring.get("contract_version", "unknown")),
                    scoring_profile_sha256,
                    provenance.get("motion_config_sha256"),
                    code_identity_sha256,
                    environment_identity_sha256,
                    str(report.get("validation_status", "unknown")),
                    int(bool(report.get("canonical_eligible", False))),
                    "writing",
                    detected_total,
                    float(report.get("runtime_seconds", 0.0)),
                    _json(report),
                ),
            )
            if detected_total != len(cavities):
                raise AtlasPersistenceError("detected_total does not match the report cavity count")

            persisted_total = 0
            observation_total = 0
            for index, pocket in enumerate(cavities):
                pocket_local_id = str(pocket.get("pocket_id", pocket.get("id", index)))
                center_x, center_y, center_z = _center(pocket)
                measurements = dict(pocket.get("scoring_measurements", {}))
                raw_measurements = measurements.get(
                    "raw_measurements",
                    {
                        "volume": pocket.get("volume", 0.0),
                        "hydrophobic_ratio": pocket.get("hydrophobic_ratio", 0.0),
                    },
                )
                score_components = dict(pocket.get("score_components", {}))
                metadata = {
                    key: value
                    for key, value in pocket.items()
                    if key
                    not in {
                        "vertices",
                        "scoring_measurements",
                        "score_components",
                    }
                }
                cursor.execute(
                    """
                    INSERT INTO pockets(
                        run_id, pdb_id, pocket_local_id, rank,
                        center_x, center_y, center_z, volume,
                        radius_geom, radius_clear, merged_vertices,
                        hydrophobic_ratio, polar_atoms, bio_score,
                        heuristic_quality_tier, druggable, profile_used,
                        raw_measurements_json, score_components_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        pdb_id,
                        pocket_local_id,
                        int(pocket.get("rank", index + 1)),
                        center_x,
                        center_y,
                        center_z,
                        float(pocket.get("volume", 0.0)),
                        float(pocket.get("radius_geom", 0.0)),
                        float(pocket.get("radius_clear", 0.0)),
                        int(pocket.get("merged_vertices", 0)),
                        float(pocket.get("hydrophobic_ratio", 0.0) or 0.0),
                        int(pocket.get("polar_atoms", 0)),
                        float(pocket.get("bio_score", 0.0)),
                        str(
                            pocket.get(
                                "heuristic_quality_tier",
                                pocket.get("druggability_class", "low"),
                            )
                        ),
                        int(
                            bool(
                                pocket.get(
                                    "heuristic_shortlist",
                                    pocket.get("heuristic_quality_tier") == "high",
                                )
                            )
                        ),
                        str(pocket.get("profile_used", "Default")),
                        _json(raw_measurements),
                        _json(score_components),
                        _json(metadata),
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO pocket_observations(
                        run_id, observation_id, pocket_local_id, layer,
                        sample_id, evidence_json
                    ) VALUES (?, ?, ?, 'static', NULL, ?)
                    """,
                    (
                        run_id,
                        f"static:{pocket_local_id}",
                        pocket_local_id,
                        _json(
                            {
                                "detector_version": static.get("detector_version"),
                                "measurements": raw_measurements,
                            }
                        ),
                    ),
                )
                persisted_total += 1
                observation_total += 1

            motion = report.get("motion_aware")
            if isinstance(motion, dict):
                for index, candidate in enumerate(motion.get("motion_pockets", ())):
                    observation_id = str(candidate.get("motion_pocket_id", f"motion:{index}"))
                    cursor.execute(
                        """
                        INSERT INTO pocket_observations(
                            run_id, observation_id, pocket_local_id,
                            layer, sample_id, evidence_json
                        ) VALUES (?, ?, ?, 'motion_experimental', NULL, ?)
                        """,
                        (
                            run_id,
                            observation_id,
                            candidate.get("static_pocket_id"),
                            _json(candidate),
                        ),
                    )
                    observation_total += 1

            cursor.execute(
                """
                UPDATE analysis_runs
                SET persisted_total = ?, status = 'completed',
                    completed_at = datetime('now')
                WHERE run_id = ?
                """,
                (persisted_total, run_id),
            )
            if persisted_total != detected_total:
                raise AtlasPersistenceError("persisted_total does not match detected_total")

        return AtlasPersistenceResult(
            run_id=run_id,
            detected_total=detected_total,
            persisted_total=persisted_total,
            observation_total=observation_total,
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM analysis_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_runs(self, pdb_id: str | None = None) -> list[dict[str, Any]]:
        if pdb_id is None:
            rows = self._conn.execute(
                "SELECT * FROM analysis_runs ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM analysis_runs
                WHERE pdb_id = ?
                ORDER BY created_at DESC, rowid DESC
                """,
                (pdb_id.upper().strip(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_run_pockets(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT *, pocket_local_id AS pocket_id
            FROM pockets WHERE run_id = ? ORDER BY rank, pocket_local_id
            """,
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def search_pockets(
        self,
        *,
        run_id: str | None = None,
        pdb_id: str | None = None,
        min_score: float = 0.0,
        max_score: float = 1.0,
        min_volume: float | None = None,
        max_volume: float | None = None,
        druggable_only: bool = False,
        druggability_class: str | None = None,
        order_by: str = "bio_score DESC",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        allowed_order = {
            "bio_score DESC": "bio_score DESC",
            "bio_score ASC": "bio_score ASC",
            "volume DESC": "volume DESC",
            "volume ASC": "volume ASC",
            "rank ASC": "rank ASC",
        }
        order_sql = allowed_order.get(order_by, "bio_score DESC")
        clauses = ["bio_score BETWEEN ? AND ?"]
        parameters: list[Any] = [min_score, max_score]
        if run_id:
            clauses.append("p.run_id = ?")
            parameters.append(run_id.strip())
        if pdb_id:
            clauses.append("p.pdb_id = ?")
            parameters.append(pdb_id.upper().strip())
        if min_volume is not None:
            clauses.append("p.volume >= ?")
            parameters.append(min_volume)
        if max_volume is not None:
            clauses.append("p.volume <= ?")
            parameters.append(max_volume)
        if druggable_only:
            clauses.append("p.druggable = 1")
        if druggability_class:
            clauses.append("p.heuristic_quality_tier = ?")
            parameters.append(druggability_class)
        parameters.extend([max(1, limit), max(0, offset)])
        rows = self._conn.execute(
            f"""
            SELECT
                p.*, p.pocket_local_id AS pocket_id,
                p.heuristic_quality_tier AS druggability_class,
                p.druggable AS heuristic_shortlist,
                r.prepared_sha256,
                r.validation_status,
                r.canonical_eligible,
                r.detector_version,
                r.scoring_contract_version
            FROM pockets p
            JOIN analysis_runs r ON r.run_id = p.run_id
            WHERE {" AND ".join(clauses)}
            ORDER BY p.{order_sql}, p.id ASC
            LIMIT ? OFFSET ?
            """,
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def count_pockets(
        self,
        *,
        run_id: str | None = None,
        pdb_id: str | None = None,
        min_score: float = 0.0,
        max_score: float = 1.0,
        min_volume: float | None = None,
        max_volume: float | None = None,
        druggable_only: bool = False,
        druggability_class: str | None = None,
    ) -> int:
        clauses = ["p.bio_score BETWEEN ? AND ?"]
        parameters: list[Any] = [min_score, max_score]
        if run_id:
            clauses.append("p.run_id = ?")
            parameters.append(run_id.strip())
        if pdb_id:
            clauses.append("p.pdb_id = ?")
            parameters.append(pdb_id.upper().strip())
        if min_volume is not None:
            clauses.append("p.volume >= ?")
            parameters.append(min_volume)
        if max_volume is not None:
            clauses.append("p.volume <= ?")
            parameters.append(max_volume)
        if druggable_only:
            clauses.append("p.druggable = 1")
        if druggability_class:
            clauses.append("p.heuristic_quality_tier = ?")
            parameters.append(druggability_class)
        row = self._conn.execute(
            f"SELECT COUNT(*) AS count FROM pockets p WHERE {' AND '.join(clauses)}",
            parameters,
        ).fetchone()
        return int(row["count"] or 0)

    def get_statistics(self) -> dict[str, Any]:
        summary = self._conn.execute(
            """
            SELECT
                COUNT(DISTINCT pdb_id) AS total_proteins,
                COUNT(*) AS total_pockets,
                SUM(CASE WHEN heuristic_quality_tier = 'high' THEN 1 ELSE 0 END)
                    AS heuristic_shortlist_pockets,
                AVG(bio_score) AS avg_bio_score,
                AVG(volume) AS avg_volume
            FROM pockets
            """
        ).fetchone()
        class_rows = self._conn.execute(
            """
            SELECT heuristic_quality_tier, COUNT(*) AS count
            FROM pockets GROUP BY heuristic_quality_tier
            """
        ).fetchall()
        elite = self._conn.execute(
            """
            SELECT COUNT(*) AS count FROM pockets
            WHERE heuristic_quality_tier = 'high' AND bio_score >= 0.6
            """
        ).fetchone()
        shortlist_count = int(summary["heuristic_shortlist_pockets"] or 0)
        return {
            "total_proteins": int(summary["total_proteins"] or 0),
            "total_pockets": int(summary["total_pockets"] or 0),
            "heuristic_shortlist_pockets": shortlist_count,
            "druggable_pockets": shortlist_count,
            "elite_pockets": int(elite["count"] or 0),
            "avg_bio_score": float(summary["avg_bio_score"] or 0.0),
            "avg_volume": float(summary["avg_volume"] or 0.0),
            "class_distribution": {
                row["heuristic_quality_tier"]: int(row["count"]) for row in class_rows
            },
        }
