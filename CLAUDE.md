# CLAUDE.md: PadMaster project instructions

> Name: the app was called PadLab until v0.1.0. The Python package and the commands stay `padlab` (`python -m padlab`). Old logs are named `padlab_*.csv.gz` and still work.

Read this file fully before you change anything. It tells you what PadMaster is, what works, what is not tested, and the order of work.

## 1. What PadMaster is

PadMaster is a Windows tool that logs a game controller **in the background while the owner plays a game**. When the session stops, PadMaster makes an HTML report that shows controller faults that players complain about:

- hidden centre deadzones and cross-shaped (axial) deadzones on the sticks
- stick drift at rest, and a "safe in-game deadzone" value
- outer reach of the sticks (do they get to 100% in all directions)
- stutter / data gaps while a stick moves (wireless dropouts)
- trigger start deadzone, full pull, analogue or digital
- double inputs (button chatter)
- D-pad diagonal flicker and accidental diagonal blips
- D-pad diagonal split time and two-button split time (info only)
- disconnects

The owner makes controller review videos. The report must be **accurate, readable on camera, and honest about its limits**. The event-time list in the report lets the owner find each fault in his gameplay recording.

PadMaster does **not** measure true input latency. That needs hardware. Do not add any feature that claims to measure it.

## 2. How the owner works (read this)

- Write all user-facing text (UI, console messages, report text, README) in **ASD-STE100 Simplified Technical English**: short sentences, active voice, one instruction per sentence.
- Use **British English** (colour, analyse, licence) in UI and docs.
- **Never use em dashes** in any text the owner sees. Use a colon, a full stop or brackets.
- **Sans-serif fonts only** in all visual output.
- Give a clear recommendation, the reason, and the next action. Do not give long lists of options.
- Label each claim: **tested** (you ran it and saw the result), **inference** (you think it is true), or **untested**.
- Do not say a thing works if you did not run it. If you can't test something (for example, no controller connected), say so plainly.
- Explain each step in plain words. Assume the owner is technical but is not a Python developer.
- Ask before you install software outside the project virtual environment, and before you change system settings.

## 3. Current state

### Files

```
padlab/
  __init__.py      version
  __main__.py      python -m padlab
  cli.py           commands: log (default), report, list, check, gui; log --ipc for the GUI
  gui.py           app window (pywebview): starts 'log --ipc' as a child process, reads JSON status lines
  app.html         the app page: sidebar, History, Compare, Report
  history.py       session history cache, controller names, settings, CSV export
  theme.py         SCROLLBAR_CSS (the only scroll bar style)
  branding.py      the owner's channel links
  logger.py        background logger (SDL2 via pygame-ce)
  logfile.py       log format: gzip CSV, read and write
  analysis.py      all checks and THRESHOLDS (pure Python, no numpy)
  report.py        self-contained HTML report (inline SVG, light and dark)
tests/
  synth.py         synthetic log with KNOWN faults
  test_analysis.py checks that analysis finds the known faults, and no false alarms
  test_logger_smoke.py  runs the logger loop against a FAKE pygame
tools/make_sample.py     makes docs/sample_report.html
.github/workflows/build.yml  tests on Ubuntu, builds PadMaster.exe on Windows, attaches to release on v* tags
run_padlab.py      PyInstaller entry point
```

### Log format (do not break it)

gzip CSV. Lines that start with `#` are JSON metadata. Data rows are `t_ms,kind,name,value`:

- `kind`: `a` axis, `b` button, `c` connection
- `name`: `lx ly rx ry lt rt` for axes. Buttons use SDL GameController names: `a b x y back guide start ls rs lb rb up down left right misc p1 p2 p3 p4 touchpad`. Unmapped pads use `jb0`, `jb1`...
- `value`: **raw integer**. Sticks -32768..32767 (SDL: y down is positive). Triggers 0..32767. Buttons 1/0. Connection 1/0.

Raw integers are kept on purpose. The inner deadzone check needs the exact smallest value the pad reports. If you must change the format, add a `format` version number to the metadata and keep `read_log` able to read old logs.

### What is tested

- **Tested:** analysis on synthetic logs (known faults found, no false alarms for fast mashing, slow low-resolution stick movement, or hold-then-flick). The logger loop against a fake pygame module. All 15 tests passed on Linux, Python 3.13.
- **Untested:** the logger on a real Windows PC with a real controller. The GitHub Actions build. The PyInstaller .exe. Background input while a game has focus.
- **Inference (needs checking):** pygame-ce exposes `pygame._sdl2.controller` with `is_controller`, `Controller`, and `CONTROLLER*` events with `instance_id`, `axis`, `button`, `value` attributes. SDL button numbers 16 to 20 (paddles, touchpad) are correct for the bundled SDL version.

