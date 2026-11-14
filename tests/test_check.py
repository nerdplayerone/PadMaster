"""Run 'padlab check' against the fake pygame from test_logger_smoke.py."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_logger_smoke import Ev, make_fake_pygame  # noqa: E402


def run_check(monkeypatch, script, times, mapped=True):
    """``times[i]`` is the clock value after event batch i."""
    pg, sdl2, ctrl = make_fake_pygame(script, mapped)
    monkeypatch.setitem(sys.modules, "pygame", pg)
    monkeypatch.setitem(sys.modules, "pygame._sdl2", sdl2)
    monkeypatch.setitem(sys.modules, "pygame._sdl2.controller", ctrl)
    from padlab import logger
    monkeypatch.setattr(logger, "POLL_SLEEP_S", 0)

    clock_vals = iter([0.0] + list(times) + [times[-1]] * 10)
    lines = []
    logger.check(0, out=lines.append, clock=lambda: next(clock_vals))
    body = lines[lines.index("  Press Ctrl+C to stop.\n") + 1:-1]
    return body


def test_check_buttons_and_throttled_axes(monkeypatch):
    A = 1000  # CONTROLLERAXISMOTION in the fake module
    script = [
        lambda pg: [Ev(pg.CONTROLLERBUTTONDOWN, instance_id=7, button=0)],
        lambda pg: [Ev(pg.CONTROLLERBUTTONUP, instance_id=7, button=0)],
        # 0.00 s: first axis value prints at once.
        lambda pg: [Ev(A, instance_id=7, axis=0, value=14090)],
        # 0.03 s: too soon after the last line. Kept pending.
        lambda pg: [Ev(A, instance_id=7, axis=0, value=16384)],
        # 0.15 s: interval passed. Newest pending value prints.
        lambda pg: [],
        # 0.30 s: change below 2%. Not printed.
        lambda pg: [Ev(A, instance_id=7, axis=0, value=16500)],
        # Other pad: ignored.
        lambda pg: [Ev(A, instance_id=99, axis=1, value=30000)],
        # Trigger and D-pad.
        lambda pg: [Ev(A, instance_id=7, axis=5, value=32767),
                    Ev(pg.CONTROLLERBUTTONDOWN, instance_id=7, button=11)],
        lambda pg: [Ev(pg.JOYDEVICEREMOVED, instance_id=7)],
    ]
    times = [0.0, 0.0, 0.0, 0.03, 0.15, 0.30, 0.40, 0.50, 0.60]
    body = run_check(monkeypatch, script, times)
    assert body == [
        "button a down",
        "button a up",
        "axis lx 0.43",
        "axis lx 0.50",
        "button up down",
        "axis rt 1.00",
        "controller lost",
    ]


def test_check_no_false_connected_at_start(monkeypatch):
    # Real SDL sends JOYDEVICEADDED at start for a pad that is already there.
    script = [
        lambda pg: [Ev(pg.JOYDEVICEADDED, device_index=0)],
        lambda pg: [Ev(pg.JOYDEVICEREMOVED, instance_id=7)],
        lambda pg: [Ev(pg.JOYDEVICEADDED, device_index=0)],
    ]
    body = run_check(monkeypatch, script, [0.0, 0.1, 0.2])
    assert body == ["controller lost", "controller connected"]


def test_check_unmapped_pad(monkeypatch):
    script = [
        lambda pg: [Ev(pg.JOYBUTTONDOWN, instance_id=7, button=3)],
        lambda pg: [Ev(pg.JOYHATMOTION, instance_id=7, hat=0, value=(1, 0))],
        lambda pg: [Ev(pg.JOYAXISMOTION, instance_id=7, axis=1, value=-1.0)],
    ]
    body = run_check(monkeypatch, script, [0.0, 0.1, 0.2], mapped=False)
    assert body == ["button jb3 down", "button right down", "axis ly -1.00"]
