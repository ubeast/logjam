# Carrier Routes

**Reference · illustrative seed set — Direct calls vs. bus-stop strings: real carrier rotations on one map**

| | |
|---|---|
| **By** | Michael Schertz |
| **Tooling** | [`logjam`](https://github.com/ubeast/logjam) (open-source) |
| **Generated** | 15 Sep 2026 |
| **Data as of** | 15 Sep 2026 |
| **Source** | IMF PortWatch (`portwatch.imf.org`) |
| **Verdict** | Reference · Illustrative |

> Charts for this brief are in `carrier_routes_2026.html` and `carrier_routes_2026.pdf`. This Markdown version carries the same findings, the underlying monthly figures, and the full method.

---

## Key figures

| Metric | Now | Pre-crisis | vs baseline |
|---|--:|--:|--:|
| Services plotted | 6 | — | **—** |
| Ports on this map | 23 | — | **—** |
| Services with published transit times | 1 | — | **—** |

---

## 1. Nine real services, one frame

Every line is a real, currently published carrier rotation — not a simplified trade-lane arrow. 6 of 9 loaded services have at least two calls inside this basemap's frame and are drawn; the rest (Maersk's Asia-Europe strings, which spend most of their rotation in the Far East and North Europe) mostly fall outside it. Where a service's rotation leaves and re-enters this frame, the drawn line connects only its in-frame calls, in sailing order — it does not draw the great-circle path through the ports this basemap can't show.

## 2. Direct call or bus stop? Ask a specific pair

This map answers 'where do these services go'; it doesn't rank them for a specific shipment. For that, `logjam carrier-route "<origin>" "<destination>"` finds every loaded service touching both ports, in that sailing order, and reports whether it's a direct call or how many stops sit between them, plus a real transit time where the carrier publishes one (currently only CMA CGM MEDEX) or a clearly labeled distance/speed estimate otherwise. Example: `logjam carrier-route "Djibouti" "Piraeus"`.

**Every loaded service**

| Carrier | Service | Route | Calls plotted | Real transit data |
|---|--:|--:|--:|--:|
| Maersk | AE1 | Cape of Good Hope | 1/9 in frame | no — CLI shows an estimate |
| Maersk | AE2 | Cape of Good Hope | 2/9 in frame | no — CLI shows an estimate |
| Maersk | AE3 | Cape of Good Hope | 0/9 in frame | no — CLI shows an estimate |
| Maersk | AE5 | Cape of Good Hope | 1/9 in frame | no — CLI shows an estimate |
| Maersk | AE11 | Cape of Good Hope | 3/10 in frame | no — CLI shows an estimate |
| Maersk | AE12 | Suez Canal | 2/8 in frame | no — CLI shows an estimate |
| Maersk | AE15 | Suez Canal | 3/8 in frame | no — CLI shows an estimate |
| CMA CGM | MEDEX | Suez Canal | 13/15 in frame | yes (MEDEX-style matrix) |
| CMA CGM | BIGEX 1 | Gulf (intra-regional, no Suez/Cape transit) | 8/8 in frame | no — CLI shows an estimate |

---

## Method & provenance

Every figure in this brief is reproducible from a local database built by the open-source `logjam` tool and a single generator script. Nothing is hand-transcribed.

**What this is.** A small, hand-curated seed set of real named container-service rotations, fetched from carrier network publications (Maersk's own Asia-Europe network update page; CMA CGM's own MEDEX and BIGEX 1 service flyers) in September 2026 — not derived from PortWatch, not an exhaustive model of global container shipping. See `src/logjam/resources/carrier_routes.yaml` for each service's exact source and to add more.

**Direct vs. stops.** Counted from each service's own published rotation order, walking forward from origin to destination, wrapping at most once around the loop (a real weekly string repeats). The reverse pair can match the same service with a different stop count — going the long way round costs more — so it is not assumed symmetric. A port a service reaches only 'in transshipment' (its vessel doesn't call there directly) doesn't count as a stop.

**Real vs. estimated transit time.** Only CMA CGM's MEDEX service publishes a from/to transit-time matrix (its April 2026 flyer, non-contractual). Every other service here has no published transit time; both this report and the `carrier-route` CLI command show a distance/speed estimate instead (great-circle distance along the sailed path ÷ an assumed 18kn) and label it 'estimated', never blending it with a published figure.

**Basemap.** The 'corridor' basemap (the same one the Suez & Red Sea brief uses) — the widest of the three basemaps this tool has built. Most of the Maersk Asia-Europe strings' Far East / North Europe calls fall outside its frame and aren't drawn; see §1.

**Reproduce.** `uv run python scripts/reports/carrier_routes_2026.py`. Full method in `docs/METHODOLOGY.md`.

### Limitations

- Nine services is a seed set illustrating the idea, not a survey of global container shipping — most carriers' most services aren't modeled here.
- Only CMA CGM MEDEX has a published transit-time matrix; every other transit time shown anywhere in this report or the CLI is a distance/speed estimate, and a rough one — it counts steaming time only and excludes port dwell, so it understates any real multi-stop transit.
- MEDEX's own published matrix is not required to arithmetically reconcile with the simplified single-pass rotation order used for stop-counting — CMA CGM's own flyer shows MEDEX as a pendulum string calling some ports more than once per loop, which the simplified order here doesn't reconstruct. See the comments in `carrier_routes.yaml`.
- Port coordinates are approximate port-city lookups, not PortWatch-sourced, and are not used anywhere else in this tool.
- Ports outside the 'corridor' basemap's frame are not drawn: Aarhus, Antwerp, Bremerhaven, Fos, Genoa, Gothenburg, Gwangyang, Hamburg, Koper, La Spezia, London Gateway, Ningbo, Qingdao, Rijeka, Rotterdam, Shanghai, Singapore, Southampton, Tanjung Pelepas, Vado Ligure, Wilhelmshaven, Yantian.

---

*Michael Schertz · built with [`logjam`](https://github.com/ubeast/logjam), an open-source logistics bottleneck & opportunity identifier. Data © IMF PortWatch, used under its free public-use terms. This document reports analysis of public shipping data; it is not affiliated with or endorsed by the IMF.*