## 4. Hard rules

1. PadMaster only **reads** the controller. Never send input, never use virtual controller drivers, never hook, read or inject into a game process. (Anti-cheat safety.)
2. No network access in the app, with one exception: the update check (owner decision, 2026-11-17). It asks GitHub for the latest release version, on a click or once a day at start (the user can turn the start check off). It sends no user data and downloads nothing: the user downloads the new .exe in the browser. No telemetry. No auto-install. "Report a bug" only opens a draft (email if `BUG_EMAIL` in `branding.py` is set, else a GitHub issue); the user sends it. (`tools/fetch_gamepadla.py` runs only on the developer PC before a release. The app never connects to Gamepadla.)
3. No admin rights needed. No drivers.
4. The analysis stays pure Python (standard library only). The .exe must stay small.
5. Keep all tests passing. Add a test for every bug you fix.
6. OK / Watch / Problem limits live only in `THRESHOLDS` in `analysis.py`. The report must keep saying they are defaults, not industry standards.
7. Never commit real logs or reports (`*.csv.gz`, `*_report.html`). They can contain long play sessions. `.gitignore` already blocks them.
8. Do not add a dependency without asking the owner first. Runtime dependencies: `pygame-ce` and `pywebview` (approved by the owner on 2026-11-14, for the app window and the report inside the app).
9. Make small commits with clear messages. Do not push to GitHub until the owner says so.

## 5. Work order

Do the phases in order. Stop at the end of each phase and report to the owner (see section 7). Do not start the next phase until the owner agrees.

---

### Phase 1: set up and run the tests on Windows

1. Check Python: `py --version`. Use Python 3.12 if it is available (the GitHub build uses 3.12).
2. Make a virtual environment in the project folder: `py -3.12 -m venv .venv`, then `.venv\Scripts\activate`.
3. `pip install -r requirements.txt pytest pyinstaller`
4. `python -m pytest -q`. All tests must pass.
5. Record the installed pygame-ce version and the SDL version: `python -c "import pygame; print(pygame.version.ver, pygame.get_sdl_version())"`.
6. Check the inference in section 3: `python -c "from pygame._sdl2 import controller; import pygame; print(controller.is_controller, pygame.CONTROLLERAXISMOTION, pygame.CONTROLLERBUTTONDOWN)"`. If this fails, find the correct API for the installed pygame-ce version and fix `logger.py`. Then pin the working version range in `requirements.txt` and `pyproject.toml`.

**Done when:** tests pass on Windows, and the controller API is confirmed or fixed.

---

### Phase 2: real controller smoke test

**2a. Add a live input check command first.** Add `padlab check`: it opens the controller and prints each input as it happens, in one line per event, for example `button a down`, `axis lx 0.43`. Throttle axis printing (for example, at most 10 lines per second per axis, or only changes larger than 2%). The owner uses this to confirm the mapping. Add a unit test with the fake pygame from `test_logger_smoke.py`.

**2b. Mapping check with the owner.** Ask the owner to:

1. Run `python -m padlab list`. Record the name, the GUID and whether the pad shows `mapped`.
2. Run `python -m padlab check`. Press each button once, in this order: A, B, X, Y, LB, RB, LT, RT, back, start, L3, R3, D-pad up, down, left, right, paddles (if any). Move each stick in a full circle.
3. Confirm that each name is correct.

**2c. Background test (this is the main risk).**

1. Run `python -m padlab log`.
2. Put the pad down for 10 seconds.
3. Start a game in **fullscreen**, then in **borderless window**. Play 2 minutes in each.
4. Check that the "inputs" number on the status line goes up while the game has focus. (The owner can look at it after alt-tab. The number must be higher than before the game started.)
5. Stop with Ctrl+C. Check that the report opens.

If input stops while the game has focus:

- Confirm that `SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS=1` is set **before** pygame is imported (it is set at the top of `logger.py`).
- Check whether Steam Input, DS4Windows, DSX or similar tools are running. Ask the owner to close them and test again.
- Try `SDL_HINT_JOYSTICK_RAWINPUT=0` and, separately, `SDL_JOYSTICK_HIDAPI=0` to see if a different SDL driver works in the background. Record which combination works for which pad.
- Report the result to the owner before you change the design.

