# Hardware results

PadLab 0.1.0, pygame-ce 2.5.8, SDL 2.32.10, Python 3.14.0, Windows 11.

| Pad | Connection | SDL driver | Mapped | Mapping check | Background works | Notes |
|---|---|---|---|---|---|---|
| Xbox One Controller (GUID 0300938d5e040000ff02000000007200) | not recorded | not recorded | yes | passed (2026-11-13) | Steam Input ON, fullscreen: **yes** (26196 inputs, steady from 31 s to 67 s). An earlier run with 0 inputs for 232 s was not a fault: the owner did not use the pad in that time. Steam Input OFF for the game: **yes**, fullscreen, 1 min (4402 inputs, steady from 11 s). Borderless, Steam Input OFF: **probably yes** (11360 inputs in a 21 s log, input from 0.4 s; the log is shorter than planned, so confirm with a longer run). | All 12 buttons, D-pad, both sticks and both triggers show the correct names. `lt` and `rt` are separate. Sticks reach about 1.00 in all directions and go back to 0.00 at rest. |

## Phase 2e checks (Xbox One Controller)

| Risk | Result |
|---|---|
| Loop rate | 957 loop passes per second (tested, 12 s log). Now written to the metadata as `loop_hz`. |
| Same timestamps | Not a problem (tested). The pad sends a report about every 4 ms (median 4.1 ms). One report gives up to 4 axis rows with the same time. Times of different reports are different. D-pad and two-button split times were mostly not 0 ms. |
| Hands-off check | Was "not done" (tested). Cause: SDL sends no event while a stick does not move. Fixed: the logger writes the start value of each axis at t=0. A 12 s real log now starts with these rows. |
| Values at rest | Every axis reads exactly 0 at rest (tested). Inference: the Windows driver for this pad can hide small drift. |
| `lt` and `rt` separate | Yes (tested in `padlab check`). |
| Ctrl+C in the .exe | Not tested. Needs the .exe build. |
| Pad turns off and on | Works (tested). `c` rows at 17.9 s (lost) and 22.4 s (back). 18492 rows logged after the pad came back. The report shows 1 disconnect as "Problem", as expected for a pad that was turned off on purpose. |
| Hands-off fix on real data | Works (tested). The same log shows a hands-off rest window of 28 s (left stick) and 27 s (right stick). |
| PlayStation / Switch pads | Not tested. No pad available. |
