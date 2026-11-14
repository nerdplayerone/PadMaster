"""Tests for the checks added in the ControllerMeta feature-gap work:
update rate, noise at rest, circularity, return to centre, resolution, GUID ids."""

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402

from padlab.analysis import NODATA, OK, PROBLEM, WATCH, analyse, guid_info  # noqa: E402
from padlab.logfile import LogWriter, read_log  # noqa: E402
from padlab.report import render  # noqa: E402
from synth import build  # noqa: E402

MAX = 32767


def find(rep, key):
    return next(f for f in rep.findings if f.key == key)


def _write(tmp_path, name, rows, end, meta=None):
    p = str(tmp_path / name)
    w = LogWriter(p, {"device": name, "mode": "controller", **(meta or {})})
    for r in sorted(rows, key=lambda r: r[0]):
        w.write(*r)
    w.meta({"ended_ms": end})
    w.close()
    return analyse(read_log(p))


def _circles(t0, t1, step, rows, radius=1.0, shape=None, side="l"):
    t = t0
    while t < t1:
        a = t / 600
        x, y = math.cos(a) * radius, math.sin(a) * radius
        if shape:
            x, y = shape(x, y)
        rows.append((t, "a", f"{side}x", int(max(-1, min(1, x)) * MAX)))
        rows.append((t, "a", f"{side}y", int(max(-1, min(1, -y)) * MAX)))
        t += step
    return t


def _rest(t0, t1, step, rows, x=0.0, y=0.0, noise=0.0, rnd=None, side="l"):
    t = t0
    while t < t1:
        nx = x + (rnd.uniform(-noise, noise) if noise else 0)
        ny = y + (rnd.uniform(-noise, noise) if noise else 0)
        rows.append((t, "a", f"{side}x", int(nx * MAX)))
        rows.append((t, "a", f"{side}y", int(-ny * MAX)))
        t += step


# ------------------------------------------------------------ update rate

def test_update_rate_from_steady_4ms_reports(tmp_path):
    rows = []
    _circles(0, 60000, 4, rows)
    r = _write(tmp_path, "rate.csv.gz", rows, 60000)
    iv = r.sticks["l"]["intervals"]
    assert iv["median"] == pytest.approx(4.0)
    assert iv["rate_hz"] == pytest.approx(250)
    assert iv["std"] < 0.1
    assert iv["late_share"] == 0
    f = find(r, "l_rate")
    assert f.status == "info" and "latency" in f.detail


def test_update_rate_counts_late_reports(tmp_path):
    rows = []
    t = 0.0
    k = 0
    while t < 60000:
        a = t / 600
        rows.append((t, "a", "lx", int(math.cos(a) * MAX)))
        rows.append((t, "a", "ly", int(math.sin(a) * MAX)))
        t += 12 if k % 10 == 0 else 4  # every 10th report is 3x late
        k += 1
    r = _write(tmp_path, "late.csv.gz", rows, 60000)
    assert 0.08 < r.sticks["l"]["intervals"]["late_share"] < 0.12


# ------------------------------------------------------------ noise

def test_noisy_stick_at_rest_is_problem(tmp_path):
    rnd = random.Random(1)
    rows = []
    _rest(0, 12000, 8, rows, noise=0.03, rnd=rnd)
    _circles(12000, 60000, 4, rows)
    r = _write(tmp_path, "noise.csv.gz", rows, 60000)
    assert r.sticks["l"]["noise_p2p"] > 0.05
    assert find(r, "l_noise").status == PROBLEM


def test_quiet_stick_at_rest_is_ok(tmp_path):
    rnd = random.Random(2)
    rows = []
    _rest(0, 12000, 8, rows, noise=0.002, rnd=rnd)
    _circles(12000, 60000, 4, rows)
    r = _write(tmp_path, "quiet.csv.gz", rows, 60000)
    assert find(r, "l_noise").status == OK


def test_thumb_held_still_during_play_is_not_noise(tmp_path):
    """Regression (real log 2026-11-13 23:31): no hands-off window, and a still moment during
    play (a thumb on the stick) was graded as noise. Noise must use the hands-off check only."""
    rnd = random.Random(3)
    rows = []
    _circles(0, 30000, 4, rows)
    _rest(30000, 33000, 8, rows, x=0.05, noise=0.03, rnd=rnd)  # thumb wobble at low tilt
    _circles(33000, 60000, 4, rows)
    r = _write(tmp_path, "thumb.csv.gz", rows, 60000)
    assert find(r, "l_noise").status == NODATA


