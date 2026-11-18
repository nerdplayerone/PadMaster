"""Write a self-contained HTML report (no internet needed, opens in any browser)."""

from __future__ import annotations

import html
import math
from datetime import datetime

from . import __version__
from .theme import SCROLLBAR_CSS
from .analysis import ANALYSIS_VERSION, INFO, NODATA, OK, PROBLEM, THRESHOLDS, WATCH, Report, clock, summary_counts

STATUS = {
    OK: ("✓", "OK"),
    WATCH: ("!", "Watch"),
    PROBLEM: ("✕", "Problem"),
    NODATA: ("–", "No data"),
    INFO: ("i", "Info"),
}

CSS = """
.viz-root{color-scheme:dark;
 --surface-0:#0b0b0c;--surface-1:#141416;--surface-2:#1b1b1e;--line:#2e2e33;--grid:#222226;
 --text-primary:#f2f2f5;--text-secondary:#b9b9c2;--text-muted:#85858f;
 --silver:#d9d9de;--series-1:#c9ced8;
 --q1:#1e2430;--q2:#2b3445;--q3:#3f4c63;--q4:#5b6b86;--q5:#8291ab;--q6:#b1bccf;--q7:#e3e8f1;
 --good:#5fbf3a;--warning:#f0a531;--critical:#e5484d;--info:#9aa6bd;--nodata:#6b6a72;}
@media print{.viz-root{color-scheme:light;
 --surface-0:#ffffff;--surface-1:#f6f6f7;--surface-2:#efeff1;--line:#d4d4d8;--grid:#e6e6e9;
 --text-primary:#0b0b0c;--text-secondary:#45454c;--text-muted:#6d6d75;--silver:#2a2a2e;--series-1:#3a4a66;
 --q1:#e3e8f1;--q2:#b1bccf;--q3:#8291ab;--q4:#5b6b86;--q5:#3f4c63;--q6:#2b3445;--q7:#1e2430;
 --good:#2e8b12;--warning:#b87400;--critical:#c4262c;--info:#4b5a75;--nodata:#8a8990;}}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-0)}
.viz-root{font-family:"Segoe UI",Inter,system-ui,-apple-system,Roboto,Helvetica,Arial,sans-serif;
 background:var(--surface-0);color:var(--text-primary);padding:28px;max-width:1180px;margin:0 auto;line-height:1.45}
.head{display:flex;align-items:center;gap:16px;margin:0 0 8px;padding-bottom:14px;border-bottom:1px solid var(--line)}.head h1{margin:0}
.kicker{font-size:12px;letter-spacing:.16em;color:var(--text-muted);text-transform:uppercase}
.logo{border-radius:8px;flex:none}
h1{font-size:28px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:13px;margin:36px 0 12px;letter-spacing:.14em;text-transform:uppercase;color:var(--silver);font-weight:600}
h3{font-size:15px;margin:0 0 8px}
.sub{color:var(--text-secondary);font-size:14px}
.card{background:var(--surface-1);border:1px solid var(--line);border-radius:6px;padding:18px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}
.tiles{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}
.tile{background:var(--surface-1);border:1px solid var(--line);border-top:3px solid var(--nodata);border-radius:0;padding:12px 16px;min-width:140px}
.tile.t-problem{border-top-color:var(--critical)}.tile.t-watch{border-top-color:var(--warning)}.tile.t-ok{border-top-color:var(--good)}.tile.t-info{border-top-color:var(--info)}
.tile .n{font-size:32px;font-weight:600;font-variant-numeric:tabular-nums}
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
.legend{display:flex;flex-wrap:wrap;align-items:center;gap:4px;line-height:1.2;}
.legend .lt{white-space:nowrap}
.legend .ls{flex-basis:100%;white-space:nowrap}
.legend{font-size:12px;color:var(--text-muted);margin-top:6px}
.legend span.sw{width:16px;height:10px;border-radius:2px;display:inline-block}
details{margin-top:8px} summary{cursor:pointer;color:var(--text-secondary);font-size:14px}
.foot{margin-top:40px;font-size:12px;color:var(--text-muted)}
.gpl-head{display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;margin-bottom:10px}
.gpl a{color:var(--text)}
.gpl-small{font-size:12px;color:var(--text-muted);margin:12px 0 0;line-height:1.5}
.promo{margin-top:40px;margin-bottom:-24px;display:flex;gap:18px;align-items:center;padding:18px 20px;border-radius:12px;border:1px solid var(--line);
 background:radial-gradient(120% 120% at 0% 0%,rgba(255,255,255,.07),transparent 60%)}
.promo img{width:64px;height:64px;flex:none}
.promo .ph{font-size:18px;font-weight:700}
.promo .ps{color:var(--text-muted);margin:4px 0 10px}
.promo .pl{display:flex;flex-wrap:wrap;gap:8px}
.promo .pl a{font-weight:700;text-decoration:none;color:#0b0b0c;padding:8px 14px;border-radius:6px;
 background:linear-gradient(180deg,#f5f5f7,#c4c4ca);box-shadow:inset 0 1px 0 rgba(255,255,255,.7)}
.promo .pl a:hover{filter:brightness(1.08)}
@media print{.promo .pl a{color:#000;border:1px solid #000;background:none}}
.rc{display:grid;grid-template-columns:220px 1fr;gap:18px;margin:18px 0}
@media (max-width:760px){.rc{grid-template-columns:1fr}}
.rc-score{background:var(--surface-1);border:1px solid var(--line);border-radius:6px;padding:18px;text-align:center}
.rc-score .big{font-size:44px;font-weight:700;fill:var(--text-primary);font-variant-numeric:tabular-nums}
.rc-score .lbl{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--text-muted);margin-top:4px}
.rc-counts{display:flex;justify-content:center;gap:14px;margin-top:14px;font-size:13px;color:var(--text-secondary)}
.rc-counts b{display:block;font-size:20px;color:var(--text-primary);font-variant-numeric:tabular-nums}
.rc-groups{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.rc-g{background:var(--surface-1);border:1px solid var(--line);border-radius:6px;padding:14px 16px}
.rc-g h3{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--silver);margin:0 0 10px}
.mt{display:grid;grid-template-columns:1fr auto;gap:2px 10px;margin-bottom:10px;font-size:13px}
.mt .nm{color:var(--text-secondary)}
.mt .vl{font-weight:600;font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.mt svg{grid-column:1 / -1;display:block;width:100%;height:12px}
.mt .st{grid-column:1 / -1}
.z-ok{fill:var(--good);opacity:.35}.z-watch{fill:var(--warning);opacity:.35}.z-problem{fill:var(--critical);opacity:.35}
.z-perf{fill:var(--line)}.z-fill{fill:var(--silver)}
.mk{fill:var(--text-primary);stroke:var(--surface-1);stroke-width:2}
.ring-bg{fill:none;stroke:var(--line);stroke-width:12}.ring-fg{fill:none;stroke:var(--silver);stroke-width:12;stroke-linecap:round}
"""


