# crash_picker

Desktop bot for a crash-style betting page. Watches fixed screen regions on any monitor, places bets with pyautogui, reads
results with exact pixel colors and Tesseract OCR. Windows only. Python 3.12 in `venv/`, run with `venv\Scripts\python.exe main.py`.
Tesseract must be on PATH; `pytesseract` runs the `tesseract` command.

`docs/SPECIFICATION.md` is the original behavior contract and `docs/images/` holds a `profit_text` crop and the red and green swatches.
`README.md` is the user-facing setup guide. Where the
spec and this file disagree, this file wins: the project is four modules not two, there are no config templates or tests, every
refresh reason except `confirmation_failures` and `input_failures` resets strategy to base, there are two more regions `ball_start_color` and `lag_crash_strip`, and the ladder comes
from `data/crash_strats.json` through the CRASH PATTERN dropdown instead of the ini, so `base_loss_trigger` follows the active strategy. The user tests by hand on the live page; there is
no test suite and none should be added.

## Files and where things go

The whole project is four modules and about 1,420 lines. Read all four before changing anything; grepping for context costs more than
reading them.

| File | Owns | Put here |
| --- | --- | --- |
| `main.py` | entry point, paths, config and strategy load, strategy select/queue, `watch_mode` save, coordinate load/save, CSV append, screenshot slots, the worker loop, the button handlers | anything that touches files, threads, or the round loop |
| `game_flow.py` | `GameConfig`, `Strategy`, `PlannedBet`, `RoundRecord`, `GameFlow` (all strategy and accounting, pure Python, no I/O, no clock) | any rule about tiers, holds, skips, money, streaks, resets |
| `screen.py` | pyautogui clicks/typing, PIL capture, GDI BitBlt fast capture, exact color match, OCR, monitor lookup | anything that reads or touches the screen |
| `ui.py` | Tk window (dark dashboard: status, balance, stat tiles, CRASH PATTERN dropdown, FEATURES checkboxes, button grid, footer notice), overlays with drag-move and corner-grip resize, the MODES checkboxes, dialogs | anything Tkinter |

Import direction is one way: `main` imports `ui`, `screen`, `game_flow`. `ui` receives the running main module through `build_ui(sys.modules[__name__])`
and reaches main's names as `app.x`. Never `import main` from another module: when launched as `python main.py` that would load a second copy with
empty globals. `screen` and `game_flow` import nothing from the project. `game_flow` never reads the clock, screen, or files; every timestamp is
passed in from `main` as `time.monotonic()` values. `main.window_start` is the position loaded at launch; `ui.window_position()` reads the
live window for Save.

## Runtime data (`data/`)

`crash_picker.ini`, `crash_picker.json`, and `crash_strats.json` are tracked in git. Everything else under `data/` is git-ignored.
Save/Exit rewrites all three, so they are usually dirty with the user's own state (window position, watch mode, picked pattern). Leave that
out of your commits unless you edited the file yourself, and never assume a dirty data file means your change is uncommitted.
The shipped values are placeholders: the nine regions sit in a column at the top of the primary monitor and must be dragged onto the page before Start,
and the ini ships with `watch_mode = 1` so a fresh install places no bets.

- `crash_picker.ini` is hand-edited input, read once at launch. `balance` and `bet_value` are starting values; the running balance and computed
  stakes live only in `flow`, the UI, and the log. The window reads `flow` fields directly every 500 ms; only `flow.phase_text` is preformatted. Save/Exit replaces only the `watch_mode`, `autoplay_mode`, `best_strategy_enabled`, `bet_holding`, `max_loss_skipping`, `crashpoint_rate_enabled` and
  `randomize_cashout` lines in place with their checkbox values; no other line is ever touched. A bad file shows an error dialog and exits. Start reads the Watch and Autoplay checkboxes into
  `flow.watch_mode` and `flow.autoplay_mode`, and both are disabled while running.
- Five ini keys nothing else here explains. `bankroll_betting = 1` sizes the base bet as `balance / bankroll_betsize` clamped to the `low,high` of
  `min_max_init_bet`, so `bet_value` is used only when it is 0. `randomize_cashout = 1` jitters every rolled target by `uniform(0.95, 1.05)` to 2 dp,
  which is why `target=` rarely equals the strategy cashpoint. `move_mouse_back = 1` returns the cursor to where it was after each click or type.
  `failed_confirmation_limit` is the streak length of `unconfirmed` or `not_submitted` rounds that forces a refresh (`confirmation_failures`,
  `input_failures`). `ocr_debug` also sets the log level to DEBUG on top of saving the debug PNGs.
