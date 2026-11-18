"""Background controller logger.

Uses SDL2 (through pygame-ce) with SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS=1, so the
logger keeps receiving controller input while a game has focus.

The logger only READS the controller. It does not inject input and does not touch
the game process.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime

# Must be set before SDL starts.
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from . import __version__  # noqa: E402
from .logfile import LogWriter  # noqa: E402

# SDL_GameControllerAxis values.
CONTROLLER_AXES = {0: "lx", 1: "ly", 2: "rx", 3: "ry", 4: "lt", 5: "rt"}

# SDL_GameControllerButton values (SDL 2.0.14+).
CONTROLLER_BUTTONS = {
    0: "a", 1: "b", 2: "x", 3: "y",
    4: "back", 5: "guide", 6: "start",
    7: "ls", 8: "rs", 9: "lb", 10: "rb",
    11: "up", 12: "down", 13: "left", 14: "right",
    15: "misc", 16: "p1", 17: "p2", 18: "p3", 19: "p4", 20: "touchpad",
}

POLL_SLEEP_S = 0.0005  # about 1 kHz loop. Sets the timing precision of the log.
FLUSH_EVERY_S = 1.0
STATUS_EVERY_S = 5.0
LOOP_RATE_WINDOW_S = 10.0  # measure loop passes per second over the first 10 s


def _import_pygame():
    try:
        import pygame  # pygame-ce provides the "pygame" module
        from pygame._sdl2 import controller
    except ImportError as exc:  # pragma: no cover - depends on the user's install
        sys.exit(
            "pygame-ce is not installed. Run:  pip install pygame-ce\n"
            f"(details: {exc})"
        )
    return pygame, controller


def list_devices() -> list[dict]:
    pygame, controller = _import_pygame()
    pygame.init()
    controller.init()
    out = []
    for i in range(pygame.joystick.get_count()):
        js = pygame.joystick.Joystick(i)
        out.append(
            {
                "index": i,
                "name": js.get_name(),
                "guid": js.get_guid(),
                "mapped": bool(controller.is_controller(i)),
            }
        )
    pygame.quit()
    return out


class _Pad:
    """One open device. Prefers the SDL GameController mapping (same names for all pads)."""

    def __init__(self, pygame, controller, index: int):
        self.index = index
        self.joystick = pygame.joystick.Joystick(index)
        self.instance_id = self.joystick.get_instance_id()
        self.name = self.joystick.get_name()
        self.guid = self.joystick.get_guid()
        self.mapped = bool(controller.is_controller(index))
        self.controller = controller.Controller(index) if self.mapped else None
        self.hat = (0, 0)

    def axis_snapshot(self) -> list[tuple[str, int]]:
        """Current raw value of each axis.

        SDL sends axis events only when a value changes. A stick that does not move
        at the start gives no rows, so the analysis can't see the hands-off window.
        These rows give the start value.
        """
        if self.mapped:
            return [(name, int(self.controller.get_axis(i))) for i, name in CONTROLLER_AXES.items()]
        guess = {0: "lx", 1: "ly", 2: "rx", 3: "ry"}
        return [
            (guess.get(i, f"j{i}"), int(round(self.joystick.get_axis(i) * 32767)))
            for i in range(self.joystick.get_numaxes())
        ]

    def describe(self) -> dict:
        return {
            "device": self.name,
            "guid": self.guid,
            "mode": "controller" if self.mapped else "joystick",
            "axes": self.joystick.get_numaxes(),
            "buttons": self.joystick.get_numbuttons(),
            "hats": self.joystick.get_numhats(),
            "power": self.power(),
        }

    def power(self) -> str | None:
        """SDL power level ("low", "full", "wired"...). None if this pygame-ce version can't read it."""
        try:
            return str(self.joystick.get_power_level())
        except Exception:
            return None


def _hat_rows(old: tuple[int, int], new: tuple[int, int]) -> list[tuple[str, int]]:
    """Turn a hat (x, y) change into D-pad button rows. SDL hat y: +1 is up."""
    rows = []
    for name, was, now in (
        ("left", old[0] < 0, new[0] < 0),
        ("right", old[0] > 0, new[0] > 0),
        ("up", old[1] > 0, new[1] > 0),
        ("down", old[1] < 0, new[1] < 0),
    ):
        if was != now:
            rows.append((name, 1 if now else 0))
    return rows


