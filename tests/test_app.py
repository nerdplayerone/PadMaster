"""App window back end: IPC logger mode, session history, and the Api class (no window)."""

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from synth import build  # noqa: E402
from test_logger_smoke import Ev, make_fake_pygame  # noqa: E402

from padlab.logfile import read_log  # noqa: E402


def _install_fake(monkeypatch, script):
    pg, sdl2, ctrl = make_fake_pygame(script)
    monkeypatch.setitem(sys.modules, "pygame", pg)
    monkeypatch.setitem(sys.modules, "pygame._sdl2", sdl2)
    monkeypatch.setitem(sys.modules, "pygame._sdl2.controller", ctrl)
    from padlab import logger
    monkeypatch.setattr(logger, "POLL_SLEEP_S", 0)
    return logger


def test_ipc_mode_prints_only_json_and_stops_on_flag(monkeypatch, tmp_path, capsys):
    flag = {"stop": False}

    def press(pg):
        return [Ev(pg.CONTROLLERBUTTONDOWN, instance_id=7, button=0)]

    def ask_stop(pg):
        flag["stop"] = True
        return []

    logger = _install_fake(monkeypatch, [press, ask_stop])
    path = logger.run(str(tmp_path), 0, ipc=True, stop_flag=flag)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    msgs = [json.loads(ln) for ln in lines]  # every line is JSON
    assert msgs[0]["state"] == "logging" and msgs[0]["device"] == "Fake Pad"
    rows = [(e.kind, e.name, e.value) for e in read_log(path).events if e.kind == "b"]
    assert rows == [("b", "a", 1)]


def test_stdin_watcher_sets_flag_on_stop_line():
    import time
    from padlab.logger import stdin_stop_watcher
    flag = {"stop": False}
    stdin_stop_watcher(flag, io.StringIO("hello\nstop\n"))
    for _ in range(100):
        if flag["stop"]:
            break
        time.sleep(0.01)
    assert flag["stop"]


def test_history_index_and_export(tmp_path):
    from padlab.history import export_csv, update_index
    build(str(tmp_path / "padlab_20260101_100000.csv.gz"))
    (tmp_path / "padlab_20260102_100000.csv.gz").write_bytes(b"not a gzip file")
    rows = update_index(str(tmp_path))
    assert len(rows) == 2
    good = [r for r in rows if r["device"] != "Unreadable log"][0]
    assert good["inputs"] > 0 and good["problem"] + good["watch"] + good["ok"] > 0
    assert (tmp_path / "history.json").exists()
    # A lost cache is made again from the logs.
    (tmp_path / "history.json").write_text("{broken", encoding="utf-8")
    assert len(update_index(str(tmp_path))) == 2
    n = export_csv(str(tmp_path), str(tmp_path / "h.csv"))
    text = (tmp_path / "h.csv").read_text(encoding="utf-8").splitlines()
    assert n == 2 and text[0].startswith("started,device") and len(text) == 3


class FakeProc:
    def __init__(self, lines):
        self.stdout = iter(lines)
        self.stderr = iter([])
        self.stdin = io.StringIO()
        self._done = False

    def poll(self):
        return 0 if self._done else None

    def wait(self, timeout=None):
        self._done = True
        return 0


def test_api_start_reads_status_and_done(tmp_path):
    import time
    from padlab.gui import Api
    lines = [json.dumps({"state": "logging", "t": 1.0, "inputs": 5, "disconnects": 0}) + "\n",
             "not json\n",
             json.dumps({"state": "done", "report": "r.html", "log": "x.csv.gz"}) + "\n"]
    seen = {}

    def popen(cmd, **kw):
        seen["cmd"] = cmd
        return FakeProc(lines)

    api = Api(str(tmp_path), popen=popen)
    assert api.start(1)["ok"]
    assert "--ipc" in seen["cmd"] and seen["cmd"][seen["cmd"].index("--pad") + 1] == "1"
    for _ in range(100):
        if api.status()["state"] == "done":
            break
        time.sleep(0.01)
    assert api.status()["state"] == "done" and api.status()["log"] == "x.csv.gz"