def fmt_metric(m: dict, v: float) -> str:
    x = v * 100 if m["pct"] else v
    if m["unit"] == "count":
        return str(round(x))
    if m["unit"] == "Hz":
        return f"{round(x)} Hz"
    if m["unit"] == "bits":
        return "12+ bits" if x >= 12 else f"{x:.1f} bits"
    if m["unit"] == "ms":
        return f"{x:.1f} ms"
    return f"{x:.1f}%"


def _meter(m: dict, v: float) -> str:
    """One check as a bar: OK, Watch and Problem zones, and a marker at the value.
    Checks without limits (update rate) show a 0 to 100 performance bar."""
    from .analysis import grade_metric, perf_score
    W = 300.0
    tip = f"{m['label']}: {fmt_metric(m, v)}"
    m = dict(m, label=m["label"].split(": ", 1)[-1].capitalize() if m["label"].startswith(("Left stick", "Right stick")) else m["label"])
    if not (m["ok"] and m["watch"]):
        sc = perf_score(m["key"], v) if m["key"] == "update_rate_hz" else None
        if sc is None:
            return ""
        w = W * sc / 100
        return (f'<div class="mt"><span class="nm">{e(m["label"])}</span><span class="vl">{e(fmt_metric(m, v))}</span>'
                f'<svg viewBox="0 0 {W:.0f} 12" preserveAspectRatio="none" role="img" aria-label="{e(tip)}"><title>{e(tip)}, score {sc:.0f} of 100</title>'
                f'<rect class="z-perf" x="0" y="3" width="{W:.0f}" height="6" rx="3"/>'
                f'<rect class="z-fill" x="0" y="3" width="{w:.1f}" height="6" rx="3"/></svg>'
                f'<span class="st">{badge("info")}</span></div>')
    ok, watch = THRESHOLDS[m["ok"]], THRESHOLDS[m["watch"]]
    if m["better"] == "low":
        lo, hi = 0.0, max(watch * 1.6, ok * 2, v * 1.08, 1e-9)
        zones = [(lo, ok, OK), (ok, watch, WATCH), (watch, hi, PROBLEM)] if watch > ok else [(lo, ok, OK), (ok, hi, WATCH)]
    else:
        hi = THRESHOLDS["bits_cap"] if m["unit"] == "bits" else 1.0
        lo = min(watch - (ok - watch), v)
        zones = [(lo, watch, PROBLEM), (watch, ok, WATCH), (ok, hi, OK)]
    sx = lambda x: W * (min(max(x, lo), hi) - lo) / (hi - lo)
    rects = "".join(f'<rect class="z-{st}" x="{sx(a):.1f}" y="3" width="{max(sx(b) - sx(a), 0):.1f}" height="6"/>'
                    for a, b, st in zones)
    st = grade_metric(m, v)
    return (f'<div class="mt"><span class="nm">{e(m["label"])}</span><span class="vl">{e(fmt_metric(m, v))}</span>'
            f'<svg viewBox="0 0 {W:.0f} 12" preserveAspectRatio="none" role="img" aria-label="{e(tip)}"><title>{e(tip)}</title>{rects}'
            f'<rect class="mk" x="{max(sx(v) - 2, 0):.1f}" y="0" width="4" height="12" rx="2"/></svg>'
            f'<span class="st">{badge(st)}</span></div>')


