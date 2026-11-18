"""Turn a PadMaster log into measurements and findings.

Pure Python (no numpy), so the Windows build stays small.

Every check here is passive: the logger does not know what the player WANTED to
press. So each check looks for patterns that a human hand does not make
(for example a release and a new press 5 ms apart), or uses moments when the
player is not touching a stick. All thresholds are in THRESHOLDS so you can
tune them. They are judgement calls, not industry standards.
"""

from __future__ import annotations

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

# Increase when a check or a threshold changes. Old reports and the history cache are
# then made again from the logs.
ANALYSIS_VERSION = 8  # raise when checks or report layout change: old reports are made again

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
    # Stick resolution (steps from centre, bits)
    "resolution_min_gaps": 50,     # neighbouring value pairs needed on an axis
    "resolution_max_gap": 2048,    # larger gaps are unvisited ranges, not steps
    "bits_ok": 10.0, "bits_watch": 8.0,
    "bits_cap": 12.0,              # above this the value can come from driver smoothing: show "12+ bits"
    # Circularity
    "circle_min_covered": 30,     # of the 36 directions
    "circle_full_tilt": 0.85,     # a direction counts only if the stick got this far
    "circle_ok": 0.05, "circle_watch": 0.10,
    # Noise at rest (hands-off window)
    "noise_ok": 0.005, "noise_watch": 0.02,
    "noise_window_ms": 10000,
    # Update rate and interval spread
    "timing_min_intervals": 500,
    "spread_ok_ms": 1.5, "spread_watch_ms": 4.0,
    # Stutter
    "stream_mag": 0.2,
    "stutter_min_gap_ms": 40,
    "stutter_gap_x_median": 6,
    "stutter_jump": 0.08,         # minimum jump across the gap
    "stutter_speed_match": 0.5,   # jump must be at least this share of (speed before gap x gap)
    "stutter_ok_per_min": 0.5, "stutter_watch_per_min": 3,
    # Triggers
    "trigger_start_ok": 0.03, "trigger_start_watch": 0.10,
    "trigger_end_ok": 0.98, "trigger_end_watch": 0.90,
    "min_trigger_events": 20,
    "trigger_digital_share": 0.95,  # share of values at fully off or fully on: digital trigger
    # Buttons
    "double_gap_ms": 20,          # release -> press faster than this is not a human
    "double_watch": 1, "double_problem": 3,
    # D-pad
    "flicker_ms": 35,
    "dpad_split_max_ms": 100,
    "dpad_min_diagonals": 10,
    "flicker_ok_pct": 2, "flicker_watch_pct": 10,
    "blip_ok_pct": 2, "blip_watch_pct": 10,
    # Rolls: a quick move from one direction to the next (right -> down). A working rocker passes
    # through the diagonal on almost every roll. Only a direct switch (C1 -> C2, no diagonal) is graded.
    # A short gap of nothing is shown as info only: a good pad also shows it when the thumb lifts
    # (owner's Xbox pad: 3% direct switches, 15% gaps; faulty pad: 19% direct, 27% gaps).
    "roll_diag_max_ms": 100,      # a diagonal longer than this is a held diagonal, not a roll
    "roll_gap_max_ms": 40,        # a gap of nothing shorter than this, between neighbours, is a gap roll
    "roll_min": 20,
    "roll_skip_ok_pct": 5, "roll_skip_watch_pct": 15,
    # Return to centre: rest position after the stick was pushed past centre_from
    "centre_from": 0.5,
    "centre_lookback_ms": 1000,
    "centre_min_returns": 5,
    "centre_ok": 0.03, "centre_watch": 0.06,
    "dpad_min_cardinals": 20,
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
    timing: dict = field(default_factory=dict)


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
    # Intervals during steady movement (pauses removed), for the update-rate check.
    res["move_intervals"] = [d for d in dts if d <= 3 * med] if dts else []

    res.update(_stick_resolution(s))
    res.update(_circularity(res["reach"]))
    res.update(_rest_noise(s, res["handsoff"]))
    res.update(_centre_return(s, wins))
    return res