def test_api_logger_exit_without_report_is_an_error(tmp_path):
    import time
    from padlab.gui import Api
    api = Api(str(tmp_path), popen=lambda cmd, **kw: FakeProc([]))
    api.start(0)
    for _ in range(100):
        if api.status()["state"] == "error":
            break
        time.sleep(0.01)
    assert api.status()["state"] == "error"


def test_api_report_html_only_reads_logs_folder(tmp_path):
    from padlab.gui import Api
    build(str(tmp_path / "padlab_20260101_100000.csv.gz"))
    api = Api(str(tmp_path))
    res = api.report_html("padlab_20260101_100000.csv.gz")
    assert res["ok"] and "<html" in res["html"] and os.path.isfile(res["path"])
    assert not api.report_html("..\\..\\secret.csv.gz")["ok"]


def test_window_geometry_fits_and_centres():
    from padlab.gui import window_geometry
    for sw, sh in ((1920, 1080), (3072, 1728), (1280, 720), (800, 500)):
        w, h, x, y = window_geometry(sw, sh)
        assert w <= sw and h <= sh and x >= 0 and y >= 0
        assert abs((sw - w) - 2 * x) <= 1 and abs((sh - h) - 2 * y) <= 1  # centred
    assert window_geometry(3072, 1728)[:2] == (2764, 1520)


def test_one_scrollbar_style_everywhere(tmp_path):
    """Owner request (2026-11-14): every scroll bar uses the same minimal style."""
    import glob
    from padlab.gui import Api
    from padlab.theme import SCROLLBAR_CSS, SCROLLBAR_MARKER
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "padlab")
    # Scroll bar rules live only in theme.py.
    for f in glob.glob(os.path.join(root, "*.py")) + glob.glob(os.path.join(root, "*.html")):
        if os.path.basename(f) != "theme.py":
            assert "-webkit-scrollbar" not in open(f, encoding="utf-8").read(), f
    assert SCROLLBAR_MARKER in open(os.path.join(root, "app.html"), encoding="utf-8").read()
    # New reports carry the style.
    log = str(tmp_path / "padlab_20260101_100000.csv.gz")
    build(log)
    res = Api(str(tmp_path)).report_html(os.path.basename(log))
    assert SCROLLBAR_CSS in res["html"]
    # A report made by an older version (no style) gets it when the app shows it.
    with open(res["path"], "w", encoding="utf-8") as fh:
        fh.write("<html><head><style>body{}</style></head><body>old</body></html>")
    os.utime(res["path"], (2e9, 2e9))  # newer than the log, so it is not made again
    assert SCROLLBAR_CSS in Api(str(tmp_path)).report_html(os.path.basename(log))["html"]


def test_old_reports_are_made_again_when_checks_change(tmp_path):
    from padlab.analysis import ANALYSIS_VERSION
    from padlab.gui import Api
    log = str(tmp_path / "padlab_20260101_100000.csv.gz")
    build(log)
    res = Api(str(tmp_path)).report_html(os.path.basename(log))
    assert f'content="{ANALYSIS_VERSION}"' in res["html"]
    with open(res["path"], "w", encoding="utf-8") as fh:  # a report from older checks
        fh.write('<html><head><meta name="padlab-analysis" content="1"></head><body>old</body></html>')
    os.utime(res["path"], (2e9, 2e9))
    assert "old</body>" not in Api(str(tmp_path)).report_html(os.path.basename(log))["html"]


def test_rename_session_updates_history_and_report(tmp_path):
    from padlab.gui import Api
    log = str(tmp_path / "padlab_20260101_100000.csv.gz")
    build(log)
    before = open(log, "rb").read()
    api = Api(str(tmp_path))
    res = api.rename(os.path.basename(log), "  Xbox pad   A ")
    assert res["ok"] and res["name"] == "Xbox pad A"
    row = res["history"][0]
    assert row["device"] == "Xbox pad A" and row["model"] != "Xbox pad A"
    html = api.report_html(os.path.basename(log))["html"]
    assert "<h1>Xbox pad A</h1>" in html and "Controller model:" in html
    assert open(log, "rb").read() == before  # the log is never changed
    # An empty name goes back to the model name.
    res = api.rename(os.path.basename(log), "")
    assert res["history"][0]["device"] == res["history"][0]["model"]
    assert "Controller model:" not in api.report_html(os.path.basename(log))["html"]


