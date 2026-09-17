"""Bottleneck detection: flag days where flow collapsed vs a series' baseline."""

from __future__ import annotations

import json

import duckdb

from logjam.config import settings

# Every PortWatch metric is "more == more flow" (port calls, transits, trade
# volume, cargo capacity). A bottleneck is therefore always the *negative* tail.
# A positive spike is a surge - interesting, but tracked separately later.
_BOTTLENECK_METRICS_LIKE = (
    "portcalls%",
    "import%",
    "export%",
    "n\\_%",  # chokepoint transit counts (escaped _ for LIKE)
    "capacity%",
    "vessels\\_moving",   # AIS: fewer vessels under way near a port == blocked
    "ais\\_transiting",   # AIS: fewer vessels moving through a chokepoint == blocked
)


def detect_bottlenecks(con: duckdb.DuckDBPyConnection) -> int:
    """Populate ``signal`` rows of type 'bottleneck'. Returns rows written.

    A day is flagged when the **short** baseline z-score OR the **year-over-year**
    z-score is at or below ``-bottleneck_z_threshold``:

    * short trigger  -> a fresh disruption (onset).
    * yoy trigger    -> still materially below where this series was a year ago,
                        even if the short baseline has "healed" around the new
                        low level. This is what keeps a months-long event (e.g. a
                        Strait of Hormuz shutdown) visible instead of it fading
                        once the crisis becomes the trailing norm.

    A series' most recent ``bottleneck_trailing_exclude_days`` days are never
    flagged: PortWatch revises those estimates upward as more data arrives, so a
    fresh low can be an under-report rather than a real stoppage (see
    ``docs/METHODOLOGY.md`` known limitation #3). A collapse that persists past
    that window still gets flagged on its older, no-longer-trailing days.

    An exact-zero day on a series that normally runs at least
    ``bottleneck_zero_expected_min`` is treated as a likely reporting gap rather
    than a real stoppage, and is skipped too - *unless* the previous day was also
    zero, in which case the zero has become a sustained run (e.g. an actual canal
    closure) and gets flagged like any other collapse.

    ``robust_z`` / ``expected`` on the signal row reflect whichever baseline
    triggered more strongly; ``detail.trigger`` records which fired.
    """
    z = settings.bottleneck_z_threshold
    min_obs = settings.baseline_min_observations
    yoy_min = settings.yoy_min_observations
    excl = settings.bottleneck_trailing_exclude_days
    zero_min = settings.bottleneck_zero_expected_min
    like_clause = " OR ".join("b.metric LIKE ? ESCAPE '\\'" for _ in _BOTTLENECK_METRICS_LIKE)

    rows = con.execute(
        f"""
        WITH series_latest AS (
            SELECT entity_type, entity_id, metric, max(obs_date) AS latest_date
            FROM baseline
            GROUP BY 1, 2, 3
        ),
        with_prior AS (
            SELECT entity_type, entity_id, metric, obs_date,
                   lag(value) OVER (
                       PARTITION BY entity_type, entity_id, metric ORDER BY obs_date
                   ) AS prior_value
            FROM baseline
        )
        SELECT b.entity_type, b.entity_id, o.entity_name, b.metric, b.obs_date,
               b.value, b.expected, b.robust_z, b.n_obs,
               b.expected_yoy, b.robust_z_yoy, b.pct_of_yoy, b.n_obs_yoy
        FROM baseline b
        JOIN series_latest sl USING (entity_type, entity_id, metric)
        JOIN with_prior p USING (entity_type, entity_id, metric, obs_date)
        JOIN (
            SELECT entity_type, entity_id, any_value(entity_name) AS entity_name
            FROM observation GROUP BY entity_type, entity_id
        ) o USING (entity_type, entity_id)
        WHERE ({like_clause})
          AND b.obs_date <= sl.latest_date - ?
          AND NOT (
                b.value = 0 AND b.expected >= ?
                AND (p.prior_value IS NULL OR p.prior_value != 0)
              )
          AND (
                (b.robust_z <= ? AND b.n_obs >= ?)
             OR (b.robust_z_yoy <= ? AND b.n_obs_yoy >= ?)
          )
        """,
        [*_BOTTLENECK_METRICS_LIKE, excl, zero_min, -abs(z), min_obs, -abs(z), yoy_min],
    ).fetchall()

    con.execute("DELETE FROM signal WHERE signal_type = 'bottleneck'")
    if not rows:
        return 0

    payload = []
    for (
        etype, eid, ename, metric, obs_date,
        value, expected, rz, n_obs,
        expected_yoy, rz_yoy, pct_yoy, n_obs_yoy,
    ) in rows:
        short_hit = rz is not None and n_obs is not None and rz <= -abs(z) and n_obs >= min_obs
        yoy_hit = (
            rz_yoy is not None and n_obs_yoy is not None
            and rz_yoy <= -abs(z) and n_obs_yoy >= yoy_min
        )
        trigger = "both" if short_hit and yoy_hit else ("short" if short_hit else "yoy")

        # Report on whichever baseline is the more extreme.
        yoy_more_extreme = rz_yoy is not None and rz is not None and rz_yoy < rz
        use_yoy = yoy_hit and (not short_hit or yoy_more_extreme)
        report_z = rz_yoy if use_yoy else rz
        report_exp = expected_yoy if use_yoy else expected
        drop_pct = (
            None if not report_exp else round(100 * (value - report_exp) / report_exp, 1)
        )
        detail = json.dumps(
            {
                "trigger": trigger,
                "drop_pct_vs_expected": drop_pct,
                "short": {
                    "expected": round(expected, 2) if expected is not None else None,
                    "robust_z": round(rz, 2) if rz is not None else None,
                    "n_obs": int(n_obs) if n_obs is not None else None,
                    "window_days": settings.baseline_window_days,
                },
                "yoy": {
                    "expected": round(expected_yoy, 2) if expected_yoy is not None else None,
                    "robust_z": round(rz_yoy, 2) if rz_yoy is not None else None,
                    "pct_of_year_ago": round(pct_yoy, 3) if pct_yoy is not None else None,
                    "n_obs": int(n_obs_yoy) if n_obs_yoy is not None else None,
                },
            }
        )
        payload.append(
            (etype, eid, ename, metric, obs_date, value, report_exp,
             report_z, abs(report_z), detail)
        )

    con.executemany(
        """
        INSERT INTO signal
            (signal_type, entity_type, entity_id, entity_name, metric, obs_date,
             value, expected, robust_z, severity, detail)
        VALUES ('bottleneck', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    return len(payload)


# AIS metrics where *more* means flow is blocked - the bottleneck is the
# POSITIVE tail (a growing anchorage queue), the mirror image of every
# PortWatch metric. Kept out of `detect_bottlenecks` so its sign logic stays
# simple.
_CONGESTION_METRICS = ("vessels_at_anchor",)


def detect_congestion(con: duckdb.DuckDBPyConnection) -> int:
    """Flag AIS anchorage-queue spikes as bottleneck signals. Returns rows written.

    A day is flagged when the short baseline z-score for a ``_CONGESTION_METRICS``
    series is at or **above** ``+bottleneck_z_threshold``: materially more vessels
    sitting at anchor than the trailing norm. ``detail.trigger`` is
    ``"ais_congestion"`` so these are distinguishable from throughput collapses.
    """
    z = settings.bottleneck_z_threshold
    min_obs = settings.baseline_min_observations
    placeholders = ", ".join("?" for _ in _CONGESTION_METRICS)

    rows = con.execute(
        f"""
        SELECT b.entity_type, b.entity_id, o.entity_name, b.metric, b.obs_date,
               b.value, b.expected, b.robust_z, b.n_obs
        FROM baseline b
        JOIN (
            SELECT entity_type, entity_id, any_value(entity_name) AS entity_name
            FROM observation GROUP BY entity_type, entity_id
        ) o USING (entity_type, entity_id)
        WHERE b.metric IN ({placeholders})
          AND b.robust_z >= ? AND b.n_obs >= ?
        """,
        [*_CONGESTION_METRICS, abs(z), min_obs],
    ).fetchall()

    con.execute(
        "DELETE FROM signal WHERE signal_type = 'bottleneck' "
        f"AND metric IN ({placeholders})",
        list(_CONGESTION_METRICS),
    )
    if not rows:
        return 0

    payload = []
    for etype, eid, ename, metric, obs_date, value, expected, rz, n_obs in rows:
        rise_pct = None if not expected else round(100 * (value - expected) / expected, 1)
        detail = json.dumps(
            {
                "trigger": "ais_congestion",
                "rise_pct_vs_expected": rise_pct,
                "short": {
                    "expected": round(expected, 2) if expected is not None else None,
                    "robust_z": round(rz, 2) if rz is not None else None,
                    "n_obs": int(n_obs) if n_obs is not None else None,
                    "window_days": settings.baseline_window_days,
                },
            }
        )
        payload.append(
            (etype, eid, ename, metric, obs_date, value, expected, rz, abs(rz), detail)
        )

    con.executemany(
        """
        INSERT INTO signal
            (signal_type, entity_type, entity_id, entity_name, metric, obs_date,
             value, expected, robust_z, severity, detail)
        VALUES ('bottleneck', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    return len(payload)
