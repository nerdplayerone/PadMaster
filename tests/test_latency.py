"""Gamepadla latency lookup: name matching, the owner's choice, the credited report box."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402

from padlab import latency  # noqa: E402
from padlab.logfile import LogWriter  # noqa: E402

XBOX = "https://gamepadla.com/xbox-core-controller.html"
DATA = {
    "source": "Gamepadla.com", "collected": "2026-11-14",
    "controllers": [
        {"name": "Microsoft Xbox Series Controller", "url": XBOX,
         "results": [{"connection": "Dongle", "mode": "XInput", "button_ms": 7.21, "stick_ms": 8.88,
                      "polling_hz": 124.69, "primary": True}]},
        {"name": "Sony DualSense", "url": "https://gamepadla.com/sony-dualsense.html",
         "results": [{"connection": "Cable", "mode": "DInput", "button_ms": 4.0, "stick_ms": 4.5,
                      "polling_hz": 250.0, "primary": True}]},
        {"name": "8BitDo Ultimate 2 Bluetooth", "url": "https://gamepadla.com/8bitdo-ultimate-2-bluetooth-controller.html",
         "results": []},
    ],
}


@pytest.fixture(autouse=True)
def fake_data(monkeypatch):
    monkeypatch.setattr(latency, "_cache", DATA)


def test_close_name_matches_without_a_question():
    res = latency.resolve({"label": "Xbox Series controller"}, {})
    assert res["state"] == "auto" and res["entry"]["url"] == XBOX


def test_typo_asks_with_the_right_suggestion_first():
    res = latency.resolve({"label": "xbx seris"}, {})
    assert res["state"] == "ask" and res["entry"] is None
    assert res["suggest"][0]["url"] == XBOX


def test_owner_choice_wins_and_none_means_no_data():
    meta = {"label": "My odd pad"}
    key = "label:My odd pad"
    assert latency.resolve(meta, {key: XBOX})["entry"]["url"] == XBOX
    assert latency.resolve(meta, {key: "none"})["state"] == "none"


def test_report_box_gives_credit_link_and_small_print():
    from padlab.analysis import analyse
    from padlab.logfile import read_log
    from padlab.report import render
    from synth import build
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "padlab_20260101_100000.csv.gz")
        build(p)
        rep = analyse(read_log(p))
        html = render(rep, "x", latency=DATA["controllers"][0], latency_date="2026-11-14")
        assert "Hardware latency (data: Gamepadla.com)" in html
        assert f"href='{XBOX}'" in html and "Full credit to Gamepadla" in html
        assert "Gamepadla may have newer results" in html and "2026-11-14" in html
        assert "7.21 ms" in html and "—" not in html  # no em dashes
        assert "Hardware latency" not in render(rep, "x")


def _log(tmp_path, label):
    p = tmp_path / "padlab_20261114_100000.csv.gz"
    w = LogWriter(str(p), {"device": "Xbox One Controller", "guid": "aaa", "label": label})
    w.write(0.0, "b", "a", 1)
    w.meta({"ended_ms": 1000.0})
    w.close()
    return p.name


def test_app_asks_then_saves_choice_and_report_shows_it(tmp_path):
    from padlab.gui import Api
    api = Api(str(tmp_path))
    log = _log(tmp_path, "xbx seris")
    st = api.latency_status(log)
    assert st["state"] == "ask" and st["suggest"][0]["url"] == XBOX
    assert "Hardware latency" not in api.report_html(log)["html"]
    res = api.latency_choose(log, XBOX)
    assert res["ok"] and "Hardware latency (data: Gamepadla.com)" in res["html"]
    assert api.latency_status(log)["state"] == "chosen"
    assert not api.latency_choose(log, "https://example.com/x")["ok"]
    res = api.latency_choose(log, "none")
    assert "Hardware latency" not in res["html"] and api.latency_status(log)["state"] == "none"


def test_links_open_only_owner_channels_and_gamepadla_pages(monkeypatch, tmp_path):
    import webbrowser
    from padlab.gui import Api
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda u: opened.append(u))
    api = Api(str(tmp_path))
    assert api.open_link(XBOX) and api.open_link("https://gamepadla.com")
    assert not api.open_link("https://gamepadla.com/admin") and not api.open_link("https://evil.example/")
    assert opened == [XBOX, "https://gamepadla.com"]


def test_two_near_equal_models_ask_instead_of_guessing(monkeypatch):
    data = {"controllers": [
        {"name": "Microsoft Xbox Series Controller", "url": "a", "results": []},
        {"name": "Microsoft Xbox Series Elite Controller", "url": "b", "results": []}]}
    monkeypatch.setattr(latency, "_cache", data)
    assert latency.resolve({"label": "Xbox Series"}, {})["state"] in ("ask", "auto")
    assert latency.resolve({"label": "Xbox"}, {})["state"] == "ask"
