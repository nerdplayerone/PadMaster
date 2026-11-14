"""Command line entry point.

    padlab                 start logging (Ctrl+C to stop), then write and open the report
    padlab report LOG      make a report from an existing log
    padlab list            list connected controllers
    padlab check           show each input live, to confirm the mapping
    padlab gui             open the window (the .exe does this when started with no arguments)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser

from . import __version__


def default_out_dir() -> str:
    base = os.path.join(os.path.expanduser("~"), "Documents")
    if not os.path.isdir(base):
        base = os.path.expanduser("~")
    return os.path.join(base, "PadLab")


def make_report(log_path: str, open_it: bool = True) -> str:
    from .analysis import analyse
    from .logfile import read_log
    from .report import render

    log = read_log(log_path)
    rep = analyse(log)
    html_path = log_path.replace(".csv.gz", "").replace(".csv", "") + "_report.html"
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(render(rep, os.path.basename(log_path)))
    print(f"Report: {html_path}")
    if open_it:
        webbrowser.open("file:///" + os.path.abspath(html_path).replace("\\", "/"))
    return html_path


def _ensure_stdio() -> None:
    """A windowed .exe can start with sys.stdin/sys.stdout set to None, even when the GUI
    gives it pipes. Open the pipes from the OS handles so that --ipc works."""
    if sys.stdout is not None and sys.stdin is not None:
        return
    for name, fd, mode, std in (("stdin", 0, "r", -10), ("stdout", 1, "w", -11)):
        if getattr(sys, name) is not None:
            continue
        stream = None
        try:
            stream = os.fdopen(fd, mode, encoding="utf-8", buffering=1)
        except OSError:
            try:
                import ctypes
                import msvcrt
                handle = ctypes.windll.kernel32.GetStdHandle(std)
                if handle and handle != -1:
                    flags = os.O_RDONLY if mode == "r" else os.O_WRONLY
                    stream = os.fdopen(msvcrt.open_osfhandle(handle, flags), mode, encoding="utf-8", buffering=1)
            except Exception:
                stream = None
        setattr(sys, name, stream)


def run_ipc(args) -> int:
    """Logger for the GUI: JSON status lines on stdout, 'stop' on stdin."""
    import threading

    from .logger import emit_status, run, stdin_stop_watcher

    _ensure_stdio()
    stop = threading.Event()
    stdin_stop_watcher(stop)
    try:
        path = run(args.out, pad_index=args.pad, seconds=args.seconds, connection=args.connection,
                   ipc=True, stop=stop)
        if path is None:
            emit_status({"state": "done", "report": None, "log": None})
            return 0
        emit_status({"state": "reporting", "log": path})
        report = make_report(path, open_it=False)
        emit_status({"state": "done", "report": report, "log": path})
    except Exception as exc:  # the GUI shows the message
        emit_status({"state": "error", "message": f"{type(exc).__name__}: {exc}"})
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="padlab", description="Log a controller while you play, then get a report.")
    p.add_argument("--version", action="version", version=f"PadLab {__version__}")
    sub = p.add_subparsers(dest="cmd")

    lg = sub.add_parser("log", help="start logging (default)")
    lg.add_argument("--pad", type=int, default=0, help="controller index (see 'padlab list')")
    lg.add_argument("--out", default=default_out_dir(), help="folder for logs and reports")
    lg.add_argument("--seconds", type=float, default=None, help="stop after this many seconds")
    lg.add_argument("--no-open", action="store_true", help="do not open the report")
    lg.add_argument("--connection", choices=("wired", "dongle", "bluetooth", "other"), default=None,
                    help="how the controller is connected (shown in the report)")
    lg.add_argument("--ipc", action="store_true", help=argparse.SUPPRESS)  # used by the GUI

    rp = sub.add_parser("report", help="make a report from a log file")
    rp.add_argument("log")
    rp.add_argument("--no-open", action="store_true")

    ls = sub.add_parser("list", help="list connected controllers")
    ls.add_argument("--json", action="store_true", help=argparse.SUPPRESS)  # used by the GUI

    sub.add_parser("gui", help="open the PadLab window")

    ck = sub.add_parser("check", help="show each input live, to confirm the mapping")
    ck.add_argument("--pad", type=int, default=0, help="controller index (see 'padlab list')")

    raw = argv if argv is not None else sys.argv[1:]
    if not raw and getattr(sys, "frozen", False):
        raw = ["gui"]  # the .exe opens the window by default
    args = p.parse_args(raw)

    if args.cmd == "gui":
        from .gui import main as gui_main
        return gui_main()

    if args.cmd == "check":
        from .logger import check
        check(pad_index=args.pad)
        return 0

    if args.cmd == "report":
        make_report(args.log, open_it=not args.no_open)
        return 0
    if args.cmd == "list":
        from .logger import list_devices
        if args.json:
            _ensure_stdio()
            try:
                devs = list_devices()
            except BaseException as exc:  # sys.exit from a missing pygame is also caught
                devs = []
                print(json.dumps({"error": str(exc)}), flush=True)
            print(json.dumps(devs), flush=True)
            return 0
        devs = list_devices()
        if not devs:
            print("No controllers found.")
        for d in devs:
            print(f"[{d['index']}] {d['name']}  {'mapped' if d['mapped'] else 'NOT mapped'}  {d['guid']}")
        return 0

    # Default: log.
    if args.cmd is None:
        args = p.parse_args(["log"] + raw)
    if args.ipc:
        return run_ipc(args)
    from .logger import run
    path = run(args.out, pad_index=args.pad, seconds=args.seconds, connection=args.connection)
    make_report(path, open_it=not args.no_open)
    if getattr(sys, "frozen", False):
        try:
            input("\nPress Enter to close this window.")
        except EOFError:
            pass  # no console input (for example, started from a script)
    return 0


if __name__ == "__main__":
    sys.exit(main())
