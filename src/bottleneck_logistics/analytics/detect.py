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

    A day is flagged when ``robust_z <= -threshold`` and the baseline rests on
    at least ``baseline_min_observations`` points. ``severity`` is ``abs(z)``.
    """
    z = settings.bottleneck_z_threshold
    min_obs = settings.baseline_min_observations
    like_clause = " OR ".join("b.metric LIKE ? ESCAPE '\\'" for _ in _BOTTLENECK_METRICS_LIKE)

    rows = con.execute(
        f"""
        SELECT b.entity_type, b.entity_id, o.entity_name, b.metric, b.obs_date,
               b.value, b.expected, b.scale, b.robust_z, b.n_obs
        FROM baseline b
        JOIN (
            SELECT entity_type, entity_id, any_value(entity_name) AS entity_name
            FROM observation GROUP BY entity_type, entity_id
        ) o USING (entity_type, entity_id)
        WHERE b.robust_z <= ?
          AND b.n_obs >= ?
          AND ({like_clause})
        """,
        [-abs(z), min_obs, *_BOTTLENECK_METRICS_LIKE],
    ).fetchall()

    con.execute("DELETE FROM signal WHERE signal_type = 'bottleneck'")
    if not rows:
        return 0

    payload = []
    for (etype, eid, ename, metric, obs_date, value, expected, scale, rz, n_obs) in rows:
        drop_pct = None if not expected else round(100 * (value - expected) / expected, 1)
        detail = json.dumps(
            {
                "drop_pct_vs_expected": drop_pct,
                "scale": round(scale, 3) if scale is not None else None,
                "baseline_n_obs": int(n_obs),
                "window_days": settings.baseline_window_days,
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
