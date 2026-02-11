"""
Bio-Void Hunter: Discovery Dashboard (Phase 5.3)
==================================================

Streamlit-based interactive dashboard for exploring the Cryptic Pocket
Atlas database. Provides search, filtering, 3D visualization, and
statistics at a glance.

Key Features:
- Overview page with KPI cards and distribution charts
- Advanced pocket search with multi-filter sidebar
- Interactive 3D Plotly visualization of pocket locations
- Protein detail view with all pockets
- Elite discoveries leaderboard
- CSV export of filtered results
- Performance: <2s initial load, <1s filtering

Usage:
    streamlit run src/dashboard.py -- --db data/atlas.db

Author: Bio-Void Hunter Team
Version: 0.9.0 (Phase 5.3)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so we can import database
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.database import AtlasDB  # noqa: E402


# ============================================================================
# CONSTANTS
# ============================================================================

APP_TITLE = "🔬 Bio-Void Hunter — Discovery Dashboard"
APP_ICON = "🧬"
PAGE_SIZE = 50
DEFAULT_DB = "data/atlas.db"

# Color palette
COLOR_DRUGGABLE = "#e74c3c"       # Warm red
COLOR_NON_DRUGGABLE = "#7f8c8d"   # Grey
COLOR_ELITE = "#f39c12"           # Gold
COLOR_HIGH = "#27ae60"            # Green
COLOR_MEDIUM = "#3498db"          # Blue
COLOR_LOW = "#95a5a6"             # Light grey
COLOR_BACKBONE = "#bdc3c7"        # Silver

CLASS_COLORS = {
    "high": COLOR_HIGH,
    "medium": COLOR_MEDIUM,
    "low": COLOR_LOW,
}

# Druggability class display labels
CLASS_LABELS = {
    "high": "🟢 High",
    "medium": "🔵 Medium",
    "low": "⚪ Low",
}


# ============================================================================
# DATA HELPERS (testable without Streamlit)
# ============================================================================


def load_statistics(db: AtlasDB) -> dict[str, Any]:
    """Load atlas statistics from database. Returns dict with counts + averages."""
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
    """
    Query pockets from database and return as a DataFrame.

    This is the primary data loading function for the dashboard.
    It wraps AtlasDB.search_pockets() and converts results to pandas.
    """
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
    """Get list of all protein PDB IDs in the atlas."""
    rows = db.conn.execute(
        "SELECT pdb_id FROM proteins ORDER BY pdb_id"
    ).fetchall()
    return [r["pdb_id"] for r in rows]


def load_elite_dataframe(
    db: AtlasDB,
    min_bio_score: float = 0.6,
    min_volume: float = 100.0,
    limit: int = 500,
) -> pd.DataFrame:
    """Load elite pockets as DataFrame."""
    rows = db.query_elite_pockets(
        min_bio_score=min_bio_score,
        min_volume=min_volume,
        limit=limit,
    )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def build_kpi_cards(stats: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Transform raw statistics into KPI card data for display.

    Returns list of dicts with 'label', 'value', 'delta' keys.
    """
    cards = [
        {
            "label": "Toplam Protein",
            "value": stats.get("total_proteins", 0),
            "delta": None,
        },
        {
            "label": "Toplam Cep (Pocket)",
            "value": stats.get("total_pockets", 0),
            "delta": None,
        },
        {
            "label": "İlaçlanabilir Cep",
            "value": stats.get("druggable_pockets", 0),
            "delta": f"{stats.get('druggable_pockets', 0) / max(stats.get('total_pockets', 1), 1) * 100:.1f}%",
        },
        {
            "label": "Elit Keşif",
            "value": stats.get("elite_pockets", 0),
            "delta": f"Bio-Score ≥ 0.6",
        },
    ]
    return cards


def build_score_histogram(df: pd.DataFrame) -> go.Figure | None:
    """Create bio_score distribution histogram from pocket DataFrame."""
    if df.empty or "bio_score" not in df.columns:
        return None

    fig = px.histogram(
        df,
        x="bio_score",
        nbins=30,
        color_discrete_sequence=["#3498db"],
        labels={"bio_score": "Bio-Score"},
        title="Bio-Score Dağılımı",
    )
    fig.update_layout(
        margin=dict(l=20, r=20, t=40, b=20),
        height=300,
        xaxis_title="Bio-Score",
        yaxis_title="Cep Sayısı",
        showlegend=False,
    )
    return fig


