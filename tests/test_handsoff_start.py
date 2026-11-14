"""Regression: hands-off check was "not done" on a real Xbox pad.

Cause: SDL sends no axis event while a stick does not move. In a real log the first
stick row came 31 s after the start, so no rest window covered the hands-off time.
Fix: the logger writes the start value of each axis at t=0.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from padlab.analysis import analyse  # noqa: E402
from padlab.logfile import Event, Log  # noqa: E402


def _play_rows(start_ms: float) -> list[Event]:
    ev = []
    for i in range(400):  # circles on the left stick, 4 ms per report
        a = i / 40 * 2 * math.pi
        t = start_ms + i * 4
        ev.append(Event(t, "a", "lx", int(30000 * math.cos(a))))
        ev.append(Event(t, "a", "ly", int(30000 * math.sin(a))))
    return ev


def test_start_rows_give_handsoff_window():
    start = [Event(0.0, "a", n, 0) for n in ("lx", "ly", "rx", "ry", "lt", "rt")]
    log = Log(meta={"ended_ms": 40000}, events=start + _play_rows(31000))
    ho = analyse(log).sticks["l"]["handsoff"]
    assert ho is not None and ho["t"] == 0.0 and ho["dur"] >= 30000


def test_without_start_rows_no_handsoff():
    # Documents the old behaviour, so the cause stays clear.
    log = Log(meta={"ended_ms": 40000}, events=_play_rows(31000))
    assert analyse(log).sticks["l"]["handsoff"] is None