def _centre_return(s, wins) -> dict:
    """Rest position after each push past centre_from (from the parallel PadMaster branch)."""
    import bisect
    th = THRESHOLDS
    times = [t for t, _, _ in s]
    returns = []
    for w in wins:
        k = bisect.bisect_left(times, w["t"] - th["centre_lookback_ms"])
        if any(math.hypot(norm(s[q][1]), norm(s[q][2])) > th["centre_from"] for q in range(k, w["i0"])):
            returns.append((w["x"], w["y"]))
    out = {"centre_returns": len(returns)}
    if len(returns) >= th["centre_min_returns"]:
        out["centre_err"] = percentile([math.hypot(x, y) for x, y in returns], 0.9)
        out["centre_spread"] = max(math.hypot(a[0] - b[0], a[1] - b[1]) for a in returns for b in returns)
    else:
        out["centre_err"] = out["centre_spread"] = float("nan")
    return out


def _stick_resolution(s) -> dict:
    """Step size from the raw values: the most common gap between neighbouring values.

    In a long session the stick passes through most positions, so neighbouring values
    in the sorted list are one step apart. Steps from centre = 32767 / step.
    """
    th = THRESHOLDS
    out: dict = {}
    for idx, axis in ((1, "x"), (2, "y")):
        vals = sorted({smp[idx] for smp in s})
        gaps = [b - a for a, b in zip(vals, vals[1:]) if 0 < b - a <= th["resolution_max_gap"]]
        # Need values over at least half the full range. Count gaps, not values: a coarse
        # stick has few values, and that is the fault this check must find.
        if len(vals) < 2 or vals[-1] - vals[0] < AXIS_MAX or len(gaps) < th["resolution_min_gaps"]:
            out[f"step_{axis}"] = float("nan")
            continue
        counts: dict[int, int] = {}
        for g in gaps:
            counts[g] = counts.get(g, 0) + 1
        top = max(counts.values())
        # Several sizes near the top count (rounding gives e.g. 64 and 65): take their mean.
        near = [g for g, c in counts.items() if c >= 0.5 * top]
        out[f"step_{axis}"] = sum(g * counts[g] for g in near) / sum(counts[g] for g in near)
    steps = [v for v in (out["step_x"], out["step_y"]) if not math.isnan(v)]
    if steps:
        worst = max(steps)
        out["steps_from_centre"] = AXIS_MAX / worst
        out["bits"] = math.log2(65536 / worst)
    else:
        out["steps_from_centre"] = out["bits"] = float("nan")
    return out


def _circularity(reach: list) -> dict:
    """Mean distance of the outer edge from a circle, as a share of its mean radius.

    Only directions where the stick was pushed to full tilt count. In normal play a
    stick is often pushed only part way, and that is not a fault of the stick.
    """
    covered = [r for r in reach if r is not None and r >= THRESHOLDS["circle_full_tilt"]]
    if len(covered) < THRESHOLDS["circle_min_covered"]:
        return {"circle_error": float("nan")}
    mean = sum(covered) / len(covered)
    return {"circle_error": sum(abs(r - mean) for r in covered) / len(covered) / mean}


def _rest_noise(s, handsoff: dict | None) -> dict:
    """Largest movement of the reported value while nobody touched the stick (hands-off window)."""
    if not handsoff:
        return {"rest_noise": float("nan"), "rest_changes_per_s": float("nan")}
    # Use only the instructed 10 s, and leave out the last second before the window ends
    # (the player picks up the controller then).
    t0 = handsoff["t"]
    t1 = min(t0 + THRESHOLDS["noise_window_ms"], t0 + handsoff["dur"] - 1000)
    if t1 - t0 < 3000:
        return {"rest_noise": float("nan"), "rest_changes_per_s": float("nan")}
    xs = [norm(x) for t, x, _ in s if t0 <= t < t1]
    ys = [norm(y) for t, _, y in s if t0 <= t < t1]
    if not xs:
        return {"rest_noise": float("nan"), "rest_changes_per_s": float("nan")}
    noise = max(max(xs) - min(xs), max(ys) - min(ys))
    return {"rest_noise": noise, "rest_changes_per_s": (len(xs) - 1) / ((t1 - t0) / 1000)}


def analyse_timing(log: Log, sticks: dict) -> dict:
    """Update rate and interval spread seen by PadMaster while a stick moves steadily.

    This is the rate at which PadMaster receives new stick values. It is not the USB polling
    rate measured by other tools, and it is not input latency.
    """
    th = THRESHOLDS
    iv = [d for s in sticks.values() for d in s.get("move_intervals", [])]
    res: dict = {"intervals": len(iv), "loop_hz": log.meta.get("loop_hz")}
    if len(iv) < th["timing_min_intervals"]:
        res["enough"] = False
        return res
    res["enough"] = True
    med = percentile(iv, 0.5)
    mean = sum(iv) / len(iv)
    res["median_ms"] = med
    res["rate_hz"] = 1000 / med if med > 0 else float("nan")
    res["spread_ms"] = math.sqrt(sum((d - mean) ** 2 for d in iv) / len(iv))
    res["p10_ms"], res["p90_ms"] = percentile(iv, 0.1), percentile(iv, 0.9)
    lh = res["loop_hz"]
    res["at_limit"] = bool(lh) and res["rate_hz"] > lh / 2
    return res


