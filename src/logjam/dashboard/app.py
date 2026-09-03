"""Minimal Streamlit view over the signal tables.

Run: ``uv run streamlit run src/logjam/dashboard/app.py``

This is intentionally thin - it reads the same DuckDB tables the CLI does. The
real analytical work lives in ``logjam.analytics``; keep it that
way so a future FastAPI layer can reuse it without touching this file.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from logjam.config import settings
from logjam.store.db import connect

st.set_page_config(page_title="Logistics Bottlenecks", layout="wide")
st.title("Logistics bottleneck & opportunity monitor")
st.caption("Source: IMF PortWatch. Throughput/transit signal — not queue length (yet).")

days = st.sidebar.slider("Lookback (days)", 7, 120, 30)
cutoff = dt.date.today() - dt.timedelta(days=days)


@st.cache_data(ttl=600)
def load(signal_type: str, cutoff: dt.date) -> pd.DataFrame:
    con = connect(read_only=True)
    try:
        return con.execute(
            """
            SELECT obs_date, entity_type, entity_name, metric,
                   value, expected, robust_z, severity, detail
            FROM signal
            WHERE signal_type = ? AND obs_date >= ?
            ORDER BY obs_date DESC, severity DESC
            """,
            [signal_type, cutoff],
        ).df()
    finally:
        con.close()


col1, col2 = st.columns(2)
with col1:
    st.subheader("Bottlenecks")
    st.dataframe(load("bottleneck", cutoff), use_container_width=True, hide_index=True)
with col2:
    st.subheader("Opportunities")
    st.dataframe(load("opportunity", cutoff), use_container_width=True, hide_index=True)

st.sidebar.write(f"DB: `{settings.db_path}`")
st.sidebar.write("Refresh data with `uv run logjam refresh`.")
