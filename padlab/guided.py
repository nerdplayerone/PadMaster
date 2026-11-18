"""Guided test: a fixed schedule of on-screen instructions (owner approval, 2026-11-18).

Every controller gets the same moves, so results are fair to compare. The logger writes
each instruction to the log as a prompt row (kind ``p``) at the time it is shown. The
analysis then knows what the player was asked to press.
"""

from __future__ import annotations

import random

DPAD = {
    "dpad_up": ("↑", ("up",)), "dpad_down": ("↓", ("down",)),
    "dpad_left": ("←", ("left",)), "dpad_right": ("→", ("right",)),
    "dpad_upleft": ("↖", ("up", "left")), "dpad_upright": ("↗", ("up", "right")),
    "dpad_downleft": ("↙", ("down", "left")), "dpad_downright": ("↘", ("down", "right")),
}
BUTTONS = {
    "btn_a": ("A (bottom)", "a"), "btn_b": ("B (right)", "b"),
    "btn_x": ("X (left)", "x"), "btn_y": ("Y (top)", "y"),
    "btn_lb": ("LB", "lb"), "btn_rb": ("RB", "rb"),
}

# (seconds, key, text). Phases first, then the prompt game.
PHASES = [
    (0, "phase_rest", "Put the controller down. Do not touch it."),
    (30, "phase_circles_slow", "Turn both sticks slowly in full circles. Keep them at the edge."),
    (55, "phase_circles_fast", "Turn both sticks fast in full circles."),
    (75, "phase_edges", "Push each stick to the edge and let go. Do this in all directions."),
    (100, "phase_triggers", "Pull both triggers slowly to the end. Then let go slowly. Do this 3 times."),
    (130, "phase_game", "Get ready. Press what you see. Use the D-pad for the arrows."),
]
GAME_START_S = 134.0
GAME_STEP_S = 1.6
GAME_EACH = 24  # cardinal, diagonal and button prompts: this many of each


def schedule(seed: int = 0) -> list[tuple[float, str, str]]:
    """The full guided test. The same seed gives the same order."""
    rng = random.Random(seed)
    card = [k for k in DPAD if len(DPAD[k][1]) == 1]
    diag = [k for k in DPAD if len(DPAD[k][1]) == 2]
    items = [card[i % 4] for i in range(GAME_EACH)] + [diag[i % 4] for i in range(GAME_EACH)] \
        + [list(BUTTONS)[i % 6] for i in range(GAME_EACH)]
    rng.shuffle(items)
    for i in range(1, len(items)):  # no prompt twice in a row
        if items[i] == items[i - 1]:
            j = next((j for j in range(i + 1, len(items)) if items[j] != items[i]), None)
            if j is not None:
                items[i], items[j] = items[j], items[i]
    out = [(float(t), k, txt) for t, k, txt in PHASES]
    for n, k in enumerate(items):
        txt = DPAD[k][0] if k in DPAD else BUTTONS[k][0]
        out.append((GAME_START_S + n * GAME_STEP_S, k, txt))
    out.append((GAME_START_S + len(items) * GAME_STEP_S + 1.0, "end", "Done. Making the report..."))
    return out


def duration_s(seed: int = 0) -> float:
    return schedule(seed)[-1][0]