**2d. Connection types.** If the owner has them, repeat a 2-minute log for: wired, 2.4 GHz dongle, Bluetooth. Record the "update interval while moving" in each report. (Expected, inference: wired and dongle about 1 to 8 ms, Bluetooth often slower.)

**2e. Known risks to check:**

| Risk | What to check |
|---|---|
| Ctrl+C in the .exe console | Does the report still get written? If not, also stop on a key press (for example `q` + Enter via a background stdin thread). |
| Hands-off check | The report shows "Rest offset, hands-off check". If it says "not done", the rest detection did not find the 10-second window. Fix `rest_windows` with the real data. |
| Same timestamps | All events from one `pygame.event.get()` call get the same time. Check that D-pad split time is not always 0 ms because of this. |
| `time.sleep` resolution | Python 3.11+ on Windows uses a high-resolution timer. Check the real loop rate: log how many loop passes happen per second for 10 seconds. Record it in the metadata. |
| Xbox pads (XInput) | Triggers can be combined on some drivers. Check that `lt` and `rt` are separate. |
| PlayStation / Switch pads | Check that they show `mapped`, and that the A/B mapping matches the position (SDL uses the Xbox position names). Write the result in the README. |
| Pad turns off and on | Check that the `c` rows appear and that logging continues after the pad comes back. |

**Done when:** at least one pad logs correctly in the background in a real game, and the mapping is confirmed. Write the results into `docs/hardware_results.md` (pad, connection, SDL driver, background works yes/no, notes).

---

### Phase 3: tune the analysis with real data

1. Ask the owner for logs from: one pad he thinks is good, and one pad with a known fault (he has seen D-pad diagonal problems on at least one pad).
2. Run `python -m padlab report <log>` on each. Compare the results with what the owner feels in the hand.
3. For each false alarm or missed fault:
   - Find the cause in the data. Show the owner the event times and values.
   - Fix the logic or the threshold.
   - Add a regression test. Cut a **small** anonymous part of the real log (a few seconds around the event) into `tests/data/`. Only button and axis rows. No metadata with device serials.
4. Watch these known weak points:
   - **Rest detection** can treat a thumb that holds the stick still at low tilt as "rest". This makes drift look worse. The hands-off check at the start is the main source for that reason.
   - **Inner deadzone** can't see a deadzone that rescales its output. The report already says this. Keep that text.
   - **Axial band** needs enough samples where one axis is pushed past 25%. Check that racing games or games with little stick use don't give false results.
   - **Stutter** must not flag low-resolution pads or hold-then-flick moves (tests exist for both). Check with real Bluetooth data.
   - **Double inputs** threshold is 20 ms release-to-press. Check fast mashing in a real game (for example, a fighting game) does not trigger it.
5. Do not change a threshold only to make a pad look good or bad. Each change must have a reason the owner can repeat on camera.

**Done when:** the good pad shows no Problems that the owner can't feel, and the faulty pad shows the fault he knows.

---

### Phase 4: GUI

Requirements (in this order of importance):

1. The app window is a local page (`padlab/app.html`) shown with `pywebview` (Edge WebView2). It loads nothing from the internet. The report opens inside the app (owner request, 2026-11-14). The HTML report file is still saved next to each log.
1b. **History:** a list of every session in the logs folder (`padlab/history.py`), with CSV export. `history.json` is only a cache; the logs are the source of truth.
1c. **Controller name:** before Start, the owner types or selects which physical pad this is ("Which controller is this?"). It defaults to the last name used. The logger writes it to the metadata as `label`. Sessions with a name group by that name; sessions without one group by model GUID. Renaming a session renames every session in its group (owner request, 2026-11-14). The owner also selects the connection (Wired, Dongle, Bluetooth; default: the last one). It is stored as `connection` in the metadata and shown in History, the report and Compare. PadMaster can't detect it itself.
2. **Start / Stop** button. Players must not need Ctrl+C.
3. A **10-second countdown** at the start: "Put the controller down." Then "Logging. Play your game."
4. **Live counters:** time logged, inputs, disconnects. The input counter shows the owner that background logging works.
5. A **controller dropdown** (from `list_devices`), with a refresh button.
6. **Open last report** and **Open logs folder** buttons.
7. **Always-on-top** option, off by default.
8. Black and silver theme to match the owner logo, sans-serif font (Segoe UI on Windows). The report uses the same theme (light only for print).
9. Window and taskbar icon: the owner logo (`assets/padlab.ico`, set with `iconbitmap`). Bundle the .ico in the .exe with `--add-data`.

