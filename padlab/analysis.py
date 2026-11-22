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
from array import array
from dataclasses import dataclass, field
from typing import Iterable

from .logfile import (
    AXIS_MAX,
    DPAD_BUTTONS,
    FACE_AND_SHOULDER,
    PADDLES,
    Event,
    Log,
)

# Increase when a check or a threshold changes. Old reports and the history cache are
# then made again from the logs.
ANALYSIS_VERSION = 9  # raise when checks or report layout change: old reports are made again

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
    # Guided test (information only: the results include the player's own accuracy).
    # A prompt counts as hit if the exact input comes before the next prompt, at most this late.
    "guided_window_ms": 1500,
    # Performance score (Best controller view, owner request 2026-11-18). Update rate:
    # 125 Hz scores 0 and 2000 Hz scores 100. Each doubling adds a quarter (250 = 25, 500 = 50,
    # 1000 = 75). Owner request (2026-11-22): pads can report faster than 1000 Hz. 2000 Hz is
    # about the fastest rate PadMaster can measure (its loop runs about 1900 times a second).
    "perf_rate_low_hz": 125.0, "perf_rate_high_hz": 2000.0,
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
    # Contact bounce (default, from one submitted log, 2026-11-18): after a hold of at least
    # bounce_hold_ms, the switch goes off and on again within bounce_gap_ms. A thumb can't do
    # that. Games that read the state once per frame usually miss it. Graded Watch at most.
    "bounce_gap_ms": 5, "bounce_hold_ms": 50, "bounce_watch": 1,
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
    guided: dict = field(default_factory=dict)


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


def norm_samples(samples) -> list[tuple[float, float, float]]:
    """(x, y, magnitude) for each sample, normalised once. Long sessions have millions of
    samples, and each check used to normalise them again (user report, 2026-11-19)."""
    out = []
    hyp = math.hypot
    for _, x, y in samples:
        nx = x / AXIS_MAX
        ny = y / AXIS_MAX
        nx = 1.0 if nx > 1.0 else -1.0 if nx < -1.0 else nx
        ny = 1.0 if ny > 1.0 else -1.0 if ny < -1.0 else ny
        out.append((nx, ny, hyp(nx, ny)))
    return out


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


def window_stats(samples, i: int, j: int, lo: float, hi: float, end_ms: float, nm=None) -> dict | None:
    """Mean, max and sample range of samples[i:j], counting only the time between lo and hi."""
    if nm is None:
        nm = norm_samples(samples)
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
        nxk, nyk, mk = nm[k]
        sx += nxk * w
        sy += nyk * w
        wsum += w
        if mk > max_mag:
            max_mag = mk
        k0 = k if k0 is None else k0
        k1 = k + 1
    if wsum <= 0:
        return None
    mx, my = sx / wsum, sy / wsum
    return {"x": mx, "y": -my, "mean_mag": math.hypot(mx, my), "max_mag": max_mag, "i0": k0, "i1": k1}


def rest_windows(samples, end_ms: float, nm=None) -> list[dict]:
    th = THRESHOLDS
    if nm is None:
        nm = norm_samples(samples)
    radius, tol = th["rest_radius"], th["rest_tolerance"]
    windows = []
    n = len(samples)
    i = 0
    while i < n:
        t0 = samples[i][0]
        nx0, ny0, m0 = nm[i]
        if m0 >= radius:
            i += 1
            continue
        j = i
        while j < n:
            nxj, nyj, mj = nm[j]
            if abs(nxj - nx0) > tol or abs(nyj - ny0) > tol or mj >= radius:
                break
            j += 1
        t_end = samples[j][0] if j < n else end_ms
        dur = t_end - t0
        if dur >= th["rest_min_ms"] and dur > 0:
            # Use only the middle of the window. The first and last samples can be the end of a
            # return or the start of the next push (the thumb touches the stick first).
            lo, hi = t0 + th["rest_trim_ms"], t_end - th["rest_trim_ms"]
            ws = window_stats(samples, i, j, lo, hi, end_ms, nm)
            if ws:
                windows.append({"t": t0, "dur": dur, "t_end": t_end, "i_start": i, "j": j, **ws})
        i = max(j, i + 1)
    return windows


