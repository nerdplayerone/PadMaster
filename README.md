# PadLab

PadLab logs your game controller in the background **while you play**. When you stop, it makes a report that shows hidden deadzones, drift, D-pad flicker, double inputs and wireless stutter.

You don't need to do test routines. Play as normal, then read the report.

![Sample report](docs/sample_report.png)

> **Status: early version, not tested on real hardware yet.** The analysis is tested with synthetic logs that contain known faults (see `tests/`). The logger has not run on a Windows PC with a real controller yet. Please report problems in Issues.

## What it checks

| Area | Check | How |
|---|---|---|
| Sticks | Drift at rest | 10-second hands-off check at the start, plus moments in play when you don't touch the stick |
| Sticks | Safe in-game deadzone | Rest offset plus a 2% margin |
| Sticks | In-built centre deadzone | The smallest movement out of centre that the pad ever reports |
| Sticks | Cross-shaped deadzone / snapping | The dead band on one axis while the other axis is pushed |
| Sticks | Outer reach | The maximum value at full tilt in 36 directions |
| Sticks | Stutter while moving | Gaps in the data during continuous movement |
| Triggers | Start deadzone, full pull, analogue or digital | The smallest and largest values, the number of different values |
| Buttons | Double inputs | A new press less than 20 ms after a release (a hand can't do that) |
| D-pad | Diagonal flicker | A held diagonal drops to one direction for less than 35 ms |
| D-pad | Accidental diagonal blips | A diagonal shows for less than 35 ms during a single-direction press |
| D-pad | Diagonal split time | The time between the first and second direction of a diagonal (info) |
| Buttons | Two-button split time | The time between two buttons pressed together (info) |
| Connection | Disconnects | The controller is lost and comes back |

The report also lists the **time of each event**, so you can find it in your gameplay recording.

## What it can't do

- **True input latency.** That needs hardware that presses the buttons. See [Gamepadla](https://gamepadla.com) for that.
- **Know what you meant to press.** PadLab only looks for patterns that a hand doesn't make. For hit-rate tests you need a guided test (planned).
- **Precise timing below about 1 ms.** The logger loop runs at about 1 kHz.
- **Gyro and touchpad.** Not logged in this version.

The OK / Watch / Problem limits are PadLab defaults (judgement calls), not industry standards. You can change them in `THRESHOLDS` in `padlab/analysis.py`.

## Use it (Windows)

### Option A: the .exe

1. Download `PadMaster.exe` from [Releases](../../releases).
2. Connect your controller.
3. Start `PadMaster.exe`. A console window opens.
4. Put the controller down for 10 seconds (hands-off drift check).
5. Play your game. PadLab keeps logging in the background.
6. Go back to the PadLab window and press **Ctrl+C**. The report opens in your browser.

Logs and reports go to `Documents\PadLab`.

### Option B: Python

```
pip install pygame-ce
python -m padlab                  # log, then report
python -m padlab list             # list controllers
python -m padlab log --pad 1      # log the second controller
python -m padlab report FILE.csv.gz
```

## For a clean test

- Turn off Steam Input, DS4Windows, DSX and similar tools. They change what PadLab sees.
- Use the same game, player and connection when you compare two controllers.
- Play for at least 10 minutes. Some checks need more data.
- To test wireless stutter, do one session per setup: dongle at the back of the PC, dongle on a USB extension, Bluetooth, wired.

## How it works

- PadLab uses SDL2 through [pygame-ce](https://github.com/pygame-community/pygame-ce). It sets `SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS=1`, so it gets controller input while the game has focus.
- It uses the SDL GameController mapping, so all mapped pads use the same names (A, B, LB, D-pad up, and so on). For unmapped pads it guesses the stick axes and does not test triggers.
- It only **reads** the controller. It doesn't send input and doesn't touch the game process. The anti-cheat risk is low, but test it in an offline game first.
- The log is a gzip CSV file with raw values (`t_ms,kind,name,value`). See `padlab/logfile.py`.

## Develop

```
pip install pygame-ce pytest
python -m pytest
python tools/make_sample.py       # makes docs/sample_report.html from synthetic data
```

To make a release: push a tag such as `v0.1.0`. GitHub Actions builds `PadMaster.exe` and attaches it to the release.

## Made by

PadMaster is made by the owner of these channels:

- [@iamyourgamingnerd](https://www.youtube.com/@iamyourgamingnerd)
- [@pressstartbynerd](https://www.youtube.com/@pressstartbynerd)

## Licence

MIT. See `LICENSE`.
