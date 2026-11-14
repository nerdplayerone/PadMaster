"""Collect hardware latency results from Gamepadla.com into padlab/gamepadla_latency.json.

    python tools/fetch_gamepadla.py            # all controller pages
    python tools/fetch_gamepadla.py --limit 5  # a quick test

Run this by hand before a release. The PadMaster app never connects to Gamepadla.
All data belongs to Gamepadla.com, and the app shows it with credit and a link.

Rules this tool keeps:
- It reads only the English controller pages listed in the public sitemap.
  It does not read pages that robots.txt disallows (/result, /profile, query strings).
- One page every DELAY_S seconds.
- It keeps only the summary latency row for each connection, not the detailed tests.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "padlab", "gamepadla_latency.json")
SITE = "https://gamepadla.com"
UA = "PadMaster-data-tool/0.1"
DELAY_S = 3.0


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def controller_pages(sitemap: str) -> list[str]:
    urls = [html.unescape(u) for u in re.findall(r"<loc>([^<]+)</loc>", sitemap)]
    out = []
    for u in urls:
        path = u[len(SITE):] if u.startswith(SITE) else ""
        # English controller pages only: /name.html (no language prefix, no sub-folder).
        if re.fullmatch(r"/[a-z0-9][a-z0-9\-]*\.html", path):
            out.append(u)
    return sorted(set(out))


def _text(s: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def _num(s: str) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", s or "")
    return float(m.group()) if m else None


def parse_page(page: str, url: str) -> dict | None:
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    if not h1:
        return None
    name = _text(h1.group(1))
    rows = []
    for m in re.finditer(r"<tr class='merged_table_row[^']*'[^>]*>(.*?)</tr>", page, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)
        if len(cells) < 6:
            continue
        conn = _text(re.sub(r"<span class='primary-badge.*?</span>", "", cells[1], flags=re.S))
        vals = re.findall(r"title='(Button|Stick)'>[^<]*</span><span class='merged-metric-value'[^>]*>([^<]*)<", cells[3])
        lat = {k.lower(): _num(v) for k, v in vals}
        rows.append({
            "connection": conn,
            "mode": _text(cells[2]),
            "button_ms": lat.get("button"),
            "stick_ms": lat.get("stick"),
            "polling_hz": _num(_text(cells[4])),
            "primary": "primary-badge" in cells[1],
        })
    if not rows:
        return None
    return {"name": name, "url": url, "results": rows}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)
    pages = controller_pages(get(SITE + "/sitemap.xml"))
    if args.limit:
        pages = pages[: args.limit]
    pads = []
    for i, url in enumerate(pages, 1):
        try:
            item = parse_page(get(url), url)
        except Exception as exc:  # one bad page must not stop the run
            print(f"{i}/{len(pages)} skipped {url}: {exc}", file=sys.stderr)
            item = None
        if item:
            pads.append(item)
        print(f"{i}/{len(pages)} {'ok' if item else 'no latency'} {url}", flush=True)
        time.sleep(DELAY_S)
    data = {
        "source": "Gamepadla.com",
        "source_url": SITE,
        "collected": date.today().isoformat(),
        "controllers": sorted(pads, key=lambda p: p["name"].lower()),
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=0)
    print(f"Saved {len(pads)} controllers to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
