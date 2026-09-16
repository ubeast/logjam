#!/usr/bin/env python
"""Global chokepoint map — one map combining all four briefs' points (2026).

Not a new analysis. The Hormuz, Suez & Red Sea, Horn of Africa, and Djibouti
Port briefs each carry their own map, each measured against its own baseline
window. This script does not recompute anything - it reads those four
briefs' already-written payload JSON (``reports/data/*.json``), merges their
map points onto one shared basemap as a geographic index, and is explicit
that the plotted percentages are NOT on a common baseline and should not be
compared against each other across briefs. See each point's tooltip (source
brief + window) and section 2's method note below.

    uv run python scripts/reports/global_map_2026.py

Output:
    reports/data/global_map_2026.json
    reports/global_map_2026.md
    reports/global_map_2026.html

Requires the four source briefs to have been generated first (their JSON
payloads under reports/data/ are this script's only input - no database
access).
"""

from __future__ import annotations

import datetime as dt
import json
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

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "reports" / "data"
SLUG = "global_map_2026"
BASEMAP = "corridor"  # the widest of the three existing basemaps

# Which key each source brief's payload stores its map points under, its
# short display name, and the (source, window) label stamped onto every
# point so the merged map never implies a single common baseline.
SOURCES: list[tuple[str, str, str, str]] = [
    ("hormuz_container_2026", "diversion_map", "Hormuz brief", "Jul 2026 vs Sep 2025-Feb 2026"),
    ("suez_redsea_2026", "reroute_map", "Suez & Red Sea brief", "Jul 2026 vs Sep-Nov 2023"),
    ("horn_of_africa_2026", "region_map", "Horn of Africa brief", "Jul 2026 vs Sep-Nov 2023"),
    ("djibouti_port_2026", "region_map", "Djibouti Port brief", "Jul 2026 vs Sep 2025-Feb 2026"),
]
# Dedup priority when the same port appears in more than one brief's map -
# the most specific/most recent brief about that region wins. Applied
# uniformly (not judged port-by-port) so the rule is simple to state and
# reproduce.
PRIORITY = [
    "djibouti_port_2026",
    "horn_of_africa_2026",
    "suez_redsea_2026",
    "hormuz_container_2026",
]


