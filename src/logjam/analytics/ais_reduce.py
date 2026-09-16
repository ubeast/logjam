"""Reduce raw AIS captures to daily per-zone metrics.

The :mod:`logjam.ingest.aisstream` sampler drops raw position
reports into ``settings.ais_raw_dir/dt=<date>/*.parquet``. This module turns one
day of those captures into rows for the ``observation`` table (source
``aisstream``), using the geofences in :mod:`logjam.ingest.ais_zones`:

* per watched port
    - ``vessels_at_anchor`` - distinct vessels sitting still in the anchorage
      catchment (a queue: a *standing* quantity, so a sample measures it well)
    - ``vessels_moving``     - distinct vessels under way near the port
* per chokepoint in a subscription region
    - ``ais_transiting``     - distinct vessels under way inside the chokepoint
      box during the sample - an independent, same-day cross-check on
      PortWatch's ``n_total`` (which lags a week and reads exact-zero on
      missing data)

These are counts *observed during the sample window*, not full-day censuses;
they are comparable across days because the sampling cadence is fixed.
"""

from __future__ import annotations

import datetime as dt
import shutil
from typing import cast

import duckdb
import numpy as np
import pandas as pd

from logjam.config import settings
from logjam.ingest.ais_zones import Zone, load_zones
from logjam.ingest.portwatch import TIDY_COLUMNS
from logjam.store.loaders import upsert_observations

_MOVING_SOG_KN = 3.0            # at/above this a vessel is "under way"
_ANCHOR_NAV_STATUS = (1, 5)     # AIS: 1 = at anchor, 5 = moored
_SOG_NOT_AVAILABLE = 80.0       # AIS encodes "no speed" as ~102.3 kn; treat as missing
_RE_REDUCE_TRAILING_DAYS = 2    # always redo the last couple of days (partial samples)
_KM_PER_DEG_LAT = 111.32


def _raw_dates() -> list[dt.date]:
    root = settings.ais_raw_dir
    if not root.exists():
        return []
    out: list[dt.date] = []
    for child in sorted(root.glob("dt=*")):
        try:
            out.append(dt.date.fromisoformat(child.name[3:]))
        except ValueError:
            continue
    return out


def _load_day(date: dt.date) -> pd.DataFrame:
    """All position reports captured for ``date`` (deduped later per zone)."""
    glob = str(settings.ais_raw_dir / f"dt={date.isoformat()}" / "*.parquet")
    con = duckdb.connect()
    try:
        return con.execute(
            f"""
            SELECT mmsi, lat, lon, sog, nav_status
            FROM read_parquet('{glob}')
            WHERE msg_type = 'PositionReport' AND lat IS NOT NULL AND lon IS NOT NULL
            """
        ).df()
    finally:
        con.close()


def _haversine_km(lat1: np.ndarray, lon1: np.ndarray, lat0: float, lon0: float) -> np.ndarray:
    p1 = np.radians(lat1)
    p0 = np.radians(lat0)
    dp = np.radians(lat1 - lat0)
    dl = np.radians(lon1 - lon0)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p0) * np.sin(dl / 2) ** 2
    return cast(np.ndarray, 2 * 6371.0088 * np.arcsin(np.sqrt(a)))


def _in_zone(df: pd.DataFrame, z: Zone) -> pd.DataFrame:
    """Rows of ``df`` inside zone ``z`` (bbox prefilter, then exact shape)."""
    pad = z.radius_km / _KM_PER_DEG_LAT if z.radius_km is not None else (z.half_deg or 0.0)
    cand = df[
        df["lat"].between(z.lat - pad, z.lat + pad)
        & df["lon"].between(z.lon - pad, z.lon + pad)
    ]
    if cand.empty:
        return cand
    if z.radius_km is not None:
        d = _haversine_km(cand["lat"].to_numpy(), cand["lon"].to_numpy(), z.lat, z.lon)
        return cand[d <= z.radius_km]
    hd = z.half_deg or 0.0
    return cand[(cand["lat"] - z.lat).abs().le(hd) & (cand["lon"] - z.lon).abs().le(hd)]


def _zone_metrics(inz: pd.DataFrame, z: Zone) -> dict[str, int]:
    """Per-vessel roll-up inside one zone -> the metric counts for that zone."""
    if inz.empty:
        return {}
    inz = inz.assign(sog=inz["sog"].where(inz["sog"] < _SOG_NOT_AVAILABLE))
    g = inz.groupby("mmsi").agg(
        sog_med=("sog", "median"),
        anchored=("nav_status", lambda s: s.isin(_ANCHOR_NAV_STATUS).any()),
    )
    still = g["sog_med"].le(settings.ais_anchor_max_sog_kn) | g["anchored"]
    moving = g["sog_med"].ge(_MOVING_SOG_KN)

    if z.entity_type == "chokepoint":
        return {"ais_transiting": int(moving.sum())}
    return {
        "vessels_at_anchor": int(still.sum()),
        "vessels_moving": int(moving.sum()),
    }


def reduce_day(con: duckdb.DuckDBPyConnection, date: dt.date) -> int:
    """Reduce one day's raw captures into ``observation``. Returns rows written."""
    raw = _load_day(date)
    if len(raw) < settings.ais_min_messages_per_day:
        return 0

    records: list[dict[str, object]] = []
    for z in load_zones():
        for metric, value in _zone_metrics(_in_zone(raw, z), z).items():
            records.append(
                {
                    "entity_type": z.entity_type,
                    "entity_id": z.entity_id,
                    "entity_name": z.entity_name,
                    "country": None,
                    "iso3": None,
                    "date": date,
                    "metric": metric,
                    "value": float(value),
                }
            )
    if not records:
        return 0
    tidy = pd.DataFrame(records, columns=TIDY_COLUMNS)
    return upsert_observations(con, tidy, source="aisstream")


def _prune_raw(reduced: set[dt.date]) -> None:
    """Delete raw capture dirs older than the retention window once reduced."""
    horizon = dt.date.today() - dt.timedelta(days=settings.ais_raw_retention_days)
    for d in _raw_dates():
        if d < horizon and d in reduced:
            shutil.rmtree(settings.ais_raw_dir / f"dt={d.isoformat()}", ignore_errors=True)


def reduce_pending(con: duckdb.DuckDBPyConnection) -> int:
    """Reduce every captured day not yet in the store (plus the last two, always).

    Returns total observation rows written. Safe to call every refresh; a no-op
    when there are no raw captures. Also prunes raw captures past
    ``ais_raw_retention_days`` - the reduced metrics stay in the store.
    """
    dates = _raw_dates()
    if not dates:
        return 0
    done = {
        r[0]
        for r in con.execute(
            "SELECT DISTINCT obs_date FROM observation WHERE source = 'aisstream'"
        ).fetchall()
    }
    cutoff = dt.date.today() - dt.timedelta(days=_RE_REDUCE_TRAILING_DAYS)
    written = 0
    for d in dates:
        if d in done and d < cutoff:
            continue
        written += reduce_day(con, d)

    reduced_ok = done | {
        r[0]
        for r in con.execute(
            "SELECT DISTINCT obs_date FROM observation WHERE source = 'aisstream'"
        ).fetchall()
    }
    _prune_raw(reduced_ok)
    return written
