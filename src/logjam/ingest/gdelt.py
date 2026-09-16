"""GDELT ingestion adapter - the news-attention signal.

PortWatch tells you a chokepoint's transits collapsed; it cannot tell you *why*.
GDELT (the Global Database of Events, Language, and Tone) monitors world news in
100+ languages in near-real time and is free with no API key. This adapter pulls
two daily series per watched chokepoint from the DOC 2.0 API:

* ``gdelt_volume`` - share of GDELT's monitored articles that mention the
  chokepoint that day, in per-mille (normalised by the daily total so the
  steady growth of GDELT's own corpus does not create a trend). A spike is a
  surge of attention - almost always a disruption for a shipping chokepoint.
* ``gdelt_tone``   - average sentiment of that coverage on GDELT's tone scale
  (roughly -10..+10; negative = negative coverage).

Both land in the ``observation`` table as ``entity_type='chokepoint'`` keyed by
the PortWatch chokepoint id, so baselines and any later cross-referencing line
up with the throughput analysis for the same chokepoint.

**Window.** The DOC 2.0 API only serves roughly the last three months, so this
is a *collect-forward* source like the AIS sampler: each refresh pulls the
trailing window and the store accumulates history past what the API still
returns. ``fetch_gdelt`` clamps ``since`` to ``gdelt_max_lookback_days``.

Query strings live in ``resources/gdelt_queries.yaml``; only chokepoints listed
there are tracked.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections import defaultdict
from functools import lru_cache
from typing import Any

import httpx
import pandas as pd
import yaml

from logjam.config import settings
from logjam.ingest.portwatch import TIDY_COLUMNS

_VOLUME_METRIC = "gdelt_volume"
_TONE_METRIC = "gdelt_tone"
_DT_FMT = "%Y%m%d%H%M%S"


@lru_cache(maxsize=1)
def _queries() -> dict[str, str]:
    """{chokepoint_id: GDELT query string} from the resource file."""
    cfg = yaml.safe_load(settings.gdelt_queries_path.read_text())
    return dict(cfg.get("chokepoints", {}))


@lru_cache(maxsize=1)
def _chokepoint_names() -> dict[str, str]:
    """{chokepoint_id: display name} from the PortWatch coordinate table."""
    data = json.loads((settings.geo_dir / "portwatch_places.json").read_text())
    return {cid: str(v[2]) for cid, v in data["chokepoints"].items()}


class GdeltUnavailable(RuntimeError):
    """The DOC API timed out or kept rate-limiting - a transient, retry-later state."""


def _get(
    client: httpx.Client, query: str, mode: str, start: dt.date, end: dt.date
) -> list[dict[str, Any]]:
    """One DOC 2.0 timeline call -> its ``data`` list.

    Retries the API's 429s and its frequent timeouts a few times, then raises
    :class:`GdeltUnavailable` so the caller can skip this series and move on.
    """
    params = {
        "query": query,
        "mode": mode,
        "format": "json",
        "startdatetime": dt.datetime(start.year, start.month, start.day).strftime(_DT_FMT),
        "enddatetime": dt.datetime(end.year, end.month, end.day).strftime(_DT_FMT),
    }
    for attempt in range(4):
        try:
            resp = client.get(settings.gdelt_doc_url, params=params)
        except httpx.TransportError:  # connect/read timeout, connection reset, ...
            time.sleep(settings.gdelt_request_pause_s * (attempt + 2))
            continue
        if resp.status_code == 429:
            time.sleep(settings.gdelt_request_pause_s * (attempt + 2))
            continue
        resp.raise_for_status()
        # GDELT returns an HTML error page (not JSON) for a malformed query.
        try:
            payload = resp.json()
        except ValueError as exc:
            raise RuntimeError(
                f"GDELT returned non-JSON for query {query!r}: {resp.text[:200]}"
            ) from exc
        timeline = payload.get("timeline") or []
        return timeline[0]["data"] if timeline else []
    raise GdeltUnavailable(f"GDELT DOC API unreachable for mode={mode} query={query!r}")


def _daily_volume(rows: list[dict[str, Any]]) -> dict[dt.date, float]:
    """Roll (possibly sub-daily) volraw points up to per-mille share per day."""
    hits: dict[dt.date, float] = defaultdict(float)
    total: dict[dt.date, float] = defaultdict(float)
    for r in rows:
        day = dt.datetime.strptime(r["date"][:8], "%Y%m%d").date()
        hits[day] += float(r.get("value") or 0.0)
        total[day] += float(r.get("norm") or 0.0)
    return {d: 1000.0 * hits[d] / total[d] for d in hits if total[d] > 0}


def _daily_tone(rows: list[dict[str, Any]]) -> dict[dt.date, float]:
    """Roll tone points up to a simple daily mean."""
    acc: dict[dt.date, list[float]] = defaultdict(list)
    for r in rows:
        val = r.get("value")
        if val is None:
            continue
        acc[dt.datetime.strptime(r["date"][:8], "%Y%m%d").date()].append(float(val))
    return {d: sum(v) / len(v) for d, v in acc.items() if v}


def fetch_gdelt(since: dt.date | None = None, until: dt.date | None = None) -> pd.DataFrame:
    """Return tidy GDELT news-attention observations for the watched chokepoints.

    Args:
        since: only keep rows on/after this date. Clamped to
            ``today - gdelt_max_lookback_days`` (the DOC 2.0 API window).
        until: only keep rows strictly before this date (half-open range).

    Returns:
        DataFrame with :data:`logjam.ingest.portwatch.TIDY_COLUMNS`,
        ``entity_type='chokepoint'``, metrics ``gdelt_volume`` / ``gdelt_tone``.
        Empty frame (right columns) if nothing is configured or returned.
    """
    today = dt.date.today()
    floor = today - dt.timedelta(days=settings.gdelt_max_lookback_days)
    start = max(since, floor) if since else floor
    end = min(until, today + dt.timedelta(days=1)) if until else today + dt.timedelta(days=1)
    if start >= end:
        return pd.DataFrame(columns=TIDY_COLUMNS)

    names = _chokepoint_names()
    records: list[dict[str, Any]] = []
    attempted = failed = 0
    with httpx.Client(timeout=settings.gdelt_timeout_s) as client:
        for cid, query in _queries().items():
            for metric, mode, rollup in (
                (_VOLUME_METRIC, "timelinevolraw", _daily_volume),
                (_TONE_METRIC, "timelinetone", _daily_tone),
            ):
                attempted += 1
                try:
                    daily = rollup(_get(client, query, mode, start, end))
                except GdeltUnavailable:
                    failed += 1
                    continue  # skip this series; keep whatever else we can get
                for day, value in daily.items():
                    if start <= day < end:
                        records.append(
                            {
                                "entity_type": "chokepoint",
                                "entity_id": cid,
                                "entity_name": names.get(cid, cid),
                                "country": None,
                                "iso3": None,
                                "date": day,
                                "metric": metric,
                                "value": round(value, 4),
                            }
                        )
                time.sleep(settings.gdelt_request_pause_s)

    # Only treat it as an error if *every* call failed - a partial pull still
    # advances the store and the next refresh fills the gaps.
    if failed and failed == attempted:
        raise GdeltUnavailable(f"all {attempted} GDELT calls failed - API is down or throttling us")
    if not records:
        return pd.DataFrame(columns=TIDY_COLUMNS)
    return pd.DataFrame(records, columns=TIDY_COLUMNS)