# ---------------------------------------------------------------- triggers

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
    # Digital mode: only on/off. Some pads also send 1 or 2 values on the way, within about
    # 1 ms (owner report and a submitted log, 2026-11-17/18). So a trigger that is almost
    # always fully off or fully on is digital, even if it sent a few in-between values.
    at_ends = sum(1 for v in vals if v == 0 or v >= AXIS_MAX * 0.98)
    res["end_share"] = at_ends / len(vals)
    res["digital"] = res["unique"] <= 3 or res["end_share"] >= THRESHOLDS["trigger_digital_share"]
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

    tm = r.timing
    not_latency = ("This is how often PadMaster gets new stick values on this PC. It is not input latency, and "
                   "it does not use the same method as other test sites.")
    if not tm.get("enough"):
        _f(F, "update_rate", "Update rate seen by PadMaster", NODATA, "-",
           "Not enough steady stick movement to measure it. " + not_latency)
        _f(F, "update_spread", "Update interval spread", NODATA, "-", "Not enough steady stick movement.")
    else:
        limit = (f" PadMaster checks for input about {tm['loop_hz']:.0f} times per second, so rates above about "
                 f"{tm['loop_hz'] / 2:.0f} Hz can't be measured exactly." if tm.get("loop_hz") else "")
        _f(F, "update_rate", "Update rate seen by PadMaster", INFO,
           f"{tm['rate_hz']:.0f} Hz ({tm['median_ms']:.1f} ms)",
           f"Median time between new stick values while a stick moved. {not_latency}{limit}"
           + (" This result is at that limit." if tm["at_limit"] else ""))
        _f(F, "update_spread", "Update interval spread",
           grade(tm["spread_ms"], th["spread_ok_ms"], th["spread_watch_ms"]), f"{tm['spread_ms']:.1f} ms",
           f"How much the time between updates changes (standard deviation). 10% of intervals were below "
           f"{tm['p10_ms']:.1f} ms and 10% above {tm['p90_ms']:.1f} ms. A large spread means uneven updates, "
           "which you can feel as less smooth aim. Wireless connections often have a larger spread.")

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
        # Circularity
        if math.isnan(s["circle_error"]):
            _f(F, f"{side}_circle", f"{label}: circularity error", NODATA, "-",
               f"Needs full-tilt movement in at least {th['circle_min_covered']} of {th['outer_sectors']} "
               f"directions. This session has {s['reach_covered']}. Turn the stick in full circles to test it.")
        else:
            _f(F, f"{side}_circle", f"{label}: circularity error",
               grade(s["circle_error"], th["circle_ok"], th["circle_watch"]), pct(s["circle_error"]),
               "How far the outer edge is from a perfect circle, as a share of its average size. "
               "A high value means the stick reaches further in some directions than in others.")
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
        # Resolution
        if math.isnan(s["bits"]):
            _f(F, f"{side}_resolution", f"{label}: resolution", NODATA, "-",
               "Not enough different stick positions in this session to find the step size.")
        else:
            fine = s["bits"] >= th["bits_cap"]
            _f(F, f"{side}_resolution", f"{label}: resolution",
               grade(s["bits"], th["bits_ok"], th["bits_watch"], higher_is_better=True),
               f"{th['bits_cap']:.0f}+ bits" if fine else f"{s['bits']:.1f} bits ({s['steps_from_centre']:,.0f} steps)",
               "Number of steps the pad reports from the centre to the edge, from the most common gap "
               "between values. More steps give smoother aim. "
               + (f"Above {th['bits_cap']:.0f} bits PadMaster can't tell real steps from driver smoothing, so it "
                  "shows only that the steps are fine." if fine else
                  "If the driver smooths or rescales the values, the real resolution can be lower than shown."))
        # Noise at rest
        if math.isnan(s["rest_noise"]):
            _f(F, f"{side}_noise", f"{label}: noise at rest", NODATA, "-",
               "Needs the hands-off check: put the controller down for 10 seconds at the start.")
        else:
            _f(F, f"{side}_noise", f"{label}: noise at rest",
               grade(s["rest_noise"], th["noise_ok"], th["noise_watch"]), pct(s["rest_noise"]),
               f"How much the value moved while nobody touched the stick (hands-off check). "
               f"{s['rest_changes_per_s']:.1f} value changes per second. "
               + ("The pad reported no change at all. A driver deadzone can hide noise." if s["rest_noise"] == 0 else ""))
        # Stutter
        if s["motion_min"] >= 0.5:
            rate = len(s["stutters"]) / s["motion_min"]
            _f(F, f"{side}_stutter", f"{label}: stutter while moving",
               grade(rate, th["stutter_ok_per_min"], th["stutter_watch_per_min"]),
               f"{len(s['stutters'])} ({rate:.1f}/min)",
               f"Gaps in the data while the stick was moving, with a large jump after the gap. "
               f"Normal update interval seen by the logger: {s['update_ms']:.1f} ms.")

    for name, label in (("lt", "Left trigger"), ("rt", "Right trigger")):
        t = r.triggers.get(name, {})
        if not t.get("enough"):
            _f(F, f"{name}", label, NODATA, "-", "Not enough trigger data.")
            continue
        if t["digital"]:
            _f(F, f"{name}_type", f"{label}: type", INFO, "Digital",
               f"The trigger was fully off or fully on for {t['end_share']:.0%} of its values (a hair-trigger or digital mode). "
               "PadMaster does not grade the deadzone of a digital trigger.")
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
    r.timing = analyse_timing(log, r.sticks)
    _drop_flicker_doubles(r)
    build_findings(r)
    return r