def test_push_after_handsoff_is_not_drift_or_noise():
    """Regression (real Xbox pad log 2026-11-14 00:06, first 25 s, axis rows only).
    The stick read exactly 0 for 21.8 s. The first samples of the next push (up to about 5%)
    were counted in the rest window and gave false drift and noise of about 5%."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "handsoff_then_push.csv.gz")
    r = analyse(read_log(p))
    for side in "lr":
        s = r.sticks[side]
        assert s["handsoff"] is not None
        assert s["handsoff"]["max_mag"] == 0
        assert s["noise_p2p"] == 0


def test_touch_at_end_of_long_handsoff_is_not_noise():
    """Regression (real Xbox pad log 2026-11-14 00:17, right stick, first 60 s).
    The pad rested for 42.7 s. A 12 ms thumb touch (3.1%) at 42.5 s was counted as noise and drift.
    The hands-off check must use only the first handsoff_window_ms of the session."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "long_handsoff_then_touch.csv.gz")
    r = analyse(read_log(p))
    s = r.sticks["r"]
    assert s["handsoff"]["max_mag"] == 0
    assert s["noise_p2p"] == 0


# ------------------------------------------------------------ circularity

def test_round_stick_has_low_circularity_error(tmp_path):
    rows = []
    _circles(0, 60000, 4, rows)
    r = _write(tmp_path, "round.csv.gz", rows, 60000)
    assert r.sticks["l"]["circ_err"] < 0.01
    assert find(r, "l_circ").status == OK


def test_square_gate_has_high_circularity_error(tmp_path):
    """A pad that maps the circle to a square reports up to 141% in the diagonals."""
    def square(x, y):
        m = max(abs(x), abs(y))
        return (x / m, y / m) if m else (0.0, 0.0)
    rows = []
    _circles(0, 60000, 4, rows, shape=square)
    r = _write(tmp_path, "square.csv.gz", rows, 60000)
    assert r.sticks["l"]["circ_err"] > 0.10
    assert find(r, "l_circ").status == PROBLEM


def test_short_reach_shows_in_circularity(tmp_path):
    p = str(tmp_path / "synth.csv.gz")
    build(p)
    r = analyse(read_log(p))
    assert 0.06 < r.sticks["r"]["circ_err"] < 0.10  # right stick reaches only 92%
    assert find(r, "r_circ").status == WATCH


# ------------------------------------------------------------ return to centre

def _flicks(rest_points, tmp_path, name):
    rows = []
    t = 0.0
    for (x, y) in rest_points:
        _circles(t, t + 600, 4, rows)          # push to the edge
        t += 600
        _rest(t, t + 2000, 8, rows, x=x, y=y)  # come back and rest
        t += 2000
    return _write(tmp_path, name, rows, t)


def test_stick_that_returns_off_centre_is_problem(tmp_path):
    pts = [(0.07, 0.0), (-0.07, 0.0), (0.0, 0.07), (0.0, -0.07)] * 3
    r = _flicks(pts, tmp_path, "sticky.csv.gz")
    s = r.sticks["l"]
    assert s["centre_returns"] >= 10
    assert s["centre_err"] == pytest.approx(0.07, abs=0.005)
    assert s["centre_spread"] == pytest.approx(0.14, abs=0.01)
    assert find(r, "l_centre").status == PROBLEM


def test_stick_that_returns_to_zero_is_ok(tmp_path):
    r = _flicks([(0.0, 0.0)] * 12, tmp_path, "clean_return.csv.gz")
    assert find(r, "l_centre").status == OK


def test_return_to_centre_needs_enough_returns(tmp_path):
    rows = []
    _circles(0, 60000, 4, rows)
    r = _write(tmp_path, "noreturn.csv.gz", rows, 60000)
    assert find(r, "l_centre").status == NODATA


# ------------------------------------------------------------ resolution

def test_resolution_of_an_8_bit_stick(tmp_path):
    def quant(x, y):
        return round(x * 127) / 127, round(y * 127) / 127
    rows = []
    _circles(0, 60000, 4, rows, shape=quant)
    r = _write(tmp_path, "8bit.csv.gz", rows, 60000)
    res = r.sticks["l"]["resolution"]["lx"]
    assert 7.5 < res["bits"] < 8.5
    assert "8 bit" in find(r, "l_res").value


def test_resolution_of_a_full_16_bit_stick(tmp_path):
    rows = []
    _circles(0, 120000, 1, rows)
    r = _write(tmp_path, "16bit.csv.gz", rows, 120000)
    assert r.sticks["l"]["resolution"]["lx"]["bits"] > 14


# ------------------------------------------------------------ D-pad rolls

ROLL_PAIRS = [("right", "down"), ("down", "left"), ("left", "up"), ("up", "right")]


