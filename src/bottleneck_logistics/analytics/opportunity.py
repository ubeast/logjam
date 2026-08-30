"""Opportunity detection: bottleneck in one group member, headroom in another.

Reads ``resources/substitution_groups.yaml``, resolves each member to a
PortWatch entity, and for every date where at least one member is bottlenecked
emits an 'opportunity' signal for each member that is simultaneously running
at or above its own baseline (robust_z >= -opportunity_z_threshold, i.e. not
itself degraded; a positive z means it is actively absorbing diverted volume).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import yaml

from bottleneck_logistics.config import settings


@dataclass(frozen=True)
class ResolvedMember:
    group: str
    entity_type: str
    entity_id: str
    entity_name: str
    metric: str


def _load_groups(path: Path) -> tuple[list[dict[str, Any]], str]:
    with path.open() as fh:
        doc = yaml.safe_load(fh)
    return doc.get("groups", []), doc.get("default_metric", "portcalls_container")


def _resolve_member(
    con: duckdb.DuckDBPyConnection,
    member: dict[str, Any],
    entity_type: str,
) -> tuple[str, str] | None:
    """Return (entity_id, entity_name) or None if unresolved/ambiguous-empty."""
    if "portid" in member:
        row = con.execute(
            "SELECT entity_id, any_value(entity_name) FROM observation "
            "WHERE entity_id = ? GROUP BY entity_id",
            [member["portid"]],
        ).fetchone()
        return (row[0], row[1]) if row else None

    where = ["entity_type = ?", "lower(entity_name) LIKE lower(?)"]
    params: list[Any] = [entity_type, member["match"]]
    if member.get("iso3"):
        where.append("iso3 = ?")
        params.append(member["iso3"])

    # Prefer the highest-volume match (most rows) when a pattern hits several.
    row = con.execute(
        f"""
        SELECT entity_id, any_value(entity_name) AS name, count(*) AS n
        FROM observation
        WHERE {' AND '.join(where)}
        GROUP BY entity_id
        ORDER BY n DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    return (row[0], row[1]) if row else None


def resolve_groups(con: duckdb.DuckDBPyConnection) -> tuple[list[ResolvedMember], list[str]]:
    groups, top_default_metric = _load_groups(settings.substitution_groups_path)
    resolved: list[ResolvedMember] = []
    unresolved: list[str] = []

    for grp in groups:
        gname = grp["name"]
        etype = grp.get("entity_type", "port")
        metric = grp.get("default_metric", top_default_metric)
        for member in grp.get("members", []):
            hit = _resolve_member(con, member, etype)
            label = member.get("portid") or member.get("match", "?")
            if hit is None:
                unresolved.append(f"{gname}: {label}")
                continue
            resolved.append(
                ResolvedMember(gname, etype, hit[0], hit[1], metric)
            )
    return resolved, unresolved


def detect_opportunities(con: duckdb.DuckDBPyConnection) -> int:
    """Populate ``signal`` rows of type 'opportunity'. Returns rows written."""
    members, _unresolved = resolve_groups(con)
    con.execute("DELETE FROM signal WHERE signal_type = 'opportunity'")
    if not members:
        return 0

    by_group: dict[str, list[ResolvedMember]] = {}
    for m in members:
        by_group.setdefault(m.group, []).append(m)

    bt = settings.bottleneck_z_threshold
    ot = settings.opportunity_z_threshold
    written = 0

    for gname, gmembers in by_group.items():
        if len(gmembers) < 2:
            continue
        ids = [m.entity_id for m in gmembers]
        name_by_id = {m.entity_id: m.entity_name for m in gmembers}
        metric = gmembers[0].metric
        group_entity_type = gmembers[0].entity_type
        placeholders = ",".join("?" for _ in ids)

        # One row per (entity, date) with its robust_z for this group's metric.
        # (`baseline` has no name column - names come from ``name_by_id``.)
        rows = con.execute(
            f"""
            SELECT b.obs_date, b.entity_id, b.value, b.expected, b.robust_z
            FROM baseline b
            WHERE b.metric = ?
              AND b.entity_id IN ({placeholders})
              AND b.n_obs >= ?
            ORDER BY b.obs_date
            """,
            [metric, *ids, settings.baseline_min_observations],
        ).fetchall()

        per_date: dict[dt.date, list[tuple]] = {}
        for r in rows:
            per_date.setdefault(r[0], []).append(r)

        for obs_date, day_rows in per_date.items():
            # row = (obs_date, entity_id, value, expected, robust_z)
            bottlenecked = [r for r in day_rows if r[4] <= -bt]
            if not bottlenecked:
                continue
            alternatives = [r for r in day_rows if r[4] >= -ot and r not in bottlenecked]
            if not alternatives:
                continue

            worst = min(bottlenecked, key=lambda r: r[4])
            worst_id, worst_val, worst_exp, worst_z = worst[1], worst[2], worst[3], worst[4]
            for alt in alternatives:
                _, alt_id, alt_val, alt_exp, alt_z = alt
                alt_name = name_by_id.get(alt_id, alt_id)
                lift_pct = None if not alt_exp else round(100 * (alt_val - alt_exp) / alt_exp, 1)
                detail = json.dumps(
                    {
                        "group": gname,
                        "metric": metric,
                        "congested_port": {
                            "entity_id": worst_id,
                            "name": name_by_id.get(worst_id, worst_id),
                            "robust_z": round(worst_z, 2),
                            "drop_pct_vs_expected": (
                                None if not worst_exp
                                else round(100 * (worst_val - worst_exp) / worst_exp, 1)
                            ),
                        },
                        "alternative_lift_pct_vs_expected": lift_pct,
                    }
                )
                con.execute(
                    """
                    INSERT OR REPLACE INTO signal
                        (signal_type, entity_type, entity_id, entity_name, metric, obs_date,
                         value, expected, robust_z, severity, detail)
                    VALUES ('opportunity', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        group_entity_type,
                        alt_id, alt_name, metric, obs_date,
                        alt_val, alt_exp, alt_z,
                        abs(worst_z),  # severity ranked by how bad the congested side is
                        detail,
                    ],
                )
                written += 1

    return written
