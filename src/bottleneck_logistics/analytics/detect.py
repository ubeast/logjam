"""Bottleneck detection: flag days where flow collapsed vs a series' baseline."""

from __future__ import annotations

import json

import duckdb

from bottleneck_logistics.config import settings

# Every PortWatch metric is "more == more flow" (port calls, transits, trade
# volume, cargo capacity). A bottleneck is therefore always the *negative* tail.
# A positive spike is a surge - interesting, but tracked separately later.
_BOTTLENECK_METRICS_LIKE = (
    "portcalls%",
    "import%",
    "export%",
    "n\\_%",  # chokepoint transit counts (escaped _ for LIKE)
    "capacity%",
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

    ``robust_z`` / ``expected`` on the signal row reflect whichever baseline
    triggered more strongly; ``detail.trigger`` records which fired.
    """
    z = settings.bottleneck_z_threshold
    min_obs = settings.baseline_min_observations
    yoy_min = settings.yoy_min_observations
    like_clause = " OR ".join("b.metric LIKE ? ESCAPE '\\'" for _ in _BOTTLENECK_METRICS_LIKE)

    rows = con.execute(
        f"""
        SELECT b.entity_type, b.entity_id, o.entity_name, b.metric, b.obs_date,
               b.value, b.expected, b.robust_z, b.n_obs,
               b.expected_yoy, b.robust_z_yoy, b.pct_of_yoy, b.n_obs_yoy
        FROM baseline b
        JOIN (
            SELECT entity_type, entity_id, any_value(entity_name) AS entity_name
            FROM observation GROUP BY entity_type, entity_id
        ) o USING (entity_type, entity_id)
        WHERE ({like_clause})
          AND (
                (b.robust_z <= ? AND b.n_obs >= ?)
             OR (b.robust_z_yoy <= ? AND b.n_obs_yoy >= ?)
          )
        """,
        [*_BOTTLENECK_METRICS_LIKE, -abs(z), min_obs, -abs(z), yoy_min],
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
