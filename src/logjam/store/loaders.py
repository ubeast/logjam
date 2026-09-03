"""Idempotent loaders: take a tidy DataFrame, upsert into ``observation``."""

from __future__ import annotations

import duckdb
import pandas as pd

from logjam.ingest.portwatch import TIDY_COLUMNS

_REQUIRED = set(TIDY_COLUMNS)


def upsert_observations(
    con: duckdb.DuckDBPyConnection,
    tidy: pd.DataFrame,
    *,
    source: str = "portwatch",
) -> int:
    """Insert or replace observation rows. Returns the number of rows written.

    PortWatch revises recent estimates, so re-ingesting an overlapping window
    must overwrite, not duplicate - hence DELETE-then-INSERT on the natural key
    rather than a plain append.
    """
    missing = _REQUIRED - set(tidy.columns)
    if missing:
        raise ValueError(f"tidy frame missing columns: {sorted(missing)}")
    if tidy.empty:
        return 0

    staged = tidy[TIDY_COLUMNS].copy()
    staged["source"] = source
    staged = staged.rename(columns={"date": "obs_date"})

    con.register("staged_obs", staged)
    try:
        con.execute("BEGIN TRANSACTION")
        con.execute(
            """
            DELETE FROM observation o
            USING staged_obs s
            WHERE o.entity_type = s.entity_type
              AND o.entity_id   = s.entity_id
              AND o.obs_date    = s.obs_date
              AND o.metric      = s.metric
              AND o.source      = s.source
            """
        )
        con.execute(
            """
            INSERT INTO observation
                (entity_type, entity_id, entity_name, country, iso3,
                 obs_date, metric, value, source)
            SELECT entity_type, entity_id, entity_name, country, iso3,
                   obs_date, metric, value, source
            FROM staged_obs
            """
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("staged_obs")

    return len(staged)
