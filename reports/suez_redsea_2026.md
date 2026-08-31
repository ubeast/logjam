# Suez Canal Recovery Check

**Supply-chain disruption brief — Two years on, the Suez Canal is back to half strength — and containers haven't returned at all**

| | |
|---|---|
| **By** | Michael Schertz |
| **Tooling** | [`bottleneck-logistics`](https://github.com/ubeast/bottleneck-logistics) (open-source) |
| **Generated** | 30 Aug 2026 |
| **Data as of** | 23 Aug 2026 |
| **Source** | IMF PortWatch (`portwatch.imf.org`) |
| **Verdict** | Ongoing · No Container Recovery |

> Charts for this brief are in `suez_redsea_2026.html` and `suez_redsea_2026.pdf`. This Markdown version carries the same findings, the underlying monthly figures, and the full method.

---

## Key figures

| Metric | Now | Pre-crisis | vs baseline |
|---|--:|--:|--:|
| Suez total transits / day | 42 | 76 | **55 %** |
| Suez container transits / day | 9.2 | 20.2 | **46 %** |
| Suez container capacity / day | 287,127 | 1,124,014 | **26 %** |
| Suez tanker transits / day | 15.7 | 25.0 | **63 %** |
| Cape of Good Hope container transits / day | 20 | 6 | **+233 %** |

---

## 1. The finding

*Two and a half years on, the Suez Canal carries about **55% of its pre-crisis traffic** — and for containers, essentially none of it has come back.*

IMF PortWatch counts vessel transits at 28 maritime chokepoints from satellite AIS. Through the Suez Canal, total transits averaged **76 per day** in the clean quarter before the December 2023 escalation of attacks on Red Sea shipping. In July 2026 they averaged **42 per day** — a partial recovery from the 2024 trough, but still a third below normal.

Split by cargo class, the recovery is lopsided. Tanker transits are back to **63%** of pre-crisis. Container transits sit at **46%** — 9 per day against 20 before — and container *cargo capacity* through the canal is at just **26%**. The box trade did not slow down and recover; it left.

## 2. The diversion held

The break is visible as a single step down in the first quarter of 2024 and a flat line since. There is no upward trajectory in the container series across nine quarters — the disruption is not resolving, it has become the operating baseline.

Total transits have ground back a little, from the 2024 low toward 42 per day, entirely on the back of tankers and dry bulk. Those cargoes are more willing to price in the war-risk insurance premium and the longer exposure; container lines, running fixed weekly schedules, rerouted wholesale and have stayed rerouted.

## 3. Blocked for boxes, not for barrels

Indexing each cargo class to its own pre-crisis average makes the split unmistakable. Tankers and dry bulk have clawed back toward normal; containers are pinned near the floor. Container cargo capacity — the aggregate slot capacity of the ships still using the canal — is at **26% of normal**, below even the vessel count, because the container ships that do transit are the smaller feeders, not the 20,000-TEU mainliners.

A uniform collapse across every class would point to a hard closure. This selective pattern is the signature of a commercial reroute: the route is open, but for scheduled container services the math no longer works.

**Why this matters.** A transit count alone could be read as “slowly recovering.” Capacity confirms it is not: for containers, real throughput through Suez is a small fraction of what it was, and flat.

## 4. The Cape took the load

*Every box that left the Red Sea route had to go somewhere. It went around Africa — and has stayed there.*

Container transits past the Cape of Good Hope have risen from **6 per day** pre-crisis to **20 per day** — up **+233%** — and container cargo capacity on the route is up **+526%**, from 193,096 to 1,208,567 per day. The Cape line shows the same single step in early 2024 as Suez, in the opposite direction, and the same flat plateau since.

The cost is distance. Asia–North Europe via the Cape is roughly 3,500 nautical miles and 10–14 days longer than via Suez, which ties up ships, burns bunkers, and has kept effective fleet capacity tight across the whole Asia–Europe trade for two years.

## 5. Who lost the transshipment

There is no clear port-level winner, because the reroute is a longer version of the same voyage rather than a switch to a new hub. The clear *losers* are the Mediterranean transshipment hubs that fed the Suez route: Marsaxlokk -14%, Piraeus -23%, Algeciras -24%. They handled Asia-origin boxes that came through the canal for onward distribution; that feeder role has thinned.

Egypt's own canal-adjacent container ports (Port Said, Damietta) are roughly flat — they were never the point of the route. The one consistent gainer is **Colombo**, up as a consolidation point where Asian cargo is aggregated onto the big ships before the long haul around the Cape.

## 6. Assessment

The Suez Canal in 2026 is a structurally smaller artery. Mixed traffic has stabilised near **55% of pre-crisis**; containerised trade shows **no recovery trend** after nine quarters and runs at well under half its former volume. The Cape of Good Hope is the load-bearing alternative and there is no sign of that unwinding.

Two caveats bound this read. PortWatch measures vessel movements, not their causes — the 2024 break coincides with the reported Red Sea shipping crisis, but the data attests to the outcome. And the pre-crisis window is a fixed 2023 quarter; that is the right comparison for a structural shift of this kind, but it means every figure here is “versus 2023,” not versus a hypothetical undisrupted 2026.

---

## Method & provenance

Every figure in this brief is reproducible from a local database built by the open-source `bottleneck-logistics` tool and a single generator script. Nothing is hand-transcribed.

**Data source.** IMF PortWatch (portwatch.imf.org) — daily maritime activity estimated from satellite AIS on ~90,000 ships, via the UN Global Platform. Free public use with attribution. Backfill covers 1 Jan 2023 – 23 Aug 2026.

**What the numbers are.** `n_total` / `n_container` / `n_tanker` are counts of vessel transits by class. `capacity_container` is the estimated aggregate cargo capacity of transiting container ships. `portcalls_container` is container-ship port calls.

**Baseline.** A fixed pre-crisis window, **September–November 2023** — the last clean quarter before the December 2023 escalation — not a rolling baseline, which by 2026 would treat the diverted level as normal. Percent-of-normal = current value ÷ pre-crisis mean.

**“Current” month.** **July 2026.** PortWatch revises its most recent ~2 weeks upward as satellite data lands, so the latest month in the store is still settling and is not used for headline figures.

**Reroute analysis.** The Cape of Good Hope is the route substitute (`n_container`, chokepoint 7). Port-level comparison on `portcalls_container`, July 2026 vs the same 2023 window, for East Mediterranean transshipment hubs, Egyptian canal ports, Colombo, and South African / Red Sea ports.

**Reproduce.** Clone github.com/ubeast/bottleneck-logistics, backfill the database to 2023, then `uv run python scripts/reports/suez_redsea_2026.py`. Full method in `docs/METHODOLOGY.md`.

### Limitations

- PortWatch measures throughput (vessels moving), not queue length, berth dwell, or voyage duration. This brief cannot quantify the added transit time around the Cape beyond the standard distance estimate.
- The data attests to the shipping outcome, not the cause. The Q1 2024 break coincides with the reported Red Sea crisis; causation is not established here.
- Capacity and trade-volume fields are model estimates, not manifest data.
- All comparisons are versus a fixed 2023 quarter — “versus pre-crisis,” not versus a counterfactual undisrupted 2026.
- Port-level effects are shown only for a hand-picked candidate set; an unlisted beneficiary or casualty would be missed.

---

*Michael Schertz · built with [`bottleneck-logistics`](https://github.com/ubeast/bottleneck-logistics), an open-source logistics bottleneck & opportunity identifier. Data © IMF PortWatch, used under its free public-use terms. This document reports analysis of public shipping data; it is not affiliated with or endorsed by the IMF.*
