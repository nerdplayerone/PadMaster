"""Write a self-contained HTML report (no internet needed, opens in any browser)."""

from __future__ import annotations

import html
import math
from datetime import datetime

from . import __version__
from .analysis import INFO, NODATA, OK, PROBLEM, THRESHOLDS, WATCH, Report, clock, summary_counts

STATUS = {
    OK: ("✓", "OK"),
    WATCH: ("!", "Watch"),
    PROBLEM: ("✕", "Problem"),
    NODATA: ("–", "No data"),
    INFO: ("i", "Info"),
}

CSS = """
.viz-root{color-scheme:light;
 --surface-0:#f4f3f0;--surface-1:#fcfcfb;--line:#dddcd7;--grid:#e8e7e3;
 --text-primary:#0b0b0b;--text-secondary:#52514e;--text-muted:#7a7974;
 --series-1:#2a78d6;
 --q1:#cde2fb;--q2:#9ec5f4;--q3:#6da7ec;--q4:#3987e5;--q5:#256abf;--q6:#184f95;--q7:#0d366b;
 --good:#0ca30c;--warning:#fab219;--critical:#d03b3b;--info:#2a78d6;--nodata:#9a9993;}
@media (prefers-color-scheme: dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;
 --surface-0:#111110;--surface-1:#1a1a19;--line:#33332f;--grid:#2a2a27;
 --text-primary:#f0efec;--text-secondary:#c3c2b7;--text-muted:#8f8e86;
 --series-1:#3987e5;
 --q1:#104281;--q2:#184f95;--q3:#256abf;--q4:#2a78d6;--q5:#5598e7;--q6:#86b6ef;--q7:#cde2fb;
 --info:#3987e5;--nodata:#6b6a64;}}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-0)}
.viz-root{font-family:Inter,"Segoe UI",system-ui,-apple-system,Roboto,Helvetica,Arial,sans-serif;
 background:var(--surface-0);color:var(--text-primary);padding:28px;max-width:1180px;margin:0 auto;line-height:1.45}
h1{font-size:28px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:18px;margin:36px 0 12px}
h3{font-size:15px;margin:0 0 8px}
.sub{color:var(--text-secondary);font-size:14px}
.card{background:var(--surface-1);border:1px solid var(--line);border-radius:12px;padding:18px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}
.tiles{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}
.tile{background:var(--surface-1);border:1px solid var(--line);border-radius:12px;padding:12px 16px;min-width:130px}
.tile .n{font-size:30px;font-weight:700}
.tile .l{font-size:13px;color:var(--text-secondary)}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;color:var(--text-secondary);font-weight:600;border-bottom:1px solid var(--line);padding:8px 8px}
td{border-bottom:1px solid var(--grid);padding:8px 8px;vertical-align:top}
td.v{font-weight:600;white-space:nowrap;font-variant-numeric:tabular-nums}
td.d{color:var(--text-secondary);font-size:13px}
.badge{display:inline-flex;align-items:center;gap:6px;font-weight:600;font-size:13px;white-space:nowrap}
.dot{display:inline-flex;width:18px;height:18px;border-radius:50%;align-items:center;justify-content:center;
 font-size:11px;color:#0b0b0b;font-weight:800}
.s-ok .dot{background:var(--good)} .s-watch .dot{background:var(--warning)}
.s-problem .dot{background:var(--critical);color:#fff} .s-info .dot{background:var(--info);color:#fff}
.s-nodata .dot{background:var(--nodata)}
.warn{border-left:4px solid var(--warning);padding:10px 14px;background:var(--surface-1);border-radius:8px;margin:14px 0;font-size:14px}
svg text{fill:var(--text-secondary);font-size:11px;font-family:inherit}
.cap{font-size:12px;color:var(--text-muted);margin-top:6px}
.q0{fill:transparent}.q1{fill:var(--q1)}.q2{fill:var(--q2)}.q3{fill:var(--q3)}.q4{fill:var(--q4)}
.q5{fill:var(--q5)}.q6{fill:var(--q6)}.q7{fill:var(--q7)}
.legend{display:flex;align-items:center;gap:4px;font-size:12px;color:var(--text-muted);margin-top:6px}
.legend span.sw{width:16px;height:10px;border-radius:2px;display:inline-block}
details{margin-top:8px} summary{cursor:pointer;color:var(--text-secondary);font-size:14px}
.foot{margin-top:40px;font-size:12px;color:var(--text-muted)}
"""