- `crash_picker.json` picker coordinates, one `{name, x, y, width, height}` entry per region and nothing else; dragging an overlay moves it and dragging its 5x5 bottom-right grip resizes it, both updating in memory
  under `coordinate_lock`; Save/Exit persist. `win_end_color`, `refresh_button`, `ball_start_color` have no grip: their size is hand-edited in the json (10x10, 15x15, 10x10 now). Save/Exit also write the main window's top-left as `window: {x, y}` and the next launch
  opens there. Unchanged unless you move or resize an overlay or the window.
- `crash_data.csv` one row per round that reached red, any action (rounds closed by Stop, a stall, or a capture error have no end time and no row; a lag suspect's row is written a round late, once the strip resolves it): `crashpoint,startTime,endTime` with local times written as
  `2026-09-14T06-45-52` (`wall_time`, ISO seconds with `-` instead of `:` so the same string is a valid filename). The crashpoint is the
  first `\d+\.\d{2}` match in the OCR text (`1.90.` gives `1.90`, `1.958` gives `1.95`; the badge is `1.36×` and the × glyph sometimes leaks
  through the digit whitelist as a trailing `.` or digit). The formula `exp(0.06 * (end_ts - open_ts - 7.4))` floored at 1.00, fitted
  2026-09-14 on 88 rounds with 0.8% median error, is computed every round but never stored: it feeds the lag test and the FORMULA flags, and a
  round with no OCR match writes it as the crashpoint. The `formulapoint` column was dropped 2026-09-21 and stripped out of the history.
  The END log line carries `crashpoint=` and the settlement (`net=`, `balance=`, `hold=`, `skip=`, `baseloss=`) on a clean round; a lag
  suspect's END line has no settlement fields because `LAG_RESOLVED` carries them once the strip is read. The raw OCR text is never logged on
  it (the debug `OCR crash_text` line has it), and `formula=` appears only next to a `FORMULA_USED`, `FORMULA_OFF` or `LAG_SUSPECT` flag,
  because the formula is worth logging only where it is being used to judge something. Logs before 2026-09-23 call the line `RED` and the
  value `csv=`. With
  `ocr_debug = 1` a flagged round also saves a full-monitor `screenshots/check_R<n>.png`. Nothing creates the file or writes a header; the
  one in the file was written by hand and the column strip kept it.
- A log line never repeats a value another line already carries a second apart: `SUBMIT` is written once, at confirmation, with the click
  timestamp, the `profit_text` echo and the delay, because the round's `START` just gave the tier, stake, target and pattern, and `END` drops
  `pending=` because the next `START` prints it. `UNCONFIRMED` carries the click timestamp because no `SUBMIT` line was written for that round.
  Check this before adding a field.
- There is one formula threshold, `LAG_CHECK_RATIO`, and it means one thing: the formula is only ever used to ask whether a round was missed.
  A formula more than 1.5x the badge read is `FORMULA_OFF`, and on a confirmed loss the same test is the lag suspect test. Nothing else
  compares the two, and neither flag has ever changed a bet: `note` reaches only the log line and the debug PNG. Fitted 2026-09-17 over 1098
  rounds of both logs, where lag is bimodal - ratios 1.3, 1.5 and 2.0 flag the identical 7 rounds, because a real freeze runs 5-10x off while
  ordinary drift never passes 1.3x. The old 10% tolerance flagged clean reads: R154 (2026-09-17) was a correct `2.33` read 13.7% off formula.
- The crash value animates in over a few hundred ms and stays about 3-4 s, so the `crash_text` capture waits `FINAL_READ_DELAY_SECONDS` after red.
- The `crash_text` crashpoint is white glyphs with a red drop shadow on dark. Its OCR keeps only pixels at or above `CRASHPOINT_WHITE_FLOOR`
  gray, thins the glyphs with a 5x5 max filter, upscales 2x, whitelists digits and dot. The bold 5 is the only weak glyph: it reads as an 8
  when too much of its anti-aliased edge survives. Floor 200 still misread 3 of 293 (`159.25` as `189.25`, `1.54` as `1.84`, 2026-09-14);
  floors 220-225 read all 374 saved captures, 215 and 228 each missed one, 3x3/7x7 filters and psm 6/8/13 were worse. Do not retune the
  floor from theory: replay every `screenshots/final_R<n>.png` through `screen.ocr_text` against the `crashpoint=` value in the log's END lines
  (the shipped pipeline reproduces the log 1:1 offline) and ship only a setting that reads them all. `final_R<n>.png` is the whole monitor,
  not the `crash_text` crop, so the replay crops it first: subtract the monitor origin in that run's `START watch_mode=` line from the `crash_text` entry in
  `crash_picker.json`, crop, then `screen.ocr_text`. The user deletes `.scratch/` when tidying, so rebuild the replay there and compare each
  result with the `crashpoint=` value on that round's END line.
  A debug `OCR <region>` line is written only when that region's text differs from its previous read (`screen.last_logged`), so a run of
  identical polls shows once; the INFO lines carry every value that matters.
- A `FORMULA_OFF` flag is not always an OCR fault: R118 (2026-09-14) was a real `1.25` after a 52 s round because the page stalled before the
  launch. The OCR value stays authoritative in the CSV; the formula only estimates missing reads. Refitting 290 rounds from the log gave
  0.0600 / 7.45 s, so the constants stand. Played rounds sit within 0.5% median (end_ts from the 5 ms loop); no-bet and cashed rounds
  drift to about 1.4% because red is polled every `normal_poll_seconds` there.
- `profit_text` confirms with the stake echo (`0.15`, `2.10`), not the profit, and `confirmation_loop` polls it every `CONFIRM_POLL_SECONDS`
  (1.0 s, not `normal_poll_seconds`) because every one of 49 confirmations measured 2026-09-17 landed at 0.72-0.75 s and none earlier, so a
  read before then proves nothing. Reads fall at click +0.2 s, +1.2 s and +2.2 s; the first is too early to judge, and every later read that is
  still `0.00` logs `BET_RETRY` and clicks `play_button` again, because a `0.00` at +1.2 s means the bet never landed. An unconfirmed round reads `0.00` for the whole 3 s (2 of 368 rounds). Never compare the page balance with the app balance;
  the app balance is an estimate and the user does not want it reconciled.
- `screenshots/` holds the `ocr_debug` shots (`final_R<n>.png`, `check_R<n>.png`) and one shot per latched green,
  named `cashout_R<n>_T<tier>_<stake>_<target>_<startTime>.png` where startTime is exactly the CSV `startTime` of that round.
  Every other capture goes through `save_debug_shot`, which writes the whole monitor. `final_R<n>.png` is the only one gated on `ocr_debug`;
  the rest fire unconditionally because each marks a moment that costs money or rounds and leaves no other record: `unconfirmed_R<n>_streak<k>`
  and `dark_button_R<n>_streak<k>` for a bet that did not take, `check_R<n>` on any lag suspect or flagged read, `lag_page_R<n>_<startTime>`
  beside the `lag_R<n>_<startTime>` strip crop so the panel state behind the strip is visible, `stall_R<n>` and `stall_ready_R<n>` before the
  stall is closed out, `refresh_<reason>_R<n>` before the click clears whatever forced it, and `unknown_R<n>` when an interrupt leaves money in
  limbo. They are all rare; nothing deletes them but Clear Images.
  Full-monitor shots are of the monitor that contains `win_end_color`, looked up once at Start. Nothing deletes PNGs except the Clear Images button,
  and the log is appended across launches; the user clears both by hand. `check_R<n>.png` is the full monitor at settle time: the big red
  badge on the page is the truth for that round.
- The user usually leaves the bot running on the live page while asking for analysis: `tail logs/crash_picker.log` first. That tail is also the only way
  to know the current state at the start of a session, so read it before anything else: a `START` newer than the last `STOP`/`Exiting` means rounds
  are live, and the ini's `watch_mode` says whether real money is on them. Never assume either. Code edits take effect
  at the next launch only; never start, stop, or relaunch it yourself, and never rewrite `crash_data.csv` while it is appending. A run does
  about 130 rounds an hour.
- To check a UI change without launching the bot, import `main` and `ui` in a scratch script, set `main.cfg`, `main.strategies`,
  `main.flow`, and `main.inplay_objects`/`restart_objects`/`window_start` from the loaders (the last three default to empty, which renders
  no overlay rows and no error), stub `ui.create_overlay`, call `ui.build_ui(main)`, and screenshot with `ImageGrab`. Syntax check is
  `venv\Scripts\python.exe -m py_compile`; there is no typechecker configured.
- Directories are created once in `main()`. Nothing checks or creates them again.
- `data/crash_strats.json` is the user's ladder library and the only strategy input: `current_strategy_id` plus `strategies`, each
  `{id, label, cashpoints, multipliers}` with exactly `TIER_COUNT` (10) tiers, validated at launch like the ini (bad file: dialog and exit).
  Save/Exit rewrites only the quoted `current_strategy_id` value in place (a queued pick wins over the active one), so the next launch
  opens on the last pattern picked; the arrays are hand-formatted one line each and nothing else in the file is ever touched.
  Labels are the pattern name plus the profit on a $1 base bet (`Alt Peaks 8.8K`). Append to it, never create another strategy file or
  format; a different tier count means editing `TIER_COUNT` and every entry together. The user's ladder rule: climb rungs risk 30-60% of the bank
  so far, one cut (multiply below 1) right after the cash rung, low-risk ride after. Rejected 2026-09-14: flat stakes, 100% parlays, cuts
  mid-climb, staking the whole previous win. To judge a ladder, simulate it against the CSV in `.scratch/`: per-rung P(win), 1-in-N, and
  hours at 110 base bets/h. Under the half rule the bank after n wins is `0.15*(t0-1)*prod((t_i+1)/2)`, so the biggest target belongs at T0.
- Verified 2026-09-14 over 27 higher-tier rounds: every loss crashed below the typed target and every green fired within 2% of it, so a
  "tier 1 always loses" impression is variance (6 of 21 won at 4.9x, 0 of 6 at 18.1x). Check `crashpoint=` against `target=` before suspecting code.
- Delete anything you generate in `.scratch/` or `.playwright/` as soon as it is no longer needed, before replying. Keep only files this file
  names or a screenshot the user has not seen yet.
- Source files and this file are stored LF; the three `data/` files are CRLF because `write_atomic` translates on write. Match the file you
  are rewriting, or the commit becomes a whole-file diff: regenerating `crash_strats.json` with LF once cost exactly that.

## Phases (`flow.phase`)

`run_worker` in `main` dispatches on the phase; `GameFlow` in `game_flow` sets it. Every transition below is the only way into that phase.

| Phase | Set by | Meaning |
| --- | --- | --- |
| `stopped` | `GameFlow()`, `interrupt('stop')` | worker not running |
| `syncing` | `run_worker` start, `do_refresh` end, `interrupt('capture_error')`, `interrupt('stalled')`, `refresh_started` in waiting mode | polling `ball_start_color` for white (`round_ready`), no round open |
| `ready` | `run_worker` after the post-red wait | same poll as `syncing`, previous round settled |
| `submitting` | `open_round` (play) | typing stake and target, clicking `play_button` |
| `confirming` | `submitted` | reading `profit_text` until positive or 3 s deadline |
| `playing` | `confirmed` | fast `win_end_color` loop, waiting for green or red |
| `cashed` | `colors` on green | green latched, normal-speed wait for red |
| `watching` | `open_round` (watch/autoplay/skip/hold), `not_submitted`, `confirmation_timeout` | no stake, normal-speed wait for red |
| `post_red` | `final_read` | settled, waiting `after_red_wait_seconds`; a lag suspect is not settled yet and holds here until resolved |
| `refreshing` | `refresh_started` | `refresh_button` clicked, waiting `refresh_wait_seconds`; skipped once waiting mode is on |

`logs/crash_picker.log` is appended on every launch; grep from the last `Starting crash_picker logger` line for the current run.

## Rules that must hold

- Exact colors only: red `(191,43,63)` and green `(96,221,63)` in `win_end_color`, white `(255,255,255)` in `ball_start_color`, live-bet blue `(37,115,220)` in
  `play_button`; one matching pixel, one frame. No tolerance, no coverage.
- `lag_crash_strip` is the strip of recent crashpoint pills at the top of the page, newest on the right, and it is read only during a lag check, never
  in the round loop. It cannot use the `crash_text` pipeline: a dark pill carries white text but a green pill carries near-black text, so one
  brightness floor erases exactly the high multipliers that decide a win. `screen.strip_values` splits the strip into pills by column (any
  column with pixels above `PILL_FLOOR`), picks the polarity from each pill's own mean against `PILL_SPLIT`, upscales 3x and reads each pill
  alone at psm 7, which keeps the left-to-right order. Every pill is read twice, at both floors in `PILL_LIGHT`, and a pill whose two reads
  disagree is returned as `None` rather than guessed; positions never shift, so a `None` only costs the check when it lands on the anchor or
  on the round being recovered. Both polarities get a real second opinion: `PILL_LIGHT` holds the two floors used on a dark pill and
  `PILL_DARK` the two used on a green one, so neither branch reads the same image twice.
- Stop or a stall while a lag suspect is waiting abandons the check: `close_round` settles the round on the misread badge and still writes
  its CSV row, logging `LAG_ABANDONED`, so a round that reached red never loses its row. Tuned 2026-09-16 on 17 live captures, 68 pills: no floor read all of them correctly on its own (190 turned
  a clear `1.70` into nothing, 200 turned a clear `1.87` into `1.37`), while the pair dropped 6 pills and misread none. Retune the same way,
  by capturing the live strip and checking that values track correctly as it slides one place per round; the green thresholds were fitted
  the same way over 13 captures and 52 pills, 12 of them green, dropping one pill and misreading none. Green marks any multiplier at or
  above 2x, so green pills are common, not rare.
- A round that lost after a confirmed bet is a lag suspect when its formula is more than `LAG_CHECK_RATIO` times the badge read: the screen
  froze and the badge belongs to a later round. There is no target gate; it was dropped 2026-09-17 because the check earns its keep on the
  CSV and the resync even when the recovered value cannot change the money. R59 and R122 that day were real lags the gate hid, both
  recovered correctly in replay (`2.07` to `1.02`, `1.31` to `3.57`, both still losses). Settlement, the CSV row, and the money are held back, `END` logs `LAG_SUSPECT`, and the
  next ready signal waits `LAG_CHECK_DELAY_SECONDS` before capturing `lag_crash_strip` and saving it as `lag_R<n>_<startTime>.png`. The crashpoint we
  recorded for the previous round is the anchor: if exactly one pill sits within `LAG_ANCHOR_TOLERANCE` of it, the value one position newer
  is the round we missed, and it counts as a win when it is at or above the submitted target, compared exactly because the site cashes out
  at the typed number. Anything else (no pill near the anchor, more than one near it, the nearest already the newest, unreadable strip)
  settles the loss exactly as before with the misread badge value. The tolerance absorbs a last-digit misread on either side; it is 2%
  because over 6807 rounds of history that leaves the anchor ambiguous in 6% of four-pill windows against 1% for an exact match, while 5%
  would reach 14% and throw away recoveries. The anchor is `main.last_crashpoint`, valid only as
  the crashpoint of the immediately preceding round that wrote a CSV row from a real OCR read; a formula-only read and any interrupted
  round both clear it, because an unrecorded round between the anchor and the suspect would shift the strip search onto the wrong pill.
  While a suspect is pending `flow.suspect` and `flow.round` are the same record, which is why `resolve_suspect` may edit the record
  through `flow.suspect` and then let `settle` operate on `flow.round`. `LAG_RESOLVED` logs the whole strip, the anchor, and the outcome. A
  resolved win pays `stake * actual_target` and steps the tier like any other win; the anchor for the next check becomes the newest pill.
- `submit_bet` first calls `screen.wait_for_idle`: if the user moved the mouse, scrolled or typed within the last `INPUT_IDLE_SECONDS` (0.5) it
  sleeps until half a second of quiet, at most `INPUT_IDLE_CAP_SECONDS` (2.0) in total, then proceeds regardless. It runs once per bet and
  never inside `click_button`, because Windows counts the bot's own synthetic input (`GetLastInputInfo`) and later checks would stall on it.
- A round is ready when `ball_start_color` holds one pure white `(255,255,255)` pixel and `win_end_color` holds no red (`round_ready`, two fast captures, no OCR):
  white with red still showing is the previous round's stop, so the poll just waits. `submit_bet` runs the same check once more right before
  the click. `play_button_live` reads `play_button` for live-bet blue twice, once before typing so a dead panel costs no OCR and no typing into
  disabled boxes, and again immediately before the click because the panel can go dark in between; a greyed panel is `(36,77,129)`, the click
  would do nothing, so the round becomes `not_submitted` and saves `dark_button_R<n>_streak<k>.png` with the stage in the log. Nothing checks
  `play_button` after the click; `profit_text` stays the sole confirmation, because `play_button` reads live blue during a placed bet too and a
  post-click colour test would fail every healthy round. `round_ready` itself never checks `play_button`: the round must still open, settle, and
  write its CSV row so the strip anchor survives a dead panel.
- One round per ready signal, one click, one `profit_text` confirmation window (3 s from the click, `profit_text` only), one green latch that red never clears,
  one `end_ts`, one `crash_text` capture with at most one OCR, one settlement (`RoundRecord.settled`), one draw per settlement.
- The fast loop (`monitor_round` while `flow.phase == 'playing'`) does only capture, classify, `flow.colors`, sleep 5 ms. No OCR, files, UI, or logs per frame.
- Watch mode makes every round action `watch`: no bet, no hold/skip/base-loss changes, rounds are still read, settled, and written to the CSV.
  Waiting mode uses the same action; the status label reading `WAITING` is what tells them apart.
- Autoplay mode is the `Autoplay mode (click start)` checkbox under Watch mode, seeded by `autoplay_mode` in the ini and written back by Save; it wins
  over Watch when both are ticked. Every round is an `autoplay` action, decided before skip, hold and play, so it is a watch round (no stake, no
  hold/skip/base-loss changes, still read, settled and written to the CSV) that first OCRs `play_button` for letters and, when the text contains
  `start` in any case, clicks the button once so the site's own autoplay restarts. Nothing is typed into the inputs and nothing checks the button
  colour: the page's autoplay owns the bet. `flow.autoplay_clicks` counts consecutive rounds that needed the click and a round that reads no
  `start` zeroes it, which is how a click is confirmed. When the count already stands at `AUTOPLAY_CLICK_LIMIT` (5) and the next round still reads
  `start`, `check_autoplay` makes no click, sets `flow.waiting`, logs `WAITING reason=autoplay_clicks` and saves `waiting_R<n>.png`, so every later
  round is a plain `watch` round: five failed restarts mean the account needs reloading, and the user wants neither a refresh nor a sixth click for that
  (2026-09-28). Stalls refresh exactly as in watch mode, and `refresh_started` recomputes `waiting` from `refresh_streak`, so a stall while waiting
  on clicks still refreshes until `refresh_failure_limit`; the refreshed page gets no new attempts, because only a round without `start` or Stop
  zeroes the count, and a failed OCR read (`None`) neither clicks nor touches it. The phase text reads `Autoplay mode`; the count has no tile and
  lives only in the `AUTOPLAY_CLICK streak=` lines.
- Hold/skip draws are `randint(0, n)` inclusive with no cap. `base_loss_trigger` is `floor(cashpoints[0] * base_loss_multiplier)`, the
  cashpoint from the active strategy and the multiplier from the ini, recomputed by `GameFlow.set_strategy` on activation and never else.
- The FEATURES checkboxes (Hold, Skip, 3+ rate, Cashout) stay enabled while running (Hold and Skip are greyed while Best pattern is checked) and write into `main.features`, a plain dict, from the Tk
  thread. The worker copies that dict into `flow.holding`, `flow.skipping`, `flow.rate_on` and `flow.randomizing` at the next ready signal, so
  a toggle never lands mid-round, and `settle` and `plan_target` read those instead of the ini flags. Save writes them back to the ini. Unchecking Hold or Skip stops the next
  streak from being drawn and cancels one already counting down: `set_features` zeroes the countdown of any feature that is off (a best-mode hold plan keeps its hold), so the tile's
  `OFF` and the phase text never disagree.
- The 3+ RATE tile counts crashpoints at or above `crashpoint_rate_threshold` over the last `crashpoint_rate_window` confirmed reads
  (`flow.crashpoints`, a deque fed by `write_crash_row` only when the OCR actually matched and the outcome is not `unknown`, so formula-only rounds are excluded and hold,
  skip and watch rounds are included). It starts empty each launch and shows the real denominator until the window fills. `flow.rate_on`
  only hides the number as `OFF`; recording never stops, so turning it back on shows history immediately.
- The window runs top to bottom: status and phase text, balance and its run delta, six tiles (WINS / LOSSES, UNKNOWN, BASE LOSS,
  NEXT TIER, HOLD / SKIP, 3+ RATE), the CRASH PATTERN dropdown, the FEATURES checkboxes, the button grid, then two columns side by side,
  MODES (Watch mode, Autoplay mode and Best pattern stacked, `ui.mode_checks`) on the left and OVERLAY REGIONS on the right, and a footer
  notice. Adding a seventh tile means rebalancing the
  grid, so prefer an existing cell.
- One value has one home on screen. A number a tile already shows is never repeated in the phase text, the footer or another label: the
  BASE LOSS tile carries the trigger as its denominator and the HOLD / SKIP tile carries both countdowns, so the phase text says only
  `Holding` or `Skipping`, drops the tier the NEXT TIER tile already shows and keeps just the stake and target, and the footer stays empty
  unless it has something of its own to say, which today is `pattern swap queued`, in random mode the running pattern and its loss count,
  because the dropdown reads `Random` there and the label has nowhere else to live, and in best mode `next pick in N`. Check this before adding any label.
- Every tile is one centred title over one centred value label. HOLD / SKIP and WINS / LOSSES pack their two numbers into that single
  value as `2 / 3`, and hold or skip reads `OFF` when its feature is off, as does the whole rate value.
- The CRASH PATTERN dropdown stays enabled while running (greyed while Best pattern is checked) and calls `select_strategy`: picking the active strategy only cancels a queued one;
  while stopped the pick activates at once; while running it sits in `flow.queued` and `run_worker` activates it right before the next
  `open_round`, whatever the previous round did, and Stop activates it as the run closes (`close_round`, before `interrupt`, so the
  `random after N losses` count is still the real one). Activation (`set_strategy`) resets the ladder to base (pending, hold, skip, base-loss count)
  and recomputes the trigger; balance, stats, and the failure streaks survive. The log carries `STRATEGY queued` and `STRATEGY active` lines,
  the run's `START watch_mode=` line names the strategy by id, and every round's `R#<n> START` line ends with `pattern=`, the label lowercased
  with underscores (`alt_peaks_8.8k`) and prefixed `(R)` in random mode; outside random mode the dropdown is the only on-screen strategy display.
- The dropdown's first row is `Random` and is not a strategy: index 0 means random mode, every other index is `strategies[index - 1]`. Picking
  it turns `flow.random_mode` on and rolls a pattern that is never the current one, so picking it again is a manual re-roll; from then on
  `settle` drops another roll into `flow.queued` at the `random_strategy_losses`th loss, so an automatic swap is a queued pick like any other
  and `run_worker` activates it at the next `open_round`. A loss ends a ladder attempt at any tier, so a swap never cuts a climb short. Picking
  any named pattern turns random mode back off and replaces or cancels the queued roll. `set_strategy` zeroes the count with the rest of the
  ladder. `current_strategy_id` saves as `random`, an id no strategy in the library may use; `load_strategies` turns it into a `Strategy` or
  `None` for `GameFlow`, so game_flow never sees the id.
- Best mode is the `Best pattern (40)` checkbox under Watch mode: `best_strategy_enabled` in the ini seeds it and Save writes it back,
  `best_strategy_window` (40, hand-edited, at least 1) sizes the window, and the box is disabled while running. Ticking it while stopped
  calls `set_best`, which sets `flow.best_mode`, forces random mode off (the running pattern stays), re-applies the features, and
  `ui.apply_best` greys the dropdown and the Hold and Skip boxes; unticking re-enables them, and random mode stays off with the running
  pattern picked until Random is chosen again. Every `best_strategy_window` confirmed
  OCR reads the bot picks the pattern that would have earned the most over those crashpoints and plays it for the next window. `flow.window` collects the reads
  (`record_crashpoint` returns True on the 40th), `pick_best` runs `best_holds` for every pattern from base stake at the current balance, sorts,
  clears the window, drops the winner into `flow.queued` like any other queued pick and keeps its hold plan, and `log_best` writes one
  `BEST_STRATEGY` block: a header with the base, then one row per pattern best to worst with net, a `#`/`-` bar scaled to the largest net,
  wins, losses, the highest tier its bets reached and the window round that reached it (`T3@r27`), and its holds. The header and the
  winning row are INFO; the other rows follow as one DEBUG record, so they show only with `ocr_debug = 1`. Row 1 is the pick, named again
  by the `STRATEGY active` line at the next round. Every confirmed read enters the
  window whatever the round did (hold, skip, watch, a lag row resolved or abandoned); a round with no confirmed read (formula-only,
  interrupted, stalled, capture error), an `unknown` outcome (an ambiguous green-and-red frame; its CSV row still carries the read but
  `monitor_round` passes `confirmed` as False so the rate, the anchor and the window skip it) and a refresh leave no gap. `close_round` writes an abandoned
  lag row before `interrupt`, so a Stop clears it with the rest of the window. The swap happens at the very next round even mid-climb, and the same pattern picked again also restarts
  from base (2026-09-27: the 40 games decide, whatever the running climb was doing).
- `best_holds` is exact: the hold plan is one number per tier, 0 to `BEST_HOLD_MAX` (3), applied every time that tier is won, and the search
  commits a tier's hold the first time that tier is won along a path and branches only there, so the tree is tiny for high ladders and at most
  a few hundred thousand calls for one whose low targets win nearly every round; the slowest of 26,415 sliding 40-round windows of the CSV
  took 0.68 s for all 14 patterns (median 2 ms), checked against a full enumeration of every hold vector. The window size has no
  cap: a window of 400 takes 7 s, 800 takes 10 s, and 1000 hits the recursion limit and crashes the worker. Tiers the best path never won have no
  entry and hold 0 live. On ties the shorter hold and the earlier library pattern win. The sim uses nominal cashpoints, no jitter, no
  skipping, the base stake fixed for all 40 rounds, and no `final_tier` refresh gap after a completed ladder. Low-target ladders win most windows in hindsight because holds let the sim cherry-pick crashes: on 2026-09-28 `quad_4`
  (8, 4, 4, 4, 4) became `quad_5` (10, 5, 5, 5, 5) and `target_arch` grew from 4-10-4 to 6-15-6 to bring them from 131 and 106 picks of
  659 windows down to about 85 and 58, level with `dip_surge` and `power_climb`; `flat_return` and `10_5_wave` got slightly higher
  multipliers the same day so that every ladder pays at least 4K on a $1 base, which every label states.
- In best mode holding and skipping are overridden, not unchecked: `set_features` (also what `GameFlow.__init__` runs) keeps `flow.holding`
  and `flow.skipping` off while `flow.best_mode` is on, so the Hold and Skip boxes keep their ini values behind the grey and Save writes
  them unchanged, and `settle` takes each hold from `flow.hold_plan[tier]` instead of a draw (the first window and every game after Stop
  have an empty plan, so no holds). The HOLD tile shows the countdown whenever a plan exists and `set_features` leaves `hold_remaining`
  alone while one does. `update_status` keeps the greyed dropdown pointed at the running pattern, the footer reads `next pick in N`,
  `pattern=` is prefixed `(B)` and the START line says `best every 40`. Stop clears the window and the plan, so a new run starts with a
  hold-free window; `current_strategy_id` saves the last pick.
- The cashout target is rolled once per tier: at the first base bet, on each tier step, and after a skip block ends. A base loss keeps the
  target and only recomputes the stake. `plan_target` jitters it by `cashout_range` percent either way (`uniform(1 - r/100, 1 + r/100)`, 5 now)
  when `flow.randomizing` is on, which is why a logged `target=` rarely equals the strategy cashpoint. `cashout_range` is also the single
  source for the ladder check in `load_strategies`, which rejects any ladder whose lowest cashpoint could roll to 1.01 or below: a crash round
  starts at 1.00x, so a target at or under it is one the site cannot honour. The two used to be separate literals that had to agree by hand. `submit_bet` OCRs `bet_input` and `cashout_input` before every click and types only a field whose read differs
  from the planned value, so a misclick or a hand edit is corrected on the next round and a clean round within a tier is one click on `play_button`.
  The `profit_text` echo is compared with the submitted stake after confirmation and logs `STAKE_MISMATCH`; accounting still uses the planned stake.
- Overlays stay visible while running: each one is excluded from screen capture (`SetWindowDisplayAffinity`) at creation and made click-through
  and unmovable (`WS_EX_TRANSPARENT`) from Start to Stop. Hide/Show works at any time. `raise_overlay` (SetWindowPos HWND_TOPMOST with
  FRAMECHANGED) runs after creation, after every style change, and on Show, because an ex-style change alone can drop the window behind the page. There is no manual Refresh button; the user refreshes by hand.
- A lag check never triggers a refresh of its own. Rejected 2026-09-17: the freeze does leave the bet panel dark, and R#68 proved it by
  resolving to nothing and then losing five rounds to `dark_before_typing`, but the user does not want a reload decided in the middle of a play.
  `failed_confirmation_limit` of 2 is the answer instead - two dead rounds and the ordinary streak refreshes. The cost is those two rounds.
- Refreshing resets the ladder to base for every reason except the two in `KEEP_TIER_REASONS` - `confirmation_failures` and `input_failures` -
  which keep the pending tier, because neither ever placed a bet or risked money. Balance and trigger survive every reason.
- `refresh_failure_limit` (3) refreshes in a row with no confirmed bet between them ends the refreshing: `refresh_started` returns False,
  nothing is clicked, the phase drops back to `syncing`, the status label turns to an amber `WAITING`, and every round after it is a `watch`
  round, so the CSV, the strip anchor and the 3+ rate keep filling while no money moves. `WAITING` and `waiting_R<n>.png` record every time it is reached, including a later stall that would
  have refreshed again. The streak resets only on a confirmed bet or Stop; autoplay mode reaches the same state from its click limit with the
  streak untouched, so a stall still refreshes there. The usual cause is an empty site balance, which the app
  balance only estimates and never sees, so nothing stops on a zero balance.
- Stop is immediate. `GameFlow.interrupt` closes an open round by phase: `submitting` becomes `not_submitted`, `confirming`/`playing` become
  `unknown`, `cashed` becomes `win`, no-bet rounds stay `no_bet`; then it settles once. Unknown outcomes log, reset to base, and continue.
  Stop then ends the run: `interrupt('stop')` resets the ladder to base, zeroes the random loss count and both failure streaks, and clears
  `waiting` and `refresh_streak`, so the window shows a clean slate while stopped and Start begins from whatever is picked now. Balance,
  wins, losses, unknown and the 3+ window are money and history, not run state, and survive. Start itself sets only `flow.watch_mode`. A
  Stop/Start that still skipped, held or climbed from the previous run was a bug (2026-09-22); nothing decided in one run may drive the next.
- No checks inside functions that the caller already decided. If a thing is off, the caller does not call. Decide once before a loop, not per
  iteration. `set_running` disables Start, Clear images, and the three MODES checkboxes while running, so their handlers never
  re-test `running`.
- Do not wrap a statement to respect a line limit: the user re-joined every call, tuple, and log line that had been split at 150 characters
  (several now over 200). Shorten a long line by naming a local or dropping words instead. The three standing exceptions left wrapped are the `GameConfig(...)` call in `main.py`, the `BITMAPINFOHEADER` fields in `screen.py` and the button `spec` tuple in `ui.py`; keep those as they are.
- No comments over two lines, and almost none at all. No unused functions, fields, or imports.
