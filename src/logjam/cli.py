"""Command-line interface.

    logjam refresh [--full]         pull data + recompute everything
    logjam bottlenecks [--days 14]  list recent bottleneck signals
    logjam opportunities [--days 14] list recent reroute opportunities
    logjam recovery -s "hormuz"     ongoing or recovered vs a year ago
    logjam news -s "hormuz"         GDELT news-attention vs the trailing norm
    logjam ports --search "long beach"   look up PortWatch port ids
    logjam status                   what's in the local database
    logjam ais-collect [--minutes 30]   sample the live AIS stream
    logjam ais-reduce [--all]       fold AIS captures into the store
    logjam carrier-route <origin> <destination>   compare named carrier services
"""

from __future__ import annotations

import datetime as dt

import typer
from rich.console import Console
from rich.table import Table

from logjam.analytics.recovery import recovery_status
from logjam.config import settings
from logjam.pipeline import refresh as run_refresh
from logjam.store.db import connect, init_schema

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
        f"ais_rows={res.ais_rows_written:,}  gdelt_rows={res.gdelt_rows_written:,}  "
        f"baseline_rows={res.baseline_rows:,}  "
        f"bottlenecks={res.bottlenecks:,}  opportunities={res.opportunities:,}"
    )


@app.command("ais-collect")
def ais_collect(
    minutes: float = typer.Option(
        None, "--minutes", "-m", help="Sample length. Default: LOGJAM_AIS_SAMPLE_MINUTES."
    ),
) -> None:
    """Sample the live AIS stream into date-partitioned Parquet (needs an API key)."""
    from logjam.ingest.aisstream import sample  # noqa: PLC0415 - optional path

    try:
        kept = sample(minutes, progress=lambda m: console.log(m))
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"[green]Captured[/green] {kept:,} AIS messages → {settings.ais_raw_dir}")


