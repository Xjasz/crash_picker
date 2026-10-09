# crash_picker

Desktop bot for a crash-style betting page. Watches fixed screen regions on any monitor, places bets with pyautogui, reads
results with pixel colours within a tolerance and Tesseract OCR. Windows only. Python 3.12 in `venv/`, run with `venv\Scripts\python.exe main.py`.
Tesseract must be on PATH; `pytesseract` runs the `tesseract` command.

`docs/SPECIFICATION.md` is the original behavior contract and `docs/images/` holds a `profit_text` crop and the red and green swatches.
`README.md` is the user-facing setup guide. Where the
spec and this file disagree, this file wins: the project is four modules not two, there are no config templates or tests, every
refresh reason except `confirmation_failures` and `input_failures` resets strategy to base, there is one more region `ball_start_color`, and the ladder comes
from `data/crash_strats.json` through the CRASH PATTERN dropdown instead of the ini, so `base_loss_trigger` follows the active strategy. The user tests by hand on the live page; there is
no test suite and none should be added.

## Files and where things go

The whole project is four modules and about 1,400 lines. Read all four before changing anything; grepping for context costs more than
reading them.

| File | Owns | Put here |
| --- | --- | --- |
| `main.py` | entry point, paths, config and strategy load, strategy select/queue, `watch_mode` save, coordinate load/save, CSV append, screenshot slots, the worker loop, the button handlers | anything that touches files, threads, or the round loop |
| `game_flow.py` | `GameConfig`, `Strategy`, `PlannedBet`, `RoundRecord`, `GameFlow` (all strategy and accounting, pure Python, no I/O, no clock) | any rule about tiers, holds, skips, money, streaks, resets |
| `screen.py` | pyautogui clicks/typing, PIL capture, GDI BitBlt fast capture, tolerant color match, OCR, monitor lookup | anything that reads or touches the screen |
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
The shipped values are placeholders: the eight regions sit in a column at the top of the primary monitor and must be dragged onto the page before Start,
and the ini ships with `watch_mode = 1` so a fresh install places no bets.

- `crash_picker.ini` is hand-edited input, read once at launch. `balance` and `bet_value` are starting values; the running balance and computed
  stakes live only in `flow`, the UI, and the log. The window reads `flow` fields directly every 500 ms; only `flow.phase_text` is preformatted. Save/Exit replaces only the `watch_mode`, `autoplay_mode`, `manual_cashout`, `random_backstop`, `best_strategy_enabled`, `bet_holding`, `max_loss_skipping`, `crashpoint_rate_enabled` and
  `randomize_cashout` lines in place with their checkbox values; no other line is ever touched. A bad file shows an error dialog and exits. Start reads the Watch, Autoplay, Manual cashout and Random backstop checkboxes into
  `flow.watch_mode`, `flow.autoplay_mode`, `flow.manual_cashout` and `flow.random_backstop`, and all four are disabled while running.
- Seven ini keys nothing else here explains. `backstop_multiplier` (2) scales the typed auto-cashout in manual cashout mode and `cashout_lead_seconds` is how early
  the click fires; both are explained under that mode below. `bankroll_betting = 1` sizes the base bet as `balance / bankroll_betsize` clamped to the `low,high` of
  `min_max_init_bet`, so `bet_value` is used only when it is 0. `randomize_cashout = 1` jitters every rolled target by `uniform(0.95, 1.05)` to 2 dp,
  which is why `target=` rarely equals the strategy cashpoint. `move_mouse_back = 1` returns the cursor to where it was after each click or type.
  `failed_confirmation_limit` is the streak length of `unconfirmed` or `not_submitted` rounds that forces a refresh (`confirmation_failures`,
  `input_failures`). `ocr_debug` also sets the log level to DEBUG on top of saving the debug PNGs.