class LiveAnalysis:
    """Analysis that runs during logging (user report, 2026-11-22). The logger gives it each
    row (see the LogWriter tap). Stick rows go to two StickAnalysers. Other rows (buttons,
    triggers, D-pad, prompts, connection) are kept: they are few, and their checks are fast.
    At Stop, analyse(live.as_log(), live) gives the same Report as analyse(read_log(path))."""

    STICK = {"lx": "l", "ly": "l", "rx": "r", "ry": "r"}

    def __init__(self):
        self.meta: dict = {}
        self.events: list[Event] = []
        self.sticks = {"l": StickAnalyser("lx", "ly"), "r": StickAnalyser("rx", "ry")}
        self.stick_inputs = 0
        self.stick_minutes: set[int] = set()
        self.n = 0
        self.last_t = 0.0

    def add_meta(self, meta: dict) -> None:
        self.meta.update(meta)

    def add(self, t: float, kind: str, name: str, value: int) -> None:
        self.n += 1
        self.last_t = t
        side = self.STICK.get(name) if kind == "a" else None
        if side:
            self.sticks[side].feed(t, name, value)
            self.stick_inputs += 1
            self.stick_minutes.add(int(t // 60000))
        else:
            self.events.append(Event(t, kind, name, value))

    def duration_ms(self) -> float:
        if not self.n:
            return 0.0
        end = self.meta.get("ended_ms")
        return float(end) if end is not None else self.last_t

    def as_log(self) -> Log:
        return _LiveLog(meta=self.meta, events=self.events, live=self)


@dataclass
class _LiveLog(Log):
    live: "LiveAnalysis | None" = None

    @property
    def duration_ms(self) -> float:
        return self.live.duration_ms()


def analyse_stick(log: Log, side: str) -> dict:
    """All stick checks for one stick ("l" or "r"). See StickAnalyser."""
    an = StickAnalyser(f"{side}x", f"{side}y")
    for e in log.events:
        if e.kind == "a":
            an.feed(e.t, e.name, e.value)
    return an.finish(log.duration_ms)


class StickAnalyser:
    """Stick checks, one sample at a time (user report, 2026-11-22: the report took too long
    after long sessions). The logger feeds it during play, so at Stop only the last steps run.
    The normal report (analyse_stick) uses the same class, so both give the same results.

    It keeps only what the checks need: running minimums, maximums and counts, the stream
    intervals, the set of raw values, and the samples since the start of the current rest
    window search (plus centre_lookback_ms before it)."""

    TRIM_AT = 50000  # drop old buffered samples when this many can go

    def __init__(self, xn: str, yn: str):
        th = THRESHOLDS
        self.xn, self.yn = xn, yn
        self.x = self.y = 0
        self.pending: tuple[float, int, int] | None = None
        self.n = 0                       # samples committed
        self.base = 0                    # absolute index of buf[0]
        self.buf: list[tuple[float, int, int]] = []
        self.nmb: list[tuple[float, float, float]] = []
        self.i = 0                       # rest window search position (absolute)
        self.j = 0                       # search progress for the window that starts at i
        self.wins: list[dict] = []
        self.handsoff: dict | None = None
        self.handsoff_done = False
        self.noise: dict | None = None
        self.returns: list[tuple[float, float]] = []
        self.inner = math.inf
        self.band = {1: [0, 0, math.inf], 2: [0, 0, math.inf]}  # count, nonzero, min nonzero
        self.n_sec = th["outer_sectors"]
        self.reach = [0.0] * self.n_sec
        self.hit = [False] * self.n_sec
        self.grid = [[0] * 41 for _ in range(41)]
        self.vals = ({}, {})              # raw x values, raw y values (dict keeps it fast)
        self.prev: tuple[float, float, float, float] | None = None  # t, nx, ny, mag
        self.st_idx = array("q")
        self.st_dt = array("d")
        self.st_jump = array("d")
        self.cand: list[int] = []         # stream positions that can be stutters
        self.cand_t: list[float] = []

    # -- input
    def feed(self, t: float, name: str, value: int) -> None:
        if name == self.xn:
            self.x = value
        elif name == self.yn:
            self.y = value
        else:
            return
        p = self.pending
        if p is not None and p[0] != t:
            self._commit(p)
        self.pending = (t, self.x, self.y)

    def _commit(self, smp: tuple[float, int, int]) -> None:
        th = THRESHOLDS
        t, x, y = smp
        nx = x / AXIS_MAX
        ny = y / AXIS_MAX
        nx = 1.0 if nx > 1.0 else -1.0 if nx < -1.0 else nx
        ny = 1.0 if ny > 1.0 else -1.0 if ny < -1.0 else ny
        m = math.hypot(nx, ny)
        idx = self.n
        self.n += 1
        self.buf.append(smp)
        self.nmb.append((nx, ny, m))
        self.vals[0][x] = 1
        self.vals[1][y] = 1
        if (x or y) and m < self.inner:
            self.inner = m
        lim = th["axial_other_axis"]
        for a, va, vb in ((1, nx, ny), (2, ny, nx)):
            if abs(vb) > lim:
                b = self.band[a]
                b[0] += 1
                av = abs(va)
                if av > 0:
                    b[1] += 1
                    if av < b[2]:
                        b[2] = av
        if m >= th["outer_min_mag"]:
            ang = (math.degrees(math.atan2(-ny, nx)) + 360) % 360
            k = int(ang // (360 / self.n_sec)) % self.n_sec
            self.hit[k] = True
            if m > self.reach[k]:
                self.reach[k] = m
        g = 41
        self.grid[min(g - 1, int((ny + 1) / 2 * g))][min(g - 1, int((nx + 1) / 2 * g))] += 1
        pv = self.prev
        smag = th["stream_mag"]
        if pv is not None and pv[3] > smag and m > smag:
            dt = t - pv[0]
            jump = math.hypot(nx - pv[1], ny - pv[2])
            if dt > th["stutter_min_gap_ms"] and jump > th["stutter_jump"]:
                self.cand.append(len(self.st_idx))
                self.cand_t.append(t)
            self.st_idx.append(idx)
            self.st_dt.append(dt)
            self.st_jump.append(jump)
        self.prev = (t, nx, ny, m)
        self._scan(None)

    # -- rest windows (same rule as rest_windows, run on the buffer)
    def _scan(self, end_ms: float | None) -> None:
        th = THRESHOLDS
        radius, tol = th["rest_radius"], th["rest_tolerance"]
        buf, nmb, base = self.buf, self.nmb, self.base
        n = len(buf)
        i = self.i
        while i - base < n:
            li = i - base
            nx0, ny0, m0 = nmb[li]
            if m0 >= radius:
                i += 1
                continue
            j = max(self.j, i) - base
            while j < n:
                nxj, nyj, mj = nmb[j]
                if abs(nxj - nx0) > tol or abs(nyj - ny0) > tol or mj >= radius:
                    break
                j += 1
            if j >= n and end_ms is None:
                self.j = j + base  # the window can still grow: wait for more samples
                break
            t0 = buf[li][0]
            t_end = buf[j][0] if j < n else end_ms
            dur = t_end - t0
            if dur >= th["rest_min_ms"] and dur > 0:
                lo, hi = t0 + th["rest_trim_ms"], t_end - th["rest_trim_ms"]
                ws = window_stats(buf, li, j, lo, hi, end_ms if end_ms is not None else t_end, nmb)
                if ws:
                    ws["i0"] += base
                    ws["i1"] += base
                    w = {"t": t0, "dur": dur, "t_end": t_end, "i_start": i, "j": j + base, **ws}
                    self.wins.append(w)
                    self._window_done(w, li, j, end_ms)
            i = max(j + base, i + 1)
            self.j = i
        self.i = i
        self._trim()

    def _window_done(self, w: dict, li: int, lj: int, end_ms: float | None) -> None:
        import bisect
        th = THRESHOLDS
        buf, nmb, base = self.buf, self.nmb, self.base
        if not self.handsoff_done and w["t"] < th["handsoff_window_ms"]:
            self.handsoff_done = True
            hi = min(w["t_end"] - th["rest_trim_ms"], th["handsoff_window_ms"])
            ws = window_stats(buf, li, lj, w["t"] + th["rest_trim_ms"], hi,
                              end_ms if end_ms is not None else w["t_end"], nmb)
            if ws:
                ws["i0"] += base
                ws["i1"] += base
                self.handsoff = {**w, **ws}
                self.noise = _rest_noise(buf, self.handsoff)
        times_k = bisect.bisect_left(buf, w["t"] - th["centre_lookback_ms"], 0, w["i0"] - base, key=lambda s: s[0])
        cf = th["centre_from"]
        if any(nmb[q][2] > cf for q in range(times_k, w["i0"] - base)):
            self.returns.append((w["x"], w["y"]))

    def _trim(self) -> None:
        # Keep centre_lookback_ms before the search position (for the centre return check).
        li = self.i - self.base
        if li < self.TRIM_AT:
            return
        # A later window starts at a sample at or after buf[li] (or after the newest sample).
        ref_t = self.buf[li][0] if li < len(self.buf) else self.buf[-1][0]
        keep_t = ref_t - THRESHOLDS["centre_lookback_ms"]
        cut = 0
        while cut < li and self.buf[cut][0] < keep_t:
            cut += 1
        if cut >= self.TRIM_AT // 2:
            del self.buf[:cut]
            del self.nmb[:cut]
            self.base += cut

    # -- result
    def finish(self, end_ms: float) -> dict:
        th = THRESHOLDS
        if self.pending is not None:
            self._commit(self.pending)
            self.pending = None
        res: dict = {"samples": self.n}
        if self.n < th["min_stick_samples"]:
            res["enough"] = False
            return res
        res["enough"] = True
        self._scan(end_ms)
        wins = self.wins
        res["rest_windows"] = len(wins)
        res["handsoff"] = self.handsoff
        res["rest_typical"] = percentile([w["mean_mag"] for w in wins], 0.5) if wins else float("nan")
        res["rest_worst"] = percentile([w["max_mag"] for w in wins], 0.9) if wins else float("nan")
        res["rest_points"] = [(w["x"], w["y"]) for w in wins][:400]
        res["rest_all_zero"] = bool(wins) and all(w["max_mag"] == 0 for w in wins)
        basis = self.handsoff["max_mag"] if self.handsoff else res["rest_worst"]
        res["safe_deadzone"] = float("nan") if math.isnan(basis) else math.ceil((basis + 0.02) * 100) / 100
        res["inner_dz"] = self.inner if self.inner != math.inf else float("nan")

        def band(a: int) -> tuple[float, float, int]:
            cnt, nz, mn = self.band[a]
            if cnt < 50:
                return float("nan"), float("nan"), cnt
            return (mn if nz else 1.0), 1 - nz / cnt, cnt

        bx, zx, _ = band(1)
        by, zy, _ = band(2)
        res["axial_x"], res["axial_zero_share_x"] = bx, zx
        res["axial_y"], res["axial_zero_share_y"] = by, zy
        candidates = [b for b, z in ((bx, zx), (by, zy)) if not math.isnan(b) and z > 0.05]
        res["axial_band"] = max(candidates) if candidates else (0.0 if not (math.isnan(bx) and math.isnan(by)) else float("nan"))

        n_sec, reach, hit = self.n_sec, self.reach, self.hit
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
        res["heatmap"] = self.grid

        st_idx, st_dt, st_jump = self.st_idx, self.st_dt, self.st_jump
        dts = [d for d in st_dt if d > 0]
        med = percentile(dts, 0.5) if dts else float("nan")
        res["update_ms"] = med
        stutters = []
        motion_ms = 0.0
        if dts:
            lim3 = 3 * med
            for d in st_dt:  # the same order of additions as before (exact same result)
                if d <= lim3:
                    motion_ms += d
            gap_limit = max(th["stutter_min_gap_ms"], th["stutter_gap_x_median"] * med)
            ns = len(st_idx)
            for p, pt in zip(self.cand, self.cand_t):
                dt, jump, i = st_dt[p], st_jump[p], st_idx[p]
                if not (dt > gap_limit and jump > th["stutter_jump"]):
                    continue
                prev_ok = p > 0 and st_idx[p - 1] == i - 1 and st_dt[p - 1] <= lim3
                next_ok = p + 1 < ns and st_idx[p + 1] == i + 1 and st_dt[p + 1] <= lim3
                speed_ok = False
                if prev_ok:
                    pdt, pjump = st_dt[p - 1], st_jump[p - 1]
                    expected = (pjump / pdt) * dt if pdt > 0 else 0.0
                    speed_ok = jump >= th["stutter_speed_match"] * expected
                if prev_ok and next_ok and speed_ok:
                    stutters.append({"t": pt, "gap_ms": dt, "jump": jump})
        res["stutters"] = stutters
        res["motion_min"] = motion_ms / 60000
        res["move_intervals"] = [d for d in dts if d <= 3 * med] if dts else []

        res.update(_resolution_from_values(sorted(self.vals[0]), sorted(self.vals[1])))
        res.update(_circularity(res["reach"]))
        res.update(self.noise if self.noise is not None else _rest_noise([], None))
        returns = self.returns
        out = {"centre_returns": len(returns)}
        if len(returns) >= th["centre_min_returns"]:
            out["centre_err"] = percentile([math.hypot(x, y) for x, y in returns], 0.9)
            out["centre_spread"] = max(math.hypot(a[0] - b[0], a[1] - b[1]) for a in returns for b in returns)
        else:
            out["centre_err"] = out["centre_spread"] = float("nan")
        res.update(out)
        return res


def _centre_return(s, wins, nm=None) -> dict:
    """Rest position after each push past centre_from (from the parallel PadMaster branch)."""
    import bisect
    th = THRESHOLDS
    times = [t for t, _, _ in s]
    returns = []
    for w in wins:
        k = bisect.bisect_left(times, w["t"] - th["centre_lookback_ms"])
        if any((nm[q][2] if nm else math.hypot(norm(s[q][1]), norm(s[q][2]))) > th["centre_from"]
               for q in range(k, w["i0"])):
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
    return _resolution_from_values(sorted({smp[1] for smp in s}), sorted({smp[2] for smp in s}))


def _resolution_from_values(vx: list[int], vy: list[int]) -> dict:
    """_stick_resolution from the sorted distinct raw values of each axis."""
    th = THRESHOLDS
    out: dict = {}
    for vals, axis in ((vx, "x"), (vy, "y")):
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
    res: dict = {"counts": {}, "doubles": {}, "double_times": [], "bounces": {}, "bounce_times": []}
    for name, lst in sorted(pr.items()):
        res["counts"][name] = len(lst)
        for (d1, u1), (d2, _) in zip(lst, lst[1:]):
            if u1 is not None and 0 <= d2 - u1 < gap:
                item = {"t": d2, "button": name, "gap_ms": d2 - u1, "held_ms": u1 - d1}
                bounce = item["gap_ms"] < THRESHOLDS["bounce_gap_ms"] and item["held_ms"] >= THRESHOLDS["bounce_hold_ms"]
                kind = "bounce" if bounce else "double"
                res[kind + "_times"].append(item)
                res[kind + "s"][name] = res[kind + "s"].get(name, 0) + 1
    res["double_total"] = sum(res["doubles"].values())
    res["bounce_total"] = sum(res["bounces"].values())
    res["double_times"].sort(key=lambda d: d["t"])
    res["bounce_times"].sort(key=lambda d: d["t"])
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


def _guided_findings(r: Report, F: list) -> None:
    g = r.guided
    if not g:
        return
    note = " This includes your own accuracy, so compare pads with the same player."
    for kind, title, what in (("diag", "Guided: D-pad diagonals hit", "Diagonal prompts where both directions were held together."),
                              ("card", "Guided: D-pad directions hit", "Up, down, left and right prompts that were pressed."),
                              ("btn", "Guided: buttons hit", "Button prompts that were pressed.")):
        hit, n = g[kind]
        if n:
            _f(F, f"guided_{kind}", title, INFO, f"{hit} of {n} ({hit / n:.0%})", what + note)
    if g["card"][1]:
        _f(F, "guided_accidental", "Guided: accidental diagonals", INFO, str(g["accidental_diag"]),
           "Up, down, left or right prompts where a diagonal also showed." + note)
    if g["btn"][1]:
        _f(F, "guided_wrong", "Guided: wrong button presses", INFO, str(g["wrong"]),
           "Button prompts where another button was also pressed." + note)
    if not g["complete"]:
        _f(F, "guided_incomplete", "Guided test not finished", INFO, "stopped early",
           "The test was stopped before the end. Some results can be missing.")


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
       f"A new press less than {th['double_gap_ms']} ms after a release. " + (f"Buttons: {which}." if which else "")
       + f" Contact bounce is not counted here (see the next line).")
    nb = b.get("bounce_total", 0)
    bwhich = ", ".join(f"{k} x{v}" for k, v in sorted(b.get("bounces", {}).items(), key=lambda kv: -kv[1]))
    _f(F, "bounce", "Contact bounce", OK if nb < th["bounce_watch"] else WATCH, str(nb),
       f"After a hold of at least {th['bounce_hold_ms']} ms, the button went off and on again in less than "
       f"{th['bounce_gap_ms']} ms. A thumb can't do that: the switch contact bounces. Games that read the button "
       f"once per frame usually miss it. Games that read every press can see a second press. "
       + (f"Buttons: {bwhich}." if bwhich else ""))

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
    for kind in ("double", "bounce"):
        keep = []
        counts = r.buttons.get(kind + "s", {})
        for d in r.buttons.get(kind + "_times", []):
            if d["button"] in DPAD_BUTTONS and any(abs(d["t"] - x) < 0.01 for x in ends):
                counts[d["button"]] -= 1
                continue
            keep.append(d)
        r.buttons[kind + "_times"] = keep
        r.buttons[kind + "s"] = {k: v for k, v in counts.items() if v > 0}
        r.buttons[kind + "_total"] = sum(r.buttons[kind + "s"].values())


def analyse(log: Log, live: "LiveAnalysis | None" = None) -> Report:
    """Full analysis. With ``live`` (from the logger), the stick checks are already done."""
    if live is None:
        r = Report(meta=log.meta, session=session_info(log))
        r.sticks = {"l": analyse_stick(log, "l"), "r": analyse_stick(log, "r")}
    else:
        si = session_info(log)
        others = {int(e.t // 60000) for e in log.events if e.kind in ("a", "b")}
        si["inputs"] += live.stick_inputs
        si["active_min"] = len(others | live.stick_minutes)
        r = Report(meta=log.meta, session=si)
        end = live.duration_ms()
        r.sticks = {k: an.finish(end) for k, an in live.sticks.items()}
    r.triggers = {"lt": analyse_trigger(log, "lt"), "rt": analyse_trigger(log, "rt")}
    r.buttons = analyse_buttons(log)
    r.dpad = analyse_dpad(log)
    r.chords = analyse_chords(log)
    r.connection = analyse_connection(log)
    r.timing = analyse_timing(log, r.sticks)
    r.guided = analyse_guided(log)
    _drop_flicker_doubles(r)
    build_findings(r)
    _guided_findings(r, r.findings)
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
    {"key": "bounce", "label": "Contact bounce", "unit": "count", "better": "low", "ok": "bounce_watch", "watch": "bounce_watch", "pct": False},
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
    out["bounce"] = float(r.buttons.get("bounce_total", 0))
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


# ---------------------------------------------------------------- best controller

def grade_metric(m: dict, v: float) -> str:
    """OK, Watch or Problem for one Compare number, from the THRESHOLDS limits."""
    ok, watch = THRESHOLDS[m["ok"]], THRESHOLDS[m["watch"]]
    if m["better"] == "low":
        if ok == watch:  # one limit only (contact bounce): Watch at most, as in the report
            return OK if v < ok else WATCH
        return OK if v < ok else WATCH if v < watch else PROBLEM
    return OK if v >= ok else WATCH if v >= watch else PROBLEM


# Performance checks: how well the pad works, not only if it has a fault. Score 100 is the
# best possible value. Score 0 is the Watch limit (or 125 Hz for the update rate).
PERF_KEYS = ["update_rate_hz", "update_spread_ms", "l_bits", "r_bits", "l_outer", "r_outer",
             "l_circle", "r_circle", "l_inner", "r_inner", "lt_start", "rt_start"]


def perf_score(key: str, v: float) -> float:
    """0 to 100 for one performance check."""
    th = THRESHOLDS
    if key == "update_rate_hz":
        lo, hi = th["perf_rate_low_hz"], th["perf_rate_high_hz"]
        x = math.log2(max(v, 1e-9) / lo) / math.log2(hi / lo)
    else:
        m = next(m for m in METRICS if m["key"] == key)
        watch = th[m["watch"]]
        best = {"bits": th["bits_cap"], "%": 1.0 if m["better"] == "high" else 0.0}.get(m["unit"], 0.0)
        x = (v - watch) / (best - watch)
    return round(max(0.0, min(1.0, x)) * 100, 1)


# Price rule (owner request, 2026-11-19): "the bar goes up with the price". For each
# doubling of the price above the cheapest priced controller, a controller must be
# PRICE_POINTS_DEFAULT performance points better to tie. A very good cheap pad can beat an
# expensive pad that is only as good as its price leads you to expect. The user can change
# the points (0 to 20). 0 ranks by performance only.
PRICE_POINTS_DEFAULT = 10


def price_bar(price: float, cheapest: float, points: float) -> float:
    """Points taken off for the price: points x the number of price doublings above the cheapest."""
    return round(points * math.log2(price / cheapest), 1) if price > cheapest else 0.0


def rank_controllers(groups: dict[str, list[dict]], min_checks: int = 5,
                     prices: dict[str, float] | None = None, price_points: float = 0.0) -> list[dict]:
    """Rank controllers for the Best controller view.

    groups: controller name -> list of metric_values() dicts (one per session).
    Each controller gets the median of its sessions for each check. The rule (simple, so
    it can be said on camera): the highest performance score (mean of PERF_KEYS scores)
    is first. Problems and Watch results are shown and only decide a tie. Controllers
    with fewer than min_checks graded results, or fewer than 3 performance results, are
    listed, but not ranked."""
    graded = [m for m in METRICS if m["ok"] and m["watch"]]
    med: dict[str, dict[str, float]] = {}
    for name, rows in groups.items():
        med[name] = {}
        for m in METRICS:
            vals = sorted(r[m["key"]] for r in rows if r and r.get(m["key"]) is not None)
            if vals:
                n = len(vals)
                med[name][m["key"]] = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    out = []
    gkeys = {m["key"]: m for m in graded}
    for name, allvals in med.items():
        vals = {k: v for k, v in allvals.items() if k in gkeys}
        grades = {k: grade_metric(gkeys[k], v) for k, v in vals.items()}
        perf = {k: perf_score(k, allvals[k]) for k in PERF_KEYS if k in allvals}
        # Star (owner request, 2026-11-22): checks where this controller is better than every
        # other controller. A tie gives no star, so the stars show what makes a pad different.
        wins = []
        for m in METRICS:
            k = m["key"]
            if k not in allvals or m.get("better") not in ("low", "high"):
                continue
            others = [med[o][k] for o in med if o != name and k in med[o]]
            v = allvals[k]
            if others and all((v < x) if m["better"] == "low" else (v > x) for x in others):
                wins.append(k)
        out.append({
            "name": name, "sessions": len(groups[name]), "checks": len(vals),
            "problems": [k for k, g in grades.items() if g == PROBLEM],
            "watch": [k for k, g in grades.items() if g == WATCH],
            "wins": wins, "values": allvals, "grades": grades, "perf": perf,
            "score": round(sum(perf.values()) / len(perf), 1) if len(perf) >= 3 else None,
            "ranked": len(vals) >= min_checks and len(perf) >= 3,
        })
    # Price rule: value score = performance score - price bar (see PRICE_POINTS_DEFAULT).
    # When the rule is on, a controller with no price is listed, but not ranked.
    prices = {k: float(v) for k, v in (prices or {}).items() if v and float(v) > 0}
    pts = max(0.0, min(20.0, float(price_points or 0)))
    if len([n for n in prices if n in groups]) < 2:
        pts = 0.0  # fewer than two prices: nothing to compare, rank by performance only
    cheap = min((prices[c["name"]] for c in out if c["name"] in prices and c["ranked"]), default=None)
    for c in out:
        p = prices.get(c["name"])
        c["price"] = p
        c["points"] = pts
        c["price_bar"] = price_bar(p, cheap, pts) if p and cheap else None
        c["overall"] = c["score"]
        if pts > 0:
            if c["price_bar"] is None:
                c["ranked"] = False
                c["overall"] = None
            elif c["score"] is not None:
                c["overall"] = round(c["score"] - c["price_bar"], 1)
    # Overall score first. Problems and Watch only decide a tie.
    out.sort(key=lambda c: (not c["ranked"], -(c["overall"] or 0), len(c["problems"]), len(c["watch"]), c["name"]))
    pos = 0
    for c in out:
        if c["ranked"]:
            pos += 1
            c["rank"] = pos
        else:
            c["rank"] = None
    return out


# ---------------------------------------------------------------- guided test

def analyse_guided(log: Log) -> dict:
    """Score the prompt game of a guided test. Empty dict for a normal session.

    For each prompt: hit if the exact input happens before the next prompt (at most
    guided_window_ms after it). D-pad: the held directions must be exactly the asked
    ones (both for a diagonal). A cardinal prompt that also shows a diagonal counts as
    an accidental diagonal. A button prompt with another face or shoulder button
    pressed counts as a wrong press."""
    from .guided import BUTTONS, DPAD
    prompts = [e for e in log.events if e.kind == "p"]
    if not prompts:
        return {}
    win = THRESHOLDS["guided_window_ms"]
    steps = [{"t": e.t, "key": e.name} for e in prompts]
    game = [i for i, p in enumerate(steps) if p["key"] in DPAD or p["key"] in BUTTONS]
    dirs = ("up", "down", "left", "right")
    held: set[str] = set()
    timeline: list[tuple[float, frozenset]] = [(0.0, frozenset())]
    presses: list[tuple[float, str]] = []
    for e in log.events:
        if e.kind != "b":
            continue
        if e.name in dirs:
            (held.add if e.value else held.discard)(e.name)
            timeline.append((e.t, frozenset(held)))
        elif e.value:
            presses.append((e.t, e.name))
    btn_names = {v[1] for v in BUTTONS.values()}
    res = {"card": [0, 0], "diag": [0, 0], "btn": [0, 0], "accidental_diag": 0, "wrong": 0,
           "misses": [], "prompts": len(game),
           "complete": bool(log.meta.get("guided_complete", False)),
           "phases": [{"t": p["t"], "key": p["key"]} for p in steps if p["key"].startswith("phase_")]}
    for i in game:
        p = steps[i]
        t0 = p["t"]
        nxt = steps[i + 1]["t"] if i + 1 < len(steps) else t0 + win
        t1 = min(t0 + win, nxt)
        if p["key"] in DPAD:
            want = frozenset(DPAD[p["key"]][1])
            kind = "diag" if len(want) == 2 else "card"
            before = [s for t, s in timeline if t <= t0]
            states = ([before[-1]] if before else []) + [s for t, s in timeline if t0 < t <= t1]
            hit = want in states[1:]  # a new press after the prompt
            if kind == "card" and any(len(s) == 2 for s in states[1:]):
                res["accidental_diag"] += 1
        else:
            want_b = BUTTONS[p["key"]][1]
            kind = "btn"
            got = [n for t, n in presses if t0 < t <= t1 and n in btn_names]
            hit = want_b in got
            if any(n != want_b for n in got):
                res["wrong"] += 1
        res[kind][1] += 1
        if hit:
            res[kind][0] += 1
        else:
            res["misses"].append({"t": t0, "prompt": p["key"]})
    return res
