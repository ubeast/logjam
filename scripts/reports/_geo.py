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

_PLACES_PATH = settings.geo_dir / "portwatch_places.json"


@lru_cache(maxsize=4)
def basemap(name: str = "mideast") -> dict[str, Any]:
    """Clipped land + border geometry and its bbox for the named window.

    ``name`` matches a ``basemap_<name>.json`` file: ``mideast`` (Hormuz brief),
    ``corridor`` (Suez brief - the Asia-Europe maritime corridor), or ``redsea``
    (Horn brief - Suez to the Gulf of Aden and the East African coast).
    """
    return json.loads((settings.geo_dir / f"basemap_{name}.json").read_text())


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


def in_bbox(lon: float, lat: float, name: str = "mideast") -> bool:
    lo_lon, lo_lat, hi_lon, hi_lat = basemap(name)["bbox"]
    return lo_lon <= lon <= hi_lon and lo_lat <= lat <= hi_lat


def map_point(
    entity_id: str,
    name: str,
    delta: float,
    pct: float | None,
    *,
    role: str,
    basemap_name: str = "mideast",
    country: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build one ``MapChart`` point, or ``None`` if the place is unknown / off-map.

    ``role`` is ``"gain"`` | ``"loss"`` | ``"chokepoint"``; ``delta`` sizes the
    bubble, ``pct`` fills the tooltip (``None`` renders as "n/a", not 0%).
    ``country`` is dropped for a chokepoint (a strait is in no single country).
    ``extra`` merges in extra keys (e.g. label placement).
    """
    loc = coord(entity_id)
    if loc is None:
        return None
    lon, lat = loc
    if not in_bbox(lon, lat, basemap_name):
        return None
    point: dict[str, Any] = {
        "name": name,
        "lon": round(lon, 4),
        "lat": round(lat, 4),
        "delta": round(delta, 1),
        "pct": round(pct, 0) if pct is not None else None,
        "role": role,
    }
    if country and role != "chokepoint":
        point["country"] = country
    if extra:
        point.update(extra)
    return point
