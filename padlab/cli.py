"""Command line entry point.

    padlab                 start logging (Ctrl+C to stop), then write and open the report
    padlab report LOG      make a report from an existing log
    padlab list            list connected controllers
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="padlab", description="Log a controller while you play, then get a report.")
    p.add_argument("--version", action="version", version=f"PadLab {__version__}")
    sub = p.add_subparsers(dest="cmd")

    lg = sub.add_parser("log", help="start logging (default)")
    lg.add_argument("--pad", type=int, default=0, help="controller index (see 'padlab list')")
    lg.add_argument("--out", default=default_out_dir(), help="folder for logs and reports")
    lg.add_argument("--seconds", type=float, default=None, help="stop after this many seconds")
    lg.add_argument("--no-open", action="store_true", help="do not open the report")

    rp = sub.add_parser("report", help="make a report from a log file")
    rp.add_argument("log")
    rp.add_argument("--no-open", action="store_true")

    sub.add_parser("list", help="list connected controllers")

    args = p.parse_args(argv)

    if args.cmd == "report":
        make_report(args.log, open_it=not args.no_open)
        return 0
    if args.cmd == "list":
        from .logger import list_devices
        devs = list_devices()
        if not devs:
            print("No controllers found.")
        for d in devs:
            print(f"[{d['index']}] {d['name']}  {'mapped' if d['mapped'] else 'NOT mapped'}  {d['guid']}")
        return 0

    # Default: log.
    if args.cmd is None:
        args = p.parse_args(["log"] + (argv if argv is not None else sys.argv[1:]))
    from .logger import run
    path = run(args.out, pad_index=args.pad, seconds=args.seconds)
    make_report(path, open_it=not args.no_open)
    if getattr(sys, "frozen", False):
        input("\nPress Enter to close this window.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
