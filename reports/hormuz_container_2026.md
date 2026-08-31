# Hormuz Container Closure

**Supply-chain disruption brief — The Strait of Hormuz has been closed to container ships since March**

| | |
|---|---|
| **By** | Michael Schertz |
| **Tooling** | [`bottleneck-logistics`](https://github.com/ubeast/bottleneck-logistics) (open-source) |
| **Generated** | 30 Aug 2026 |
| **Data as of** | 23 Aug 2026 |
| **Source** | IMF PortWatch (`portwatch.imf.org`) |
| **Verdict** | Severe · Ongoing |

> Charts for this brief are in `hormuz_container_2026.html` and `hormuz_container_2026.pdf`. This Markdown version carries the same findings, the underlying monthly figures, and the full method.

---

## Key figures

| Metric | Now | Pre-crisis | vs baseline |
|---|--:|--:|--:|
| Hormuz container transits / day | 1.0 | 15 | **7 %** |
| Hormuz container capacity / day | 17,750 | 451,172 | **4 %** |
| Hormuz total transits / day | 10 | 92 | **11 %** |
| Jebel Ali container calls / day | 2.3 | 13 | **18 %** |
| Jebel Ali container imports / day (est.) | 42,047 | 243,342 | **17 %** |

---

## 1. The finding

*Container-ship transits through the Strait of Hormuz have run at roughly **7% of normal** since March 2026 — the Persian Gulf's box trade has effectively stopped.*

This is the **2026 Strait of Hormuz crisis**, not the Red Sea one. Different chokepoint, two years later: the Red Sea / Houthi disruption (late 2023) diverted the Asia–Europe route around Africa; the Iran conflict (March 2026) closed the entrance to the Persian Gulf.

IMF PortWatch counted **15 container transits per day** through Hormuz in the clean quarter of late 2023, and the level was steady at about 16 per day through 2025. Since March 2026 it has averaged **under one per day** — 1.0 in July. Container cargo capacity through the strait is at **4% of normal**. The collapse is uniform across classes — tankers are at **9%**, total transits at **11%** — the signature of a route-wide closure, not a commodity-specific restriction.

## 2. Stable for three years, then a wall

Hormuz traffic is normally seasonal but flat year to year. Container transits held between roughly 13 and 21 per day every quarter from 2023 through 2025 — the 2023 Red Sea crisis, visible as a cliff in the Suez and Bab el-Mandeb data, left Hormuz untouched, because the Gulf oil trade does not use the Red Sea.

Then the line falls off the table in the first quarter of 2026 and keeps falling into the second. There is no recovery trend through late August.

## 3. Blocked, not merely thinned

A fall in vessel *count* could mean fewer, larger ships moving the same cargo. It does not: PortWatch's estimate of the aggregate cargo *capacity* of transiting container ships is at **4% of pre-crisis** — as low as the count, or lower. The few box ships still using the strait are the smaller ones. Real throughput is gone, not redistributed onto bigger tonnage.

**Why this matters.** If the count fell while capacity held, a count-based alarm would be a false positive. Here both lines hit the floor together.

## 4. Two shocks, two chokepoints

*The 2024 line and the 2026 line are different events at different straits — and neither one spilled into the other.*

Put container transits through all three chokepoints on one axis and the picture separates cleanly. **Suez** and **Bab el-Mandeb** fall together in Q1 2024 — the Red Sea / Houthi crisis — and have held at that lower level ever since. **Hormuz** is flat through that whole period, then falls on its own in Q1–Q2 2026 — the Iran conflict.

The Red Sea route shows almost no *additional* dip in 2026: the Asia–Europe container trade had already left it, so the Iran crisis had nothing there to divert. The two disruptions stack in cost — the Cape reroute and the Gulf closure are both live — but they are independent in the data.

## 5. Jebel Ali goes dark

Jebel Ali (Dubai) is the Gulf's dominant container port and one of the ten busiest in the world. It sits *inside* the strait, and it tracked the chokepoint almost exactly: container port calls held at about 13 per day from 2023 through 2025, then **2.3** in July 2026 (**18% of normal**). Estimated container trade volume — imports and exports — is running at **17–22%** of pre-crisis.

## 6. Where the containers went

Cargo that would have moved through the Gulf has rerouted, and not to the usual transshipment hubs. Measured against the six months just before the crisis, container port calls have surged on the **Indian subcontinent's west coast** and at ports positioned *outside* the strait: Nhava Sheva +108%, Karachi +100%, Salalah +41%, Damietta +40%.

Saudi Arabia's Red Sea ports (Aqaba -21%, Port Said -29%, Jeddah -31%, Dammam -61%) are *down* — the Bab el-Mandeb disruption compounds the Gulf one there — and the mega-transshipment hubs that would normally absorb a shock (Colombo, Piraeus) are flat. This section uses the immediate pre-conflict window, not the 2023 baseline, because several of these ports grew on their own over 2023–2025.

## 7. Assessment

For container shipping the Strait of Hormuz has been functionally closed since March 2026, with no recovery trend through late August. The regional network has partly re-formed around it — Indian west-coast direct calls, Salalah, and Egyptian Mediterranean transshipment are the load-bearing alternatives — at a fraction of the lost volume and longer transit distances. This is a distinct shock from the still-unresolved Red Sea diversion; the two now run in parallel.

PortWatch measures vessel movements, not their causes: the March 2026 break coincides with the reported Strait of Hormuz crisis, but the data attests to the shipping outcome. Every figure is measured against a fixed 2023 quarter; because Gulf throughput was within ~10% of that level right through 2025, the reference choice does not move the finding.

---

## Method & provenance

Every figure in this brief is reproducible from a local database built by the open-source `bottleneck-logistics` tool and a single generator script. Nothing is hand-transcribed.

**Data source.** IMF PortWatch (portwatch.imf.org) — daily maritime activity estimated from satellite AIS on ~90,000 ships, via the UN Global Platform. Free public use with attribution. Backfill covers 1 Jan 2023 – 23 Aug 2026.

**What the numbers are.** `n_total` / `n_container` / `n_tanker` are counts of vessel transits by class at chokepoint 6. `capacity_container` is the estimated aggregate cargo capacity of transiting container ships. `import_container` / `export_container` are PortWatch's modelled trade-volume estimates — directional, not measured TEU.

**Baseline.** Chokepoint transits, capacity, the comparison chart, and Jebel Ali use a fixed **September–November 2023** window, matching the sibling Red Sea briefs — Hormuz throughput was within ~10% of that level every quarter through 2025, so the immediate pre-conflict period gives the same result. The **reroute analysis (§6) uses September 2025 – February 2026** instead, because several candidate ports grew on their own over 2023–2025 and a 2023 comparison would conflate that growth with the diversion. Percent-of-normal = current value ÷ baseline mean.

**“Current” month.** **July 2026.** PortWatch revises its most recent ~2 weeks upward as satellite data lands, so August 2026 was still settling at generation time.

**Two crises.** The 2023 Red Sea / Houthi crisis and the 2026 Iran / Strait of Hormuz crisis are separate events at separate chokepoints. The cross-chokepoint chart (§4) plots `n_container` for Hormuz, Suez, and Bab el-Mandeb on one axis; the Suez and Horn briefs cover the Red Sea side.

**Reroute analysis.** Candidate substitute ports (Indian west coast, Omani and Red Sea ports, Mediterranean and South Asian transshipment hubs) compared on `portcalls_container`, July 2026 vs Sep 2025 – Feb 2026. Ranked by percent change; absolute rates shown alongside because small ports swing large percentages off a low base.

**Reproduce.** Clone github.com/ubeast/bottleneck-logistics, backfill the database to 2023, then `uv run python scripts/reports/hormuz_container_2026.py`. Full method in `docs/METHODOLOGY.md`.

### Limitations

- PortWatch measures throughput (vessels moving), not queue length or berth dwell time. This brief cannot say how long individual ships waited.
- The data attests to the shipping outcome, not the cause. The March 2026 onset coincides with the reported Strait of Hormuz crisis; causation is not established here.
- Trade-volume and capacity fields are model estimates, not manifest data.
- All comparisons are versus a fixed 2023 quarter; Gulf throughput was stable from 2023 through early 2026, so the choice is not sensitive, but every figure is “versus 2023.”
- The reroute set only includes ports named in the tool's substitution list; an unlisted beneficiary would be missed.

---

*Michael Schertz · built with [`bottleneck-logistics`](https://github.com/ubeast/bottleneck-logistics), an open-source logistics bottleneck & opportunity identifier. Data © IMF PortWatch, used under its free public-use terms. This document reports analysis of public shipping data; it is not affiliated with or endorsed by the IMF.*
