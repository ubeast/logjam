"""Connection handling and schema definition."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import duckdb

from bottleneck_logistics.config import settings

# Bump when the schema changes in a non-additive way; ``init_schema`` is
# additive-only today, so this is informational.
SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS observation (
    entity_type   TEXT    NOT NULL,   -- 'port' | 'chokepoint'
    entity_id     TEXT    NOT NULL,   -- PortWatch portid, e.g. 'port1114'
    entity_name   TEXT,
    country       TEXT,
    iso3          TEXT,
    obs_date      DATE    NOT NULL,
    metric        TEXT    NOT NULL,   -- e.g. 'portcalls_container', 'n_tanker'
    value         DOUBLE  NOT NULL,
    source        TEXT    NOT NULL DEFAULT 'portwatch',
    ingested_at   TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (entity_type, entity_id, obs_date, metric, source)
);

CREATE INDEX IF NOT EXISTS observation_date_idx ON observation (obs_date);
CREATE INDEX IF NOT EXISTS observation_entity_idx ON observation (entity_type, entity_id, metric);

-- Rolling per-series baseline, recomputed by analytics.baseline.
CREATE TABLE IF NOT EXISTS baseline (
    entity_type   TEXT   NOT NULL,
    entity_id     TEXT   NOT NULL,
    metric        TEXT   NOT NULL,
    obs_date      DATE   NOT NULL,
    value         DOUBLE NOT NULL,     -- the actual observed value that day
    expected      DOUBLE NOT NULL,     -- trailing median
    scale         DOUBLE NOT NULL,     -- trailing MAD (scaled to ~sigma)
    robust_z      DOUBLE NOT NULL,     -- (value - expected) / scale
    n_obs         INTEGER NOT NULL,
    computed_at   TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (entity_type, entity_id, metric, obs_date)
);

-- Detected bottlenecks (flow blocked) and opportunities (flow available).
CREATE TABLE IF NOT EXISTS signal (
    signal_type   TEXT   NOT NULL,     -- 'bottleneck' | 'opportunity'
    entity_type   TEXT   NOT NULL,
    entity_id     TEXT   NOT NULL,
    entity_name   TEXT,
    metric        TEXT   NOT NULL,
    obs_date      DATE   NOT NULL,
    value         DOUBLE NOT NULL,
    expected      DOUBLE NOT NULL,
    robust_z      DOUBLE NOT NULL,
    severity      DOUBLE NOT NULL,     -- abs(robust_z), for ranking
    detail        JSON,                -- signal-specific context
    computed_at   TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (signal_type, entity_type, entity_id, metric, obs_date)
);
"""


def connect(db_path: Path | None = None, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(_SCHEMA_SQL)


def latest_observation_date(
    con: duckdb.DuckDBPyConnection, *, source: str = "portwatch"
) -> dt.date | None:
    row = con.execute(
        "SELECT max(obs_date) FROM observation WHERE source = ?", [source]
    ).fetchone()
    return row[0] if row and row[0] is not None else None
