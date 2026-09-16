"""Shared machinery for supply-chain disruption briefs.

A brief (Hormuz, Suez / Red Sea, Horn of Africa, ...) is a fixed-window
before/after read of PortWatch data for one chokepoint plus a reroute analysis.
Each brief script:

1. queries the local DuckDB store through the helpers here,
2. assembles a ``payload`` dict and writes it to ``reports/data/<slug>.json``
   (the reproducible record - every figure the brief cites),
3. hands ``payload`` plus human-written narrative to :func:`render_markdown`
   and :func:`render_html`, which emit ``reports/<slug>.md`` / ``.html``.

The narrative prose is written by a person (it interprets the data), but every
number in it comes from ``payload`` via f-strings, so re-running the script
after a ``logjam refresh`` regenerates a consistent brief.

Design note: the HTML CSS and the SVG chart library are lifted verbatim from
the first brief (``hormuz_container_2026``) so all briefs share one visual
system. Only the content is parametrised.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from logjam.config import settings

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
DATA_DIR = REPORTS_DIR / "data"
REPO_URL = "https://github.com/ubeast/logjam"


# --------------------------------------------------------------------------- #
#  DB helpers
# --------------------------------------------------------------------------- #
def connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(settings.db_path), read_only=True)


def resolve(
    con: duckdb.DuckDBPyConnection, name_like: str, *, entity_type: str = "port"
) -> tuple[str, str, str | None] | None:
    """Return (entity_id, entity_name, iso3) for the highest-volume name match."""
    row = con.execute(
        """
        SELECT entity_id, any_value(entity_name), any_value(iso3)
        FROM observation
        WHERE lower(entity_name) LIKE lower(?) AND entity_type = ?
        GROUP BY entity_id ORDER BY count(*) DESC LIMIT 1
        """,
        [name_like, entity_type],
    ).fetchone()
    return (row[0], row[1], row[2]) if row else None


def country_of(con: duckdb.DuckDBPyConnection, entity_id: str) -> str | None:
    """Full country name for a port entity (from PortWatch's own `country` column)."""
    row = con.execute(
        "SELECT any_value(country) FROM observation WHERE entity_id = ? AND country IS NOT NULL",
        [entity_id],
    ).fetchone()
    return row[0] if row and row[0] else None


def short_name(name: str) -> str:
    """A compact port label: prefer the parenthetical, else drop 'Port' noise."""
    if "(" in name:
        return name.split(" (")[-1].rstrip(")")
    name = name.replace(" Port", "")
    return name[len("Port of "):] if name.startswith("Port of ") else name


def monthly(
    con: duckdb.DuckDBPyConnection, entity_id: str, metric: str, since: dt.date
) -> dict[str, float]:
    """Monthly mean of ``metric`` for one entity, keyed 'YYYY-MM'."""
    rows = con.execute(
        """
        SELECT strftime(date_trunc('month', obs_date), '%Y-%m') AS mon, avg(value)
        FROM observation
        WHERE entity_id = ? AND metric = ? AND obs_date >= ?
        GROUP BY 1 ORDER BY 1
        """,
        [entity_id, metric, since],
    ).fetchall()
    return {m: round(v, 1) for m, v in rows if v is not None}


def window_avg(
    con: duckdb.DuckDBPyConnection,
    entity_id: str,
    metric: str,
    lo: dt.date,
    hi: dt.date,
) -> float | None:
    """Mean of ``metric`` over the half-open window [lo, hi)."""
    row = con.execute(
        "SELECT avg(value) FROM observation "
        "WHERE entity_id = ? AND metric = ? AND obs_date >= ? AND obs_date < ?",
        [entity_id, metric, lo, hi],
    ).fetchone()
    return round(row[0], 1) if row and row[0] is not None else None


def pct(now: float | None, base: float | None) -> float | None:
    """``now`` as a percentage of ``base`` (rounded, 1dp). None if not computable."""
    if now is None or not base:
        return None
    return round(100 * now / base, 1)


def pct_change(now: float | None, base: float | None) -> float | None:
    if now is None or not base:
        return None
    return round(100 * (now - base) / base, 0)


def month_labels(start: dt.date, count: int) -> list[str]:
    """['Sep 25', 'Oct 25', ...] - ``count`` months from ``start`` (first of month)."""
    out: list[str] = []
    y, m = start.year, start.month
    for _ in range(count):
        out.append(dt.date(y, m, 1).strftime("%b %y"))
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return out


def month_keys(start: dt.date, count: int) -> list[str]:
    out: list[str] = []
    y, m = start.year, start.month
    for _ in range(count):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return out


# --------------------------------------------------------------------------- #
#  Report config
# --------------------------------------------------------------------------- #
@dataclass
class Tile:
    label: str
    value: str            # e.g. "9" or "6"
    unit: str = ""        # e.g. "% of normal"
    note: str = ""
    crit: bool = False


@dataclass
class Section:
    num: str              # "1", "2", ...
    heading: str
    body_md: str          # markdown-ish prose (paragraphs, **bold**, *italic*, `code`)
    lede_md: str | None = None
    figure: dict[str, Any] | None = None   # {title, sub, chart_id, caption, legend?}
    callout: tuple[str, str] | None = None  # (label, text)
    table: DataTable | None = None          # optional table rendered after the prose/figure


@dataclass
class LineChart:
    chart_id: str
    kind: str = "line"
    y_max: float = 0
    y_ticks: list[float] = field(default_factory=list)
    y_pct: bool = False
    mark_index: int | None = None
    mark_label: str = ""
    marks: list[dict[str, Any]] = field(default_factory=list)  # [{index, label}] extra verticals
    ref_line: float | None = None
    ref_label: str = ""
    provisional_last: bool = False
    series: list[dict[str, Any]] = field(default_factory=list)  # {values,color,label,tipLabel,area,asPct}


@dataclass
class DivergingChart:
    chart_id: str
    kind: str = "diverging"
    rows: list[dict[str, Any]] = field(default_factory=list)  # {name,country,pct,a,b}
    max_abs: float = 135


@dataclass
class MapChart:
    """A geographic bubble map: real basemap first, then a circle per place.

    ``land`` / ``borders`` are GeoJSON *geometry* objects (Polygon/MultiPolygon,
    LineString/MultiLineString) from ``assets/geo/basemap_mideast.json`` via
    :mod:`_geo`. ``bbox`` is ``[minlon, minlat, maxlon, maxlat]`` and drives a
    Web-Mercator projection in the browser. Each point:
        {name, lon, lat, delta, pct, role, country?}
    ``role`` is ``"gain"`` | ``"loss"`` | ``"chokepoint"``; ``delta`` is the
    signed absolute change and sizes the bubble, ``pct`` the percent change;
    ``country`` (optional) is the port's country, shown in the tooltip.
    """

    chart_id: str
    kind: str = "map"
    bbox: list[float] = field(default_factory=list)
    land: dict[str, Any] = field(default_factory=dict)
    borders: dict[str, Any] = field(default_factory=dict)
    points: list[dict[str, Any]] = field(default_factory=list)
    size_max: float = 0            # |delta| that maps to the largest bubble
    size_unit: str = ""            # e.g. "container calls/day"
    size_legend: list[float] = field(default_factory=list)  # |delta| values for the size key
    labels: list[str] = field(default_factory=list)         # point names to always label


@dataclass
class CapacityChart:
    """Horizontal meter bars: each row's current level as a % of its own ceiling.

    Answers "can this port absorb more?" rather than "how much did it change?".
    Each row:
        {name, pct: <current / historical-peak, %>, mark: <current / p95, %>,
         band: "headroom" | "tight" | "maxed", note: "<7.5 vs 9.5 peak/day>"}
    A dashed reference line sits at 100 (the port's own busiest month); ``mark``
    draws a small tick for the 95th-percentile "sustained" level.
    """

    chart_id: str
    kind: str = "capacity"
    rows: list[dict[str, Any]] = field(default_factory=list)
    bar_max: float = 115.0
    ref: float = 100.0
    ref_label: str = "own peak"


@dataclass
class DataTable:
    caption: str
    columns: list[str]
    rows: list[list[str]]
    break_row: int | None = None
    crit_cols: list[int] = field(default_factory=list)


@dataclass
class Brief:
    slug: str
    title: str                    # "Hormuz Container Disruption" -> <title> + MD H1
    kicker: str                   # "Supply-chain disruption brief" -> masthead eyebrow
    chokepoint_code: str          # "CHOKEPOINT 6" -> status bar
    data_as_of: str               # "23 Aug 2026"
    generated: str                # "30 Aug 2026"
    verdict: str                  # "Severe · Ongoing"
    verdict_tone: str             # "critical" | "serious" | "warning" | "good"
    headline: str                 # the h1
    dek: str
    months: list[str]             # x-axis labels shared by all line charts
    tiles: list[Tile]
    sections: list[Section]
    charts: list[Any]             # LineChart | DivergingChart
    table: DataTable
    method_dl: list[tuple[str, str]]   # (term, definition_md)
    limitations: list[str]


# --------------------------------------------------------------------------- #
#  Tiny markdown -> inline HTML (paragraphs + ** * ` only)
# --------------------------------------------------------------------------- #
def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = text.replace(" -- ", " &mdash; ")
    return text


def _prose_html(body_md: str) -> str:
    paras = [p.strip() for p in body_md.strip().split("\n\n") if p.strip()]
    return "\n".join(f"<p>{_inline(p)}</p>" for p in paras)


def _strip_md(text: str) -> str:
    """Plain text from the tiny markdown subset - for the MD kicker line."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text


# --------------------------------------------------------------------------- #
#  Markdown renderer
# --------------------------------------------------------------------------- #
def _markdown_table(t: DataTable) -> str:
    """A GitHub-flavoured Markdown table; first column left-, the rest right-aligned."""
    align = "|" + "|".join(["---"] + ["--:"] * (len(t.columns) - 1)) + "|"
    lines = [f"**{t.caption}**", "", "| " + " | ".join(t.columns) + " |", align]
    for row in t.rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_markdown(b: Brief, key_figures: list[tuple[str, str, str, str]]) -> str:
    """key_figures: list of (metric, now, baseline, pct_of_normal) rows."""
    L: list[str] = []
    L.append(f"# {b.title}\n")
    L.append(f"**{b.kicker} — {_strip_md(b.headline)}**\n")
    L.append("| | |\n|---|---|")
    L.append("| **By** | Michael Schertz |")
    L.append(f"| **Tooling** | [`logjam`]({REPO_URL}) (open-source) |")
    L.append(f"| **Generated** | {b.generated} |")
    L.append(f"| **Data as of** | {b.data_as_of} |")
    L.append("| **Source** | IMF PortWatch (`portwatch.imf.org`) |")
    L.append(f"| **Verdict** | {b.verdict} |\n")
    L.append(
        f"> Charts for this brief are in `{b.slug}.html` and `{b.slug}.pdf`. This "
        "Markdown version carries the same findings, the underlying monthly "
        "figures, and the full method.\n"
    )
    L.append("---\n")
    L.append("## Key figures\n")
    L.append("| Metric | Now | Pre-crisis | vs baseline |\n|---|--:|--:|--:|")
    for metric, now, base, pn in key_figures:
        L.append(f"| {metric} | {now} | {base} | **{pn}** |")
    L.append("")
    L.append("---\n")
    for s in b.sections:
        L.append(f"## {s.num}. {s.heading}\n")
        if s.lede_md:
            L.append(f"*{s.lede_md.strip()}*\n")
        L.append(s.body_md.strip() + "\n")
        if s.callout:
            L.append(f"**{s.callout[0]}.** {s.callout[1]}\n")
        if s.table:
            L.append(_markdown_table(s.table) + "\n")
    L.append("---\n")
    L.append("## Method & provenance\n")
    L.append(
        "Every figure in this brief is reproducible from a local database built "
        "by the open-source `logjam` tool and a single generator "
        "script. Nothing is hand-transcribed.\n"
    )
    for term, defn in b.method_dl:
        L.append(f"**{term}.** {defn}\n")
    L.append("### Limitations\n")
    for lim in b.limitations:
        L.append(f"- {lim}")
    L.append("")
    L.append("---\n")
    L.append(
        f"*Michael Schertz · built with [`logjam`]({REPO_URL}), an "
        "open-source logistics bottleneck & opportunity identifier. Data © IMF "
        "PortWatch, used under its free public-use terms. This document reports "
        "analysis of public shipping data; it is not affiliated with or endorsed "
        "by the IMF.*\n"
    )
    return "\n".join(L)


# --------------------------------------------------------------------------- #
#  HTML renderer
# --------------------------------------------------------------------------- #
def _table_html(table: DataTable) -> str:
    thead = "".join(f"<th>{html.escape(c)}</th>" for c in table.columns)
    tbody_rows = []
    for i, row in enumerate(table.rows):
        cls = ' class="break"' if table.break_row == i else ""
        cells = "".join(
            f'<td class="{"cell-crit" if j in table.crit_cols and table.break_row is not None and i >= table.break_row else ""}">{html.escape(v)}</td>'
            for j, v in enumerate(row)
        )
        tbody_rows.append(f"<tr{cls}>{cells}</tr>")
    return f'''  <div class="tbl-wrap">
    <table>
      <caption>{html.escape(table.caption)}</caption>
      <thead><tr>{thead}</tr></thead>
      <tbody>
        {"".join(tbody_rows)}
      </tbody>
    </table>
  </div>'''


def _chart_to_json(c: Any) -> dict[str, Any]:
    if isinstance(c, LineChart):
        return {
            "type": "line",
            "mount": c.chart_id,
            "yMax": c.y_max,
            "yTicks": c.y_ticks,
            "yPct": c.y_pct,
            "markIndex": c.mark_index,
            "markLabel": c.mark_label,
            "marks": c.marks,
            "refLine": c.ref_line,
            "refLabel": c.ref_label,
            "provisionalLast": c.provisional_last,
            "series": c.series,
        }
    if isinstance(c, MapChart):
        return {
            "type": "map",
            "mount": c.chart_id,
            "bbox": c.bbox,
            "land": c.land,
            "borders": c.borders,
            "points": c.points,
            "sizeMax": c.size_max,
            "sizeUnit": c.size_unit,
            "sizeLegend": c.size_legend,
            "labels": c.labels,
        }
    if isinstance(c, CapacityChart):
        return {
            "type": "capacity",
            "mount": c.chart_id,
            "rows": c.rows,
            "barMax": c.bar_max,
            "ref": c.ref,
            "refLabel": c.ref_label,
        }
    return {
        "type": "diverging",
        "mount": c.chart_id,
        "maxAbs": c.max_abs,
        "rows": c.rows,
    }


def render_html(b: Brief) -> str:
    table = b.table
    tone = b.verdict_tone
    tiles_html = "\n".join(
        f'''    <div class="tile">
      <div class="k">{html.escape(t.label)}</div>
      <div class="v{' crit' if t.crit else ''}">{html.escape(t.value)}'''
        + (f'<small>&thinsp;{html.escape(t.unit)}</small>' if t.unit else "")
        + f'''</div>
      <div class="note">{html.escape(t.note)}</div>
    </div>'''
        for t in b.tiles
    )

    sections_html: list[str] = []
    for s in b.sections:
        parts = [
            f'  <section>\n    <div class="sec-head">'
            f'<span class="sec-num">§ {s.num}</span><h2>{_inline(s.heading)}</h2></div>'
        ]
        if s.lede_md:
            parts.append(f'    <p class="lede">{_inline(s.lede_md)}</p>')
        parts.append(f'    <div class="prose">\n{_prose_html(s.body_md)}\n    </div>')
        if s.figure:
            f = s.figure
            legend = ""
            if f.get("legend"):
                items = "".join(
                    f'<span><i style="background:{c}"></i> {html.escape(lbl)}</span>'
                    for lbl, c in f["legend"]
                )
                legend = f'\n      <div class="legend">{items}</div>'
            parts.append(
                f'''    <figure>
      <div class="fig-top">
        <p class="fig-title">{html.escape(f["title"])}</p>
        <p class="fig-sub">{html.escape(f["sub"])}</p>
      </div>
      <div class="chart-scroll"><div class="chart" id="{f["chart_id"]}"></div></div>{legend}
      <figcaption>{_inline(f["caption"])}</figcaption>
    </figure>'''
            )
        if s.callout:
            parts.append(
                f'''    <div class="callout">
      <span class="lbl">{html.escape(s.callout[0])}</span>
      <p>{_inline(s.callout[1])}</p>
    </div>'''
            )
        if s.table:
            parts.append(_table_html(s.table))
        parts.append("  </section>")
        sections_html.append("\n".join(parts))

    table_html = _table_html(table)

    method_dl = "\n".join(
        f"      <dt>{html.escape(term)}</dt>\n      <dd>{_inline(defn)}</dd>"
        for term, defn in b.method_dl
    )
    limits = "\n".join(f"      <li>{_inline(x)}</li>" for x in b.limitations)

    report_json = json.dumps(
        {"months": b.months, "charts": [_chart_to_json(c) for c in b.charts]}
    )

    return f"""<meta charset="utf-8" />
<title>{html.escape(b.title)}</title>
<meta name="description" content="{html.escape(_strip_md(b.dek))}" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&display=swap" />

<style>
{PAGE_CSS}
</style>

<div class="statusbar">
  <div class="wrap">
    <span class="id">Disruption Brief · {html.escape(b.chokepoint_code)}</span>
    <span class="sep">/</span>
    <span class="asof">DATA AS OF {html.escape(b.data_as_of.upper())}</span>
    <span class="verdict tone-{tone}"><span class="dot"></span>{html.escape(b.verdict)}</span>
  </div>
</div>

<div class="wrap">

  <header class="masthead">
    <div class="eyebrow">{html.escape(b.kicker)}</div>
    <h1>{_inline(b.headline)}</h1>
    <p class="dek">{_inline(b.dek)}</p>
    <div class="byline">
      <span><b>By</b> Michael Schertz</span>
      <span><b>Tooling</b> <a href="{REPO_URL}">logjam</a> (open-source)</span>
      <span><b>Generated</b> {html.escape(b.generated)}</span>
      <span><b>Source</b> IMF PortWatch</span>
      <span><b>Method</b> see §&nbsp;Method &amp; provenance</span>
    </div>
  </header>

  <div class="tiles">
{tiles_html}
  </div>

{chr(10).join(sections_html)}

{table_html}

</div>

<section class="method">
  <div class="wrap">
    <div class="sec-head"><span class="sec-num">§</span><h2>Method &amp; provenance</h2></div>
    <div class="prose">
      <p>Every figure in this brief is reproducible from a local database built by the open-source <code>logjam</code> tool and a single generator script. Nothing is hand-transcribed.</p>
    </div>
    <dl>
{method_dl}
    </dl>
    <p class="prose" style="margin-top:2rem"><strong>Limitations</strong></p>
    <ul class="limits">
{limits}
    </ul>
  </div>
</section>

<footer class="colophon">
  <div class="wrap">
    Michael Schertz · built with <a href="{REPO_URL}">logjam</a>, an open-source logistics bottleneck &amp; opportunity identifier<br />
    Data © IMF PortWatch, used under its free public-use terms · Brief generated {html.escape(b.generated)}<br />
    This document reports analysis of public shipping data. It is not affiliated with or endorsed by the IMF.
  </div>
</footer>

<div class="tooltip" id="tt" role="status" aria-live="polite"></div>

<script>
window.REPORT = {report_json};
{CHART_JS}
</script>
"""


def write_all(
    b: Brief,
    payload: dict[str, Any],
    key_figures: list[tuple[str, str, str, str]],
) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / f"{b.slug}.json").write_text(json.dumps(payload, indent=2))
    (REPORTS_DIR / f"{b.slug}.md").write_text(render_markdown(b, key_figures))
    (REPORTS_DIR / f"{b.slug}.html").write_text(render_html(b))
    print(f"wrote reports/data/{b.slug}.json, reports/{b.slug}.md, reports/{b.slug}.html")


# --------------------------------------------------------------------------- #
#  Verbatim CSS from hormuz_container_2026.html (shared visual system)
# --------------------------------------------------------------------------- #
PAGE_CSS = r"""
  :root {
    color-scheme: light;
    --paper:        #eaeef0;
    --surface:      #f7f9f9;
    --surface-2:    #ffffff;
    --ink:          #15211f;
    --ink-2:        #47585b;
    --ink-3:        #7a898c;
    --hairline:     #d2dadc;
    --rule:         #b6c2c4;
    --accent:       #b0591a;
    --accent-ink:   #b0591a;
    --accent-soft:  #f0e3d5;

    --chart-surface:#fbfcfc;
    --grid:         #e2e3dd;
    --axis:         #c3c2b7;
    --s1:           #2a78d6;
    --s2:           #eb6834;
    --s3:           #2e8b6f;
    --pos:          #2a78d6;
    --neg:          #d03b3b;

    --map-water:    #eef2f3;
    --map-land:     #e1e5df;
    --map-coast:    #a6b1a3;
    --map-border:   #c3ccc3;

    --good:     #0ca30c;
    --warning:  #fab219;
    --serious:  #ec835a;
    --critical: #d03b3b;

    --measure: 66ch;
    --gap: clamp(1.5rem, 4vw, 3rem);

    --font-display: "Newsreader", Georgia, "Times New Roman", serif;
    --font-body: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
    --font-mono: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace;
  }

  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --paper:        #0c1214;
      --surface:      #131c1e;
      --surface-2:    #182225;
      --ink:          #e9eeef;
      --ink-2:        #aab8ba;
      --ink-3:        #78878a;
      --hairline:     #243437;
      --rule:         #32464a;
      --accent:       #e08a4c;
      --accent-ink:   #e79a63;
      --accent-soft:  #271d14;

      --chart-surface:#161d1f;
      --grid:         #2b2c2a;
      --axis:         #3b3b38;
      --s1:           #3987e5;
      --s2:           #d95926;
      --s3:           #46b892;
      --pos:          #3987e5;
      --neg:          #e66767;

      --map-water:    #0f171a;
      --map-land:     #222d30;
      --map-coast:    #3d5155;
      --map-border:   #33474a;
    }
  }

  :root[data-theme="dark"] {
    color-scheme: dark;
    --paper:        #0c1214;
    --surface:      #131c1e;
    --surface-2:    #182225;
    --ink:          #e9eeef;
    --ink-2:        #aab8ba;
    --ink-3:        #78878a;
    --hairline:     #243437;
    --rule:         #32464a;
    --accent:       #e08a4c;
    --accent-ink:   #e79a63;
    --accent-soft:  #271d14;

    --chart-surface:#161d1f;
    --grid:         #2b2c2a;
    --axis:         #3b3b38;
    --s1:           #3987e5;
    --s2:           #d95926;
    --s3:           #46b892;
    --pos:          #3987e5;
    --neg:          #e66767;

    --map-water:    #0f171a;
    --map-land:     #222d30;
    --map-coast:    #3d5155;
    --map-border:   #33474a;
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    background: var(--paper);
    color: var(--ink);
    font-family: var(--font-body);
    font-size: 1.0625rem;
    line-height: 1.62;
    -webkit-font-smoothing: antialiased;
  }

  .wrap { max-width: 1100px; margin: 0 auto; padding: 0 clamp(1rem, 4vw, 2.5rem); }

  .statusbar {
    position: sticky; top: 0; z-index: 20;
    background: color-mix(in srgb, var(--paper) 88%, transparent);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--hairline);
    font-family: var(--font-mono);
    font-size: 0.75rem;
    letter-spacing: 0.02em;
  }
  .statusbar .wrap {
    display: flex; align-items: center; gap: 1rem;
    min-height: 44px; flex-wrap: wrap;
  }
  .statusbar .id { color: var(--ink-3); text-transform: uppercase; }
  .statusbar .sep { color: var(--rule); }
  .statusbar .asof { color: var(--ink-2); }
  .statusbar .verdict {
    margin-left: auto;
    display: inline-flex; align-items: center; gap: 0.4rem;
    padding: 0.2rem 0.55rem;
    border: 1px solid color-mix(in srgb, var(--critical) 45%, transparent);
    color: var(--critical);
    border-radius: 2px;
    text-transform: uppercase; font-weight: 500;
  }
  .statusbar .verdict.tone-serious { border-color: color-mix(in srgb, var(--serious) 55%, transparent); color: var(--serious); }
  .statusbar .verdict.tone-warning { border-color: color-mix(in srgb, var(--warning) 60%, transparent); color: var(--warning); }
  .statusbar .verdict.tone-good { border-color: color-mix(in srgb, var(--good) 50%, transparent); color: var(--good); }
  .verdict .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }

  header.masthead { padding: clamp(2.5rem, 8vw, 5rem) 0 clamp(1.5rem, 4vw, 2.5rem); }
  .eyebrow {
    font-family: var(--font-mono);
    font-size: 0.72rem; letter-spacing: 0.22em; text-transform: uppercase;
    color: var(--accent-ink);
    display: flex; align-items: center; gap: 0.8rem;
    margin-bottom: 1.4rem;
  }
  .eyebrow::after { content: ""; flex: 1; height: 1px; background: var(--rule); }

  h1 {
    font-family: var(--font-display);
    font-weight: 500;
    font-size: clamp(2.4rem, 6.5vw, 4.1rem);
    line-height: 1.04;
    letter-spacing: -0.015em;
    text-wrap: balance;
    margin: 0 0 1.1rem;
    max-width: 22ch;
  }
  .dek {
    font-family: var(--font-display);
    font-size: clamp(1.15rem, 2.4vw, 1.5rem);
    font-weight: 400;
    line-height: 1.5;
    color: var(--ink-2);
    max-width: 46ch;
    margin: 0 0 2rem;
  }
  .byline {
    font-family: var(--font-mono);
    font-size: 0.76rem;
    color: var(--ink-3);
    display: flex; flex-wrap: wrap; gap: 0.4rem 1.4rem;
    padding-top: 1.2rem;
    border-top: 1px solid var(--hairline);
  }
  .byline b { color: var(--ink-2); font-weight: 500; }

  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1px;
    background: var(--hairline);
    border: 1px solid var(--hairline);
    border-radius: 3px;
    overflow: hidden;
    margin: var(--gap) 0;
  }
  .tile { background: var(--surface); padding: 1.4rem 1.3rem 1.3rem; }
  .tile .k {
    font-family: var(--font-mono);
    font-size: 0.68rem; letter-spacing: 0.1em; text-transform: uppercase;
    color: var(--ink-3);
    margin-bottom: 0.7rem;
  }
  .tile .v {
    font-family: var(--font-display);
    font-size: 2.5rem; font-weight: 500; line-height: 1;
    letter-spacing: -0.02em;
  }
  .tile .v small { font-size: 1rem; font-weight: 400; color: var(--ink-2); letter-spacing: 0; }
  .tile .note { font-size: 0.82rem; color: var(--ink-2); margin-top: 0.5rem; line-height: 1.4; }
  .tile .v.crit { color: var(--critical); }

  section { padding: clamp(2rem, 5vw, 3.5rem) 0; border-top: 1px solid var(--hairline); }
  .sec-head { display: flex; gap: 1rem; align-items: baseline; margin-bottom: 1.6rem; }
  .sec-num {
    font-family: var(--font-mono);
    font-size: 0.8rem; color: var(--accent-ink); font-weight: 500;
    padding-top: 0.4rem;
  }
  h2 {
    font-family: var(--font-display);
    font-weight: 500;
    font-size: clamp(1.6rem, 3.6vw, 2.3rem);
    line-height: 1.15;
    letter-spacing: -0.01em;
    text-wrap: balance;
    margin: 0;
  }
  .prose { max-width: var(--measure); }
  .prose p { margin: 0 0 1.1rem; }
  .prose p:last-child { margin-bottom: 0; }
  .prose strong { font-weight: 600; }
  .prose em { font-style: italic; color: var(--ink-2); }

  a { color: var(--accent-ink); text-decoration: underline; text-underline-offset: 2px; text-decoration-thickness: 1px; }
  a:hover { text-decoration-thickness: 2px; }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 2px; }

  .lede {
    font-family: var(--font-display);
    font-size: clamp(1.2rem, 2.6vw, 1.6rem);
    line-height: 1.45;
    font-weight: 400;
    max-width: 40ch;
    margin: 0 0 1.6rem;
  }
  .lede .hl { background: linear-gradient(transparent 62%, var(--accent-soft) 62%); padding: 0 0.1em; }

  figure {
    margin: 2rem 0 0;
    background: var(--chart-surface);
    border: 1px solid var(--hairline);
    border-radius: 4px;
    padding: 1.4rem clamp(0.8rem, 2vw, 1.5rem) 1.1rem;
  }
  figure .fig-top { margin-bottom: 1rem; }
  figure .fig-title {
    font-family: var(--font-body);
    font-weight: 600; font-size: 0.98rem;
    margin: 0 0 0.2rem;
  }
  figure .fig-sub { font-size: 0.82rem; color: var(--ink-2); margin: 0; }
  .chart-scroll { overflow-x: auto; }
  .chart svg { display: block; width: 100%; height: auto; font-family: var(--font-mono); }
  .chart text { fill: var(--ink-2); }
  .axis-line { stroke: var(--axis); stroke-width: 1; }
  .grid-line { stroke: var(--grid); stroke-width: 1; }
  .ref-line { stroke: var(--ink-3); stroke-width: 1; stroke-dasharray: 3 3; }
  .tick { font-size: 11px; fill: var(--ink-3); }
  .series-label { font-size: 12px; font-weight: 500; font-family: var(--font-body); }

  .map-water { fill: var(--map-water); }
  .map-land { fill: var(--map-land); stroke: var(--map-coast); stroke-width: 0.75; stroke-linejoin: round; }
  .map-border { fill: none; stroke: var(--map-border); stroke-width: 0.75; stroke-dasharray: 2 2; }
  .map-grat { stroke: var(--map-coast); stroke-width: 0.5; stroke-opacity: 0.28; fill: none; }
  .map-grat-tick { font-size: 10px; fill: var(--ink-3); }
  .map-bubble { fill-opacity: 0.72; stroke-width: 1.25; }
  .map-choke { fill: var(--accent-ink); fill-opacity: 0.22; stroke: var(--accent-ink); stroke-width: 2; }
  .map-label {
    font-size: 11px; font-family: var(--font-body); font-weight: 500; fill: var(--ink);
    paint-order: stroke; stroke: var(--chart-surface); stroke-width: 3px; stroke-linejoin: round;
  }
  .map-key-txt { font-size: 11px; fill: var(--ink-2); font-family: var(--font-body); }

  .legend {
    display: flex; flex-wrap: wrap; gap: 0.4rem 1.3rem;
    margin-top: 0.9rem; font-size: 0.8rem; color: var(--ink-2);
    font-family: var(--font-body);
  }
  .legend span { display: inline-flex; align-items: center; gap: 0.45rem; }
  .legend i { width: 20px; height: 3px; border-radius: 2px; display: inline-block; }

  figcaption {
    margin-top: 0.9rem; padding-top: 0.8rem;
    border-top: 1px solid var(--hairline);
    font-size: 0.78rem; color: var(--ink-3); line-height: 1.5;
  }

  .tooltip {
    position: fixed; z-index: 40; pointer-events: none;
    background: var(--surface-2); color: var(--ink);
    border: 1px solid var(--rule); border-radius: 4px;
    padding: 0.5rem 0.7rem; font-size: 0.78rem; font-family: var(--font-mono);
    box-shadow: 0 6px 24px rgba(0,0,0,0.16);
    opacity: 0; transition: opacity 0.12s; max-width: 240px;
  }
  .tooltip .tt-h { font-weight: 500; margin-bottom: 0.2rem; }
  .tooltip .tt-row { color: var(--ink-2); }
  .tooltip .tt-row b { color: var(--ink); font-weight: 500; }

  .hover-dot { pointer-events: none; }
  .hit { fill: transparent; cursor: crosshair; }

  .callout {
    margin: 2rem 0 0;
    border-left: 2px solid var(--accent);
    background: var(--surface);
    padding: 1.1rem 1.3rem;
    border-radius: 0 3px 3px 0;
    max-width: var(--measure);
  }
  .callout p { margin: 0; font-size: 0.96rem; }
  .callout .lbl {
    font-family: var(--font-mono); font-size: 0.68rem; letter-spacing: 0.12em;
    text-transform: uppercase; color: var(--accent-ink); display: block; margin-bottom: 0.4rem;
  }

  .tbl-wrap { overflow-x: auto; margin-top: 2rem; border: 1px solid var(--hairline); border-radius: 4px; }
  table { border-collapse: collapse; width: 100%; font-size: 0.82rem; font-family: var(--font-mono); }
  caption {
    text-align: left; padding: 0.9rem 1rem; font-family: var(--font-body);
    font-weight: 600; font-size: 0.92rem; background: var(--surface);
    border-bottom: 1px solid var(--hairline);
  }
  th, td { padding: 0.5rem 0.9rem; text-align: right; font-variant-numeric: tabular-nums; }
  th:first-child, td:first-child { text-align: left; }
  thead th {
    font-size: 0.68rem; letter-spacing: 0.06em; text-transform: uppercase;
    color: var(--ink-3); font-weight: 500; border-bottom: 1px solid var(--rule);
    position: sticky; top: 0; background: var(--chart-surface);
  }
  tbody tr:nth-child(even) { background: color-mix(in srgb, var(--surface) 55%, transparent); }
  tbody td { border-bottom: 1px solid var(--hairline); }
  tr.break td { border-bottom: 2px solid var(--rule); }
  .cell-crit { color: var(--critical); }

  .method { background: var(--surface); border-top: 1px solid var(--hairline); }
  .method h2 { font-size: clamp(1.3rem, 3vw, 1.7rem); }
  .method dl { margin: 1.4rem 0 0; max-width: 78ch; }
  .method dt {
    font-family: var(--font-mono); font-size: 0.72rem; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--accent-ink); margin-top: 1.3rem;
  }
  .method dd { margin: 0.35rem 0 0; font-size: 0.94rem; color: var(--ink-2); }
  .method dd code {
    font-family: var(--font-mono); font-size: 0.85em;
    background: var(--surface-2); border: 1px solid var(--hairline);
    padding: 0.05rem 0.35rem; border-radius: 3px; color: var(--ink);
  }
  footer.colophon {
    padding: 2.5rem 0 3.5rem;
    font-family: var(--font-mono); font-size: 0.74rem; color: var(--ink-3);
    line-height: 1.7;
  }

  .limits { max-width: 78ch; margin-top: 1.4rem; padding-left: 1.1rem; }
  .limits li { margin-bottom: 0.5rem; font-size: 0.92rem; color: var(--ink-2); }

  @media (prefers-reduced-motion: no-preference) {
    .draw { stroke-dasharray: var(--len); stroke-dashoffset: var(--len); animation: draw 1.4s ease-out 0.2s forwards; }
    .fade-area { opacity: 0; animation: fade 1s ease-out 1s forwards; }
    @keyframes draw { to { stroke-dashoffset: 0; } }
    @keyframes fade { to { opacity: 1; } }
  }

  @page { margin: 16mm 14mm; }
  @media print {
    :root {
      --paper: #ffffff; --surface: #f6f8f8; --surface-2: #ffffff;
      --ink: #15211f; --ink-2: #3f5054; --ink-3: #6b7a7d;
      --hairline: #cdd6d8; --rule: #aab6b8;
      --chart-surface: #ffffff;
      --map-water: #ffffff; --map-land: #edf0eb; --map-coast: #b4bdb1; --map-border: #ccd3cc;
    }
    * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
    body { font-size: 10.5pt; line-height: 1.5; background: #fff; }
    .wrap { max-width: none; padding: 0; }
    .statusbar { position: static; backdrop-filter: none; border-bottom: 1px solid var(--rule); }
    .statusbar .wrap { min-height: 0; padding: 6pt 0; }
    .tooltip { display: none !important; }
    .draw { stroke-dasharray: none !important; stroke-dashoffset: 0 !important; animation: none !important; }
    .fade-area { opacity: 1 !important; animation: none !important; }
    .hit { display: none; }
    header.masthead { padding: 18pt 0 12pt; }
    h1 { font-size: 26pt; max-width: none; }
    .dek { font-size: 13pt; }
    section { padding: 14pt 0; }
    h2 { font-size: 16pt; }
    figure, .callout { break-inside: avoid; }
    .tiles { grid-template-columns: 1fr 1fr; break-inside: avoid; }
    .sec-head { break-after: avoid; }
    h2, h3, dt { break-after: avoid; }
    figure { box-shadow: none; }
    thead th { position: static; }
    td:first-child { white-space: nowrap; }
    a { color: var(--accent-ink); text-decoration: none; }
    footer.colophon { padding: 12pt 0 0; }
  }
"""

# --------------------------------------------------------------------------- #
#  Chart library - generalised from hormuz_container_2026.html.
#  Reads window.REPORT = { months: [...], charts: [ {type, mount, ...} ] }.
# --------------------------------------------------------------------------- #
CHART_JS = r"""
(function () {
  "use strict";
  var R = window.REPORT || { months: [], charts: [] };
  var MONTHS = R.months;
  var n = MONTHS.length;

  var SVGNS = "http://www.w3.org/2000/svg";
  function el(name, attrs) {
    var nd = document.createElementNS(SVGNS, name);
    if (attrs) for (var k in attrs) nd.setAttribute(k, attrs[k]);
    return nd;
  }
  function fmt(v) {
    if (v >= 1000) return Math.round(v).toLocaleString("en-US");
    return (Math.round(v * 10) / 10).toString();
  }
  function pctFmt(v) { return Math.round(v) + "%"; }

  var tt = document.getElementById("tt");
  function showTip(html, x, y) {
    tt.innerHTML = html; tt.style.opacity = "1";
    var r = tt.getBoundingClientRect();
    var px = x + 14, py = y - r.height - 10;
    if (px + r.width > window.innerWidth - 8) px = x - r.width - 14;
    if (py < 8) py = y + 16;
    tt.style.left = px + "px"; tt.style.top = py + "px";
  }
  function hideTip() { tt.style.opacity = "0"; }

  function lineChart(mount, opts) {
    var W = 860, H = 340, m = { t: 16, r: 84, b: 34, l: 48 };
    var iw = W - m.l - m.r, ih = H - m.t - m.b;
    var yMax = opts.yMax;
    var yFmt = opts.yPct ? function (v) { return v + "%"; } : function (v) { return v; };

    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img" });
    svg.setAttribute("aria-label", opts.aria || "");
    function X(i) { return m.l + (iw * i) / (n - 1); }
    function Y(v) { return m.t + ih - (ih * v) / yMax; }

    opts.yTicks.forEach(function (v) {
      svg.appendChild(el("line", { class: "grid-line", x1: m.l, y1: Y(v), x2: m.l + iw, y2: Y(v) }));
      var t = el("text", { class: "tick", x: m.l - 8, y: Y(v) + 4, "text-anchor": "end" });
      t.textContent = yFmt(v); svg.appendChild(t);
    });
    svg.appendChild(el("line", { class: "axis-line", x1: m.l, y1: m.t + ih, x2: m.l + iw, y2: m.t + ih }));

    if (opts.refLine != null) {
      svg.appendChild(el("line", { class: "ref-line", x1: m.l, y1: Y(opts.refLine), x2: m.l + iw, y2: Y(opts.refLine) }));
      var rt = el("text", { class: "tick", x: m.l + iw + 6, y: Y(opts.refLine) + 4 });
      rt.textContent = opts.refLabel || ""; rt.setAttribute("fill", "var(--ink-3)");
      svg.appendChild(rt);
    }

    MONTHS.forEach(function (mo, i) {
      if (i % 2 !== 0 && i !== n - 1) return;
      var t = el("text", { class: "tick", x: X(i), y: m.t + ih + 20, "text-anchor": "middle" });
      t.textContent = mo; svg.appendChild(t);
    });

    var allMarks = (opts.marks || []).slice();
    if (opts.markIndex != null) allMarks.push({ index: opts.markIndex, label: opts.markLabel || "" });
    allMarks.forEach(function (mkDef) {
      var mx = X(mkDef.index);
      svg.appendChild(el("line", { class: "ref-line", x1: mx, y1: m.t, x2: mx, y2: m.t + ih }));
      var mk = el("text", { class: "tick", x: mx + 5, y: m.t + 12 });
      mk.textContent = mkDef.label; mk.setAttribute("fill", "var(--accent-ink)");
      svg.appendChild(mk);
    });

    opts.series.forEach(function (s) {
      var color = s.color || "var(--s1)";
      var pts = s.values.map(function (v, i) { return [X(i), Y(v)]; });
      var solidPts = opts.provisionalLast ? pts.slice(0, n - 1) : pts;
      var dLine = solidPts.map(function (p, i) { return (i ? "L" : "M") + p[0] + " " + p[1]; }).join(" ");

      if (s.area) {
        var ap = solidPts;
        var dArea = ap.map(function (p, i) { return (i ? "L" : "M") + p[0] + " " + p[1]; }).join(" ") +
          " L" + ap[ap.length - 1][0] + " " + (m.t + ih) + " L" + ap[0][0] + " " + (m.t + ih) + " Z";
        svg.appendChild(el("path", { d: dArea, fill: color, "fill-opacity": "0.12", class: "fade-area" }));
      }
      var path = el("path", { d: dLine, fill: "none", stroke: color, "stroke-width": "2", "stroke-linejoin": "round", "stroke-linecap": "round" });
      var len = 0;
      solidPts.forEach(function (p, i) { if (i) len += Math.hypot(p[0] - solidPts[i - 1][0], p[1] - solidPts[i - 1][1]); });
      path.setAttribute("class", "draw"); path.style.setProperty("--len", len);
      svg.appendChild(path);

      if (opts.provisionalLast) {
        svg.appendChild(el("path", {
          d: "M" + pts[n - 2][0] + " " + pts[n - 2][1] + " L" + pts[n - 1][0] + " " + pts[n - 1][1],
          fill: "none", stroke: color, "stroke-width": "2", "stroke-dasharray": "3 3", "stroke-opacity": "0.7"
        }));
      }
      if (s.label) {
        var last = pts[pts.length - 1];
        var lb = el("text", { class: "series-label", x: last[0] + 8, y: last[1] + 4, fill: color });
        lb.textContent = s.label; svg.appendChild(lb);
      }
      var lp = pts[pts.length - 1];
      svg.appendChild(el("circle", {
        cx: lp[0], cy: lp[1], r: opts.provisionalLast ? 4 : 4.5,
        fill: opts.provisionalLast ? "var(--chart-surface)" : color, stroke: color, "stroke-width": "2"
      }));
    });

    var focusLine = el("line", { class: "ref-line hover-dot", y1: m.t, y2: m.t + ih, style: "opacity:0" });
    svg.appendChild(focusLine);
    var dots = opts.series.map(function (s) {
      var c = el("circle", { r: 4, class: "hover-dot", fill: "var(--chart-surface)", stroke: s.color || "var(--s1)", "stroke-width": "2", style: "opacity:0" });
      svg.appendChild(c); return c;
    });
    for (var i = 0; i < n; i++) {
      (function (i) {
        var hit = el("rect", { class: "hit", x: X(i) - (iw / (n - 1)) / 2, y: m.t, width: iw / (n - 1), height: ih });
        hit.addEventListener("mousemove", function (ev) {
          focusLine.setAttribute("x1", X(i)); focusLine.setAttribute("x2", X(i));
          focusLine.style.opacity = "0.7";
          var rows = opts.series.map(function (s, si) {
            dots[si].setAttribute("cx", X(i)); dots[si].setAttribute("cy", Y(s.values[i])); dots[si].style.opacity = "1";
            var vf = s.asPct ? pctFmt(s.values[i]) : fmt(s.values[i]);
            return '<div class="tt-row">' + (s.tipLabel || s.label || "value") + ': <b>' + vf + '</b></div>';
          }).join("");
          showTip('<div class="tt-h">' + MONTHS[i] + (i === n - 1 && opts.provisionalLast ? ' · provisional' : '') + '</div>' + rows, ev.clientX, ev.clientY);
        });
        hit.addEventListener("mouseleave", function () {
          focusLine.style.opacity = "0"; dots.forEach(function (d) { d.style.opacity = "0"; }); hideTip();
        });
        svg.appendChild(hit);
      })(i);
    }
    document.getElementById(mount).appendChild(svg);
  }

  function divergingBars(mount, rows, maxAbs) {
    maxAbs = maxAbs || 135;
    var rowH = 30, padTop = 10, padBottom = 28;
    var W = 860, H = padTop + rows.length * rowH + padBottom;
    var labelW = 150, valW = 104;
    var plotL = labelW, plotW = W - labelW - valW;
    function X(v) { return plotL + (plotW * (v + maxAbs)) / (2 * maxAbs); }

    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Percent change by port." });
    var ticks = maxAbs > 120 ? [-100, -50, 0, 50, 100] : [-100, -50, 0, 50, 100].filter(function (v) { return Math.abs(v) <= maxAbs; });
    ticks.forEach(function (v) {
      svg.appendChild(el("line", { class: v === 0 ? "axis-line" : "grid-line", x1: X(v), y1: padTop, x2: X(v), y2: H - padBottom }));
      var t = el("text", { class: "tick", x: X(v), y: H - padBottom + 18, "text-anchor": "middle" });
      t.textContent = (v > 0 ? "+" : "") + v + "%"; svg.appendChild(t);
    });

    rows.forEach(function (r, i) {
      var y = padTop + i * rowH, cy = y + rowH / 2;
      var pos = r.pct >= 0;
      var color = pos ? "var(--pos)" : "var(--neg)";
      var x0 = X(0), x1 = X(Math.max(-maxAbs, Math.min(maxAbs, r.pct)));
      var bx = Math.min(x0, x1), bw = Math.abs(x1 - x0);
      svg.appendChild(el("rect", { x: bx, y: cy - 8, width: Math.max(bw, 1.5), height: 16, rx: 3, fill: color, "fill-opacity": "0.9" }));

      var nm = el("text", { x: labelW - 12, y: cy + 4, "text-anchor": "end", class: "series-label" });
      nm.setAttribute("fill", "var(--ink)"); nm.textContent = r.name; svg.appendChild(nm);

      var inside = pos && x1 > plotL + plotW - 52;
      var pv = el("text", {
        x: inside ? x1 - 7 : (pos ? x1 + 8 : x1 - 8), y: cy + 4,
        "text-anchor": inside ? "end" : (pos ? "start" : "end"), class: "tick"
      });
      pv.setAttribute("fill", inside ? "#ffffff" : color);
      pv.setAttribute("font-weight", "500");
      pv.textContent = (pos ? "+" : "") + r.pct + "%"; svg.appendChild(pv);

      var abs = el("text", { x: W - 6, y: cy + 4, "text-anchor": "end", class: "tick" });
      abs.textContent = r.a.toFixed(1) + " → " + r.b.toFixed(1); svg.appendChild(abs);

      var hit = el("rect", { class: "hit", x: 0, y: y, width: W, height: rowH });
      hit.addEventListener("mousemove", function (ev) {
        showTip('<div class="tt-h">' + r.name + (r.country ? " (" + r.country + ")" : "") + "</div>" +
          '<div class="tt-row">Change: <b>' + (pos ? "+" : "") + r.pct + '%</b></div>' +
          '<div class="tt-row">Calls/day: <b>' + r.a.toFixed(1) + ' → ' + r.b.toFixed(1) + '</b></div>', ev.clientX, ev.clientY);
      });
      hit.addEventListener("mouseleave", hideTip);
      svg.appendChild(hit);
    });
    document.getElementById(mount).appendChild(svg);
  }

  // --- capacity meter -------------------------------------------------
  // One bar per port: current throughput as a % of that port's own busiest
  // month on record. A dashed line at 100 is the port's own ceiling; a small
  // caret marks its 95th-percentile ("sustained") level. Bar colour bands the
  // headroom.
  function capacityBars(mount, opts) {
    var rows = opts.rows, barMax = opts.barMax || 115, ref = opts.ref || 100;
    var rowH = 34, padTop = 12, padBottom = 30;
    var W = 860, H = padTop + rows.length * rowH + padBottom;
    var labelW = 150, valW = 150;
    var plotL = labelW, plotW = W - labelW - valW;
    function X(v) { return plotL + plotW * Math.min(v, barMax) / barMax; }
    var BAND = { headroom: "var(--good)", tight: "var(--warning)", maxed: "var(--neg)" };

    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": "Each port's current container throughput as a share of its own historical peak." });

    [0, 25, 50, 75, 100].forEach(function (v) {
      svg.appendChild(el("line", { class: v === 0 ? "axis-line" : "grid-line", x1: X(v), y1: padTop, x2: X(v), y2: H - padBottom }));
      var t = el("text", { class: "tick", x: X(v), y: H - padBottom + 18, "text-anchor": "middle" });
      t.textContent = v + "%"; svg.appendChild(t);
    });
    // the port's-own-peak reference
    svg.appendChild(el("line", { class: "ref-line", x1: X(ref), y1: padTop - 2, x2: X(ref), y2: H - padBottom }));
    var rl = el("text", { class: "tick", x: X(ref), y: padTop - 5, "text-anchor": "middle" });
    rl.setAttribute("fill", "var(--ink-3)"); rl.textContent = opts.refLabel || "own peak"; svg.appendChild(rl);

    rows.forEach(function (r, i) {
      var y = padTop + i * rowH, cy = y + rowH / 2;
      var col = BAND[r.band] || "var(--s1)";
      var x0 = X(0), x1 = X(r.pct);
      svg.appendChild(el("rect", { x: x0, y: cy - 9, width: Math.max(x1 - x0, 2), height: 18, rx: 3, fill: col, "fill-opacity": "0.85" }));

      // 95th-percentile caret
      if (r.mark != null) {
        var mx = X(r.mark);
        svg.appendChild(el("path", { d: "M" + mx + " " + (cy - 11) + " L" + (mx - 4) + " " + (cy - 16) + " L" + (mx + 4) + " " + (cy - 16) + " Z",
          fill: "var(--ink-2)" }));
      }

      var nm = el("text", { x: labelW - 12, y: cy + 4, "text-anchor": "end", class: "series-label" });
      nm.setAttribute("fill", "var(--ink)"); nm.textContent = r.name; svg.appendChild(nm);

      var inside = x1 > plotL + plotW - 44;
      var pv = el("text", { x: inside ? x1 - 7 : x1 + 8, y: cy + 4,
        "text-anchor": inside ? "end" : "start", class: "tick" });
      pv.setAttribute("fill", inside ? "#ffffff" : col); pv.setAttribute("font-weight", "500");
      pv.textContent = Math.round(r.pct) + "%"; svg.appendChild(pv);

      if (r.note) {
        var nt = el("text", { x: W - 6, y: cy + 4, "text-anchor": "end", class: "tick" });
        nt.textContent = r.note; svg.appendChild(nt);
      }

      var hit = el("rect", { class: "hit", x: 0, y: y, width: W, height: rowH });
      hit.addEventListener("mousemove", function (ev) {
        showTip('<div class="tt-h">' + r.name + '</div>' +
          '<div class="tt-row">Now vs own peak: <b>' + Math.round(r.pct) + '%</b></div>' +
          (r.mark != null ? '<div class="tt-row">vs sustained (p95): <b>' + Math.round(r.mark) + '%</b></div>' : '') +
          (r.note ? '<div class="tt-row">' + r.note + '</div>' : ''), ev.clientX, ev.clientY);
      });
      hit.addEventListener("mouseleave", hideTip);
      svg.appendChild(hit);
    });
    document.getElementById(mount).appendChild(svg);
  }

  // --- geographic bubble map -------------------------------------------
  // Real basemap (Natural Earth land + national borders, clipped and
  // projected here with Web Mercator) drawn first, then one circle per place
  // sized by the absolute change and coloured by its direction.
  function mapChart(mount, opts) {
    var b = opts.bbox, minLon = b[0], minLat = b[1], maxLon = b[2], maxLat = b[3];
    function mercY(lat) { return Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)); }
    var yTop = mercY(maxLat), yBot = mercY(minLat);
    var lonSpan = maxLon - minLon, ySpan = yTop - yBot;  // Mercator units, north-positive

    var m = { t: 14, r: 14, b: 14, l: 14 }, W = 860;
    var pw = W - m.l - m.r;
    var ph = pw * ySpan / (lonSpan * Math.PI / 180);
    var H = Math.round(ph + m.t + m.b);

    function X(lon) { return m.l + pw * (lon - minLon) / lonSpan; }
    function Y(lat) { return m.t + ph * (yTop - mercY(lat)) / ySpan; }
    function txt(s, x, y, anchor, cls) {
      var t = el("text", { x: x, y: y, class: cls });
      if (anchor) t.setAttribute("text-anchor", anchor);
      t.textContent = s; return t;
    }

    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img" });
    svg.setAttribute("aria-label", opts.aria || "Map of the change in container port calls by port.");
    svg.appendChild(el("rect", { class: "map-water", x: m.l, y: m.t, width: pw, height: ph }));

    var clipId = mount + "-clip", defs = el("defs"), cp = el("clipPath", { id: clipId });
    cp.appendChild(el("rect", { x: m.l, y: m.t, width: pw, height: ph }));
    defs.appendChild(cp); svg.appendChild(defs);
    var g = el("g", { "clip-path": "url(#" + clipId + ")" });
    svg.appendChild(g);

    for (var lon = Math.ceil(minLon / 10) * 10; lon <= maxLon; lon += 10)
      g.appendChild(el("line", { class: "map-grat", x1: X(lon), y1: m.t, x2: X(lon), y2: m.t + ph }));
    for (var lat = Math.ceil(minLat / 10) * 10; lat <= maxLat; lat += 10)
      g.appendChild(el("line", { class: "map-grat", x1: m.l, y1: Y(lat), x2: m.l + pw, y2: Y(lat) }));

    function ring(r) {
      return r.map(function (c, i) { return (i ? "L" : "M") + X(c[0]).toFixed(1) + " " + Y(c[1]).toFixed(1); }).join(" ") + "Z";
    }
    function draw(geom, cls) {
      if (!geom || !geom.type) return;
      var d = "";
      if (geom.type === "Polygon" || geom.type === "MultiPolygon") {
        var polys = geom.type === "Polygon" ? [geom.coordinates] : geom.coordinates;
        polys.forEach(function (p) { p.forEach(function (r) { d += ring(r) + " "; }); });
      } else if (geom.type === "LineString" || geom.type === "MultiLineString") {
        var lines = geom.type === "LineString" ? [geom.coordinates] : geom.coordinates;
        d = lines.map(function (ln) {
          return ln.map(function (c, i) { return (i ? "L" : "M") + X(c[0]).toFixed(1) + " " + Y(c[1]).toFixed(1); }).join(" ");
        }).join(" ");
      }
      if (d) g.appendChild(el("path", { d: d, class: cls, "fill-rule": "evenodd" }));
    }
    draw(opts.land, "map-land");
    draw(opts.borders, "map-border");
    svg.appendChild(el("rect", { x: m.l, y: m.t, width: pw, height: ph, fill: "none", stroke: "var(--map-coast)", "stroke-width": "1" }));

    var rMax = 20, rMin = 3;
    function radius(v) {
      if (!opts.sizeMax) return rMin;
      return Math.max(rMin, rMax * Math.sqrt(Math.abs(v) / opts.sizeMax));
    }

    // Bubbles largest-first so small ones stay clickable on top; the chokepoint
    // marker always draws last so the bubbles never bury it.
    var pts = opts.points.slice().sort(function (a, b) {
      var ac = a.role === "chokepoint" ? 1 : 0, bc = b.role === "chokepoint" ? 1 : 0;
      if (ac !== bc) return ac - bc;
      return Math.abs(b.delta) - Math.abs(a.delta);
    });
    pts.forEach(function (p) {
      var cx = X(p.lon), cy = Y(p.lat);
      if (p.role === "chokepoint") {
        var s = 8;
        svg.appendChild(el("path", { class: "map-choke",
          d: "M" + cx + " " + (cy - s) + " L" + (cx + s) + " " + cy + " L" + cx + " " + (cy + s) + " L" + (cx - s) + " " + cy + " Z" }));
      } else {
        var col = p.role === "gain" ? "var(--pos)" : "var(--neg)";
        svg.appendChild(el("circle", { class: "map-bubble", cx: cx, cy: cy, r: radius(p.delta), fill: col, stroke: col }));
      }
      var hit = el("circle", { class: "hit", cx: cx, cy: cy, r: Math.max(radius(p.delta || 0), 11) });
      hit.addEventListener("mousemove", function (ev) {
        var ps = p.pct == null ? "n/a"
          : (p.pct >= 0 ? "+" : "") + Math.round(p.pct) + "%";
        var rows = p.role === "chokepoint"
          ? '<div class="tt-row">Container transits: <b>' + ps
            + (p.pct == null ? '' : ' of pre-crisis change') + '</b></div>'
          : '<div class="tt-row">Container calls: <b>' + ps + '</b></div>' +
            '<div class="tt-row">Change: <b>' + (p.delta >= 0 ? "+" : "") + fmt(p.delta) + " " + (opts.sizeUnit || "") + '</b></div>';
        var head = p.name + (p.country ? " (" + p.country + ")" : "");
        showTip('<div class="tt-h">' + head + '</div>' + rows, ev.clientX, ev.clientY);
      });
      hit.addEventListener("mouseleave", hideTip);
      svg.appendChild(hit);
    });

    var labelSet = {};
    (opts.labels || []).forEach(function (nm) { labelSet[nm] = 1; });
    pts.forEach(function (p) {
      if (!labelSet[p.name]) return;
      var cx = X(p.lon), cy = Y(p.lat);
      var r = p.role === "chokepoint" ? 8 : radius(p.delta);
      var left = p.labelSide === "left";
      var t = txt(p.name, cx + (left ? -(r + 5) : r + 5), cy + 3.5 + (p.labelDy || 0),
        left ? "end" : "start", "map-label");
      svg.appendChild(t);
    });

    if (opts.sizeLegend && opts.sizeLegend.length) {
      var vals = opts.sizeLegend.slice().sort(function (a, b) { return a - b; });
      var bx = m.l + 16, by = m.t + ph - 14, keyG = el("g");
      keyG.appendChild(txt("Circle area ≈ " + (opts.sizeUnit || "change"),
        bx, by - radius(vals[vals.length - 1]) * 2 - 12, "start", "map-key-txt"));
      var cur = bx + 2;
      vals.forEach(function (v) {
        var rr = radius(v); cur += rr;
        keyG.appendChild(el("circle", { cx: cur, cy: by - rr - 3, r: rr, fill: "none", stroke: "var(--ink-3)", "stroke-width": "1" }));
        keyG.appendChild(txt(String(v), cur, by + 11, "middle", "map-key-txt"));
        cur += rr + 18;
      });
      svg.appendChild(keyG);
    }

    document.getElementById(mount).appendChild(svg);
  }

  R.charts.forEach(function (c) {
    if (!document.getElementById(c.mount)) return;
    if (c.type === "line") lineChart(c.mount, c);
    else if (c.type === "diverging") divergingBars(c.mount, c.rows, c.maxAbs);
    else if (c.type === "capacity") capacityBars(c.mount, c);
    else if (c.type === "map") mapChart(c.mount, c);
  });
})();
"""