def summary_counts(findings: Iterable[Finding]) -> dict[str, int]:
    out = {OK: 0, WATCH: 0, PROBLEM: 0, NODATA: 0, INFO: 0}
    for f in findings:
        out[f.status] = out.get(f.status, 0) + 1
    return out


# ---------------------------------------------------------------- comparison values

# Numbers for the Compare view. "better": which way is better. "ok"/"watch": THRESHOLDS
# keys for the limit lines (None = information only). "pct": stored as a fraction,
# shown as a percentage.
METRICS = [
    {"key": "update_rate_hz", "label": "Update rate seen by PadMaster", "unit": "Hz", "better": "high", "ok": None, "watch": None, "pct": False},
    {"key": "update_spread_ms", "label": "Update interval spread", "unit": "ms", "better": "low", "ok": "spread_ok_ms", "watch": "spread_watch_ms", "pct": False},
    {"key": "l_drift", "label": "Left stick: drift at rest", "unit": "%", "better": "low", "ok": "drift_ok", "watch": "drift_watch", "pct": True},
    {"key": "r_drift", "label": "Right stick: drift at rest", "unit": "%", "better": "low", "ok": "drift_ok", "watch": "drift_watch", "pct": True},
    {"key": "l_noise", "label": "Left stick: noise at rest", "unit": "%", "better": "low", "ok": "noise_ok", "watch": "noise_watch", "pct": True},
    {"key": "r_noise", "label": "Right stick: noise at rest", "unit": "%", "better": "low", "ok": "noise_ok", "watch": "noise_watch", "pct": True},
    {"key": "l_inner", "label": "Left stick: centre deadzone", "unit": "%", "better": "low", "ok": "inner_dz_ok", "watch": "inner_dz_watch", "pct": True},
    {"key": "r_inner", "label": "Right stick: centre deadzone", "unit": "%", "better": "low", "ok": "inner_dz_ok", "watch": "inner_dz_watch", "pct": True},
    {"key": "l_axial", "label": "Left stick: cross-shaped deadzone", "unit": "%", "better": "low", "ok": "axial_ok", "watch": "axial_watch", "pct": True},
    {"key": "r_axial", "label": "Right stick: cross-shaped deadzone", "unit": "%", "better": "low", "ok": "axial_ok", "watch": "axial_watch", "pct": True},
    {"key": "l_outer", "label": "Left stick: outer reach", "unit": "%", "better": "high", "ok": "outer_ok", "watch": "outer_watch", "pct": True},
    {"key": "r_outer", "label": "Right stick: outer reach", "unit": "%", "better": "high", "ok": "outer_ok", "watch": "outer_watch", "pct": True},
    {"key": "l_circle", "label": "Left stick: circularity error", "unit": "%", "better": "low", "ok": "circle_ok", "watch": "circle_watch", "pct": True},
    {"key": "r_circle", "label": "Right stick: circularity error", "unit": "%", "better": "low", "ok": "circle_ok", "watch": "circle_watch", "pct": True},
    {"key": "l_bits", "label": "Left stick: resolution", "unit": "bits", "better": "high", "ok": "bits_ok", "watch": "bits_watch", "pct": False},
    {"key": "r_bits", "label": "Right stick: resolution", "unit": "bits", "better": "high", "ok": "bits_ok", "watch": "bits_watch", "pct": False},
    {"key": "lt_start", "label": "Left trigger: start deadzone", "unit": "%", "better": "low", "ok": "trigger_start_ok", "watch": "trigger_start_watch", "pct": True},
    {"key": "rt_start", "label": "Right trigger: start deadzone", "unit": "%", "better": "low", "ok": "trigger_start_ok", "watch": "trigger_start_watch", "pct": True},
    {"key": "doubles", "label": "Double inputs", "unit": "count", "better": "low", "ok": "double_watch", "watch": "double_problem", "pct": False},
    {"key": "l_centre", "label": "Left stick: return to centre", "unit": "%", "better": "low", "ok": "centre_ok", "watch": "centre_watch", "pct": True},
    {"key": "r_centre", "label": "Right stick: return to centre", "unit": "%", "better": "low", "ok": "centre_ok", "watch": "centre_watch", "pct": True},
    {"key": "dpad_roll_skip", "label": "D-pad: diagonal skipped in rolls", "unit": "%", "better": "low", "ok": "roll_skip_ok_pct", "watch": "roll_skip_watch_pct", "pct": False},
    {"key": "dpad_flicker", "label": "D-pad: diagonal flicker", "unit": "%", "better": "low", "ok": "flicker_ok_pct", "watch": "flicker_watch_pct", "pct": False},
    {"key": "disconnects", "label": "Disconnects", "unit": "count", "better": "low", "ok": None, "watch": None, "pct": False},
]


