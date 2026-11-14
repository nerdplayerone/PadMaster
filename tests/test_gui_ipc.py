"""Tests for the GUI helpers and the logger --ipc protocol (no window, no controller)."""

import io
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from padlab import gui  # noqa: E402
from padlab.logfile import read_log  # noqa: E402
from test_logger_smoke import Ev, make_fake_pygame  # noqa: E402


# ------------------------------------------------------------ helpers

def test_logger_command_python_and_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    cmd = gui.logger_command(1, "dongle", "C:/out")
    assert cmd[1:3] == ["-m", "padlab"]
    assert cmd[3:] == ["log", "--ipc", "--no-open", "--pad", "1", "--out", "C:/out", "--connection", "dongle"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    cmd = gui.logger_command(0, "Not set", "C:/out")
    assert cmd[1] == "log" and "--connection" not in cmd


def test_parse_status_ignores_other_text():
    assert gui.parse_status('{"state": "logging", "t": 3.0}\n') == {"state": "logging", "t": 3.0}
    assert gui.parse_status("Report: C:/x_report.html") is None
    assert gui.parse_status("{broken") is None
    assert gui.parse_status('{"no_state": 1}') is None


def test_parse_devices_and_label():
    out = 'pygame-ce 2.5.8\n[{"index": 0, "name": "Pad A", "mapped": true, "guid": "x"}]\n'
    devs = gui.parse_devices(out)
    assert devs[0]["name"] == "Pad A"
    assert gui.device_label(devs[0]) == "[0] Pad A"
    assert gui.device_label({"index": 1, "name": "Odd", "mapped": False}) == "[1] Odd (not mapped)"
    assert gui.parse_devices("nothing") == []


def test_countdown_and_elapsed():
    assert gui.countdown_text(0) == ("Put the controller down. Do not touch it. 10", True)
    assert gui.countdown_text(9.5)[1] is True
    assert gui.countdown_text(10) == ("Logging. Play your game.", False)
    assert gui.elapsed(65) == "1:05" and gui.elapsed(3725) == "1:02:05"


def test_gui_text_has_no_em_dash():
    src = open(gui.__file__, encoding="utf-8").read()
    assert "\u2014" not in src


# ------------------------------------------------------------ logger --ipc

def _run_ipc(monkeypatch, tmp_path, capsys, script, stop):
    pg, sdl2, ctrl = make_fake_pygame(script)
    monkeypatch.setitem(sys.modules, "pygame", pg)
    monkeypatch.setitem(sys.modules, "pygame._sdl2", sdl2)
    monkeypatch.setitem(sys.modules, "pygame._sdl2.controller", ctrl)
    from padlab import logger
    monkeypatch.setattr(logger, "POLL_SLEEP_S", 0)
    monkeypatch.setattr(logger, "IPC_STATUS_EVERY_S", 0)
    path = logger.run(str(tmp_path), 0, ipc=True, stop=stop)
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    return path, lines


def test_ipc_writes_json_status_and_stops_on_event(monkeypatch, tmp_path, capsys):
    stop = threading.Event()

    def press_then_stop(pg):
        stop.set()
        return [Ev(pg.CONTROLLERBUTTONDOWN, instance_id=7, button=0)]

    script = [lambda pg: [Ev(pg.CONTROLLERAXISMOTION, instance_id=7, axis=0, value=500)], press_then_stop]
    path, lines = _run_ipc(monkeypatch, tmp_path, capsys, script, stop)
    states = [x["state"] for x in lines]
    assert states[0] == "waiting" and "logging" in states
    first = next(x for x in lines if x["state"] == "logging")
    assert first["device"] == "Fake Pad" and first["log"] == path
    assert max(x.get("inputs", 0) for x in lines) >= 1
    log = read_log(path)
    assert ("b", "a", 1) in [(e.kind, e.name, e.value) for e in log.events]
    assert "ended_ms" in log.meta


def test_ipc_mode_prints_no_console_text(monkeypatch, tmp_path, capsys):
    stop = threading.Event()
    script = [lambda pg: (stop.set(), [])[1]]
    _, _ = _run_ipc(monkeypatch, tmp_path, capsys, script, stop)
    # capsys was read inside _run_ipc; run again to check every line is JSON
    stop2 = threading.Event()
    script2 = [lambda pg: (stop2.set(), [])[1]]
    pg, sdl2, ctrl = make_fake_pygame(script2)
    monkeypatch.setitem(sys.modules, "pygame", pg)
    monkeypatch.setitem(sys.modules, "pygame._sdl2", sdl2)
    monkeypatch.setitem(sys.modules, "pygame._sdl2.controller", ctrl)
    from padlab import logger
    logger.run(str(tmp_path), 0, ipc=True, stop=stop2)
    out = capsys.readouterr().out
    assert out.strip() and all(line.startswith("{") for line in out.splitlines())


def test_stdin_watcher_stops_on_stop_line_and_on_eof(monkeypatch):
    from padlab.logger import stdin_stop_watcher
    for text in ("hello\nstop\n", ""):
        monkeypatch.setattr(sys, "stdin", io.StringIO(text))
        ev = threading.Event()
        stdin_stop_watcher(ev).join(timeout=2)
        assert ev.is_set()


def test_run_ipc_reports_done(monkeypatch, tmp_path, capsys):
    from padlab import cli
    import padlab.logger as logger

    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(logger, "run", lambda *a, **k: str(tmp_path / "x.csv.gz"))
    monkeypatch.setattr(cli, "make_report", lambda p, open_it=True: p.replace(".csv.gz", "_report.html"))
    assert cli.main(["log", "--ipc", "--out", str(tmp_path)]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    assert lines[-1]["state"] == "done" and lines[-1]["report"].endswith("x_report.html")


def test_run_ipc_reports_error(monkeypatch, tmp_path, capsys):
    from padlab import cli
    import padlab.logger as logger

    def boom(*a, **k):
        raise RuntimeError("no SDL")

    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(logger, "run", boom)
    assert cli.main(["log", "--ipc", "--out", str(tmp_path)]) == 1
    last = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert last == {"state": "error", "message": "RuntimeError: no SDL"}
