"""Recovery status: is a disruption still ongoing, or has flow returned to normal?

Answers the question the bottleneck feed cannot: for a named port or chokepoint,
where does throughput sit *now* relative to a year ago, and which way is it
trending? Built on the ``baseline.pct_of_yoy`` column.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import duckdb

from bottleneck_logistics.config import settings

# The "headline" total metric per entity type - what a human means by
# "traffic through Hormuz" or "activity at Rotterdam".
_DEFAULT_METRICS = ("n_total", "portcalls", "import", "export")

Verdict = str  # one of the constants below
RECOVERED: Verdict = "recovered"
PARTIAL: Verdict = "partial recovery"
ONGOING: Verdict = "disruption ongoing"
SEVERE: Verdict = "severe disruption ongoing"
NO_HISTORY: Verdict = "insufficient year-ago history"


@dataclass(frozen=True)
class RecoveryRow:
    entity_type: str
    entity_id: str
    entity_name: str
    metric: str
    as_of: dt.date
    value: float
    expected_yoy: float | None
    pct_of_yoy: float | None
    pct_of_yoy_prior: float | None  # ~4 weeks earlier, for trend
    verdict: Verdict

    @property
    def trend(self) -> str:
        if self.pct_of_yoy is None or self.pct_of_yoy_prior is None:
            return "n/a"
        delta = self.pct_of_yoy - self.pct_of_yoy_prior
        if abs(delta) < 0.05:
            return "flat"
        return "improving" if delta > 0 else "worsening"


def _verdict(pct: float | None) -> Verdict:
    if pct is None:
        return NO_HISTORY
    if pct >= 1 - settings.recovery_tolerance:
        return RECOVERED
    if pct >= 0.75:
        return PARTIAL
    if pct >= 0.4:
        return ONGOING
    return SEVERE


def recovery_status(
    con: duckdb.DuckDBPyConnection,
    search: str,
    *,
    metrics: tuple[str, ...] = _DEFAULT_METRICS,
    prior_days: int = 28,
) -> list[RecoveryRow]:
    """Recovery status for every entity whose name matches ``search``.

    ``search`` is a case-insensitive substring of the port / chokepoint name.
    Each figure is the median over a trailing ``recovery_window_days`` window
    that ends ``recovery_trailing_exclude_days`` before the last available date
    (PortWatch under-reports its most recent days). ``pct_of_yoy_prior`` is the
    same window shifted ``prior_days`` back, for the trend column.

    Returns one row per (entity, metric), worst (lowest pct_of_yoy) first.
    """
    like = f"%{search}%"
    metric_list = ",".join(f"'{m}'" for m in metrics)
    win = settings.recovery_window_days
    excl = settings.recovery_trailing_exclude_days

    rows = con.execute(
        f"""
        WITH names AS (
            SELECT entity_type, entity_id, any_value(entity_name) AS entity_name
            FROM observation GROUP BY entity_type, entity_id
        ),
        matched AS (
            SELECT DISTINCT b.entity_type, b.entity_id, b.metric
            FROM baseline b
            JOIN names o USING (entity_type, entity_id)
            WHERE lower(o.entity_name) LIKE lower(?)
              AND b.metric IN ({metric_list})
        ),
        bounds AS (  -- trailing evaluation window per series
            SELECT m.entity_type, m.entity_id, m.metric,
                   max(b.obs_date) - ? AS win_end,
                   max(b.obs_date) - ? - ? AS win_start
            FROM matched m
            JOIN baseline b USING (entity_type, entity_id, metric)
            GROUP BY 1, 2, 3
        ),
        agg AS (
            SELECT x.entity_type, x.entity_id, x.metric,
                   max(b.obs_date) AS as_of,
                   median(b.value) AS value,
                   median(b.expected_yoy) AS expected_yoy,
                   median(b.pct_of_yoy) AS pct_of_yoy,
                   median(pr.pct_of_yoy) AS pct_of_yoy_prior
            FROM bounds x
            JOIN baseline b
              ON b.entity_type = x.entity_type AND b.entity_id = x.entity_id
             AND b.metric = x.metric
             AND b.obs_date BETWEEN x.win_start AND x.win_end
            LEFT JOIN baseline pr
              ON pr.entity_type = x.entity_type AND pr.entity_id = x.entity_id
             AND pr.metric = x.metric AND pr.obs_date = b.obs_date - ?
            GROUP BY 1, 2, 3
        )
        SELECT a.entity_type, a.entity_id, n.entity_name, a.metric, a.as_of,
               a.value, a.expected_yoy, a.pct_of_yoy, a.pct_of_yoy_prior
        FROM agg a
        JOIN names n USING (entity_type, entity_id)
        ORDER BY a.pct_of_yoy NULLS LAST
        """,
        [like, excl, excl, win - 1, prior_days],
    ).fetchall()

    out: list[RecoveryRow] = []
    for (etype, eid, ename, metric, as_of, value, exp_yoy, pct, pct_prior) in rows:
        out.append(
            RecoveryRow(
                entity_type=etype,
                entity_id=eid,
                entity_name=ename,
                metric=metric,
                as_of=as_of,
                value=value,
                expected_yoy=exp_yoy,
                pct_of_yoy=pct,
                pct_of_yoy_prior=pct_prior,
                verdict=_verdict(pct),
            )
        )
    return out