def e(s) -> str:
    return html.escape(str(s))


def badge(status: str) -> str:
    icon, label = STATUS[status]
    return f'<span class="badge s-{status}"><span class="dot">{icon}</span>{label}</span>'


def fmt_pct(x: float) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:.1f}%"


# ---------------------------------------------------------------- charts

def heatmap_svg(grid: list[list[int]], rest_points: list[tuple[float, float]], extent: float = 1.0,
                label: str = "Stick position heatmap") -> str:
    g = len(grid)
    size = 260
    cell = size / g
    pad = 20
    mx = max((v for row in grid for v in row), default=0)
    parts = [f'<svg viewBox="0 0 {size + 2 * pad} {size + 2 * pad}" width="100%" style="max-width:320px" role="img" '
             f'aria-label="{e(label)}">']
    cx = cy = pad + size / 2
    if extent >= 1.0:
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{size / 2}" fill="none" stroke="var(--line)" stroke-width="1"/>')
    else:
        parts.append(f'<text x="{pad + 2}" y="{pad + size + 14}">±{extent * 100:.0f}%</text>')
    parts.append(f'<rect x="{pad}" y="{pad}" width="{size}" height="{size}" fill="none" stroke="var(--grid)"/>')
    parts.append(f'<line x1="{pad}" y1="{cy}" x2="{pad + size}" y2="{cy}" stroke="var(--grid)"/>')
    parts.append(f'<line x1="{cx}" y1="{pad}" x2="{cx}" y2="{pad + size}" stroke="var(--grid)"/>')
    if mx > 0:
        lmx = math.log1p(mx)
        for r, row in enumerate(grid):
            for c, v in enumerate(row):
                if not v:
                    continue
                q = max(1, min(7, 1 + int(math.log1p(v) / lmx * 6.999)))
                x = pad + c * cell
                y = pad + r * cell
                vx = ((c + 0.5) / g * 2 - 1) * extent
                vy = -((r + 0.5) / g * 2 - 1) * extent
                parts.append(f'<rect class="q{q}" x="{x:.2f}" y="{y:.2f}" width="{cell + 0.1:.2f}" height="{cell + 0.1:.2f}">'
                             f'<title>x {vx:+.2f}, y {vy:+.2f}: {v} samples</title></rect>')
    parts.append(f'<text x="{cx}" y="{pad - 6}" text-anchor="middle">up</text>')
    parts.append(f'<text x="{pad + size - 2}" y="{pad + size + 14}" text-anchor="end">right →</text>')
    parts.append("</svg>")
    legend = ('<div class="legend">fewer '
              + "".join(f'<span class="sw" style="background:var(--q{i})"></span>' for i in range(1, 8))
              + " more samples (log scale)</div>")
    return "".join(parts) + legend


