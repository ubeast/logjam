"""End-to-end refresh: ingest -> store -> baseline -> detect -> opportunities."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

import duckdb

from bottleneck_logistics.analytics.baseline import compute_baselines
from bottleneck_logistics.analytics.detect import detect_bottlenecks
from bottleneck_logistics.analytics.opportunity import detect_opportunities
from bottleneck_logistics.ingest.portwatch import default_since, fetch_portwatch, month_starts
from bottleneck_logistics.store.db import connect, init_schema, latest_observation_date
from bottleneck_logistics.store.loaders import upsert_observations

# Above this span we ingest month-by-month so a first backfill (potentially
# ~1M rows/year) never has to sit in memory all at once.
_CHUNK_THRESHOLD_DAYS = 75


@dataclass
class RefreshResult:
    since: dt.date
    observations_written: int
    baseline_rows: int
    bottlenecks: int
    opportunities: int


def _ingest(
    con: duckdb.DuckDBPyConnection, since: dt.date, *, progress: Callable[[str], None]
) -> int:
    """Fetch PortWatch data from ``since`` to today and upsert it. Returns rows."""
    today = dt.date.today()
    written = 0

    if (today - since).days <= _CHUNK_THRESHOLD_DAYS:
        progress(f"fetching {since} .. {today}")
        written += upsert_observations(con, fetch_portwatch(since=since), source="portwatch")
        return written

    bounds = [*month_starts(since, today), today + dt.timedelta(days=1)]
    for start, end in zip(bounds, bounds[1:], strict=False):
        chunk_since = max(start, since)
        progress(f"fetching {chunk_since} .. {end}")
        tidy = fetch_portwatch(since=chunk_since, until=end)
        written += upsert_observations(con, tidy, source="portwatch")
    return written


def refresh(
    *,
    full_backfill: bool = False,
    progress: Callable[[str], None] = lambda _msg: None,
) -> RefreshResult:
    """Run the whole pipeline. Safe to call repeatedly (idempotent upserts).

    Args:
        full_backfill: ignore stored data and pull ``initial_backfill_days``.
        progress: optional callback for human-readable status lines.
    """
    con = connect()
    try:
        init_schema(con)
        latest = None if full_backfill else latest_observation_date(con)
        since = default_since(latest)

        written = _ingest(con, since, progress=progress)

        progress("computing baselines")
        baseline_rows = compute_baselines(con)
        progress("detecting bottlenecks")
        bottlenecks = detect_bottlenecks(con)
        progress("detecting opportunities")
        opportunities = detect_opportunities(con)

        return RefreshResult(
            since=since,
            observations_written=written,
            baseline_rows=baseline_rows,
            bottlenecks=bottlenecks,
            opportunities=opportunities,
        )
    finally:
        con.close()
