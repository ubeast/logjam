# Bab el-Mandeb Watch

**Supply-chain disruption brief — The Red Sea's southern gate is still half shut — and may be tightening again**

| | |
|---|---|
| **By** | Michael Schertz |
| **Tooling** | [`bottleneck-logistics`](https://github.com/ubeast/bottleneck-logistics) (open-source) |
| **Generated** | 30 Aug 2026 |
| **Data as of** | 23 Aug 2026 |
| **Source** | IMF PortWatch (`portwatch.imf.org`) |
| **Verdict** | Ongoing · Possible Fresh Dip |

> Charts for this brief are in `horn_of_africa_2026.html` and `horn_of_africa_2026.pdf`. This Markdown version carries the same findings, the underlying monthly figures, and the full method.

---

## Key figures

| Metric | Now | Pre-crisis | vs baseline |
|---|--:|--:|--:|
| Strait total transits / day | 34 | 77 | **44 %** |
| Strait container transits / day | 5.3 | 19.5 | **27 %** |
| Strait container capacity / day | 78,235 | 1,061,053 | **7 %** |
| Strait tanker transits / day | 11.6 | 26.5 | **44 %** |
| Djibouti container calls / day | 2.0 | 1.6 | **+25 %** |

---

## 1. The finding

*The Bab el-Mandeb Strait — the strait the attacks actually target — is running at **44% of its pre-crisis traffic**, and for containers it is close to shut.*

The Bab el-Mandeb is the 20-mile gap between Yemen and Djibouti that every Suez-bound ship from Asia must pass. IMF PortWatch counts **77 transits per day** there in the clean quarter before the December 2023 escalation; in July 2026 it counts **34**.

By cargo class the picture matches the Suez Canal at the other end of the route: tankers back to **44%** of normal, containers at **27%** (5.3 per day vs 20), and container cargo capacity at just **7%** — the single most depressed figure in this brief. The container lines are gone; what still runs the strait is tankers and bulk carriers pricing in the war-risk premium.

## 2. Two and a half years, no container recovery

Across nine quarters the container line does not trend up. The strait settled into its disrupted level by mid-2024 and has held there. Total transits have recovered somewhat — tankers and dry bulk returning — but the containerised Asia–Europe trade that this route existed to carry has not.

This is the southern half of the same story the Suez brief tells from the northern end: one route, diverted whole, around the Cape of Good Hope, where container transits are up +233%.

## 3. Capacity says shut, not slow

Container *cargo capacity* through the strait is at **7% of pre-crisis** — lower than the vessel count, because the few container ships still transiting are small regional feeders, not mainline tonnage. Indexed against their own 2023 baselines, tankers have climbed back toward normal while containers sit near the floor and flat.

A route-wide hard closure would flatten every class equally. The gap between tankers and containers here is the market choosing: the passage is transitable if the cargo can absorb the risk and the premium, and scheduled container services cannot.

**Why this matters.** Container capacity at single-digit percent, sustained for two years, is the clearest signal in the dataset that this is a structural reroute and not a disruption waiting to clear.

## 4. A fresh dip in mid-2026 — worth watching

Total transits had actually ground back to a post-crisis high of about **37 per day** through the spring of 2026. Then they slipped: **34** in July and **28** in August 2026. Tanker transits fell alongside.

Two things temper this. The most recent month is provisional — PortWatch revises its last ~2 weeks upward as more satellite data lands, so August 2026 will likely be marked up. But the direction is consistent with the March 2026 Strait of Hormuz crisis pulling war-risk insurance capacity and underwriting appetite out of the whole region at once. This is a signal to track, not yet a confirmed second leg down.

## 5. Djibouti holds; the Saudi Red Sea coast does not

**Djibouti** has kept its place as the regional anchor — container port calls 1.6 → 2.0 per day, total calls roughly flat. It sits at the mouth of the strait, hosts multinational naval forces, and is where cargo that does run the gauntlet gets consolidated and bunkered. **Salalah**, just outside the strait in Oman, is up +11% as a safe-side transshipment alternative.

The port-level casualties are on the **Saudi Red Sea coast**, which has no way around its own geography: **Jeddah** container calls are down **55%** and **King Abdullah Port** down **67%** — both sit deep inside the risk zone with the Suez route as their only artery. East African feeder ports (Berbera, Mombasa) are down modestly, squeezed by thinner regional transshipment.

## 6. Assessment

The Bab el-Mandeb is a persistently degraded chokepoint — mixed traffic near **44% of pre-crisis**, containers effectively removed — with a possible fresh deterioration in the second half of 2026 that the next few PortWatch refreshes will confirm or revise away. Djibouti is the regional constant; the Saudi Red Sea ports are the clearest port-level loss; the Cape of Good Hope remains the route.

The same two caveats apply as to any PortWatch read: the data shows the shipping outcome, not its cause, and every figure is measured against a fixed 2023 quarter rather than a counterfactual 2026. The August 2026 data point specifically should be treated as provisional.

---

## Method & provenance

Every figure in this brief is reproducible from a local database built by the open-source `bottleneck-logistics` tool and a single generator script. Nothing is hand-transcribed.

**Data source.** IMF PortWatch (portwatch.imf.org) — daily maritime activity estimated from satellite AIS via the UN Global Platform. Free public use with attribution. Backfill covers 1 Jan 2023 – 23 Aug 2026.

**What the numbers are.** `n_total` / `n_container` / `n_tanker` are counts of vessel transits by class at chokepoint 4. `capacity_container` is the estimated aggregate cargo capacity of transiting container ships. `portcalls_container` is container-ship port calls.

**Baseline.** A fixed pre-crisis window, **September–November 2023**, not a rolling baseline. Percent-of-normal = current value ÷ pre-crisis mean.

**“Current” month.** **July 2026** for headline figures. The monthly watch chart runs through the latest month in the store, with its final point marked provisional — PortWatch under-reports its most recent ~2 weeks.

**Regional analysis.** Port-level comparison on `portcalls_container`, July 2026 vs the same 2023 window, for Djibouti, Salalah, the Saudi Red Sea ports, Aqaba, Port Sudan, and East African feeder ports. The Cape of Good Hope (chokepoint 7) is the route substitute.

**Reproduce.** Clone github.com/ubeast/bottleneck-logistics, backfill the database to 2023, then `uv run python scripts/reports/horn_of_africa_2026.py`. Full method in `docs/METHODOLOGY.md`.

### Limitations

- PortWatch measures throughput (vessels crossing the line), not queue length, berth dwell, or how long a diversion adds to a voyage.
- The data attests to the shipping outcome, not the cause. The Q1 2024 break and the mid-2026 dip coincide with reported events; causation is not established here.
- The most recent month is provisional and will likely be revised upward; the “fresh dip” finding is explicitly provisional.
- Capacity and trade-volume fields are model estimates, not manifest data.
- All comparisons are versus a fixed 2023 quarter.
- Regional port effects are shown only for a hand-picked candidate set.

---

*Michael Schertz · built with [`bottleneck-logistics`](https://github.com/ubeast/bottleneck-logistics), an open-source logistics bottleneck & opportunity identifier. Data © IMF PortWatch, used under its free public-use terms. This document reports analysis of public shipping data; it is not affiliated with or endorsed by the IMF.*