def _ring(score: float | None) -> str:
    r, c = 70, 2 * math.pi * 70
    frac = 0 if score is None else score / 100
    txt = "-" if score is None else f"{score:.0f}"
    return (f'<svg viewBox="0 0 180 180" width="180" height="180" role="img" aria-label="Performance score {txt} of 100">'
            f'<circle class="ring-bg" cx="90" cy="90" r="{r}"/>'
            f'<circle class="ring-fg" cx="90" cy="90" r="{r}" stroke-dasharray="{c * frac:.1f} {c:.1f}" transform="rotate(-90 90 90)"/>'
            f'<text class="big" x="90" y="104" text-anchor="middle">{txt}</text></svg>')


RC_GROUPS = [
    ("Left stick", ["l_drift", "l_noise", "l_inner", "l_axial", "l_outer", "l_circle", "l_bits", "l_centre"]),
    ("Right stick", ["r_drift", "r_noise", "r_inner", "r_axial", "r_outer", "r_circle", "r_bits", "r_centre"]),
    ("Triggers", ["lt_start", "rt_start"]),
    ("Buttons and D-pad", ["doubles", "bounce", "dpad_flicker", "dpad_roll_skip"]),
    ("Connection", ["update_rate_hz", "update_spread_ms", "disconnects"]),
]


def report_card(r: Report) -> str:
    """The visual summary at the top of the report: one score and one bar per check."""
    from .analysis import METRICS, PERF_KEYS, metric_values, perf_score
    vals = metric_values(r)
    perf = [perf_score(k, vals[k]) for k in PERF_KEYS if vals.get(k) is not None]
    score = sum(perf) / len(perf) if len(perf) >= 3 else None
    counts = summary_counts(r.findings)
    by = {m["key"]: m for m in METRICS}
    out = ['<h2>Report card</h2><div class="rc"><div class="rc-score">', _ring(score),
           '<div class="lbl">Performance score</div>',
           '<div class="rc-counts">' + "".join(f'<span><b>{counts.get(st, 0)}</b>{badge(st)}</span>'
                                              for st in (PROBLEM, WATCH, OK)) + '</div>',
           '<div class="cap">The score is the mean of the performance checks (update rate, interval spread, '
           'resolution, outer reach, circularity, centre and trigger deadzones). 100 is the best possible '
           'value. 0 is the Watch limit.</div></div><div class="rc-groups">']
    for title, keys in RC_GROUPS:
        rows = "".join(_meter(by[k], vals[k]) for k in keys if vals.get(k) is not None)
        if title == "Triggers":
            for n, lab in (("lt", "Left trigger"), ("rt", "Right trigger")):
                t = r.triggers.get(n, {})
                if t.get("enough") and t.get("digital"):
                    rows += (f'<div class="mt"><span class="nm">{lab}</span><span class="vl">Digital</span>'
                             f'<span class="st">{badge("info")}</span></div>')
        out.append(f'<div class="rc-g"><h3>{e(title)}</h3>' + (rows or '<div class="sub">No result.</div>') + "</div>")
    out.append('</div></div><div class="cap">Coloured zones: OK, Watch and Problem limits (PadMaster defaults, '
               'not industry standards). The white mark is this session. Hover a bar to see the value.</div>')
    return "".join(out)


