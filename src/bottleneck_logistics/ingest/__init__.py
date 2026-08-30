"""Ingestion adapters.

Each adapter is responsible for one external source and exposes a single
``fetch_*`` function that returns a tidy :class:`pandas.DataFrame` in the
long format the store expects:

    entity_type | entity_id | entity_name | country | iso3 | date | metric | value

Adding a new source (AISStream, Freightos, GDELT, ...) means adding a module
here that produces that same shape - nothing downstream needs to change.
"""

from bottleneck_logistics.ingest.portwatch import fetch_portwatch

__all__ = ["fetch_portwatch"]