def main() -> None:
    lo_lon, lo_lat, hi_lon, hi_lat = geo_basemap(BASEMAP)["bbox"]

    by_name: dict[str, list[dict[str, Any]]] = {}
    for slug, key, source_label, window_label in SOURCES:
        payload = json.loads((DATA_DIR / f"{slug}.json").read_text())
        for p in payload[key]["points"]:
            rec = dict(p)
            rec["_slug"] = slug
            rec["source"] = source_label
            rec["window"] = window_label
            by_name.setdefault(p["name"], []).append(rec)

    chosen: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    dup_count = 0
    for _name, entries in by_name.items():
        if len(entries) > 1:
            dup_count += 1
        entries.sort(key=lambda e: PRIORITY.index(e["_slug"]))
        p = entries[0]
        if geo_in_bbox(p["lon"], p["lat"], BASEMAP):
            chosen.append(p)
        else:
            dropped.append(p)

    if not (lo_lon <= chosen[0]["lon"] <= hi_lon):  # sanity: bbox unpacked correctly
        raise AssertionError("bbox sanity check failed")

    n_chokepoints = sum(1 for p in chosen if p["role"] == "chokepoint")
    n_ports = len(chosen) - n_chokepoints

    size_max = max((abs(p["delta"]) for p in chosen if p["role"] != "chokepoint"), default=1.0)
    top_movers = sorted(
        (p for p in chosen if p["role"] != "chokepoint"),
        key=lambda p: abs(p["delta"]),
        reverse=True,
    )[:8]
    labels = [p["name"] for p in top_movers] + [
        p["name"] for p in chosen if p["role"] == "chokepoint"
    ]

    _bmap = geo_basemap(BASEMAP)
    map_points = [
        {
            "name": p["name"],
            "lon": p["lon"],
            "lat": p["lat"],
            "delta": p["delta"],
            "pct": p.get("pct"),
            "role": p["role"],
            "country": p.get("country"),
            "source": p["source"],
            "window": p["window"],
        }
        for p in chosen
    ]

    table = DataTable(
        caption="Every point on this map",
        columns=["Chokepoint / Port", "Country", "Source brief", "Window"],
        rows=[
            [p["name"], p.get("country") or "—", p["source"], p["window"]]
            for p in sorted(chosen, key=lambda p: (p["role"] != "chokepoint", p["name"]))
        ],
    )

    dropped_txt = ", ".join(f"{p['name']} ({p['source']})" for p in dropped) if dropped else "none"

    brief = Brief(
        slug=SLUG,
        title="Global Chokepoint Map",
        kicker="Reference index",
        chokepoint_code="ALL CHOKEPOINTS",
        data_as_of=dt.date.today().strftime("%-d %b %Y"),
        generated=dt.date.today().strftime("%-d %b %Y"),
        verdict="Reference · Index",
        verdict_tone="good",
        headline="Every chokepoint and port from the four 2026 briefs, on one map",
        dek="A geographic index, not a new analysis: every point here comes "
        "from the Hormuz, Suez & Red Sea, Horn of Africa, and Djibouti Port "
        "briefs' own maps, merged onto one shared basemap. Each brief "
        "measures its ports against a different baseline window - see each "
        "point's tooltip, and §2 below, before comparing magnitudes "
        "across briefs.",
        months=[],
        tiles=[
            Tile(
                "Chokepoints mapped",
                str(n_chokepoints),
                "",
                "Strait of Hormuz, Suez Canal, Bab el-Mandeb",
            ),
            Tile("Ports mapped", str(n_ports), "", "Deduplicated across all four briefs' maps"),
            Tile(
                "Source briefs", "4", "", "Hormuz · Suez & Red Sea · Horn of Africa · Djibouti Port"
            ),
            Tile(
                "Out of frame",
                str(len(dropped)),
                "",
                dropped_txt if dropped else "Every plotted point fit this basemap",
            ),
        ],
        sections=[
            Section(
                "1",
                "Everything, in one frame",
                body_md=(
                    f"{len(chosen)} chokepoints and ports from the four briefs, "
                    f"deduplicated where the same port appeared on more than one "
                    f"brief's map ({dup_count} names collided; the most specific "
                    f"or most recent brief's version was kept - see §2) and "
                    f"drawn on the same basemap used by the Suez & Red Sea brief "
                    f"(the widest of the three basemaps this tool has built). "
                    f"Bubble color follows each point's own brief: green gained "
                    f"container traffic against its own baseline, red lost it. "
                    f"Bubble size is the absolute daily change, again by each "
                    f"point's own brief - not on a common scale across briefs."
                ),
                figure={
                    "title": "All four briefs, one map",
                    "sub": "Every chokepoint and port discussed across the 2026 disruption briefs",
                    "chart_id": "chart-global-map",
                    "caption": "Basemap: Natural Earth 10m (public domain), "
                    "the same 'corridor' window used by the Suez & Red Sea "
                    "brief. Hover any point for its source brief and "
                    "comparison window. "
                    + (
                        f"Out of this basemap's frame and not shown: {dropped_txt}."
                        if dropped
                        else "Nothing from the four briefs' maps fell outside this frame."
                    ),
                },
            ),
            Section(
                "2",
                "Why the numbers here are not one comparison",
                body_md=(
                    "The four briefs do not all measure “current vs. "
                    "baseline” the same way. The Suez & Red Sea and Horn "
                    "of Africa briefs compare July 2026 against a fixed "
                    "September-November 2023 pre-crisis window. The Hormuz "
                    "and Djibouti Port briefs instead compare July 2026 "
                    "against September 2025-February 2026, the immediate "
                    "pre-diversion period, because several of their candidate "
                    "ports grew for unrelated reasons between 2023 and 2025 "
                    "and a 2023 comparison would conflate that growth with "
                    "the diversion itself.\n\n"
                    "That means a point showing “+25%” from the "
                    "Djibouti Port brief and a point showing “+25%” "
                    "from the Suez & Red Sea brief are not the same kind of "
                    "twenty-five percent - they are measured from different "
                    "starting points. This map is a geographic index of what "
                    "the four briefs found, not a recomputed, unified "
                    "comparison. For the exact methodology and figures behind "
                    "any single point, read that point's own brief - named in "
                    "its tooltip and in the table at the end of this page."
                ),
            ),
        ],
        charts=[
            MapChart(
                "chart-global-map",
                bbox=_bmap["bbox"],
                land=_bmap["land"],
                borders=_bmap["borders"],
                points=map_points,
                size_max=size_max,
                size_unit="calls/day",
                size_legend=[1, 3, round(size_max)] if size_max >= 4 else [1, 2, 3],
                labels=labels,
            ),
        ],
        table=table,
        method_dl=[
            (
                "What this is",
                "A geographic index built from the already-"
                "published map data of four independently generated briefs "
                "(Hormuz, Suez & Red Sea, Horn of Africa, Djibouti Port), not a "
                "new database query or a recomputed comparison. Every figure "
                "traces back to one of those four briefs' own `reports/data/"
                "*.json` payload.",
            ),
            (
                "Baselines differ by brief",
                "The Suez & Red Sea and Horn of "
                "Africa briefs compare against a fixed September-November 2023 "
                "pre-crisis quarter. The Hormuz and Djibouti Port briefs "
                "compare against September 2025-February 2026 instead, for "
                "their reroute/competitor reads specifically. Do not compare "
                "percent-change magnitudes across points from different source "
                "briefs - compare only within one brief, or read the underlying "
                "brief for the full picture.",
            ),
            (
                "Deduplication",
                "When the same port appeared on more than one "
                "source brief's map, this script kept one version, by a fixed "
                "priority order (Djibouti Port brief, then Horn of Africa, then "
                "Suez & Red Sea, then Hormuz - the more specific or more recent "
                "brief about that port's region wins). The table above and each "
                "point's tooltip name which brief's version is shown.",
            ),
            (
                "Basemap",
                "The 'corridor' basemap (the same one the Suez & Red "
                "Sea brief uses) - the widest of the three basemaps this tool "
                "has built. A small number of points from the source briefs can "
                "fall outside its frame; any such point is listed in the "
                "'Out of frame' tile above and named in §1's figure "
                "caption, and is not silently dropped.",
            ),
            (
                "Reproduce",
                "Generate the four source briefs first (`uv run "
                "python scripts/reports/hormuz_container_2026.py`, "
                "`suez_redsea_2026.py`, `horn_of_africa_2026.py`, "
                "`djibouti_port_2026.py`), then `uv run python "
                "scripts/reports/global_map_2026.py`. Full method in "
                "`docs/METHODOLOGY.md`.",
            ),
        ],
        limitations=[
            "This is an index of the four briefs' own map data, not an "
            "independent analysis - any error or judgment call in a source "
            "brief (its baseline window, its port candidate list, its "
            "rounding) carries through to this map unchanged.",
            "Percent-change and absolute-change figures are not on a common "
            "baseline across source briefs; see §2. Do not read this "
            "map as a single ranked comparison of who gained or lost most.",
            f"Points outside the 'corridor' basemap's frame are omitted from "
            f"the map (though listed in the tiles/caption above), not "
            f"relocated or approximated: {dropped_txt}.",
            "Where the same port appeared in more than one source brief with "
            "different figures, only one version is shown here (see "
            "§2's deduplication note) - the other brief's figure for "
            "that same port may differ and is not shown.",
        ],
    )

    key_figures = [
        ("Chokepoints mapped", str(n_chokepoints), "—", "—"),
        ("Ports mapped", str(n_ports), "—", "—"),
        ("Source briefs merged", "4", "—", "—"),
    ]

    payload = {
        "meta": {
            "generated": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "data_source": "Derived from reports/data/{hormuz_container_2026,"
            "suez_redsea_2026,horn_of_africa_2026,djibouti_port_2026}.json",
            "basemap": BASEMAP,
        },
        "global_map": {
            "bbox": _bmap["bbox"],
            "points": map_points,
            "dropped": [
                {"name": p["name"], "lon": p["lon"], "lat": p["lat"], "source": p["source"]}
                for p in dropped
            ],
        },
    }

    write_all(brief, payload, key_figures)
    print(
        f"  Global map: {len(chosen)} points plotted "
        f"({n_chokepoints} chokepoints, {n_ports} ports), "
        f"{len(dropped)} dropped (out of frame), {dup_count} name collisions deduped"
    )


if __name__ == "__main__":
    main()
