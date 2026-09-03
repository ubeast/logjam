#!/usr/bin/env python
"""Build the static geographic assets the map figures in the briefs draw on.

The briefs are self-contained, offline-reproducible HTML -> PDF: no runtime
network calls, no slippy-map tiles. A map figure therefore needs its basemap
and its place coordinates baked into version-controlled files. This script
produces those files. Run it once (or when you want to refresh the basemap /
pick up new PortWatch ports); commit the output.

    uv run --with shapely --with httpx python scripts/reports/build_geo_assets.py

Outputs (committed, in ``src/logjam/resources/geo/``):
    basemap_mideast.json
        {bbox, land: <GeoJSON geometry>, borders: <GeoJSON geometry>, ...}
        Land polygons + national boundary lines for the Gulf / Arabian Sea /
        Red Sea / NW Indian Ocean window, clipped to `BBOX`, simplified, and
        rounded to 3 decimal degrees (~110 m) to keep the embedded payload
        small. Source: Natural Earth 10m (public domain). Used by the briefs.
    portwatch_places.json
        {ports: {portid: [lon, lat]}, chokepoints: {id: [lon, lat]}, ...}
        Every PortWatch port and chokepoint, from the PortWatch "*_database"
        metadata layers. ~2,065 ports. Used by the briefs' maps and by the
        AISStream adapter to place its geofence zones.

Neither `shapely` nor a network connection is needed to *run* a brief - only to
rebuild these assets, which is why shapely is not a project dependency.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import httpx

from logjam.config import settings

ASSETS_DIR = settings.geo_dir

# minlon, minlat, maxlon, maxlat. Frames the Hormuz reroute story: the Egyptian
# Mediterranean coast in the NW, the Gulf and the strait in the centre, and the
# Indian subcontinent's west coast in the E. Deliberately tight so the map
# renders large without a lot of empty ocean.
BBOX: tuple[float, float, float, float] = (31.0, 8.0, 78.0, 32.0)

# Pinned Natural Earth release so a rebuild is deterministic.
_NE_TAG = "v5.1.2"
_NE_BASE = f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{_NE_TAG}/geojson"
_NE_LAND = f"{_NE_BASE}/ne_10m_land.geojson"
_NE_BORDERS = f"{_NE_BASE}/ne_10m_admin_0_boundary_lines_land.geojson"

_SIMPLIFY_TOLERANCE_DEG = 0.02  # ~2 km; the map renders at ~16 px/degree, so sub-pixel
_COORD_DECIMALS = 3

_PW_SERVICES = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services"
_PW_PORTS_DB = f"{_PW_SERVICES}/PortWatch_ports_database/FeatureServer/0/query"
_PW_CHOKES_DB = f"{_PW_SERVICES}/PortWatch_chokepoints_database/FeatureServer/0/query"

_HTTP_TIMEOUT_S = 90.0


def _round_coords(obj: Any) -> Any:
    """Recursively round every float in a nested list/dict to `_COORD_DECIMALS`."""
    if isinstance(obj, float):
        return round(obj, _COORD_DECIMALS)
    if isinstance(obj, list):
        return [_round_coords(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _round_coords(v) for k, v in obj.items()}
    return obj


def _clip_and_simplify(geojson: dict[str, Any]) -> dict[str, Any]:
    """Clip a GeoJSON FeatureCollection to `BBOX`, union, simplify, round."""
    from shapely.geometry import box, mapping, shape  # noqa: PLC0415 - build-only dep
    from shapely.ops import unary_union  # noqa: PLC0415

    clip = box(*BBOX)
    pieces = []
    for feat in geojson["features"]:
        geom = shape(feat["geometry"])
        if geom.intersects(clip):
            pieces.append(geom.intersection(clip))
    merged = unary_union(pieces).simplify(
        _SIMPLIFY_TOLERANCE_DEG, preserve_topology=True
    )
    return _round_coords(mapping(merged))


def _fetch_json(client: httpx.Client, url: str) -> dict[str, Any]:
    resp = client.get(url)
    resp.raise_for_status()
    return resp.json()


def _fetch_places(client: httpx.Client, url: str) -> dict[str, list[Any]]:
    """Return {portid: [lon, lat, name]} for a PortWatch "*_database" layer.

    These layers carry `lat` / `lon` / `portname` attribute columns, so no
    geometry parsing is needed. They are small (chokepoints: 28 rows; ports:
    ~2,065) but the ports layer exceeds one page, so we follow `resultOffset`.
    The name is kept so the AIS adapter can resolve a port by name without the
    database.
    """
    out: dict[str, list[Any]] = {}
    offset = 0
    page = 2000
    while True:
        payload = _fetch_json(
            client,
            f"{url}?where=1%3D1&outFields=portid,portname,lat,lon&returnGeometry=false"
            f"&resultOffset={offset}&resultRecordCount={page}&f=json",
        )
        feats = payload.get("features", [])
        for feat in feats:
            a = feat["attributes"]
            if a.get("lat") is None or a.get("lon") is None:
                continue
            out[a["portid"]] = [
                round(float(a["lon"]), 5),
                round(float(a["lat"]), 5),
                a.get("portname") or "",
            ]
        if len(feats) < page and not payload.get("exceededTransferLimit"):
            break
        offset += len(feats)
        if not feats:
            break
    return out


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().isoformat()

    with httpx.Client(timeout=_HTTP_TIMEOUT_S, follow_redirects=True) as client:
        print(f"Natural Earth {_NE_TAG}: land + boundary lines ...")
        land = _clip_and_simplify(_fetch_json(client, _NE_LAND))
        borders = _clip_and_simplify(_fetch_json(client, _NE_BORDERS))

        basemap = {
            "_source": (
                f"Natural Earth 10m ({_NE_TAG}), public domain, via "
                "github.com/nvkelso/natural-earth-vector"
            ),
            "_built": stamp,
            "_note": (
                f"Clipped to bbox {BBOX}, unioned, simplified "
                f"{_SIMPLIFY_TOLERANCE_DEG} deg, coords rounded to "
                f"{_COORD_DECIMALS} dp. Rebuild with scripts/reports/build_geo_assets.py."
            ),
            "bbox": list(BBOX),
            "land": land,
            "borders": borders,
        }
        basemap_path = ASSETS_DIR / "basemap_mideast.json"
        basemap_path.write_text(json.dumps(basemap, separators=(",", ":")))
        print(f"  wrote {basemap_path.name}  ({basemap_path.stat().st_size // 1024} KB)")

        print("PortWatch metadata layers: port + chokepoint coordinates ...")
        ports = _fetch_places(client, _PW_PORTS_DB)
        chokes = _fetch_places(client, _PW_CHOKES_DB)

    places = {
        "_source": (
            "IMF PortWatch (portwatch.imf.org) - PortWatch_ports_database / "
            "PortWatch_chokepoints_database metadata layers"
        ),
        "_fetched": stamp,
        "ports": dict(sorted(ports.items())),
        "chokepoints": dict(sorted(chokes.items())),
    }
    places_path = ASSETS_DIR / "portwatch_places.json"
    places_path.write_text(json.dumps(places, separators=(",", ":"), indent=0))
    print(
        f"  wrote {places_path.name}  ({len(ports)} ports, {len(chokes)} chokepoints, "
        f"{places_path.stat().st_size // 1024} KB)"
    )


if __name__ == "__main__":
    main()
