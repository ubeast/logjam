# Djibouti Port Watch

**Supply-chain status brief — Djibouti held through the Red Sea crisis — and is now running close to its own ceiling**

| | |
|---|---|
| **By** | Michael Schertz |
| **Tooling** | [`logjam`](https://github.com/ubeast/logjam) (open-source) |
| **Generated** | 15 Sep 2026 |
| **Data as of** | 13 Sep 2026 |
| **Source** | IMF PortWatch (`portwatch.imf.org`) |
| **Verdict** | Holding · Near Capacity |

> Charts for this brief are in `djibouti_port_2026.html` and `djibouti_port_2026.pdf`. This Markdown version carries the same findings, the underlying monthly figures, and the full method.

---

## Key figures

| Metric | Now | Pre-crisis | vs baseline |
|---|--:|--:|--:|
| Djibouti container port calls / day | 2.0 | 1.6 | **125 %** |
| Djibouti container exports / day (est.) | 3,739 | 1,478 | **253 %** |
| Djibouti container imports / day (est.) | 8,741 | 14,606 | **60 %** |
| Djibouti own-peak utilization | 98 % | 2.03/day peak | **maxed** |

---

## 1. The finding

*Djibouti's container port calls are up **+25%** since the Bab el-Mandeb crisis began — a real, if modest, gain. But it has pushed the port close to the busiest level it has ever recorded, and the gain is not uniform: export volume has surged while import volume has fallen.*

IMF PortWatch counted **1.6 container port calls per day** at Djibouti in the clean quarter before the December 2023 Red Sea escalation; by July 2026 that had risen to **2.0** — **125% of its pre-crisis level**. Total port calls across every vessel class are essentially flat (3.8 → 3.6/day), which means the gain is specifically in container traffic, not a general uptick.

The cargo-volume estimates tell a more mixed story than the call count alone. Djibouti's estimated **container exports** are up **+153%** — more than double their pre-crisis level — while estimated **container imports** are **down 40%**. A port doing more consolidation and re-export work while its own import demand softens is a different story than simple growth.

## 2. A modest, gradual step up — not a boom

Djibouti's container calls do not show a sharp jump at the December 2023 crisis onset the way the strait itself does. The port was already the region's busiest transshipment and consolidation hub before the crisis, and its call count has climbed gradually rather than snapping to a new level — consistent with a port absorbing overflow demand at the margin, not one suddenly rerouted onto.

## 3. Calls up, but the cargo mix flipped

Set import and export container volume side by side, indexed to their own pre-crisis levels, and they diverge sharply. Exports climb through the period and are now running at **253% of pre-crisis**; imports slide and sit at **60%**. Djibouti's own trade volume (much of it landlocked Ethiopia's import corridor) looks softer, even as the port handles more container calls overall — consistent with more transshipment and consolidation traffic passing through without being destined for Djibouti itself.

**Why this matters.** A rising call count with falling import volume is not the same finding as a port simply booming. It points to a shift in what kind of traffic Djibouti is handling, not just how much.

## 4. Who else is holding in the region

Measured against the immediate pre-diversion window (not the 2023 baseline, to avoid conflating pre-existing growth with the crisis), Djibouti's container calls are **+5%**. **Salalah**, just outside the strait in Oman, is the region's biggest recent gainer at **+41%**. **Mombasa** is down **17%**, and the **Saudi Red Sea coast** — Jeddah (-31%) and King Abdullah Port (+100%) — remains the deepest regional loss, even where the percentage change looks like a recovery: King Abdullah's recent window is measured off an already-collapsed base, not a return to its pre-crisis level.

**Regional container port calls — recent window vs July 2026**

| Port | Baseline /day | Jul 2026 /day | Change |
|---|--:|--:|--:|
| King Abdullah | 0.4 | 0.8 | +100% |
| Salalah | 2.2 | 3.1 | +41% |
| Port Sudan | 0.4 | 0.5 | +25% |
| Djibouti | 1.9 | 2.0 | +5% |
| Mombasa | 1.8 | 1.5 | -17% |
| Jeddah | 4.5 | 3.1 | -31% |

## 5. Near its own ceiling

*PortWatch publishes no berth or design capacity, so each port's own busiest month on record stands in as a floor estimate of its ceiling. On that test, the region's two steadiest ports are also its fullest.*

Djibouti's July 2026 container calls sit at **98% of its own busiest month** on record since 2023 (Sep 2025, 2.03/day) — effectively at the ceiling it has ever demonstrated it can sustain. Salalah is nearly identical, at **96%** of its own record month, if it has enough history to measure. The two ports carrying the region's diverted container demand are both running close to the busiest they have ever been.

