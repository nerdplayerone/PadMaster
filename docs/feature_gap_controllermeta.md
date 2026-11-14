# Feature gap: ControllerMeta compared with PadLab

Source: REA static inspection of `ControllerMeta.exe` 1.1.0 (PE imports and the built-in UI text). The program did not run. These are the features that the program shows in its UI. How each one works inside is **inference** until it is decompiled.

## What ControllerMeta is

A native C++ Windows app with a WebView2 (web page) UI. It reads pads through Raw HID, XInput, GameInput and Steam Input. It has 3D pad models, desktop overlays for OBS, and an update checker.

## A. Fits PadLab (read-only, offline analysis, no new dependency)

| Feature in ControllerMeta | PadLab today | Recommendation |
|---|---|---|
| Polling rate distribution (Hz histogram), mean, median, percentiles | Median "update interval while moving" only | Add: histogram and percentile table in the report |
| Jitter of the report interval (standard deviation, MAD) | No | Add, from logged times |
| OS stutter rate | Stutter while moving | Add a rate (stutters per minute) to the existing check |
| Stick noise at rest (standard deviation, max minus min) | Drift and rest offset | Add noise numbers to the drift section |
| Circularity error (average outer-edge error) | Outer reach in 36 directions | Add one average error number and draw the shape |
| Centering test (return-to-centre precision) | No | Add: the rest value after each release, spread of the values |
| Resolution: unique values, minimum step, estimated bit depth | Trigger "number of different values" only | Add for sticks and triggers |
| Deadzone shape plot | Inner and axial deadzone numbers | Add a plot of the centre area |
| D-pad crosstalk | Diagonal flicker and blips | Already covered. Add a count per direction. |
| Button timeline | Event-time list | Already covered |
| Battery / power level | No | Add to metadata if SDL gives it (untested) |
| Device info (VID, PID) | GUID only | Add VID and PID from the GUID |
| Connection type label (wired, dongle, Bluetooth) | Manual note only | Add a `--connection` option and show it in the report |

## B. Breaks a PadLab hard rule (do not add unless the owner changes the rule)

| Feature | Rule it breaks |
|---|---|
| Rumble, trigger rumble, adaptive triggers, test pulses | Rule 1: PadLab only reads the pad |
| Update check, auto-update, release notes download | Rule 2: no network, no auto-update |
| Usage analytics (Umami script in the UI) | Rule 2: no telemetry |
| "Submit to community database" | Rule 2: no network |
| OBS overlay web server (port 24560) | Rule 2 (network server) |
| "Packet latency" and "stick latency" numbers | Section 8: do not claim latency numbers. ControllerMeta's "packet latency" is the time between reports, which PadLab already reports as the update interval. |
| Steam Input, GameInput, XInput back ends | Rule 8: new dependencies |
| 3D pad models, WebView2 UI | Rule 8 and the small-.exe rule |
| Custom mapping editor, pad brand layouts | Section 8: no brand names or images |

## C. Possible later (needs a decision)

| Feature | Why it needs a decision |
|---|---|
| Gyro and accelerometer (noise, bias, drift) | Needs SDL sensor events. Inference: pygame-ce may not expose them. Needs a test. |
| Raw HID monitor (report bytes, descriptors) | Possible with `ctypes` (part of Python), but large work and Windows only |
| Live overlay window | Phase 4 GUI could show live stick plots. Plan it with the GUI. |
| Guided tests (resolution: push the stick slowly; centering) | Matches the planned Phase 5 guided mode |
