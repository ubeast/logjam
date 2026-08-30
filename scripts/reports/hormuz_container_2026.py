#!/usr/bin/env python
"""Generate the data behind the 2026 Strait of Hormuz container-disruption report.

Reads the local DuckDB store (built by ``bottleneck refresh``) and writes a
single JSON file with every figure the report cites, so the report is fully
reproducible:

    uv run python scripts/reports/hormuz_container_2026.py

Output: reports/data/hormuz_container_2026.json

All metrics are IMF PortWatch estimates. Vessel counts (``n_*``, ``portcalls_*``)
are transit / port-call counts; ``capacity_*`` is estimated aggregate cargo
capacity of transiting vessels; ``import_container`` / ``export_container`` are
PortWatch's modelled trade-volume estimates (not measured TEU).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import duckdb

from bottleneck_logistics.config import settings

OUT = Path(__file__).resolve().parents[2] / "reports" / "data" / "hormuz_container_2026.json"

# Pre-crisis reference window (stable months immediately before the March break).
PRECRISIS = (dt.date(2025, 11, 1), dt.date(2026, 3, 1))
# "Current clean" month - August is still being revised by PortWatch, so the
# headline comparison uses July; August is shown for context only.
CURRENT_CLEAN = dt.date(2026, 7, 1)

HORMUZ = "chokepoint6"


def _resolve(con: duckdb.DuckDBPyConnection, name_like: str) -> tuple[str, str, str] | None:
    row = con.execute(
        """
        SELECT entity_id, any_value(entity_name), any_value(iso3)
        FROM observation
        WHERE lower(entity_name) LIKE lower(?) AND entity_type = 'port'
        GROUP BY entity_id ORDER BY count(*) DESC LIMIT 1
        """,
        [name_like],
    ).fetchone()
    return (row[0], row[1], row[2]) if row else None


def _monthly(con: duckdb.DuckDBPyConnection, entity_id: str, metric: str,
             since: dt.date) -> dict[str, float]:
    rows = con.execute(
        """
        SELECT strftime(date_trunc('month', obs_date), '%Y-%m') AS mon, avg(value)
        FROM observation
        WHERE entity_id = ? AND metric = ? AND obs_date >= ?
        GROUP BY 1 ORDER BY 1
        """,
        [entity_id, metric, since],
    ).fetchall()
    return {m: round(v, 1) for m, v in rows}


def _window_avg(con: duckdb.DuckDBPyConnection, entity_id: str, metric: str,
                lo: dt.date, hi: dt.date) -> float | None:
    row = con.execute(
        "SELECT avg(value) FROM observation "
        "WHERE entity_id = ? AND metric = ? AND obs_date >= ? AND obs_date < ?",
        [entity_id, metric, lo, hi],
    ).fetchone()
    return round(row[0], 1) if row and row[0] is not None else None


def _pct(now: float | None, base: float | None) -> float | None:
    if now is None or not base:
        return None
    return round(100 * now / base, 1)


def main() -> None:
    con = duckdb.connect(str(settings.db_path), read_only=True)

    meta: dict[str, Any] = {
        "generated": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "data_source": "IMF PortWatch (portwatch.imf.org)",
        "db_coverage": con.execute(
            "SELECT min(obs_date), max(obs_date) FROM observation"
        ).fetchone(),
        "precrisis_window": [d.isoformat() for d in PRECRISIS],
        "current_clean_month": CURRENT_CLEAN.isoformat(),
        "notes": (
            "PortWatch revises its most recent ~2 weeks upward as more satellite "
            "AIS arrives; the headline comparison therefore uses July 2026, not "
            "August. Figures are PortWatch estimates, not measured cargo volumes."
        ),
    }
    meta["db_coverage"] = [str(x) for x in meta["db_coverage"]]

    # --- Chokepoint: container transits + capacity -----------------------
    hormuz = {
        "n_container_monthly": _monthly(con, HORMUZ, "n_container", dt.date(2025, 9, 1)),
        "capacity_container_monthly": _monthly(
            con, HORMUZ, "capacity_container", dt.date(2025, 9, 1)
        ),
    }
    for key, metric in (("n_container", "n_container"),
                        ("capacity_container", "capacity_container")):
        base = _window_avg(con, HORMUZ, metric, *PRECRISIS)
        cur = _window_avg(con, HORMUZ, metric, CURRENT_CLEAN,
                          CURRENT_CLEAN + dt.timedelta(days=31))
        hormuz[f"{key}_precrisis"] = base
        hormuz[f"{key}_current"] = cur
        hormuz[f"{key}_pct_of_normal"] = _pct(cur, base)

    # --- Jebel Ali: the Gulf container hub -----------------------------
    ja_id, ja_name, ja_iso = _resolve(con, "%jebel ali%")  # type: ignore[misc]
    jebel_ali: dict[str, Any] = {"entity_id": ja_id, "name": ja_name, "iso3": ja_iso}
    for key, metric in (
        ("portcalls_container", "portcalls_container"),
        ("import_container", "import_container"),
        ("export_container", "export_container"),
    ):
        jebel_ali[f"{key}_monthly"] = _monthly(con, ja_id, metric, dt.date(2025, 9, 1))
        base = _window_avg(con, ja_id, metric, *PRECRISIS)
        cur = _window_avg(con, ja_id, metric, CURRENT_CLEAN,
                          CURRENT_CLEAN + dt.timedelta(days=31))
        jebel_ali[f"{key}_precrisis"] = base
        jebel_ali[f"{key}_current"] = cur
        jebel_ali[f"{key}_pct_of_normal"] = _pct(cur, base)

    # --- Reroute: candidate beneficiary container ports ----------------
    candidates = [
        "%jawaharlal%", "%nhava sheva%", "%mundra%", "%hazira%", "%pipavav%",
        "%karachi%", "%port qasim%", "%salalah%", "%sohar%", "%damietta%",
        "%port said%", "%colombo%", "%piraeus%", "%king abdullah%", "%jeddah%",
        "%dammam%", "%aqaba%",
    ]
    seen: set[str] = set()
    reroute: list[dict[str, Any]] = []
    for pat in candidates:
        hit = _resolve(con, pat)
        if not hit or hit[0] in seen:
            continue
        seen.add(hit[0])
        eid, name, iso = hit
        base = _window_avg(con, eid, "portcalls_container", *PRECRISIS)
        cur = _window_avg(con, eid, "portcalls_container", CURRENT_CLEAN,
                          CURRENT_CLEAN + dt.timedelta(days=31))
        if base is None or cur is None or base < 0.3:
            continue
        reroute.append(
            {
                "entity_id": eid,
                "name": name,
                "iso3": iso,
                "precrisis_calls_per_day": base,
                "current_calls_per_day": cur,
                "pct_change": round(100 * (cur - base) / base, 0),
            }
        )
    reroute.sort(key=lambda r: r["pct_change"], reverse=True)

    payload = {
        "meta": meta,
        "hormuz_chokepoint": hormuz,
        "jebel_ali": jebel_ali,
        "reroute_candidates": reroute,
    }
    OUT.write_text(json.dumps(payload, indent=2))
    ja_pct = jebel_ali["portcalls_container_pct_of_normal"]
    winners = ", ".join(f"{r['name']} {r['pct_change']:+.0f}%" for r in reroute[:5])
    print(f"wrote {OUT}")
    print(f"  Hormuz container transits: {hormuz['n_container_pct_of_normal']}% of normal")
    print(f"  Jebel Ali container calls: {ja_pct}% of normal")
    print(f"  reroute winners: {winners}")
    con.close()


if __name__ == "__main__":
    main()
