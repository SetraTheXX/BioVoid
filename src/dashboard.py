"""
DEPRECATED: Legacy Streamlit Dashboard
========================================

This dashboard has been replaced by the unified BioVoid portal.
Use the FastAPI portal instead:

    python scripts/run_phase6_api.py --host 127.0.0.1 --port 8000
    Open: http://127.0.0.1:8000/portal

The data helper functions below are preserved for backward compatibility
with existing tests.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.database import AtlasDB

APP_TITLE = "BioVoid — Discovery Dashboard (DEPRECATED)"
APP_ICON = "🧬"
PAGE_SIZE = 50
DEFAULT_DB = "data/atlas.db"

COLOR_DRUGGABLE = "#e74c3c"
COLOR_NON_DRUGGABLE = "#7f8c8d"
COLOR_ELITE = "#f39c12"
COLOR_HIGH = "#27ae60"
COLOR_MEDIUM = "#3498db"
COLOR_LOW = "#95a5a6"
COLOR_BACKBONE = "#bdc3c7"

CLASS_COLORS = {"high": COLOR_HIGH, "medium": COLOR_MEDIUM, "low": COLOR_LOW}
CLASS_LABELS = {"high": "High", "medium": "Medium", "low": "Low"}


def load_statistics(db: AtlasDB) -> dict[str, Any]:
    return db.get_statistics()


def load_pocket_dataframe(
    db: AtlasDB,
    pdb_id: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    druggable_only: bool = False,
    druggability_class: str | None = None,
    min_volume: float | None = None,
    max_volume: float | None = None,
    order_by: str = "bio_score DESC",
    limit: int = 1000,
    offset: int = 0,
) -> pd.DataFrame:
    rows = db.search_pockets(
        pdb_id=pdb_id,
        min_score=min_score,
        max_score=max_score,
        druggable_only=druggable_only,
        druggability_class=druggability_class,
        min_volume=min_volume,
        max_volume=max_volume,
        order_by=order_by,
        limit=limit,
        offset=offset,
    )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def load_protein_list(db: AtlasDB) -> list[str]:
    rows = db.conn.execute("SELECT pdb_id FROM proteins ORDER BY pdb_id").fetchall()
    return [r["pdb_id"] for r in rows]


def load_elite_dataframe(
    db: AtlasDB,
    min_bio_score: float = 0.6,
    min_volume: float = 100.0,
    limit: int = 500,
) -> pd.DataFrame:
    rows = db.query_elite_pockets(
        min_bio_score=min_bio_score,
        min_volume=min_volume,
        limit=limit,
    )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def build_kpi_cards(stats: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"label": "Total Proteins", "value": stats.get("total_proteins", 0), "delta": None},
        {"label": "Total Pockets", "value": stats.get("total_pockets", 0), "delta": None},
        {"label": "Druggable", "value": stats.get("druggable_pockets", 0), "delta": None},
        {"label": "Elite", "value": stats.get("elite_pockets", 0), "delta": None},
    ]


def build_score_histogram(*args, **kwargs):
    return None


def build_volume_scatter(*args, **kwargs):
    return None


def build_class_pie(*args, **kwargs):
    return None


def build_3d_pocket_view(*args, **kwargs):
    return None


def build_top_proteins_bar(*args, **kwargs):
    return None


def dataframe_to_csv(df: pd.DataFrame) -> str:
    return df.to_csv(index=False) if not df.empty else ""
