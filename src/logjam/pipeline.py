"""End-to-end refresh: ingest -> store -> baseline -> detect -> opportunities."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

import duckdb

from logjam.analytics.ais_reduce import reduce_pending as reduce_ais_pending
from logjam.analytics.baseline import compute_baselines
from logjam.analytics.detect import detect_bottlenecks, detect_congestion
from logjam.analytics.opportunity import detect_opportunities
from logjam.config import settings
from logjam.ingest.gdelt import fetch_gdelt
from logjam.ingest.portwatch import default_since, fetch_portwatch, month_starts
from logjam.store.db import connect, init_schema, latest_observation_date
from logjam.store.loaders import upsert_observations

# Above this span we ingest month-by-month so a first backfill (potentially
# ~1M rows/year) never has to sit in memory all at once.
_CHUNK_THRESHOLD_DAYS = 75


@dataclass
class RefreshResult:
    since: dt.date
    observations_written: int
    ais_rows_written: int
    baseline_rows: int
    bottlenecks: int
    opportunities: int
    gdelt_rows_written: int = 0


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

        # News-attention signal (GDELT). Off by default (the DOC API is slow);
        # best-effort when on, so a failure never sinks the PortWatch run.
        gdelt_rows = 0
        if settings.gdelt_on_refresh:
            progress("fetching GDELT news signal")
            try:
                gdelt_rows = upsert_observations(con, fetch_gdelt(since=since), source="gdelt")
                if gdelt_rows:
                    progress(f"  {gdelt_rows:,} GDELT observation rows")
            except Exception as exc:  # noqa: BLE001 - non-critical source, keep going
                progress(f"  GDELT skipped: {type(exc).__name__}: {exc}")

        # Fold in any AIS captures that have not been reduced yet. No-op unless
        # the AISStream sampler (`logjam ais-collect`) has been run.
        progress("reducing AIS captures")
        ais_rows = reduce_ais_pending(con)
        if ais_rows:
            progress(f"  {ais_rows:,} AIS observation rows")

        progress("computing baselines")
        baseline_rows = compute_baselines(con)
        progress("detecting bottlenecks")
        bottlenecks = detect_bottlenecks(con) + detect_congestion(con)
        progress("detecting opportunities")
        opportunities = detect_opportunities(con)

        return RefreshResult(
            since=since,
            observations_written=written,
            ais_rows_written=ais_rows,
            baseline_rows=baseline_rows,
            bottlenecks=bottlenecks,
            opportunities=opportunities,
            gdelt_rows_written=gdelt_rows,
        )
    finally:
        con.close()
