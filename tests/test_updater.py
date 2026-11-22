"""Update in place (owner decision, 2026-11-22): download, checksum, replace the exe."""

import hashlib
import io
import os

import pytest

from padlab import updater

GOOD = updater.DOWNLOAD_PREFIX + "v9.0.0/PadMaster.exe"


def _release(data=b"new exe", url=GOOD, digest=True):
    a = {"name": "PadMaster.exe", "browser_download_url": url, "size": len(data)}
    if digest:
        a["digest"] = "sha256:" + hashlib.sha256(data).hexdigest()
    return {"tag_name": "v9.0.0", "assets": [{"name": "PadMaster-console.exe"}, a]}


def test_pick_asset_needs_owner_release_and_checksum():
    url, size, sha = updater.pick_asset(_release())
    assert url == GOOD and size == 7 and len(sha) == 64
    with pytest.raises(updater.UpdateError):
        updater.pick_asset(_release(url="https://example.com/PadMaster.exe"))
    with pytest.raises(updater.UpdateError):
        updater.pick_asset(_release(digest=False))
    with pytest.raises(updater.UpdateError):
        updater.pick_asset({"assets": []})


def test_download_checks_the_checksum(tmp_path):
    data = b"new exe"
    _, size, sha = updater.pick_asset(_release(data))
    dest = str(tmp_path / "u.exe")
    updater.download(GOOD, dest, size, sha, opener=lambda u: io.BytesIO(data))
    assert open(dest, "rb").read() == data
    with pytest.raises(updater.UpdateError):
        updater.download(GOOD, dest, size, sha, opener=lambda u: io.BytesIO(b"bad exe"))
    assert not os.path.exists(dest)


def test_self_replace_overwrites_target_and_starts_it(tmp_path):
    new, target = tmp_path / "new.exe", tmp_path / "PadMaster.exe"
    new.write_bytes(b"v2")
    target.write_bytes(b"v1")
    started = []
    rc = updater.self_replace(str(target), me=str(new), popen=lambda a, **k: started.append(a), pause=0)
    assert rc == 0 and target.read_bytes() == b"v2"
    assert started == [[str(target), "--updated-from", str(new)]]
    assert not (tmp_path / "PadMaster.exe.new").exists()


def test_self_replace_failure_starts_the_old_app(tmp_path, monkeypatch):
    new, target = tmp_path / "new.exe", tmp_path / "PadMaster.exe"
    new.write_bytes(b"v2")
    target.write_bytes(b"v1")

    def locked(a, b):
        raise PermissionError("in use")
    monkeypatch.setattr(updater.os, "replace", locked)
    started = []
    rc = updater.self_replace(str(target), me=str(new), popen=lambda a, **k: started.append(a), tries=3, pause=0)
    assert rc == 1 and target.read_bytes() == b"v1" and started == [[str(target)]]


def test_update_now_downloads_checks_and_starts_replace(tmp_path):
    from padlab.gui import Api
    api = Api(str(tmp_path))
    got = {}
    r = api.update_now(fetch=_release, download=lambda *a: got.setdefault("dl", a),
                       start=lambda new, target: got.setdefault("start", (new, target)))
    assert r["ok"] and got["dl"][0] == GOOD and got["start"][0].endswith("PadMaster-update-9.0.0.exe")
    same = api.update_now(fetch=lambda: {"tag_name": "v0.0.1"}, start=lambda *a: None)
    assert not same["ok"] and "latest" in same["message"]


def test_cli_self_replace_dispatch(monkeypatch):
    from padlab import cli
    seen = []
    monkeypatch.setattr(updater, "self_replace", lambda t: seen.append(t) or 0)
    assert cli.main(["--self-replace", "C:/x/PadMaster.exe"]) == 0 and seen == ["C:/x/PadMaster.exe"]
