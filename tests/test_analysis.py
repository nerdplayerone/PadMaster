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


def test_digital_trigger_with_a_small_value_on_the_way_is_digital():
    """Submitted log (2026-11-18): each press goes 0 -> 6167 -> 23643 -> 32767 within
    about 2 ms. The small value on the way must not make it an analogue trigger."""
    from padlab.analysis import analyse
    from padlab.logfile import Log, Event
    ev, t = [], 0.0
    for i in range(100):
        ev.append(Event(t, "a", "lt", 0)); t += 200
        if i % 25 == 0:
            ev.append(Event(t, "a", "lt", 1413 + i)); t += 1
            ev.append(Event(t, "a", "lt", 19017 + i)); t += 1
        ev.append(Event(t, "a", "lt", 32767)); t += 200
    rep = analyse(Log(meta={"device": "Pad"}, events=ev))
    assert rep.triggers["lt"]["digital"] and rep.triggers["lt"]["unique"] > 3
    keys = [f.key for f in rep.findings]
    assert "lt_type" in keys and "lt_start" not in keys


def test_slow_analogue_pulls_stay_analogue():
    from padlab.analysis import analyse
    from padlab.logfile import Log, Event
    ev, t = [], 0.0
    for _ in range(10):
        for v in list(range(0, 32767, 1500)) + [32767] + list(range(32767, -1, -1500)):
            ev.append(Event(t, "a", "rt", v)); t += 4
    rep = analyse(Log(meta={"device": "Pad"}, events=ev))
    assert not rep.triggers["rt"]["digital"]




def test_contact_bounce_is_split_from_double_inputs():
    """Owner decision (2026-11-18): a long hold, then off and on in under 5 ms, is contact
    bounce (Watch). A short press, then a new press 8 ms later, stays a double input."""
    from padlab.analysis import analyse, WATCH
    from padlab.logfile import Log, Event
    ev, t = [], 0.0

    def press(name, start, ms):
        ev.append(Event(start, "b", name, 1)); ev.append(Event(start + ms, "b", name, 0))
    for i in range(30):
        t = i * 1000.0
        press("a", t, 300)
        if i % 10 == 0:
            press("a", t + 302, 200)   # bounce: 2 ms off after a 300 ms hold
        press("b", t + 600, 30)
        if i % 15 == 0:
            press("b", t + 638, 30)    # double: 8 ms after a 30 ms press
    ev.sort(key=lambda e: e.t)
    rep = analyse(Log(meta={"device": "Pad"}, events=ev))
    assert rep.buttons["bounces"] == {"a": 3} and rep.buttons["doubles"] == {"b": 2}
    f = {x.key: x for x in rep.findings}
    assert f["bounce"].status == WATCH and f["bounce"].value == "3"
    assert f["doubles"].value == "2"



def test_rank_controllers_fewest_problems_first():
    """Owner request (2026-11-18): a Best controller view. Fewest Problems wins,
    then fewest Watch, then most best values. Too few checks: listed, not ranked."""
    from padlab.analysis import rank_controllers, THRESHOLDS as T
    good = {"l_drift": T["drift_ok"] / 2, "r_drift": T["drift_ok"] / 2, "doubles": 0.0,
            "bounce": 0.0, "l_outer": 1.0, "r_outer": 1.0}
    bad = dict(good, doubles=float(T["double_problem"] + 5))
    meh = dict(good, bounce=float(T["bounce_watch"] + 1))
    few = {"doubles": 0.0}
    r = rank_controllers({"Bad": [bad], "Meh": [meh, meh], "Good": [good], "Few": [few]})
    assert [c["name"] for c in r] == ["Good", "Meh", "Bad", "Few"]
    assert [c["rank"] for c in r] == [1, 2, 3, None]
    assert r[2]["problems"] == ["doubles"] and r[1]["watch"] == ["bounce"]
