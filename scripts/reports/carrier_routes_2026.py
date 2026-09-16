#!/usr/bin/env python
"""Carrier routes — real named container-service rotations on one map (2026).

Not a PortWatch analysis. This reads the small, hand-curated seed set of real
published carrier-service rotations in
``src/logjam/resources/carrier_routes.yaml`` (via
``logjam.analytics.carrier_routes``) and draws them as line overlays on the
same basemap the Suez & Red Sea brief uses, so a reader can see at a glance
which named services are direct calls between two ports and which are
multi-stop "bus stop" strings — the same lookup the `logjam carrier-route`
CLI command answers for a specific origin/destination pair.

    uv run python scripts/reports/carrier_routes_2026.py

Output:
    reports/data/carrier_routes_2026.json
    reports/carrier_routes_2026.md
    reports/carrier_routes_2026.html

No database access — this script's only input is
``src/logjam/resources/carrier_routes.yaml``.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _brief import (  # noqa: E402
    Brief,
    DataTable,
    MapChart,
    Section,
    Tile,
    write_all,
)
from _geo import basemap as geo_basemap  # noqa: E402
from _geo import in_bbox as geo_in_bbox  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from logjam.analytics.carrier_routes import load_ports, load_services  # noqa: E402

SLUG = "carrier_routes_2026"
BASEMAP = "corridor"  # the widest of the three existing basemaps

# One distinct colour per service, in load order. Fixed hex (not the shared
# --s1/--s2/--s3 theme tokens) because these reports render light-only and
# there are more routes here than the shared palette defines.
ROUTE_COLORS = [
    "#3987e5", "#d95926", "#46b892", "#8e44ad", "#c0392b",
    "#16a085", "#e67e22", "#2c3e50", "#f39c12",
]

# A straight line between two ports on this basemap can cut across land
# wherever the real sea route threads a strait or canal - a line drawn
# without waypoints, e.g. Piraeus straight to Jeddah, crosses Egypt/the
# Sinai instead of following the Suez Canal. Model the corridor as a chain
# of basins connected by named chokepoints, and route any leg that crosses
# a basin boundary through that chokepoint's real coordinates instead of
# drawing it direct. Basins not listed here (a port this table doesn't
# know) fall back to a direct line - better than crashing, and this is a
# small illustrative seed set, not a routing engine.
_BASIN_CHAIN = ["atlantic", "med", "red_sea", "gulf_aden_arabian", "persian_gulf"]
_PORT_BASIN: dict[str, str] = {
    "Tangier": "med", "Algeciras": "med", "Valencia": "med", "Barcelona": "med",
    "La Spezia": "med", "Genoa": "med", "Vado Ligure": "med", "Koper": "med",
    "Rijeka": "med", "Malta": "med", "Piraeus": "med", "Port Said": "med",
    "Damietta": "med", "Fos": "med",
    "Jeddah": "red_sea",
    "Djibouti": "gulf_aden_arabian", "Salalah": "gulf_aden_arabian",
    "Karachi": "gulf_aden_arabian", "Port Qasim": "gulf_aden_arabian",
    "Mundra": "gulf_aden_arabian", "Nhava Sheva": "gulf_aden_arabian",
    "Hazira": "gulf_aden_arabian", "Mangalore": "gulf_aden_arabian",
    "Colombo": "gulf_aden_arabian",
    "Jebel Ali": "persian_gulf", "Khalifa Port": "persian_gulf",
    "Umm Qasr": "persian_gulf", "Shuaiba": "persian_gulf", "Jubail": "persian_gulf",
}
# [lon, lat] waypoint(s) for the chokepoint BETWEEN chain positions (i, i+1),
# in low-to-high basin order - reversed automatically for the other direction.
_CHOKEPOINT_WAYPOINTS: list[list[list[float]]] = [
    [[-5.6, 35.95]],                          # atlantic <-> med: Strait of Gibraltar
    [[32.35, 31.26], [32.55, 29.93]],         # med <-> red_sea: Suez Canal (Port Said -> Suez)
    [[43.3, 12.6]],                           # red_sea <-> gulf_aden_arabian: Bab el-Mandeb
    [[56.25, 26.6]],                          # gulf_aden_arabian <-> persian_gulf: Strait of Hormuz
]


def _waypoints_between(port_a: str, port_b: str) -> list[list[float]]:
    """Chokepoint waypoints to insert sailing from `port_a` to `port_b`, in order."""
    basin_a, basin_b = _PORT_BASIN.get(port_a), _PORT_BASIN.get(port_b)
    if basin_a is None or basin_b is None or basin_a == basin_b:
        return []
    i_a, i_b = _BASIN_CHAIN.index(basin_a), _BASIN_CHAIN.index(basin_b)
    lo, hi = min(i_a, i_b), max(i_a, i_b)
    pts = [pt for boundary in range(lo, hi) for pt in _CHOKEPOINT_WAYPOINTS[boundary]]
    return pts if i_a < i_b else list(reversed(pts))


def main() -> None:
    ports = load_ports()
    services = load_services()
    _bmap = geo_basemap(BASEMAP)

    routes: list[dict[str, Any]] = []
    map_points: dict[str, dict[str, Any]] = {}
    port_service_count: dict[str, int] = {}
    dropped_ports: set[str] = set()

    for i, svc in enumerate(services):
        color = ROUTE_COLORS[i % len(ROUTE_COLORS)]
        legs: list[list[float]] = []
        prev_port: str | None = None
        for call in svc.calls:
            coord = ports.get(call.port)
            if coord is None:
                continue
            lon, lat = coord
            if not geo_in_bbox(lon, lat, BASEMAP):
                dropped_ports.add(call.port)
                continue
            if prev_port is not None:
                legs.extend(_waypoints_between(prev_port, call.port))
            legs.append([lon, lat])
            prev_port = call.port
            port_service_count[call.port] = port_service_count.get(call.port, 0) + 1
            if call.port not in map_points:
                point: dict[str, Any] = {
                    "name": call.port,
                    "lon": round(lon, 4),
                    "lat": round(lat, 4),
                    "delta": 0.0,
                    "pct": None,
                    "role": "waypoint",
                }
                # A right-extending label on a port near the frame's east edge
                # (e.g. Colombo) runs off the visible plot and gets clipped -
                # flip it to draw leftward, back into the frame, instead.
                lo_lon, _, hi_lon, _ = _bmap["bbox"]
                if lon > hi_lon - 0.15 * (hi_lon - lo_lon):
                    point["labelSide"] = "left"
                map_points[call.port] = point
        if len(legs) >= 2:
            routes.append({
                "name": f"{svc.carrier} {svc.service}",
                "color": color,
                "legs": legs,
            })

    # Per-service visible/total call counts for the table.
    service_rows: list[list[str]] = []
    for svc in services:
        total = len(svc.calls)
        visible = sum(1 for c in svc.calls if ports.get(c.port) and geo_in_bbox(*ports[c.port], BASEMAP))
        has_published = "yes (MEDEX-style matrix)" if svc.transit_days else "no — CLI shows an estimate"
        service_rows.append([
            svc.carrier, svc.service, svc.route_type,
            f"{visible}/{total} in frame", has_published,
        ])

    map_points.pop("__meta__", None)

    # Label hub ports (touched by 2+ services) plus a small set of ports this
    # tool's other briefs already discuss, for continuity across reports.
    always_label = {"Djibouti", "Jeddah", "Jebel Ali", "Karachi", "Colombo", "Port Said"}
    labels = [
        name for name in map_points
        if port_service_count.get(name, 0) >= 2 or name in always_label
    ]

    n_ports_plotted = len(map_points)
    n_routes_drawn = len(routes)
    dropped_txt = (
        ", ".join(sorted(dropped_ports)) if dropped_ports else "none"
    )

    brief = Brief(
        slug=SLUG,
        title="Carrier Routes",
        kicker="Reference · illustrative seed set",
        chokepoint_code="CARRIER SERVICES",
        data_as_of=dt.date.today().strftime("%-d %b %Y"),
        generated=dt.date.today().strftime("%-d %b %Y"),
        verdict="Reference · Illustrative",
        verdict_tone="good",
        headline="Direct calls vs. bus-stop strings: real carrier rotations on one map",
        dek=f"{len(services)} real, currently published named container "
        "services (Maersk's AE-series Asia-Europe network, CMA CGM's MEDEX "
        "and BIGEX 1) drawn as their own rotations — not an exhaustive model "
        "of global container shipping, a seed set to extend. For a specific "
        "origin/destination pair, `logjam carrier-route` answers the same "
        "question as a table: is there a direct service, and if not, how "
        "many stops.",
        months=[],
        tiles=[
            Tile("Services plotted", str(n_routes_drawn), "", f"of {len(services)} loaded"),
            Tile("Carriers", str(len({s.carrier for s in services})), "", "Maersk, CMA CGM"),
            Tile("Ports on this map", str(n_ports_plotted), "", "In this basemap's frame"),
            Tile(
                "Published transit times",
                str(sum(1 for s in services if s.transit_days)),
                "of " + str(len(services)) + " services",
                "Only CMA CGM MEDEX publishes a from/to matrix; the rest show "
                "a distance-based estimate, always labeled as such",
            ),
        ],
        sections=[
            Section(
                "1",
                "Nine real services, one frame",
                body_md=(
                    f"Every line is a real, currently published carrier "
                    f"rotation — not a simplified trade-lane arrow. "
                    f"{n_routes_drawn} of {len(services)} loaded services have "
                    f"at least two calls inside this basemap's frame and are "
                    f"drawn; the rest (Maersk's Asia-Europe strings, which "
                    f"spend most of their rotation in the Far East and North "
                    f"Europe) mostly fall outside it. Where a service's "
                    f"rotation leaves and re-enters this frame, the drawn "
                    f"line connects only its in-frame calls, in sailing "
                    f"order — it does not draw the great-circle path through "
                    f"the ports this basemap can't show."
                ),
                figure={
                    "title": "Carrier rotations",
                    "sub": "Real published named container services, Middle East / Red Sea / Indian Ocean frame",
                    "chart_id": "chart-carrier-routes",
                    "legend": [(r["name"], r["color"]) for r in routes],
                    "caption": "Basemap: Natural Earth 10m (public domain), "
                    "the same 'corridor' window used by the Suez & Red Sea "
                    "brief. Hover any port for the services calling there. "
                    f"Ports referenced by a loaded service but outside this "
                    f"basemap's frame, and so not shown: {dropped_txt}.",
                },
            ),
            Section(
                "2",
                "Direct call or bus stop? Ask a specific pair",
                body_md=(
                    "This map answers 'where do these services go'; it "
                    "doesn't rank them for a specific shipment. For that, "
                    "`logjam carrier-route \"<origin>\" \"<destination>\"` "
                    "finds every loaded service touching both ports, in that "
                    "sailing order, and reports whether it's a direct call or "
                    "how many stops sit between them, plus a real transit "
                    "time where the carrier publishes one (currently only "
                    "CMA CGM MEDEX) or a clearly labeled distance/speed "
                    "estimate otherwise. Example: `logjam carrier-route "
                    "\"Djibouti\" \"Piraeus\"`."
                ),
                table=DataTable(
                    caption="Every loaded service",
                    columns=["Carrier", "Service", "Route", "Calls plotted", "Real transit data"],
                    rows=service_rows,
                ),
            ),
        ],
        charts=[
            MapChart(
                "chart-carrier-routes",
                bbox=_bmap["bbox"],
                land=_bmap["land"],
                borders=_bmap["borders"],
                points=list(map_points.values()),
                labels=labels,
                routes=routes,
            ),
        ],
        table=DataTable(
            caption="Ports plotted and how many loaded services call there",
            columns=["Port", "Services calling here"],
            rows=[
                [name, str(port_service_count.get(name, 0))]
                for name in sorted(map_points, key=lambda n: -port_service_count.get(n, 0))
            ],
        ),
        method_dl=[
            (
                "What this is",
                "A small, hand-curated seed set of real named "
                "container-service rotations, fetched from carrier network "
                "publications (Maersk's own Asia-Europe network update page; "
                "CMA CGM's own MEDEX and BIGEX 1 service flyers) in "
                "September 2026 — not derived from PortWatch, not an "
                "exhaustive model of global container shipping. See "
                "`src/logjam/resources/carrier_routes.yaml` for each "
                "service's exact source and to add more.",
            ),
            (
                "Direct vs. stops",
                "Counted from each service's own published "
                "rotation order, walking forward from origin to destination, "
                "wrapping at most once around the loop (a real weekly string "
                "repeats). The reverse pair can match the same service with "
                "a different stop count — going the long way round costs "
                "more — so it is not assumed symmetric. A port a service "
                "reaches only 'in transshipment' (its vessel doesn't call "
                "there directly) doesn't count as a stop.",
            ),
            (
                "Real vs. estimated transit time",
                "Only CMA CGM's MEDEX service "
                "publishes a from/to transit-time matrix (its April 2026 "
                "flyer, non-contractual). Every other service here has no "
                "published transit time; both this report and the "
                "`carrier-route` CLI command show a distance/speed estimate "
                "instead (great-circle distance along the sailed path ÷ an "
                "assumed 18kn) and label it 'estimated', never blending it "
                "with a published figure.",
            ),
            (
                "Basemap",
                "The 'corridor' basemap (the same one the Suez & "
                "Red Sea brief uses) — the widest of the three basemaps this "
                "tool has built. Most of the Maersk Asia-Europe strings' "
                "Far East / North Europe calls fall outside its frame and "
                "aren't drawn; see §1.",
            ),
            (
                "Reproduce",
                "`uv run python "
                "scripts/reports/carrier_routes_2026.py`. Full method in "
                "`docs/METHODOLOGY.md`.",
            ),
        ],
        limitations=[
            "Nine services is a seed set illustrating the idea, not a "
            "survey of global container shipping — most carriers' most "
            "services aren't modeled here.",
            "Only CMA CGM MEDEX has a published transit-time matrix; every "
            "other transit time shown anywhere in this report or the CLI is "
            "a distance/speed estimate, and a rough one — it counts steaming "
            "time only and excludes port dwell, so it understates any real "
            "multi-stop transit.",
            "MEDEX's own published matrix is not required to arithmetically "
            "reconcile with the simplified single-pass rotation order used "
            "for stop-counting — CMA CGM's own flyer shows MEDEX as a "
            "pendulum string calling some ports more than once per loop, "
            "which the simplified order here doesn't reconstruct. See the "
            "comments in `carrier_routes.yaml`.",
            "Port coordinates are approximate port-city lookups, not "
            "PortWatch-sourced, and are not used anywhere else in this tool.",
            f"Ports outside the 'corridor' basemap's frame are not drawn: "
            f"{dropped_txt}.",
        ],
    )

    key_figures = [
        ("Services plotted", str(n_routes_drawn), "—", "—"),
        ("Ports on this map", str(n_ports_plotted), "—", "—"),
        (
            "Services with published transit times",
            str(sum(1 for s in services if s.transit_days)),
            "—",
            "—",
        ),
    ]

    payload = {
        "meta": {
            "generated": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "data_source": "src/logjam/resources/carrier_routes.yaml "
            "(carrier network publications, fetched Sep 2026)",
            "basemap": BASEMAP,
        },
        "services": [
            {
                "carrier": s.carrier,
                "service": s.service,
                "route_type": s.route_type,
                "source": s.source,
                "calls": [c.port for c in s.calls],
                "has_published_transit_times": bool(s.transit_days),
            }
            for s in services
        ],
        "carrier_map": {
            "bbox": _bmap["bbox"],
            "points": list(map_points.values()),
            "routes": routes,
            "dropped_ports": sorted(dropped_ports),
        },
    }

    write_all(brief, payload, key_figures)
    print(
        f"  Carrier routes: {n_routes_drawn}/{len(services)} services plotted, "
        f"{n_ports_plotted} ports, {len(dropped_ports)} ports out of frame"
    )


if __name__ == "__main__":
    main()
