"""Open-source logistics / supply-chain bottleneck and opportunity identifier.

Pipeline overview
-----------------
1. ``ingest``    - pull raw daily activity from external sources (PortWatch first).
2. ``store``     - normalise into a DuckDB analytical database.
3. ``analytics`` - compute per-series baselines, flag bottlenecks, score opportunities.

Everything is driven from :mod:`logjam.cli` or ``scripts/refresh.py``.
"""

__version__ = "0.1.0"