Architecture (recommendation and reason):

- Run the SDL logger in a **separate process**, not a thread. Start it with `python -m padlab log --ipc` (or the frozen .exe with the same arguments). The logger writes one JSON status line per second to stdout (`{"t": 12.0, "inputs": 345, "disconnects": 0, "state": "logging"}`). The GUI reads these lines.
- Stop the logger with a `stop` line on its stdin, not with a signal. The logger then writes the report and prints `{"state": "done", "report": "<path>"}`.
- Reason: SDL event handling and tkinter both want to own the main thread. Separate processes avoid this problem, and a GUI freeze can't stop the logging.
- Keep the console mode working (`padlab log` without `--ipc`). It is useful for testing.
- The .exe opens the GUI by default when started with no arguments. Use `--windowed` in PyInstaller for the GUI build. Keep a console build too, for debugging. It goes only in the Actions run artefacts, not in releases (owner request, 2026-11-14).

**Done when:** the owner can start, play, stop and open the report without the console.

---

### Phase 5 (later, only when the owner asks): guided test mode

A 5-minute guided run for the tests that need to know what the player meant to press. Plan only, do not build without approval:

1. Hands off, 30 s: drift, centre error, mapping.
2. Sticks, 60 s: slow circles, fast circles, slow push to the edge in 8 directions.
3. Triggers, 30 s: slow pull and release, 3 times each.
4. Prompt game, 2 to 3 min: random on-screen prompts for D-pad directions, quarter circles, single buttons and button pairs. Measures diagonal hit rate, accidental diagonals, roll test and chord reliability.

The guided run reuses the same log format and analysis, plus a prompt track (`kind = p`) that records what was asked and when.

---

### Phase 6: release

1. The owner makes the GitHub repo **private** first.
2. Push. Check that the GitHub Actions run is green and that `PadMaster.exe` is in the run artefacts.
3. The owner downloads the .exe and repeats the Phase 2c test with it (not with Python).
4. Check Windows SmartScreen and Defender. An unsigned PyInstaller one-file .exe can show a warning (inference). Write what the owner sees in the README, with the steps to run it. Do not tell users to turn off their antivirus.
5. Update the README: remove "not tested on real hardware" only for the pads in `docs/hardware_results.md`. Keep a list of tested pads.
6. Tag `v0.1.0`. Check that the release has the .exe.
7. The owner decides when to make the repo public.

## 6. Coding standards

- Python 3.10+. Type hints on public functions.
- Keep `analysis.py` free of pygame imports, so tests run without a controller.
- Each new check in `analysis.py` needs: a `THRESHOLDS` entry, a `Finding` with a plain-English `detail` text, a synthetic test with a known fault, and a test that a clean log gives no false alarm.
- The report stays one self-contained HTML file (no CDN, no web fonts, no JavaScript needed to read it). SVG `<title>` elements give hover values.
- Scroll bars: every scroll bar (app window, report, any new page) uses `SCROLLBAR_CSS` from `padlab/theme.py` (owner request, 2026-11-14). Do not style scroll bars anywhere else. A test checks this.
- Report colours: use the CSS variables already in `report.py`. Status always shows an icon and a word, never colour alone.
- Run `python -m pytest -q` and `python tools/make_sample.py` before each commit. Look at the sample report after any report change.

## 7. How to report back to the owner

At the end of each phase, give:

1. **Result:** one or two sentences. What works now.
2. **Tested / untested:** a short list, with labels.
3. **Problems found:** each one with the cause (if known) and the fix, or "not fixed yet".
4. **Decision needed:** only if there is one. Give your recommendation and the reason.
5. **Next action:** one line.

No long logs in the message. Put long output in a file and give the file name.

## 8. Do not

- Do not claim latency numbers as PadMaster's own results.
- Gamepadla latency data (owner decision, 2026-11-14): show it only in its own box, "Hardware latency (data: Gamepadla.com)", with full credit, a link to the Gamepadla page, the collection date and the note that newer results can exist. Never mix it with PadMaster's checks, and never compare the two as if they used the same method. If Gamepadla asks for the data to be removed, remove it in the next release.
- `tools/fetch_gamepadla.py` reads only pages that Gamepadla's robots.txt allows, at one page every 3 s.
- Do not add third-party brand names, logos or controller product images to the app or report. The owner's own logo (`assets/logo.png`) is allowed.
- Do not push, tag or make the repo public without the owner's approval.
- Do not delete the owner's logs.