def test_rename_rejects_files_outside_logs_folder(tmp_path):
    from padlab.gui import Api
    assert not Api(str(tmp_path)).rename("../other.csv.gz", "x")["ok"]


def test_compare_values_match_metric_list(tmp_path):
    from padlab.analysis import METRICS, THRESHOLDS
    from padlab.gui import Api
    build(str(tmp_path / "padlab_20260101_100000.csv.gz"))
    data = Api(str(tmp_path)).compare_data()
    keys = [m["key"] for m in data["metrics"]]
    assert keys == [m["key"] for m in METRICS]
    vals = data["sessions"][0]["metrics"]
    assert set(vals) == set(keys)
    # Limit lines come from THRESHOLDS only.
    d = {m["key"]: m for m in data["metrics"]}
    assert d["l_drift"]["ok_value"] == THRESHOLDS["drift_ok"]
    assert all(v is None or isinstance(v, float) for v in vals.values())


def _tiny_log(path, guid, device="Pad"):
    from padlab.logfile import LogWriter
    w = LogWriter(str(path), {"padlab": "test", "device": device, "guid": guid,
                              "started": "2026-11-14T10:00:00"})
    w.write(0.0, "b", "a", 1)
    w.write(50.0, "b", "a", 0)
    w.meta({"ended_ms": 1000.0})
    w.close()


def test_rename_applies_to_all_sessions_of_same_model(tmp_path):
    """Owner request (2026-11-14): renaming one session renames every session of that model."""
    from padlab.gui import Api
    _tiny_log(tmp_path / "padlab_20261114_100000.csv.gz", "aaa")
    _tiny_log(tmp_path / "padlab_20261114_110000.csv.gz", "aaa")
    _tiny_log(tmp_path / "padlab_20261114_120000.csv.gz", "bbb")
    api = Api(str(tmp_path))
    rows = api.rename("padlab_20261114_100000.csv.gz", "Pad A")["history"]
    names = {r["log_file"]: r["device"] for r in rows}
    assert names["padlab_20261114_100000.csv.gz"] == "Pad A"
    assert names["padlab_20261114_110000.csv.gz"] == "Pad A"
    assert names["padlab_20261114_120000.csv.gz"] == "Pad"  # other model not changed
    # A new log from the same model gets the name too.
    _tiny_log(tmp_path / "padlab_20261114_130000.csv.gz", "aaa")
    names = {r["log_file"]: r["device"] for r in api.history()}
    assert names["padlab_20261114_130000.csv.gz"] == "Pad A"
    # The report of the other session also shows the name when it opens.
    assert "<h1>Pad A</h1>" in api.report_html("padlab_20261114_110000.csv.gz")["html"]


def test_pad_name_groups_sessions_and_is_remembered(tmp_path):
    """Owner request (2026-11-14): name the physical pad at start; default to the last name."""
    from padlab.gui import Api
    from padlab.logfile import LogWriter
    seen = {}

    def popen(cmd, **kw):
        seen["cmd"] = cmd
        return FakeProc([])

    api = Api(str(tmp_path), popen=popen)
    assert api.start(0, "  Xbox pad  B ")["ok"]
    assert seen["cmd"][seen["cmd"].index("--name") + 1] == "Xbox pad B"
    assert api.pad_names()["last"] == "Xbox pad B"
    # Two pads of the same model (same GUID) stay apart when they have names.
    for stamp, label in (("100000", "Xbox pad A"), ("110000", "Xbox pad B"), ("120000", "Xbox pad B")):
        w = LogWriter(str(tmp_path / f"padlab_20261114_{stamp}.csv.gz"),
                      {"device": "Pad", "guid": "aaa", "label": label, "started": "2026-11-14T" + stamp})
        w.write(0.0, "b", "a", 1)
        w.meta({"ended_ms": 1000.0})
        w.close()
    names = {r["log_file"][16:22]: r["device"] for r in api.history()}
    assert names == {"100000": "Xbox pad A", "110000": "Xbox pad B", "120000": "Xbox pad B"}
    assert api.pad_names()["names"] == ["Xbox pad A", "Xbox pad B"]
    # Renaming pad B renames only pad B, and the default follows the new name.
    rows = api.rename("padlab_20261114_110000.csv.gz", "Pad B (worn)")["history"]
    names = {r["log_file"][16:22]: r["device"] for r in rows}
    assert names == {"100000": "Xbox pad A", "110000": "Pad B (worn)", "120000": "Pad B (worn)"}
    assert api.pad_names()["last"] == "Pad B (worn)"


