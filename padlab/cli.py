"""Command line entry point.

    padlab                 open the app window
    padlab log             start logging in this console (Ctrl+C to stop), then write and open the report
    padlab log --ipc       logging for the app window (JSON status lines, 'stop' on stdin)
    padlab report LOG      make a report from an existing log
    padlab list            list connected controllers
    padlab check           show each input live, to confirm the mapping
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser

from . import __version__


def default_out_dir() -> str:
    base = os.path.join(os.path.expanduser("~"), "Documents")
    if not os.path.isdir(base):
        base = os.path.expanduser("~")
    return os.path.join(base, "PadLab")


def latency_for(log_path: str, meta: dict) -> dict:
    """Gamepadla latency entry for this session (or None), using the owner's saved choices."""
    from .history import load_settings
    from .latency import load, resolve
    choices = load_settings(os.path.dirname(os.path.abspath(log_path))).get("latency_map", {})
    from .history import load_names, model_key
    typed = load_names(os.path.dirname(os.path.abspath(log_path))).get(model_key(meta), "")
    res = resolve(meta, choices if isinstance(choices, dict) else {}, typed=typed)
    res["collected"] = load().get("collected", "")
    return res


def make_report(log_path: str, open_it: bool = True, quiet: bool = False, keep: dict | None = None,
                live=None) -> str:
    """Write the HTML report. If ``keep`` is a dict, the log and the analysis are put in it,
    so the caller can use them again without a second read (long sessions are slow to read)."""
    from .analysis import analyse
    from .logfile import read_log
    from .report import render

    from .history import display_name

    if live is not None:
        log = live.as_log()  # analysed during play: no second read of a long log
        rep = analyse(log, live)
    else:
        log = read_log(log_path)
        rep = analyse(log)
    if keep is not None:
        keep.update(log=log, rep=rep)
    html_path = log_path.replace(".csv.gz", "").replace(".csv", "") + "_report.html"
    name = display_name(log_path, log.meta)
    lat = latency_for(log_path, log.meta)
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(render(rep, os.path.basename(log_path), name=name, latency=lat["entry"],
                        latency_date=lat["collected"]))
    if not quiet:
        print(f"Report: {html_path}")
    if open_it:
        webbrowser.open("file:///" + os.path.abspath(html_path).replace("\\", "/"))
    return html_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="padlab", description="Log a controller while you play, then get a report.")
    p.add_argument("--version", action="version", version=f"PadMaster {__version__}")
    sub = p.add_subparsers(dest="cmd")

    lg = sub.add_parser("log", help="start logging in this console")
    lg.add_argument("--pad", type=int, default=0, help="controller index (see 'padlab list')")
    lg.add_argument("--out", default=default_out_dir(), help="folder for logs and reports")
    lg.add_argument("--seconds", type=float, default=None, help="stop after this many seconds")
    lg.add_argument("--no-open", action="store_true", help="do not open the report")
    lg.add_argument("--name", default="", help="your name for this controller, for example 'Xbox pad A'")
    lg.add_argument("--connection", default="", choices=["", "Wired", "Dongle", "Bluetooth"],
                    help="how the controller is connected")
    lg.add_argument("--auto-stop", type=float, default=0,
                    help="stop after this many minutes with no controller use (0: off)")
    lg.add_argument("--guided", action="store_true",
                    help="guided test: about 4 minutes of on-screen steps, then stop")
    lg.add_argument("--high-rate", action="store_true",
                    help="measure pads up to about 8000 Hz (keeps one CPU core busy)")
    lg.add_argument("--ipc", action="store_true", help="for the app window: JSON status lines, stop with a 'stop' line")

    rp = sub.add_parser("report", help="make a report from a log file")
    rp.add_argument("log")
    rp.add_argument("--no-open", action="store_true")

    ls = sub.add_parser("list", help="list connected controllers")
    ls.add_argument("--json", action="store_true", help="print the list as JSON (for the app window)")
    gu = sub.add_parser("gui", help="open the app window (default)")
    gu.add_argument("--out", default=default_out_dir(), help="folder for logs and reports")

    ck = sub.add_parser("check", help="show each input live, to confirm the mapping")
    ck.add_argument("--pad", type=int, default=0, help="controller index (see 'padlab list')")

    raw = list(sys.argv[1:] if argv is None else argv)
    if raw[:1] == ["--self-replace"] and len(raw) >= 2:  # in-place update, see updater.py
        from .updater import self_replace
        return self_replace(raw[1])
    if raw[:1] == ["--updated-from"] and len(raw) >= 2:
        from .updater import cleanup_later
        cleanup_later(raw[1])
        argv = raw[2:]
    args = p.parse_args(argv)

    if args.cmd == "check":
        from .logger import check
        check(pad_index=args.pad)
        return 0

    if args.cmd == "report":
        make_report(args.log, open_it=not args.no_open)
        return 0
    if args.cmd == "list":
        from .logger import list_devices
        devs = list_devices()
        if args.json:
            import json
            print(json.dumps(devs))
            return 0
        if not devs:
            print("No controllers found.")
        for d in devs:
            print(f"[{d['index']}] {d['name']}  {'mapped' if d['mapped'] else 'NOT mapped'}  {d['guid']}")
        return 0

    if args.cmd in (None, "gui"):
        from .gui import main as gui_main
        return gui_main(getattr(args, "out", None) or default_out_dir())

    from .logger import emit, run
    path = run(args.out, pad_index=args.pad, seconds=args.seconds, ipc=args.ipc, label=args.name, connection=args.connection,
               idle_stop_s=(args.auto_stop * 60) or None,
               guided=args.guided, high_rate=args.high_rate)
    if args.ipc:
        if not path:
            emit({"state": "done", "report": "", "log": ""})
            return 0
        try:
            done: dict = {}
            from . import logger as _lg
            live = _lg.last_live if _lg.last_live is not None and _lg.last_live.meta.get("ended_ms") is not None else None
            report = make_report(path, open_it=False, quiet=True, keep=done, live=live)
            from .history import update_index
            update_index(args.out, known={path: done["rep"]})
            auto = bool(done["log"].meta.get("auto_stopped"))
            emit({"state": "done", "report": report, "log": path, "auto_stopped": auto})
        except Exception as exc:  # report the error to the app window
            emit({"state": "error", "message": f"The report failed: {exc}", "log": path})
            return 1
        return 0
    make_report(path, open_it=not args.no_open)
    try:
        from .history import update_index
        update_index(args.out)
    except Exception:
        pass
    if getattr(sys, "frozen", False):
        try:
            input("\nPress Enter to close this window.")
        except (EOFError, RuntimeError):
            pass  # no console input (for example, started from a script or the windowed .exe)
    return 0


if __name__ == "__main__":
    sys.exit(main())