- `crash_picker.json` picker coordinates, one `{name, x, y, width, height}` entry per region and nothing else; dragging an overlay moves it and dragging its 5x5 bottom-right grip resizes it, both updating in memory
  under `coordinate_lock`; Save/Exit persist. `win_end_color`, `refresh_button`, `ball_start_color` have no grip: their size is hand-edited in the json (10x10, 15x15, 10x10 now). Save/Exit also write the main window's top-left as `window: {x, y}` and the next launch
  opens there. Unchanged unless you move or resize an overlay or the window.
- `crash_data.csv` one row per round that reached red, any action (rounds closed by Stop, a stall, or a capture error have no end time and no row): `crashpoint,startTime,endTime` with local times written as
  `2026-09-14T06-45-52` (`wall_time`, ISO seconds with `-` instead of `:` so the same string is a valid filename). The crashpoint is the
  first `\d+\.\d{2}` match in the OCR text (`1.90.` gives `1.90`, `1.958` gives `1.95`; the badge is `1.36×` and the × glyph sometimes leaks
  through the digit whitelist as a trailing `.` or digit). The formula `exp(0.06006 * (end_ts - open_ts - 8.04))` floored at 1.00 (growth refitted 2026-10-07 on 781 red-to-red gaps, residual p5-p95 0.055 s;
  offset measured the same day as the ready white appearing 8.04 s before launch under a 5 ms poll), is computed every round but never stored: it feeds the FORMULA flags, and a
  round with no OCR match writes it as the crashpoint. The `formulapoint` column was dropped 2026-09-21 and stripped out of the history.
  The END log line carries `crashpoint=`, the bet's `target=` (added 2026-10-08 so a win or loss can be judged without scrolling back to START) and the settlement (`net=`, `balance=`, `hold=`, `skip=`, `baseloss=`). The raw OCR text is never logged on
  it (the debug `OCR crash_text` line has it), and `formula=` appears only next to a `FORMULA_USED` or `FORMULA_OFF` flag,
  because the formula is worth logging only where it is being used to judge something. Logs before 2026-09-23 call the line `RED` and the
  value `csv=`. With
  `ocr_debug = 1` a flagged round also saves a full-monitor `screenshots/check_R<n>.png`. Nothing creates the file or writes a header; the
  one in the file was written by hand and the column strip kept it.
- A log line never repeats a value another line already carries a second apart: `SUBMIT` is written once, at confirmation, with the click
  timestamp, the `profit_text` echo and the delay, because the round's `START` just gave the tier, stake, target and pattern, and `END` drops
  `pending=` because the next `START` prints it. `UNCONFIRMED` carries the click timestamp because no `SUBMIT` line was written for that round.
  Check this before adding a field.
- There is one formula threshold, `FORMULA_OFF_RATIO`, and it means one thing: the formula only flags a badge read that looks like a later round's
  (`FORMULA_OFF`, more than 1.5x the read) and stands in when there is no read (`FORMULA_USED`). Nothing else
  compares the two, and the flag has never changed a bet: `note` reaches only the log line and the debug PNG. Fitted 2026-09-17 over 1098
  rounds of both logs, where lag is bimodal - ratios 1.3, 1.5 and 2.0 flag the identical 7 rounds, because a real freeze runs 5-10x off while
  ordinary drift never passes 1.3x. The old 10% tolerance flagged clean reads: R154 (2026-09-17) was a correct `2.33` read 13.7% off formula.
  The lag check that used the same test to hold a confirmed loss and recover the missed value from the page's strip of recent pills was removed
  2026-10-07: in about 3300 rounds it never resolved to a win (2 suspects in 2219 rounds that day, both losses), so a frozen round settles on its badge
  read like any other, a round without green is a loss whatever was clicked, and nothing decides a reload in the middle of a play (rejected 2026-09-17).
