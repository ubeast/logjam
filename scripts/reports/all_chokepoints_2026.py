#!/usr/bin/env python
"""Global Chokepoint Watch — all three 2026 briefs in one document.

Merges the three independently generated briefs — Suez Canal / Red Sea
(``suez_redsea_2026``), Bab el-Mandeb / Horn of Africa (``horn_of_africa_2026``),
and the Strait of Hormuz (``hormuz_container_2026``) — into a single report,
section by section, without recomputing or reinterpreting anything across
regions. Each of the three source scripts exposes a ``build()`` function that
returns its ``Brief`` plus the raw payload/key-figures used to write it; this
script calls all three, renumbers and namespaces their sections and charts so
they coexist on one page, and writes its own combined ``Brief``.

    uv run python scripts/reports/all_chokepoints_2026.py

Output:
    reports/data/all_chokepoints_2026.json
    reports/all_chokepoints_2026.md
    reports/all_chokepoints_2026.html

Run the three source scripts first (or just run this one — it imports and
calls their ``build()`` functions directly, so it always reflects their
current output). Needs a store backfilled to 2023, same as the source briefs.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _brief import Brief, DataTable, Section, Tile, write_all  # noqa: E402
from hormuz_container_2026 import build as build_hormuz  # noqa: E402
from horn_of_africa_2026 import build as build_horn  # noqa: E402
from suez_redsea_2026 import build as build_suez  # noqa: E402

SLUG = "all_chokepoints_2026"

_TONE_RANK = {"critical": 3, "serious": 2, "warning": 1, "good": 0}


def _namespace(
    brief: Brief, prefix: str, label: str, start_num: int
) -> tuple[list[Section], list[Any], int]:
    """Copy one brief's sections+charts, renumbered and chart-id-namespaced.

    Returns (sections, charts, next_start_num).
    """
    id_map = {c.chart_id: f"{prefix}-{c.chart_id}" for c in brief.charts}
    new_charts = [dataclasses.replace(c, chart_id=id_map[c.chart_id]) for c in brief.charts]

    new_sections: list[Section] = []
    num = start_num
    for s in brief.sections:
        new_figure = None
        if s.figure:
            new_figure = dict(s.figure)
            new_figure["chart_id"] = id_map[s.figure["chart_id"]]
        new_sections.append(
            dataclasses.replace(
                s, num=str(num), heading=f"{label} — {s.heading}", figure=new_figure
            )
        )
        num += 1
    return new_sections, new_charts, num


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def main() -> None:
    s_brief, s_payload, s_kf = build_suez()
    b_brief, b_payload, b_kf = build_horn()
    h_brief, h_payload, h_kf = build_hormuz()

    if not (s_brief.months == b_brief.months == h_brief.months):
        raise RuntimeError(
            "combined report requires all three briefs to share one quarterly "
            f"axis; got suez={s_brief.months!r} horn={b_brief.months!r} "
            f"hormuz={h_brief.months!r}"
        )
    months = s_brief.months

    if not (s_brief.data_as_of == b_brief.data_as_of == h_brief.data_as_of):
        data_as_of = max(s_brief.data_as_of, b_brief.data_as_of, h_brief.data_as_of)
    else:
        data_as_of = s_brief.data_as_of

    # Chronological order: Suez & Red Sea and Horn of Africa share the Dec 2023
    # Houthi/Red Sea crisis onset; Hormuz is a separate, later (Mar 2026) shock.
    regions = [
        (s_brief, "sz", "Suez & Red Sea"),
        (b_brief, "ba", "Horn of Africa"),
        (h_brief, "hz", "Hormuz"),
    ]

    sections: list[Section] = []
    charts: list[Any] = []
    num = 1
    for brief, prefix, label in regions:
        new_sections, new_charts, num = _namespace(brief, prefix, label, num)
        sections.extend(new_sections)
        charts.extend(new_charts)

    seen_chart_ids = [c.chart_id for c in charts]
    if len(seen_chart_ids) != len(set(seen_chart_ids)):
        raise RuntimeError(f"duplicate chart_id after namespacing: {seen_chart_ids}")

    tiles: list[Tile] = (
        list(s_brief.tiles[:2]) + list(b_brief.tiles[:2]) + list(h_brief.tiles[:2])
    )

    # Fresh top-level comparison table — the three source tables have
    # incompatible columns, so this flattens each brief's key_figures instead.
    region_kf = [
        ("Suez & Red Sea", s_kf),
        ("Horn of Africa", b_kf),
        ("Hormuz", h_kf),
    ]
    table_rows = [
        [region, metric, now, base, pn]
        for region, kf in region_kf
        for metric, now, base, pn in kf
    ]
    table = DataTable(
        caption="Key figures — all three chokepoints",
        columns=["Chokepoint", "Metric", "Now", "Pre-crisis", "vs baseline"],
        rows=table_rows,
    )
    key_figures = [
        (f"{region} — {metric}", now, base, pn)
        for region, kf in region_kf
        for metric, now, base, pn in kf
    ]

    tones = [s_brief.verdict_tone, b_brief.verdict_tone, h_brief.verdict_tone]
    worst_tone = max(tones, key=lambda t: _TONE_RANK.get(t, 0))
    worst_verdict = {
        s_brief.verdict_tone: s_brief.verdict,
        b_brief.verdict_tone: b_brief.verdict,
        h_brief.verdict_tone: h_brief.verdict,
    }[worst_tone]

    payload = {
        "hormuz": h_payload,
        "suez_redsea": s_payload,
        "horn_of_africa": b_payload,
    }

    brief = Brief(
        slug=SLUG,
        title="Global Chokepoint Watch — 2026",
        kicker="Global chokepoint watch",
        chokepoint_code="CHOKEPOINTS 1 · 4 · 6",
        data_as_of=data_as_of,
        generated=h_brief.generated,
        verdict=worst_verdict,
        verdict_tone=worst_tone,
        headline="Three chokepoints, two crises, one shipping network under strain",
        dek="This document merges three independently generated briefs — Suez "
        "Canal / Red Sea, Bab el-Mandeb / Horn of Africa, and the Strait of "
        "Hormuz — into a single read of 2026's maritime disruptions. The Red "
        "Sea crisis (Dec 2023) and the Hormuz crisis (Mar 2026) are distinct "
        "events at distinct chokepoints, told here side by side, not as cause "
        "and effect.",
        months=months,
        tiles=tiles,
        sections=sections,
        charts=charts,
        table=table,
        method_dl=[
            ("Data source", "IMF PortWatch (portwatch.imf.org) — daily maritime "
             "activity estimated from satellite AIS on ~90,000 ships, via the UN "
             "Global Platform. Free public use with attribution. Backfill covers "
             f"1 Jan 2023 – {data_as_of}."),
            ("Baseline", "Each region compares current data to a **fixed "
             "pre-crisis 2023 quarter** (September–November), not a rolling "
             "baseline — by 2026 a rolling baseline would have absorbed a "
             "multi-year diversion into its own definition of “normal.” "
             "Percent-of-normal = current value ÷ that fixed baseline mean."),
            ("What this document is", "This brief merges three independently "
             "generated reports — Suez Canal / Red Sea, Bab el-Mandeb / Horn of "
             "Africa, and Strait of Hormuz — section by section, into one "
             "document. Each section is reproduced from its source brief; "
             "nothing here is recomputed or reinterpreted across regions."),
            ("Two separate crises", "The 2023 Red Sea / Houthi crisis (Suez, "
             "Bab el-Mandeb) and the 2026 Iran / Strait of Hormuz crisis are "
             "distinct events at distinct chokepoints, roughly two years apart. "
             "This document tells them side by side; it does not imply either "
             "caused the other."),
            ("Reproduce", "Clone github.com/ubeast/logjam, backfill the "
             "database to 2023, then run `suez_redsea_2026.py`, "
             "`horn_of_africa_2026.py`, and `hormuz_container_2026.py`, "
             "followed by `uv run python "
             "scripts/reports/all_chokepoints_2026.py`. Full method in "
             "`docs/METHODOLOGY.md`."),
        ],
        limitations=_dedupe(
            s_brief.limitations + b_brief.limitations + h_brief.limitations
        ),
    )

    write_all(brief, payload, key_figures)
    print(
        f"  Global watch: Suez {s_kf[0][3]} | Bab el-Mandeb {b_kf[0][3]} | "
        f"Hormuz {h_kf[0][3]}"
    )


if __name__ == "__main__":
    main()