def e(s) -> str:
    return html.escape(str(s))


def badge(status: str) -> str:
    icon, label = STATUS[status]
    return f'<span class="badge s-{status}"><span class="dot">{icon}</span>{label}</span>'


def fmt_pct(x: float) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:.1f}%"


# ---------------------------------------------------------------- charts

def heatmap_svg(grid: list[list[int]], rest_points: list[tuple[float, float]]) -> str:
    g = len(grid)
    size = 260
    cell = size / g
    pad = 20
    mx = max((v for row in grid for v in row), default=0)
    parts = [f'<svg viewBox="0 0 {size + 2 * pad} {size + 2 * pad}" width="100%" style="max-width:320px" role="img" '
             f'aria-label="Stick position heatmap">']
    cx = cy = pad + size / 2
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{size / 2}" fill="none" stroke="var(--line)" stroke-width="1"/>')
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
                vx = (c + 0.5) / g * 2 - 1
                vy = -((r + 0.5) / g * 2 - 1)
                parts.append(f'<rect class="q{q}" x="{x:.2f}" y="{y:.2f}" width="{cell + 0.1:.2f}" height="{cell + 0.1:.2f}">'
                             f'<title>x {vx:+.2f}, y {vy:+.2f}: {v} samples</title></rect>')
    parts.append(f'<text x="{cx}" y="{pad - 6}" text-anchor="middle">up</text>')
    parts.append(f'<text x="{pad + size - 2}" y="{pad + size + 14}" text-anchor="end">right →</text>')
    parts.append("</svg>")
    legend = ('<div class="legend"><span class="lt">fewer</span>'
              + "".join(f'<span class="sw" style="background:var(--q{i})"></span>' for i in range(1, 8))
              + '<span class="lt">more samples</span><span class="ls">Log scale.</span></div>')
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

def _logo_uri() -> str:
    """Owner logo as a base64 data URI. Empty if the file is missing."""
    import base64
    import os
    import sys
    here = getattr(sys, "_MEIPASS", None)
    path = os.path.join(here, "padlab", "logo_128.png") if here else os.path.join(os.path.dirname(__file__), "logo_128.png")
    try:
        with open(path, "rb") as fh:
            data = base64.b64encode(fh.read()).decode("ascii")
    except OSError:
        return ""
    return f"data:image/png;base64,{data}"


def logo_data_uri() -> str:
    """Owner logo as a data: URI, or "" if the file is missing."""
    return _logo_uri()


def _logo_tag() -> str:
    uri = _logo_uri()
    return f'<img class="logo" alt="" width="56" height="56" src="{uri}">' if uri else ""


def _latency_box(entry: dict, collected: str) -> str:
    """Gamepadla.com hardware latency, in its own box. PadMaster did not measure these numbers."""
    def ms(v):
        return f"{v:.2f} ms" if isinstance(v, (int, float)) else "-"

    def hz(v):
        return f"{v:,.0f} Hz" if isinstance(v, (int, float)) else "-"

    rows = [x for x in entry.get("results", []) if x.get("primary")] or entry.get("results", [])
    body = "".join(
        f"<tr><td>{e(x.get('connection', ''))}</td><td>{e(x.get('mode', ''))}</td>"
        f"<td class='num'>{ms(x.get('button_ms'))}</td><td class='num'>{ms(x.get('stick_ms'))}</td>"
        f"<td class='num'>{hz(x.get('polling_hz'))}</td></tr>" for x in rows)
    url = e(entry.get("url", ""))
    return ("<h2>Hardware latency (data: Gamepadla.com)</h2><div class='card gpl'>"
            f"<div class='gpl-head'><strong>{e(entry.get('name', ''))}</strong> "
            f"<a href='{url}' target='_blank' rel='noopener'>See the full results on Gamepadla.com &#x2197;</a></div>"
            "<table><thead><tr><th>Connection</th><th>Mode</th><th>Button latency</th><th>Stick latency</th>"
            f"<th>Polling rate</th></tr></thead><tbody>{body}</tbody></table>"
            "<p class='gpl-small'>All numbers in this box were measured by <a href='https://gamepadla.com' "
            "target='_blank' rel='noopener'>Gamepadla.com</a> with hardware testers. Full credit to Gamepadla. "
            "PadMaster did not measure them, and they use a different method from PadMaster's own checks, so do not "
            f"compare them directly. Data collected {e(collected or 'on an unknown date')}. "
            "Gamepadla may have newer results. The match is by controller name, so check that it is your model.</p></div>")


