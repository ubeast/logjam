"""Ingestion adapters.

Each adapter is responsible for one external source and exposes a single
``fetch_*`` function that returns a tidy :class:`pandas.DataFrame` in the
long format the store expects:

    entity_type | entity_id | entity_name | country | iso3 | date | metric | value

Adding a new source (Freightos, GDELT, ...) means adding a module here that
produces that same shape - nothing downstream needs to change.

The AISStream adapter is the exception to the "one ``fetch_*`` function" rule:
AIS is a push WebSocket, so it is a two-step *sample then reduce* flow -
:func:`logjam.ingest.aisstream.sample` captures raw messages and
:func:`logjam.analytics.ais_reduce.reduce_pending` turns them into
the tidy long frame.
"""

from logjam.ingest.aisstream import sample as sample_ais
from logjam.ingest.portwatch import fetch_portwatch

__all__ = ["fetch_portwatch", "sample_ais"]