- The crash value animates in over a few hundred ms and stays about 3-4 s, so the `crash_text` capture waits `FINAL_READ_DELAY_SECONDS` after red, and that wait
  doubles as the crash check: one more `win_end_color` capture must still show red, because a real pill stays 3-4 s (88 of 89 final shots on 2026-10-08) while R#81's red
  was a one-off flash at 5.2x with the round still live (the final shot shows 5.32x and a live Cashout button; the bet missed its 7.77 click and lost at 25x). A red that
  is gone logs `RED_FLASH`, saves `red_flash_R<n>.png`, clears `end_ts`, `outcome` and `close_reason`, and the fast loop carries on as if the frame never happened.
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
  launch. The OCR value stays authoritative in the CSV; the formula only estimates missing reads. The old `0.06 / 7.4` pair was fitted under a 0.5 s
  ready poll phase-locked to the previous red, which saw the white 7.53 or 8.03 s before launch; the ready poll now runs at `FAST_POLL_SECONDS` in
  every mode, so `open_ts` is the first white frame the poll sees and 8.04 holds, except on the round after Start or a refresh,
  where the poll started late. Played rounds sit within 0.5% median (end_ts from the 5 ms loop); no-bet and cashed rounds
  drift to about 1.4% because red is polled every `normal_poll_seconds` there.
- `profit_text` confirms with the stake echo (`0.15`, `2.10`), not the profit, and `confirmation_loop` polls it every `CONFIRM_POLL_SECONDS`
  (1.0 s, not `normal_poll_seconds`) because every one of 49 confirmations measured 2026-09-17 landed at 0.72-0.75 s and none earlier, so a
  read before then proves nothing. Reads fall every second from click +0.2 s until `submission_confirmation_seconds` (5, raised from 3 on 2026-10-08); the first is too early to judge, and every later read that is
  still `0.00` logs `BET_RETRY` with the `play_button` text and clicks it again only when that text is the bare `Bet`: `Cancel Bet` means the first click landed and the echo is late,
  and a second click there cancels the live bet (guard added 2026-10-08 after 7 of 21 bets read `0.00` through +2.2 s on a page whose echo had always landed by 0.75 s). An unconfirmed round reads `0.00` for the whole window (2 of 368 rounds on 2026-09-17). Never compare the page balance with the app balance;
  the app balance is an estimate and the user does not want it reconciled.
- `screenshots/` holds the `ocr_debug` shots (`final_R<n>.png`, `check_R<n>.png`) and one shot per latched green,
  named `cashout_R<n>_T<tier>_<stake>_<target>_<startTime>.png` where startTime is exactly the CSV `startTime` of that round.
  Every other capture goes through `save_debug_shot`, which writes the whole monitor. `final_R<n>.png` and `check_R<n>.png` are the only ones gated on `ocr_debug`;
  the rest fire unconditionally because each marks a moment that costs money or rounds and leaves no other record: `unconfirmed_R<n>_streak<k>`
  and `dark_button_R<n>_streak<k>` for a bet that did not take, `stall_R<n>` and `stall_ready_R<n>` before the
  stall is closed out, `refresh_<reason>_R<n>` before the click clears whatever forced it, `waiting_R<n>` when refreshing gives up, `red_flash_R<n>` when the end frame's red is gone half a second later, `bet_gone_R<n>` when `play_button` shows the bet
  already over, and `unknown_R<n>` when an interrupt leaves money in
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
| `playing` | `confirmed` | fast `win_end_color` loop, waiting for green or red; in manual cashout mode it also watches the ball leave `ball_start_color`, reads `play_button` every 2 s for a bet that is already over, and clicks it at the target moment |
| `cashed` | `colors` on green | green latched, normal-speed wait for red |
| `watching` | `open_round` (watch/autoplay/skip/hold), `not_submitted`, `confirmation_timeout` | no stake, normal-speed wait for red |
| `post_red` | `final_read` | settled, waiting `after_red_wait_seconds` |
| `refreshing` | `refresh_started` | `refresh_button` clicked, waiting `refresh_wait_seconds`; skipped once waiting mode is on |

