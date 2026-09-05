# logjam

Detect where maritime trade flow is blocked and where it reroutes, from free public
data. See `README.md` for the full pitch and `docs/METHODOLOGY.md` for the method.

## What it does

Answers three questions per port / chokepoint:

1. **Where is flow blocked?** — transits/throughput below that location's own robust
   seasonal baseline.
2. **Has a known disruption recovered?** — current throughput vs the same calendar
   period a year ago (`logjam recovery`).
3. **Where is the opportunity?** — when one port in a substitution group is
   bottlenecked, which alternative in the group is at/above baseline.

## Pipeline

IMF PortWatch (daily port calls + chokepoint transits, weekly refresh) → **DuckDB**
→ rolling robust baseline + year-over-year baseline → bottleneck signals →
opportunity signals → `recovery` verdicts. There's also a live-AIS queue adapter
(`ais-collect` / `ais-reduce`).

## Layout

```
src/logjam/            the package — analytics/, store/, cli.py (Typer app), config.py
scripts/refresh.py     weekly data pull (run by GitHub Actions)
scripts/reports/       one generator per disruption brief
reports/               committed briefs (.md/.html/.pdf) — regenerate via the scripts, don't hand-edit
docs/METHODOLOGY.md    the baseline math and signal definitions
```

## Env & checks

Python 3.11+. `uv sync --extra dev`.

```bash
uv run pytest -q                 # tests/ — fixture `con` = in-memory DuckDB w/ schema; respx mocks httpx
uv run ruff check .              # line-length 100, py311
uv run mypy                      # strict
```

CLI: `uv run logjam {refresh,bottlenecks,opportunities,recovery,ais-collect,ais-reduce}`.

## Gotchas

- `scripts/reports/*.py` and `scripts/build_pdfs.py` are **E501-exempt** — they embed
  long prose / HTML / CSS strings. Don't hard-wrap them.
- The files in `reports/` are build artifacts, committed for reference. Change the
  generator, not the output.
- Optional extras: `dashboard` (streamlit/pydeck), `api` (fastapi).
