"""Minimal ArcGIS FeatureServer query client.

PortWatch publishes its data as hosted ArcGIS feature layers. A single query
response is capped by the server (``maxRecordCount``), so anything beyond the
first page must be retrieved with ``resultOffset`` paging. This module hides
that loop.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from bottleneck_logistics.config import settings


def query_all(
    url: str,
    *,
    where: str = "1=1",
    out_fields: str = "*",
    order_by: str = "date ASC",
    page_size: int | None = None,
    timeout_s: float | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield attribute dicts for every feature matching ``where``.

    Paging stops when the server returns fewer rows than requested and no
    ``exceededTransferLimit`` flag - the standard ArcGIS end-of-data signal.

    Raises:
        httpx.HTTPStatusError: on any non-2xx response.
        RuntimeError: if the server returns an ``error`` payload (ArcGIS returns
            HTTP 200 with an error body for bad queries).
    """
    page_size = page_size or settings.arcgis_page_size
    timeout_s = timeout_s or settings.http_timeout_s
    offset = 0

    # PortWatch's layer has maxRecordCount=1000 but advertises
    # supportsMaxRecordCountFactor, so factor * 1000 rows come back per request.
    # Keep page_size == maxRecordCount * factor so paging math stays correct.
    factor = max(1, round(page_size / 1000))

    with httpx.Client(timeout=timeout_s) as client:
        while True:
            params = {
                "where": where,
                "outFields": out_fields,
                "orderByFields": order_by,
                "resultOffset": offset,
                "resultRecordCount": page_size,
                "maxRecordCountFactor": factor,
                "returnGeometry": "false",
                "f": "json",
            }
            resp = client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()

            if "error" in payload:
                raise RuntimeError(f"ArcGIS error from {url}: {payload['error']}")

            features = payload.get("features", [])
            for feat in features:
                yield feat["attributes"]

            if len(features) < page_size and not payload.get("exceededTransferLimit"):
                return
            offset += len(features)
            if not features:  # defensive: avoid an infinite loop on odd servers
                return
