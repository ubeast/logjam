# Global Chokepoint Map

**Reference index — Every chokepoint and port from the four 2026 briefs, on one map**

| | |
|---|---|
| **By** | Michael Schertz |
| **Tooling** | [`logjam`](https://github.com/ubeast/logjam) (open-source) |
| **Generated** | 15 Sep 2026 |
| **Data as of** | 15 Sep 2026 |
| **Source** | IMF PortWatch (`portwatch.imf.org`) |
| **Verdict** | Reference · Index |

> Charts for this brief are in `global_map_2026.html` and `global_map_2026.pdf`. This Markdown version carries the same findings, the underlying monthly figures, and the full method.

---

## Key figures

| Metric | Now | Pre-crisis | vs baseline |
|---|--:|--:|--:|
| Chokepoints mapped | 3 | — | **—** |
| Ports mapped | 15 | — | **—** |
| Source briefs merged | 4 | — | **—** |

---

## 1. Everything, in one frame

18 chokepoints and ports from the four briefs, deduplicated where the same port appeared on more than one brief's map (5 names collided; the most specific or most recent brief's version was kept - see §2) and drawn on the same basemap used by the Suez & Red Sea brief (the widest of the three basemaps this tool has built). Bubble color follows each point's own brief: green gained container traffic against its own baseline, red lost it. Bubble size is the absolute daily change, again by each point's own brief - not on a common scale across briefs.

## 2. Why the numbers here are not one comparison

The four briefs do not all measure “current vs. baseline” the same way. The Suez & Red Sea and Horn of Africa briefs compare July 2026 against a fixed September-November 2023 pre-crisis window. The Hormuz and Djibouti Port briefs instead compare July 2026 against September 2025-February 2026, the immediate pre-diversion period, because several of their candidate ports grew for unrelated reasons between 2023 and 2025 and a 2023 comparison would conflate that growth with the diversion itself.

That means a point showing “+25%” from the Djibouti Port brief and a point showing “+25%” from the Suez & Red Sea brief are not the same kind of twenty-five percent - they are measured from different starting points. This map is a geographic index of what the four briefs found, not a recomputed, unified comparison. For the exact methodology and figures behind any single point, read that point's own brief - named in its tooltip and in the table at the end of this page.

---

## Method & provenance

Every figure in this brief is reproducible from a local database built by the open-source `logjam` tool and a single generator script. Nothing is hand-transcribed.

**What this is.** A geographic index built from the already-published map data of four independently generated briefs (Hormuz, Suez & Red Sea, Horn of Africa, Djibouti Port), not a new database query or a recomputed comparison. Every figure traces back to one of those four briefs' own `reports/data/*.json` payload.

**Baselines differ by brief.** The Suez & Red Sea and Horn of Africa briefs compare against a fixed September-November 2023 pre-crisis quarter. The Hormuz and Djibouti Port briefs compare against September 2025-February 2026 instead, for their reroute/competitor reads specifically. Do not compare percent-change magnitudes across points from different source briefs - compare only within one brief, or read the underlying brief for the full picture.

**Deduplication.** When the same port appeared on more than one source brief's map, this script kept one version, by a fixed priority order (Djibouti Port brief, then Horn of Africa, then Suez & Red Sea, then Hormuz - the more specific or more recent brief about that port's region wins). The table above and each point's tooltip name which brief's version is shown.

**Basemap.** The 'corridor' basemap (the same one the Suez & Red Sea brief uses) - the widest of the three basemaps this tool has built. A small number of points from the source briefs can fall outside its frame; any such point is listed in the 'Out of frame' tile above and named in §1's figure caption, and is not silently dropped.

**Reproduce.** Generate the four source briefs first (`uv run python scripts/reports/hormuz_container_2026.py`, `suez_redsea_2026.py`, `horn_of_africa_2026.py`, `djibouti_port_2026.py`), then `uv run python scripts/reports/global_map_2026.py`. Full method in `docs/METHODOLOGY.md`.

### Limitations

- This is an index of the four briefs' own map data, not an independent analysis - any error or judgment call in a source brief (its baseline window, its port candidate list, its rounding) carries through to this map unchanged.
- Percent-change and absolute-change figures are not on a common baseline across source briefs; see §2. Do not read this map as a single ranked comparison of who gained or lost most.
- Points outside the 'corridor' basemap's frame are omitted from the map (though listed in the tiles/caption above), not relocated or approximated: Mombasa (Djibouti Port brief).
- Where the same port appeared in more than one source brief with different figures, only one version is shown here (see §2's deduplication note) - the other brief's figure for that same port may differ and is not shown.

---

*Michael Schertz · built with [`logjam`](https://github.com/ubeast/logjam), an open-source logistics bottleneck & opportunity identifier. Data © IMF PortWatch, used under its free public-use terms. This document reports analysis of public shipping data; it is not affiliated with or endorsed by the IMF.*
