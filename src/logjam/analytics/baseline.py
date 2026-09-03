"""Rolling robust baseline for every (entity, metric) series."""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from logjam.config import settings

# MAD -> sigma consistency constant for a normal distribution.
_MAD_TO_SIGMA = 1.4826


def robust_z_series(series: pd.DataFrame, window: int, min_obs: int) -> pd.DataFrame:
    """Single-series reference implementation of the baseline (used in tests).

    ``compute_baselines`` runs the same maths as vectorised groupby-rolling for
    speed; this function is the readable definition of what it computes.

    ``series`` is one sorted (entity, metric) group with columns date/value.

    Window is a *row count*, not a calendar window. PortWatch is daily and
    dense, so rows ~= days; gaps make the window look slightly further back,
    which is acceptable for a baseline. ``min_obs`` guards new/sparse series.

    ``closed="left"`` -> the current day is NOT in its own baseline, so a
    genuine anomaly cannot mask itself.

    Scale is a fast MAD approximation: the trailing median of absolute
    deviations from the trailing median. Both passes are vectorised C
    (``rolling().median()``); a strict per-window MAD via ``rolling().apply``
    is ~100x slower over tens of thousands of series and gives materially the
    same anomaly band.
    """
    v = series["value"]
    roll = v.rolling(window=window, min_periods=min_obs, closed="left")
    expected = roll.median()

    abs_dev = (v - expected).abs()
    mad_approx = abs_dev.rolling(window=window, min_periods=min_obs, closed="left").median()
    scale = (mad_approx * _MAD_TO_SIGMA).replace(0.0, np.nan)

    out = series.copy()
    out["expected"] = expected
    out["scale"] = scale
    out["robust_z"] = (v - expected) / scale
    out["n_obs"] = roll.count()
    return out.dropna(subset=["expected", "robust_z"])


def compute_baselines(con: duckdb.DuckDBPyConnection) -> int:
    """Recompute the ``baseline`` table from scratch. Returns rows written.

    Performance: this pulls the whole ``observation`` table into pandas. At a
    few million rows that is a couple of seconds and a few hundred MB. If the
    table grows past ~50M rows (e.g. after adding vessel-level AIS), push this
    into DuckDB window functions or process per entity_type in chunks.
    """
    obs = con.execute(
        """
        SELECT entity_type, entity_id, metric, obs_date AS date, value
        FROM observation
        ORDER BY entity_type, entity_id, metric, obs_date
        """
    ).df()
    if obs.empty:
        con.execute("DELETE FROM baseline")
        return 0

    window = settings.baseline_window_days
    min_obs = settings.baseline_min_observations
    keys = ["entity_type", "entity_id", "metric"]

    # Two vectorised groupby-rolling passes (see _robust_z_frame for the method).
    # `obs` is already sorted by (keys, obs_date) from the SQL query.
    def _grouped_roll(s: pd.Series) -> pd.Series:
        rolled = (
            s.groupby([obs[k] for k in keys], sort=False)
            .rolling(window=window, min_periods=min_obs, closed="left")
            .median()
        )
        # drop the group-key index levels, keep alignment to the original rows
        return rolled.reset_index(level=list(range(len(keys))), drop=True).sort_index()

    v = obs["value"]
    expected = _grouped_roll(v)
    abs_dev = (v - expected).abs()
    scale = (_grouped_roll(abs_dev) * _MAD_TO_SIGMA).replace(0.0, np.nan)
    n_obs = (
        v.groupby([obs[k] for k in keys], sort=False)
        .rolling(window=window, min_periods=min_obs, closed="left")
        .count()
        .reset_index(level=list(range(len(keys))), drop=True)
        .sort_index()
    )

    result = obs.assign(
        obs_date=obs["date"],
        expected=expected,
        scale=scale,
        robust_z=(v - expected) / scale,
        n_obs=n_obs,
    ).dropna(subset=["expected", "robust_z"])
    result = result[
        ["entity_type", "entity_id", "metric", "obs_date",
         "value", "expected", "scale", "robust_z", "n_obs"]
    ]
    result["n_obs"] = result["n_obs"].astype("int64")

    con.register("staged_baseline", result)
    try:
        con.execute("BEGIN TRANSACTION")
        con.execute("DELETE FROM baseline")
        con.execute(
            """
            INSERT INTO baseline
                (entity_type, entity_id, metric, obs_date,
                 value, expected, scale, robust_z, n_obs)
            SELECT entity_type, entity_id, metric, obs_date,
                   value, expected, scale, robust_z, n_obs
            FROM staged_baseline
            """
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("staged_baseline")

    _fill_yoy_baseline(con)
    return len(result)


def _fill_yoy_baseline(con: duckdb.DuckDBPyConnection) -> None:
    """Fill the year-over-year columns on ``baseline`` in a single SQL pass.

    For each baseline row, ``expected_yoy`` is the median observed value in a
    +/- ``yoy_halfwidth_days`` window centred ``yoy_lag_days`` before that row's
    date. Rows with fewer than ``yoy_min_observations`` year-ago points keep
    NULL YoY columns.

    Performance: this is a range self-join of ``observation`` (millions of rows)
    against ``baseline``. On a weekly refresh that is a few seconds to low tens
    of seconds; it is the heaviest single statement in the pipeline.
    """
    lag = settings.yoy_lag_days
    hw = settings.yoy_halfwidth_days
    min_obs = settings.yoy_min_observations

    con.execute(
        """
        UPDATE baseline b
        SET expected_yoy = sub.med,
            n_obs_yoy    = sub.n,
            robust_z_yoy = CASE WHEN b.scale > 0
                                THEN (b.value - sub.med) / b.scale END,
            pct_of_yoy   = CASE WHEN sub.med > 0
                                THEN b.value / sub.med END
        FROM (
            SELECT b2.entity_type, b2.entity_id, b2.metric, b2.obs_date,
                   median(o.value) AS med, count(*) AS n
            FROM baseline b2
            JOIN observation o
              ON o.entity_type = b2.entity_type
             AND o.entity_id   = b2.entity_id
             AND o.metric      = b2.metric
             AND o.obs_date BETWEEN b2.obs_date - ? AND b2.obs_date - ?
            GROUP BY 1, 2, 3, 4
            HAVING count(*) >= ?
        ) sub
        WHERE b.entity_type = sub.entity_type
          AND b.entity_id   = sub.entity_id
          AND b.metric      = sub.metric
          AND b.obs_date    = sub.obs_date
        """,
        [lag + hw, lag - hw, min_obs],
    )
