"""IMF PortWatch ingestion adapter.

Source: https://portwatch.imf.org  (Data & Methodology page for definitions).
Licence: free public use with attribution to IMF PortWatch.

PortWatch publishes two daily feature layers, both derived from satellite AIS
via the UN Global Platform and refreshed weekly (Tuesdays ~09:00 ET):

* ``Daily_Ports_Data``        - port calls + estimated import/export volume,
                                for ~2,065 ports.
* ``Daily_Chokepoints_Data``  - transit counts + estimated cargo capacity
                                for 28 maritime chokepoints (Hormuz, Suez,
                                Panama, Bab-el-Mandeb, ...).

What this gives us (and what it does not)
----------------------------------------
PortWatch is a *throughput* signal, not a *queue* signal: it counts vessels
arriving/transiting, not vessels waiting at anchor or berth dwell time. So from
this source we detect:

* Port throughput anomalies  - a sharp fall in port calls / trade volume vs a
  port's own seasonal baseline (disruption, strike, weather, conflict).
* Chokepoint transit anomalies - the most direct signal for events like the
  2026 Strait of Hormuz crisis: tanker transits through ``chokepoint`` collapse.

Anchorage queue length and berth dwell time require vessel-level AIS and will
come from a separate adapter (AISStream) later.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from logjam.config import settings
from logjam.ingest.arcgis import query_all

# Columns we keep as measures. Everything else (year/month/day/ObjectId) is
# either redundant with ``date`` or ArcGIS bookkeeping.
_PORT_METRICS: tuple[str, ...] = (
    "portcalls_container",
    "portcalls_dry_bulk",
    "portcalls_general_cargo",
    "portcalls_roro",
    "portcalls_tanker",
    "portcalls_cargo",
    "portcalls",
    "import_container",
    "import_dry_bulk",
    "import_general_cargo",
    "import_roro",
    "import_tanker",
    "import_cargo",
    "import",
    "export_container",
    "export_dry_bulk",
    "export_general_cargo",
    "export_roro",
    "export_tanker",
    "export_cargo",
    "export",
)

_CHOKEPOINT_METRICS: tuple[str, ...] = (
    "n_container",
    "n_dry_bulk",
    "n_general_cargo",
    "n_roro",
    "n_tanker",
    "n_cargo",
    "n_total",
    "capacity_container",
    "capacity_dry_bulk",
    "capacity_general_cargo",
    "capacity_roro",
    "capacity_tanker",
    "capacity_cargo",
    "capacity_total",
)

TIDY_COLUMNS: list[str] = [
    "entity_type",
    "entity_id",
    "entity_name",
    "country",
    "iso3",
    "date",
    "metric",
    "value",
]


def _parse_arcgis_date(value: Any) -> dt.date | None:
    """Parse an ArcGIS ``esriFieldTypeDateOnly`` value.

    This layer returns an ISO string (``"2026-08-21"``). Other ArcGIS services
    return epoch milliseconds for the same field type, so we handle both.
    """
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return dt.date.fromisoformat(value[:10])
    # numeric: epoch milliseconds (UTC)
    return dt.datetime.fromtimestamp(value / 1000, tz=dt.UTC).date()


def _where_range(since: dt.date | None, until: dt.date | None) -> str:
    """Build an ArcGIS where-clause for a half-open date range [since, until)."""
    parts: list[str] = []
    if since is not None:
        parts.append(f"date >= DATE '{since.isoformat()}'")
    if until is not None:
        parts.append(f"date < DATE '{until.isoformat()}'")
    return " AND ".join(parts) if parts else "1=1"


def _to_tidy(
    rows: list[dict[str, Any]],
    *,
    entity_type: str,
    metrics: tuple[str, ...],
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=TIDY_COLUMNS)

    wide = pd.DataFrame(rows)
    wide["date"] = wide["date"].map(_parse_arcgis_date)
    wide = wide.dropna(subset=["date"])

    id_vars = {
        "entity_id": "portid",
        "entity_name": "portname",
        "country": "country",
        "iso3": "ISO3",
    }
    # Chokepoint layer has no country/ISO3 columns.
    present_id_vars = {k: v for k, v in id_vars.items() if v in wide.columns}
    keep = list(present_id_vars.values()) + ["date"]
    present_metrics = [m for m in metrics if m in wide.columns]

    long = wide[keep + present_metrics].melt(
        id_vars=keep,
        value_vars=present_metrics,
        var_name="metric",
        value_name="value",
    )
    long = long.rename(columns={v: k for k, v in present_id_vars.items()})
    for missing in ("country", "iso3"):
        if missing not in long.columns:
            long[missing] = None

    long["entity_type"] = entity_type
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long = long.dropna(subset=["value"])
    return long[TIDY_COLUMNS].reset_index(drop=True)


def fetch_portwatch(
    since: dt.date | None = None,
    until: dt.date | None = None,
) -> pd.DataFrame:
    """Return tidy PortWatch observations for ports **and** chokepoints.

    Args:
        since: only pull rows on/after this date.
        until: only pull rows strictly before this date. Together they form a
            half-open range so month-by-month backfill chunks do not overlap.
            ``since=None`` pulls the server's full history - a few million rows
            per year, so the pipeline chunks large backfills (see
            :func:`logjam.pipeline.refresh`).

    Returns:
        DataFrame with :data:`TIDY_COLUMNS`. ``entity_type`` is ``"port"`` or
        ``"chokepoint"``.
    """
    where = _where_range(since, until)
    port_rows = list(query_all(settings.portwatch_ports_url, where=where))
    choke_rows = list(query_all(settings.portwatch_chokepoints_url, where=where))

    ports = _to_tidy(port_rows, entity_type="port", metrics=_PORT_METRICS)
    chokes = _to_tidy(choke_rows, entity_type="chokepoint", metrics=_CHOKEPOINT_METRICS)
    return pd.concat([ports, chokes], ignore_index=True)


def month_starts(since: dt.date, until: dt.date) -> list[dt.date]:
    """First-of-month boundaries spanning [since, until], for chunked backfill."""
    cur = since.replace(day=1)
    out: list[dt.date] = []
    while cur <= until:
        out.append(cur)
        cur = (cur.replace(day=28) + dt.timedelta(days=7)).replace(day=1)
    return out


def default_since(latest_stored: dt.date | None) -> dt.date:
    """Pick a ``since`` date: incremental if we have data, else a bounded backfill.

    We re-pull a small overlap (``baseline_window_days`` is overkill; 10 days is
    enough) because PortWatch revises recent estimates as more AIS arrives.
    """
    if latest_stored is not None:
        return latest_stored - dt.timedelta(days=10)
    return dt.date.today() - dt.timedelta(days=settings.initial_backfill_days)