def build_volume_scatter(df: pd.DataFrame) -> go.Figure | None:
    """Create volume vs bio_score scatter plot colored by druggability."""
    if df.empty or "bio_score" not in df.columns:
        return None

    color_map = {"high": COLOR_HIGH, "medium": COLOR_MEDIUM, "low": COLOR_LOW}

    fig = px.scatter(
        df,
        x="volume",
        y="bio_score",
        color="druggability_class",
        color_discrete_map=color_map,
        hover_data=["pdb_id", "pocket_id", "rank"],
        labels={
            "volume": "Hacim (ų)",
            "bio_score": "Bio-Score",
            "druggability_class": "Sınıf",
        },
        title="Hacim vs Bio-Score",
    )
    fig.update_layout(
        margin=dict(l=20, r=20, t=40, b=20),
        height=350,
    )
    return fig


def build_class_pie(stats: dict[str, Any]) -> go.Figure | None:
    """Create druggability class pie chart."""
    dist = stats.get("class_distribution", {})
    if not dist:
        return None

    labels = list(dist.keys())
    values = list(dist.values())
    colors = [CLASS_COLORS.get(l, COLOR_LOW) for l in labels]

    fig = go.Figure(
        data=[
            go.Pie(
                labels=[CLASS_LABELS.get(l, l) for l in labels],
                values=values,
                marker=dict(colors=colors),
                hole=0.4,
                textinfo="percent+value",
            )
        ]
    )
    fig.update_layout(
        title="İlaçlanabilirlik Sınıf Dağılımı",
        margin=dict(l=20, r=20, t=40, b=20),
        height=300,
        showlegend=True,
    )
    return fig


def build_3d_pocket_view(df: pd.DataFrame, title: str = "") -> go.Figure | None:
    """
    Build 3D scatter plot of pocket centers from DataFrame.

    Pocket centers are displayed as spheres colored by druggability,
    sized by volume. Similar to BioVoidVisualizer but from DB data.
    """
    if df.empty:
        return None

    required = {"center_x", "center_y", "center_z", "bio_score"}
    if not required.issubset(df.columns):
        return None

    fig = go.Figure()

    # Split by druggability
    for druggable_val, label, color, opacity in [
        (1, "İlaçlanabilir", COLOR_DRUGGABLE, 0.85),
        (0, "İlaçlanamaz", COLOR_NON_DRUGGABLE, 0.4),
    ]:
        mask = df["druggable"] == druggable_val
        subset = df[mask]
        if subset.empty:
            continue

        # Size: scale volume to marker size (min 3, max 15)
        sizes = subset["volume"].values if "volume" in subset.columns else np.full(len(subset), 5)
        size_norm = np.clip(sizes / max(sizes.max(), 1) * 12 + 3, 3, 15)

        hover_text = [
            f"<b>{row.get('pdb_id', '?')} #{row.get('pocket_id', '?')}</b><br>"
            f"Score: {row.get('bio_score', 0):.3f}<br>"
            f"Hacim: {row.get('volume', 0):.1f} ų<br>"
            f"Sınıf: {row.get('druggability_class', 'N/A')}"
            for _, row in subset.iterrows()
        ]

        fig.add_trace(
            go.Scatter3d(
                x=subset["center_x"],
                y=subset["center_y"],
                z=subset["center_z"],
                mode="markers",
                marker=dict(
                    size=size_norm,
                    color=color,
                    opacity=opacity,
                    line=dict(width=0.5, color="white"),
                ),
                name=label,
                hovertext=hover_text,
                hoverinfo="text",
            )
        )

    fig.update_layout(
        title=title or "3D Cep Konumları",
        scene=dict(
            xaxis_title="X (Å)",
            yaxis_title="Y (Å)",
            zaxis_title="Z (Å)",
            aspectmode="data",
            camera=dict(eye=dict(x=1.5, y=1.5, z=1.2)),
        ),
        margin=dict(l=0, r=0, b=0, t=40),
        height=500,
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
    )
    return fig


