"""Update rate and spread, stick resolution, circularity, noise at rest.

Each check: one test with a known fault, one clean test with no false alarm.
"""

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from padlab.analysis import (  # noqa: E402
    OK, PROBLEM, THRESHOLDS, WATCH, _circularity, _rest_noise, _stick_resolution, analyse,
)
from padlab.logfile import Event, Log  # noqa: E402


def _circles(start_ms, n, dt_fn, step=1, radius=1.0, turns=40):
    """Left stick turning in circles. dt_fn gives the time to the next report."""
    ev, t = [], start_ms
    for i in range(n):
        a = i / n * turns * 2 * math.pi
        x = int(round(radius * 32767 * math.cos(a) / step)) * step
        y = int(round(radius * 32767 * math.sin(a) / step)) * step
        ev += [Event(t, "a", "lx", x), Event(t, "a", "ly", y)]
        t += dt_fn(i)
    return ev, t


def _find(log, key):
    return {f.key: f for f in analyse(log).findings}[key]


# ---------------------------------------------------------------- update rate and spread

def test_update_rate_steady_wired_like():
    ev, end = _circles(0, 6000, lambda i: 4.0)
    log = Log(meta={"ended_ms": end, "loop_hz": 1000}, events=ev)
    rate = _find(log, "update_rate")
    assert rate.value.startswith("250 Hz")
    assert _find(log, "update_spread").status == OK


def test_update_spread_uneven_wireless_like():
    rnd = random.Random(3)
    ev, end = _circles(0, 6000, lambda i: rnd.choice([3.0, 7.5, 7.5, 15.0, 22.0]))
    log = Log(meta={"ended_ms": end, "loop_hz": 1000}, events=ev)
    assert _find(log, "update_spread").status in (WATCH, PROBLEM)


def test_update_rate_says_it_is_not_latency():
    ev, end = _circles(0, 6000, lambda i: 4.0)
    detail = _find(Log(meta={"ended_ms": end}, events=ev), "update_rate").detail
    assert "not input latency" in detail


# ---------------------------------------------------------------- resolution

def _samples_with_step(step, n=20000):
    rnd = random.Random(1)
    return [(i, rnd.randrange(-32767 // step, 32767 // step) * step,
             rnd.randrange(-32767 // step, 32767 // step) * step) for i in range(n)]


def test_resolution_ten_bit_stick():
    out = _stick_resolution(_samples_with_step(64))
    assert abs(out["bits"] - 10.0) < 0.05


def test_resolution_low_resolution_stick_is_a_problem():
    out = _stick_resolution(_samples_with_step(512))
    assert out["bits"] < THRESHOLDS["bits_watch"]


def test_resolution_fine_steps_shown_as_cap():
    ev, end = _circles(0, 60000, lambda i: 4.0, step=1, turns=401.37)
    f = _find(Log(meta={"ended_ms": end}, events=ev), "l_resolution")
    assert f.status == OK and f.value == "12+ bits"


# ---------------------------------------------------------------- circularity

def test_circularity_round_stick_ok():
    assert _circularity([1.0] * 36)["circle_error"] == 0.0


def test_circularity_uneven_edge_found():
    reach = [1.0 if k % 2 else 0.86 for k in range(36)]
    err = _circularity(reach)["circle_error"]
    assert err > THRESHOLDS["circle_ok"]


def test_circularity_ignores_half_pushes():
    # In play the stick is often pushed only part way. That must not count as a fault.
    reach = [1.0] * 20 + [0.6] * 16
    assert math.isnan(_circularity(reach)["circle_error"])


# ---------------------------------------------------------------- noise at rest

def test_noise_found_in_hands_off_window():
    s = [(t * 100.0, (1000 if t % 2 else 0), 0) for t in range(120)]  # 3% jumps for 12 s
    out = _rest_noise(s, {"t": 0.0, "dur": 12000.0})
    assert abs(out["rest_noise"] - 1000 / 32767) < 1e-6


def test_noise_ignores_pick_up_at_end_of_window():
    # Still for 11 s, then a 5% move in the last second (the player picks the pad up).
    s = [(t * 100.0, 0, 0) for t in range(110)] + [(11500.0, 1600, 0)]
    out = _rest_noise(s, {"t": 0.0, "dur": 12000.0})
    assert out["rest_noise"] == 0.0


def test_noise_needs_hands_off_window():
    assert math.isnan(_rest_noise([(0, 0, 0)], None)["rest_noise"])
