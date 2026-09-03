"""DuckDB analytical store.

One embedded file (``data/logjam.duckdb`` by default). DuckDB is a good fit
here: the workload is read-heavy analytical aggregation over a few million rows,
there is no concurrent-writer requirement, and it needs zero server setup.
Swap to Postgres/Timescale only if/when live AIS ingestion makes this
write-hot.
"""

from logjam.store.db import connect, init_schema, latest_observation_date
from logjam.store.loaders import upsert_observations

__all__ = [
    "connect",
    "init_schema",
    "latest_observation_date",
    "upsert_observations",
]