def test_logger_writes_pad_name_to_metadata(monkeypatch, tmp_path):
    flag = {"stop": False}

    def ask_stop(pg):
        flag["stop"] = True
        return []

    logger = _install_fake(monkeypatch, [ask_stop])
    path = logger.run(str(tmp_path), 0, ipc=True, stop_flag=flag, label="Xbox pad A")
    assert read_log(path).meta["label"] == "Xbox pad A"


def test_connection_is_recorded_and_remembered(monkeypatch, tmp_path):
    """Owner request (2026-11-14): select Wired, Dongle or Bluetooth at Start."""
    from padlab.gui import Api
    seen = {}
    api = Api(str(tmp_path), popen=lambda cmd, **kw: seen.setdefault("cmd", cmd) and FakeProc([]))
    assert api.start(0, "Pad A", "Bluetooth")["ok"]
    assert seen["cmd"][seen["cmd"].index("--connection") + 1] == "Bluetooth"
    assert api.pad_names()["last_connection"] == "Bluetooth"
    api2 = Api(str(tmp_path), popen=lambda cmd, **kw: FakeProc([]))
    api2.start(0, "Pad A", "Laser")  # unknown values are not passed on
    assert api2.pad_names()["last_connection"] == ""


def test_logger_writes_connection_and_report_shows_it(monkeypatch, tmp_path):
    flag = {"stop": False}

    def ask_stop(pg):
        flag["stop"] = True
        return []

    logger = _install_fake(monkeypatch, [ask_stop])
    path = logger.run(str(tmp_path), 0, ipc=True, stop_flag=flag, connection="Dongle")
    assert read_log(path).meta["connection"] == "Dongle"
    from padlab.gui import Api
    api = Api(str(tmp_path))
    assert api.history()[0]["connection"] == "Dongle"
    assert "Connection: Dongle" in api.report_html(os.path.basename(path))["html"]


def test_channel_links_only_open_owner_channels(tmp_path, monkeypatch):
    import webbrowser
    from padlab.branding import CHANNELS
    from padlab.gui import Api
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda u: opened.append(u))
    api = Api(str(tmp_path))
    assert api.open_link(CHANNELS[0][1]) and opened == [CHANNELS[0][1]]
    assert not api.open_link("https://example.com/") and len(opened) == 1
    assert [c["url"] for c in api.init()["channels"]] == [u for _, u in CHANNELS]


def test_report_footer_has_channel_links(tmp_path):
    from padlab.branding import CHANNELS
    from padlab.gui import Api
    build(str(tmp_path / "padlab_20260101_100000.csv.gz"))
    html = Api(str(tmp_path)).report_html("padlab_20260101_100000.csv.gz")["html"]
    assert all(f'href="{u}"' in html for _, u in CHANNELS)


def test_delete_moves_sessions_to_deleted_folder_and_keeps_files(tmp_path):
    """Owner request (2026-11-17): delete and bulk delete in History. Files move, not erase."""
    from padlab.gui import Api
    from padlab.logfile import LogWriter
    names = []
    for i in range(3):
        p = tmp_path / f"padlab_2026111{i}_100000.csv.gz"
        w = LogWriter(str(p), {"device": "Pad", "guid": "g"})
        w.write(0.0, "b", "a", 1); w.meta({"ended_ms": 1000.0}); w.close()
        names.append(p.name)
    (tmp_path / names[0].replace(".csv.gz", "_report.html")).write_text("x")
    api = Api(str(tmp_path))
    assert len(api.history()) == 3
    res = api.delete_sessions([names[0], names[1], "../evil.csv.gz", "notes.txt"])
    assert res["moved"] == 2 and [r["log_file"] for r in res["history"]] == [names[2]]
    gone = tmp_path / "Deleted"
    assert (gone / names[0]).is_file() and (gone / names[1]).is_file()
    assert (gone / names[0].replace(".csv.gz", "_report.html")).is_file()



