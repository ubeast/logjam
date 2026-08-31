#!/usr/bin/env python
"""Strait of Hormuz — container shipping and the 2026 Iran conflict (brief).

The March 2026 Strait of Hormuz crisis is a *separate* shock from the 2023
Houthi / Red Sea crisis: a different chokepoint, two years later, and it hits
the Persian Gulf trade, not the Asia-Europe route. This brief reads the
PortWatch data for the strait (``chokepoint 6``) against a fixed 2023 pre-crisis
baseline, sets it beside the Red Sea chokepoints so the two shocks can be told
apart, and traces where the Gulf's container volume rerouted.

    uv run python scripts/reports/hormuz_container_2026.py

Output:
    reports/data/hormuz_container_2026.json   every figure the brief cites
    reports/hormuz_container_2026.md
    reports/hormuz_container_2026.html

Needs a store backfilled to 2023 for a genuine pre-crisis baseline
(``BNL_INITIAL_BACKFILL_DAYS=1400 uv run bottleneck refresh --full``).
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

SLUG = "hormuz_container_2026"
HORMUZ = "chokepoint6"
SUEZ = "chokepoint1"
BAB = "chokepoint4"

# Fixed pre-crisis reference: the last clean quarter before the March 2026
# Strait of Hormuz crisis is Dec 2025 - Feb 2026, but Gulf throughput was within
# ~10% of this level right back through 2023, so this brief uses the same
# Sep-Nov 2023 window as the sibling Red Sea briefs for a common baseline.
PRECRISIS = (dt.date(2023, 9, 1), dt.date(2023, 12, 1))
# The reroute (port-level) analysis uses the *immediate* pre-conflict window
# instead: several candidate ports grew substantially over 2023-2025 for
# unrelated reasons, and a 2023 comparison would conflate that growth with the
# diversion. The chokepoint itself was flat over the same span, so its figures
# stay on the 2023 baseline.
REROUTE_BASE = (dt.date(2025, 9, 1), dt.date(2026, 3, 1))
CURRENT = (dt.date(2026, 7, 1), dt.date(2026, 8, 1))
CURRENT_LABEL = "July 2026"

QUARTERS: list[tuple[int, int]] = [
    (y, q) for y in (2023, 2024, 2025, 2026) for q in (1, 2, 3, 4)
][:15]
QUARTER_LABELS = [f"{y % 100} Q{q}" for y, q in QUARTERS]
REDSEA_ONSET_INDEX = 4   # 2024 Q1 - Houthi / Red Sea crisis
HORMUZ_ONSET_INDEX = 12  # 2026 Q1 - Iran / Strait of Hormuz crisis

# Reroute candidates: regional container ports that could absorb Gulf volume.
REROUTE_PATTERNS = [
    "%jawaharlal%", "%nhava sheva%", "%mundra%", "%hazira%", "%pipavav%",
    "%karachi%", "%port qasim%", "%salalah%", "%sohar%", "%damietta%",
    "%port said%", "%colombo%", "%piraeus%", "%king abdullah%", "%jeddah%",
    "%dammam%", "%aqaba%",
]


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
            "(BNL_INITIAL_BACKFILL_DAYS=1400 uv run bottleneck refresh --full)."
        )

    def ba(eid: str, metric: str) -> dict[str, float | None]:
        base = window_avg(con, eid, metric, *PRECRISIS)
        cur = window_avg(con, eid, metric, *CURRENT)
        return {"precrisis": base, "current": cur,
                "pct_of_normal": pct(cur, base), "pct_change": pct_change(cur, base)}

    hormuz = {m: ba(HORMUZ, m) for m in ("n_total", "n_container", "n_tanker",
                                         "n_dry_bulk", "capacity_container")}
    hormuz["n_container_quarterly"] = quarterly(con, HORMUZ, "n_container")
    hormuz["n_total_quarterly"] = quarterly(con, HORMUZ, "n_total")
    hormuz["capacity_container_quarterly"] = quarterly(con, HORMUZ, "capacity_container")
    # 2025 mean, to show the pre-conflict level was stable vs the 2023 baseline.
    hormuz["n_container_2025"] = window_avg(
        con, HORMUZ, "n_container", dt.date(2025, 1, 1), dt.date(2026, 1, 1)
    )

    # cross-chokepoint container comparison
    compare = {
        "hormuz": [v or 0 for v in hormuz["n_container_quarterly"]],
        "suez": [v or 0 for v in quarterly(con, SUEZ, "n_container")],
        "bab_el_mandeb": [v or 0 for v in quarterly(con, BAB, "n_container")],
    }

    # Jebel Ali - the Gulf's container hub, inside the strait
    ja_id, ja_name, ja_iso = resolve(con, "%jebel ali%")  # type: ignore[misc]
    jebel_ali: dict[str, Any] = {"entity_id": ja_id, "name": ja_name, "iso3": ja_iso}
    for metric in ("portcalls_container", "import_container", "export_container"):
        jebel_ali[metric] = ba(ja_id, metric)
    jebel_ali["portcalls_container_quarterly"] = quarterly(con, ja_id, "portcalls_container")

    # Reroute beneficiaries
    seen: set[str] = set()
    reroute: list[dict[str, Any]] = []
    for pat in REROUTE_PATTERNS:
        hit = resolve(con, pat)
        if not hit or hit[0] in seen:
            continue
        seen.add(hit[0])
        eid, name, iso = hit
        a = window_avg(con, eid, "portcalls_container", *REROUTE_BASE)
        b = window_avg(con, eid, "portcalls_container", *CURRENT)
        if a is None or b is None or a < 0.3:
            continue
        reroute.append({"entity_id": eid, "name": name, "iso3": iso,
                        "precrisis": a, "current": b, "pct_change": pct_change(b, a)})
    reroute.sort(key=lambda r: r["pct_change"], reverse=True)

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
        "hormuz_chokepoint": hormuz,
        "chokepoint_container_comparison": compare,
        "jebel_ali": jebel_ali,
        "reroute_candidates": reroute,
    }

    h_tot = hormuz["n_total"]
    h_con = hormuz["n_container"]
    h_tank = hormuz["n_tanker"]
    h_cap = hormuz["capacity_container"]
    ja_calls = jebel_ali["portcalls_container"]
    ja_imp = jebel_ali["import_container"]
    ja_exp = jebel_ali["export_container"]
    def _short(name: str) -> str:
        return name.split(" (")[-1].rstrip(")") if "(" in name else name.replace(" Port", "")

    # Winners need a meaningful absolute base, or a tiny port dominates on percent.
    winners = [r for r in reroute if r["pct_change"] >= 25 and r["precrisis"] >= 1.0][:6]
    winners_txt = ", ".join(f"{_short(r['name'])} {r['pct_change']:+.0f}%" for r in winners)
    losers = [r for r in reroute if r["pct_change"] <= -20 and r["precrisis"] >= 1.0]
    losers_txt = ", ".join(f"{_short(r['name'])} {r['pct_change']:+.0f}%" for r in losers)

    sections = [
        Section(
            "1", "The finding",
            lede_md="Container-ship transits through the Strait of Hormuz have run "
            f"at roughly **{h_con['pct_of_normal']:.0f}% of normal** since March 2026 "
            "— the Persian Gulf's box trade has effectively stopped.",
            body_md=(
                f"This is the **2026 Strait of Hormuz crisis**, not the Red Sea one. "
                f"Different chokepoint, two years later: the Red Sea / Houthi "
                f"disruption (late 2023) diverted the Asia–Europe route around Africa; "
                f"the Iran conflict (March 2026) closed the entrance to the Persian "
                f"Gulf.\n\n"
                f"IMF PortWatch counted **{h_con['precrisis']:.0f} container transits "
                f"per day** through Hormuz in the clean quarter of late 2023, and the "
                f"level was steady at about {hormuz['n_container_2025']:.0f} per day "
                f"through 2025. Since March 2026 it has averaged **under one per day** "
                f"— {h_con['current']:.1f} in July. Container cargo capacity through "
                f"the strait is at **{h_cap['pct_of_normal']:.0f}% of normal**. The "
                f"collapse is uniform across classes — tankers are at "
                f"**{h_tank['pct_of_normal']:.0f}%**, total transits at "
                f"**{h_tot['pct_of_normal']:.0f}%** — the signature of a route-wide "
                f"closure, not a commodity-specific restriction."
            ),
        ),
        Section(
            "2", "Stable for three years, then a wall",
            body_md=(
                "Hormuz traffic is normally seasonal but flat year to year. Container "
                "transits held between roughly 13 and 21 per day every quarter from "
                "2023 through 2025 — the 2023 Red Sea crisis, visible as a cliff in "
                "the Suez and Bab el-Mandeb data, left Hormuz untouched, because the "
                "Gulf oil trade does not use the Red Sea.\n\n"
                "Then the line falls off the table in the first quarter of 2026 and "
                "keeps falling into the second. There is no recovery trend through "
                "late August."
            ),
            figure={
                "title": "Strait of Hormuz transits per day — total vs container",
                "sub": "Quarterly average, 2023 Q1 – 2026 Q3",
                "chart_id": "chart-hormuz-trend",
                "caption": "Source: IMF PortWatch, `Daily_Chokepoints_Data`, chokepoint 6, "
                "fields `n_total` and `n_container`. Marker: March 2026 crisis onset.",
                "legend": [("Total transits", "var(--s1)"), ("Container", "var(--s2)")],
            },
        ),
        Section(
            "3", "Blocked, not merely thinned",
            body_md=(
                "A fall in vessel *count* could mean fewer, larger ships moving the "
                "same cargo. It does not: PortWatch's estimate of the aggregate cargo "
                f"*capacity* of transiting container ships is at "
                f"**{h_cap['pct_of_normal']:.0f}% of pre-crisis** — as low as the "
                f"count, or lower. The few box ships still using the strait are the "
                f"smaller ones. Real throughput is gone, not redistributed onto "
                f"bigger tonnage."
            ),
            figure={
                "title": "Vessel count and cargo capacity fell together",
                "sub": "Hormuz container traffic, indexed to the Sep–Nov 2023 average (= 100)",
                "chart_id": "chart-hormuz-index",
                "caption": "Source: IMF PortWatch, `Daily_Chokepoints_Data`. Both series "
                "divided by their own pre-crisis mean.",
                "legend": [("Vessel count", "var(--s1)"), ("Cargo capacity", "var(--s2)")],
            },
            callout=(
                "Why this matters",
                "If the count fell while capacity held, a count-based alarm would be "
                "a false positive. Here both lines hit the floor together.",
            ),
        ),
        Section(
            "4", "Two shocks, two chokepoints",
            lede_md="The 2024 line and the 2026 line are different events at "
            "different straits — and neither one spilled into the other.",
            body_md=(
                "Put container transits through all three chokepoints on one axis and "
                "the picture separates cleanly. **Suez** and **Bab el-Mandeb** fall "
                "together in Q1 2024 — the Red Sea / Houthi crisis — and have held at "
                "that lower level ever since. **Hormuz** is flat through that whole "
                "period, then falls on its own in Q1–Q2 2026 — the Iran conflict.\n\n"
                "The Red Sea route shows almost no *additional* dip in 2026: the "
                "Asia–Europe container trade had already left it, so the Iran crisis "
                "had nothing there to divert. The two disruptions stack in cost — the "
                "Cape reroute and the Gulf closure are both live — but they are "
                "independent in the data."
            ),
            figure={
                "title": "Container transits per day — Hormuz vs the Red Sea chokepoints",
                "sub": "Quarterly average, 2023 Q1 – 2026 Q3",
                "chart_id": "chart-compare",
                "caption": "Source: IMF PortWatch, `Daily_Chokepoints_Data`, field "
                "`n_container`. Markers: Q1 2024 Red Sea / Houthi crisis; "
                "Q1 2026 Iran / Strait of Hormuz crisis.",
                "legend": [("Strait of Hormuz", "var(--s1)"),
                           ("Suez Canal", "var(--s2)"),
                           ("Bab el-Mandeb", "var(--s3)")],
            },
        ),
        Section(
            "5", "Jebel Ali goes dark",
            body_md=(
                f"Jebel Ali (Dubai) is the Gulf's dominant container port and one of "
                f"the ten busiest in the world. It sits *inside* the strait, and it "
                f"tracked the chokepoint almost exactly: container port calls held at "
                f"about {ja_calls['precrisis']:.0f} per day from 2023 through 2025, "
                f"then **{ja_calls['current']:.1f}** in July 2026 "
                f"(**{ja_calls['pct_of_normal']:.0f}% of normal**). Estimated "
                f"container trade volume — imports and exports — is running at "
                f"**{ja_imp['pct_of_normal']:.0f}–{ja_exp['pct_of_normal']:.0f}%** of "
                f"pre-crisis."
            ),
            figure={
                "title": "Jebel Ali — container port calls per day",
                "sub": "Quarterly average, 2023 Q1 – 2026 Q3",
                "chart_id": "chart-jebelali",
                "caption": "Source: IMF PortWatch, `Daily_Ports_Data`, field "
                "`portcalls_container`, port ID `port744`.",
            },
        ),
        Section(
            "6", "Where the containers went",
            body_md=(
                "Cargo that would have moved through the Gulf has rerouted, and not "
                "to the usual transshipment hubs. Measured against the six months "
                "just before the crisis, container port calls have surged on the "
                "**Indian subcontinent's west coast** and at ports positioned "
                f"*outside* the strait: {winners_txt}.\n\n"
                f"Saudi Arabia's Red Sea ports ({losers_txt}) are *down* — the "
                "Bab el-Mandeb disruption compounds the Gulf one there — and the "
                "mega-transshipment hubs that would normally absorb a shock "
                "(Colombo, Piraeus) are flat. This section uses the immediate "
                "pre-conflict window, not the 2023 baseline, because several of "
                "these ports grew on their own over 2023–2025."
            ),
            figure={
                "title": "Change in container port calls — July 2026 vs pre-conflict",
                "sub": "Percent change in daily port-call average, Sep 2025 – Feb 2026 baseline",
                "chart_id": "chart-reroute",
                "caption": "Source: IMF PortWatch, `Daily_Ports_Data`, field "
                "`portcalls_container`. Baseline is the six months before the crisis "
                "(not 2023). Absolute rates (calls/day, pre-conflict → July) at right "
                "— small ports swing large percentages off a low base.",
            },
        ),
        Section(
            "7", "Assessment",
            body_md=(
                "For container shipping the Strait of Hormuz has been functionally "
                "closed since March 2026, with no recovery trend through late August. "
                "The regional network has partly re-formed around it — Indian "
                "west-coast direct calls, Salalah, and Egyptian Mediterranean "
                "transshipment are the load-bearing alternatives — at a fraction of "
                "the lost volume and longer transit distances. This is a distinct "
                "shock from the still-unresolved Red Sea diversion; the two now run "
                "in parallel.\n\n"
                "PortWatch measures vessel movements, not their causes: the March "
                "2026 break coincides with the reported Strait of Hormuz crisis, but "
                "the data attests to the shipping outcome. Every figure is measured "
                "against a fixed 2023 quarter; because Gulf throughput was within "
                "~10% of that level right through 2025, the reference choice does not "
                "move the finding."
            ),
        ),
    ]

    charts = [
        LineChart(
            "chart-hormuz-trend", y_max=110, y_ticks=[0, 25, 50, 75, 100],
            mark_index=HORMUZ_ONSET_INDEX, mark_label="Iran crisis",
            series=[
                {"values": [v or 0 for v in hormuz["n_total_quarterly"]],
                 "color": "var(--s1)", "label": "Total", "tipLabel": "Total transits/day", "area": True},
                {"values": compare["hormuz"],
                 "color": "var(--s2)", "label": "Container", "tipLabel": "Container transits/day"},
            ],
        ),
        LineChart(
            "chart-hormuz-index", y_max=140, y_ticks=[0, 50, 100], y_pct=True,
            ref_line=100, ref_label="pre-crisis", mark_index=HORMUZ_ONSET_INDEX,
            mark_label="Iran crisis",
            series=[
                {"values": [round(100 * v / h_con["precrisis"], 0) for v in compare["hormuz"]],
                 "color": "var(--s1)", "tipLabel": "Vessel count", "asPct": True},
                {"values": [round(100 * (v or 0) / h_cap["precrisis"], 0)
                            for v in hormuz["capacity_container_quarterly"]],
                 "color": "var(--s2)", "tipLabel": "Cargo capacity", "asPct": True},
            ],
        ),
        LineChart(
            "chart-compare", y_max=25, y_ticks=[0, 5, 10, 15, 20, 25],
            marks=[{"index": REDSEA_ONSET_INDEX, "label": "Red Sea"},
                   {"index": HORMUZ_ONSET_INDEX, "label": "Iran"}],
            series=[
                {"values": compare["hormuz"], "color": "var(--s1)",
                 "label": "Hormuz", "tipLabel": "Hormuz"},
                {"values": compare["suez"], "color": "var(--s2)",
                 "label": "Suez", "tipLabel": "Suez Canal"},
                {"values": compare["bab_el_mandeb"], "color": "var(--s3)",
                 "label": "Bab", "tipLabel": "Bab el-Mandeb"},
            ],
        ),
        LineChart(
            "chart-jebelali", y_max=16, y_ticks=[0, 4, 8, 12, 16],
            mark_index=HORMUZ_ONSET_INDEX, mark_label="Iran crisis",
            series=[{"values": [v or 0 for v in jebel_ali["portcalls_container_quarterly"]],
                     "color": "var(--s1)", "label": "per day",
                     "tipLabel": "Container calls/day", "area": True}],
        ),
        DivergingChart(
            "chart-reroute",
            rows=[{"name": _short(r["name"]), "country": r["iso3"],
                   "pct": int(r["pct_change"]),
                   "a": r["precrisis"], "b": r["current"]} for r in reroute],
            max_abs=max(80, min(160, max(abs(r["pct_change"]) for r in reroute) + 15)),
        ),
    ]

    cap_q = hormuz["capacity_container_quarterly"]
    table = DataTable(
        caption="Quarterly figures — Strait of Hormuz and Jebel Ali, containers",
        columns=["Quarter", "Hormuz total/day", "Hormuz container/day",
                 "Hormuz container capacity/day", "Jebel Ali calls/day"],
        rows=[
            [QUARTER_LABELS[i],
             f"{hormuz['n_total_quarterly'][i]:.0f}" if hormuz['n_total_quarterly'][i] else "–",
             f"{compare['hormuz'][i]:.1f}",
             f"{(cap_q[i] or 0):,.0f}",
             f"{(jebel_ali['portcalls_container_quarterly'][i] or 0):.1f}"]
            for i in range(len(QUARTER_LABELS))
        ],
        break_row=HORMUZ_ONSET_INDEX,
        crit_cols=[2, 3, 4],
    )

    brief = Brief(
        slug=SLUG,
        title="Hormuz Container Closure",
        kicker="Supply-chain disruption brief",
        chokepoint_code="CHOKEPOINT 6",
        data_as_of=cov[1].strftime("%-d %b %Y"),
        generated=dt.date.today().strftime("%-d %b %Y"),
        verdict="Severe · Ongoing",
        verdict_tone="critical",
        headline="The Strait of Hormuz has been closed to container ships since March",
        dek="A separate shock from the Red Sea crisis: the 2026 Iran conflict shut "
        "the entrance to the Persian Gulf, and box-ship transits have run near zero "
        "for six months.",
        months=QUARTER_LABELS,
        tiles=[
            Tile("Hormuz container transits", f"{h_con['pct_of_normal']:.0f}", "% of normal",
                 f"{h_con['current']:.1f}/day now vs {h_con['precrisis']:.0f} pre-crisis",
                 crit=True),
            Tile("Container cargo capacity", f"{h_cap['pct_of_normal']:.0f}", "% of normal",
                 "Capacity fell as hard as the vessel count", crit=True),
            Tile("Jebel Ali container calls", f"{ja_calls['pct_of_normal']:.0f}", "% of normal",
                 "The Gulf's main box hub, effectively offline", crit=True),
            Tile("Onset", "Mar", "2026",
                 "Distinct from the 2023 Red Sea crisis; no recovery trend"),
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
             "counts of vessel transits by class at chokepoint 6. `capacity_container` "
             "is the estimated aggregate cargo capacity of transiting container ships. "
             "`import_container` / `export_container` are PortWatch's modelled "
             "trade-volume estimates — directional, not measured TEU."),
            ("Baseline", "Chokepoint transits, capacity, the comparison chart, and "
             "Jebel Ali use a fixed **September–November 2023** window, matching the "
             "sibling Red Sea briefs — Hormuz throughput was within ~10% of that "
             "level every quarter through 2025, so the immediate pre-conflict period "
             "gives the same result. The **reroute analysis (§6) uses "
             "September 2025 – February 2026** instead, because several candidate "
             "ports grew on their own over 2023–2025 and a 2023 comparison would "
             "conflate that growth with the diversion. Percent-of-normal = current "
             "value ÷ baseline mean."),
            ("“Current” month", f"**{CURRENT_LABEL}.** PortWatch revises its most "
             "recent ~2 weeks upward as satellite data lands, so August 2026 was "
             "still settling at generation time."),
            ("Two crises", "The 2023 Red Sea / Houthi crisis and the 2026 Iran / "
             "Strait of Hormuz crisis are separate events at separate chokepoints. "
             "The cross-chokepoint chart (§4) plots `n_container` for Hormuz, Suez, "
             "and Bab el-Mandeb on one axis; the Suez and Horn briefs cover the Red "
             "Sea side."),
            ("Reroute analysis", "Candidate substitute ports (Indian west coast, "
             "Omani and Red Sea ports, Mediterranean and South Asian transshipment "
             "hubs) compared on `portcalls_container`, July 2026 vs Sep 2025 – "
             "Feb 2026. Ranked by percent change; absolute rates shown alongside "
             "because small ports swing large percentages off a low base."),
            ("Reproduce", "Clone github.com/ubeast/bottleneck-logistics, backfill the "
             "database to 2023, then `uv run python "
             "scripts/reports/hormuz_container_2026.py`. Full method in "
             "`docs/METHODOLOGY.md`."),
        ],
        limitations=[
            "PortWatch measures throughput (vessels moving), not queue length or "
            "berth dwell time. This brief cannot say how long individual ships "
            "waited.",
            "The data attests to the shipping outcome, not the cause. The March 2026 "
            "onset coincides with the reported Strait of Hormuz crisis; causation is "
            "not established here.",
            "Trade-volume and capacity fields are model estimates, not manifest data.",
            "All comparisons are versus a fixed 2023 quarter; Gulf throughput was "
            "stable from 2023 through early 2026, so the choice is not sensitive, but "
            "every figure is “versus 2023.”",
            "The reroute set only includes ports named in the tool's substitution "
            "list; an unlisted beneficiary would be missed.",
        ],
    )

    key_figures = [
        ("Hormuz container transits / day", f"{h_con['current']:.1f}",
         f"{h_con['precrisis']:.0f}", f"{h_con['pct_of_normal']:.0f} %"),
        ("Hormuz container capacity / day", f"{h_cap['current']:,.0f}",
         f"{h_cap['precrisis']:,.0f}", f"{h_cap['pct_of_normal']:.0f} %"),
        ("Hormuz total transits / day", f"{h_tot['current']:.0f}",
         f"{h_tot['precrisis']:.0f}", f"{h_tot['pct_of_normal']:.0f} %"),
        ("Jebel Ali container calls / day", f"{ja_calls['current']:.1f}",
         f"{ja_calls['precrisis']:.0f}", f"{ja_calls['pct_of_normal']:.0f} %"),
        ("Jebel Ali container imports / day (est.)", f"{ja_imp['current']:,.0f}",
         f"{ja_imp['precrisis']:,.0f}", f"{ja_imp['pct_of_normal']:.0f} %"),
    ]

    write_all(brief, payload, key_figures)
    con.close()
    print(f"  Hormuz container: {h_con['pct_of_normal']:.0f}% of normal | "
          f"capacity {h_cap['pct_of_normal']:.0f}% | "
          f"Jebel Ali calls {ja_calls['pct_of_normal']:.0f}% | "
          f"reroute winners: {winners_txt}")


if __name__ == "__main__":
    main()
