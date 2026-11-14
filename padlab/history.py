"""Session history: one row for each log in the logs folder.

The logs are the source of truth. ``history.json`` in the same folder is only a cache,
so the list opens fast. If the cache is lost or damaged, PadMaster makes it again from
the logs. PadMaster never deletes logs.
"""

from __future__ import annotations

import csv
import glob
import json
import os

from .analysis import ANALYSIS_VERSION, NODATA, OK, PROBLEM, WATCH, analyse, metric_values, summary_counts
from .logfile import read_log

INDEX_NAME = "history.json"
INDEX_VERSION = 4  # format of history.json
NAMES_FILE = "names.json"  # names the owner gave to sessions: {log file: name}
NAME_MAX = 60


def model_key(meta: dict) -> str:
    """One key for each controller.

    If the owner named the pad at the start of the session, the key is that name.
    Otherwise it is the model (PadMaster can't tell two pads of the same model apart).
    """
    label = str(meta.get("label", "") or "")
    if label:
        return "label:" + label
    guid = str(meta.get("guid", "") or "")
    return "guid:" + guid if guid else "model:" + str(meta.get("device", "Unknown controller"))


def load_names(out_dir: str) -> dict[str, str]:
    """Names the owner gave: {model key: name}."""
    try:
        with open(os.path.join(out_dir, NAMES_FILE), encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items() if str(k).startswith(("guid:", "model:", "label:"))}
    except (OSError, ValueError):
        return {}


def set_name(out_dir: str, meta: dict, name: str) -> str:
    """Name a controller model. All sessions from that model (old and new) show the name.

    An empty name goes back to the model name. Log files are never changed.
    Returns the stored name ("" if removed).
    """
    key = model_key(meta)
    name = " ".join(str(name).split())[:NAME_MAX]
    names = load_names(out_dir)
    if name:
        names[key] = name
    else:
        names.pop(key, None)
    tmp = os.path.join(out_dir, NAMES_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(names, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, os.path.join(out_dir, NAMES_FILE))
    return name


def display_name(log_path: str, meta: dict) -> str:
    """The owner's name for this controller model, or the model name."""
    names = load_names(os.path.dirname(os.path.abspath(log_path)))
    return (names.get(model_key(meta), "") or str(meta.get("label", "") or "")
            or str(meta.get("device", "Unknown controller")))


SETTINGS_FILE = "settings.json"


def load_settings(out_dir: str) -> dict:
    try:
        with open(os.path.join(out_dir, SETTINGS_FILE), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_setting(out_dir: str, key: str, value) -> None:
    data = load_settings(out_dir)
    data[key] = value
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, SETTINGS_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, os.path.join(out_dir, SETTINGS_FILE))

CSV_COLUMNS = [
    "started", "device", "connection", "model", "mode", "duration_s", "active_min", "inputs", "disconnects",
    "problem", "watch", "ok", "no_data", "padlab_version", "log_file", "report_file",
]


def _summarise(path: str) -> dict:
    log = read_log(path)
    rep = analyse(log)
    counts = summary_counts(rep.findings)
    m, s = rep.meta, rep.session
    report = path.replace(".csv.gz", "").replace(".csv", "") + "_report.html"
    model = m.get("device", "Unknown controller")
    return {
        "started": m.get("started", ""),
        "device": display_name(path, m),
        "model": model,
        "connection": m.get("connection", ""),
        "mode": m.get("mode", ""),
        "duration_s": round(s.get("duration_ms", 0) / 1000, 1),
        "active_min": s.get("active_min", 0),
        "inputs": s.get("inputs", 0),
        "disconnects": rep.connection.get("disconnects", 0),
        "problem": counts[PROBLEM],
        "watch": counts[WATCH],
        "ok": counts[OK],
        "no_data": counts[NODATA],
        "padlab_version": m.get("padlab", ""),
        "log_file": os.path.basename(path),
        "report_file": os.path.basename(report) if os.path.exists(report) else "",
        "metrics": metric_values(rep),
    }


def _load_index(out_dir: str) -> dict:
    try:
        with open(os.path.join(out_dir, INDEX_NAME), encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("version") == INDEX_VERSION and isinstance(data.get("sessions"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"version": INDEX_VERSION, "sessions": {}}


def update_index(out_dir: str) -> list[dict]:
    """Bring the cache up to date with the logs on disk. Returns sessions, newest first."""
    data = _load_index(out_dir)
    old = data["sessions"]
    names = load_names(out_dir)
    new: dict[str, dict] = {}
    for path in glob.glob(os.path.join(out_dir, "padlab_*.csv.gz")):
        name = os.path.basename(path)
        st = os.stat(path)
        key = [st.st_size, int(st.st_mtime), ANALYSIS_VERSION, json.dumps(names, sort_keys=True)]
        cached = old.get(name)
        report_now = os.path.exists(path[: -len(".csv.gz")] + "_report.html")
        if cached and cached.get("_key") == key and bool(cached.get("report_file")) == report_now:
            new[name] = cached
            continue
        try:
            row = _summarise(path)
        except Exception as exc:  # a damaged log must not hide the others
            row = {"started": "", "device": "Unreadable log", "log_file": name,
                   "report_file": "", "error": str(exc)}
        row["_key"] = key
        new[name] = row
    data["sessions"] = new
    if os.path.isdir(out_dir):
        tmp = os.path.join(out_dir, INDEX_NAME + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, os.path.join(out_dir, INDEX_NAME))
    return sessions_sorted(new)


def sessions_sorted(sessions: dict[str, dict]) -> list[dict]:
    rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in sessions.values()]
    return sorted(rows, key=lambda r: (r.get("started", ""), r.get("log_file", "")), reverse=True)


def export_csv(out_dir: str, csv_path: str) -> int:
    """Write the history to a CSV file. Returns the number of rows."""
    rows = update_index(out_dir)
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in CSV_COLUMNS})
    return len(rows)
