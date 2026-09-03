"""logjam - detect where maritime trade flow is blocked and where it reroutes.

Pipeline overview
-----------------
1. ``ingest``    - PortWatch daily port/chokepoint activity (batch); plus a
                   sampled AISStream feed for the live anchorage-queue signal
                   (free feed covers Europe / N. America only - see METHODOLOGY).
2. ``store``     - normalise both into one DuckDB ``observation`` table.
3. ``analytics`` - per-series short + year-over-year baselines, then flag
                   bottlenecks, score reroute opportunities, and judge recovery.

Everything is driven from :mod:`logjam.cli` or ``scripts/refresh.py``.
"""

__version__ = "0.1.0"
