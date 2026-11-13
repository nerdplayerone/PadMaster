"""Build a synthetic PadLab log with known faults, for tests and the demo report.

Known faults in the default session:
* Left stick: drift at rest of about 4.5%, cross-shaped (axial) dead band of 10%,
  5 stutters (80 ms gaps during fast circles).
* Right stick: round centre deadzone of 12%, outer reach only 92%, no drift.
* Left trigger: analogue, start deadzone 6%. Right trigger: digital.
* RB: 4 double inputs (8 ms gaps). A: 200 clean presses.
* D-pad: 100 diagonals, 6 flickers. 100 single-direction presses, 5 blips.
* 30 two-button presses (A+B) with 5-25 ms split.
* 1 disconnect, back after 3 s.
"""

from __future__ import annotations

import math
import random

from padlab.logfile import LogWriter

MAX = 32767


def _raw(v: float) -> int:
    return int(round(max(-1.0, min(1.0, v)) * MAX))


def build(path: str, seed: int = 7) -> dict:
    rnd = random.Random(seed)
    ev: list[tuple[float, str, str, int]] = []

    def axis(t, name, v):
        ev.append((t, "a", name, v))

    def left(t, x, y):  # x right+, y up+ (SDL y is down+)
        if abs(x) < 0.10:
            x = 0.0
        if abs(y) < 0.10:
            y = 0.0
        axis(t, "lx", _raw(x))
        axis(t, "ly", _raw(-y))

    def right(t, x, y):
        m = math.hypot(x, y)
        if m < 0.12:
            x = y = 0.0
        axis(t, "rx", _raw(x * 0.92))
        axis(t, "ry", _raw(-y * 0.92))

    # Hands-off: 0-12 s. Left stick rests off centre with noise. Right stick reads 0.
    t = 0.0
    while t < 12000:
        ev.append((t, "a", "lx", _raw(0.04 + rnd.uniform(-0.005, 0.005))))
        ev.append((t, "a", "ly", _raw(0.02 + rnd.uniform(-0.005, 0.005))))
        t += 8
    # (no axial band applied in rest: values below 10% are only zeroed when the other
    # axis is pushed in this simple model, so we keep raw rest noise visible)

    # Movement: 12-120 s. Circles, sweeps, plus 5 stutters on the left stick.
    stutter_at = {20000, 35000, 50000, 65000, 82000}
    t = 12000.0
    while t < 120000:
        phase = (t / 700.0)
        r = 1.0 if (int(t / 5000) % 2 == 0) else 0.6 + 0.4 * math.sin(t / 1300)
        lx, ly = r * math.cos(phase), r * math.sin(phase)
        rx, ry = math.cos(phase * 0.8) * r, math.sin(phase * 0.8) * r
        if any(abs(t - s) < 4 for s in stutter_at):
            t += 80  # gap: no reports
            continue
        left(t, lx, ly)
        right(t, rx, ry)
        t += 8
    # Small slow moves near centre for the right stick (to show its deadzone).
    t = 120000.0
    while t < 130000:
        a = t / 500
        rr = 0.05 + 0.25 * (t - 120000) / 10000
        right(t, rr * math.cos(a), rr * math.sin(a))
        t += 8
    # Back to rest
    left(130000, 0, 0)
    right(130000, 0, 0)

    # Triggers
    t = 131000.0
    for _ in range(40):
        for k in range(0, 21):
            v = k / 20
            ev.append((t, "a", "lt", 0 if v < 0.06 else _raw(v)))
            t += 8
        for k in range(20, -1, -1):
            v = k / 20
            ev.append((t, "a", "lt", 0 if v < 0.06 else _raw(v)))
            t += 8
        ev.append((t, "a", "rt", MAX))
        ev.append((t + 100, "a", "rt", 0))
        t += 200

    def press(name, t_down, held):
        ev.append((t_down, "b", name, 1))
        ev.append((t_down + held, "b", name, 0))

    # Clean A presses
    t = 160000.0
    for _ in range(200):
        press("a", t, rnd.uniform(60, 120))
        t += rnd.uniform(200, 300)
    # RB with 4 double inputs
    t = 220000.0
    for i in range(40):
        press("rb", t, 80)
        if i % 10 == 3:
            press("rb", t + 80 + 8, 20)  # chatter: 8 ms after release
        t += 300

    # D-pad diagonals: up, then left 15 ms later, hold 300 ms. 6 flickers.
    t = 240000.0
    for i in range(100):
        a, b = [("up", "left"), ("up", "right"), ("down", "left"), ("down", "right")][i % 4]
        ev.append((t, "b", a, 1))
        ev.append((t + 15, "b", b, 1))
        if i % 16 == 5:  # flicker: drop b for 10 ms
            ev.append((t + 150, "b", b, 0))
            ev.append((t + 160, "b", b, 1))
        ev.append((t + 315, "b", a, 0))
        ev.append((t + 315, "b", b, 0))
        t += 500
    # Cardinal presses with 5 blips.
    t = 300000.0
    for i in range(100):
        a = ["up", "down", "left", "right"][i % 4]
        ev.append((t, "b", a, 1))
        if i % 20 == 7:
            other = {"up": "left", "down": "right", "left": "down", "right": "up"}[a]
            ev.append((t + 120, "b", other, 1))
            ev.append((t + 132, "b", other, 0))
        ev.append((t + 250, "b", a, 0))
        t += 400

    # Chords A+B
    t = 345000.0
    for _ in range(30):
        sp = rnd.uniform(5, 25)
        ev.append((t, "b", "a", 1))
        ev.append((t + sp, "b", "b", 1))
        ev.append((t + 150, "b", "a", 0))
        ev.append((t + 155, "b", "b", 0))
        t += 600

    # Disconnect
    ev.append((200000.0, "c", "pad", 0))
    ev.append((203000.0, "c", "pad", 1))

    ev.sort(key=lambda r: r[0])
    end = 365000.0
    w = LogWriter(path, {"padlab": "test", "device": "Synthetic Test Pad", "mode": "controller",
                         "started": "2026-11-13T22:00:00", "sdl": "test"})
    for row in ev:
        w.write(*row)
    w.meta({"ended_ms": end})
    w.close()
    return {"end": end}