`logs/crash_picker.log` is appended on every launch; grep from the last `Starting crash_picker logger` line for the current run.

## Rules that must hold

- Colors match within `COLOR_TOLERANCE` (60) on every channel of one pixel in one frame, no coverage: red `(202,13,61)` and green `(45,224,28)` in `win_end_color`,
  white `(255,255,255)` in `ball_start_color`, live-bet blue `(20,117,225)` in `play_button`. Exact matching was dropped 2026-10-07 after a site restyle moved
  the red from `(191,43,63)` and the blue from `(37,115,220)` and the bot missed every crash and every live button; the tolerance covers both palettes and
  still rejects the greyed panel `(27,78,131)`, 90 off on blue. Green is centred on the site's current accent green, measured on the page's recent-crash pills; the old `(96,221,63)` is inside the tolerance, and the first
  `cashout_R<n>` shot should confirm the cashout badge sits inside it too.
- `submit_bet` first calls `screen.wait_for_idle`: if the user moved the mouse, scrolled or typed within the last `INPUT_IDLE_SECONDS` (0.5) it
  sleeps until half a second of quiet, at most `INPUT_IDLE_CAP_SECONDS` (2.0) in total, then proceeds regardless. It runs once per bet and
  never inside `click_button`, because Windows counts the bot's own synthetic input (`GetLastInputInfo`) and later checks would stall on it.
- A round is ready when `ball_start_color` holds one pure white `(255,255,255)` pixel and `win_end_color` holds no red (`round_ready`, two fast captures, no OCR):
  white with red still showing is the previous round's stop, so the poll just waits. `submit_bet` runs the same check once more right before
  the click. `play_button_live` reads `play_button` for live-bet blue twice, once before typing so a dead panel costs no OCR and no typing into
  disabled boxes, and again immediately before the click because the panel can go dark in between; a greyed panel is `(27,78,131)`, the click
  would do nothing, so the round becomes `not_submitted` and saves `dark_button_R<n>_streak<k>.png` with the stage in the log. Nothing checks
  the `play_button` colour after the click; `profit_text` stays the sole confirmation, because `play_button` reads live blue during a placed bet too and a
  post-click colour test would fail every healthy round; the retry reads its text, never its colour. `round_ready` itself never checks `play_button`: the round must still open, settle, and
  write its CSV row whatever the panel shows.
- One round per ready signal, one click, one `profit_text` confirmation window (`submission_confirmation_seconds` from the click, `profit_text` only), one green latch that red never clears,
  one `end_ts`, one `crash_text` capture with at most one OCR, one settlement (`RoundRecord.settled`), one draw per settlement.
