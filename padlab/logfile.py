"""Log file format.

A PadMaster log is a gzip-compressed CSV file.

* Lines that start with ``#`` hold JSON metadata (device name, mode, start time).
* Each data row is ``t_ms,kind,name,value``:

  - ``t_ms``  milliseconds since the start of the session (float, 3 decimals)
  - ``kind``  ``a`` axis, ``b`` button, ``c`` connection, ``p`` guided-test prompt
              (``name`` is the prompt key, ``value`` its number in the schedule)
  - ``name``  normalised signal name, for example ``lx``, ``rt``, ``a``, ``up``
  - ``value`` raw integer value. Sticks: -32768..32767. Triggers: 0..32767.
              Buttons: 1 (down) or 0 (up). Connection: 1 (connected) or 0 (lost).

Raw integers are kept on purpose, so the analysis can see the exact smallest
value the controller reports (this is how hidden deadzones show up).
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from typing import Iterator, TextIO

STICK_AXES = ("lx", "ly", "rx", "ry")
TRIGGER_AXES = ("lt", "rt")
DPAD_BUTTONS = ("up", "down", "left", "right")
FACE_AND_SHOULDER = ("a", "b", "x", "y", "lb", "rb", "ls", "rs", "back", "start")
PADDLES = ("p1", "p2", "p3", "p4")

AXIS_MAX = 32767.0


@dataclass(slots=True)  # slots: about half the memory for long sessions (user report, 2026-11-19)
class Event:
    t: float  # ms
    kind: str
    name: str
    value: int


@dataclass
class Log:
    meta: dict = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        if not self.events:
            return 0.0
        end = self.meta.get("ended_ms")
        return float(end) if end is not None else self.events[-1].t


class LogWriter:
    """Writes rows to a gzip CSV. Call ``flush`` often so a crash loses little data."""

    def __init__(self, path: str, meta: dict):
        self.path = path
        self._fh: TextIO = gzip.open(path, "wt", encoding="utf-8", newline="")
        self._fh.write("# " + json.dumps(meta) + "\n")
        self._buf: list[str] = []

    def write(self, t_ms: float, kind: str, name: str, value: int) -> None:
        self._buf.append(f"{t_ms:.3f},{kind},{name},{int(value)}\n")

    def meta(self, meta: dict) -> None:
        self._buf.append("# " + json.dumps(meta) + "\n")

    def flush(self) -> None:
        if self._buf:
            self._fh.write("".join(self._buf))
            self._buf.clear()
        self._fh.flush()

    def close(self) -> None:
        self.flush()
        self._fh.close()


def _iter_lines(path: str) -> Iterator[str]:
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:  # type: ignore[operator]
        try:
            yield from fh
        except (EOFError, OSError):
            # The file was not closed cleanly (crash or power cut). Keep what we read.
            return


def read_log(path: str) -> Log:
    log = Log()
    names: dict[str, str] = {}
    for line in _iter_lines(path):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            try:
                log.meta.update(json.loads(line[1:].strip()))
            except json.JSONDecodeError:
                pass
            continue
        parts = line.split(",")
        if len(parts) != 4:
            continue  # a cut-off last line after a crash
        try:
            # Share one string object per kind and name. Millions of rows reuse the same few names.
            k = names.setdefault(parts[1], parts[1])
            n = names.setdefault(parts[2], parts[2])
            log.events.append(Event(float(parts[0]), k, n, int(parts[3])))
        except ValueError:
            continue
    log.events.sort(key=lambda e: e.t)
    return log