@app.command("ais-reduce")
def ais_reduce(
    all_days: bool = typer.Option(
        False, "--all", help="Re-reduce every captured day, not just the pending ones."
    ),
) -> None:
    """Fold captured AIS into the observation table (source 'aisstream')."""
    from logjam.analytics.ais_reduce import (  # noqa: PLC0415
        _raw_dates,
        reduce_day,
        reduce_pending,
    )

    con = connect()
    try:
        init_schema(con)
        written = (
            sum(reduce_day(con, d) for d in _raw_dates())
            if all_days
            else reduce_pending(con)
        )
    finally:
        con.close()
    console.print(f"[green]Reduced[/green] {written:,} AIS observation rows into the store.")
    console.print("Run [bold]logjam refresh[/bold] to recompute baselines and signals.")


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

    Example: `logjam recovery -s hormuz`
    """
    con = connect(read_only=True)
    try:
        rows = recovery_status(con, search)
    finally:
        con.close()

    if not rows:
        console.print(f'No baseline rows match "{search}". Try `logjam ports -s {search}`.')
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


@app.command("news-fetch")
def news_fetch() -> None:
    """Pull the GDELT news-attention window into the store (its own step - the API is slow).

    Then run `logjam refresh` to fold it into the baselines. Configure which
    chokepoints are tracked in `resources/gdelt_queries.yaml`.
    """
    from logjam.ingest.gdelt import fetch_gdelt  # noqa: PLC0415
    from logjam.store.loaders import upsert_observations  # noqa: PLC0415

    con = connect()
    try:
        init_schema(con)
        console.log("fetching GDELT news window (the DOC API is slow - allow a few minutes)")
        try:
            tidy = fetch_gdelt()
        except RuntimeError as exc:
            console.print(f"[red]GDELT unavailable:[/red] {exc}")
            raise typer.Exit(1) from exc
        written = upsert_observations(con, tidy, source="gdelt")
    finally:
        con.close()
    console.print(f"[green]Fetched[/green] {written:,} GDELT observation rows.")
    console.print(
        "Run [bold]logjam refresh[/bold] to recompute baselines, then `logjam news -s <name>`."
    )


@app.command()
def news(
    search: str = typer.Option(
        ..., "--search", "-s", help="Substring of the chokepoint name."
    ),
    days: int = typer.Option(21, "--days", help="How many recent days to show."),
) -> None:
    """GDELT news-attention for a chokepoint: recent volume/tone vs the trailing norm.

    Context for a throughput signal - a spike in `gdelt_volume` (share of world
    coverage) or a slump in `gdelt_tone` around a chokepoint is what "why" looks
    like. Example: `logjam news -s hormuz`
    """
    cutoff = dt.date.today() - dt.timedelta(days=days)
    con = connect(read_only=True)
    try:
        rows = con.execute(
            """
            SELECT b.obs_date, o.entity_name, b.metric, b.value, b.expected, b.robust_z
            FROM baseline b
            JOIN (SELECT entity_type, entity_id, any_value(entity_name) AS entity_name
                  FROM observation GROUP BY entity_type, entity_id) o USING (entity_type, entity_id)
            WHERE b.metric IN ('gdelt_volume', 'gdelt_tone')
              AND b.obs_date >= ?
              AND lower(o.entity_name) LIKE lower(?)
            ORDER BY b.obs_date DESC, b.metric
            """,
            [cutoff, f"%{search}%"],
        ).fetchall()
    finally:
        con.close()

    if not rows:
        console.print(
            f'No GDELT baseline rows match "{search}" in the last {days}d. '
            "Run `logjam refresh`, and check `resources/gdelt_queries.yaml`."
        )
        return

    table = Table(title=f'News attention: "{search}" (last {days}d)')
    for col in ("date", "chokepoint", "metric", "value", "expected", "z"):
        table.add_column(col)
    for (d, name, metric, val, exp, z) in rows:
        colour = "red" if (metric == "gdelt_volume" and z >= 2) or (
            metric == "gdelt_tone" and z <= -2
        ) else "white"
        table.add_row(
            str(d), name or "?", metric,
            f"[{colour}]{val:,.2f}[/]", f"{exp:,.2f}", f"{z:+.1f}",
        )
    console.print(table)
    console.print(
        "[dim]gdelt_volume = per-mille of GDELT's daily articles mentioning the "
        "chokepoint; gdelt_tone = mean sentiment (-=negative). z is vs the "
        f"{settings.baseline_window_days}-day trailing median.[/dim]"
    )


@app.command("carrier-route")
def carrier_route(
    origin: str = typer.Argument(..., help="Origin port name (substring match)."),
    destination: str = typer.Argument(..., help="Destination port name (substring match)."),
) -> None:
    """Compare named carrier services between two ports: stops and transit time.

    Reads the small, hand-curated seed set in
    ``resources/carrier_routes.yaml`` (real published rotations - see
    docs/METHODOLOGY.md). Ranks fastest first; a real carrier-published
    transit time is marked "published", everything else is a distance/speed
    estimate marked "est." - the two are never blended without saying so.

    Example: `logjam carrier-route "Djibouti" "Piraeus"`
    """
    from logjam.analytics.carrier_routes import (  # noqa: PLC0415
        DEFAULT_SPEED_KN,
        find_routes,
        load_ports,
        load_services,
    )

    services = load_services()
    ports = load_ports()
    matches = find_routes(origin, destination, services, ports)

    if not matches:
        console.print(
            f'No modeled service connects "{origin}" -> "{destination}" in that sailing '
            f"direction. This is a small seed set ({len(services)} services) illustrating "
            "real published rotations, not an exhaustive carrier database - try the "
            "reverse pair, or see `resources/carrier_routes.yaml` to add more services."
        )
        return

    table = Table(title=f'Carrier services: "{origin}" -> "{destination}"')
    for col in ("carrier", "service", "route", "stops between", "transit", "calls"):
        table.add_column(col)
    for m in matches:
        route = f"{m.origin_call} -> {m.destination_call}"
        stops = "direct" if m.direct else f"{m.stops_between} stop(s)"
        if m.transit_days is None:
            transit = "n/a"
        elif m.transit_estimated:
            transit = f"~{m.transit_days}d (est.)"
        else:
            transit = f"{m.transit_days}d (published)"
        table.add_row(
            m.service.carrier, m.service.service, route, stops, transit,
            f"[dim]{m.service.operator_note}[/dim]",
        )
    console.print(table)
    console.print(
        "[dim]'published' = the carrier's own transit-time matrix; 'est.' = great-circle "
        f"distance along the sailed path / {DEFAULT_SPEED_KN:.0f}kn, steaming time only "
        "(excludes port dwell, so it under-states real multi-stop transits). This is one "
        "sailing direction only - the reverse pair can match the same service with a "
        "different stop count and transit time, not a mirrored one.[/dim]"
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
    assert obs is not None  # SELECT count(*) always returns exactly one row
    console.print(f"db: {settings.db_path}")
    console.print(
        f"observations: {obs[0]:,}  dates: {obs[1]} .. {obs[2]}  entities: {obs[3]:,}"
    )
    for (stype, n) in sigs:
        console.print(f"  {stype}: {n:,}")


if __name__ == "__main__":
    app()
