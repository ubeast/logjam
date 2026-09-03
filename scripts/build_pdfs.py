#!/usr/bin/env python
"""Build the PDF deliverables from their sources.

    uv run --with markdown python scripts/build_pdfs.py

Produces:
  reports/hormuz_container_2026.pdf   <- reports/hormuz_container_2026.html
  docs/METHODOLOGY.pdf                <- docs/METHODOLOGY.md

Rendering uses headless Google Chrome (new headless mode), which runs the
report's JavaScript charts and loads its web fonts before printing. Set
``CHROME`` in the environment to override the binary path.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_CHROME_CANDIDATES = [
    os.environ.get("CHROME", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
    shutil.which("chrome") or "",
]


def _chrome() -> str:
    for c in _CHROME_CANDIDATES:
        if c and Path(c).exists():
            return c
    sys.exit("No Chrome/Chromium found. Set CHROME=/path/to/chrome and retry.")


def html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    subprocess.run(
        [
            _chrome(),
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            "--hide-scrollbars",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=15000",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ],
        check=True,
        capture_output=True,
    )
    if not pdf_path.exists():
        sys.exit(f"Chrome did not produce {pdf_path}")
    print(f"  {pdf_path.relative_to(ROOT)}  ({pdf_path.stat().st_size // 1024} KB)")


# Standalone print stylesheet for the Markdown docs - same type family and
# restrained palette as the HTML brief, tuned for A4/Letter paper.
_MD_CSS = """
@page { margin: 18mm 16mm; }
* { -webkit-print-color-adjust: exact; print-color-adjust: exact; box-sizing: border-box; }
body {
  font: 10.5pt/1.55 "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  color: #15211f; background: #fff; max-width: 46rem; margin: 0 auto; padding: 8mm 0;
}
h1, h2, h3, h4 { font-family: "Newsreader", Georgia, serif; font-weight: 500; line-height: 1.15; }
h1 { font-size: 24pt; margin: 0 0 .3em; letter-spacing: -.01em; }
h2 { font-size: 15pt; margin: 1.7em 0 .5em; padding-top: .7em; border-top: 1px solid #cdd6d8; break-after: avoid; }
h3 { font-size: 12pt; margin: 1.3em 0 .4em; break-after: avoid; }
p, li { margin: 0 0 .7em; }
strong { font-weight: 600; }
em { color: #3f5054; }
a { color: #15211f; text-decoration: none; }
code {
  font-family: "IBM Plex Mono", ui-monospace, Menlo, monospace; font-size: .86em;
  background: #f2f5f5; border: 1px solid #dde5e6; border-radius: 3px; padding: .05em .3em;
}
pre { background: #f6f8f8; border: 1px solid #dde5e6; border-radius: 4px; padding: .8em 1em; overflow-x: auto; }
pre code { background: none; border: none; padding: 0; font-size: .82em; }
blockquote {
  margin: 1em 0; padding: .5em 1em; border-left: 2px solid #b0591a;
  background: #f6f8f8; color: #3f5054; border-radius: 0 3px 3px 0;
}
blockquote p { margin: 0; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 9.5pt; break-inside: avoid; }
th, td {
  border-bottom: 1px solid #cdd6d8; padding: .4em .7em; text-align: left;
  font-variant-numeric: tabular-nums;
}
thead th {
  border-bottom: 1px solid #aab6b8; font-size: 8pt; letter-spacing: .04em;
  text-transform: uppercase; color: #6b7a7d; font-weight: 600;
}
td[align="right"], th[align="right"] { text-align: right; }
hr { border: none; border-top: 1px solid #cdd6d8; margin: 1.6em 0; }
h1 + p em, body > p:first-of-type em { color: #6b7a7d; }
"""


def md_to_pdf(md_path: Path, pdf_path: Path, *, title: str) -> None:
    import markdown  # noqa: PLC0415 - optional dep, imported on demand

    body = markdown.markdown(
        md_path.read_text(),
        extensions=["tables", "fenced_code", "sane_lists", "toc"],
    )
    html = (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>"
        "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
        "<link rel='stylesheet' href='https://fonts.googleapis.com/css2?"
        "family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&"
        "family=Newsreader:opsz,wght@6..72,400;6..72,500&display=swap'>"
        f"<style>{_MD_CSS}</style></head><body>{body}</body></html>"
    )
    with tempfile.NamedTemporaryFile(
        "w", suffix=".html", dir=md_path.parent, delete=False, encoding="utf-8"
    ) as fh:
        tmp = Path(fh.name)
        fh.write(html)
    try:
        html_to_pdf(tmp, pdf_path)
    finally:
        tmp.unlink(missing_ok=True)


# Every published HTML brief in reports/. Add a slug here when a new
# scripts/reports/<slug>.py generator lands.
_BRIEF_SLUGS = (
    "hormuz_container_2026",
    "suez_redsea_2026",
    "horn_of_africa_2026",
)


def main() -> None:
    print("Building PDFs:")
    for slug in _BRIEF_SLUGS:
        html = ROOT / "reports" / f"{slug}.html"
        if html.exists():
            html_to_pdf(html, html.with_suffix(".pdf"))
        else:
            print(f"  (skip {slug}.html - not generated yet)")
    md_to_pdf(
        ROOT / "docs" / "METHODOLOGY.md",
        ROOT / "docs" / "METHODOLOGY.pdf",
        title="logjam — Methodology",
    )


if __name__ == "__main__":
    main()
