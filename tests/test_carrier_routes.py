"""Carrier route stop-counting and transit-time lookup, plus a sanity check
that the seed data file actually loads."""

from __future__ import annotations

from logjam.analytics.carrier_routes import (
    CarrierService,
    PortCall,
    find_routes,
    load_ports,
    load_services,
)

# A tiny synthetic rotation, deliberately shaped to exercise: a direct call,
# an intermediate stop, a transshipment-only call, and a published transit
# time alongside an unpublished leg needing the distance estimate.
_PORTS = {
    "Alpha": (0.0, 0.0),
    "Bravo": (1.0, 0.0),
    "Charlie": (2.0, 0.0),
    "Delta": (3.0, 0.0),
    "Echo": (10.0, 0.0),
}
_SERVICE = CarrierService(
    carrier="TestLine",
    service="TL1",
    operator_note="synthetic test fixture",
    route_type="Test",
    source="unit test",
    calls=(
        PortCall(port="Alpha"),
        PortCall(port="Bravo"),
        PortCall(port="Charlie", transship=True),
        PortCall(port="Delta"),
    ),
    transit_days={("Alpha", "Delta"): 7},
)


def test_direct_call_has_zero_stops() -> None:
    matches = find_routes("Alpha", "Bravo", [_SERVICE], _PORTS)
    assert len(matches) == 1
    m = matches[0]
    assert m.direct is True
    assert m.stops_between == 0


def test_transshipment_call_does_not_count_as_a_stop() -> None:
    # Alpha -> Delta passes through Bravo (direct call) and Charlie
    # (transshipment only) - only Bravo counts as a stop.
    matches = find_routes("Alpha", "Delta", [_SERVICE], _PORTS)
    assert len(matches) == 1
    m = matches[0]
    assert m.stops_between == 1
    assert m.direct is False


def test_published_transit_time_is_not_estimated() -> None:
    matches = find_routes("Alpha", "Delta", [_SERVICE], _PORTS)
    m = matches[0]
    assert m.transit_days == 7
    assert m.transit_estimated is False


def test_unpublished_leg_falls_back_to_a_labeled_estimate() -> None:
    matches = find_routes("Alpha", "Bravo", [_SERVICE], _PORTS)
    m = matches[0]
    assert m.transit_estimated is True
    assert m.transit_days is not None
    assert m.transit_days >= 0


def test_direction_changes_the_stop_count() -> None:
    # A rotation is a repeating loop, so both directions eventually reach
    # any in-rotation pair - but going "the long way round" costs more
    # stops, and that asymmetry (not a reverse-is-impossible rule) is what
    # should show up here. Alpha -> Bravo is the very next call (0 stops);
    # Bravo -> Alpha has to sail the rest of the loop first.
    forward = find_routes("Alpha", "Bravo", [_SERVICE], _PORTS)[0]
    backward = find_routes("Bravo", "Alpha", [_SERVICE], _PORTS)[0]
    assert forward.stops_between == 0
    assert backward.stops_between > forward.stops_between


def test_unserved_pair_reports_no_matches_without_crashing() -> None:
    matches = find_routes("Echo", "Alpha", [_SERVICE], _PORTS)
    assert matches == []


def test_seed_data_file_loads_cleanly() -> None:
    services = load_services()
    ports = load_ports()
    assert len(services) >= 8
    assert "Djibouti" in ports
    # Every port referenced by a call resolves to a coordinate - this is the
    # main way a typo in the yaml would silently go unnoticed otherwise.
    missing = {
        call.port
        for svc in services
        for call in svc.calls
        if call.port not in ports
    }
    assert not missing, f"calls with no coordinate entry: {missing}"


def test_real_medex_pair_is_published_and_direct() -> None:
    services = load_services()
    ports = load_ports()
    matches = find_routes("Jeddah", "Djibouti", services, ports)
    medex = next(m for m in matches if m.service.service == "MEDEX")
    assert medex.direct is True
    assert medex.transit_estimated is False
    assert medex.transit_days == 2