CHECK_AXIS_MIN_INTERVAL_S = 0.1  # at most 10 lines per second per axis
CHECK_AXIS_MIN_CHANGE = 0.02     # print only changes of 2% or more


def _axis_fraction(name: str, raw: int) -> float:
    """Raw SDL value to a fraction: sticks -1..1, triggers 0..1."""
    return max(-1.0, min(1.0, raw / 32767.0))


def check(
    pad_index: int = 0,
    seconds: float | None = None,
    out=print,
    clock=time.perf_counter,
) -> int:
    """Print each input as it happens, to confirm the button and axis names.

    Writes no log file. Stops on Ctrl+C (or after ``seconds``). Returns the number
    of lines printed.
    """
    pygame, controller = _import_pygame()
    pygame.init()
    controller.init()
    pygame.joystick.init()

    out(f"PadMaster {__version__}. Waiting for a controller...")
    while pygame.joystick.get_count() <= pad_index:
        pygame.event.pump()
        time.sleep(0.25)

    pad = _Pad(pygame, controller, pad_index)
    out(f"Checking: {pad.name}  ({'controller' if pad.mapped else 'joystick'} mode)")
    if not pad.mapped:
        out("  Note: SDL has no mapping for this pad. Stick and trigger names are guesses.")
    out("  Press each button once. Move each stick in a full circle.")
    out("  Press Ctrl+C to stop.\n")

    printed = {}   # axis name -> (time, value) of the last printed line
    pending = {}   # axis name -> newest value not printed yet
    lines = 0
    connected = True
    t0 = clock()

    def emit(text: str) -> None:
        nonlocal lines
        out(text)
        lines += 1

    def axis_in(name: str, value: float) -> None:
        pending[name] = value

    try:
        while True:
            events = pygame.event.get()
            for ev in events:
                inst = getattr(ev, "instance_id", None)
                if inst != pad.instance_id:
                    # SDL also sends JOYDEVICEADDED at start for a pad that is
                    # already connected. Report it only after a "lost" line.
                    if ev.type == pygame.JOYDEVICEADDED and not connected:
                        for i in range(pygame.joystick.get_count()):
                            if pygame.joystick.Joystick(i).get_guid() == pad.guid:
                                pad = _Pad(pygame, controller, i)
                                emit("controller connected")
                                connected = True
                                break
                    continue
                if ev.type == pygame.CONTROLLERAXISMOTION and pad.mapped:
                    name = CONTROLLER_AXES.get(ev.axis)
                    if name:
                        axis_in(name, _axis_fraction(name, ev.value))
                elif ev.type in (pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERBUTTONUP) and pad.mapped:
                    name = CONTROLLER_BUTTONS.get(ev.button, f"btn{ev.button}")
                    emit(f"button {name} {'down' if ev.type == pygame.CONTROLLERBUTTONDOWN else 'up'}")
                elif ev.type == pygame.JOYAXISMOTION and not pad.mapped:
                    name = {0: "lx", 1: "ly", 2: "rx", 3: "ry"}.get(ev.axis, f"j{ev.axis}")
                    axis_in(name, max(-1.0, min(1.0, float(ev.value))))
                elif ev.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP) and not pad.mapped:
                    emit(f"button jb{ev.button} {'down' if ev.type == pygame.JOYBUTTONDOWN else 'up'}")
                elif ev.type == pygame.JOYHATMOTION and not pad.mapped and ev.hat == 0:
                    for name, val in _hat_rows(pad.hat, tuple(ev.value)):
                        emit(f"button {name} {'down' if val else 'up'}")
                    pad.hat = tuple(ev.value)
                elif ev.type == pygame.JOYDEVICEREMOVED:
                    emit("controller lost")
                    connected = False

            now = clock()
            for name, value in list(pending.items()):
                last_t, last_v = printed.get(name, (None, None))
                if last_v is not None and abs(value - last_v) < CHECK_AXIS_MIN_CHANGE:
                    del pending[name]
                    continue
                if last_t is not None and now - last_t < CHECK_AXIS_MIN_INTERVAL_S:
                    continue  # keep it pending; print it when the interval has passed
                emit(f"axis {name} {value:.2f}")
                printed[name] = (now, value)
                del pending[name]

            if seconds is not None and now - t0 >= seconds:
                break
            time.sleep(POLL_SLEEP_S)
    except KeyboardInterrupt:
        pass
    finally:
        pygame.quit()
        out("\nStopped.")
    return lines