def build_top_proteins_bar(db: AtlasDB, limit: int = 15) -> go.Figure | None:
    """Bar chart of proteins sorted by druggable pocket count."""
    rows = db.conn.execute(
        """
        SELECT pdb_id, druggable_cavities, top_bio_score
        FROM proteins
        WHERE druggable_cavities > 0
        ORDER BY druggable_cavities DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    if not rows:
        return None

    df = pd.DataFrame([dict(r) for r in rows])
    fig = px.bar(
        df,
        x="pdb_id",
        y="druggable_cavities",
        color="top_bio_score",
        color_continuous_scale="YlOrRd",
        labels={
            "pdb_id": "Protein (PDB ID)",
            "druggable_cavities": "İlaçlanabilir Cep",
            "top_bio_score": "En Yüksek Score",
        },
        title=f"En Zengin {limit} Protein",
    )
    fig.update_layout(
        margin=dict(l=20, r=20, t=40, b=20),
        height=350,
    )
    return fig


def dataframe_to_csv(df: pd.DataFrame) -> str:
    """Convert DataFrame to CSV string for download."""
    return df.to_csv(index=False)


# ============================================================================
# STREAMLIT APP (UI Layer)
# ============================================================================


def get_db_path() -> str:
    """Parse --db argument from CLI or use default."""
    parser = argparse.ArgumentParser(description="Bio-Void Dashboard")
    parser.add_argument("--db", type=str, default=DEFAULT_DB, help="Atlas DB path")
    # Only parse known args to avoid Streamlit arg conflicts
    args, _ = parser.parse_known_args()
    return args.db


@st.cache_resource
def get_database(db_path: str) -> AtlasDB:
    """Cached database connection (singleton per session)."""
    return AtlasDB(db_path, check_same_thread=False)


def render_sidebar(db: AtlasDB) -> dict[str, Any]:
    """Render sidebar filters and return filter state dict."""
    st.sidebar.title("🔍 Arama Filtreleri")

    # Navigation
    page = st.sidebar.radio(
        "Sayfa",
        ["📊 Genel Bakış", "🔎 Cep Arama", "🏆 Elit Keşifler", "🧬 Protein Detay"],
        index=0,
    )

    filters: dict[str, Any] = {"page": page}

    if page == "🔎 Cep Arama":
        st.sidebar.markdown("---")

        # PDB ID filter
        proteins = load_protein_list(db)
        pdb_options = ["Tümü"] + proteins
        selected_pdb = st.sidebar.selectbox("Protein (PDB ID)", pdb_options)
        filters["pdb_id"] = None if selected_pdb == "Tümü" else selected_pdb

        # Score range
        st.sidebar.markdown("**Bio-Score Aralığı**")
        score_range = st.sidebar.slider(
            "Score", 0.0, 1.0, (0.0, 1.0), step=0.05, key="score_slider"
        )
        filters["min_score"] = score_range[0] if score_range[0] > 0 else None
        filters["max_score"] = score_range[1] if score_range[1] < 1.0 else None

        # Volume range
        st.sidebar.markdown("**Hacim Aralığı (ų)**")
        vol_range = st.sidebar.slider(
            "Hacim", 0, 5000, (0, 5000), step=50, key="vol_slider"
        )
        filters["min_volume"] = vol_range[0] if vol_range[0] > 0 else None
        filters["max_volume"] = vol_range[1] if vol_range[1] < 5000 else None

        # Druggable only
        filters["druggable_only"] = st.sidebar.checkbox(
            "Sadece İlaçlanabilir", value=False
        )

        # Druggability class
        class_opt = st.sidebar.selectbox(
            "İlaçlanabilirlik Sınıfı",
            ["Tümü", "high", "medium", "low"],
        )
        filters["druggability_class"] = None if class_opt == "Tümü" else class_opt

        # Sort
        sort_opt = st.sidebar.selectbox(
            "Sıralama",
            [
                "bio_score DESC",
                "bio_score ASC",
                "volume DESC",
                "volume ASC",
                "rank ASC",
            ],
        )
        filters["order_by"] = sort_opt

        # Limit
        filters["limit"] = st.sidebar.number_input(
            "Maks. Sonuç", min_value=10, max_value=5000, value=200, step=50
        )

    elif page == "🏆 Elit Keşifler":
        st.sidebar.markdown("---")
        filters["elite_min_score"] = st.sidebar.slider(
            "Min Bio-Score", 0.0, 1.0, 0.6, step=0.05
        )
        filters["elite_min_volume"] = st.sidebar.number_input(
            "Min Hacim (ų)", min_value=0, max_value=2000, value=100, step=50
        )

    elif page == "🧬 Protein Detay":
        st.sidebar.markdown("---")
        proteins = load_protein_list(db)
        if proteins:
            filters["detail_pdb"] = st.sidebar.selectbox(
                "Protein Seç", proteins
            )
        else:
            filters["detail_pdb"] = None

    return filters


def render_overview(db: AtlasDB) -> None:
    """Render overview page with KPIs and charts."""
    st.header("📊 Atlas Genel Bakış")

    stats = load_statistics(db)
    cards = build_kpi_cards(stats)

    # KPI row
    cols = st.columns(len(cards))
    for col, card in zip(cols, cards):
        col.metric(
            label=card["label"],
            value=f"{card['value']:,}",
            delta=card["delta"],
        )

    st.markdown("---")

    # Charts row
    col1, col2 = st.columns(2)

    # All pockets for histogram
    all_pockets = load_pocket_dataframe(db, limit=5000)

    with col1:
        hist_fig = build_score_histogram(all_pockets)
        if hist_fig:
            st.plotly_chart(hist_fig, use_container_width=True)
        else:
            st.info("Henüz veri yok.")

    with col2:
        pie_fig = build_class_pie(stats)
        if pie_fig:
            st.plotly_chart(pie_fig, use_container_width=True)
        else:
            st.info("Sınıf dağılımı yok.")

    # Scatter + Bar row
    col3, col4 = st.columns(2)

    with col3:
        scatter_fig = build_volume_scatter(all_pockets)
        if scatter_fig:
            st.plotly_chart(scatter_fig, use_container_width=True)

    with col4:
        bar_fig = build_top_proteins_bar(db)
        if bar_fig:
            st.plotly_chart(bar_fig, use_container_width=True)

    # Summary stats
    if stats.get("avg_bio_score") is not None:
        st.markdown("---")
        st.markdown("### 📈 İstatistik Özeti")
        c1, c2, c3 = st.columns(3)
        c1.metric("Ortalama Bio-Score", f"{stats['avg_bio_score']:.4f}")
        c2.metric("Ortalama Hacim", f"{stats['avg_volume']:.1f} ų")
        c3.metric(
            "Score Aralığı",
            f"{stats['min_bio_score']:.4f} – {stats['max_bio_score']:.4f}",
        )


def render_search(db: AtlasDB, filters: dict[str, Any]) -> None:
    """Render pocket search page with filters."""
    st.header("🔎 Cep Arama")

    t0 = time.perf_counter()
    df = load_pocket_dataframe(
        db,
        pdb_id=filters.get("pdb_id"),
        min_score=filters.get("min_score"),
        max_score=filters.get("max_score"),
        druggable_only=filters.get("druggable_only", False),
        druggability_class=filters.get("druggability_class"),
        min_volume=filters.get("min_volume"),
        max_volume=filters.get("max_volume"),
        order_by=filters.get("order_by", "bio_score DESC"),
        limit=filters.get("limit", 200),
    )
    elapsed = time.perf_counter() - t0

    st.caption(f"🕐 Sorgu: {elapsed:.3f}s — {len(df)} sonuç bulundu")

    if df.empty:
        st.warning("Filtrelere uyan cep bulunamadı.")
        return

    # 3D View
    fig_3d = build_3d_pocket_view(df, title="Filtrelenmiş Cepler — 3D Görünüm")
    if fig_3d:
        st.plotly_chart(fig_3d, use_container_width=True)

    # Data table
    display_cols = [
        "pdb_id", "pocket_id", "rank", "bio_score", "volume",
        "druggable", "druggability_class", "hydrophobic_ratio",
        "enclosure_score", "depth_score",
    ]
    available_cols = [c for c in display_cols if c in df.columns]

    st.dataframe(
        df[available_cols].head(PAGE_SIZE),
        use_container_width=True,
        hide_index=True,
    )

    if len(df) > PAGE_SIZE:
        st.caption(f"İlk {PAGE_SIZE} sonuç gösteriliyor ({len(df)} toplam)")

    # CSV download
    csv = dataframe_to_csv(df[available_cols])
    st.download_button(
        "📥 CSV İndir",
        data=csv,
        file_name="biovoid_search_results.csv",
        mime="text/csv",
    )


def render_elite(db: AtlasDB, filters: dict[str, Any]) -> None:
    """Render elite discoveries page."""
    st.header("🏆 Elit Keşifler")
    st.markdown(
        "Yüksek Bio-Score, ilaçlanabilir ve yeterli hacme sahip en önemli cep keşifleri."
    )

    min_score = filters.get("elite_min_score", 0.6)
    min_volume = filters.get("elite_min_volume", 100)

    t0 = time.perf_counter()
    df = load_elite_dataframe(db, min_bio_score=min_score, min_volume=min_volume)
    elapsed = time.perf_counter() - t0

    st.caption(f"🕐 Sorgu: {elapsed:.3f}s — {len(df)} elit cep bulundu")

    if df.empty:
        st.info("Kriterlere uyan elit cep yok.")
        return

    # Top 3 highlight
    st.subheader("🥇 En İyi 3 Keşif")
    top3 = df.head(3)
    medals = ["🥇", "🥈", "🥉"]
    cols = st.columns(min(3, len(top3)))
    for i, (_, row) in enumerate(top3.iterrows()):
        with cols[i]:
            st.markdown(
                f"### {medals[i]} {row.get('pdb_id', '?')} #{row.get('pocket_id', '?')}"
            )
            st.metric("Bio-Score", f"{row.get('bio_score', 0):.4f}")
            st.metric("Hacim", f"{row.get('volume', 0):.1f} ų")
            st.caption(f"Sınıf: {row.get('druggability_class', 'N/A')}")

    st.markdown("---")

    # 3D view of elite pockets
    fig_3d = build_3d_pocket_view(df, title="Elit Cepler — 3D Konumlar")
    if fig_3d:
        st.plotly_chart(fig_3d, use_container_width=True)

    # Full table
    display_cols = [
        "pdb_id", "pocket_id", "rank", "bio_score", "volume",
        "druggability_class", "hydrophobic_ratio",
        "enclosure_score", "depth_score", "volume_score",
    ]
    available_cols = [c for c in display_cols if c in df.columns]

    st.dataframe(df[available_cols], use_container_width=True, hide_index=True)

    # Export
    csv = dataframe_to_csv(df[available_cols])
    st.download_button(
        "📥 Elit Cepleri CSV İndir",
        data=csv,
        file_name="biovoid_elite_pockets.csv",
        mime="text/csv",
    )


def render_protein_detail(db: AtlasDB, filters: dict[str, Any]) -> None:
    """Render single protein detail page."""
    st.header("🧬 Protein Detay")

    pdb_id = filters.get("detail_pdb")
    if not pdb_id:
        st.warning("Veritabanında protein bulunamadı.")
        return

    # Protein info
    row = db.conn.execute(
        "SELECT * FROM proteins WHERE pdb_id = ?", (pdb_id,)
    ).fetchone()

    if not row:
        st.error(f"Protein {pdb_id} bulunamadı.")
        return

    protein = dict(row)

    st.subheader(f"Protein: {pdb_id}")

    # Info cards
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Cep", protein.get("total_cavities", 0))
    c2.metric("İlaçlanabilir", protein.get("druggable_cavities", 0))
    c3.metric("En Yüksek Score", f"{protein.get('top_bio_score', 0):.4f}")
    c4.metric("Analiz Süresi", f"{protein.get('analysis_runtime', 0):.1f}s")

    st.markdown("---")

    # All pockets for this protein
    pockets_df = load_pocket_dataframe(db, pdb_id=pdb_id, limit=500)

    if pockets_df.empty:
        st.info("Bu protein için cep verisi yok.")
        return

    # 3D scatter
    fig_3d = build_3d_pocket_view(
        pockets_df, title=f"{pdb_id} — Cep Haritası"
    )
    if fig_3d:
        st.plotly_chart(fig_3d, use_container_width=True)

    # Score distribution for this protein
    col1, col2 = st.columns(2)
    with col1:
        hist_fig = build_score_histogram(pockets_df)
        if hist_fig:
            hist_fig.update_layout(title=f"{pdb_id} Bio-Score Dağılımı")
            st.plotly_chart(hist_fig, use_container_width=True)

    with col2:
        scatter_fig = build_volume_scatter(pockets_df)
        if scatter_fig:
            scatter_fig.update_layout(title=f"{pdb_id} Hacim vs Score")
            st.plotly_chart(scatter_fig, use_container_width=True)

    # Pocket table
    st.subheader("📋 Cep Tablosu")
    display_cols = [
        "pocket_id", "rank", "bio_score", "volume",
        "druggable", "druggability_class", "hydrophobic_ratio",
        "enclosure_score", "depth_score",
    ]
    available_cols = [c for c in display_cols if c in pockets_df.columns]
    st.dataframe(pockets_df[available_cols], use_container_width=True, hide_index=True)


def main() -> None:
    """Main Streamlit application entry point."""
    st.set_page_config(
        page_title="Bio-Void Discovery Dashboard",
        page_icon=APP_ICON,
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title(APP_TITLE)

    # Database connection
    db_path = get_db_path()
    db = get_database(db_path)

    # Sidebar filters
    filters = render_sidebar(db)
    page = filters["page"]

    # Page routing
    if page == "📊 Genel Bakış":
        render_overview(db)
    elif page == "🔎 Cep Arama":
        render_search(db, filters)
    elif page == "🏆 Elit Keşifler":
        render_elite(db, filters)
    elif page == "🧬 Protein Detay":
        render_protein_detail(db, filters)

    # Footer
    st.sidebar.markdown("---")
    st.sidebar.caption("Bio-Void Hunter v0.9.0 • Phase 5.3")


if __name__ == "__main__":
    main()
