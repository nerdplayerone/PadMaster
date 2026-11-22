"""Update in place (owner decision, 2026-11-22).

On a click, the app downloads PadMaster.exe from the owner's GitHub release, checks it
against the SHA-256 checksum that GitHub publishes, and starts the new file from the
temporary folder with ``--self-replace <old exe>``. The old app closes. The new file copies
itself over the old exe (same folder, same name), starts it with ``--updated-from <temp
file>``, and the started app deletes the temporary file. No old copy stays behind.
Nothing is downloaded without a click, and no user data is sent.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

from . import branding

ASSET = "PadMaster.exe"
DOWNLOAD_PREFIX = f"https://github.com/{branding.REPO}/releases/download/"


class UpdateError(Exception):
    """Plain-English message for the user."""


def pick_asset(release: dict) -> tuple[str, int, str]:
    """(download URL, size, sha256 hex) of PadMaster.exe in a GitHub release."""
    for a in release.get("assets") or []:
        if a.get("name") != ASSET:
            continue
        url = str(a.get("browser_download_url") or "")
        digest = str(a.get("digest") or "")
        if not url.startswith(DOWNLOAD_PREFIX):
            raise UpdateError("The download address is not a PadMaster release.")
        if not digest.startswith("sha256:"):
            raise UpdateError("The release has no checksum. Download the update in your browser.")
        return url, int(a.get("size") or 0), digest.split(":", 1)[1].lower()
    raise UpdateError("The release has no PadMaster.exe. Download the update in your browser.")


def download(url: str, dest: str, size: int, sha256: str, opener=None) -> str:
    """Download to dest and check the size and the checksum. A bad file is deleted."""
    opener = opener or (lambda u: urllib.request.urlopen(
        urllib.request.Request(u, headers={"User-Agent": "PadMaster"}), timeout=30))
    h = hashlib.sha256()
    n = 0
    try:
        with opener(url) as r, open(dest, "wb") as fh:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                n += len(chunk)
    except UpdateError:
        raise
    except Exception as exc:
        _remove(dest)
        raise UpdateError("PadMaster can't download the update. Check your internet connection.") from exc
    if (size and n != size) or h.hexdigest() != sha256:
        _remove(dest)
        raise UpdateError("The downloaded file is not correct. PadMaster keeps your current version.")
    return dest


def temp_path(tag: str) -> str:
    return os.path.join(tempfile.gettempdir(), f"PadMaster-update-{tag}.exe")


def start_replace(new_exe: str, target: str, popen=subprocess.Popen) -> None:
    """Start the new exe. It waits until this app has closed, then replaces target."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    popen([new_exe, "--self-replace", target], creationflags=flags, close_fds=True)


def self_replace(target: str, me: str | None = None, popen=subprocess.Popen,
                 tries: int = 120, pause: float = 0.5) -> int:
    """Run by the new exe. Copy me over target when the old app has closed, then start target.
    If the copy fails, start the old target, so the user still has a working app."""
    me = me or sys.executable
    tmp = target + ".new"
    ok = False
    for _ in range(tries):
        try:
            shutil.copyfile(me, tmp)
            os.replace(tmp, target)  # fails while the old app still runs (file in use)
            ok = True
            break
        except OSError:
            _remove(tmp)
            time.sleep(pause)
    args = [target, "--updated-from", me] if ok else [target]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0)
    popen(args, creationflags=flags, close_fds=True)
    return 0 if ok else 1


def cleanup_later(path: str) -> None:
    """Delete the temporary update file when the process that ran it has closed."""
    if os.path.basename(path).startswith("PadMaster-update-") and \
            os.path.dirname(os.path.abspath(path)) == os.path.abspath(tempfile.gettempdir()):
        def run():
            for _ in range(60):
                if _remove(path):
                    return
                time.sleep(0.5)
        threading.Thread(target=run, daemon=True).start()


def _remove(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False