- The fast loop (`monitor_round` while `flow.phase == 'playing'`) does only capture, classify, `flow.colors`, sleep 5 ms, plus in manual cashout mode one
  `ball_start_color` capture per frame until the launch is seen and one `play_button` capture on the click frame, and one `play_button` OCR every
  `BET_TEXT_POLL_SECONDS` (2 s) until a click lands, skipped within `ocr_timeout_seconds` of an armed click. No OCR, files, UI, or logs per frame.
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
- Manual cashout mode is the `Manual cashout (click at target)` checkbox under Best pattern, seeded by `manual_cashout` in the ini, written back by Save
  and disabled while running. A play round still types the stake and a cashout, but the typed cashout is `target * backstop_multiplier`
  (`PlannedBet.typed`, rolled by `plan_cashout` beside the target, so once per tier and kept across base losses, 2x now) and the bot clicks `play_button` itself when the multiplier reaches the target: the typed value is only a backstop, and at
  2x a backstop cashout is unmistakable in the log and in the site history, which is how the user tracks click success (2026-10-07). Random backstop is the `Random backstop (2x-1000x)` checkbox under it, seeded by
  `random_backstop`, written by Save, disabled while running and inert unless Manual cashout is on: `plan_cashout` then draws the multiplier from
  `uniform(*BACKSTOP_RANGE)` once per tier instead of `backstop_multiplier` (per bet until 2026-10-08, which retyped the field every round), so the site history shows no 2x fingerprint, and the START line carries `typed=`
  whenever the typed value differs from the target (the page clamps the field only in the billions, 2026-10-07). The multiplier is
  `exp(0.06006 * t)` from launch, so the click moment is `launch + ln(target) / CRASH_GROWTH_PER_SECOND - cashout_lead_seconds`. Launch is the first playing frame
  where `ball_start_color` has lost its white after a frame that had it, minus `BALL_LEAVE_SECONDS` (0.52, sd 0.04 over 11 rounds); a round whose first
  playing frame already has no white (the round after Start when the intermission was half over) never arms a click and rides to the backstop. The ready
  signal is not used as a clock here because `open_ts` is late on the first round after Start or a refresh. The click
  (`screen.click_fast`, no pyautogui pauses, cursor returned when `move_mouse_back = 1`) fires only when the same frame shows no red and live blue in
  `play_button`, and only while the phase is still `playing`, because right after a green the same blue button reads `Bet Next Round`; a refused click
  logs `CLICK_SKIPPED` with the red and phase it saw. Every fast-loop capture and the `play_button` OCR sit inside the same `OSError` guard as `win_end_color`. On green the
  round is `via=click` when the green came within `CLICK_GREEN_LIMIT_SECONDS` of the click and `via=backstop` otherwise; `flow.clicks` counts `click`,
  `backstop` and `lost` (a loss after a click, counted at END) and survives Stop like the
  balance. `CASHOUT` logs the click offset from launch and the `clicks=click/backstop/lost` tally; `CLICK_LOST` carries the same tally. Nothing reads the
  realized multiplier off the page: green is the only cashout confirmation, `record.realized` is the target for a click and the typed value for a backstop,
  and `settle` pays `stake * realized` (rejected 2026-10-07: an OCR region on the cashed-out badge), except that a backstop `realized` above the round's own crashpoint read
  is a payout the site cannot have made: `final_read(crashpoint)` hands the read to `settle`, which turns that win into `unknown`, parks the stake in `unknown_stake`, takes the
  backstop back out of the tally, and `BACKSTOP_UNPAID` logs it (`interrupt` settles with no read, so a backstop green cut off by Stop, a stall or a capture error is `unknown` too). Added 2026-10-08 after R#23: the fast loop missed a 2.61
  red, the next round's live digits painted `win_end_color` green and the app credited 4605x on a 0.28 bet, which lifted the base stake to the 1.00 cap. The red `Crashed` pill and the green cashout badge
  are one element that swaps colour and wording and sits a little higher on a win, and red replaces green at once; `win_end_color` has read it over thousands of rounds
  and is never moved (Nick 2026-10-08): the `play_button` text check below is the guard against a missed red, not a region move. The lead is a hand-edited ini value, never learned;
  the site history shows every realized multiplier, so a consistently high read means a late click and a bigger lead. A missed click rides to the typed backstop (2x, or the random draw), which
  keeps the expected value and halves that rung's chance of continuing. The click never touches an outcome: a round without green is a loss,
  click or no click. A `play_button` read of exactly `Bet`, the word it shows alone while a new round is getting ready, while the bet should still be live means the crash was missed: the round ends as a loss
  (`BET_GONE`, `bet_gone_R<n>.png`), checked every 2 s from 2 s after the launch until a click lands (a refused click keeps the reads going), never before launch where the button may read `Cancel Bet` (added 2026-10-08 after R#23). Timing error
  moves the multiplier by 0.6% per 0.1 s and the click cannot change the expected value (`x * P(crash >= x)` is flat on the CSV). It composes with Best pattern and Random
  (verified in a game_flow smoke 2026-10-07): the pick, the hold plan and the stake ladder are untouched, the next stake scales from the previous stake and never from a backstop payout, hold and skip rounds never click because they are
  `watching`, and the 40x rungs type 80.00, up to 84.00 with jitter under the fixed 2x.
- Hold/skip draws are `randint(0, n)` inclusive with no cap. `base_loss_trigger` is `floor(cashpoints[0] * base_loss_multiplier)`, the
  cashpoint from the active strategy and the multiplier from the ini, recomputed by `GameFlow.set_strategy` on activation and never else.
- The FEATURES checkboxes (Hold, Skip, 3+ rate, Cashout) stay enabled while running (Hold and Skip are greyed while Best pattern is checked) and write into `main.features`, a plain dict, from the Tk
  thread. The worker copies that dict into `flow.holding`, `flow.skipping`, `flow.rate_on` and `flow.randomizing` at the next ready signal, so
  a toggle never lands mid-round, and `settle` and `plan_cashout` read those instead of the ini flags. Save writes them back to the ini. Unchecking Hold or Skip stops the next
  streak from being drawn and cancels one already counting down: `set_features` zeroes the countdown of any feature that is off (a best-mode hold plan keeps its hold), so the tile's
  `OFF` and the phase text never disagree.
- The 3+ RATE tile counts crashpoints at or above `crashpoint_rate_threshold` over the last `crashpoint_rate_window` confirmed reads
  (`flow.crashpoints`, a deque fed by `write_crash_row` only when the OCR actually matched and the outcome is not `unknown`, so formula-only rounds are excluded and hold,
  skip and watch rounds are included). It starts empty each launch and shows the real denominator until the window fills. `flow.rate_on`
  only hides the number as `OFF`; recording never stops, so turning it back on shows history immediately.
- The window runs top to bottom: status and phase text, balance and its run delta, six tiles (WINS / LOSSES, UNKNOWN, BASE LOSS,
  NEXT TIER, HOLD / SKIP, 3+ RATE), the CRASH PATTERN dropdown, the FEATURES checkboxes, the button grid, then two columns side by side,
  MODES (Watch mode, Autoplay mode, Best pattern, Manual cashout and Random backstop stacked, `ui.mode_checks`) on the left and OVERLAY REGIONS on the right, and a footer
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
  while stopped the pick activates at once; while running it sits in `flow.queued` and `begin_round` activates it right before the next
  `open_round` once the ladder is back at base (`flow.pending` is None or tier 0: after a loss, a final-tier win, a ladder-resetting refresh or an unknown), so a queued
  pick never cuts a climb short, and Stop activates it as the run closes (`close_round`, before `interrupt`, so the
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
  clears the window, drops the winner and its hold plan into `flow.queued` and `flow.queued_plan` like any other queued pick, and `log_best` writes one
  `BEST_STRATEGY` block: a header with the base, then one row per pattern best to worst with net, a `#`/`-` bar scaled to the largest net,
  wins, losses, the highest tier its bets reached and the window round that reached it (`T3@r27`), and its holds. The header and the
  winning row are INFO; the other rows follow as one DEBUG record, so they show only with `ocr_debug = 1`. Row 1 is the pick, named again
  by the `STRATEGY active` line at the next round. Every confirmed read enters the
  window whatever the round did (hold, skip, watch); a round with no confirmed read (formula-only,
  interrupted, stalled, capture error), an `unknown` outcome (an ambiguous green-and-red frame or an unpaid backstop; its CSV row still carries the read but
  `write_crash_row` keeps it out of the rate and the window) and a refresh leave no gap. The swap waits for the running ladder to return to base (the climb keeps its own hold plan until then, `set_strategy` installs the queued one, and a
  second pick before it lands replaces it), and the same pattern picked again restarts from base with the new plan (2026-10-08, reversing
  2026-09-27: a winning run finishes or loses before the 40 games decide).
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
  target and only recomputes the stake. `plan_cashout` jitters it by `cashout_range` percent either way (`uniform(1 - r/100, 1 + r/100)`, 5 now)
  when `flow.randomizing` is on, which is why a logged `target=` rarely equals the strategy cashpoint. `cashout_range` is also the single
  source for the ladder check in `load_strategies`, which rejects any ladder whose lowest cashpoint could roll to 1.01 or below: a crash round
  starts at 1.00x, so a target at or under it is one the site cannot honour. The two used to be separate literals that had to agree by hand. `submit_bet` OCRs `bet_input` and `cashout_input` before every click and types only a field whose whole decimal read (`FIELD_PATTERN`, not the
  two-decimal crashpoint match: the page once held `0.28999995` after a typed 0.28 and bet 0.29 for seven rounds, 2026-10-08) differs from the planned value, so a misclick or a hand edit is corrected on the next round and a clean round within a tier is one click on `play_button`.
  The `profit_text` echo is compared with the submitted stake after confirmation and logs `STAKE_MISMATCH`; accounting still uses the planned stake.
- Overlays stay visible while running: each one is excluded from screen capture (`SetWindowDisplayAffinity`) at creation and made click-through
  and unmovable (`WS_EX_TRANSPARENT`) from Start to Stop. Hide/Show works at any time. `raise_overlay` (SetWindowPos HWND_TOPMOST with
  FRAMECHANGED) runs after creation, after every style change, and on Show, because an ex-style change alone can drop the window behind the page. There is no manual Refresh button; the user refreshes by hand.
- Refreshing resets the ladder to base for every reason except the two in `KEEP_TIER_REASONS` - `confirmation_failures` and `input_failures` -
  which keep the pending tier, because neither ever placed a bet or risked money. Balance and trigger survive every reason.
- `refresh_failure_limit` (3) refreshes in a row with no confirmed bet between them ends the refreshing: `refresh_started` returns False,
  nothing is clicked, the phase drops back to `syncing`, the status label turns to an amber `WAITING`, and every round after it is a `watch`
  round, so the CSV and the 3+ rate keep filling while no money moves. `WAITING` and `waiting_R<n>.png` record every time it is reached, including a later stall that would
  have refreshed again. The streak resets only on a confirmed bet or Stop; autoplay mode reaches the same state from its click limit with the
  streak untouched, so a stall still refreshes there. The usual cause is an empty site balance, which the app
  balance only estimates and never sees, so nothing stops on a zero balance.
- Stop is immediate. `GameFlow.interrupt` closes an open round by phase: `submitting` becomes `not_submitted`, `confirming`/`playing` become
  `unknown`, `cashed` becomes `win` (a backstop green becomes `unknown`, since there is no read to prove its payout), no-bet rounds stay `no_bet`; then it settles once. Unknown outcomes log, reset to base, and continue.
  Stop then ends the run: `interrupt('stop')` resets the ladder to base, zeroes the random loss count and both failure streaks, and clears
  `waiting` and `refresh_streak`, so the window shows a clean slate while stopped and Start begins from whatever is picked now. Balance,
  wins, losses, unknown and the 3+ window are money and history, not run state, and survive, as does the click tally. Start itself sets only the four mode flags. A
  Stop/Start that still skipped, held or climbed from the previous run was a bug (2026-09-22); nothing decided in one run may drive the next.
- No checks inside functions that the caller already decided. If a thing is off, the caller does not call. Decide once before a loop, not per
  iteration. `set_running` disables Start, Clear images, and the MODES checkboxes while running, so their handlers never
  re-test `running`.
- Do not wrap a statement to respect a line limit: the user re-joined every call, tuple, and log line that had been split at 150 characters
  (several now over 200). Shorten a long line by naming a local or dropping words instead. The three standing exceptions left wrapped are the `GameConfig(...)` call in `main.py`, the `BITMAPINFOHEADER` fields in `screen.py` and the button `spec` tuple in `ui.py`; keep those as they are.
- No comments over two lines, and almost none at all. No unused functions, fields, or imports.