IPC_STATUS_EVERY_S = 1.0


def stdin_stop_watcher(flag: dict, stream=None) -> None:
    """Background thread: set ``flag["stop"]`` on a 'stop' line or at end of input."""
    import threading

    def watch():
        src = stream if stream is not None else sys.stdin
        try:
            for line in src:
                if line.strip().lower() == "stop":
                    break
        except (OSError, ValueError):
            pass
        flag["stop"] = True

    threading.Thread(target=watch, daemon=True).start()


def emit(obj: dict) -> None:
    """Write one JSON status line for the app window."""
    import json
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


CONNECTIONS = ("Wired", "Dongle", "Bluetooth")


IDLE_MOVE = 0.08  # stick/trigger movement (share of full range) that counts as use


def run(out_dir: str, pad_index: int = 0, seconds: float | None = None,
        ipc: bool = False, stop_flag: dict | None = None, label: str = "",
        connection: str = "", idle_stop_s: float | None = None) -> str:
    """Log until Ctrl+C, a stop request, ``seconds``, or ``idle_stop_s`` with no use.
    Returns the log file path.

    No use means no button press and no stick or trigger movement larger than
    IDLE_MOVE of the full range. Small noise from a drifting stick does not count as use.

    IPC mode (used by the app window): no text for people on stdout. One JSON status
    line per second instead, for example
    {"state": "logging", "t": 12.0, "inputs": 345, "disconnects": 0}.
    Returns "" if stopped before a controller was found.
    """
    say = (lambda *a, **k: None) if ipc else print
    if stop_flag is None:
        stop_flag = {"stop": False}
        if ipc:
            stdin_stop_watcher(stop_flag)
    pygame, controller = _import_pygame()
    pygame.init()
    controller.init()
    pygame.joystick.init()

    say(f"PadMaster {__version__}. Waiting for a controller...")
    while pygame.joystick.get_count() <= pad_index:
        if ipc:
            emit({"state": "waiting"})
        if stop_flag["stop"]:
            pygame.quit()
            return ""
        pygame.event.pump()
        time.sleep(0.25)

    pad = _Pad(pygame, controller, pad_index)
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"padlab_{stamp}.csv.gz")

    meta = {
        "padlab": __version__,
        "started": datetime.now().isoformat(timespec="seconds"),
        "poll_sleep_ms": POLL_SLEEP_S * 1000,
        "platform": sys.platform,
        "sdl": ".".join(str(v) for v in pygame.get_sdl_version()),
        **pad.describe(),
    }
    label = " ".join(str(label or "").split())[:60]
    if label:
        meta["label"] = label  # the name the owner gave this physical pad
    if connection in CONNECTIONS:
        meta["connection"] = connection  # selected by the owner; PadMaster can't detect it
    writer = LogWriter(path, meta)

    say(f"Logging: {pad.name}  ({meta['mode']} mode)")
    if not pad.mapped:
        say("  Note: SDL has no mapping for this pad. Stick and trigger names are guesses.")
    say(f"  Log file: {path}")
    say("\n  1. Put the controller down for 10 seconds (hands-off drift check).")
    say("  2. Play your game. PadMaster keeps logging in the background.")
    say("  3. Come back to this window and press Ctrl+C to stop and make the report.\n")

    pygame.event.pump()
    t0 = time.perf_counter()
    for name, value in pad.axis_snapshot():
        writer.write(0.0, "a", name, value)
    last_flush = last_status = last_ipc = t0
    if ipc:
        emit({"state": "logging", "t": 0.0, "inputs": 0, "disconnects": 0,
              "connected": True, "device": pad.name, "log": path})
    n_events = 0
    disconnects = 0
    connected = True
    loop_passes = 0
    loop_rate_done = False
    last_use = time.perf_counter()
    idle_ref: dict[str, int] = {}
    auto_stopped = False

    def used(kind: str, name: str, value: int) -> None:
        nonlocal last_use
        if kind == "b":
            last_use = time.perf_counter()
            return
        ref = idle_ref.get(name)
        if ref is None or abs(value - ref) > 32767 * IDLE_MOVE:
            if ref is not None:
                last_use = time.perf_counter()
            idle_ref[name] = value

    try:
        while True:
            events = pygame.event.get()
            now = time.perf_counter()
            t_ms = (now - t0) * 1000.0
            loop_passes += 1
            if not loop_rate_done and now - t0 >= LOOP_RATE_WINDOW_S:
                writer.meta({"loop_hz": round(loop_passes / (now - t0), 1)})
                loop_rate_done = True

            for ev in events:
                inst = getattr(ev, "instance_id", None)
                if ev.type == pygame.CONTROLLERAXISMOTION and pad.mapped and inst == pad.instance_id:
                    name = CONTROLLER_AXES.get(ev.axis)
                    if name:
                        writer.write(t_ms, "a", name, ev.value)
                        n_events += 1
                        used("a", name, ev.value)
                elif ev.type in (pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERBUTTONUP) and pad.mapped and inst == pad.instance_id:
                    name = CONTROLLER_BUTTONS.get(ev.button, f"btn{ev.button}")
                    writer.write(t_ms, "b", name, 1 if ev.type == pygame.CONTROLLERBUTTONDOWN else 0)
                    n_events += 1
                    used("b", name, 1)
                elif ev.type == pygame.JOYAXISMOTION and not pad.mapped and inst == pad.instance_id:
                    # Unmapped pad: guess the common layout (0,1 left stick, 2,3 right stick).
                    guess = {0: "lx", 1: "ly", 2: "rx", 3: "ry"}.get(ev.axis, f"j{ev.axis}")
                    writer.write(t_ms, "a", guess, int(round(ev.value * 32767)))
                    n_events += 1
                    used("a", guess, int(round(ev.value * 32767)))
                elif ev.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP) and not pad.mapped and inst == pad.instance_id:
                    writer.write(t_ms, "b", f"jb{ev.button}", 1 if ev.type == pygame.JOYBUTTONDOWN else 0)
                    n_events += 1
                    used("b", "jb", 1)
                elif ev.type == pygame.JOYHATMOTION and not pad.mapped and inst == pad.instance_id and ev.hat == 0:
                    for name, val in _hat_rows(pad.hat, tuple(ev.value)):
                        writer.write(t_ms, "b", name, val)
                        n_events += 1
                        used("b", name, 1)
                    pad.hat = tuple(ev.value)
                elif ev.type == pygame.JOYDEVICEREMOVED and inst == pad.instance_id:
                    writer.write(t_ms, "c", "pad", 0)
                    disconnects += 1
                    connected = False
                    say(f"  [{t_ms / 1000:8.1f}s] Controller lost.")
                elif ev.type == pygame.JOYDEVICEADDED and not connected:
                    # Re-open the first device with the same GUID.
                    for i in range(pygame.joystick.get_count()):
                        if pygame.joystick.Joystick(i).get_guid() == pad.guid:
                            pad = _Pad(pygame, controller, i)
                            writer.write(t_ms, "c", "pad", 1)
                            connected = True
                            say(f"  [{t_ms / 1000:8.1f}s] Controller back.")
                            break

            if now - last_flush >= FLUSH_EVERY_S:
                writer.flush()
                last_flush = now
            if now - last_status >= STATUS_EVERY_S:
                mins = (now - t0) / 60
                say(f"  {mins:6.1f} min   {n_events:9d} inputs   {disconnects} disconnects", end="\r")
                last_status = now
            if ipc and now - last_ipc >= IPC_STATUS_EVERY_S:
                emit({"state": "logging", "t": round(now - t0, 1), "inputs": n_events,
                      "disconnects": disconnects, "connected": connected})
                last_ipc = now
            if stop_flag["stop"]:
                break
            if seconds is not None and now - t0 >= seconds:
                break
            if idle_stop_s and time.perf_counter() - last_use >= idle_stop_s:
                auto_stopped = True
                say(f"\n  No controller use for {idle_stop_s / 60:g} min. Logging stops.")
                break
            time.sleep(POLL_SLEEP_S)
    except KeyboardInterrupt:
        pass
    finally:
        ended_ms = (time.perf_counter() - t0) * 1000.0
        end_meta = {"ended_ms": round(ended_ms, 3)}
        if auto_stopped:
            end_meta["auto_stopped"] = True
            end_meta["idle_stop_s"] = idle_stop_s
        writer.meta(end_meta)
        writer.close()
        pygame.quit()
        say("\nStopped.")

    return path
