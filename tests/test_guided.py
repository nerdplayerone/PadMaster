"""Guided test (owner approval, 2026-11-18): schedule, prompt scoring and the logger."""

import sys
import types

from padlab.guided import BUTTONS, DPAD, schedule
from padlab.logfile import Event, Log


def test_schedule_is_fixed_and_fair():
    a, b = schedule(5), schedule(5)
    assert a == b
    game = [k for _, k, _ in a if k in DPAD or k in BUTTONS]
    assert len(game) == 72
    assert sum(1 for k in game if k in DPAD and len(DPAD[k][1]) == 2) == 24
    assert all(x != y for x, y in zip(game, game[1:]))
    assert 200 < a[-1][0] < 300 and a[-1][1] == "end"
    assert [t for t, _, _ in a] == sorted(t for t, _, _ in a)


def _log(steps, presses, complete=True):
    ev = [Event(t, "p", k, i) for i, (t, k) in enumerate(steps)]
    for t, name, v in presses:
        ev.append(Event(t, "b", name, v))
    ev.sort(key=lambda e: e.t)
    return Log(meta={"device": "Pad", "guided": True, "guided_complete": complete}, events=ev)


def test_prompt_scoring_hits_misses_and_accidental_diagonals():
    from padlab.analysis import analyse
    steps = [(0, "phase_game"), (1000, "dpad_upleft"), (3000, "dpad_up"), (5000, "btn_a"),
             (7000, "dpad_downright"), (9000, "btn_b"), (11000, "end")]
    presses = [
        (1200, "up", 1), (1230, "left", 1), (1400, "up", 0), (1410, "left", 0),   # diagonal hit
        (3200, "up", 1), (3250, "right", 1), (3300, "right", 0), (3500, "up", 0),  # hit + accidental diagonal
        (5300, "a", 1), (5400, "a", 0),                                           # button hit
        (7200, "down", 1), (7500, "down", 0),                                     # diagonal missed
        (9300, "a", 1), (9400, "a", 0),                                           # wrong button, miss
    ]
    rep = analyse(_log(steps, presses))
    g = rep.guided
    assert g["diag"] == [1, 2] and g["card"] == [1, 1] and g["btn"] == [1, 2]
    assert g["accidental_diag"] == 1 and g["wrong"] == 1
    assert [m["prompt"] for m in g["misses"]] == ["dpad_downright", "btn_b"]
    keys = {f.key: f for f in rep.findings}
    assert keys["guided_diag"].value == "1 of 2 (50%)" and keys["guided_diag"].status == "info"
    assert "guided_incomplete" not in keys


def test_normal_session_has_no_guided_results():
    from padlab.analysis import analyse
    rep = analyse(Log(meta={"device": "Pad"}, events=[Event(0, "b", "a", 1), Event(50, "b", "a", 0)]))
    assert rep.guided == {} and not any(f.key.startswith("guided") for f in rep.findings)


def test_guided_report_section():
    from padlab.analysis import analyse
    from padlab.report import render
    rep = analyse(_log([(0, "phase_rest"), (500, "phase_game"), (1000, "btn_a"), (3000, "end")], [], complete=False))
    h = render(rep)
    assert "<h2>Guided test</h2>" in h and "Guided miss" in h and "stopped before the end" in h


def test_logger_writes_prompts_and_stops_at_the_end(monkeypatch, tmp_path):
    from tests.test_logger_smoke import make_fake_pygame
    from padlab.logfile import read_log
    import time as _t
    pg, sdl2, ctrl = make_fake_pygame([], True)
    n = {"i": 0}

    def get():
        n["i"] += 1
        _t.sleep(0.005)
        if n["i"] > 400:
            raise KeyboardInterrupt  # safety: the test did not end
        return []
    pg.event = types.SimpleNamespace(get=get, pump=lambda: None)
    monkeypatch.setitem(sys.modules, "pygame", pg)
    monkeypatch.setitem(sys.modules, "pygame._sdl2", sdl2)
    monkeypatch.setitem(sys.modules, "pygame._sdl2.controller", ctrl)
    from padlab import guided, logger
    monkeypatch.setattr(logger, "POLL_SLEEP_S", 0)
    monkeypatch.setattr(guided, "schedule", lambda seed=0: [(0.0, "phase_rest", "Rest"), (0.05, "btn_a", "A"), (0.2, "end", "Done")])
    log = read_log(logger.run(str(tmp_path), 0, guided=True, idle_stop_s=0.01))
    assert [e.name for e in log.events if e.kind == "p"] == ["phase_rest", "btn_a", "end"]
    assert log.meta.get("guided") is True and log.meta.get("guided_complete") is True
    assert n["i"] < 400
