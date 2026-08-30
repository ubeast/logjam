"""Command-line interface.

    bottleneck refresh [--full]         pull data + recompute everything
    bottleneck bottlenecks [--days 14]  list recent bottleneck signals
    bottleneck opportunities [--days 14] list recent reroute opportunities
    bottleneck ports --search "long beach"   look up PortWatch port ids
    bottleneck status                   what's in the local database
"""

from __future__ import annotations

import datetime as dt

import typer
from rich.console import Console
from rich.table import Table

from bottleneck_logistics.analytics.recovery import recovery_status
from bottleneck_logistics.config import settings
from bottleneck_logistics.pipeline import refresh as run_refresh
from bottleneck_logistics.store.db import connect, init_schema

app = typer.Typer(add_completion=False, help="Logistics bottleneck & opportunity identifier.")
console = Console()


@app.command()
def refresh(
    full: bool = typer.Option(False, "--full", help="Ignore stored data; backfill."),
) -> None:
    """Ingest the latest PortWatch data and recompute signals."""
    res = run_refresh(full_backfill=full, progress=lambda m: console.log(m))
    console.print(
        f"[green]Done.[/green] since={res.since}  observations={res.observations_written:,}  "
        f"baseline_rows={res.baseline_rows:,}  "
        f"bottlenecks={res.bottlenecks:,}  opportunities={res.opportunities:,}"
    )


def _signal_table(signal_type: str, days: int, limit: int) -> Table:
    cutoff = dt.date.today() - dt.timedelta(days=days)
    con = connect(read_only=True)
    try:
        rows = con.execute(
            """
            SELECT obs_date, entity_type, entity_name, metric,
                   value, expected, robust_z, severity, detail
            FROM signal
            WHERE signal_type = ? AND obs_date >= ?
            ORDER BY obs_date DESC, severity DESC
            LIMIT ?
            """,
            [signal_type, cutoff, limit],
        ).fetchall()
    finally:
        con.close()

    table = Table(title=f"{signal_type.title()} signals (last {days}d)")
    for col in ("date", "type", "entity", "metric", "value", "expected", "z", "detail"):
        table.add_column(col)
    for (d, et, name, metric, val, exp, z, _sev, detail) in rows:
        table.add_row(
            str(d), et, name or "?", metric,
            f"{val:,.0f}", f"{exp:,.0f}", f"{z:+.1f}",
            (detail or "")[:80],
        )
    return table


@app.command()
def bottlenecks(days: int = 14, limit: int = 40) -> None:
    """List recent bottleneck signals (flow blocked vs baseline)."""
    console.print(_signal_table("bottleneck", days, limit))


@app.command()
def opportunities(days: int = 14, limit: int = 40) -> None:
    """List recent opportunity signals (alternative with headroom in a substitution group)."""
    console.print(_signal_table("opportunity", days, limit))


@app.command()
def ports(
    search: str = typer.Option(..., "--search", "-s", help="Substring of the port name."),
) -> None:
    """Look up PortWatch entity ids by name."""
    con = connect(read_only=True)
    try:
        rows = con.execute(
            """
            SELECT entity_type, entity_id, any_value(entity_name), any_value(iso3),
                   count(*) AS n, max(obs_date) AS last_seen
            FROM observation
            WHERE lower(entity_name) LIKE lower(?)
            GROUP BY entity_type, entity_id
            ORDER BY n DESC
            LIMIT 50
            """,
            [f"%{search}%"],
        ).fetchall()
    finally:
        con.close()
    table = Table(title=f'ports matching "{search}"')
    for col in ("type", "entity_id", "name", "iso3", "last_seen"):
        table.add_column(col)
    for (et, eid, name, iso3, _n, last_seen) in rows:
        table.add_row(et, eid, name, iso3 or "", str(last_seen))
    console.print(table)


@app.command()
def recovery(
    search: str = typer.Option(
        ..., "--search", "-s", help="Substring of the port/chokepoint name."
    ),
) -> None:
    """Is a disruption still ongoing? Current throughput vs the same period a year ago.

    Example: `bottleneck recovery -s hormuz`
    """
    con = connect(read_only=True)
    try:
        rows = recovery_status(con, search)
    finally:
        con.close()

    if not rows:
        console.print(f'No baseline rows match "{search}". Try `bottleneck ports -s {search}`.')
        return

    table = Table(title=f'Recovery status: "{search}"')
    for col in ("entity", "metric", "as of", "now", "yr-ago", "% of normal", "trend", "verdict"):
        table.add_column(col)
    style = {
        "recovered": "green",
        "partial recovery": "yellow",
        "disruption ongoing": "red",
        "severe disruption ongoing": "bold red",
        "insufficient year-ago history": "dim",
    }
    for r in rows:
        pct = "-" if r.pct_of_yoy is None else f"{r.pct_of_yoy * 100:.0f}%"
        yr = "-" if r.expected_yoy is None else f"{r.expected_yoy:,.0f}"
        table.add_row(
            r.entity_name, r.metric, str(r.as_of), f"{r.value:,.0f}", yr, pct, r.trend,
            f"[{style.get(r.verdict, 'white')}]{r.verdict}[/]",
        )
    console.print(table)
    console.print(
        "[dim]% of normal = today's value / median around the same date ~1 year "
        "earlier. 'trend' compares with ~4 weeks ago.[/dim]"
    )


@app.command()
def status() -> None:
    """Show what the local database currently holds."""
    # Read-write so a brand-new database gets its schema created.
    con = connect()
    try:
        init_schema(con)
        obs = con.execute(
            "SELECT count(*), min(obs_date), max(obs_date), "
            "count(DISTINCT entity_id) FROM observation"
        ).fetchone()
        sigs = con.execute(
            "SELECT signal_type, count(*) FROM signal GROUP BY signal_type"
        ).fetchall()
    finally:
        con.close()
    console.print(f"db: {settings.db_path}")
    console.print(
        f"observations: {obs[0]:,}  dates: {obs[1]} .. {obs[2]}  entities: {obs[3]:,}"
    )
    for (stype, n) in sigs:
        console.print(f"  {stype}: {n:,}")


if __name__ == "__main__":
    app()