def render(r: Report, log_name: str = "", name: str | None = None, latency: dict | None = None,
           latency_date: str = "") -> str:
    m = r.meta
    model = m.get("device", "Unknown controller")
    title = name or model
    s = r.session
    counts = summary_counts(r.findings)
    order = {PROBLEM: 0, WATCH: 1, OK: 2, INFO: 3, NODATA: 4}
    findings = sorted(r.findings, key=lambda f: order[f.status])

    out = [f'<!DOCTYPE html><html lang="en-GB"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<meta name="padlab-analysis" content="{ANALYSIS_VERSION}">'
           f'<meta name="padlab-name" content="{e(title)}">'
           f'<meta name="padlab-latency" content="{e((latency or {}).get("url", ""))}">'
           f'<title>PadMaster report: {e(title)}</title><style>{CSS}{SCROLLBAR_CSS}</style></head>'
           f'<body><div class="viz-root">']

    out.append(f'<div class="head">{_logo_tag()}<div><div class="kicker">PadMaster report</div>'
               f'<h1>{e(title)}</h1></div></div>')
    if title != model:
        out.append(f'<div class="sub">Controller model: {e(model)}</div>')
    out.append(f'<div class="sub">Connection: {e(m.get("connection") or "not recorded")}</div>')
    from .analysis import guid_info
    ids = guid_info(m.get("guid"))
    bits = []
    if ids.get("vid"):
        bits.append(f'{ids["bus_name"]} · VID {ids["vid"]} · PID {ids["pid"]}')
    if m.get("power"):
        bits.append(f'power {m["power"]}')
    if bits:
        out.append(f'<div class="sub">{e(" · ".join(bits))}</div>')
    out.append(f'<div class="sub">PadMaster report · {e(m.get("started", ""))} · {clock(s["duration_ms"])} logged · '
               f'{s["active_min"]} active min · {s["inputs"]:,} inputs · {e(m.get("mode", "?"))} mode</div>')
    if m.get("mode") == "joystick":
        out.append('<div class="warn">SDL has no mapping for this controller, so stick names are guesses and '
                   'triggers are not tested. Results for sticks may be wrong.</div>')
    if s["active_min"] < 10:
        out.append('<div class="warn">Short session. Some checks need more play time to give a result.</div>')

    out.append(report_card(r))

    out.append('<h2>Results</h2><div class="card"><table><thead><tr><th>Status</th><th>Check</th><th>Result</th>'
               '<th>What it means</th></tr></thead><tbody>')
    for f in findings:
        out.append(f'<tr><td>{badge(f.status)}</td><td>{e(f.title)}</td><td class="v">{e(f.value)}</td>'
                   f'<td class="d">{e(f.detail)}</td></tr>')
    out.append("</tbody></table></div>")

    # Sticks
    if latency:
        out.append(_latency_box(latency, latency_date))
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
                   f'{THRESHOLDS["outer_sectors"]} directions reached). Dashed ring = 100%.</div></div></div>')
        ho = st.get("handsoff")
        rows = [
            ("Smallest value out of centre", fmt_pct(st["inner_dz"])),
            ("Axial dead band X / Y", f'{fmt_pct(st["axial_x"])} / {fmt_pct(st["axial_y"])}'),
            ("Rest offset, hands-off check", fmt_pct(ho["max_mag"]) if ho else "not done"),
            ("Rest offset during play (typical / 90th pct)", f'{fmt_pct(st["rest_typical"])} / {fmt_pct(st["rest_worst"])}'),
            ("Rest moments found", str(st["rest_windows"])),
            ("Update interval while moving (logger view)", "-" if math.isnan(st["update_ms"]) else f'{st["update_ms"]:.1f} ms'),
            ("Minutes of stick movement", f'{st["motion_min"]:.1f}'),
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
                   f'{t["presses"]} pulls past 50%.</div></div>')
    out.append("</div>")

    # Guided test
    g = r.guided
    if g:
        from .guided import PHASES
        names = {k: t for _, k, t in PHASES}
        out.append("<h2>Guided test</h2><div class='card'>")
        out.append("<div class='sub'>Every controller gets the same steps, so these results are fair to compare. "
                   "The prompt results include your own accuracy: compare pads with the same player.</div><table>")
        for p in g["phases"]:
            out.append(f"<tr><td class='v'>{clock(p['t'])}</td><td>{e(names.get(p['key'], p['key']))}</td></tr>")
        out.append("</table>")
        rows = []
        for kind, lab in (("card", "D-pad directions"), ("diag", "D-pad diagonals"), ("btn", "Buttons")):
            hit, n = g[kind]
            if n:
                rows.append(f"<tr><td>{lab}</td><td class='v'>{hit} of {n}</td><td class='v'>{hit / n:.0%}</td></tr>")
        if rows:
            out.append("<h3 style='margin-top:14px'>Prompt game</h3><table><thead><tr><th>Prompt</th><th>Hit</th>"
                       "<th>Rate</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
            out.append(f"<div class='cap'>Accidental diagonals: {g['accidental_diag']}. Wrong button presses: "
                       f"{g['wrong']}. A prompt counts as hit if the exact input came before the next prompt "
                       f"(at most {THRESHOLDS['guided_window_ms'] / 1000:g} s later).</div>")
        if not g["complete"]:
            out.append("<div class='warn'>The guided test was stopped before the end. Some results can be missing.</div>")
        out.append("</div>")

    # D-pad
    d = r.dpad
    out.append("<h2>D-pad</h2><div class='card'>")
    if d["per_dir"]:
        out.append("<table><thead><tr><th>Diagonal</th><th>Times entered</th></tr></thead><tbody>")
        for k in ("up-left", "up-right", "down-left", "down-right"):
            out.append(f"<tr><td>{k}</td><td class='v'>{d['per_dir'].get(k, 0)}</td></tr>")
        out.append("</tbody></table>")
    else:
        out.append('<div class="sub">No diagonals in this session.</div>')
    out.append(f'<div class="cap">{d["card_presses"]} single-direction presses · {d["diag_entries"]} diagonals · '
               f'{d["flickers"]} flickers · {d["blips"]} blips.</div></div>')

    # Event list
    events = []
    for x in (r.guided or {}).get("misses", []):
        events.append((x["t"], "Guided miss", x["prompt"].replace("_", " ")))
    for o in r.connection["outages"]:
        events.append((o["t"], "Disconnect", f'back after {o["ms"] / 1000:.1f} s' if o["ms"] else "did not come back"))
    for x in r.buttons["double_times"]:
        events.append((x["t"], "Double input", f'{x["button"]}: {x["gap_ms"]:.1f} ms gap'))
    for x in r.buttons.get("bounce_times", []):
        events.append((x["t"], "Contact bounce", f'{x["button"]}: off for {x["gap_ms"]:.1f} ms after {x["held_ms"]:.0f} ms hold'))
    for x in d["flicker_times"]:
        events.append((x["t"], "D-pad flicker", f'{x["dir"]}: dropped for {x["ms"]:.0f} ms'))
    for x in d["blip_times"]:
        events.append((x["t"], "D-pad blip", f'{x["dir"]} for {x["ms"]:.0f} ms'))
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
               "<li>PadMaster only reads the controller while you play. It does not know what you meant to press, so each "
               "check looks for patterns that a hand does not make, or uses moments when you did not touch a stick.</li>"
               "<li>OK / Watch / Problem limits are PadMaster defaults (judgement calls), not industry standards. "
               "You can change them in <code>THRESHOLDS</code> in <code>analysis.py</code>.</li>"
               "<li>Timing is limited by the logger loop (about 1 ms) and by Windows. PadMaster can't measure true input "
               "latency. That needs hardware.</li>"
               "<li>Steam Input, DS4Windows and similar tools can change what PadMaster sees. Turn them off for a clean test.</li>"
               "<li>Compare controllers only with the same player, game and connection.</li></ul></div>")

    from .branding import CHANNELS
    out.append('<div class="promo">' + _logo_tag() + '<div class="pt"><div class="ph">Made by a controller reviewer</div>'
               '<div class="ps">PadMaster is free. See the full controller reviews and tests on video:</div>'
               '<div class="pl">' + "".join(f'<a href="{e(u)}" target="_blank" rel="noopener">&#9654; {e(n)}</a>' for n, u in CHANNELS)
               + "</div></div></div>")
    out.append(f'<div class="foot">PadMaster {e(__version__)} · log {e(log_name)} · logger {e(m.get("padlab", "?"))} · '
               f'SDL {e(m.get("sdl", "?"))} · generated {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>')
    out.append("</div></body></html>")
    return "".join(out)