That is a meaningful headroom constraint: it does not mean Djibouti cannot handle more cargo at all — bigger ships, longer dwell, or new berths could still absorb volume that call counts don't capture — but on the metric PortWatch actually measures, there is little precedent for Djibouti running materially busier than it is right now.

## 6. The regional picture, mapped

Djibouti and Salalah hold as the regional anchors — both near their own historic ceilings (§5); the Saudi Red Sea ports remain the deepest losses, still well below their pre-crisis levels even where the recent-window percentage looks like a bounce.

## 7. Assessment

Djibouti has held its position as the Horn of Africa's regional anchor port through the Bab el-Mandeb crisis and picked up a modest, real gain in container calls (125% of pre-crisis) alongside a much larger shift toward export/consolidation cargo. That gain has consumed most of the port's demonstrated headroom: it is now running near the busiest level it has ever recorded, alongside Salalah, the only other regional port with a comparable story. For a logistics planner, the takeaway is not that Djibouti is an open safety valve for further Gulf of Aden diversion — it is closer to full than any other port in this set.

As with the other briefs in this series: PortWatch measures vessel movements and modelled cargo volume, not queue length, berth dwell, or cause. The December 2023 regional context and Djibouti's gradual gain are correlated in time; causation is not established here.

---

## Method & provenance

Every figure in this brief is reproducible from a local database built by the open-source `logjam` tool and a single generator script. Nothing is hand-transcribed.

**Data source.** IMF PortWatch (portwatch.imf.org) — daily maritime activity estimated from satellite AIS via the UN Global Platform. Free public use with attribution. Backfill covers 1 Jan 2023 – 13 Sep 2026.

**What the numbers are.** `portcalls_container` is a count of container-ship port calls. `import_container` / `export_container` are PortWatch's modelled trade-volume estimates — directional, not measured TEU. Ports (unlike chokepoints) have no `capacity_container` field in this dataset, so this brief reads call counts and modelled volume, not aggregate vessel capacity.

**Baseline.** The headline figures (§1-§3) use a fixed **September–November 2023** window, matching the sibling briefs. The regional competitor comparison, absorption read, and map (§4-§6) use the immediate pre-diversion window, **September 2025 – February 2026**, instead — several candidate ports grew or shrank on their own over 2023-2025, and a 2023 comparison would conflate that with the crisis response. Percent-of-normal = current value ÷ baseline mean.

**“Current” month.** **July 2026.** PortWatch revises its most recent ~2 weeks upward as satellite data lands, so August 2026 was still settling at generation time.

**Regional context.** Djibouti sits at the mouth of the Bab el-Mandeb Strait, the subject of the companion `horn_of_africa_2026` brief. This brief does not re-derive the strait's own transit figures; it focuses on Djibouti and its regional competitor ports.

**Absorption / capacity.** PortWatch publishes no berth or design capacity for ports, so each port's ceiling is proxied by its **busiest calendar month on record since January 2023** (highest monthly average of `portcalls_container`). This is a **floor estimate** of true capacity — a port that never reached its true limit in this window looks fuller than it is — and it counts vessel calls, not container volume or berth-hours; a port taking larger ships or running longer dwell could absorb more than its call count implies.

**Map.** Basemap is Natural Earth 10m land and national boundary lines (public domain), clipped to the region (`redsea` window, shared with the Horn of Africa brief), simplified, and projected with Web Mercator in the browser — no map tiles, no network at render time. Port coordinates come from PortWatch's own port database.

**Reproduce.** Clone github.com/ubeast/logjam, backfill the database to 2023, then `uv run python scripts/reports/djibouti_port_2026.py`. Full method in `docs/METHODOLOGY.md`.

### Limitations

- PortWatch measures throughput (vessels moving), not queue length or berth dwell time. This brief cannot say how long individual ships waited, or how full they were.
- The data attests to the shipping outcome, not the cause. Djibouti's gradual gain coincides with the Bab el-Mandeb crisis; causation is not established here.
- Port-level `portcalls_container` does not distinguish transshipment or consolidation cargo from freight actually originating in or destined for Djibouti — the import/export divergence in §3 is suggestive, not a direct measurement of cargo purpose.
- Trade-volume fields (`import_container` / `export_container`) are model estimates, not manifest data.
- The regional competitor set only includes ports named in this script's candidate list; an unlisted beneficiary would be missed.
- The absorption read uses each port's busiest month since 2023 as a ceiling proxy — a floor estimate of true capacity — and counts vessel calls, not container volume; a port taking larger ships absorbs more than its call count implies.

---

*Michael Schertz · built with [`logjam`](https://github.com/ubeast/logjam), an open-source logistics bottleneck & opportunity identifier. Data © IMF PortWatch, used under its free public-use terms. This document reports analysis of public shipping data; it is not affiliated with or endorsed by the IMF.*