def test_check_update_compares_versions_and_handles_no_internet(tmp_path):
    from padlab import __version__
    from padlab.gui import Api
    api = Api(str(tmp_path))
    rel = "https://github.com/nerdplayerone/PadMaster/releases/tag/v99.0.0"
    new = api.check_update(fetch=lambda: {"tag_name": "v99.0.0", "html_url": rel})
    assert new["state"] == "update" and new["latest"] == "99.0.0" and new["url"] == rel
    assert api.check_update(fetch=lambda: {"tag_name": "v" + __version__})["state"] == "latest"
    evil = api.check_update(fetch=lambda: {"tag_name": "v99", "html_url": "https://evil.example/"})
    assert evil["url"] == "https://github.com/nerdplayerone/PadMaster/releases"

    def offline():
        raise OSError("no network")
    assert api.check_update(fetch=offline)["state"] == "error"


def test_auto_update_check_runs_once_a_day_and_can_be_turned_off(tmp_path):
    from padlab.gui import Api
    api = Api(str(tmp_path))
    calls = []
    fetch = lambda: calls.append(1) or {"tag_name": "v0.0.1"}
    assert api.check_update(auto=True, fetch=fetch)["state"] == "latest"
    assert api.check_update(auto=True, fetch=fetch)["state"] == "skipped" and len(calls) == 1
    api.set_auto_update(False)
    assert api.init()["auto_update"] is False
    assert api.check_update(auto=True, fetch=fetch)["state"] == "off" and len(calls) == 1
    assert api.check_update(fetch=fetch)["state"] == "latest"  # the button still works


def test_report_bug_opens_a_draft_and_sends_nothing(monkeypatch, tmp_path):
    import webbrowser
    from padlab import branding
    from padlab.gui import Api
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda u: opened.append(u))
    api = Api(str(tmp_path))
    monkeypatch.setattr(branding, "BUG_EMAIL", "")
    assert not api.report_bug("Pad A")["email"]
    assert opened[-1].startswith("https://github.com/nerdplayerone/PadMaster/issues/new?title=")
    monkeypatch.setattr(branding, "BUG_EMAIL", "bugs@example.com")
    assert api.report_bug("Pad A")["email"]
    assert opened[-1].startswith("mailto:bugs@example.com?subject=") and "Pad%20A" in opened[-1]



def test_controller_mapping_file_is_bundled_and_used():
    """Owner approval (2026-11-18): bundle SDL_GameControllerDB so more pads are mapped."""
    import os
    from padlab import logger
    assert os.path.isfile(logger.MAPPING_FILE)
    txt = open(logger.MAPPING_FILE, encoding="utf-8").read()
    assert "provided 'as-is'" in txt
    rows = [x for x in txt.splitlines() if x and not x.startswith("#")]
    assert len(rows) > 500 and all("platform:Windows" in x for x in rows)
    assert os.environ.get("SDL_GAMECONTROLLERCONFIG_FILE")
    root = os.path.dirname(os.path.dirname(logger.MAPPING_FILE))
    wf = open(os.path.join(root, ".github", "workflows", "build.yml"), encoding="utf-8").read()
    assert wf.count("gamecontrollerdb.txt:padlab") == 2



def test_stop_analyses_the_log_only_once(monkeypatch, tmp_path):
    """User report (2026-11-19): the report takes a long time after long sessions.
    One cause: the log was read and analysed again for History, and read a third time."""
    import os
    from padlab import analysis, cli, history, logfile
    from tests.synth import build
    path = os.path.join(str(tmp_path), "padlab_20261119_100000.csv.gz")
    build(path)
    calls = {"read": 0, "analyse": 0}
    real_read, real_an = logfile.read_log, analysis.analyse

    def read(p):
        calls["read"] += 1
        return real_read(p)

    def an(log):
        calls["analyse"] += 1
        return real_an(log)
    for mod in (cli, history):
        monkeypatch.setattr(mod, "read_log", read, raising=False)
        monkeypatch.setattr(mod, "analyse", an, raising=False)
    monkeypatch.setattr(logfile, "read_log", read)
    monkeypatch.setattr(analysis, "analyse", an)
    done: dict = {}
    cli.make_report(path, open_it=False, quiet=True, keep=done)
    rows = history.update_index(str(tmp_path), known={path: done["rep"]})
    assert calls == {"read": 1, "analyse": 1}
    assert rows and rows[0]["log_file"] == os.path.basename(path) and rows[0]["metrics"]


