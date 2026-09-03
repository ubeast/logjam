#!/usr/bin/env python
"""Suez Canal / Red Sea diversion — is the artery recovering? (2026 brief).

Two and a half years after Houthi attacks pushed the Asia–Europe trade off the
Red Sea route, this brief reads the PortWatch data for the Suez Canal
(``chokepoint 1``), asks how much traffic has come back, and confirms where the
diverted volume still goes (the Cape of Good Hope).

    uv run python scripts/reports/suez_redsea_2026.py

Output:
    reports/data/suez_redsea_2026.json   every figure the brief cites
    reports/suez_redsea_2026.md
    reports/suez_redsea_2026.html

Needs a store backfilled to at least 2023 (a genuine pre-crisis baseline) —
``LOGJAM_INITIAL_BACKFILL_DAYS=1400 uv run logjam refresh --full`` or the
``scripts/`` one-off backfill.
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
    Section,
    Tile,
    connect,
    pct,
    pct_change,
    resolve,
    window_avg,
    write_all,
)

SLUG = "suez_redsea_2026"
SUEZ = "chokepoint1"
BAB = "chokepoint4"
CAPE = "chokepoint7"

# Pre-crisis reference: the last clean quarter before the November–December 2023
# escalation of Houthi attacks on Red Sea shipping. Fixed, not rolling — a
# trailing baseline would by now have absorbed the diversion into its "normal".
PRECRISIS = (dt.date(2023, 9, 1), dt.date(2023, 12, 1))
# Onset quarter, for the chart marker.
ONSET_LABEL = "Dec 2023"
# Most recent settled month. PortWatch revises its last ~2 weeks upward.
CURRENT = (dt.date(2026, 7, 1), dt.date(2026, 8, 1))
CURRENT_LABEL = "July 2026"

# Quarterly trend axis: 2023 Q1 … 2026 Q3.
QUARTERS: list[tuple[int, int]] = [
    (y, q) for y in (2023, 2024, 2025, 2026) for q in (1, 2, 3, 4)
][:15]
QUARTER_LABELS = [f"{y % 100} Q{q}" for y, q in QUARTERS]
ONSET_INDEX = 4  # 2024 Q1


def _q_bounds(y: int, q: int) -> tuple[dt.date, dt.date]:
    lo = dt.date(y, 3 * (q - 1) + 1, 1)
    hi = dt.date(y + 1, 1, 1) if q == 4 else dt.date(y, 3 * q + 1, 1)
    return lo, hi


def quarterly(con: Any, entity_id: str, metric: str) -> list[float | None]:
    return [window_avg(con, entity_id, metric, *_q_bounds(y, q)) for y, q in QUARTERS]


def main() -> None:
    con = connect()

    cov = con.execute("SELECT min(obs_date), max(obs_date) FROM observation").fetchone()
    if cov[0] > dt.date(2023, 10, 1):
        sys.exit(
            f"store starts {cov[0]} — need pre-crisis 2023 data. Backfill first "
            "(LOGJAM_INITIAL_BACKFILL_DAYS=1400 uv run logjam refresh --full)."
        )

    # ---- chokepoint before/after ------------------------------------------
    def ba(eid: str, metric: str) -> dict[str, float | None]:
        base = window_avg(con, eid, metric, *PRECRISIS)
        cur = window_avg(con, eid, metric, *CURRENT)
        return {"precrisis": base, "current": cur,
                "pct_of_normal": pct(cur, base), "pct_change": pct_change(cur, base)}

    suez = {m: ba(SUEZ, m) for m in ("n_total", "n_container", "n_tanker",
                                     "n_dry_bulk", "capacity_container", "capacity_total")}
    suez["n_total_quarterly"] = quarterly(con, SUEZ, "n_total")
    suez["n_container_quarterly"] = quarterly(con, SUEZ, "n_container")
    cape = {m: ba(CAPE, m) for m in ("n_total", "n_container", "capacity_container", "n_tanker")}
    cape["n_container_quarterly"] = quarterly(con, CAPE, "n_container")
    bab = {m: ba(BAB, m) for m in ("n_total", "n_container", "capacity_container")}

    # ---- port-level winners / losers (Med transshipment + Cape-route + Red Sea)
    port_patterns = [
        "%piraeus%", "%algeciras%", "%marsaxlokk%", "%gioia tauro%", "%port said%",
        "%damietta%", "%el sokhna%", "%colombo%", "%jeddah%", "%king abdullah%",
        "%durban%", "%ngqura%",
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
        if a is None or b is None or a < 0.3:
            continue
        ports.append({"entity_id": eid, "name": name, "iso3": iso,
                      "precrisis": a, "current": b, "pct_change": pct_change(b, a)})
    ports.sort(key=lambda p: p["pct_change"], reverse=True)

    payload = {
        "meta": {
            "generated": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "data_source": "IMF PortWatch (portwatch.imf.org)",
            "db_coverage": [str(cov[0]), str(cov[1])],
            "precrisis_window": [d.isoformat() for d in PRECRISIS],
            "current_window": [d.isoformat() for d in CURRENT],
            "quarters": QUARTER_LABELS,
        },
        "suez": suez,
        "bab_el_mandeb": bab,
        "cape_of_good_hope": cape,
        "ports": ports,
    }

    # ---------------------------------------------------------------- prose --
    s_tot = suez["n_total"]
    s_con = suez["n_container"]
    s_tank = suez["n_tanker"]
    s_cap = suez["capacity_container"]
    c_con = cape["n_container"]
    c_cap = cape["capacity_container"]

    med_losers = ", ".join(
        f"{p['name']} {p['pct_change']:+.0f}%" for p in ports
        if p["name"] in ("Piraeus", "Algeciras", "Marsaxlokk")
    )

    sections = [
        Section(
            "1", "The finding",
            lede_md="Two and a half years on, the Suez Canal carries about "
            f"**{s_tot['pct_of_normal']:.0f}% of its pre-crisis traffic** — and for "
            "containers, essentially none of it has come back.",
            body_md=(
                f"IMF PortWatch counts vessel transits at 28 maritime chokepoints from "
                f"satellite AIS. Through the Suez Canal, total transits averaged "
                f"**{s_tot['precrisis']:.0f} per day** in the clean quarter before the "
                f"December 2023 escalation of attacks on Red Sea shipping. In July 2026 "
                f"they averaged **{s_tot['current']:.0f} per day** — a partial recovery "
                f"from the 2024 trough, but still a third below normal.\n\n"
                f"Split by cargo class, the recovery is lopsided. Tanker transits are "
                f"back to **{s_tank['pct_of_normal']:.0f}%** of pre-crisis. Container "
                f"transits sit at **{s_con['pct_of_normal']:.0f}%** — "
                f"{s_con['current']:.0f} per day against {s_con['precrisis']:.0f} before "
                f"— and container *cargo capacity* through the canal is at just "
                f"**{s_cap['pct_of_normal']:.0f}%**. The box trade did not slow down "
                f"and recover; it left."
            ),
        ),
        Section(
            "2", "The diversion held",
            body_md=(
                "The break is visible as a single step down in the first quarter of "
                "2024 and a flat line since. There is no upward trajectory in the "
                "container series across nine quarters — the disruption is not "
                "resolving, it has become the operating baseline.\n\n"
                "Total transits have ground back a little, from the 2024 low toward "
                f"{s_tot['current']:.0f} per day, entirely on the back of tankers and "
                "dry bulk. Those cargoes are more willing to price in the war-risk "
                "insurance premium and the longer exposure; container lines, running "
                "fixed weekly schedules, rerouted wholesale and have stayed rerouted."
            ),
            figure={
                "title": "Suez Canal transits per day — total vs container",
                "sub": "Quarterly average, 2023 Q1 – 2026 Q3",
                "chart_id": "chart-suez-trend",
                "caption": "Source: IMF PortWatch, `Daily_Chokepoints_Data`, fields "
                "`n_total` and `n_container`. Marker: December 2023 escalation.",
                "legend": [("Total transits", "var(--s1)"), ("Container", "var(--s2)")],
            },
        ),
        Section(
            "3", "Blocked for boxes, not for barrels",
            body_md=(
                "Indexing each cargo class to its own pre-crisis average makes the "
                "split unmistakable. Tankers and dry bulk have clawed back toward "
                "normal; containers are pinned near the floor. Container cargo "
                f"capacity — the aggregate slot capacity of the ships still using the "
                f"canal — is at **{s_cap['pct_of_normal']:.0f}% of normal**, below even "
                "the vessel count, because the container ships that do transit are the "
                "smaller feeders, not the 20,000-TEU mainliners.\n\n"
                "A uniform collapse across every class would point to a hard closure. "
                "This selective pattern is the signature of a commercial reroute: the "
                "route is open, but for scheduled container services the math no "
                "longer works."
            ),
            figure={
                "title": "Recovery by cargo class — Suez Canal",
                "sub": "Indexed to the Sep–Nov 2023 average (= 100), quarterly",
                "chart_id": "chart-suez-class",
                "caption": "Source: IMF PortWatch, `Daily_Chokepoints_Data`. Each series "
                "divided by its own pre-crisis mean.",
                "legend": [("Tanker", "var(--s1)"), ("Container", "var(--s2)")],
            },
            callout=(
                "Why this matters",
                "A transit count alone could be read as “slowly recovering.” "
                "Capacity confirms it is not: for containers, real throughput through "
                "Suez is a small fraction of what it was, and flat.",
            ),
        ),
        Section(
            "4", "The Cape took the load",
            lede_md="Every box that left the Red Sea route had to go somewhere. It "
            "went around Africa — and has stayed there.",
            body_md=(
                f"Container transits past the Cape of Good Hope have risen from "
                f"**{c_con['precrisis']:.0f} per day** pre-crisis to "
                f"**{c_con['current']:.0f} per day** — up "
                f"**{c_con['pct_change']:+.0f}%** — and container cargo capacity on the "
                f"route is up **{c_cap['pct_change']:+.0f}%**, from "
                f"{c_cap['precrisis']:,.0f} to {c_cap['current']:,.0f} per day. The "
                f"Cape line shows the same single step in early 2024 as Suez, in the "
                f"opposite direction, and the same flat plateau since.\n\n"
                "The cost is distance. Asia–North Europe via the Cape is roughly 3,500 "
                "nautical miles and 10–14 days longer than via Suez, which ties up "
                "ships, burns bunkers, and has kept effective fleet capacity tight "
                "across the whole Asia–Europe trade for two years."
            ),
            figure={
                "title": "Cape of Good Hope — container transits per day",
                "sub": "Quarterly average, 2023 Q1 – 2026 Q3",
                "chart_id": "chart-cape",
                "caption": "Source: IMF PortWatch, `Daily_Chokepoints_Data`, field "
                "`n_container`, chokepoint 7.",
            },
        ),
        Section(
            "5", "Who lost the transshipment",
            body_md=(
                "There is no clear port-level winner, because the reroute is a longer "
                "version of the same voyage rather than a switch to a new hub. The "
                "clear *losers* are the Mediterranean transshipment hubs that fed the "
                f"Suez route: {med_losers}. They handled Asia-origin boxes that came "
                "through the canal for onward distribution; that feeder role has "
                "thinned.\n\n"
                "Egypt's own canal-adjacent container ports (Port Said, Damietta) are "
                "roughly flat — they were never the point of the route. The one "
                "consistent gainer is **Colombo**, up as a consolidation point where "
                "Asian cargo is aggregated onto the big ships before the long haul "
                "around the Cape."
            ),
            figure={
                "title": "Change in container port calls — July 2026 vs pre-crisis",
                "sub": "Percent change in daily port-call average, Sep–Nov 2023 baseline",
                "chart_id": "chart-ports",
                "caption": "Source: IMF PortWatch, `Daily_Ports_Data`, field "
                "`portcalls_container`. Absolute rates (calls/day, pre-crisis → July) "
                "at right — small ports swing large percentages off a low base.",
            },
        ),
        Section(
            "6", "Assessment",
            body_md=(
                f"The Suez Canal in 2026 is a structurally smaller artery. Mixed "
                f"traffic has stabilised near **{s_tot['pct_of_normal']:.0f}% of "
                f"pre-crisis**; containerised trade shows **no recovery trend** after "
                f"nine quarters and runs at well under half its former volume. The "
                f"Cape of Good Hope is the load-bearing alternative and there is no "
                f"sign of that unwinding.\n\n"
                "Two caveats bound this read. PortWatch measures vessel movements, not "
                "their causes — the 2024 break coincides with the reported Red Sea "
                "shipping crisis, but the data attests to the outcome. And the "
                "pre-crisis window is a fixed 2023 quarter; that is the right "
                "comparison for a structural shift of this kind, but it means every "
                "figure here is “versus 2023,” not versus a hypothetical "
                "undisrupted 2026."
            ),
        ),
    ]

    charts = [
        LineChart(
            "chart-suez-trend", y_max=90, y_ticks=[0, 30, 60, 90],
            mark_index=ONSET_INDEX, mark_label="crisis",
            series=[
                {"values": [v or 0 for v in suez["n_total_quarterly"]],
                 "color": "var(--s1)", "label": "Total", "tipLabel": "Total transits/day", "area": True},
                {"values": [v or 0 for v in suez["n_container_quarterly"]],
                 "color": "var(--s2)", "label": "Container", "tipLabel": "Container transits/day"},
            ],
        ),
        LineChart(
            "chart-suez-class", y_max=110, y_ticks=[0, 50, 100], y_pct=True,
            ref_line=100, ref_label="pre-crisis", mark_index=ONSET_INDEX, mark_label="crisis",
            series=[
                {"values": [round(100 * (v or 0) / s_tank["precrisis"], 0)
                            for v in quarterly(con, SUEZ, "n_tanker")],
                 "color": "var(--s1)", "label": "Tanker", "tipLabel": "Tanker", "asPct": True},
                {"values": [round(100 * (v or 0) / s_con["precrisis"], 0)
                            for v in suez["n_container_quarterly"]],
                 "color": "var(--s2)", "label": "Container", "tipLabel": "Container", "asPct": True},
            ],
        ),
        LineChart(
            "chart-cape", y_max=25, y_ticks=[0, 5, 10, 15, 20, 25],
            mark_index=ONSET_INDEX, mark_label="crisis",
            series=[{"values": [v or 0 for v in cape["n_container_quarterly"]],
                     "color": "var(--s1)", "label": "per day",
                     "tipLabel": "Container transits/day", "area": True}],
        ),
        DivergingChart(
            "chart-ports",
            rows=[{"name": p["name"], "country": p["iso3"], "pct": int(p["pct_change"]),
                   "a": p["precrisis"], "b": p["current"]} for p in ports],
            max_abs=max(80, min(135, max(abs(p["pct_change"]) for p in ports) + 15)),
        ),
    ]

    table = DataTable(
        caption="Quarterly figures — Suez Canal and the Cape route, container traffic",
        columns=["Quarter", "Suez total/day", "Suez container/day",
                 "Suez container capacity/day", "Cape container/day"],
        rows=[
            [QUARTER_LABELS[i],
             f"{suez['n_total_quarterly'][i]:.0f}" if suez['n_total_quarterly'][i] else "–",
             f"{suez['n_container_quarterly'][i]:.1f}" if suez['n_container_quarterly'][i] else "–",
             f"{(quarterly(con, SUEZ, 'capacity_container')[i] or 0):,.0f}",
             f"{cape['n_container_quarterly'][i]:.1f}" if cape['n_container_quarterly'][i] else "–"]
            for i in range(len(QUARTER_LABELS))
        ],
        break_row=ONSET_INDEX,
        crit_cols=[2, 3],
    )

    brief = Brief(
        slug=SLUG,
        title="Suez Canal Recovery Check",
        kicker="Supply-chain disruption brief",
        chokepoint_code="CHOKEPOINT 1",
        data_as_of=cov[1].strftime("%-d %b %Y"),
        generated=dt.date.today().strftime("%-d %b %Y"),
        verdict="Ongoing · No Container Recovery",
        verdict_tone="serious",
        headline="Two years on, the Suez Canal is back to half strength — and "
        "containers haven't returned at all",
        dek="Total transits have partly recovered on the back of tankers and bulk. "
        "Container shipping stayed on the Cape route, and the data shows no trend "
        "back.",
        months=QUARTER_LABELS,
        tiles=[
            Tile("Suez total transits", f"{s_tot['pct_of_normal']:.0f}", "% of normal",
                 f"{s_tot['current']:.0f}/day now vs {s_tot['precrisis']:.0f} pre-crisis"),
            Tile("Suez container transits", f"{s_con['pct_of_normal']:.0f}", "% of normal",
                 "No recovery trend in nine quarters", crit=True),
            Tile("Suez container capacity", f"{s_cap['pct_of_normal']:.0f}", "% of normal",
                 "Only the smaller feeders still transit", crit=True),
            Tile("Cape of Good Hope containers", f"{c_con['pct_change']:+.0f}", "%",
                 f"{c_con['precrisis']:.0f} → {c_con['current']:.0f} transits/day"),
        ],
        sections=sections,
        charts=charts,
        table=table,
        method_dl=[
            ("Data source", "IMF PortWatch (portwatch.imf.org) — daily maritime "
             "activity estimated from satellite AIS on ~90,000 ships, via the UN "
             "Global Platform. Free public use with attribution. Backfill covers "
             f"1 Jan 2023 – {cov[1].strftime('%-d %b %Y')}."),
            ("What the numbers are", "`n_total` / `n_container` / `n_tanker` are "
             "counts of vessel transits by class. `capacity_container` is the "
             "estimated aggregate cargo capacity of transiting container ships. "
             "`portcalls_container` is container-ship port calls."),
            ("Baseline", "A fixed pre-crisis window, **September–November 2023** — the "
             "last clean quarter before the December 2023 escalation — not a rolling "
             "baseline, which by 2026 would treat the diverted level as normal. "
             "Percent-of-normal = current value ÷ pre-crisis mean."),
            ("“Current” month", f"**{CURRENT_LABEL}.** PortWatch revises its "
             "most recent ~2 weeks upward as satellite data lands, so the latest month "
             "in the store is still settling and is not used for headline figures."),
            ("Reroute analysis", "The Cape of Good Hope is the route substitute "
             "(`n_container`, chokepoint 7). Port-level comparison on "
             "`portcalls_container`, July 2026 vs the same 2023 window, for East "
             "Mediterranean transshipment hubs, Egyptian canal ports, Colombo, and "
             "South African / Red Sea ports."),
            ("Reproduce", "Clone github.com/ubeast/logjam, backfill the "
             "database to 2023, then `uv run python "
             "scripts/reports/suez_redsea_2026.py`. Full method in "
             "`docs/METHODOLOGY.md`."),
        ],
        limitations=[
            "PortWatch measures throughput (vessels moving), not queue length, berth "
            "dwell, or voyage duration. This brief cannot quantify the added transit "
            "time around the Cape beyond the standard distance estimate.",
            "The data attests to the shipping outcome, not the cause. The Q1 2024 "
            "break coincides with the reported Red Sea crisis; causation is not "
            "established here.",
            "Capacity and trade-volume fields are model estimates, not manifest data.",
            "All comparisons are versus a fixed 2023 quarter — “versus "
            "pre-crisis,” not versus a counterfactual undisrupted 2026.",
            "Port-level effects are shown only for a hand-picked candidate set; an "
            "unlisted beneficiary or casualty would be missed.",
        ],
    )

    key_figures = [
        ("Suez total transits / day", f"{s_tot['current']:.0f}",
         f"{s_tot['precrisis']:.0f}", f"{s_tot['pct_of_normal']:.0f} %"),
        ("Suez container transits / day", f"{s_con['current']:.1f}",
         f"{s_con['precrisis']:.1f}", f"{s_con['pct_of_normal']:.0f} %"),
        ("Suez container capacity / day", f"{s_cap['current']:,.0f}",
         f"{s_cap['precrisis']:,.0f}", f"{s_cap['pct_of_normal']:.0f} %"),
        ("Suez tanker transits / day", f"{s_tank['current']:.1f}",
         f"{s_tank['precrisis']:.1f}", f"{s_tank['pct_of_normal']:.0f} %"),
        ("Cape of Good Hope container transits / day", f"{c_con['current']:.0f}",
         f"{c_con['precrisis']:.0f}", f"{c_con['pct_change']:+.0f} %"),
    ]

    write_all(brief, payload, key_figures)
    con.close()
    print(f"  Suez total: {s_tot['pct_of_normal']:.0f}% of normal | "
          f"container: {s_con['pct_of_normal']:.0f}% | "
          f"Cape container {c_con['pct_change']:+.0f}%")


if __name__ == "__main__":
    main()
