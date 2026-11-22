# Patch notes

## Next version (not released yet)

### New

- **Price rule in Best controller.** Type a price on each controller card. The value score is the performance score minus a price bar. The cheapest controller has no price bar. For each doubling of the price, the bar goes up by 10 points (you can change this from 0 to 20). So a very good cheap controller can rank above an expensive controller that is only as good as its price leads you to expect. The rule has an effect only when two or more controllers have a price.
- **Stars in Best controller.** A star next to a result shows that this controller is better than all the other controllers in that check. A tie gives no star. The stars have their own column.
- **Update now.** When a new version is available, click **Update now**. PadMaster downloads the new PadMaster.exe from the GitHub release, checks it against the checksum that GitHub publishes, and replaces itself in the same folder, with the same name. Then it opens again. It downloads nothing until you click. This works from the version after 0.1.7: download that version manually one time.
- **High-rate mode.** For controllers that report at 4000 to 8000 Hz. Select it before you click Start. It keeps one CPU core busy while it logs, so games can run slower on some PCs.
- **Chart tab.** Select a measure (performance score, value score, price or any check) to see all your controllers in one chart. Select a second measure to see one against the other. The chart changes smoothly when you change a measure. Move the mouse pointer on a bar or dot to see the values.
- **Loading animation.** A small controller shows while a report or a tab loads.
- **Trigger stops option.** If the trigger stops are on, select **Trigger stops are on** before you click Start. PadMaster then does not grade the triggers, and does not use them in Compare or Best controller.

### Changed
- **Colours in Best controller.** The bars now show the result of each check: green for OK, orange for Watch and red for Problem. Grey means that the check has no limit. The bar length is still the performance score of the check, so a short green bar is a result that is OK but not the best possible.

- **Update rates above 1000 Hz.** PadMaster now checks for input about 1900 times per second (before: about 950), so it can measure rates up to about 1900 Hz. The update rate score is now 100 at 2000 Hz (before: 1000 Hz). Each doubling adds 25 points: 250 Hz = 25, 500 Hz = 50, 1000 Hz = 75. Update rate scores, and so performance scores, are lower than before.
- **Faster reports.** PadMaster now does the stick checks during play. On a 55-minute test session, the time from Stop to the report went from about 24 seconds to about 2 seconds. The results are the same as before.
- **Quick Test In-App.** The guided test button now has this name, and it is grey.
- The "Best value" line in Best controller is replaced by the stars.

### Fixed

- The app read the whole log again to open a report and for the latency question. Now it reads only the start of the log.
