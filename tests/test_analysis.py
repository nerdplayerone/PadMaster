import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402

from padlab.analysis import PROBLEM, OK, analyse  # noqa: E402
from padlab.logfile import read_log  # noqa: E402
from padlab.report import render  # noqa: E402
from synth import build  # noqa: E402


@pytest.fixture(scope="module")
def rep(tmp_path_factory):
    p = str(tmp_path_factory.mktemp("logs") / "synth.csv.gz")
    build(p)
    return analyse(read_log(p))


def find(rep, key):
    return next(f for f in rep.findings if f.key == key)


def test_disconnect(rep):
    assert rep.connection["disconnects"] == 1
    assert rep.connection["outages"][0]["ms"] == pytest.approx(3000)
    assert find(rep, "disconnects").status == PROBLEM


def test_left_drift_from_handsoff(rep):
    s = rep.sticks["l"]
    assert s["handsoff"] is not None
    assert 0.035 < s["handsoff"]["max_mag"] < 0.055
    assert 0.06 <= s["safe_deadzone"] <= 0.08


def test_left_axial_band(rep):
    s = rep.sticks["l"]
    assert 0.09 < s["axial_band"] < 0.12
    assert find(rep, "l_axial").status == PROBLEM


def test_right_inner_deadzone_and_reach(rep):
    s = rep.sticks["r"]
    assert 0.10 < s["inner_dz"] < 0.13
    assert s["axial_band"] < 0.03
    assert 0.90 < s["outer_avg"] < 0.93
    assert s["rest_all_zero"]


def test_left_stutters(rep):
    assert len(rep.sticks["l"]["stutters"]) == 5
    assert len(rep.sticks["r"]["stutters"]) == 5  # both sticks lose data in the same gap


def test_triggers(rep):
    lt, rt = rep.triggers["lt"], rep.triggers["rt"]
    assert not lt["digital"] and 0.05 < lt["start"] < 0.11 and lt["end"] == pytest.approx(1.0)
    assert rt["digital"]


def test_double_inputs(rep):
    b = rep.buttons
    assert b["doubles"] == {"rb": 4}
    assert "a" not in b["doubles"]


def test_dpad(rep):
    d = rep.dpad
    assert d["diag_entries"] == 100
    assert d["flickers"] == 6  # i % 16 == 5 for i < 100: 5, 21, 37, 53, 69, 85
    assert d["blips"] == 5
    assert d["card_presses"] == 100
    assert d["split_median"] == pytest.approx(15)


def test_chords(rep):
    c = rep.chords
    assert c["count"] == 30
    assert 5 <= c["median"] <= 25


def test_report_renders(rep):
    html = render(rep, "synth.csv.gz")
    assert "<svg" in html and "Synthetic Test Pad" in html
    assert "serif" not in html.replace("sans-serif", "")


def test_clean_log_has_no_false_alarms(tmp_path):
    """A clean pad: no doubles, no flicker, no stutter."""
    from padlab.logfile import LogWriter
    p = str(tmp_path / "clean.csv.gz")
    w = LogWriter(p, {"device": "Clean", "mode": "controller"})
    t = 0.0
    while t < 60000:
        a = t / 600
        w.write(t, "a", "lx", int(math.cos(a) * 32767))
        w.write(t, "a", "ly", int(math.sin(a) * 32767))
        t += 4
    t = 61000.0
    for i in range(100):
        w.write(t, "b", "a", 1)
        w.write(t + 70, "b", "a", 0)
        t += 140  # fast mashing: 70 ms gaps
    w.meta({"ended_ms": 80000})
    w.close()
    r = analyse(read_log(p))
    assert r.buttons["double_total"] == 0
    assert r.sticks["l"]["stutters"] == []
    assert find(r, "doubles").status == OK


def test_low_resolution_slow_stick_is_not_stutter(tmp_path):
    """A 7-bit stick moved slowly sends few updates. That is not a dropout."""
    from padlab.logfile import LogWriter
    p = str(tmp_path / "lowres.csv.gz")
    w = LogWriter(p, {"device": "LowRes", "mode": "controller"})
    t = 0.0
    last = None
    while t < 90000:
        a = t / 9000  # very slow circle
        x = round(math.cos(a) * 0.8 * 127) / 127
        y = round(math.sin(a) * 0.8 * 127) / 127
        if (x, y) != last:  # SDL only sends changes
            w.write(t, "a", "lx", int(x * 32767))
            w.write(t, "a", "ly", int(y * 32767))
            last = (x, y)
        t += 4
    w.meta({"ended_ms": 90000})
    w.close()
    r = analyse(read_log(p))
    assert r.sticks["l"]["stutters"] == []


def test_hold_then_flick_is_not_stutter(tmp_path):
    from padlab.logfile import LogWriter
    p = str(tmp_path / "flick.csv.gz")
    w = LogWriter(p, {"device": "Flick", "mode": "controller"})
    t = 0.0
    for rep_i in range(60):
        # hold still at the right for 500 ms (no events), then flick to the left in 40 ms
        w.write(t, "a", "lx", 32767)
        w.write(t, "a", "ly", 0)
        t += 500
        for k in range(1, 11):
            w.write(t + k * 4, "a", "lx", int(32767 * (1 - 2 * k / 10)))
            w.write(t + k * 4, "a", "ly", int(32767 * 0.5 * math.sin(math.pi * k / 10)))
        t += 540
    w.meta({"ended_ms": t})
    w.close()
    r = analyse(read_log(p))
    assert r.sticks["l"]["stutters"] == []


def test_digital_trigger_with_values_on_the_way_is_not_a_deadzone():
    """Owner report (2026-11-17): a pad with triggers in digital mode got a trigger deadzone
    result. It sends a few values between off and full, but never a small pull."""
    from padlab.analysis import analyse
    from padlab.logfile import Log, Event
    ev, t = [], 0.0
    for _ in range(15):
        for v in (21000, 32767):
            ev.append(Event(t, "a", "rt", v)); t += 1
        for v in (18000, 0):
            ev.append(Event(t, "a", "rt", v)); t += 1
    rep = analyse(Log(meta={"device": "Pad"}, events=ev))
    assert rep.triggers["rt"]["digital"]
    keys = [f.key for f in rep.findings]
    assert "rt_type" in keys and "rt_start" not in keys
