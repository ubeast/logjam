#!/usr/bin/env python
"""Horn of Africa / Bab el-Mandeb Strait — the southern Red Sea gate (2026 brief).

The Bab el-Mandeb Strait, between Yemen and Djibouti, is the southern entrance
to the Red Sea and the chokepoint the Houthi campaign actually targets. This
brief reads the PortWatch data for the strait (``chokepoint 4``) two and a half
years in, checks a possible fresh deterioration in mid-2026, and traces the
effect on regional ports — Djibouti, Salalah, and the Saudi Red Sea coast.

    uv run python scripts/reports/horn_of_africa_2026.py

Output:
    reports/data/horn_of_africa_2026.json
    reports/horn_of_africa_2026.md
    reports/horn_of_africa_2026.html

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
    DataTable,
    DivergingChart,
    LineChart,
    MapChart,
    Section,
    Tile,
    connect,
    country_of,
    month_keys,
    month_labels,
    monthly,
    pct,
    pct_change,
    resolve,
    short_name,
    window_avg,
    write_all,
)
from _geo import basemap as geo_basemap  # noqa: E402
from _geo import map_point as geo_map_point  # noqa: E402

SLUG = "horn_of_africa_2026"
BAB = "chokepoint4"
CAPE = "chokepoint7"

PRECRISIS = (dt.date(2023, 9, 1), dt.date(2023, 12, 1))
CURRENT = (dt.date(2026, 7, 1), dt.date(2026, 8, 1))
CURRENT_LABEL = "July 2026"

QUARTERS: list[tuple[int, int]] = [
    (y, q) for y in (2023, 2024, 2025, 2026) for q in (1, 2, 3, 4)
][:15]
QUARTER_LABELS = [f"{y % 100} Q{q}" for y, q in QUARTERS]
ONSET_INDEX = 4  # 2024 Q1

# 15-month detail axis for the 2026 watch chart: Jun 2025 .. Aug 2026.
DETAIL_START = dt.date(2025, 6, 1)
DETAIL_N = 15
DETAIL_LABELS = month_labels(DETAIL_START, DETAIL_N)
DETAIL_KEYS = month_keys(DETAIL_START, DETAIL_N)
HORMUZ_INDEX = DETAIL_KEYS.index("2026-03")  # Hormuz-crisis onset, for the marker


def _q_bounds(y: int, q: int) -> tuple[dt.date, dt.date]:
    lo = dt.date(y, 3 * (q - 1) + 1, 1)
    hi = dt.date(y + 1, 1, 1) if q == 4 else dt.date(y, 3 * q + 1, 1)
    return lo, hi


def quarterly(con: Any, entity_id: str, metric: str) -> list[float | None]:
    return [window_avg(con, entity_id, metric, *_q_bounds(y, q)) for y, q in QUARTERS]


def detail_series(con: Any, entity_id: str, metric: str) -> list[float]:
    m = monthly(con, entity_id, metric, DETAIL_START)
    return [m.get(k, 0.0) for k in DETAIL_KEYS]


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

    bab = {m: ba(BAB, m) for m in ("n_total", "n_container", "n_tanker", "n_dry_bulk",
                                   "capacity_container", "capacity_total")}
    bab["n_total_quarterly"] = quarterly(con, BAB, "n_total")
    bab["n_container_quarterly"] = quarterly(con, BAB, "n_container")
    bab["n_total_detail"] = detail_series(con, BAB, "n_total")
    bab["n_tanker_detail"] = detail_series(con, BAB, "n_tanker")
    cape = {m: ba(CAPE, m) for m in ("n_total", "n_container")}

    # ---- regional ports --------------------------------------------------
    port_patterns = [
        "%djibouti%", "%salalah%", "%jeddah%", "%king abdullah%", "%aqaba%",
        "%port sudan%", "%berbera%", "%mombasa%", "%dar es salaam%", "%aden%",
    ]
    seen: set[str] = set()
    ports: list[dict[str, Any]] = []
    for pat in port_patterns:
        hit = resolve(con, pat)
        if not hit or hit[0] in seen:
            continue
        seen.add(hit[0])
        eid, name, iso = hit
        a = window_avg(con, eid, "portcalls_container", *PRECRISIS)
        b = window_avg(con, eid, "portcalls_container", *CURRENT)
        if a is None or b is None or a < 0.25:
            continue
        ports.append({"entity_id": eid, "name": name, "iso3": iso,
                      "precrisis": a, "current": b, "pct_change": pct_change(b, a)})
    ports.sort(key=lambda p: p["pct_change"], reverse=True)

    dji = next((p for p in ports if p["name"] == "Djibouti"), None)
    sal = next((p for p in ports if p["name"] == "Salalah"), None)
    jed = next((p for p in ports if p["name"] == "Jeddah"), None)
    kap = next((p for p in ports if "Abdullah" in p["name"]), None)

    # ---- map: the Bab el-Mandeb region, who held and who lost ------------
    BASEMAP = "redsea"
    _bmap = geo_basemap(BASEMAP)
    # Nudge the labels of ports that sit almost on top of a neighbour.
    _LABEL_EXTRA = {"Djibouti": {"labelDy": 11.0}, "Jeddah": {"labelDy": 11.0}}
    map_points: list[dict[str, Any]] = []
    for p in ports:
        d = p["current"] - p["precrisis"]
        if abs(d) < 0.25:
            continue
        sn = short_name(p["name"])
        mp = geo_map_point(
            p["entity_id"], sn, d, p["pct_change"],
            role="gain" if d >= 0 else "loss", basemap_name=BASEMAP,
            country=country_of(con, p["entity_id"]), extra=_LABEL_EXTRA.get(sn),
        )
        if mp:
            map_points.append(mp)
    mp = geo_map_point(
        BAB, "Bab el-Mandeb", 0.0, bab["n_container"]["pct_change"],
        role="chokepoint", basemap_name=BASEMAP,
    )
    if mp:
        map_points.append(mp)
    _map_size_max = max(
        (abs(p["delta"]) for p in map_points if p["role"] != "chokepoint"), default=1.0
    )
    _map_labels = [short_name(p["name"]) for p in ports] + ["Bab el-Mandeb"]

    payload = {
        "meta": {
            "generated": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "data_source": "IMF PortWatch (portwatch.imf.org)",
            "db_coverage": [str(cov[0]), str(cov[1])],
            "precrisis_window": [d.isoformat() for d in PRECRISIS],
            "current_window": [d.isoformat() for d in CURRENT],
            "quarters": QUARTER_LABELS,
            "detail_months": DETAIL_LABELS,
        },
        "bab_el_mandeb": bab,
        "cape_of_good_hope": cape,
        "ports": ports,
        "region_map": {
            "bbox": _bmap["bbox"],
            "points": map_points,
            "size_metric": (
                f"change in container port calls/day, {CURRENT_LABEL} vs the "
                "Sep-Nov 2023 baseline"
            ),
        },
    }

    b_tot = bab["n_total"]
    b_con = bab["n_container"]
    b_tank = bab["n_tanker"]
    b_cap = bab["capacity_container"]
    _last = dt.date(*(int(x) for x in DETAIL_KEYS[-1].split("-")), 1)
    _prev = dt.date(*(int(x) for x in DETAIL_KEYS[-2].split("-")), 1)
    last_lbl = _last.strftime("%B %Y")            # "August 2026"
    latest_clean_lbl = _prev.strftime("%B")       # "July"
    peak_2026 = max(bab["n_total_detail"][6:12])  # Dec 2025 – May 2026 window
    latest = bab["n_total_detail"][-1]
    latest_clean = bab["n_total_detail"][-2]

    sections = [
        Section(
            "1", "The finding",
            lede_md="The Bab el-Mandeb Strait — the strait the attacks actually "
            f"target — is running at **{b_tot['pct_of_normal']:.0f}% of its "
            "pre-crisis traffic**, and for containers it is close to shut.",
            body_md=(
                "The Bab el-Mandeb is the 20-mile gap between Yemen and Djibouti that "
                "every Suez-bound ship from Asia must pass. IMF PortWatch counts "
                f"**{b_tot['precrisis']:.0f} transits per day** there in the clean "
                f"quarter before the December 2023 escalation; in July 2026 it counts "
                f"**{b_tot['current']:.0f}**.\n\n"
                f"By cargo class the picture matches the Suez Canal at the other end of "
                f"the route: tankers back to **{b_tank['pct_of_normal']:.0f}%** of "
                f"normal, containers at **{b_con['pct_of_normal']:.0f}%** "
                f"({b_con['current']:.1f} per day vs {b_con['precrisis']:.0f}), and "
                f"container cargo capacity at just **{b_cap['pct_of_normal']:.0f}%** — "
                f"the single most depressed figure in this brief. The container lines "
                f"are gone; what still runs the strait is tankers and bulk carriers "
                f"pricing in the war-risk premium."
            ),
        ),
        Section(
            "2", "Two and a half years, no container recovery",
            body_md=(
                "Across nine quarters the container line does not trend up. The strait "
                "settled into its disrupted level by mid-2024 and has held there. "
                "Total transits have recovered somewhat — tankers and dry bulk "
                "returning — but the containerised Asia–Europe trade that this route "
                "existed to carry has not.\n\n"
                "This is the southern half of the same story the Suez brief tells from "
                "the northern end: one route, diverted whole, around the Cape of Good "
                f"Hope, where container transits are up {cape['n_container']['pct_change']:+.0f}%."
            ),
            figure={
                "title": "Bab el-Mandeb transits per day — total vs container",
                "sub": "Quarterly average, 2023 Q1 – 2026 Q3",
                "chart_id": "chart-bab-trend",
                "caption": "Source: IMF PortWatch, `Daily_Chokepoints_Data`, chokepoint 4, "
                "fields `n_total` and `n_container`. Marker: December 2023 escalation.",
                "legend": [("Total transits", "var(--s1)"), ("Container", "var(--s2)")],
            },
        ),
        Section(
            "3", "Capacity says shut, not slow",
            body_md=(
                f"Container *cargo capacity* through the strait is at "
                f"**{b_cap['pct_of_normal']:.0f}% of pre-crisis** — lower than the "
                f"vessel count, because the few container ships still transiting are "
                f"small regional feeders, not mainline tonnage. Indexed against their "
                f"own 2023 baselines, tankers have climbed back toward normal while "
                f"containers sit near the floor and flat.\n\n"
                "A route-wide hard closure would flatten every class equally. The gap "
                "between tankers and containers here is the market choosing: the "
                "passage is transitable if the cargo can absorb the risk and the "
                "premium, and scheduled container services cannot."
            ),
            figure={
                "title": "Recovery by cargo class — Bab el-Mandeb",
                "sub": "Indexed to the Sep–Nov 2023 average (= 100), quarterly",
                "chart_id": "chart-bab-class",
                "caption": "Source: IMF PortWatch, `Daily_Chokepoints_Data`. Each series "
                "divided by its own pre-crisis mean.",
                "legend": [("Tanker", "var(--s1)"), ("Container", "var(--s2)")],
            },
            callout=(
                "Why this matters",
                "Container capacity at single-digit percent, sustained for two years, "
                "is the clearest signal in the dataset that this is a structural "
                "reroute and not a disruption waiting to clear.",
            ),
        ),
        Section(
            "4", "A fresh dip in mid-2026 — worth watching",
            body_md=(
                f"Total transits had actually ground back to a post-crisis high of "
                f"about **{peak_2026:.0f} per day** through the spring of 2026. Then "
                f"they slipped: **{latest_clean:.0f}** in {latest_clean_lbl} and "
                f"**{latest:.0f}** in {last_lbl}. Tanker transits fell alongside.\n\n"
                f"Two things temper this. The most recent month is provisional — "
                f"PortWatch revises its last ~2 weeks upward as more satellite data "
                f"lands, so {last_lbl} will likely be marked up. But the direction is "
                f"consistent with the March 2026 Strait of Hormuz crisis pulling "
                f"war-risk insurance capacity and underwriting appetite out of the "
                f"whole region at once. This is a signal to track, not yet a confirmed "
                f"second leg down."
            ),
            figure={
                "title": "Bab el-Mandeb — monthly transits, the recent window",
                "sub": f"Monthly average, {DETAIL_LABELS[0]} – {DETAIL_LABELS[-1]}",
                "chart_id": "chart-bab-2026",
                "caption": "Source: IMF PortWatch, `Daily_Chokepoints_Data`. Last point "
                "(hollow marker) is provisional. Marker: March 2026 Strait of Hormuz "
                "crisis onset.",
                "legend": [("Total transits", "var(--s1)"), ("Tanker", "var(--s2)")],
            },
        ),
        Section(
            "5", "Djibouti holds; the Saudi Red Sea coast does not",
            body_md=(
                f"**Djibouti** has kept its place as the regional anchor — container "
                f"port calls {dji['precrisis']:.1f} → {dji['current']:.1f} per day, "
                f"total calls roughly flat. It sits at the mouth of the strait, hosts "
                f"multinational naval forces, and is where cargo that does run the "
                f"gauntlet gets consolidated and bunkered. **Salalah**, just outside "
                f"the strait in Oman, is up {sal['pct_change']:+.0f}% as a safe-side "
                f"transshipment alternative.\n\n"
                f"The port-level casualties are on the **Saudi Red Sea coast**, which "
                f"has no way around its own geography: **Jeddah** container calls are "
                f"down **{abs(jed['pct_change']):.0f}%** and **King Abdullah Port** "
                f"down **{abs(kap['pct_change']):.0f}%** — both sit deep inside the "
                f"risk zone with the Suez route as their only artery. East African "
                f"feeder ports (Berbera, Mombasa) are down modestly, squeezed by "
                f"thinner regional transshipment."
            ),
            figure={
                "title": "Change in container port calls — July 2026 vs pre-crisis",
                "sub": "Percent change in daily port-call average, Sep–Nov 2023 baseline",
                "chart_id": "chart-ports",
                "caption": "Source: IMF PortWatch, `Daily_Ports_Data`, field "
                "`portcalls_container`. Absolute rates (calls/day, pre-crisis → July) "
                "at right. Small ports swing large percentages off a low base.",
            },
        ),
        Section(
            "6", "The regional picture, mapped",
            body_md=(
                "**Bab el-Mandeb** marked, the regional container ports coloured by "
                "how their call counts moved — green held or grew, red fell, bubble "
                "area proportional to the daily change. **Djibouti** and **Salalah** "
                "hold as the regional anchors; the **Saudi Red Sea** ports "
                f"(Jeddah {jed['pct_change']:+.0f}%, King Abdullah "
                f"{kap['pct_change']:+.0f}%) are the deepest losses. The "
                "container traffic that no longer transits the strait runs south "
                "around the Cape of Good Hope (off this frame — see §2)."
            ),
            figure={
                "title": "The Bab el-Mandeb region — who held, who lost",
                "sub": f"Change in container port calls/day, {CURRENT_LABEL} vs Sep-Nov 2023",
                "chart_id": "chart-map",
                "caption": "Basemap: Natural Earth 10m (public domain). Coordinates: "
                "IMF PortWatch. The strait is marked, not sized. Ports with a change "
                "too small to plot (<0.25 calls/day) are omitted here but appear in §5.",
            },
        ),
        Section(
            "7", "Assessment",
            body_md=(
                f"The Bab el-Mandeb is a persistently degraded chokepoint — mixed "
                f"traffic near **{b_tot['pct_of_normal']:.0f}% of pre-crisis**, "
                f"containers effectively removed — with a possible fresh deterioration "
                f"in the second half of 2026 that the next few PortWatch refreshes "
                f"will confirm or revise away. Djibouti is the regional constant; the "
                f"Saudi Red Sea ports are the clearest port-level loss; the Cape of "
                f"Good Hope remains the route.\n\n"
                "The same two caveats apply as to any PortWatch read: the data shows "
                "the shipping outcome, not its cause, and every figure is measured "
                "against a fixed 2023 quarter rather than a counterfactual 2026. The "
                f"{last_lbl} data point specifically should be treated as provisional."
            ),
        ),
    ]

    charts = [
        LineChart(
            "chart-bab-trend", y_max=90, y_ticks=[0, 30, 60, 90],
            mark_index=ONSET_INDEX, mark_label="crisis",
            series=[
                {"values": [v or 0 for v in bab["n_total_quarterly"]],
                 "color": "var(--s1)", "label": "Total", "tipLabel": "Total transits/day", "area": True},
                {"values": [v or 0 for v in bab["n_container_quarterly"]],
                 "color": "var(--s2)", "label": "Container", "tipLabel": "Container transits/day"},
            ],
        ),
        LineChart(
            "chart-bab-class", y_max=110, y_ticks=[0, 50, 100], y_pct=True,
            ref_line=100, ref_label="pre-crisis", mark_index=ONSET_INDEX, mark_label="crisis",
            series=[
                {"values": [round(100 * (v or 0) / b_tank["precrisis"], 0)
                            for v in quarterly(con, BAB, "n_tanker")],
                 "color": "var(--s1)", "label": "Tanker", "tipLabel": "Tanker", "asPct": True},
                {"values": [round(100 * (v or 0) / b_con["precrisis"], 0)
                            for v in bab["n_container_quarterly"]],
                 "color": "var(--s2)", "label": "Container", "tipLabel": "Container", "asPct": True},
            ],
        ),
        LineChart(
            "chart-bab-2026", y_max=45, y_ticks=[0, 15, 30, 45],
            mark_index=HORMUZ_INDEX, mark_label="Hormuz", provisional_last=True,
            series=[
                {"values": bab["n_total_detail"], "color": "var(--s1)",
                 "label": "Total", "tipLabel": "Total transits/day", "area": True},
                {"values": bab["n_tanker_detail"], "color": "var(--s2)",
                 "label": "Tanker", "tipLabel": "Tanker transits/day"},
            ],
        ),
        DivergingChart(
            "chart-ports",
            rows=[{"name": p["name"], "country": p["iso3"], "pct": int(p["pct_change"]),
                   "a": p["precrisis"], "b": p["current"]} for p in ports],
            max_abs=max(80, min(135, max(abs(p["pct_change"]) for p in ports) + 15)),
        ),
        MapChart(
            "chart-map",
            bbox=_bmap["bbox"], land=_bmap["land"], borders=_bmap["borders"],
            points=map_points, size_max=_map_size_max, size_unit="calls/day",
            size_legend=[1, 3, round(_map_size_max)] if _map_size_max >= 4 else [1, 2, 3],
            labels=_map_labels,
        ),
    ]

    cap_q = quarterly(con, BAB, "capacity_container")
    dji_q = quarterly(con, ports and dji["entity_id"] or "port294", "portcalls_container")
    table = DataTable(
        caption="Quarterly figures — Bab el-Mandeb Strait and Djibouti",
        columns=["Quarter", "Strait total/day", "Strait container/day",
                 "Strait container capacity/day", "Djibouti container calls/day"],
        rows=[
            [QUARTER_LABELS[i],
             f"{bab['n_total_quarterly'][i]:.0f}" if bab['n_total_quarterly'][i] else "–",
             f"{bab['n_container_quarterly'][i]:.1f}" if bab['n_container_quarterly'][i] else "–",
             f"{(cap_q[i] or 0):,.0f}",
             f"{(dji_q[i] or 0):.1f}"]
            for i in range(len(QUARTER_LABELS))
        ],
        break_row=ONSET_INDEX,
        crit_cols=[2, 3],
    )

    brief = Brief(
        slug=SLUG,
        title="Bab el-Mandeb Watch",
        kicker="Supply-chain disruption brief",
        chokepoint_code="CHOKEPOINT 4",
        data_as_of=cov[1].strftime("%-d %b %Y"),
        generated=dt.date.today().strftime("%-d %b %Y"),
        verdict="Ongoing · Possible Fresh Dip",
        verdict_tone="serious",
        headline="The Red Sea's southern gate is still half shut — and may be "
        "tightening again",
        dek="Two and a half years of blockade at the Bab el-Mandeb, no container "
        "recovery, and a mid-2026 dip that lines up with the Hormuz crisis.",
        months=QUARTER_LABELS,
        tiles=[
            Tile("Strait total transits", f"{b_tot['pct_of_normal']:.0f}", "% of normal",
                 f"{b_tot['current']:.0f}/day now vs {b_tot['precrisis']:.0f} pre-crisis"),
            Tile("Strait container transits", f"{b_con['pct_of_normal']:.0f}", "% of normal",
                 "No recovery trend in nine quarters", crit=True),
            Tile("Strait container capacity", f"{b_cap['pct_of_normal']:.0f}", "% of normal",
                 "Deepest figure in the brief", crit=True),
            Tile("Jeddah container calls",
                 f"{jed['pct_change']:+.0f}" if jed else "–", "%",
                 "Saudi Red Sea coast, the biggest port-level loss", crit=True),
        ],
        sections=sections,
        charts=charts,
        table=table,
        method_dl=[
            ("Data source", "IMF PortWatch (portwatch.imf.org) — daily maritime "
             "activity estimated from satellite AIS via the UN Global Platform. Free "
             "public use with attribution. Backfill covers "
             f"1 Jan 2023 – {cov[1].strftime('%-d %b %Y')}."),
            ("What the numbers are", "`n_total` / `n_container` / `n_tanker` are "
             "counts of vessel transits by class at chokepoint 4. `capacity_container` "
             "is the estimated aggregate cargo capacity of transiting container ships. "
             "`portcalls_container` is container-ship port calls."),
            ("Baseline", "A fixed pre-crisis window, **September–November 2023**, not a "
             "rolling baseline. Percent-of-normal = current value ÷ pre-crisis mean."),
            ("“Current” month", f"**{CURRENT_LABEL}** for headline figures. The "
             "monthly watch chart runs through the latest month in the store, with "
             "its final point marked provisional — PortWatch under-reports its most "
             "recent ~2 weeks."),
            ("Regional analysis", "Port-level comparison on `portcalls_container`, "
             "July 2026 vs the same 2023 window, for Djibouti, Salalah, the Saudi Red "
             "Sea ports, Aqaba, Port Sudan, and East African feeder ports. The Cape of "
             "Good Hope (chokepoint 7) is the route substitute."),
            ("Reproduce", "Clone github.com/ubeast/logjam, backfill the "
             "database to 2023, then `uv run python "
             "scripts/reports/horn_of_africa_2026.py`. Full method in "
             "`docs/METHODOLOGY.md`."),
        ],
        limitations=[
            "PortWatch measures throughput (vessels crossing the line), not queue "
            "length, berth dwell, or how long a diversion adds to a voyage.",
            "The data attests to the shipping outcome, not the cause. The Q1 2024 "
            "break and the mid-2026 dip coincide with reported events; causation is "
            "not established here.",
            "The most recent month is provisional and will likely be revised upward; "
            "the “fresh dip” finding is explicitly provisional.",
            "Capacity and trade-volume fields are model estimates, not manifest data.",
            "All comparisons are versus a fixed 2023 quarter.",
            "Regional port effects are shown only for a hand-picked candidate set.",
        ],
    )

    key_figures = [
        ("Strait total transits / day", f"{b_tot['current']:.0f}",
         f"{b_tot['precrisis']:.0f}", f"{b_tot['pct_of_normal']:.0f} %"),
        ("Strait container transits / day", f"{b_con['current']:.1f}",
         f"{b_con['precrisis']:.1f}", f"{b_con['pct_of_normal']:.0f} %"),
        ("Strait container capacity / day", f"{b_cap['current']:,.0f}",
         f"{b_cap['precrisis']:,.0f}", f"{b_cap['pct_of_normal']:.0f} %"),
        ("Strait tanker transits / day", f"{b_tank['current']:.1f}",
         f"{b_tank['precrisis']:.1f}", f"{b_tank['pct_of_normal']:.0f} %"),
        ("Djibouti container calls / day",
         f"{dji['current']:.1f}" if dji else "–",
         f"{dji['precrisis']:.1f}" if dji else "–",
         f"{dji['pct_change']:+.0f} %" if dji else "–"),
    ]

    con.close()
    print(f"  Bab total: {b_tot['pct_of_normal']:.0f}% | container: "
          f"{b_con['pct_of_normal']:.0f}% | capacity: {b_cap['pct_of_normal']:.0f}% | "
          f"latest month {latest:.0f}/day (provisional)")
    return brief, payload, key_figures


def main() -> None:
    brief, payload, key_figures = build()
    write_all(brief, payload, key_figures)


if __name__ == "__main__":
    main()
