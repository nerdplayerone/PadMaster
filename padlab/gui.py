"""PadLab window (tkinter, part of Python: no new dependency).

The window does not read the controller itself. It starts the logger as a separate
process (``padlab log --ipc``) and reads one JSON status line per second from it.
It stops the logger with a ``stop`` line on stdin. Reason: SDL and tkinter both
want the main thread, and a frozen window can't stop the logging.
"""

from __future__ import annotations

import glob
import json
import os
import queue
import subprocess
import sys
import threading
import webbrowser

from . import __version__
from .cli import default_out_dir

COUNTDOWN_S = 10
CONNECTIONS = ("Not set", "wired", "dongle", "bluetooth", "other")

# Colours (same family as the report's dark theme).
BG = "#111110"
SURFACE = "#1a1a19"
LINE = "#33332f"
TEXT = "#f0efec"
TEXT_2 = "#c3c2b7"
MUTED = "#8f8e86"
ACCENT = "#3987e5"
GOOD = "#0ca30c"
CRITICAL = "#d03b3b"
FONT = "Segoe UI"


# ---------------------------------------------------------------- helpers (tested without a window)

def base_command() -> list[str]:
    """How to start PadLab again as a child process (Python or the frozen .exe)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "padlab"]


def logger_command(pad: int, connection: str | None, out_dir: str) -> list[str]:
    cmd = base_command() + ["log", "--ipc", "--no-open", "--pad", str(pad), "--out", out_dir]
    if connection and connection in CONNECTIONS[1:]:
        cmd += ["--connection", connection]
    return cmd


def parse_status(line: str) -> dict | None:
    """One status line from the logger. Other text (for example 'Report: ...') gives None."""
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) and "state" in obj else None


def parse_devices(text: str) -> list[dict]:
    """The last JSON list in the output of 'padlab list --json'."""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("["):
            try:
                devs = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(devs, list):
                return devs
    return []


def device_label(d: dict) -> str:
    return f"[{d.get('index', 0)}] {d.get('name', 'Unknown')}" + ("" if d.get("mapped") else " (not mapped)")


def elapsed(t: float) -> str:
    s = int(t)
    return f"{s // 3600:d}:{(s // 60) % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:d}:{s % 60:02d}"


def countdown_text(seconds_since_start: float) -> tuple[str, bool]:
    """(message, still counting down)."""
    left = COUNTDOWN_S - int(seconds_since_start)
    if left > 0:
        return f"Put the controller down. Do not touch it. {left}", True
    return "Logging. Play your game.", False


def latest_report(out_dir: str) -> str | None:
    files = glob.glob(os.path.join(out_dir, "*_report.html"))
    return max(files, key=os.path.getmtime) if files else None


def _no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def open_path(path: str) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        webbrowser.open("file://" + os.path.abspath(path))


# ---------------------------------------------------------------- window

class App:
    def __init__(self, root, out_dir: str | None = None):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.root = root
        self.out_dir = out_dir or default_out_dir()
        self.proc: subprocess.Popen | None = None
        self.lines: queue.Queue = queue.Queue()
        self.devices: list[dict] = []
        self.last_report = latest_report(self.out_dir)
        self.logging_since: float | None = None   # logger time when logging started
        self.last_t = 0.0
        self.state = "idle"
        self.closing = False

        root.title(f"PadLab {__version__}")
        root.configure(bg=BG)
        root.minsize(440, 470)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        st = ttk.Style(root)
        st.theme_use("clam")
        st.configure(".", background=BG, foreground=TEXT, font=(FONT, 10))
        st.configure("TFrame", background=BG)
        st.configure("Card.TFrame", background=SURFACE, bordercolor=LINE, relief="solid", borderwidth=1)
        st.configure("TLabel", background=BG, foreground=TEXT)
        st.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(FONT, 9))
        st.configure("Title.TLabel", background=BG, foreground=TEXT, font=(FONT, 18, "bold"))
        st.configure("Status.TLabel", background=BG, foreground=TEXT, font=(FONT, 12, "bold"))
        st.configure("Num.TLabel", background=SURFACE, foreground=TEXT, font=(FONT, 20, "bold"))
        st.configure("Cap.TLabel", background=SURFACE, foreground=TEXT_2, font=(FONT, 9))
        st.configure("TButton", background=SURFACE, foreground=TEXT, bordercolor=LINE, focuscolor=ACCENT,
                     padding=(10, 6))
        st.map("TButton", background=[("active", LINE), ("disabled", BG)], foreground=[("disabled", MUTED)])
        st.configure("Start.TButton", background=ACCENT, foreground="#ffffff", font=(FONT, 12, "bold"),
                     padding=(10, 10))
        st.map("Start.TButton", background=[("active", "#256abf"), ("disabled", LINE)])
        st.configure("Stop.TButton", background=CRITICAL, foreground="#ffffff", font=(FONT, 12, "bold"),
                     padding=(10, 10))
        st.map("Stop.TButton", background=[("active", "#a82e2e"), ("disabled", LINE)])
        st.configure("TCheckbutton", background=BG, foreground=TEXT_2)
        st.map("TCheckbutton", background=[("active", BG)])
        st.configure("TCombobox", fieldbackground=SURFACE, background=SURFACE, foreground=TEXT,
                     arrowcolor=TEXT, bordercolor=LINE)
        st.map("TCombobox", fieldbackground=[("readonly", SURFACE)], foreground=[("readonly", TEXT)])
        root.option_add("*TCombobox*Listbox.background", SURFACE)
        root.option_add("*TCombobox*Listbox.foreground", TEXT)
        root.option_add("*TCombobox*Listbox.font", (FONT, 10))

        f = ttk.Frame(root, padding=18)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="PadLab", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text="Logs your controller while you play. Then it makes a report.",
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 12))

        ttk.Label(f, text="Controller").grid(row=2, column=0, sticky="w", padx=(0, 10))
        self.dev_var = tk.StringVar(value="Looking for controllers...")
        self.dev_box = ttk.Combobox(f, textvariable=self.dev_var, state="readonly")
        self.dev_box.grid(row=2, column=1, sticky="ew")
        self.refresh_btn = ttk.Button(f, text="Refresh", command=self.refresh_devices)
        self.refresh_btn.grid(row=2, column=2, padx=(8, 0))

        ttk.Label(f, text="Connection").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=(8, 0))
        self.conn_var = tk.StringVar(value=CONNECTIONS[0])
        self.conn_box = ttk.Combobox(f, textvariable=self.conn_var, values=CONNECTIONS, state="readonly", width=12)
        self.conn_box.grid(row=3, column=1, sticky="w", pady=(8, 0))

        self.status_var = tk.StringVar(value="Press Start.")
        ttk.Label(f, textvariable=self.status_var, style="Status.TLabel", wraplength=400).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(16, 8))

        tiles = ttk.Frame(f)
        tiles.grid(row=5, column=0, columnspan=3, sticky="ew")
        self.vars = {}
        for i, (key, cap) in enumerate((("time", "Time logged"), ("inputs", "Inputs"), ("disc", "Disconnects"))):
            tiles.columnconfigure(i, weight=1)
            card = ttk.Frame(tiles, style="Card.TFrame", padding=(12, 8))
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            self.vars[key] = tk.StringVar(value="0:00" if key == "time" else "0")
            ttk.Label(card, textvariable=self.vars[key], style="Num.TLabel").pack(anchor="w")
            ttk.Label(card, text=cap, style="Cap.TLabel").pack(anchor="w")

        self.start_btn = ttk.Button(f, text="Start", style="Start.TButton", command=self.toggle)
        self.start_btn.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(16, 8))

        row = ttk.Frame(f)
        row.grid(row=7, column=0, columnspan=3, sticky="ew")
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=1)
        self.report_btn = ttk.Button(row, text="Open last report", command=self.open_report)
        self.report_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(row, text="Open logs folder", command=self.open_folder).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.top_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Always on top", variable=self.top_var, command=self.set_top).grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(10, 0))

        self.info_var = tk.StringVar(value=f"Logs and reports: {self.out_dir}")
        ttk.Label(f, textvariable=self.info_var, style="Muted.TLabel", wraplength=400).grid(
            row=9, column=0, columnspan=3, sticky="w", pady=(10, 0))

        self.update_buttons()
        self.refresh_devices()
        self.root.after(100, self.poll)

    # ------------------------------------------------------------ devices

    def refresh_devices(self) -> None:
        self.refresh_btn.state(["disabled"])
        self.dev_var.set("Looking for controllers...")

        def work() -> None:
            try:
                res = subprocess.run(base_command() + ["list", "--json"], capture_output=True, text=True,
                                     timeout=20, creationflags=_no_window_flags())
                devs = parse_devices(res.stdout)
            except Exception:
                devs = []
            self.lines.put(("devices", devs))

        threading.Thread(target=work, daemon=True).start()

    def show_devices(self, devs: list[dict]) -> None:
        self.devices = devs
        labels = [device_label(d) for d in devs]
        self.dev_box["values"] = labels
        if labels:
            self.dev_var.set(labels[0])
        else:
            self.dev_var.set("No controller found. Connect one and press Refresh.")
        if self.state == "idle":
            self.refresh_btn.state(["!disabled"])
        self.update_buttons()

    def selected_pad(self) -> int:
        labels = list(self.dev_box["values"])
        try:
            return int(self.devices[labels.index(self.dev_var.get())].get("index", 0))
        except (ValueError, IndexError):
            return 0

    # ------------------------------------------------------------ start / stop

    def toggle(self) -> None:
        if self.state == "idle":
            self.start()
        elif self.state in ("waiting", "logging"):
            self.stop()

    def start(self) -> None:
        conn = self.conn_var.get()
        cmd = logger_command(self.selected_pad(), conn, self.out_dir)
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         text=True, encoding="utf-8", bufsize=1, creationflags=_no_window_flags())
        except OSError as exc:
            self.status_var.set(f"Could not start the logger: {exc}")
            return
        self.state = "starting"
        self.logging_since = None
        for v, val in ((self.vars["time"], "0:00"), (self.vars["inputs"], "0"), (self.vars["disc"], "0")):
            v.set(val)
        self.status_var.set("Starting...")
        self.update_buttons()
        threading.Thread(target=self.read_output, args=(self.proc,), daemon=True).start()

    def read_output(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            st = parse_status(line)
            if st:
                self.lines.put(("status", st))
        proc.wait()
        self.lines.put(("exit", proc.returncode))

    def stop(self) -> None:
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            assert self.proc.stdin is not None
            self.proc.stdin.write("stop\n")
            self.proc.stdin.flush()
        except (OSError, ValueError):
            pass
        self.state = "stopping"
        self.status_var.set("Stopping. Making the report...")
        self.update_buttons()

    # ------------------------------------------------------------ status

    def poll(self) -> None:
        try:
            while True:
                kind, val = self.lines.get_nowait()
                if kind == "devices":
                    self.show_devices(val)
                elif kind == "status":
                    self.on_status(val)
                elif kind == "exit":
                    self.on_exit(val)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def on_status(self, st: dict) -> None:
        s = st.get("state")
        if s == "waiting":
            self.state = "waiting"
            self.status_var.set("Waiting for the controller. Connect it now.")
        elif s == "logging":
            if self.state in ("starting", "waiting"):
                self.state = "logging"
                self.logging_since = float(st.get("t", 0.0))
                if st.get("device"):
                    self.info_var.set(f"Logging: {st['device']}. Log file: {os.path.basename(st.get('log', ''))}")
            if self.state == "logging":
                t = float(st.get("t", 0.0))
                self.last_t = t
                self.vars["time"].set(elapsed(t))
                self.vars["inputs"].set(f"{int(st.get('inputs', 0)):,}")
                self.vars["disc"].set(str(st.get("disconnects", 0)))
                msg, _ = countdown_text(t - (self.logging_since or 0.0))
                if st.get("connected") is False:
                    msg = "Controller lost. Logging goes on. Connect it again."
                self.status_var.set(msg)
        elif s == "reporting":
            self.status_var.set("Making the report...")
        elif s == "done":
            self.state = "done"
            rep = st.get("report")
            if rep:
                self.last_report = rep
                self.status_var.set("Report ready. It opens in your browser.")
                self.info_var.set(f"Report: {rep}")
                if not self.closing:
                    open_path(rep)
            else:
                self.status_var.set("Stopped. No controller was found, so there is no report.")
        elif s == "error":
            self.state = "done"
            self.status_var.set(f"Error: {st.get('message', 'unknown')}")
        self.update_buttons()

    def on_exit(self, code: int) -> None:
        if self.state not in ("done",):
            self.status_var.set(f"The logger stopped unexpectedly (code {code}). Check the logs folder.")
        self.state = "idle"
        self.proc = None
        self.refresh_btn.state(["!disabled"])
        self.update_buttons()
        if self.closing:
            self.root.destroy()

    # ------------------------------------------------------------ buttons

    def update_buttons(self) -> None:
        busy = self.state not in ("idle", "done")
        if self.state in ("waiting", "logging"):
            self.start_btn.configure(text="Stop and make report", style="Stop.TButton")
            self.start_btn.state(["!disabled"])
        elif self.state in ("starting", "stopping"):
            self.start_btn.configure(text="Please wait...", style="Start.TButton")
            self.start_btn.state(["disabled"])
        else:
            self.start_btn.configure(text="Start", style="Start.TButton")
            self.start_btn.state(["!disabled"] if self.devices else ["disabled"])
        for w in (self.dev_box, self.conn_box):
            w.state(["disabled"] if busy else ["!disabled", "readonly"])
        self.report_btn.state(["!disabled"] if self.last_report and os.path.exists(self.last_report) else ["disabled"])

    def open_report(self) -> None:
        if self.last_report and os.path.exists(self.last_report):
            open_path(self.last_report)

    def open_folder(self) -> None:
        os.makedirs(self.out_dir, exist_ok=True)
        open_path(self.out_dir)

    def set_top(self) -> None:
        self.root.attributes("-topmost", bool(self.top_var.get()))

    def on_close(self) -> None:
        if self.proc and self.proc.poll() is None:
            from tkinter import messagebox
            if not messagebox.askyesno("PadLab", "PadLab is logging. Stop now and make the report?"):
                return
            self.closing = True
            self.stop()
            return  # the window closes when the logger has finished
        self.root.destroy()


def main() -> int:
    import tkinter as tk

    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0
