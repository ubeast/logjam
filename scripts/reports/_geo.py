"""Load the static geographic assets built by ``build_geo_assets.py``.

Kept separate from :mod:`_brief` because only the briefs that carry a map figure
need it. The assets are version-controlled JSON (see ``assets/geo/``); this
module just reads them and offers small lookups. No network, no shapely.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from logjam.config import settings

_BASEMAP_PATH = settings.geo_dir / "basemap_mideast.json"
_PLACES_PATH = settings.geo_dir / "portwatch_places.json"


@lru_cache(maxsize=1)
def basemap() -> dict[str, Any]:
    """The clipped land + border geometry and its bbox (minlon, minlat, maxlon, maxlat)."""
    return json.loads(_BASEMAP_PATH.read_text())


@lru_cache(maxsize=1)
def _places() -> dict[str, Any]:
    return json.loads(_PLACES_PATH.read_text())


def coord(entity_id: str) -> tuple[float, float] | None:
    """Return (lon, lat) for a PortWatch port or chokepoint id, or None if unknown."""
    p = _places()
    for bucket in ("ports", "chokepoints"):
        if entity_id in p[bucket]:
            lon, lat = p[bucket][entity_id][:2]
            return float(lon), float(lat)
    return None


def in_bbox(lon: float, lat: float) -> bool:
    lo_lon, lo_lat, hi_lon, hi_lat = basemap()["bbox"]
    return lo_lon <= lon <= hi_lon and lo_lat <= lat <= hi_lat
