"""Store + baseline + detection over synthetic data."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from bottleneck_logistics.analytics.baseline import compute_baselines
from bottleneck_logistics.analytics.detect import detect_bottlenecks
from bottleneck_logistics.store.loaders import upsert_observations


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
    # 60 stable days at ~100, then a hard drop to 10.
    values = [100.0, 98.0, 102.0, 101.0, 99.0] * 12 + [10.0]
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


def test_stable_series_produces_no_bottleneck(con) -> None:
    values = [100.0, 99.0, 101.0, 100.0, 100.0] * 14
    upsert_observations(con, _series("port2", "Beta", values, "portcalls"))
    compute_baselines(con)
    assert detect_bottlenecks(con) == 0
