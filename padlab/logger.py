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

    def describe(self) -> dict:
        return {
            "device": self.name,
            "guid": self.guid,
            "mode": "controller" if self.mapped else "joystick",
            "axes": self.joystick.get_numaxes(),
            "buttons": self.joystick.get_numbuttons(),
            "hats": self.joystick.get_numhats(),
        }


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


def run(out_dir: str, pad_index: int = 0, seconds: float | None = None) -> str:
    """Log until Ctrl+C (or ``seconds``). Returns the log file path."""
    pygame, controller = _import_pygame()
    pygame.init()
    controller.init()
    pygame.joystick.init()

    print(f"PadLab {__version__}. Waiting for a controller...")
    while pygame.joystick.get_count() <= pad_index:
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
    writer = LogWriter(path, meta)

    print(f"Logging: {pad.name}  ({meta['mode']} mode)")
    if not pad.mapped:
        print("  Note: SDL has no mapping for this pad. Stick and trigger names are guesses.")
    print(f"  Log file: {path}")
    print("\n  1. Put the controller down for 10 seconds (hands-off drift check).")
    print("  2. Play your game. PadLab keeps logging in the background.")
    print("  3. Come back to this window and press Ctrl+C to stop and make the report.\n")

    t0 = time.perf_counter()
    last_flush = last_status = t0
    n_events = 0
    disconnects = 0
    connected = True

    try:
        while True:
            events = pygame.event.get()
            now = time.perf_counter()
            t_ms = (now - t0) * 1000.0

            for ev in events:
                inst = getattr(ev, "instance_id", None)
                if ev.type == pygame.CONTROLLERAXISMOTION and pad.mapped and inst == pad.instance_id:
                    name = CONTROLLER_AXES.get(ev.axis)
                    if name:
                        writer.write(t_ms, "a", name, ev.value)
                        n_events += 1
                elif ev.type in (pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERBUTTONUP) and pad.mapped and inst == pad.instance_id:
                    name = CONTROLLER_BUTTONS.get(ev.button, f"btn{ev.button}")
                    writer.write(t_ms, "b", name, 1 if ev.type == pygame.CONTROLLERBUTTONDOWN else 0)
                    n_events += 1
                elif ev.type == pygame.JOYAXISMOTION and not pad.mapped and inst == pad.instance_id:
                    # Unmapped pad: guess the common layout (0,1 left stick, 2,3 right stick).
                    guess = {0: "lx", 1: "ly", 2: "rx", 3: "ry"}.get(ev.axis, f"j{ev.axis}")
                    writer.write(t_ms, "a", guess, int(round(ev.value * 32767)))
                    n_events += 1
                elif ev.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP) and not pad.mapped and inst == pad.instance_id:
                    writer.write(t_ms, "b", f"jb{ev.button}", 1 if ev.type == pygame.JOYBUTTONDOWN else 0)
                    n_events += 1
                elif ev.type == pygame.JOYHATMOTION and not pad.mapped and inst == pad.instance_id and ev.hat == 0:
                    for name, val in _hat_rows(pad.hat, tuple(ev.value)):
                        writer.write(t_ms, "b", name, val)
                        n_events += 1
                    pad.hat = tuple(ev.value)
                elif ev.type == pygame.JOYDEVICEREMOVED and inst == pad.instance_id:
                    writer.write(t_ms, "c", "pad", 0)
                    disconnects += 1
                    connected = False
                    print(f"  [{t_ms / 1000:8.1f}s] Controller lost.")
                elif ev.type == pygame.JOYDEVICEADDED and not connected:
                    # Re-open the first device with the same GUID.
                    for i in range(pygame.joystick.get_count()):
                        if pygame.joystick.Joystick(i).get_guid() == pad.guid:
                            pad = _Pad(pygame, controller, i)
                            writer.write(t_ms, "c", "pad", 1)
                            connected = True
                            print(f"  [{t_ms / 1000:8.1f}s] Controller back.")
                            break

            if now - last_flush >= FLUSH_EVERY_S:
                writer.flush()
                last_flush = now
            if now - last_status >= STATUS_EVERY_S:
                mins = (now - t0) / 60
                print(f"  {mins:6.1f} min   {n_events:9d} inputs   {disconnects} disconnects", end="\r")
                last_status = now
            if seconds is not None and now - t0 >= seconds:
                break
            time.sleep(POLL_SLEEP_S)
    except KeyboardInterrupt:
        pass
    finally:
        ended_ms = (time.perf_counter() - t0) * 1000.0
        writer.meta({"ended_ms": round(ended_ms, 3)})
        writer.close()
        pygame.quit()
        print("\nStopped.")

    return path
