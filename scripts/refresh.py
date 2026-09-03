#!/usr/bin/env python
"""Cron entry point: `python scripts/refresh.py [--full]`.

Kept as a thin wrapper so CI / cron does not depend on the console-script being
installed on PATH.
"""

from __future__ import annotations

import argparse
import sys

from logjam.pipeline import refresh


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="Ignore stored data; backfill.")
    args = parser.parse_args()

    res = refresh(full_backfill=args.full, progress=lambda m: print(f"... {m}", flush=True))
    print(
        f"since={res.since} observations={res.observations_written} "
        f"ais_rows={res.ais_rows_written} baseline_rows={res.baseline_rows} "
        f"bottlenecks={res.bottlenecks} opportunities={res.opportunities}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
