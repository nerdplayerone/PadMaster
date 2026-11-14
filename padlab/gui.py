"""PadMaster app window.

The window is a local web page shown with pywebview (Microsoft Edge WebView2 on
Windows). It loads nothing from the internet.

The SDL logger runs in a separate process (``padlab log --ipc``). It writes one JSON
status line per second to stdout. The window stops it with a ``stop`` line on stdin.
Reason: a freeze in the window can't stop the logging, and SDL does not share the
main thread with the window.
"""

from __future__ import annotations

from .branding import CHANNELS, is_channel_url
import json
import os
import subprocess
import sys
import threading
import time

from . import __version__

APP_HTML = "app.html"


def _resource(name: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "padlab", name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


def padlab_command(*args: str) -> list[str]:
    """Command that runs PadMaster itself, from Python or from the frozen .exe."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "padlab", *args]


def _no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def report_is_stale(report: str, log_path: str) -> bool:
    """True if the report is missing, older than the log, or made by older checks."""
    from .analysis import ANALYSIS_VERSION
    if not os.path.isfile(report) or os.path.getmtime(report) < os.path.getmtime(log_path):
        return True
    import html as _html
    from .history import display_name
    from .logfile import read_log
    with open(report, encoding="utf-8") as fh:
        head = fh.read(3000)
    if f'name="padlab-analysis" content="{ANALYSIS_VERSION}"' not in head:
        return True
    meta = read_log(log_path).meta
    if f'name="padlab-name" content="{_html.escape(display_name(log_path, meta))}"' not in head:
        return True
    from .cli import latency_for
    url = (latency_for(log_path, meta)["entry"] or {}).get("url", "")
    return f'name="padlab-latency" content="{_html.escape(url)}"' not in head


def _is_gamepadla_url(url: str) -> bool:
    from .latency import by_url
    return url.rstrip("/") == "https://gamepadla.com" or by_url(url) is not None


class Api:
    """Functions the page calls through ``window.pywebview.api``. No pywebview import here,
    so tests can use this class without a window."""

    def __init__(self, out_dir: str, popen=subprocess.Popen, run=subprocess.run):
        self._out_dir = out_dir
        self._popen = popen
        self._run = run
        self._proc = None
        self._lock = threading.Lock()
        self._status: dict = {"state": "idle"}
        self._stderr_tail: list[str] = []
        self._window = None  # set by main()

    # ---------------------------------------------------------------- start-up data
    def init(self) -> dict:
        from .report import logo_data_uri
        return {
            "version": __version__,
            "out_dir": self._out_dir,
            "logo": logo_data_uri(),
            "history": self.history(),
            "channels": [{"name": n, "url": u} for n, u in CHANNELS],
        }

    def devices(self) -> list[dict]:
        try:
            res = self._run(padlab_command("list", "--json"), capture_output=True, text=True,
                            timeout=20, creationflags=_no_window_flags())
            return json.loads(res.stdout.strip().splitlines()[-1]) if res.stdout.strip() else []
        except (OSError, ValueError, subprocess.SubprocessError, IndexError):
            return []

    # ---------------------------------------------------------------- logging
    def pad_names(self) -> dict:
        """Names used before (for the dropdown) and the last one selected."""
        from .history import load_settings
        names = sorted({r["device"] for r in self.history() if r.get("device") and r["device"] != "Unreadable log"},
                       key=str.lower)
        return {"names": names, "last": load_settings(self._out_dir).get("last_pad_name", ""),
                "last_connection": load_settings(self._out_dir).get("last_connection", "")}

    def start(self, pad_index: int = 0, pad_name: str = "", connection: str = "") -> dict:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return {"ok": False, "message": "Logging is already running."}
            os.makedirs(self._out_dir, exist_ok=True)
            from .history import save_setting
            pad_name = " ".join(str(pad_name or "").split())[:60]
            save_setting(self._out_dir, "last_pad_name", pad_name)
            connection = connection if connection in ("Wired", "Dongle", "Bluetooth") else ""
            save_setting(self._out_dir, "last_connection", connection)
            cmd = padlab_command("log", "--ipc", "--pad", str(int(pad_index)), "--out", self._out_dir)
            if pad_name:
                cmd += ["--name", pad_name]
            if connection:
                cmd += ["--connection", connection]
            try:
                self._proc = self._popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True, bufsize=1,
                                         creationflags=_no_window_flags())
            except OSError as exc:
                self._status = {"state": "error", "message": f"The logger did not start: {exc}"}
                return {"ok": False, "message": self._status["message"]}
            self._status = {"state": "starting", "started_at": time.time()}
            self._stderr_tail = []
            threading.Thread(target=self._read_stdout, args=(self._proc,), daemon=True).start()
            threading.Thread(target=self._read_stderr, args=(self._proc,), daemon=True).start()
        return {"ok": True}

    def stop(self) -> dict:
        with self._lock:
            proc = self._proc
        if not proc or proc.poll() is not None:
            return {"ok": False, "message": "Logging is not running."}
        try:
            proc.stdin.write("stop\n")
            proc.stdin.flush()
        except (OSError, ValueError):
            pass
        self._status = {**self._status, "state": "stopping"}
        return {"ok": True}

    def status(self) -> dict:
        return dict(self._status)

    def _read_stdout(self, proc) -> None:
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            keep = {k: self._status[k] for k in ("started_at", "device", "log") if k in self._status}
            if self._status.get("state") == "stopping" and msg.get("state") == "logging":
                msg["state"] = "stopping"
            self._status = {**keep, **msg}
        proc.wait()
        if self._status.get("state") not in ("done", "error"):
            tail = " ".join(self._stderr_tail[-3:]).strip()
            self._status = {"state": "error",
                            "message": "The logger stopped without a report." + (f" Details: {tail}" if tail else "")}

    def _read_stderr(self, proc) -> None:
        for line in proc.stderr:
            self._stderr_tail = (self._stderr_tail + [line.strip()])[-20:]

    # ---------------------------------------------------------------- history and reports
    def history(self) -> list[dict]:
        from .history import update_index
        try:
            return update_index(self._out_dir)
        except OSError:
            return []

    def report_html(self, log_file: str) -> dict:
        """HTML of the report for one log. Makes the report if it does not exist yet."""
        from .cli import make_report
        name = os.path.basename(log_file)  # only files in the logs folder
        log_path = os.path.join(self._out_dir, name)
        if not os.path.isfile(log_path):
            return {"ok": False, "message": "The log file is missing."}
        report = log_path[: -len(".csv.gz")] + "_report.html"
        try:
            if report_is_stale(report, log_path):
                make_report(log_path, open_it=False, quiet=True)
            from .theme import with_scrollbars
            with open(report, encoding="utf-8") as fh:
                return {"ok": True, "html": with_scrollbars(fh.read()), "path": report}
        except Exception as exc:
            return {"ok": False, "message": f"The report failed: {exc}"}

    def latency_status(self, log_file: str) -> dict:
        """Gamepadla match for this session: chosen, auto, ask or none, with suggestions."""
        from .cli import latency_for
        from .history import display_name
        from .logfile import read_log
        log_path = os.path.join(self._out_dir, os.path.basename(log_file))
        if not os.path.isfile(log_path):
            return {"ok": False}
        meta = read_log(log_path).meta
        res = latency_for(log_path, meta)
        return {"ok": True, "state": res["state"], "controller": display_name(log_path, meta),
                "match": (res["entry"] or {}).get("name", ""), "suggest": res["suggest"]}

    def latency_search(self, text: str) -> list[dict]:
        from .latency import candidates
        return candidates(str(text)[:80], limit=12)

    def latency_choose(self, log_file: str, url: str) -> dict:
        """Save the owner's choice for this controller: a Gamepadla page URL, or 'none'."""
        from .history import load_settings, model_key, save_setting
        from .latency import NONE, by_url
        from .logfile import read_log
        log_path = os.path.join(self._out_dir, os.path.basename(log_file))
        if not os.path.isfile(log_path):
            return {"ok": False, "message": "The log file is missing."}
        if url != NONE and not by_url(url):
            return {"ok": False, "message": "That controller is not in the Gamepadla data."}
        choices = load_settings(self._out_dir).get("latency_map", {})
        choices = choices if isinstance(choices, dict) else {}
        choices[model_key(read_log(log_path).meta)] = url
        save_setting(self._out_dir, "latency_map", choices)
        return self.report_html(log_file)

    def rename(self, log_file: str, name: str) -> dict:
        """Name the controller model of this session. All its sessions get the name."""
        from .cli import make_report
        from .history import set_name
        lf = os.path.basename(log_file)
        log_path = os.path.join(self._out_dir, lf)
        if not os.path.isfile(log_path):
            return {"ok": False, "message": "The log file is missing."}
        from .logfile import read_log
        try:
            meta = read_log(log_path).meta
        except Exception as exc:
            return {"ok": False, "message": f"PadMaster can't read the log: {exc}"}
        from .history import display_name, load_settings, save_setting
        old = display_name(log_path, meta)
        stored = set_name(self._out_dir, meta, name)
        if load_settings(self._out_dir).get("last_pad_name") == old:  # keep the default in step
            save_setting(self._out_dir, "last_pad_name", display_name(log_path, meta))
        try:
            make_report(log_path, open_it=False, quiet=True)
        except Exception as exc:
            return {"ok": False, "message": f"The name is saved, but the report failed: {exc}"}
        return {"ok": True, "name": stored, "history": self.history()}

    def compare_data(self) -> dict:
        from .analysis import metric_definitions
        return {"metrics": metric_definitions(), "sessions": self.history()}

    def open_logs_folder(self) -> None:
        os.makedirs(self._out_dir, exist_ok=True)
        if os.name == "nt":
            os.startfile(self._out_dir)  # noqa: S606 (opens File Explorer)

    def open_link(self, url: str) -> bool:
        """Open an allowed address in the normal web browser: the owner's channels, or a
        Gamepadla.com page from the bundled data. No other address is opened."""
        url = str(url)
        if not (is_channel_url(url) or _is_gamepadla_url(url)):
            return False
        import webbrowser
        webbrowser.open(url)
        return True

    def open_report_in_browser(self, path: str) -> None:
        import webbrowser
        p = os.path.join(self._out_dir, os.path.basename(path))
        if os.path.isfile(p):
            webbrowser.open("file:///" + os.path.abspath(p).replace("\\", "/"))

    def export_history(self) -> dict:
        from .history import export_csv
        target = os.path.join(self._out_dir, "padlab_history.csv")
        if self._window is not None:
            try:
                import webview
                res = self._window.create_file_dialog(webview.FileDialog.SAVE, directory=self._out_dir,
                                                     save_filename="padlab_history.csv",
                                                     file_types=("CSV file (*.csv)",))
                if not res:
                    return {"ok": False, "message": ""}
                target = res if isinstance(res, str) else res[0]
            except Exception:
                pass
        n = export_csv(self._out_dir, target)
        return {"ok": True, "message": f"{n} sessions exported to {target}"}

    def set_on_top(self, on: bool) -> None:
        if self._window is not None:
            self._window.on_top = bool(on)

    def shutdown(self) -> None:
        """Called when the window closes: stop the logger so the log is complete."""
        proc = self._proc
        if proc and proc.poll() is None:
            self.stop()
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()


MIN_SIZE = (900, 600)


def window_geometry(screen_w: int, screen_h: int) -> tuple[int, int, int, int]:
    """Start size and position: 90% x 88% of the screen, centred.

    A share of the screen, not a fixed size, so the window fits at every Windows
    display scale (the screen size comes in physical pixels).
    """
    w = max(min(MIN_SIZE[0], screen_w), int(screen_w * 0.9))
    h = max(min(MIN_SIZE[1], screen_h), int(screen_h * 0.88))
    return w, h, (screen_w - w) // 2, (screen_h - h) // 2


def main(out_dir: str) -> int:
    import webview

    api = Api(out_dir)
    with open(_resource(APP_HTML), encoding="utf-8") as fh:
        page = fh.read()
    from .theme import SCROLLBAR_CSS, SCROLLBAR_MARKER
    page = page.replace(SCROLLBAR_MARKER, SCROLLBAR_CSS)
    try:
        scr = webview.screens[0]
        w, h, x, y = window_geometry(scr.width, scr.height)
    except Exception:
        w, h, x, y = 1400, 880, None, None
    window = webview.create_window(
        f"PadMaster {__version__}", html=page, js_api=api,
        width=w, height=h, x=x, y=y, min_size=MIN_SIZE, background_color="#0b0b0c",
    )
    api._window = window
    window.events.closing += api.shutdown
    webview.start(private_mode=True)
    return 0