def metric_values(r: Report) -> dict[str, float | None]:
    """One number per METRICS entry for this session. None when there is no result."""
    def ok(v):
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), 5)

    out: dict[str, float | None] = {}
    tm = r.timing
    out["update_rate_hz"] = ok(tm.get("rate_hz")) if tm.get("enough") else None
    out["update_spread_ms"] = ok(tm.get("spread_ms")) if tm.get("enough") else None
    for side in ("l", "r"):
        s = r.sticks.get(side, {})
        if not s.get("enough"):
            for k in ("drift", "noise", "inner", "axial", "outer", "circle", "bits", "centre"):
                out[f"{side}_{k}"] = None
            continue
        ho = s.get("handsoff")
        out[f"{side}_drift"] = 0.0 if s.get("rest_all_zero") else ok(ho["max_mag"] if ho else s.get("rest_worst"))
        out[f"{side}_noise"] = ok(s.get("rest_noise"))
        out[f"{side}_inner"] = ok(s.get("inner_dz"))
        out[f"{side}_axial"] = ok(s.get("axial_band"))
        out[f"{side}_outer"] = ok(s.get("outer_avg"))
        out[f"{side}_circle"] = ok(s.get("circle_error"))
        out[f"{side}_centre"] = ok(s.get("centre_err"))
        bits = s.get("bits")
        out[f"{side}_bits"] = ok(min(bits, THRESHOLDS["bits_cap"])) if bits is not None and not math.isnan(bits) else None
    for name in ("lt", "rt"):
        t = r.triggers.get(name, {})
        out[f"{name}_start"] = ok(t.get("start")) if t.get("enough") and not t.get("digital") else None
    out["doubles"] = float(r.buttons.get("double_total", 0))
    fp = r.dpad.get("flicker_pct")
    out["dpad_flicker"] = ok(fp) if r.dpad.get("diag_entries") else None
    out["dpad_roll_skip"] = ok(r.dpad.get("roll_skip_pct"))
    out["disconnects"] = float(r.connection.get("disconnects", 0))
    return out


def metric_definitions() -> list[dict]:
    """METRICS with the limit values filled in from THRESHOLDS (for the Compare view)."""
    out = []
    for m in METRICS:
        d = dict(m)
        d["ok_value"] = THRESHOLDS[m["ok"]] if m["ok"] else None
        d["watch_value"] = THRESHOLDS[m["watch"]] if m["watch"] else None
        out.append(d)
    return out
