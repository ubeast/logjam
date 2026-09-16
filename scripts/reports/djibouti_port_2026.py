#!/usr/bin/env python
"""Djibouti Port — the Horn of Africa's regional anchor (2026 brief).

Djibouti Port sits at the mouth of the Bab el-Mandeb, the strait the Horn of
Africa brief already showed collapsing under the 2023 Houthi campaign. That
brief's §5 made one observation in passing — Djibouti held while its Saudi
Red Sea neighbours lost a third to two-thirds of their container calls. This
brief goes further, on Djibouti's own merits: is it actually absorbing
diverted regional volume, how does it stack up against the other ports still
standing (Salalah, Mombasa, and the Saudi Red Sea coast), and does it have
room left to take more.

    uv run python scripts/reports/djibouti_port_2026.py

Output:
    reports/data/djibouti_port_2026.json
    reports/djibouti_port_2026.md
    reports/djibouti_port_2026.html

Needs a store backfilled to 2023 for a genuine pre-crisis baseline.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _brief import (  # noqa: E402
    Brief,
    CapacityChart,
    DataTable,
    DivergingChart,
    LineChart,
    MapChart,
    Section,
    Tile,
    connect,
    country_of,
    pct,
    pct_change,
    resolve,
    short_name,
    window_avg,
    write_all,
)
from _geo import basemap as geo_basemap  # noqa: E402
from _geo import map_point as geo_map_point  # noqa: E402

SLUG = "djibouti_port_2026"
FOCUS = "port294"  # Djibouti

# Same dual-window convention as the sibling briefs: PRECRISIS is the long,
# stable 2023 baseline used for the headline story (Djibouti's own trend was
# flat for two years before this brief's window even starts, same as the
# other chokepoints/ports), REROUTE_BASE is the immediate pre-window used for
# "who is gaining right now" so organic 2023-2025 growth at a competitor port
# doesn't get mistaken for diversion.
PRECRISIS = (dt.date(2023, 9, 1), dt.date(2023, 12, 1))
REROUTE_BASE = (dt.date(2025, 9, 1), dt.date(2026, 3, 1))
CURRENT = (dt.date(2026, 7, 1), dt.date(2026, 8, 1))
CURRENT_LABEL = "July 2026"

PEAK_SINCE = dt.date(2023, 1, 1)

QUARTERS: list[tuple[int, int]] = [
    (y, q) for y in (2023, 2024, 2025, 2026) for q in (1, 2, 3, 4)
][:15]
QUARTER_LABELS = [f"{y % 100} Q{q}" for y, q in QUARTERS]
ONSET_INDEX = 4  # 2024 Q1 - Red Sea / Houthi crisis, the regional context

# Regional competitor set: the other ports still absorbing Red Sea / Gulf of
# Aden traffic, per the Horn of Africa brief's own candidate list.
PORT_PATTERNS = [
    "%djibouti%", "%salalah%", "%mombasa%", "%jeddah%", "%king abdullah%",
    "%port sudan%",
]


def _q_bounds(y: int, q: int) -> tuple[dt.date, dt.date]:
    lo = dt.date(y, 3 * (q - 1) + 1, 1)
    hi = dt.date(y + 1, 1, 1) if q == 4 else dt.date(y, 3 * q + 1, 1)
    return lo, hi


def quarterly(con: Any, entity_id: str, metric: str) -> list[float | None]:
    return [window_avg(con, entity_id, metric, *_q_bounds(y, q)) for y, q in QUARTERS]


def peak_month(con: Any, entity_id: str, metric: str) -> tuple[float, str, float] | None:
    """Return (busiest monthly-avg value, its 'YYYY-MM', 95th-pct monthly-avg)."""
    rows = con.execute(
        """
        SELECT strftime(date_trunc('month', obs_date), '%Y-%m') AS mon, avg(value) AS v
        FROM observation
        WHERE entity_id = ? AND metric = ? AND obs_date >= ?
        GROUP BY 1 HAVING avg(value) IS NOT NULL ORDER BY v
        """,
        [entity_id, metric, PEAK_SINCE],
    ).fetchall()
    if len(rows) < 6:
        return None
    values = [v for _, v in rows]
    hi_val, hi_mon = max((v, m) for m, v in rows)
    p95 = values[max(0, round(0.95 * len(values)) - 1)]
    return round(hi_val, 2), hi_mon, round(p95, 2)


def build() -> tuple[Brief, dict[str, Any], list[tuple[str, str, str, str]]]:
    con = connect()

    cov = con.execute("SELECT min(obs_date), max(obs_date) FROM observation").fetchone()
    if cov[0] > dt.date(2023, 10, 1):
        sys.exit(f"store starts {cov[0]} — need pre-crisis 2023 data. Backfill first.")

    def ba(eid: str, metric: str) -> dict[str, float | None]:
        base = window_avg(con, eid, metric, *PRECRISIS)
        cur = window_avg(con, eid, metric, *CURRENT)
        return {"precrisis": base, "current": cur,
                "pct_of_normal": pct(cur, base), "pct_change": pct_change(cur, base)}

    dji = {m: ba(FOCUS, m) for m in
           ("portcalls_container", "portcalls", "import_container", "export_container")}
    dji["portcalls_container_quarterly"] = quarterly(con, FOCUS, "portcalls_container")
    dji["import_container_quarterly"] = quarterly(con, FOCUS, "import_container")
    dji["export_container_quarterly"] = quarterly(con, FOCUS, "export_container")

    # ---- regional competitor set (reroute-base convention) ----------------
    seen: set[str] = set()
    ports: list[dict[str, Any]] = []
    for pat in PORT_PATTERNS:
        hit = resolve(con, pat)
        if not hit or hit[0] in seen:
            continue
        seen.add(hit[0])
        eid, name, iso = hit
        a = window_avg(con, eid, "portcalls_container", *REROUTE_BASE)
        b = window_avg(con, eid, "portcalls_container", *CURRENT)
        if a is None or b is None or a < 0.25:
            continue
        ports.append({"entity_id": eid, "name": name, "iso3": iso,
                      "precrisis": a, "current": b, "pct_change": pct_change(b, a)})
    ports.sort(key=lambda p: p["pct_change"], reverse=True)

    sal = next((p for p in ports if p["name"] == "Salalah"), None)
    mom = next((p for p in ports if p["name"] == "Mombasa"), None)
    jed = next((p for p in ports if p["name"] == "Jeddah"), None)
    kap = next((p for p in ports if "Abdullah" in p["name"]), None)
    dji_recent = next((p for p in ports if p["name"] == "Djibouti"), None)

    # ---- can Djibouti (and its regional peers) absorb more? ---------------
    _MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    def _abbr_month(ym: str) -> str:
        y, m = ym.split("-")
        return f"{_MON[int(m) - 1]} {y}"

    absorption: list[dict[str, Any]] = []
    for p in ports:
        pk = peak_month(con, p["entity_id"], "portcalls_container")
        if pk is None:
            continue
        peak_val, peak_ym, p95 = pk
        cur = p["current"]
        pct_of_peak = round(100 * cur / peak_val, 1)
        pct_of_p95 = round(100 * cur / p95, 1)
        band = (
            "maxed" if pct_of_peak >= 95 else "tight" if pct_of_peak >= 75 else "headroom"
        )
        absorption.append({
            "entity_id": p["entity_id"], "name": short_name(p["name"]), "iso3": p["iso3"],
            "current": cur, "peak": peak_val, "peak_month": peak_ym,
            "peak_month_label": _abbr_month(peak_ym), "p95": p95,
            "pct_of_peak": pct_of_peak, "pct_of_p95": pct_of_p95, "band": band,
        })
    absorption.sort(key=lambda a: a["pct_of_peak"], reverse=True)
    dji_abs = next((a for a in absorption if a["name"] == "Djibouti"), None)
    sal_abs = next((a for a in absorption if a["name"] == "Salalah"), None)

    # ---- map ----------------------------------------------------------------
    BASEMAP = "redsea"
    _bmap = geo_basemap(BASEMAP)
    _LABEL_EXTRA = {"Djibouti": {"labelDy": 11.0}, "Jeddah": {"labelDy": 11.0}}
    map_points: list[dict[str, Any]] = []
    for p in ports:
        d = p["current"] - p["precrisis"]
        if abs(d) < 0.15:
            continue
        sn = short_name(p["name"])
        mp = geo_map_point(
            p["entity_id"], sn, d, p["pct_change"],
            role="gain" if d >= 0 else "loss", basemap_name=BASEMAP,
            country=country_of(con, p["entity_id"]), extra=_LABEL_EXTRA.get(sn),
        )
        if mp:
            map_points.append(mp)
    _map_size_max = max((abs(p["delta"]) for p in map_points), default=1.0)
    _map_labels = [short_name(p["name"]) for p in ports]

    payload = {
        "meta": {
            "generated": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "data_source": "IMF PortWatch (portwatch.imf.org)",
            "db_coverage": [str(cov[0]), str(cov[1])],
            "precrisis_window": [d.isoformat() for d in PRECRISIS],
            "reroute_base_window": [d.isoformat() for d in REROUTE_BASE],
            "current_window": [d.isoformat() for d in CURRENT],
            "quarters": QUARTER_LABELS,
        },
        "djibouti": dji,
        "regional_ports": ports,
        "absorption": {
            "metric": "portcalls_container",
            "ceiling_proxy": f"busiest calendar month since {PEAK_SINCE.isoformat()}",
            "rows": absorption,
        },
        "region_map": {
            "bbox": _bmap["bbox"],
            "points": map_points,
            "size_metric": (
                f"change in container port calls/day, {CURRENT_LABEL} vs the "
                "Sep 2025 - Feb 2026 window"
            ),
        },
    }

    d_calls = dji["portcalls_container"]
    d_tot = dji["portcalls"]
    d_imp = dji["import_container"]
    d_exp = dji["export_container"]
    _short = short_name

    sections = [
        Section(
            "1", "The finding",
            lede_md="Djibouti's container port calls are up "
            f"**{d_calls['pct_change']:+.0f}%** since the Bab el-Mandeb crisis began "
            "— a real, if modest, gain. But it has pushed the port close to the "
            "busiest level it has ever recorded, and the gain is not uniform: "
            "export volume has surged while import volume has fallen.",
            body_md=(
                f"IMF PortWatch counted **{d_calls['precrisis']:.1f} container port "
                f"calls per day** at Djibouti in the clean quarter before the "
                f"December 2023 Red Sea escalation; by {CURRENT_LABEL} that had risen "
                f"to **{d_calls['current']:.1f}** — **{d_calls['pct_of_normal']:.0f}% "
                f"of its pre-crisis level**. Total port calls across every vessel "
                f"class are essentially flat "
                f"({d_tot['precrisis']:.1f} → {d_tot['current']:.1f}/day), which "
                f"means the gain is specifically in container traffic, not a "
                f"general uptick.\n\n"
                f"The cargo-volume estimates tell a more mixed story than the call "
                f"count alone. Djibouti's estimated **container exports** are up "
                f"**{d_exp['pct_change']:+.0f}%** — more than double their "
                f"pre-crisis level — while estimated **container imports** are "
                f"**down {abs(d_imp['pct_change']):.0f}%**. A port doing more "
                f"consolidation and re-export work while its own import demand "
                f"softens is a different story than simple growth."
            ),
        ),
        Section(
            "2", "A modest, gradual step up — not a boom",
            body_md=(
                "Djibouti's container calls do not show a sharp jump at the "
                "December 2023 crisis onset the way the strait itself does. The "
                "port was already the region's busiest transshipment and "
                "consolidation hub before the crisis, and its call count has "
                "climbed gradually rather than snapping to a new level — "
                "consistent with a port absorbing overflow demand at the margin, "
                "not one suddenly rerouted onto."
            ),
            figure={
                "title": "Djibouti — container port calls per day",
                "sub": "Quarterly average, 2023 Q1 – 2026 Q3",
                "chart_id": "chart-djibouti-trend",
                "caption": "Source: IMF PortWatch, `Daily_Ports_Data`, port ID "
                "`port294`, field `portcalls_container`. Marker: December 2023 "
                "Red Sea / Houthi escalation (regional context, not a Djibouti-"
                "specific event).",
                "legend": [("Container port calls / day", "var(--s1)")],
            },
        ),
        Section(
            "3", "Calls up, but the cargo mix flipped",
            body_md=(
                f"Set import and export container volume side by side, indexed to "
                f"their own pre-crisis levels, and they diverge sharply. Exports "
                f"climb through the period and are now running at "
                f"**{d_exp['pct_of_normal']:.0f}% of pre-crisis**; imports slide "
                f"and sit at **{d_imp['pct_of_normal']:.0f}%**. Djibouti's own "
                f"trade volume (much of it landlocked Ethiopia's import corridor) "
                f"looks softer, even as the port handles more container calls "
                f"overall — consistent with more transshipment and consolidation "
                f"traffic passing through without being destined for Djibouti "
                f"itself."
            ),
            figure={
                "title": "Djibouti — container imports vs exports",
                "sub": "Indexed to the Sep–Nov 2023 average (= 100), quarterly",
                "chart_id": "chart-djibouti-mix",
                "caption": "Source: IMF PortWatch, `Daily_Ports_Data`, fields "
                "`import_container` / `export_container` — modelled trade-volume "
                "estimates, not manifest data.",
                "legend": [("Imports", "var(--s1)"), ("Exports", "var(--s2)")],
            },
            callout=(
                "Why this matters",
                "A rising call count with falling import volume is not the same "
                "finding as a port simply booming. It points to a shift in what "
                "kind of traffic Djibouti is handling, not just how much.",
            ),
        ),
        Section(
            "4", "Who else is holding in the region",
            body_md=(
                "Measured against the immediate pre-diversion window (not the "
                "2023 baseline, to avoid conflating pre-existing growth with the "
                "crisis), Djibouti's container calls are "
                + (f"**{dji_recent['pct_change']:+.0f}%**" if dji_recent
                   else "not separately measurable in this window")
                + ". **Salalah**, just outside the strait in Oman, is the "
                "region's biggest recent gainer at "
                + (f"**{sal['pct_change']:+.0f}%**" if sal else "—")
                + ". **Mombasa** is "
                + (f"down **{abs(mom['pct_change']):.0f}%**" if mom else "not material here")
                + ", and the **Saudi Red Sea coast** — Jeddah ("
                + (f"{jed['pct_change']:+.0f}%" if jed else "—")
                + ") and King Abdullah Port ("
                + (f"{kap['pct_change']:+.0f}%" if kap else "—")
                + ") — remains the deepest regional loss, even where the "
                "percentage change looks like a recovery: King Abdullah's recent "
                "window is measured off an already-collapsed base, not a return "
                "to its pre-crisis level."
            ),
            figure={
                "title": "Change in container port calls — recent window",
                "sub": "Percent change, Sep 2025 – Feb 2026 baseline vs July 2026",
                "chart_id": "chart-competitors",
                "caption": "Source: IMF PortWatch, `Daily_Ports_Data`, field "
                "`portcalls_container`. Baseline is the six months before this "
                "window (not 2023) so organic 2023-2025 growth at any one port "
                "isn't mistaken for diversion. Absolute rates (calls/day) at "
                "right — small ports swing large percentages off a low base.",
            },
            table=DataTable(
                caption="Regional container port calls — recent window vs July 2026",
                columns=["Port", "Baseline /day", "Jul 2026 /day", "Change"],
                rows=[
                    [_short(p["name"]), f"{p['precrisis']:.1f}", f"{p['current']:.1f}",
                     f"{p['pct_change']:+.0f}%"]
                    for p in ports
                ],
            ),
        ),
        Section(
            "5", "Near its own ceiling",
            lede_md="PortWatch publishes no berth or design capacity, so each "
            "port's own busiest month on record stands in as a floor estimate "
            "of its ceiling. On that test, the region's two steadiest ports are "
            "also its fullest.",
            body_md=(
                f"Djibouti's {CURRENT_LABEL} container calls sit at "
                f"**{dji_abs['pct_of_peak']:.0f}% of its own busiest month** on "
                f"record since {PEAK_SINCE.year} ({dji_abs['peak_month_label']}, "
                f"{dji_abs['peak']:.2f}/day) — effectively at the ceiling it has "
                f"ever demonstrated it can sustain. Salalah is nearly identical, "
                f"at **{sal_abs['pct_of_peak']:.0f}%** of its own record month, "
                f"if it has enough history to measure. The two ports carrying the "
                f"region's diverted container demand are both running close to "
                f"the busiest they have ever been.\n\n"
                "That is a meaningful headroom constraint: it does not mean "
                "Djibouti cannot handle more cargo at all — bigger ships, longer "
                "dwell, or new berths could still absorb volume that call counts "
                "don't capture — but on the metric PortWatch actually measures, "
                "there is little precedent for Djibouti running materially "
                "busier than it is right now."
            ),
            figure={
                "title": "How full are the regional ports?",
                "sub": "July 2026 container port calls as a share of each port's busiest month since 2023",
                "chart_id": "chart-absorption",
                "caption": "Source: IMF PortWatch, `Daily_Ports_Data`, "
                "`portcalls_container`. Bar = July 2026 daily average ÷ the "
                "port's highest monthly average since Jan 2023 (a floor estimate "
                "of its ceiling). Caret marks the 95th-percentile month. Bands: "
                "green below 75%, amber 75–95%, red 95%+. Port calls are not "
                "TEU or berth-hours.",
                "legend": [("Headroom (<75%)", "var(--good)"),
                           ("Tightening (75–95%)", "var(--warning)"),
                           ("At ceiling (95%+)", "var(--neg)")],
            },
        ),
        Section(
            "6", "The regional picture, mapped",
            body_md=(
                "Djibouti and Salalah hold as the regional anchors — both near "
                "their own historic ceilings (§5); the Saudi Red Sea ports remain "
                "the deepest losses, still well below their pre-crisis levels "
                "even where the recent-window percentage looks like a bounce."
            ),
            figure={
                "title": "The Horn of Africa region — who held, who gained",
                "sub": f"Change in container port calls/day, recent window vs {CURRENT_LABEL}",
                "chart_id": "chart-map",
                "caption": "Basemap: Natural Earth 10m (public domain). "
                "Coordinates: IMF PortWatch. Ports with a change too small to "
                "plot (<0.15 calls/day) are omitted here but appear in §4.",
            },
        ),
        Section(
            "7", "Assessment",
            body_md=(
                f"Djibouti has held its position as the Horn of Africa's regional "
                f"anchor port through the Bab el-Mandeb crisis and picked up a "
                f"modest, real gain in container calls "
                f"({d_calls['pct_of_normal']:.0f}% of pre-crisis) alongside a much "
                f"larger shift toward export/consolidation cargo. That gain has "
                f"consumed most of the port's demonstrated headroom: it is now "
                f"running near the busiest level it has ever recorded, alongside "
                f"Salalah, the only other regional port with a comparable story. "
                f"For a logistics planner, the takeaway is not that Djibouti is "
                f"an open safety valve for further Gulf of Aden diversion — it is "
                f"closer to full than any other port in this set.\n\n"
                "As with the other briefs in this series: PortWatch measures "
                "vessel movements and modelled cargo volume, not queue length, "
                "berth dwell, or cause. The December 2023 regional context and "
                "Djibouti's gradual gain are correlated in time; causation is not "
                "established here."
            ),
        ),
    ]

    charts = [
        LineChart(
            "chart-djibouti-trend", y_max=2.4, y_ticks=[0, 0.8, 1.6, 2.4],
            mark_index=ONSET_INDEX, mark_label="Red Sea crisis",
            series=[
                {"values": [v or 0 for v in dji["portcalls_container_quarterly"]],
                 "color": "var(--s1)", "label": "Container calls",
                 "tipLabel": "Container calls/day", "area": True},
            ],
        ),
        LineChart(
            "chart-djibouti-mix", y_max=280, y_ticks=[0, 100, 200], y_pct=True,
            ref_line=100, ref_label="pre-crisis", mark_index=ONSET_INDEX,
            mark_label="Red Sea crisis",
            series=[
                {"values": [round(100 * (v or 0) / d_imp["precrisis"], 0)
                            for v in dji["import_container_quarterly"]],
                 "color": "var(--s1)", "label": "Imports", "tipLabel": "Imports", "asPct": True},
                {"values": [round(100 * (v or 0) / d_exp["precrisis"], 0)
                            for v in dji["export_container_quarterly"]],
                 "color": "var(--s2)", "label": "Exports", "tipLabel": "Exports", "asPct": True},
            ],
        ),
        DivergingChart(
            "chart-competitors",
            rows=[{"name": _short(p["name"]), "country": p["iso3"],
                   "pct": int(p["pct_change"]),
                   "a": p["precrisis"], "b": p["current"]} for p in ports],
            max_abs=max(60, min(160, max(abs(p["pct_change"]) for p in ports) + 15)),
        ),
        CapacityChart(
            "chart-absorption",
            rows=[{"name": a["name"], "pct": a["pct_of_peak"], "mark": a["pct_of_p95"],
                   "band": a["band"],
                   "note": f"{a['current']:.1f} vs {a['peak']:.2f} peak/day"}
                  for a in absorption],
        ),
        MapChart(
            "chart-map",
            bbox=_bmap["bbox"], land=_bmap["land"], borders=_bmap["borders"],
            points=map_points, size_max=_map_size_max, size_unit="calls/day",
            size_legend=[1, 2, round(_map_size_max)] if _map_size_max >= 3 else [0.5, 1, 1.5],
            labels=_map_labels,
        ),
    ]

    table = DataTable(
        caption="Quarterly figures — Djibouti container port calls and cargo volume",
        columns=["Quarter", "Djibouti calls/day", "Djibouti exports (est.)",
                 "Djibouti imports (est.)", "Salalah calls/day"],
        rows=[
            [QUARTER_LABELS[i],
             f"{(dji['portcalls_container_quarterly'][i] or 0):.1f}",
             f"{(dji['export_container_quarterly'][i] or 0):,.0f}",
             f"{(dji['import_container_quarterly'][i] or 0):,.0f}",
             f"{(quarterly(con, sal['entity_id'], 'portcalls_container')[i] or 0):.2f}"
             if sal else "–"]
            for i in range(len(QUARTER_LABELS))
        ],
        break_row=ONSET_INDEX,
        crit_cols=[1, 2],
    )

    brief = Brief(
        slug=SLUG,
        title="Djibouti Port Watch",
        kicker="Supply-chain status brief",
        chokepoint_code="PORT WATCH",
        data_as_of=cov[1].strftime("%-d %b %Y"),
        generated=dt.date.today().strftime("%-d %b %Y"),
        verdict="Holding · Near Capacity",
        verdict_tone="warning",
        headline="Djibouti held through the Red Sea crisis — and is now running "
        "close to its own ceiling",
        dek="The Horn of Africa's steadiest port gained container calls and a "
        "lot more export volume since the Bab el-Mandeb crisis began, but the "
        "gain has used up most of its demonstrated headroom.",
        months=QUARTER_LABELS,
        tiles=[
            Tile("Container port calls", f"{d_calls['pct_of_normal']:.0f}", "% of normal",
                 f"{d_calls['current']:.1f}/day now vs {d_calls['precrisis']:.1f} pre-crisis"),
            Tile("Container exports (est.)", f"{d_exp['pct_of_normal']:.0f}", "% of normal",
                 "More than doubled — consolidation/re-export activity is up"),
            Tile("Container imports (est.)", f"{d_imp['pct_of_normal']:.0f}", "% of normal",
                 "Down, even as calls rose — a shift in cargo mix, not simple growth"),
            Tile("Own-peak utilization", f"{dji_abs['pct_of_peak']:.0f}", "% of record month",
                 "Running near the busiest level it has ever recorded", crit=True),
        ],
        sections=sections,
        charts=charts,
        table=table,
        method_dl=[
            ("Data source", "IMF PortWatch (portwatch.imf.org) — daily maritime "
             "activity estimated from satellite AIS via the UN Global Platform. Free "
             "public use with attribution. Backfill covers "
             f"1 Jan 2023 – {cov[1].strftime('%-d %b %Y')}."),
            ("What the numbers are", "`portcalls_container` is a count of "
             "container-ship port calls. `import_container` / `export_container` "
             "are PortWatch's modelled trade-volume estimates — directional, not "
             "measured TEU. Ports (unlike chokepoints) have no `capacity_container` "
             "field in this dataset, so this brief reads call counts and modelled "
             "volume, not aggregate vessel capacity."),
            ("Baseline", "The headline figures (§1-§3) use a fixed "
             "**September–November 2023** window, matching the sibling briefs. "
             "The regional competitor comparison, absorption read, and map "
             "(§4-§6) use the immediate pre-diversion window, **September 2025 – "
             "February 2026**, instead — several candidate ports grew or shrank "
             "on their own over 2023-2025, and a 2023 comparison would conflate "
             "that with the crisis response. Percent-of-normal = current value ÷ "
             "baseline mean."),
            ("“Current” month", f"**{CURRENT_LABEL}.** PortWatch revises its most "
             "recent ~2 weeks upward as satellite data lands, so August 2026 was "
             "still settling at generation time."),
            ("Regional context", "Djibouti sits at the mouth of the Bab el-Mandeb "
             "Strait, the subject of the companion `horn_of_africa_2026` brief. "
             "This brief does not re-derive the strait's own transit figures; it "
             "focuses on Djibouti and its regional competitor ports."),
            ("Absorption / capacity", "PortWatch publishes no berth or design "
             "capacity for ports, so each port's ceiling is proxied by its "
             "**busiest calendar month on record since January 2023** (highest "
             "monthly average of `portcalls_container`). This is a **floor "
             "estimate** of true capacity — a port that never reached its true "
             "limit in this window looks fuller than it is — and it counts "
             "vessel calls, not container volume or berth-hours; a port taking "
             "larger ships or running longer dwell could absorb more than its "
             "call count implies."),
            ("Map", "Basemap is Natural Earth 10m land and national boundary lines "
             "(public domain), clipped to the region (`redsea` window, shared "
             "with the Horn of Africa brief), simplified, and projected with Web "
             "Mercator in the browser — no map tiles, no network at render time. "
             "Port coordinates come from PortWatch's own port database."),
            ("Reproduce", "Clone github.com/ubeast/logjam, backfill the "
             "database to 2023, then `uv run python "
             "scripts/reports/djibouti_port_2026.py`. Full method in "
             "`docs/METHODOLOGY.md`."),
        ],
        limitations=[
            "PortWatch measures throughput (vessels moving), not queue length or "
            "berth dwell time. This brief cannot say how long individual ships "
            "waited, or how full they were.",
            "The data attests to the shipping outcome, not the cause. Djibouti's "
            "gradual gain coincides with the Bab el-Mandeb crisis; causation is "
            "not established here.",
            "Port-level `portcalls_container` does not distinguish transshipment "
            "or consolidation cargo from freight actually originating in or "
            "destined for Djibouti — the import/export divergence in §3 is "
            "suggestive, not a direct measurement of cargo purpose.",
            "Trade-volume fields (`import_container` / `export_container`) are "
            "model estimates, not manifest data.",
            "The regional competitor set only includes ports named in this "
            "script's candidate list; an unlisted beneficiary would be missed.",
            "The absorption read uses each port's busiest month since 2023 as a "
            "ceiling proxy — a floor estimate of true capacity — and counts "
            "vessel calls, not container volume; a port taking larger ships "
            "absorbs more than its call count implies.",
        ],
    )

    key_figures = [
        ("Djibouti container port calls / day", f"{d_calls['current']:.1f}",
         f"{d_calls['precrisis']:.1f}", f"{d_calls['pct_of_normal']:.0f} %"),
        ("Djibouti container exports / day (est.)", f"{d_exp['current']:,.0f}",
         f"{d_exp['precrisis']:,.0f}", f"{d_exp['pct_of_normal']:.0f} %"),
        ("Djibouti container imports / day (est.)", f"{d_imp['current']:,.0f}",
         f"{d_imp['precrisis']:,.0f}", f"{d_imp['pct_of_normal']:.0f} %"),
        ("Djibouti own-peak utilization", f"{dji_abs['pct_of_peak']:.0f} %",
         f"{dji_abs['peak']:.2f}/day peak", f"{dji_abs['band']}"),
    ]

    con.close()
    print(f"  Djibouti container calls: {d_calls['pct_of_normal']:.0f}% of normal | "
          f"exports {d_exp['pct_of_normal']:.0f}% | imports {d_imp['pct_of_normal']:.0f}% | "
          f"own-peak utilization {dji_abs['pct_of_peak']:.0f}%")
    return brief, payload, key_figures


def main() -> None:
    brief, payload, key_figures = build()
    write_all(brief, payload, key_figures)


if __name__ == "__main__":
    main()
