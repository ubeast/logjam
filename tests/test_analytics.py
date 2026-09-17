"""Store + baseline + detection over synthetic data."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from logjam.analytics.baseline import compute_baselines
from logjam.analytics.detect import detect_bottlenecks
from logjam.analytics.recovery import SEVERE, recovery_status
from logjam.store.loaders import upsert_observations


def _series(entity_id: str, name: str, values: list[float], metric: str) -> pd.DataFrame:
    start = dt.date(2024, 1, 1)
    return pd.DataFrame(
        {
            "entity_type": "port",
            "entity_id": entity_id,
            "entity_name": name,
            "country": "Testland",
            "iso3": "TST",
            "date": [start + dt.timedelta(days=i) for i in range(len(values))],
            "metric": metric,
            "value": values,
        }
    )


def test_upsert_is_idempotent(con) -> None:
    df = _series("port1", "Alpha", [10.0] * 30, "portcalls_container")
    upsert_observations(con, df)
    upsert_observations(con, df)  # same window again
    n = con.execute("SELECT count(*) FROM observation").fetchone()[0]
    assert n == 30


def test_bottleneck_flagged_on_throughput_collapse(con) -> None:
    # 60 stable days at ~100, then a hard drop to 10 that persists past the
    # trailing-exclude window (a single-day drop right at the series' latest
    # date is deliberately not flagged - see test_recent_collapse_not_yet_flagged).
    values = [100.0, 98.0, 102.0, 101.0, 99.0] * 12 + [10.0] * 5
    upsert_observations(con, _series("port1", "Alpha", values, "portcalls_container"))

    assert compute_baselines(con) > 0
    flagged = detect_bottlenecks(con)
    assert flagged >= 1

    row = con.execute(
        "SELECT metric, robust_z FROM signal "
        "WHERE signal_type = 'bottleneck' ORDER BY obs_date DESC LIMIT 1"
    ).fetchone()
    assert row[0] == "portcalls_container"
    assert row[1] < 0  # collapse, not surge


def test_recent_collapse_not_yet_flagged(con) -> None:
    # Same collapse, but confined to the series' most recent
    # `bottleneck_trailing_exclude_days` (2) days - PortWatch under-reports
    # exactly this window, so it should not be flagged yet.
    values = [100.0, 98.0, 102.0, 101.0, 99.0] * 12 + [10.0] * 2
    upsert_observations(con, _series("port1b", "AlphaB", values, "portcalls_container"))

    compute_baselines(con)
    assert detect_bottlenecks(con) == 0


def test_stable_series_produces_no_bottleneck(con) -> None:
    values = [100.0, 99.0, 101.0, 100.0, 100.0] * 14
    upsert_observations(con, _series("port2", "Beta", values, "portcalls"))
    compute_baselines(con)
    assert detect_bottlenecks(con) == 0


def _long_series(
    entity_id: str, name: str, values: list[float], metric: str
) -> pd.DataFrame:
    """Like _series but starting far enough back for a year-over-year lookup."""
    start = dt.date.today() - dt.timedelta(days=len(values))
    return pd.DataFrame(
        {
            "entity_type": "chokepoint",
            "entity_id": entity_id,
            "entity_name": name,
            "country": None,
            "iso3": None,
            "date": [start + dt.timedelta(days=i) for i in range(len(values))],
            "metric": metric,
            "value": values,
        }
    )


def test_sustained_collapse_still_flags_via_year_over_year(con) -> None:
    # ~14 months normal at ~60, then ~5 months collapsed at ~4 and holding.
    # The 56-day short baseline heals around the new low; YoY must keep flagging.
    normal = [60.0, 58.0, 62.0, 59.0, 61.0] * 84       # 420 days
    collapsed = [4.0, 3.0, 5.0, 4.0, 4.0] * 30          # 150 days
    upsert_observations(con, _long_series("chokepoint6", "Strait of Hormuz",
                                          normal + collapsed, "n_total"))
    compute_baselines(con)

    latest = con.execute(
        "SELECT robust_z, robust_z_yoy, pct_of_yoy FROM baseline "
        "WHERE metric='n_total' ORDER BY obs_date DESC LIMIT 1"
    ).fetchone()
    assert latest[0] > -2.0            # short baseline has healed
    assert latest[1] <= -2.0           # YoY still deeply negative
    assert latest[2] < 0.2             # running below 20% of a year ago

    assert detect_bottlenecks(con) >= 1
    trig = con.execute(
        "SELECT detail FROM signal WHERE signal_type='bottleneck' "
        "ORDER BY obs_date DESC LIMIT 1"
    ).fetchone()[0]
    # yoy must be part of what fired (short alone can heal near the trailing
    # edge, but the sustained collapse should still show up via yoy, whether
    # or not short also happens to trip on that particular day).
    assert '"trigger": "yoy"' in trig or '"trigger": "both"' in trig

    rec = recovery_status(con, "hormuz")
    assert rec and rec[0].verdict == SEVERE
    assert rec[0].pct_of_yoy is not None and rec[0].pct_of_yoy < 0.2