def test_stick_analysis_is_fast_on_long_sessions():
    """User report (2026-11-19). 300,000 stick samples must take well under 3 s."""
    import math
    import time
    from padlab.analysis import analyse_stick
    from padlab.logfile import Event, Log
    ev, t = [], 0.0
    for i in range(300_000):
        a = i / 200
        ev.append(Event(t, "a", "lx", int(math.cos(a) * 30000)))
        ev.append(Event(t, "a", "ly", int(math.sin(a) * 30000)))
        t += 4
    log = Log(meta={"device": "Pad"}, events=ev)
    s = time.perf_counter()
    res = analyse_stick(log, "l")
    assert res["enough"] and time.perf_counter() - s < 3.0


def test_opening_a_report_does_not_read_the_whole_log(monkeypatch, tmp_path):
    """User report (2026-11-22): the report is slow after long sessions. Opening the report
    and the latency question read the whole log again only for its name."""
    import os
    from padlab import cli, logfile
    from padlab.gui import Api
    from tests.synth import build
    path = os.path.join(str(tmp_path), "padlab_20261122_100000.csv.gz")
    build(path)
    cli.make_report(path, open_it=False, quiet=True)
    calls = []
    real = logfile.read_log
    monkeypatch.setattr(logfile, "read_log", lambda p: calls.append(p) or real(p))
    api = Api(str(tmp_path))
    assert api.report_html(os.path.basename(path))["ok"]
    assert api.latency_status(os.path.basename(path))["ok"]
    assert calls == []
    assert logfile.read_header(path).get("device")


def test_ipc_stop_uses_the_live_analysis(monkeypatch, tmp_path):
    """At Stop the logger's live analysis is used: the long log is not read again."""
    import os
    from padlab import cli, logfile, logger
    from tests.test_analysis import _replay_live
    from tests.synth import build
    src = os.path.join(str(tmp_path), "src.csv.gz")
    build(src)
    path = os.path.join(str(tmp_path), "padlab_20261122_110000.csv.gz")
    live = _replay_live(src, path)
    monkeypatch.setattr(logger, "last_live", live)
    monkeypatch.setattr(logger, "run", lambda *a, **k: path)
    reads = []
    real = logfile.read_log
    monkeypatch.setattr(logfile, "read_log", lambda p: reads.append(p) or real(p))
    monkeypatch.setattr(cli, "read_log", lambda p: reads.append(p) or real(p), raising=False)
    out = []
    monkeypatch.setattr(logger, "emit", lambda d: out.append(d))
    cli.main(["log", "--ipc", "--out", str(tmp_path)])
    assert out[-1]["state"] == "done" and out[-1]["report"]
    assert path not in reads


def test_app_passes_trigger_stops_to_the_logger(tmp_path):
    from padlab.gui import Api
    seen = {}

    def popen(cmd, **k):
        seen["cmd"] = cmd
        raise OSError("not started in the test")
    Api(str(tmp_path), popen=popen).start(0, "Pad", "Wired", 0, False, False, True)
    assert "--trigger-stops" in seen["cmd"]


def test_app_has_chart_tab_coloured_best_bars_and_loader():
    """Owner request (2026-11-22): a Chart tab, OK/Watch/Problem colours in Best controller,
    and a loading animation that respects reduced motion."""
    import pathlib
    h = (pathlib.Path(__file__).parent.parent / "padlab" / "app.html").read_text(encoding="utf-8")
    assert 'id="tab-chart"' in h and "async function renderChart()" in h
    assert 'g-"+c.grades[k]' in h and ".pbar i.g-ok" in h
    assert 'loader("Making the report")' in h and ".loading .fb,.loading .da,.loading .stk-in" in h
