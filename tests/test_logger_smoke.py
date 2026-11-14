"""Run the logger loop against a fake pygame, to catch mistakes without a real controller."""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from padlab.logfile import read_log  # noqa: E402


class Ev:
    def __init__(self, type, **kw):
        self.type = type
        self.__dict__.update(kw)


def make_fake_pygame(script, mapped=True):
    pg = types.ModuleType("pygame")
    for i, name in enumerate([
        "CONTROLLERAXISMOTION", "CONTROLLERBUTTONDOWN", "CONTROLLERBUTTONUP",
        "JOYAXISMOTION", "JOYBUTTONDOWN", "JOYBUTTONUP", "JOYHATMOTION",
        "JOYDEVICEADDED", "JOYDEVICEREMOVED",
    ]):
        setattr(pg, name, 1000 + i)

    class Joystick:
        def __init__(self, i): self.i = i
        def get_instance_id(self): return 7
        def get_name(self): return "Fake Pad"
        def get_guid(self): return "abc"
        def get_numaxes(self): return 6
        def get_numbuttons(self): return 15
        def get_numhats(self): return 1
        def get_axis(self, i): return 0.0

    pg.joystick = types.SimpleNamespace(Joystick=Joystick, init=lambda: None, get_count=lambda: 1)
    calls = {"n": 0}

    def get():
        calls["n"] += 1
        if calls["n"] <= len(script):
            return script[calls["n"] - 1](pg)
        raise KeyboardInterrupt

    pg.event = types.SimpleNamespace(get=get, pump=lambda: None)
    pg.init = lambda: None
    pg.quit = lambda: None
    pg.get_sdl_version = lambda: (2, 30, 0)

    ctrl = types.ModuleType("pygame._sdl2.controller")
    ctrl.init = lambda: None
    ctrl.is_controller = lambda i: mapped
    start_axes = {0: 120, 1: -80, 2: 0, 3: 0, 4: 0, 5: 0}
    ctrl.Controller = lambda i: types.SimpleNamespace(get_axis=lambda a: start_axes[a])
    sdl2 = types.ModuleType("pygame._sdl2")
    sdl2.controller = ctrl
    pg._sdl2 = sdl2
    return pg, sdl2, ctrl


def run_with(monkeypatch, tmp_path, script, mapped=True):
    pg, sdl2, ctrl = make_fake_pygame(script, mapped)
    monkeypatch.setitem(sys.modules, "pygame", pg)
    monkeypatch.setitem(sys.modules, "pygame._sdl2", sdl2)
    monkeypatch.setitem(sys.modules, "pygame._sdl2.controller", ctrl)
    from padlab import logger
    monkeypatch.setattr(logger, "POLL_SLEEP_S", 0)
    return read_log(logger.run(str(tmp_path), 0))


def test_mapped_controller(monkeypatch, tmp_path):
    script = [
        lambda pg: [Ev(pg.CONTROLLERAXISMOTION, instance_id=7, axis=0, value=1234)],
        lambda pg: [Ev(pg.CONTROLLERBUTTONDOWN, instance_id=7, button=11),
                    Ev(pg.CONTROLLERBUTTONDOWN, instance_id=7, button=13)],
        lambda pg: [Ev(pg.CONTROLLERBUTTONUP, instance_id=7, button=11),
                    Ev(pg.CONTROLLERAXISMOTION, instance_id=99, axis=0, value=5)],  # other pad: ignored
        lambda pg: [Ev(pg.JOYAXISMOTION, instance_id=7, axis=0, value=0.5)],  # mapped: joystick events ignored
        lambda pg: [Ev(pg.JOYDEVICEREMOVED, instance_id=7)],
        lambda pg: [Ev(pg.JOYDEVICEADDED, device_index=0)],
    ]
    log = run_with(monkeypatch, tmp_path, script)
    rows = [(e.kind, e.name, e.value) for e in log.events]
    # Start values at t=0 (SDL sends no event for a stick that does not move).
    start = [("a", n, v) for n, v in (("lx", 120), ("ly", -80), ("rx", 0), ("ry", 0), ("lt", 0), ("rt", 0))]
    assert rows[:6] == start and all(e.t == 0.0 for e in log.events[:6])
    rows = rows[6:]
    assert rows == [("a", "lx", 1234), ("b", "up", 1), ("b", "left", 1), ("b", "up", 0), ("c", "pad", 0), ("c", "pad", 1)]
    assert log.meta["device"] == "Fake Pad" and log.meta["mode"] == "controller"
    assert "ended_ms" in log.meta


def test_unmapped_joystick_hat(monkeypatch, tmp_path):
    script = [
        lambda pg: [Ev(pg.JOYHATMOTION, instance_id=7, hat=0, value=(-1, 1))],
        lambda pg: [Ev(pg.JOYHATMOTION, instance_id=7, hat=0, value=(0, 1))],
        lambda pg: [Ev(pg.JOYAXISMOTION, instance_id=7, axis=1, value=-1.0)],
    ]
    log = run_with(monkeypatch, tmp_path, script, mapped=False)
    rows = [(e.kind, e.name, e.value) for e in log.events]
    assert rows[:6] == [("a", n, 0) for n in ("lx", "ly", "rx", "ry", "j4", "j5")]
    rows = rows[6:]
    assert rows == [("b", "left", 1), ("b", "up", 1), ("b", "left", 0), ("a", "ly", -32767)]
    assert log.meta["mode"] == "joystick"
