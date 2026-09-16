"""Carrier route reference: named service rotations and stop/transit-time lookups.

Reads ``resources/carrier_routes.yaml`` - a small, hand-curated seed set of
REAL published container-service rotations (not derived from PortWatch; each
service's port calls and transit times come from that carrier's own network
publications - see each service's ``source`` field). Used by the
``carrier-route`` CLI command and the ``carrier_routes_2026`` report to
compare, for an origin and destination, how many stops a service's rotation
makes between them, and - where the carrier publishes one - the real transit
time, kept distinct from a distance-based estimate for services that don't.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

from logjam.config import settings

# Typical container-ship service speed, used ONLY to estimate a transit time
# when no carrier-published figure exists. Real-world service speeds run
# roughly 16-22 knots; 18 is a reasonable mid-string average. This is
# steaming time alone - it excludes port dwell, so it under-states any real
# multi-stop transit and must never be shown without the "estimated" label.
DEFAULT_SPEED_KN = 18.0
_HOURS_PER_DAY = 24
EARTH_RADIUS_NM = 3440.065  # mean Earth radius in nautical miles


@dataclass(frozen=True)
class PortCall:
    port: str
    transship: bool = False


@dataclass(frozen=True)
class CarrierService:
    carrier: str
    service: str
    operator_note: str
    route_type: str
    source: str
    calls: tuple[PortCall, ...]
    # Real, carrier-published "From -> To" transit times in days. Empty for
    # services with no published matrix - never a guessed number here.
    transit_days: dict[tuple[str, str], int]


@dataclass(frozen=True)
class RouteMatch:
    service: CarrierService
    origin_call: str
    destination_call: str
    stops_between: int
    direct: bool
    transit_days: int | None
    transit_estimated: bool
    distance_nm: float | None


def _load_yaml(path: Path) -> dict[str, object]:
    with path.open() as fh:
        doc = yaml.safe_load(fh)
    return dict(doc) if doc else {}


def load_ports(path: Path | None = None) -> dict[str, tuple[float, float]]:
    doc = _load_yaml(path or settings.carrier_routes_path)
    raw = doc.get("ports", {})
    if not isinstance(raw, dict):
        return {}
    return {str(name): (float(c[0]), float(c[1])) for name, c in raw.items()}


def load_services(path: Path | None = None) -> list[CarrierService]:
    doc = _load_yaml(path or settings.carrier_routes_path)
    raw_services = doc.get("services", [])
    if not isinstance(raw_services, list):
        return []

    services: list[CarrierService] = []
    for s in raw_services:
        calls = tuple(
            PortCall(port=str(c["port"]), transship=bool(c.get("transship", False)))
            for c in s["calls"]
        )
        transit: dict[tuple[str, str], int] = {}
        for pair, days in (s.get("transit_days") or {}).items():
            origin, _, destination = str(pair).partition(" -> ")
            transit[(origin, destination)] = int(days)
        services.append(
            CarrierService(
                carrier=str(s["carrier"]),
                service=str(s["service"]),
                operator_note=str(s.get("operator_note", "")),
                route_type=str(s.get("route_type", "")),
                source=str(s.get("source", "")),
                calls=calls,
                transit_days=transit,
            )
        )
    return services


def _find_port(name: str, candidates: list[str]) -> str | None:
    """Case-insensitive match: exact first, else the first substring hit."""
    lname = name.lower()
    for c in candidates:
        if c.lower() == lname:
            return c
    for c in candidates:
        if lname in c.lower():
            return c
    return None


def _great_circle_nm(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(math.sqrt(min(1.0, h)))


def _path_distance_nm(
    names: list[str], idxs: list[int], ports: dict[str, tuple[float, float]]
) -> float | None:
    total = 0.0
    for k in range(len(idxs) - 1):
        a, b = names[idxs[k]], names[idxs[k + 1]]
        if a not in ports or b not in ports:
            return None
        total += _great_circle_nm(ports[a], ports[b])
    return total


def find_routes(
    origin: str,
    destination: str,
    services: list[CarrierService],
    ports: dict[str, tuple[float, float]],
) -> list[RouteMatch]:
    """Every service whose rotation touches both ``origin`` and ``destination``.

    A named service is a repeating, one-way loop, not a symmetric line: this
    walks forward from ``origin`` to ``destination`` in the service's own
    printed sailing order, wrapping at most once around the list (as a real
    weekly rotation would on its next lap). Both ``find_routes(A, B, ...)``
    and ``find_routes(B, A, ...)`` can match the same service - a loop
    reaches every port it calls, eventually - but they are NOT symmetric:
    going "the long way round" the loop costs more stops and, on a service
    with published transit times, a larger real number of days. Query the
    specific direction you actually need; don't assume A->B and B->A give
    the same answer.

    Results are ranked fastest-first: a real published transit time beats an
    estimated one at the same day count, and fewer stops break remaining ties.
    """
    matches: list[RouteMatch] = []
    for svc in services:
        names = [c.port for c in svc.calls]
        o = _find_port(origin, names)
        d = _find_port(destination, names)
        if o is None or d is None or o == d:
            continue
        oi = names.index(o)
        n = len(names)
        di = next(
            (i % n for i in range(oi + 1, oi + n) if names[i % n] == d),
            None,
        )
        if di is None:
            continue

        span = (di - oi) % n
        idxs = [(oi + k) % n for k in range(span + 1)]
        between = idxs[1:-1]
        stops_between = sum(0 if svc.calls[i].transship else 1 for i in between)
        direct = stops_between == 0

        published = svc.transit_days.get((o, d))
        distance_nm = _path_distance_nm(names, idxs, ports)
        if published is not None:
            matches.append(
                RouteMatch(
                    service=svc,
                    origin_call=o,
                    destination_call=d,
                    stops_between=stops_between,
                    direct=direct,
                    transit_days=published,
                    transit_estimated=False,
                    distance_nm=distance_nm,
                )
            )
            continue

        est_days = (
            round(distance_nm / (DEFAULT_SPEED_KN * _HOURS_PER_DAY))
            if distance_nm is not None
            else None
        )
        matches.append(
            RouteMatch(
                service=svc,
                origin_call=o,
                destination_call=d,
                stops_between=stops_between,
                direct=direct,
                transit_days=est_days,
                transit_estimated=True,
                distance_nm=distance_nm,
            )
        )

    matches.sort(
        key=lambda m: (
            m.transit_days if m.transit_days is not None else 9999,
            m.stops_between,
        )
    )
    return matches
