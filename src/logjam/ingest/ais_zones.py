"""Geofence zones for the AISStream adapter.

Turns ``resources/ais_zones.yaml`` plus the PortWatch coordinate table
(``resources/geo/portwatch_places.json``) into:

* :func:`subscription_boxes` - the wide bounding boxes the WebSocket asks for.
* :func:`load_zones` - a :class:`Zone` per watched port (a circular anchorage
  catchment) and per PortWatch chokepoint (a small square around its centre).
* :meth:`Zone.contains` - point-in-zone test for the reducer.

No database and no network: everything comes from the two committed files.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml

from logjam.config import settings

_EARTH_RADIUS_KM = 6371.0088


@lru_cache(maxsize=1)
def _places() -> dict[str, dict[str, list[Any]]]:
    """{'ports': {portid: [lon, lat, name]}, 'chokepoints': {id: [lon, lat, name]}}."""
    data = json.loads((settings.geo_dir / "portwatch_places.json").read_text())
    return {"ports": data["ports"], "chokepoints": data["chokepoints"]}


@lru_cache(maxsize=1)
def _zone_config() -> dict[str, Any]:
    data = yaml.safe_load(settings.ais_zones_path.read_text())
    assert isinstance(data, dict)
    return data


@dataclass(frozen=True)
class Zone:
    """A named catchment. ``radius_km`` set -> circle; else -> square box."""

    entity_type: str          # 'port' | 'chokepoint'
    entity_id: str            # PortWatch id, e.g. 'port744' / 'chokepoint6'
    entity_name: str
    lat: float
    lon: float
    radius_km: float | None = None
    half_deg: float | None = None

    def contains(self, lat: float, lon: float) -> bool:
        if self.radius_km is not None:
            return _haversine_km(self.lat, self.lon, lat, lon) <= self.radius_km
        hd = self.half_deg or 0.0
        return abs(lat - self.lat) <= hd and abs(lon - self.lon) <= hd


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def subscription_boxes() -> list[list[list[float]]]:
    """AISStream ``BoundingBoxes``: a list of ``[[min_lat, min_lon], [max_lat, max_lon]]``."""
    return [list(map(list, r["bbox"])) for r in _zone_config()["regions"]]


def _in_any_region(lat: float, lon: float) -> bool:
    for (lo_lat, lo_lon), (hi_lat, hi_lon) in (r["bbox"] for r in _zone_config()["regions"]):
        if lo_lat <= lat <= hi_lat and lo_lon <= lon <= hi_lon:
            return True
    return False


def _resolve_port(name_like: str) -> tuple[str, str, float, float] | None:
    """First PortWatch port whose name contains ``name_like`` (case-insensitive)."""
    needle = name_like.lower()
    for pid, (lon, lat, name) in _places()["ports"].items():
        if needle in str(name).lower():
            return pid, str(name), float(lat), float(lon)
    return None


@lru_cache(maxsize=1)
def load_zones() -> tuple[Zone, ...]:
    """Every zone the reducer scores: watched-port circles + chokepoint boxes.

    Ports named in the YAML that cannot be resolved, or that fall outside every
    subscription region (so no AIS would ever reach them), are dropped.
    """
    cfg = _zone_config()
    radius_km = float(cfg["port_radius_km"])
    half_deg = float(cfg["chokepoint_half_deg"])
    zones: list[Zone] = []
    seen: set[str] = set()

    for name_like in cfg.get("ports", []):
        hit = _resolve_port(name_like)
        if hit is None:
            continue
        pid, name, lat, lon = hit
        if pid in seen or not _in_any_region(lat, lon):
            continue
        seen.add(pid)
        zones.append(Zone("port", pid, name, lat, lon, radius_km=radius_km))

    for cid, (lon, lat, name) in _places()["chokepoints"].items():
        if _in_any_region(float(lat), float(lon)):
            zones.append(
                Zone("chokepoint", cid, str(name), float(lat), float(lon), half_deg=half_deg)
            )

    return tuple(zones)
