"""Turn a PadMaster log into measurements and findings.

Pure Python (no numpy), so the Windows build stays small.

Every check here is passive: the logger does not know what the player WANTED to
press. So each check looks for patterns that a human hand does not make
(for example a release and a new press 5 ms apart), or uses moments when the
player is not touching a stick. All thresholds are in THRESHOLDS so you can
tune them. They are judgement calls, not industry standards.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from typing import Iterable

from .logfile import (
    AXIS_MAX,
    DPAD_BUTTONS,
    FACE_AND_SHOULDER,
    PADDLES,
    Log,
)

THRESHOLDS = {
    # Sticks
    "rest_radius": 0.25,          # a stick under this magnitude may be "at rest"
    "rest_tolerance": 0.06,       # values must stay this close for a rest window
    "rest_min_ms": 1500,          # minimum rest window
    "rest_trim_ms": 150,          # ignore this much at each edge of a rest window (start or end of a move)
    "handsoff_window_ms": 15000,  # rest windows that start in the first 15 s = hands-off check
    "drift_ok": 0.05, "drift_watch": 0.10,
    "inner_dz_ok": 0.03, "inner_dz_watch": 0.10,
    "axial_other_axis": 0.25,     # other axis must be past this to test the axial band
    "axial_ok": 0.03, "axial_watch": 0.08,
    "outer_min_mag": 0.5,
    "outer_sectors": 36,
    "outer_min_covered": 12,
    "outer_ok": 0.97, "outer_watch": 0.90,
    "min_stick_samples": 200,
    # Stutter
    "stream_mag": 0.2,
    "stutter_min_gap_ms": 40,
    "stutter_gap_x_median": 6,
    "stutter_jump": 0.08,         # minimum jump across the gap
    "stutter_speed_match": 0.5,   # jump must be at least this share of (speed before gap x gap)
    "stutter_ok_per_min": 0.5, "stutter_watch_per_min": 3,
    # Update rate (info only, never latency)
    "late_x_median": 2,           # an interval longer than this x median is a "late" report
    "interval_hist_ms": 30,       # histogram bins: 1 ms each up to this value, plus one overflow bin
    # Noise at rest: peak-to-peak spread of the values in the hands-off window
    "noise_ok": 0.02, "noise_watch": 0.05,
    # Circularity: average distance of the full-tilt edge from a perfect circle
    "circ_ok": 0.05, "circ_watch": 0.10,
    # Return to centre: rest position after the stick was pushed past centre_from
    "centre_from": 0.5,
    "centre_lookback_ms": 1000,
    "centre_min_returns": 5,
    "centre_ok": 0.03, "centre_watch": 0.06,
    # Resolution (info only)
    "res_min_unique": 100,
    "res_step_share": 0.05,       # a step size must occur in this share of gaps to count
    # Triggers
    "trigger_start_ok": 0.03, "trigger_start_watch": 0.10,
    "trigger_end_ok": 0.98, "trigger_end_watch": 0.90,
    "min_trigger_events": 20,
    # Buttons
    "double_gap_ms": 20,          # release -> press faster than this is not a human
    "double_watch": 1, "double_problem": 3,
    # D-pad
    "flicker_ms": 35,
    "dpad_split_max_ms": 100,
    "dpad_min_diagonals": 10,
    "flicker_ok_pct": 2, "flicker_watch_pct": 10,
    "blip_ok_pct": 2, "blip_watch_pct": 10,
    "dpad_min_cardinals": 20,
    # Rolls: a quick move from one direction to the next (right -> down). A working rocker passes
    # through the diagonal on almost every roll. Only a direct switch (C1 -> C2, no diagonal) is graded.
    # A short gap of nothing is shown as info only: a good pad also shows it when the thumb lifts
    # (owner's Xbox pad: 3% direct switches, 15% gaps; faulty pad: 19% direct, 27% gaps).
    "roll_diag_max_ms": 100,      # a diagonal longer than this is a held diagonal, not a roll
    "roll_gap_max_ms": 40,        # a gap of nothing shorter than this, between neighbours, is a gap roll
    "roll_min": 20,
    "roll_skip_ok_pct": 5, "roll_skip_watch_pct": 15,
    # Chords
    "chord_window_ms": 50,
    "frame_ms": 1000 / 60,
}

OK, WATCH, PROBLEM, NODATA, INFO = "ok", "watch", "problem", "nodata", "info"


@dataclass
class Finding:
    key: str
    title: str
    status: str
    value: str
    detail: str = ""


@dataclass
class Report:
    meta: dict
    session: dict
    findings: list[Finding] = field(default_factory=list)
    sticks: dict = field(default_factory=dict)
    triggers: dict = field(default_factory=dict)
    buttons: dict = field(default_factory=dict)
    dpad: dict = field(default_factory=dict)
    chords: dict = field(default_factory=dict)
    connection: dict = field(default_factory=dict)


# ---------------------------------------------------------------- helpers

def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def clock(t_ms: float) -> str:
    s = int(t_ms // 1000)
    return f"{s // 3600:d}:{(s // 60) % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:d}:{s % 60:02d}"


def grade(value: float, ok: float, watch: float, higher_is_better: bool = False) -> str:
    if math.isnan(value):
        return NODATA
    if higher_is_better:
        return OK if value >= ok else WATCH if value >= watch else PROBLEM
    return OK if value < ok else WATCH if value < watch else PROBLEM


def norm(v: int) -> float:
    return max(-1.0, min(1.0, v / AXIS_MAX))


# ---------------------------------------------------------------- sticks

def stick_samples(log: Log, xn: str, yn: str) -> list[tuple[float, int, int]]:
    """(t, raw_x, raw_y) after each change. Events at the same time merge into one sample."""
    x = y = 0
    seen = False
    out: list[tuple[float, int, int]] = []
    for e in log.events:
        if e.kind != "a" or e.name not in (xn, yn):
            continue
        if e.name == xn:
            x = e.value
        else:
            y = e.value
        seen = True
        if out and out[-1][0] == e.t:
            out[-1] = (e.t, x, y)
        else:
            out.append((e.t, x, y))
    return out if seen else []


def window_stats(samples, i: int, j: int, lo: float, hi: float, end_ms: float) -> dict | None:
    """Mean, max and sample range of samples[i:j], counting only the time between lo and hi."""
    n = len(samples)
    sx = sy = wsum = 0.0
    max_mag = 0.0
    k0 = k1 = None
    for k in range(i, j):
        tk = samples[k][0]
        t_next = samples[k + 1][0] if k + 1 < n else end_ms
        w = min(t_next, hi) - max(tk, lo)
        if w <= 0:
            continue
        nxk, nyk = norm(samples[k][1]), norm(samples[k][2])
        sx += nxk * w
        sy += nyk * w
        wsum += w
        max_mag = max(max_mag, math.hypot(nxk, nyk))
        k0 = k if k0 is None else k0
        k1 = k + 1
    if wsum <= 0:
        return None
    mx, my = sx / wsum, sy / wsum
    return {"x": mx, "y": -my, "mean_mag": math.hypot(mx, my), "max_mag": max_mag, "i0": k0, "i1": k1}


def rest_windows(samples, end_ms: float) -> list[dict]:
    th = THRESHOLDS
    windows = []
    n = len(samples)
    i = 0
    while i < n:
        t0, x0, y0 = samples[i]
        nx0, ny0 = norm(x0), norm(y0)
        if math.hypot(nx0, ny0) >= th["rest_radius"]:
            i += 1
            continue
        j = i
        while j < n:
            _, xj, yj = samples[j]
            nxj, nyj = norm(xj), norm(yj)
            if (abs(nxj - nx0) > th["rest_tolerance"] or abs(nyj - ny0) > th["rest_tolerance"]
                    or math.hypot(nxj, nyj) >= th["rest_radius"]):
                break
            j += 1
        t_end = samples[j][0] if j < n else end_ms
        dur = t_end - t0
        if dur >= th["rest_min_ms"] and dur > 0:
            # Use only the middle of the window. The first and last samples can be the end of a
            # return or the start of the next push (the thumb touches the stick first).
            lo, hi = t0 + th["rest_trim_ms"], t_end - th["rest_trim_ms"]
            ws = window_stats(samples, i, j, lo, hi, end_ms)
            if ws:
                windows.append({"t": t0, "dur": dur, "t_end": t_end, "i_start": i, "j": j, **ws})
        i = max(j, i + 1)
    return windows


def analyse_stick(log: Log, side: str) -> dict:
    th = THRESHOLDS
    xn, yn = f"{side}x", f"{side}y"
    s = stick_samples(log, xn, yn)
    res: dict = {"samples": len(s)}
    if len(s) < th["min_stick_samples"]:
        res["enough"] = False
        return res
    res["enough"] = True
    end = log.duration_ms

    # Rest / drift
    wins = rest_windows(s, end)
    handsoff = [w for w in wins if w["t"] < th["handsoff_window_ms"]]
    if handsoff:
        # Use only the start of the session for the hands-off check. A long rest window can end
        # with the player picking up the pad and touching the stick.
        w0 = handsoff[0]
        hi = min(w0["t_end"] - th["rest_trim_ms"], th["handsoff_window_ms"])
        ws = window_stats(s, w0["i_start"], w0["j"], w0["t"] + th["rest_trim_ms"], hi, end)
        handsoff = [{**w0, **ws}] if ws else []
    res["rest_windows"] = len(wins)
    res["handsoff"] = handsoff[0] if handsoff else None
    res["rest_typical"] = percentile([w["mean_mag"] for w in wins], 0.5) if wins else float("nan")
    res["rest_worst"] = percentile([w["max_mag"] for w in wins], 0.9) if wins else float("nan")
    res["rest_points"] = [(w["x"], w["y"]) for w in wins][:400]
    res["rest_all_zero"] = bool(wins) and all(w["max_mag"] == 0 for w in wins)
    if handsoff:
        basis = handsoff[0]["max_mag"]
    else:
        basis = res["rest_worst"]
    res["safe_deadzone"] = float("nan") if math.isnan(basis) else math.ceil((basis + 0.02) * 100) / 100

    # Inner (radial) deadzone: smallest non-zero position the pad ever reports.
    nz = [math.hypot(norm(x), norm(y)) for _, x, y in s if x or y]
    res["inner_dz"] = min(nz) if nz else float("nan")

    # Axial band: smallest non-zero value on one axis while the other axis is pushed.
    def band(a_idx: int) -> tuple[float, float, int]:
        b_idx = 2 if a_idx == 1 else 1
        vals = [abs(norm(smp[a_idx])) for smp in s if abs(norm(smp[b_idx])) > th["axial_other_axis"]]
        if len(vals) < 50:
            return float("nan"), float("nan"), len(vals)
        nonzero = [v for v in vals if v > 0]
        zero_share = 1 - len(nonzero) / len(vals)
        return (min(nonzero) if nonzero else 1.0), zero_share, len(vals)

    bx, zx, cx = band(1)
    by, zy, cy = band(2)
    res["axial_x"], res["axial_zero_share_x"] = bx, zx
    res["axial_y"], res["axial_zero_share_y"] = by, zy
    candidates = [b for b, z in ((bx, zx), (by, zy)) if not math.isnan(b) and z > 0.05]
    res["axial_band"] = max(candidates) if candidates else (0.0 if not (math.isnan(bx) and math.isnan(by)) else float("nan"))

    # Outer reach by direction.
    n_sec = th["outer_sectors"]
    reach = [0.0] * n_sec
    hit = [False] * n_sec
    for _, x, y in s:
        nx, ny = norm(x), -norm(y)
        m = math.hypot(nx, ny)
        if m < th["outer_min_mag"]:
            continue
        ang = (math.degrees(math.atan2(ny, nx)) + 360) % 360
        k = int(ang // (360 / n_sec)) % n_sec
        hit[k] = True
        reach[k] = max(reach[k], m)
    covered = [reach[k] for k in range(n_sec) if hit[k]]
    res["reach"] = [reach[k] if hit[k] else None for k in range(n_sec)]
    res["reach_covered"] = len(covered)
    if len(covered) >= th["outer_min_covered"]:
        capped = [min(1.0, r) for r in covered]
        res["outer_avg"] = sum(capped) / len(capped)
        res["outer_min"] = min(capped)
        res["outer_full_share"] = sum(1 for r in covered if r >= 0.98) / len(covered)
    else:
        res["outer_avg"] = res["outer_min"] = res["outer_full_share"] = float("nan")

    # Heatmap (sample counts on a 41 x 41 grid, up = up).
    g = 41
    grid = [[0] * g for _ in range(g)]
    for _, x, y in s:
        gx = min(g - 1, int((norm(x) + 1) / 2 * g))
        gy = min(g - 1, int((norm(y) + 1) / 2 * g))  # SDL y: down is +, so row 0 = up
        grid[gy][gx] += 1
    res["heatmap"] = grid

    # Stutter: long gaps during continuous movement, with a big jump across the gap.
    stream = []
    for i in range(1, len(s)):
        t1, x1, y1 = s[i - 1]
        t2, x2, y2 = s[i]
        m1 = math.hypot(norm(x1), norm(y1))
        m2 = math.hypot(norm(x2), norm(y2))
        if m1 > th["stream_mag"] and m2 > th["stream_mag"]:
            stream.append((i, t2 - t1, math.hypot(norm(x2) - norm(x1), norm(y2) - norm(y1))))
    dts = [d for _, d, _ in stream if d > 0]
    med = percentile(dts, 0.5) if dts else float("nan")
    res["update_ms"] = med
    stutters = []
    motion_ms = 0.0
    if dts:
        gap_limit = max(th["stutter_min_gap_ms"], th["stutter_gap_x_median"] * med)
        for idx, (i, dt, jump) in enumerate(stream):
            if dt <= 3 * med:
                motion_ms += dt
            if dt > gap_limit and jump > th["stutter_jump"]:
                prev_ok = idx > 0 and stream[idx - 1][0] == i - 1 and stream[idx - 1][1] <= 3 * med
                next_ok = idx + 1 < len(stream) and stream[idx + 1][0] == i + 1 and stream[idx + 1][1] <= 3 * med
                speed_ok = False
                if prev_ok:
                    _, pdt, pjump = stream[idx - 1]
                    expected = (pjump / pdt) * dt if pdt > 0 else 0.0
                    speed_ok = jump >= th["stutter_speed_match"] * expected
                if prev_ok and next_ok and speed_ok:
                    stutters.append({"t": s[i][0], "gap_ms": dt, "jump": jump})
    res["stutters"] = stutters
    res["motion_min"] = motion_ms / 60000
    res["intervals"] = interval_stats(dts)

    # Noise at rest: spread of the values inside the hands-off window only. A still moment during
    # play can be a thumb that holds the stick, and a thumb adds its own noise.
    basis_win = handsoff[0] if handsoff else None
    if basis_win and basis_win["i1"] - basis_win["i0"] >= 1:
        xs = [norm(x) for _, x, _ in s[basis_win["i0"]:basis_win["i1"]]]
        ys = [norm(y) for _, _, y in s[basis_win["i0"]:basis_win["i1"]]]
        res["noise_p2p"] = max(max(xs) - min(xs), max(ys) - min(ys))
        res["noise_std"] = max(_std(xs), _std(ys))
        res["noise_source"] = "hands-off check"
    else:
        res["noise_p2p"] = res["noise_std"] = float("nan")
        res["noise_source"] = None

    # Circularity: average distance of the full-tilt edge from a perfect circle (over- and under-reach).
    if len(covered) >= th["outer_min_covered"]:
        res["circ_err"] = sum(abs(r - 1.0) for r in covered) / len(covered)
    else:
        res["circ_err"] = float("nan")

    # Return to centre: rest position after each push past centre_from.
    times = [t for t, _, _ in s]
    returns = []
    for w in wins:
        k = bisect.bisect_left(times, w["t"] - th["centre_lookback_ms"])
        pushed = any(math.hypot(norm(s[q][1]), norm(s[q][2])) > th["centre_from"] for q in range(k, w["i0"]))
        if pushed:
            returns.append((w["x"], w["y"]))
    res["centre_returns"] = len(returns)
    res["centre_points"] = returns[:400]
    if len(returns) >= th["centre_min_returns"]:
        mags = [math.hypot(x, y) for x, y in returns]
        res["centre_err"] = percentile(mags, 0.9)
        res["centre_spread"] = max(math.hypot(a[0] - b[0], a[1] - b[1]) for a in returns for b in returns)
    else:
        res["centre_err"] = res["centre_spread"] = float("nan")

    # Close-up heatmap of the centre area (+/- 20%), to show the deadzone shape.
    g, zoom = 41, 0.2
    cgrid = [[0] * g for _ in range(g)]
    for _, x, y in s:
        nx, ny = norm(x), norm(y)
        if abs(nx) < zoom and abs(ny) < zoom:
            cgrid[min(g - 1, int((ny + zoom) / (2 * zoom) * g))][min(g - 1, int((nx + zoom) / (2 * zoom) * g))] += 1
    res["heatmap_centre"] = cgrid
    res["heatmap_centre_zoom"] = zoom

    res["resolution"] = {xn: axis_resolution(log, xn, 65535), yn: axis_resolution(log, yn, 65535)}
    return res


def _std(v: list[float]) -> float:
    if not v:
        return float("nan")
    if len(v) == 1:
        return 0.0
    m = sum(v) / len(v)
    return math.sqrt(sum((a - m) ** 2 for a in v) / (len(v) - 1))


def interval_stats(dts: list[float]) -> dict:
    """Time between reports while a stick moves. This is the update rate seen by the logger, not latency."""
    th = THRESHOLDS
    if len(dts) < 20:
        return {"n": len(dts)}
    med = percentile(dts, 0.5)
    core = [d for d in dts if d <= 3 * med]
    nb = th["interval_hist_ms"]
    hist = [0] * (nb + 1)
    for d in dts:
        hist[min(nb, int(d))] += 1
    mad = percentile([abs(d - med) for d in core], 0.5)
    return {
        "n": len(dts),
        "median": med,
        "mean": sum(core) / len(core),
        "p01": percentile(dts, 0.01),
        "p99": percentile(dts, 0.99),
        "std": _std(core),
        "mad": mad,
        "rate_hz": 1000 / med if med > 0 else float("nan"),
        "late_share": sum(1 for d in dts if d > th["late_x_median"] * med) / len(dts),
        "hist": hist,
    }


def axis_resolution(log: Log, name: str, span: int) -> dict:
    """Number of different values, the typical smallest step, and an estimated bit depth."""
    th = THRESHOLDS
    vals = sorted({e.value for e in log.events if e.kind == "a" and e.name == name})
    res: dict = {"unique": len(vals)}
    if len(vals) < th["res_min_unique"]:
        res["step"] = res["bits"] = float("nan")
        return res
    gaps = [b - a for a, b in zip(vals, vals[1:]) if b > a]
    counts: dict[int, int] = {}
    for gp in gaps:
        counts[gp] = counts.get(gp, 0) + 1
    common = [gp for gp, c in counts.items() if c >= th["res_step_share"] * len(gaps)]
    step = min(common) if common else min(gaps)
    res["step"] = step
    res["min_step"] = min(gaps)
    res["bits"] = min(16.0, math.log2(span / step)) if step > 0 else float("nan")
    return res


def guid_info(guid: str | None) -> dict:
    """Bus, vendor ID and product ID from an SDL GUID (inference: SDL 2 GUID layout)."""
    if not guid or len(guid) != 32:
        return {}
    try:
        b = bytes.fromhex(guid)
    except ValueError:
        return {}
    bus = int.from_bytes(b[0:2], "little")
    if b[6:8] != b"\0\0" or b[10:12] != b"\0\0":
        return {"bus": bus}
    return {
        "bus": bus,
        "bus_name": {0x03: "USB", 0x05: "Bluetooth"}.get(bus, f"0x{bus:04x}"),
        "vid": f"{int.from_bytes(b[4:6], 'little'):04X}",
        "pid": f"{int.from_bytes(b[8:10], 'little'):04X}",
    }


# ---------------------------------------------------------------- triggers

def analyse_trigger(log: Log, name: str) -> dict:
    vals = [e.value for e in log.events if e.kind == "a" and e.name == name]
    res: dict = {"events": len(vals)}
    if len(vals) < THRESHOLDS["min_trigger_events"]:
        res["enough"] = False
        return res
    res["enough"] = True
    nonzero = [v for v in vals if v > 0]
    res["start"] = (min(nonzero) / AXIS_MAX) if nonzero else float("nan")
    res["end"] = max(vals) / AXIS_MAX
    res["unique"] = len(set(vals))
    res["digital"] = res["unique"] <= 3
    presses = 0
    above = False
    for v in vals:
        if not above and v > AXIS_MAX * 0.5:
            presses += 1
            above = True
        elif above and v < AXIS_MAX * 0.3:
            above = False
    res["presses"] = presses
    # Distribution for a small histogram (20 bins).
    bins = [0] * 20
    for v in vals:
        bins[min(19, int(v / AXIS_MAX * 20))] += 1
    res["hist"] = bins
    res["resolution"] = axis_resolution(log, name, 32767)
    return res


# ---------------------------------------------------------------- buttons

def presses(log: Log) -> dict[str, list[tuple[float, float | None]]]:
    """(down_t, up_t) for each press, by button."""
    down: dict[str, float] = {}
    out: dict[str, list[tuple[float, float | None]]] = {}
    for e in log.events:
        if e.kind != "b":
            continue
        lst = out.setdefault(e.name, [])
        if e.value:
            if e.name in down:  # down without up: close the old one
                lst.append((down[e.name], None))
            down[e.name] = e.t
        elif e.name in down:
            lst.append((down.pop(e.name), e.t))
    for name, t in down.items():
        out.setdefault(name, []).append((t, None))
    for lst in out.values():
        lst.sort()
    return out


def analyse_buttons(log: Log) -> dict:
    gap = THRESHOLDS["double_gap_ms"]
    pr = presses(log)
    res: dict = {"counts": {}, "doubles": {}, "double_times": []}
    for name, lst in sorted(pr.items()):
        res["counts"][name] = len(lst)
        n = 0
        for (d1, u1), (d2, _) in zip(lst, lst[1:]):
            if u1 is not None and 0 <= d2 - u1 < gap:
                n += 1
                res["double_times"].append({"t": d2, "button": name, "gap_ms": d2 - u1, "held_ms": u1 - d1})
        if n:
            res["doubles"][name] = n
    res["double_total"] = sum(res["doubles"].values())
    res["double_times"].sort(key=lambda d: d["t"])
    res["paddles"] = {p: res["counts"].get(p, 0) for p in PADDLES if res["counts"].get(p, 0)}
    return res


# ---------------------------------------------------------------- D-pad

DIRS = {
    (): "neutral",
    ("up",): "up", ("down",): "down", ("left",): "left", ("right",): "right",
    ("left", "up"): "up-left", ("right", "up"): "up-right",
    ("down", "left"): "down-left", ("down", "right"): "down-right",
}


def dpad_timeline(log: Log) -> list[tuple[float, frozenset]]:
    held: set[str] = set()
    tl: list[tuple[float, frozenset]] = []
    for e in log.events:
        if e.kind != "b" or e.name not in DPAD_BUTTONS:
            continue
        if e.value:
            held.add(e.name)
        else:
            held.discard(e.name)
        st = frozenset(held)
        if tl and tl[-1][0] == e.t:
            tl[-1] = (e.t, st)
        elif not tl or tl[-1][1] != st:
            tl.append((e.t, st))
    # Remove repeats created by same-time merges.
    out: list[tuple[float, frozenset]] = []
    for t, st in tl:
        if not out or out[-1][1] != st:
            out.append((t, st))
    return out


def _is_diag(st: frozenset) -> bool:
    return len(st) == 2 and not ({"up", "down"} <= st or {"left", "right"} <= st)


def _is_card(st: frozenset) -> bool:
    return len(st) == 1


def analyse_dpad(log: Log) -> dict:
    th = THRESHOLDS
    tl = dpad_timeline(log)
    end = log.duration_ms
    res: dict = {"changes": len(tl)}
    diag_entries = card_from_neutral = flickers = blips = invalid = 0
    splits: list[float] = []
    flicker_times: list[dict] = []
    blip_times: list[dict] = []
    per_dir: dict[str, int] = {}

    def dur(i: int) -> float:
        return (tl[i + 1][0] if i + 1 < len(tl) else end) - tl[i][0]

    for i, (t, st) in enumerate(tl):
        prev = tl[i - 1][1] if i > 0 else frozenset()
        if ({"up", "down"} <= st) or ({"left", "right"} <= st):
            invalid += 1
        if _is_card(st) and not prev:
            # A single direction that turns into a diagonal within the split window is a
            # diagonal attempt, not a single-direction press.
            nxt = tl[i + 1][1] if i + 1 < len(tl) else frozenset()
            if not (_is_diag(nxt) and st < nxt and dur(i) < th["dpad_split_max_ms"]):
                card_from_neutral += 1
        is_blip = (i >= 1 and i + 1 < len(tl) and _is_diag(st) and _is_card(prev)
                   and tl[i + 1][1] == prev and prev < st and dur(i) < th["flicker_ms"])
        if _is_diag(st) and not _is_diag(prev):
            # Skip re-entries right after a flicker, and blips (both counted below).
            is_reentry = (i >= 2 and tl[i - 2][1] == st and _is_card(prev)
                          and prev < st and dur(i - 1) < th["flicker_ms"])
            if not is_reentry and not is_blip:
                diag_entries += 1
                name = DIRS.get(tuple(sorted(st)), "?")
                per_dir[name] = per_dir.get(name, 0) + 1
                if not prev:
                    splits.append(0.0)
                elif _is_card(prev) and prev < st and i >= 2 and not tl[i - 2][1]:
                    sp = t - tl[i - 1][0]
                    if sp <= th["dpad_split_max_ms"]:
                        splits.append(sp)
        # Flicker: D -> C -> D, C short, C inside D.
        if (i >= 1 and i + 1 < len(tl) and _is_card(st) and _is_diag(prev)
                and tl[i + 1][1] == prev and st < prev and dur(i) < th["flicker_ms"]):
            flickers += 1
            flicker_times.append({"t": t, "dir": DIRS.get(tuple(sorted(prev)), "?"), "ms": dur(i)})
        # Blip: C -> D -> C, D short, C inside D.
        if is_blip:
            blips += 1
            blip_times.append({"t": t, "dir": DIRS.get(tuple(sorted(st)), "?"), "ms": dur(i)})

    # Rolls between neighbouring directions.
    rolls_through: dict[str, int] = {}
    rolls_skipped: dict[str, int] = {}
    rolls_gap: dict[str, int] = {}
    skip_times: list[dict] = []
    for i in range(1, len(tl)):
        a, b = tl[i - 1][1], tl[i][1]
        # C1 -> C2 directly
        if _is_card(a) and _is_card(b) and _is_diag(a | b):
            name = DIRS[tuple(sorted(a | b))]
            rolls_skipped[name] = rolls_skipped.get(name, 0) + 1
            skip_times.append({"t": tl[i][0], "dir": name, "how": "direct switch", "ms": 0.0})
        if i < 2:
            continue
        c1 = tl[i - 2][1]
        if not (_is_card(c1) and _is_card(b) and c1 != b and _is_diag(c1 | b)):
            continue
        name = DIRS[tuple(sorted(c1 | b))]
        mid_ms = tl[i][0] - tl[i - 1][0]
        # C1 -> nothing (short) -> C2
        if not a and mid_ms < th["roll_gap_max_ms"]:
            rolls_gap[name] = rolls_gap.get(name, 0) + 1
        # C1 -> D -> C2 (quick)
        elif a == c1 | b and mid_ms <= th["roll_diag_max_ms"]:
            rolls_through[name] = rolls_through.get(name, 0) + 1
    n_through = sum(rolls_through.values())
    n_skip = sum(rolls_skipped.values())
    n_gap = sum(rolls_gap.values())
    n_rolls = n_through + n_skip + n_gap
    res.update(
        rolls=n_rolls,
        rolls_through=rolls_through,
        rolls_skipped=rolls_skipped,
        rolls_gap=rolls_gap,
        roll_gap_pct=(n_gap / n_rolls * 100) if n_rolls >= th["roll_min"] else float("nan"),
        roll_skip_times=skip_times,
        roll_skip_pct=(n_skip / n_rolls * 100) if n_rolls >= th["roll_min"] else float("nan"),
    )

    res.update(
        diag_entries=diag_entries,
        card_presses=card_from_neutral,
        flickers=flickers,
        blips=blips,
        invalid=invalid,
        splits=splits,
        split_median=percentile(splits, 0.5) if splits else float("nan"),
        split_p90=percentile(splits, 0.9) if splits else float("nan"),
        flicker_times=flicker_times,
        blip_times=blip_times,
        per_dir=per_dir,
        flicker_pct=(flickers / diag_entries * 100) if diag_entries >= th["dpad_min_diagonals"] else float("nan"),
        blip_pct=(blips / card_from_neutral * 100) if card_from_neutral >= th["dpad_min_cardinals"] else float("nan"),
    )
    return res


# ---------------------------------------------------------------- chords

def analyse_chords(log: Log) -> dict:
    win = THRESHOLDS["chord_window_ms"]
    pr = presses(log)
    downs = sorted(
        (d, u, name) for name, lst in pr.items() if name in FACE_AND_SHOULDER for d, u in lst
    )
    used = set()
    splits = []
    for i, (d1, u1, n1) in enumerate(downs):
        if i in used:
            continue
        for j in range(i + 1, len(downs)):
            d2, _, n2 = downs[j]
            if d2 - d1 > win:
                break
            if j in used or n2 == n1:
                continue
            if u1 is not None and u1 < d2:
                continue  # first button was already released: not a chord
            splits.append(d2 - d1)
            used.update((i, j))
            break
    return {
        "count": len(splits),
        "splits": splits,
        "median": percentile(splits, 0.5) if splits else float("nan"),
        "p90": percentile(splits, 0.9) if splits else float("nan"),
        "over_frame": (sum(1 for s in splits if s > THRESHOLDS["frame_ms"]) / len(splits)) if splits else float("nan"),
    }


# ---------------------------------------------------------------- connection

def analyse_connection(log: Log) -> dict:
    lost = [e.t for e in log.events if e.kind == "c" and e.value == 0]
    back = [e.t for e in log.events if e.kind == "c" and e.value == 1]
    outages = []
    for t in lost:
        later = [b for b in back if b > t]
        outages.append({"t": t, "ms": (later[0] - t) if later else None})
    return {"disconnects": len(lost), "outages": outages}


# ---------------------------------------------------------------- session

def session_info(log: Log) -> dict:
    inputs = sum(1 for e in log.events if e.kind in ("a", "b"))
    minutes = {int(e.t // 60000) for e in log.events if e.kind in ("a", "b")}
    return {
        "duration_ms": log.duration_ms,
        "inputs": inputs,
        "active_min": len(minutes),
        "ids": guid_info(log.meta.get("guid")),
    }


# ---------------------------------------------------------------- findings

def _f(findings: list[Finding], *a, **k) -> None:
    findings.append(Finding(*a, **k))


def build_findings(r: Report) -> None:
    th = THRESHOLDS
    F = r.findings

    c = r.connection
    _f(F, "disconnects", "Disconnects", OK if c["disconnects"] == 0 else PROBLEM,
       str(c["disconnects"]),
       "The controller was lost and came back." if c["disconnects"] else "No disconnects in this session.")

    for side, label in (("l", "Left stick"), ("r", "Right stick")):
        s = r.sticks.get(side, {})
        if not s.get("enough"):
            _f(F, f"{side}_stick", label, NODATA, "-", f"Not enough stick data ({s.get('samples', 0)} samples).")
            continue
        # Drift
        ho = s.get("handsoff")
        if s.get("rest_all_zero"):
            _f(F, f"{side}_drift", f"{label}: drift at rest", OK, "0.0%",
               "At rest the pad reports exactly 0. If it has a deadzone, the deadzone hides any drift.")
        else:
            basis = ho["max_mag"] if ho else s["rest_worst"]
            src = "hands-off check at the start" if ho else "rest moments during play (90th percentile)"
            _f(F, f"{side}_drift", f"{label}: drift at rest", grade(basis, th["drift_ok"], th["drift_watch"]),
               pct(basis) if not math.isnan(basis) else "-",
               f"Largest offset from centre at rest, from the {src}. "
               f"Typical rest offset: {pct(s['rest_typical']) if not math.isnan(s['rest_typical']) else '-'}.")
        # Safe deadzone (info)
        if not math.isnan(s["safe_deadzone"]):
            _f(F, f"{side}_safe_dz", f"{label}: safe in-game deadzone", INFO,
               f"{s['safe_deadzone'] * 100:.0f}%",
               "Set the in-game deadzone to at least this value to stop drift. "
               "This is the rest offset plus a 2% margin.")
        # Inner deadzone
        _f(F, f"{side}_inner", f"{label}: in-built centre deadzone",
           grade(s["inner_dz"], th["inner_dz_ok"], th["inner_dz_watch"]), pct(s["inner_dz"]),
           "The smallest movement out of centre that the pad ever reported. A high value means the pad "
           "hides small movements. (A deadzone that rescales its output can't be seen this way.)")
        # Axial band
        ab = s["axial_band"]
        _f(F, f"{side}_axial", f"{label}: cross-shaped deadzone / snapping",
           grade(ab, th["axial_ok"], th["axial_watch"]), pct(ab) if not math.isnan(ab) else "-",
           "Width of the dead band on one axis while the other axis is pushed. A wide band makes small "
           "diagonal moves start late and pull to up/down/left/right. "
           f"Zero share X {pct(s['axial_zero_share_x']) if not math.isnan(s['axial_zero_share_x']) else '-'}, "
           f"Y {pct(s['axial_zero_share_y']) if not math.isnan(s['axial_zero_share_y']) else '-'}.")
        # Outer reach
        if math.isnan(s["outer_avg"]):
            _f(F, f"{side}_outer", f"{label}: outer reach", NODATA, "-",
               f"The stick reached the edge in only {s['reach_covered']} of {th['outer_sectors']} directions.")
        else:
            _f(F, f"{side}_outer", f"{label}: outer reach",
               grade(s["outer_avg"], th["outer_ok"], th["outer_watch"], higher_is_better=True), pct(s["outer_avg"]),
               f"Average maximum value at full tilt, over {s['reach_covered']} of {th['outer_sectors']} directions. "
               f"Weakest direction: {pct(s['outer_min'])}.")
        # Stutter
        if s["motion_min"] >= 0.5:
            rate = len(s["stutters"]) / s["motion_min"]
            _f(F, f"{side}_stutter", f"{label}: stutter while moving",
               grade(rate, th["stutter_ok_per_min"], th["stutter_watch_per_min"]),
               f"{len(s['stutters'])} ({rate:.1f}/min)",
               f"Gaps in the data while the stick was moving, with a large jump after the gap. "
               f"Normal update interval seen by the logger: {s['update_ms']:.1f} ms.")
        # Update rate (info)
        iv = s.get("intervals", {})
        if iv.get("median"):
            _f(F, f"{side}_rate", f"{label}: update rate while moving", INFO,
               f"{iv['rate_hz']:.0f} Hz",
               f"Median time between reports {iv['median']:.1f} ms. Jitter (standard deviation) {iv['std']:.2f} ms. "
               f"{pct(iv['late_share'])} of reports came more than {th['late_x_median']}x later than normal. "
               "This is the rate that the logger sees (about 1 ms precision). It is not input latency.")
        # Noise at rest
        if math.isnan(s["noise_p2p"]):
            _f(F, f"{side}_noise", f"{label}: noise at rest", NODATA, "-",
               "No hands-off check in this log. Put the controller down for 10 seconds at the start.")
        else:
            _f(F, f"{side}_noise", f"{label}: noise at rest",
               grade(s["noise_p2p"], th["noise_ok"], th["noise_watch"]), pct(s["noise_p2p"]),
               f"How much the value moves while nobody touches the stick (largest minus smallest value, "
               f"from the {s['noise_source']}). Standard deviation {pct(s['noise_std'])}.")
        # Circularity
        if not math.isnan(s["circ_err"]):
            _f(F, f"{side}_circ", f"{label}: circularity error",
               grade(s["circ_err"], th["circ_ok"], th["circ_watch"]), pct(s["circ_err"]),
               "Average distance of the full-tilt edge from a perfect circle, over the directions you reached. "
               "Values above 100% (a square edge) and below 100% (short reach) both count.")
        # Return to centre
        if math.isnan(s["centre_err"]):
            _f(F, f"{side}_centre", f"{label}: return to centre", NODATA, "-",
               f"Only {s['centre_returns']} returns to rest after a push were found. "
               f"At least {th['centre_min_returns']} are necessary.")
        else:
            _f(F, f"{side}_centre", f"{label}: return to centre",
               grade(s["centre_err"], th["centre_ok"], th["centre_watch"]), pct(s["centre_err"]),
               f"Offset from centre when the stick comes back to rest after a push (90th percentile of "
               f"{s['centre_returns']} returns). Spread between the rest points {pct(s['centre_spread'])}.")
        # Resolution (info)
        rx, ry = s["resolution"][f"{side}x"], s["resolution"][f"{side}y"]
        bits = [b for b in (rx["bits"], ry["bits"]) if not math.isnan(b)]
        if bits:
            _f(F, f"{side}_res", f"{label}: resolution", INFO, f"about {min(bits):.0f} bit",
               f"Different values seen: X {rx['unique']}, Y {ry['unique']}. Typical step: "
               f"X {rx['step'] if not math.isnan(rx['step']) else '-'}, Y {ry['step'] if not math.isnan(ry['step']) else '-'} "
               "raw units. A low value means coarse steps. Software scaling can hide the true resolution.")

    for name, label in (("lt", "Left trigger"), ("rt", "Right trigger")):
        t = r.triggers.get(name, {})
        if not t.get("enough"):
            _f(F, f"{name}", label, NODATA, "-", "Not enough trigger data.")
            continue
        if t["digital"]:
            _f(F, f"{name}_type", f"{label}: type", INFO, "Digital",
               "Only on/off values were seen (a hair-trigger or digital mode).")
            continue
        _f(F, f"{name}_start", f"{label}: start deadzone",
           grade(t["start"], th["trigger_start_ok"], th["trigger_start_watch"]), pct(t["start"]),
           "The smallest pull that the trigger reported.")
        _f(F, f"{name}_end", f"{label}: full pull",
           grade(t["end"], th["trigger_end_ok"], th["trigger_end_watch"], higher_is_better=True), pct(t["end"]),
           f"The highest value seen. {t['unique']} different values seen.")

    b = r.buttons
    n = b["double_total"]
    st = OK if n < th["double_watch"] else WATCH if n < th["double_problem"] else PROBLEM
    which = ", ".join(f"{k} x{v}" for k, v in sorted(b["doubles"].items(), key=lambda kv: -kv[1]))
    _f(F, "doubles", "Double inputs", st, str(n),
       f"A new press less than {th['double_gap_ms']} ms after a release. " + (f"Buttons: {which}." if which else ""))

    d = r.dpad
    _f(F, "dpad_flicker", "D-pad: diagonal flicker", grade(d["flicker_pct"], th["flicker_ok_pct"], th["flicker_watch_pct"]),
       f"{d['flickers']} ({d['flicker_pct']:.1f}%)" if not math.isnan(d["flicker_pct"]) else f"{d['flickers']}",
       f"A held diagonal dropped to one direction for less than {th['flicker_ms']} ms. "
       f"Out of {d['diag_entries']} diagonals.")
    _f(F, "dpad_blip", "D-pad: accidental diagonal blips", grade(d["blip_pct"], th["blip_ok_pct"], th["blip_watch_pct"]),
       f"{d['blips']} ({d['blip_pct']:.1f}%)" if not math.isnan(d["blip_pct"]) else f"{d['blips']}",
       f"A diagonal showed for less than {th['flicker_ms']} ms during a single-direction press. "
       f"Out of {d['card_presses']} single-direction presses.")
    n_skip = sum(d["rolls_skipped"].values())
    worst = max(d["rolls_skipped"].items(), key=lambda kv: kv[1])[0] if n_skip else None
    _f(F, "dpad_roll_skip", "D-pad: diagonal skipped in rolls",
       grade(d["roll_skip_pct"], th["roll_skip_ok_pct"], th["roll_skip_watch_pct"]),
       f"{n_skip} of {d['rolls']} ({d['roll_skip_pct']:.0f}%)" if not math.isnan(d["roll_skip_pct"])
       else f"{n_skip} of {d['rolls']}",
       "A quick move from one direction to the next (for example right to down) jumped straight to the next "
       "direction. The diagonal between them did not show at all. A working D-pad shows the diagonal on almost "
       f"every roll. Most skips: {worst or '-'}. "
       f"Rolls with a short gap of nothing (usually the thumb lifts, not graded): {sum(d['rolls_gap'].values())}. "
       f"At least {th['roll_min']} rolls are necessary for a result. Compare pads with the same player and game.")
    if d["invalid"]:
        _f(F, "dpad_invalid", "D-pad: opposite directions together", PROBLEM, str(d["invalid"]),
           "Up+down or left+right at the same time. A rocker D-pad should not do this.")
    if not math.isnan(d["split_median"]):
        _f(F, "dpad_split", "D-pad: diagonal split time", INFO,
           f"{d['split_median']:.0f} ms median", f"90th percentile {d['split_p90']:.0f} ms. "
           "Time between the first and the second direction of a diagonal. This includes your thumb, "
           "so compare pads with the same player.")

    ch = r.chords
    if ch["count"]:
        _f(F, "chords", "Two-button presses: split time", INFO, f"{ch['median']:.0f} ms median",
           f"{ch['count']} presses within {th['chord_window_ms']} ms. {pct(ch['over_frame'])} were more than one "
           "frame apart at 60 fps. This includes your timing, so compare pads with the same player.")

    if b["paddles"]:
        _f(F, "paddles", "Back paddles", INFO, str(sum(b["paddles"].values())),
           "Paddle presses in this session. Compare with how often you meant to use them.")


def _drop_flicker_doubles(r: Report) -> None:
    """A D-pad flicker also looks like a fast release + press. Count it once, as a flicker."""
    ends = [f["t"] + f["ms"] for f in r.dpad["flicker_times"]]
    keep = []
    for d in r.buttons["double_times"]:
        if d["button"] in DPAD_BUTTONS and any(abs(d["t"] - x) < 0.01 for x in ends):
            r.buttons["doubles"][d["button"]] -= 1
            continue
        keep.append(d)
    r.buttons["double_times"] = keep
    r.buttons["doubles"] = {k: v for k, v in r.buttons["doubles"].items() if v > 0}
    r.buttons["double_total"] = sum(r.buttons["doubles"].values())


def analyse(log: Log) -> Report:
    r = Report(meta=log.meta, session=session_info(log))
    r.sticks = {"l": analyse_stick(log, "l"), "r": analyse_stick(log, "r")}
    r.triggers = {"lt": analyse_trigger(log, "lt"), "rt": analyse_trigger(log, "rt")}
    r.buttons = analyse_buttons(log)
    r.dpad = analyse_dpad(log)
    r.chords = analyse_chords(log)
    r.connection = analyse_connection(log)
    _drop_flicker_doubles(r)
    build_findings(r)
    return r


def summary_counts(findings: Iterable[Finding]) -> dict[str, int]:
    out = {OK: 0, WATCH: 0, PROBLEM: 0, NODATA: 0, INFO: 0}
    for f in findings:
        out[f.status] = out.get(f.status, 0) + 1
    return out