def reach_svg(reach: list[float | None]) -> str:
    size = 260
    pad = 24
    cx = cy = pad + size / 2
    rad = size / 2 / 1.15  # leave room for values above 100%
    n = len(reach)
    parts = [f'<svg viewBox="0 0 {size + 2 * pad} {size + 2 * pad}" width="100%" style="max-width:320px" role="img" '
             f'aria-label="Outer reach by direction">']
    for frac, dash in ((0.5, "2 3"), (1.0, "5 4")):
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{rad * frac:.1f}" fill="none" stroke="var(--line)" '
                     f'stroke-dasharray="{dash}"/>')
    parts.append(f'<text x="{cx + 4}" y="{cy - rad - 4:.1f}">100%</text>')
    parts.append(f'<text x="{cx + 4}" y="{cy - rad * 0.5 - 4:.1f}">50%</text>')
    # Polyline segments through covered sectors.
    pts = []
    segs = []
    for k in range(n + 1):
        v = reach[k % n]
        if v is None:
            if len(pts) > 1:
                segs.append(pts)
            pts = []
            continue
        a = math.radians((k % n + 0.5) * 360 / n)
        pts.append((cx + math.cos(a) * rad * min(v, 1.15), cy - math.sin(a) * rad * min(v, 1.15), v, (k % n) * 360 / n))
    if len(pts) > 1:
        segs.append(pts)
    for sg in segs:
        d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y, _, _) in enumerate(sg))
        parts.append(f'<path d="{d}" fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round"/>')
    for k, v in enumerate(reach):
        if v is None:
            continue
        a = math.radians((k + 0.5) * 360 / n)
        x, y = cx + math.cos(a) * rad * min(v, 1.15), cy - math.sin(a) * rad * min(v, 1.15)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="transparent"><title>{k * 10}°–{k * 10 + 10}°: '
                     f'{v * 100:.1f}%</title></circle>')
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="var(--series-1)" stroke="var(--surface-1)" '
                     f'stroke-width="1.5" pointer-events="none"/>')
    parts.append("</svg>")
    return "".join(parts)


def interval_svg(hist: list[int]) -> str:
    """Bar chart of the time between reports (1 ms bins, last bin = longer)."""
    w, h, pad_l, pad_b = 300, 110, 8, 18
    n = len(hist)
    mx = max(hist) if hist and max(hist) else 1
    total = sum(hist) or 1
    bw = (w - pad_l) / n
    parts = [f'<svg viewBox="0 0 {w} {h + pad_b}" width="100%" style="max-width:360px" role="img" '
             f'aria-label="Time between reports">']
    parts.append(f'<line x1="{pad_l}" y1="{h}" x2="{w}" y2="{h}" stroke="var(--line)"/>')
    for i, v in enumerate(hist):
        if not v:
            continue
        bh = max(1.5, (v / mx) * (h - 8))
        x = pad_l + i * bw + 0.5
        rng = f"{i}–{i + 1} ms" if i < n - 1 else f"{n - 1} ms or more"
        parts.append(f'<rect x="{x:.1f}" y="{h - bh:.1f}" width="{max(1.0, bw - 1):.1f}" height="{bh:.1f}" rx="1" '
                     f'fill="var(--series-1)"><title>{rng}: {v} reports ({v / total * 100:.1f}%)</title></rect>')
    parts.append(f'<text x="{pad_l}" y="{h + 14}">0 ms</text>'
                 f'<text x="{w}" y="{h + 14}" text-anchor="end">{n - 1}+ ms</text>')
    parts.append("</svg>")
    return "".join(parts)


def _ms(x) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.2f} ms"


def _num(x, fmt: str = "{:.0f}") -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else fmt.format(x)