def _rolls(tmp_path, name, n, skip_every=0, skip_kind="direct"):
    """n quarter rolls C1 -> (C1+C2 for 16 ms) -> C2. Every skip_every-th roll skips the diagonal."""
    rows = []
    t = 1000.0
    for i in range(n):
        c1, c2 = ROLL_PAIRS[i % 4]
        rows.append((t, "b", c1, 1))
        skip = skip_every and i % skip_every == 0
        if skip and skip_kind == "direct":
            rows.append((t + 80, "b", c1, 0))
            rows.append((t + 80, "b", c2, 1))
        elif skip:
            rows.append((t + 80, "b", c1, 0))
            rows.append((t + 92, "b", c2, 1))  # 12 ms of nothing
        else:
            rows.append((t + 80, "b", c2, 1))
            rows.append((t + 96, "b", c1, 0))
        rows.append((t + 200, "b", c2, 0))
        t += 500
    return _write(tmp_path, name, rows, t)


def test_rolls_that_skip_the_diagonal_are_problem(tmp_path):
    r = _rolls(tmp_path, "skip.csv.gz", 40, skip_every=2)
    d = r.dpad
    assert d["rolls"] == 40
    assert sum(d["rolls_skipped"].values()) == 20
    assert d["roll_skip_pct"] == pytest.approx(50)
    assert find(r, "dpad_roll_skip").status == PROBLEM
    assert len(d["roll_skip_times"]) == 20


def test_gap_of_nothing_is_info_not_a_skip(tmp_path):
    """A good pad also shows short gaps when the thumb lifts (owner's Xbox pad: 15%). Not graded."""
    r = _rolls(tmp_path, "gap.csv.gz", 40, skip_every=4, skip_kind="gap")
    assert sum(r.dpad["rolls_gap"].values()) == 10
    assert r.dpad["roll_gap_pct"] == pytest.approx(25)
    assert r.dpad["roll_skip_pct"] == 0
    assert find(r, "dpad_roll_skip").status == OK


def test_real_logs_good_pad_ok_faulty_pad_problem():
    """Regression (owner's logs 2026-11-14, D-pad rows only, same game).
    Xbox pad: 3 of 105 rolls jumped straight (OK). DualSense: 31 of 164 (Problem)."""
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    good = analyse(read_log(os.path.join(base, "dpad_rolls_good.csv.gz")))
    bad = analyse(read_log(os.path.join(base, "dpad_rolls_faulty.csv.gz")))
    assert good.dpad["rolls"] == 105 and sum(good.dpad["rolls_skipped"].values()) == 3
    assert find(good, "dpad_roll_skip").status == OK
    assert bad.dpad["rolls"] == 164 and sum(bad.dpad["rolls_skipped"].values()) == 31
    assert find(bad, "dpad_roll_skip").status == PROBLEM


def test_clean_rolls_are_ok(tmp_path):
    r = _rolls(tmp_path, "rolls_ok.csv.gz", 40)
    assert r.dpad["roll_skip_pct"] == 0
    assert find(r, "dpad_roll_skip").status == OK


def test_slow_separate_presses_are_not_rolls(tmp_path):
    """Right, release, wait 200 ms, down: two separate presses, not a skipped roll."""
    rows = []
    t = 0.0
    for i in range(40):
        c1, c2 = ROLL_PAIRS[i % 4]
        rows += [(t, "b", c1, 1), (t + 80, "b", c1, 0), (t + 280, "b", c2, 1), (t + 360, "b", c2, 0)]
        t += 600
    r = _write(tmp_path, "separate.csv.gz", rows, t)
    assert r.dpad["rolls"] == 0
    assert find(r, "dpad_roll_skip").status == NODATA


def test_synthetic_session_has_no_roll_skips(tmp_path):
    p = str(tmp_path / "synth.csv.gz")
    build(p)
    r = analyse(read_log(p))
    assert sum(r.dpad["rolls_skipped"].values()) == 0


# ------------------------------------------------------------ device ids

def test_guid_info_usb_xbox_pad():
    g = guid_info("0300938d5e040000ff02000000007200")
    assert g == {"bus": 3, "bus_name": "USB", "vid": "045E", "pid": "02FF"}


def test_guid_info_bluetooth_and_bad_values():
    assert guid_info("05000000c82d00000161000000010000")["bus_name"] == "Bluetooth"
    assert guid_info(None) == {}
    assert guid_info("zz") == {}


def test_report_shows_ids_connection_and_power(tmp_path):
    rows = []
    _circles(0, 30000, 4, rows)
    r = _write(tmp_path, "ids.csv.gz", rows, 30000,
               {"guid": "0300938d5e040000ff02000000007200", "connection": "dongle", "power": "full"})
    html = render(r, "ids.csv.gz")
    assert "VID 045E" in html and "PID 02FF" in html
    assert "connection dongle" in html and "power full" in html
    assert "—" not in html  # owner rule: no em dashes