def hist_svg(bins: list[int]) -> str:
    w, h, pad_l, pad_b = 300, 120, 8, 18
    data = bins[1:]  # bin 0 (released) dominates, so it is left out
    mx = max(data) if data and max(data) else 1
    bw = (w - pad_l) / len(data)
    parts = [f'<svg viewBox="0 0 {w} {h + pad_b}" width="100%" style="max-width:360px" role="img" '
             f'aria-label="Trigger value distribution">']
    parts.append(f'<line x1="{pad_l}" y1="{h}" x2="{w}" y2="{h}" stroke="var(--line)"/>')
    for i, v in enumerate(data):
        bh = (v / mx) * (h - 8)
        x = pad_l + i * bw + 1
        lo, hi = (i + 1) * 5, (i + 2) * 5
        if v:
            parts.append(f'<rect x="{x:.1f}" y="{h - bh:.1f}" width="{bw - 2:.1f}" height="{bh:.1f}" rx="2" '
                         f'fill="var(--series-1)"><title>{lo}–{hi}%: {v} samples</title></rect>')
    parts.append(f'<text x="{pad_l}" y="{h + 14}">5%</text><text x="{w}" y="{h + 14}" text-anchor="end">100%</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------- page

def render(r: Report, log_name: str = "") -> str:
    m = r.meta
    s = r.session
    counts = summary_counts(r.findings)
    order = {PROBLEM: 0, WATCH: 1, OK: 2, INFO: 3, NODATA: 4}
    findings = sorted(r.findings, key=lambda f: order[f.status])

    out = [f'<!DOCTYPE html><html lang="en-GB"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<title>PadLab report: {e(m.get("device", "controller"))}</title><style>{CSS}</style></head>'
           f'<body><div class="viz-root">']

    out.append(f'<h1>{e(m.get("device", "Unknown controller"))}</h1>')
    out.append(f'<div class="sub">PadLab report · {e(m.get("started", ""))} · {clock(s["duration_ms"])} logged · '
               f'{s["active_min"]} active min · {s["inputs"]:,} inputs · {e(m.get("mode", "?"))} mode</div>')
    ids = s.get("ids") or {}
    dev_bits = []
    if ids.get("vid"):
        dev_bits.append(f'VID {ids["vid"]} · PID {ids["pid"]}')
    if ids.get("bus_name"):
        dev_bits.append(f'bus {ids["bus_name"]}')
    if m.get("connection"):
        dev_bits.append(f'connection {m["connection"]} (set by you)')
    if m.get("power"):
        end_p = m.get("power_end")
        dev_bits.append(f'power {m["power"]}' + (f' at start, {end_p} at end' if end_p and end_p != m["power"] else ""))
    if dev_bits:
        out.append(f'<div class="sub">{e(" · ".join(dev_bits))}</div>')
    if m.get("mode") == "joystick":
        out.append('<div class="warn">SDL has no mapping for this controller, so stick names are guesses and '
                   'triggers are not tested. Results for sticks may be wrong.</div>')
    if s["active_min"] < 10:
        out.append('<div class="warn">Short session. Some checks need more play time to give a result.</div>')

    out.append('<div class="tiles">')
    for st, label in ((PROBLEM, "Problems"), (WATCH, "Watch"), (OK, "OK"), (NODATA, "No data")):
        out.append(f'<div class="tile"><div class="n">{counts.get(st, 0)}</div><div class="l">{badge(st)}</div></div>')
    out.append("</div>")

    out.append('<h2>Results</h2><div class="card"><table><thead><tr><th>Status</th><th>Check</th><th>Result</th>'
               '<th>What it means</th></tr></thead><tbody>')
    for f in findings:
        out.append(f'<tr><td>{badge(f.status)}</td><td>{e(f.title)}</td><td class="v">{e(f.value)}</td>'
                   f'<td class="d">{e(f.detail)}</td></tr>')
    out.append("</tbody></table></div>")

    # Sticks
    out.append("<h2>Sticks</h2><div class='grid2'>")
    for side, label in (("l", "Left stick"), ("r", "Right stick")):
        st = r.sticks.get(side, {})
        out.append(f'<div class="card"><h3>{label}</h3>')
        if not st.get("enough"):
            out.append(f'<div class="sub">Not enough data ({st.get("samples", 0)} samples).</div></div>')
            continue
        out.append('<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px"><div>')
        out.append(heatmap_svg(st["heatmap"], st.get("rest_points", [])))
        out.append('<div class="cap">Where the stick was during play. A cross shape near the centre shows a '
                   'cross-shaped deadzone or snapping.</div></div><div>')
        out.append(reach_svg(st["reach"]))
        out.append(f'<div class="cap">Maximum value at full tilt, by direction ({st["reach_covered"]} of '
                   f'{THRESHOLDS["outer_sectors"]} directions reached). Dashed ring = 100%.</div></div><div>')
        out.append(heatmap_svg(st["heatmap_centre"], [], st["heatmap_centre_zoom"], "Centre close-up heatmap"))
        out.append(f'<div class="cap">Close-up of the centre (±{st["heatmap_centre_zoom"] * 100:.0f}%). An empty area '
                   'around the middle shows the in-built deadzone and its shape.</div></div>')
        iv = st.get("intervals", {})
        if iv.get("hist"):
            out.append("<div>" + interval_svg(iv["hist"]))
            out.append(f'<div class="cap">Time between reports while the stick moves ({iv["n"]:,} reports). '
                       'One tall bar means a steady rate. A wide spread means jitter. This is not input latency.</div></div>')
        out.append("</div>")
        ho = st.get("handsoff")
        res_x, res_y = st["resolution"][f"{side}x"], st["resolution"][f"{side}y"]
        rows = [
            ("Smallest value out of centre", fmt_pct(st["inner_dz"])),
            ("Axial dead band X / Y", f'{fmt_pct(st["axial_x"])} / {fmt_pct(st["axial_y"])}'),
            ("Rest offset, hands-off check", fmt_pct(ho["max_mag"]) if ho else "not done"),
            ("Rest offset during play (typical / 90th pct)", f'{fmt_pct(st["rest_typical"])} / {fmt_pct(st["rest_worst"])}'),
            ("Rest moments found", str(st["rest_windows"])),
            ("Update interval while moving (logger view)", "-" if math.isnan(st["update_ms"]) else f'{st["update_ms"]:.1f} ms'),
            ("Minutes of stick movement", f'{st["motion_min"]:.1f}'),
            ("Update rate while moving (median)", _num(iv.get("rate_hz"), "{:.0f} Hz")),
            ("Time between reports: mean / median", f'{_ms(iv.get("mean"))} / {_ms(iv.get("median"))}'),
            ("Time between reports: 1st / 99th pct", f'{_ms(iv.get("p01"))} / {_ms(iv.get("p99"))}'),
            ("Jitter: standard deviation / MAD", f'{_ms(iv.get("std"))} / {_ms(iv.get("mad"))}'),
            ("Late reports (more than 2x normal)", fmt_pct(iv.get("late_share"))),
            ("Noise at rest: peak-to-peak / std dev", f'{fmt_pct(st["noise_p2p"])} / {fmt_pct(st["noise_std"])}'),
            ("Circularity error", fmt_pct(st["circ_err"])),
            ("Return to centre: 90th pct / spread", f'{fmt_pct(st["centre_err"])} / {fmt_pct(st["centre_spread"])}'),
            ("Returns to rest after a push", str(st["centre_returns"])),
            ("Different values X / Y", f'{res_x["unique"]} / {res_y["unique"]}'),
            ("Typical step X / Y (raw)", f'{_num(res_x["step"])} / {_num(res_y["step"])}'),
            ("Estimated bits X / Y", f'{_num(res_x["bits"], "{:.1f}")} / {_num(res_y["bits"], "{:.1f}")}'),
        ]
        out.append("<details><summary>Numbers</summary><table>" +
                   "".join(f"<tr><td>{e(a)}</td><td class='v'>{e(b)}</td></tr>" for a, b in rows) + "</table></details>")
        out.append("</div>")
    out.append("</div>")

    # Triggers
    out.append("<h2>Triggers</h2><div class='grid2'>")
    for name, label in (("lt", "Left trigger"), ("rt", "Right trigger")):
        t = r.triggers.get(name, {})
        out.append(f'<div class="card"><h3>{label}</h3>')
        if not t.get("enough"):
            out.append('<div class="sub">Not enough data.</div></div>')
            continue
        out.append(hist_svg(t["hist"]))
        out.append(f'<div class="cap">How far the trigger was pulled, all samples above 5%. '
                   f'Start {fmt_pct(t["start"])} · full {fmt_pct(t["end"])} · {t["unique"]} values · '
                   f'{t["presses"]} pulls past 50%.')
        tr = t.get("resolution", {})
        if not math.isnan(tr.get("bits", float("nan"))):
            out.append(f' Typical step {tr["step"]} raw units (about {tr["bits"]:.1f} bit).')
        out.append('</div></div>')
    out.append("</div>")

    # D-pad
    d = r.dpad
    out.append("<h2>D-pad</h2><div class='card'>")
    if d["per_dir"]:
        fl: dict[str, int] = {}
        bl: dict[str, int] = {}
        for x in d["flicker_times"]:
            fl[x["dir"]] = fl.get(x["dir"], 0) + 1
        for x in d["blip_times"]:
            bl[x["dir"]] = bl.get(x["dir"], 0) + 1
        out.append("<table><thead><tr><th>Diagonal</th><th>Times entered</th><th>Flickers</th>"
                   "<th>Accidental blips</th><th>Rolls: through / skipped / gap</th></tr></thead><tbody>")
        for k in ("up-left", "up-right", "down-left", "down-right"):
            out.append(f"<tr><td>{k}</td><td class='v'>{d['per_dir'].get(k, 0)}</td>"
                       f"<td class='v'>{fl.get(k, 0)}</td><td class='v'>{bl.get(k, 0)}</td>"
                       f"<td class='v'>{d['rolls_through'].get(k, 0)} / {d['rolls_skipped'].get(k, 0)} / {d['rolls_gap'].get(k, 0)}</td></tr>")
        out.append("</tbody></table>")
    else:
        out.append('<div class="sub">No diagonals in this session.</div>')
    out.append(f'<div class="cap">{d["card_presses"]} single-direction presses · {d["diag_entries"]} diagonals · '
               f'{d["flickers"]} flickers · {d["blips"]} blips.</div></div>')

    # Event list
    events = []
    for o in r.connection["outages"]:
        events.append((o["t"], "Disconnect", f'back after {o["ms"] / 1000:.1f} s' if o["ms"] else "did not come back"))
    for x in r.buttons["double_times"]:
        events.append((x["t"], "Double input", f'{x["button"]}: {x["gap_ms"]:.1f} ms gap'))
    for x in d["flicker_times"]:
        events.append((x["t"], "D-pad flicker", f'{x["dir"]}: dropped for {x["ms"]:.0f} ms'))
    for x in d["blip_times"]:
        events.append((x["t"], "D-pad blip", f'{x["dir"]} for {x["ms"]:.0f} ms'))
    for x in d["roll_skip_times"]:
        det = f'{x["dir"]} not seen: jumped straight to the next direction'
        events.append((x["t"], "D-pad diagonal skipped", det))
    for side, label in (("l", "Left stick"), ("r", "Right stick")):
        for x in r.sticks.get(side, {}).get("stutters", []):
            events.append((x["t"], f"{label} stutter", f'{x["gap_ms"]:.0f} ms gap, jump {x["jump"] * 100:.0f}%'))
    events.sort()
    out.append(f"<h2>Event times ({len(events)})</h2><div class='card'>")
    out.append('<div class="sub" style="margin-bottom:8px">Time from the start of the log. Use these to find each '
               'event in your gameplay recording.</div>')
    if events:
        out.append("<table><thead><tr><th>Time</th><th>Event</th><th>Detail</th></tr></thead><tbody>")
        for t, kind, det in events[:500]:
            out.append(f"<tr><td class='v'>{clock(t)}</td><td>{e(kind)}</td><td class='d'>{e(det)}</td></tr>")
        out.append("</tbody></table>")
        if len(events) > 500:
            out.append(f'<div class="cap">First 500 of {len(events)} shown.</div>')
    else:
        out.append('<div class="sub">No events.</div>')
    out.append("</div>")

    out.append("<h2>How to read this</h2><div class='card' style='font-size:14px'><ul>"
               "<li>PadLab only reads the controller while you play. It does not know what you meant to press, so each "
               "check looks for patterns that a hand does not make, or uses moments when you did not touch a stick.</li>"
               "<li>OK / Watch / Problem limits are PadLab defaults (judgement calls), not industry standards. "
               "You can change them in <code>THRESHOLDS</code> in <code>analysis.py</code>.</li>"
               "<li>Timing is limited by the logger loop (about 1 ms) and by Windows. PadLab can't measure true input "
               "latency. That needs hardware.</li>"
               "<li>Steam Input, DS4Windows and similar tools can change what PadLab sees. Turn them off for a clean test.</li>"
               "<li>Compare controllers only with the same player, game and connection.</li></ul></div>")

    out.append(f'<div class="foot">PadLab {e(__version__)} · log {e(log_name)} · logger {e(m.get("padlab", "?"))} · '
               f'SDL {e(m.get("sdl", "?"))} · generated {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>')
    out.append("</div></body></html>")
    return "".join(out)
