# Crash Picker

Crash Picker is a Windows desktop bot for a crash-style betting page open in a browser. It watches fixed screen regions, places bets with pyautogui,
reads each result from exact pixel colors and Tesseract OCR, and climbs a ten-tier cashout ladder.

## Requirements

- Windows 10 or 11
- Python 3.12
- Tesseract OCR installed and on PATH (`pytesseract` runs the `tesseract` command)
- The game page open in a browser on any monitor; negative coordinates on a second monitor work
- The four packages in `requirements.txt`: pillow, numpy, pyautogui, pytesseract (tkinter ships with Python)

## Install and run

```
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe main.py
```

## First run: place the overlays

The nine overlays open in a column at the top of the primary monitor. Drag each one onto its element on the game page. The 5x5 grip at the
bottom-right corner of an overlay resizes it; `win_end_color`, `refresh_button` and `ball_start_color` have no grip, and their sizes are edited
in `data/crash_picker.json`. Save and Exit write the overlay positions and the window position; closing the window is Exit. `docs/images/` holds
a `profit_text` crop and the exact red and green swatches.

| Region | Must cover | Read for |
| --- | --- | --- |
| `play_button` | the bet button | live-bet blue `(37,115,220)`; OCR of the word `start` in autoplay mode |
| `crash_text` | the large multiplier in the middle of the page | the final crashpoint, read once after red |
| `win_end_color` | a spot that turns green on cashout and red when the round ends | red `(191,43,63)` and green `(96,221,63)` |
| `lag_crash_strip` | the row of recent multiplier pills, newest on the right | the pill values, read only during a lag check |
| `profit_text` | the profit-on-win field | the stake echo after a bet, which confirms it |
| `refresh_button` | the page reload button | one click per refresh |
| `bet_input` | the bet amount field | OCR of the amount; typed into only when it differs |
| `cashout_input` | the automatic cashout field | OCR of the target; typed into only when it differs |
| `ball_start_color` | a spot that is white while the next round is open | white `(255,255,255)` |

The bot moves the mouse and types into the browser with pyautogui. Before each bet it waits for half a second of no mouse or keyboard input, up to
two seconds, and with `move_mouse_back = 1` the cursor returns to where it was after every click or type. The exact colours, the `crash_text` white
floor and the strip thresholds are constants at the top of `screen.py` and `main.py`, not ini keys; a page that renders them differently needs those
edited.

`data/crash_picker.ini` ships with `watch_mode = 1`. The first runs read rounds and write the CSV without placing any bet. Unticking Watch mode in
the window is what enables real bets.

## Configuration

`data/crash_picker.ini` is read once at launch. A bad file shows an error dialog and exits.

| Key | Meaning |
| --- | --- |
| `balance` | starting balance of the app's own estimate |
| `bet_value` | base stake when `bankroll_betting` is 0 |
| `bankroll_betting` | 1 sizes the base stake as balance divided by `bankroll_betsize` |
| `bankroll_betsize` | divisor for bankroll sizing |
| `min_max_init_bet` | `low,high` clamp on the bankroll-sized base stake |
| `randomize_cashout` | 1 jitters each rolled target by `cashout_range` percent |
| `cashout_range` | jitter percent either way |
| `bet_holding` | 1 holds rounds after a win |
| `max_loss_skipping` | 1 skips rounds after enough base-tier losses |
| `move_mouse_back` | 1 returns the cursor to where it was after each click or type |
| `ocr_debug` | 1 saves a final-read shot per round and sets the log level to DEBUG |
| `ocr_timeout_seconds` | time limit for one OCR call |
| `hold_range` | a hold draws `randint(0, hold_range)` rounds |
| `skip_range` | a skip draws `randint(0, skip_range)` rounds |
| `base_loss_multiplier` | base-loss trigger is `floor(cashpoints[0] * base_loss_multiplier)` |
| `random_strategy_losses` | losses before random mode swaps the pattern |
| `submission_confirmation_seconds` | window after the click for `profit_text` to confirm |
| `failed_confirmation_limit` | consecutive unconfirmed or not-submitted rounds that force a refresh |
| `refresh_failure_limit` | refreshes in a row with no confirmed bet before WAITING |
| `normal_poll_seconds` | poll interval wherever the fast loop is not running |
| `after_red_wait_seconds` | wait after red before the next ready check |
| `refresh_wait_seconds` | wait after clicking refresh |
| `crashpoint_rate_enabled` | 1 shows the count on the 3+ RATE tile instead of OFF |
| `crashpoint_rate_threshold` | crashpoint that counts toward the rate |
| `crashpoint_rate_window` | number of recent reads the rate covers |
| `best_strategy_enabled` | 1 turns on Best pattern |
| `best_strategy_window` | confirmed reads between best-pattern picks |
| `watch_mode` | 1 places no bets |
| `autoplay_mode` | 1 clicks `play_button` when it reads `start` |

Save and Exit write back `watch_mode`, `autoplay_mode`, `best_strategy_enabled`, `bet_holding`, `max_loss_skipping`, `crashpoint_rate_enabled` and
`randomize_cashout`. No other line is touched.

`data/crash_strats.json` holds `current_strategy_id` and a list of `{id, label, cashpoints, multipliers}` entries, each with exactly ten tiers.
`multipliers[0]` is 1, and every cashpoint times `1 - cashout_range/100` must be at least 1.01. A ladder plays like this:

- Tier 0 bets the base stake at `cashpoints[0]`.
- A win multiplies the stake by the next tier's multiplier and moves up a tier.
- A loss returns to tier 0 at the base stake.
- A win on the final tier resets to base and refreshes the page.
- The base-loss counter counts tier 0 losses; when it reaches the trigger and skipping is on, a skip block is drawn.

Add new ladders to the list. Save rewrites only the `current_strategy_id` value.

## The window

- Status and phase line: RUNNING, WAITING or STOPPED, and what the current round is doing.
- Balance with the change since launch.
- Six tiles: WINS / LOSSES, UNKNOWN, BASE LOSS, NEXT TIER, HOLD / SKIP, 3+ RATE.
- CRASH PATTERN dropdown: the first row is `Random`, which rolls a new pattern and swaps after `random_strategy_losses` losses. While running, a pick is
  queued and takes effect at the next round, resetting the ladder to base.
- FEATURES checkboxes: Hold, Skip, 3+ Rate and Cashout. They stay live while running and apply at the next round.
- Buttons: Start, Stop, Hide overlays, Save, Clear images, Exit.
- Watch mode: every round is read, settled and written to the CSV with no bet.
- Autoplay mode: a watch round that clicks `play_button` once when it reads `start`, so the page's own autoplay restarts. After five clicks in a row
  that did not take, it stops clicking and watches. It wins over Watch mode when both are ticked.
- Best pattern: after every `best_strategy_window` confirmed reads, the bot picks the pattern that would have earned the most over those crashpoints and
  plays it for the next window. The dropdown, Hold and Skip are greyed while it is on.

The Watch, Autoplay and Best pattern checkboxes are disabled while running. Stop is immediate and returns the ladder, countdowns and streaks to a clean state.

## Output

- `data/crash_data.csv`: one row per round that reached red, as `crashpoint,startTime,endTime`. No header is written.
- `logs/crash_picker.log`: appended on every launch, one line per event (START, SUBMIT, GREEN, END, REFRESH, STRATEGY, BEST_STRATEGY).
- `data/screenshots/`: one PNG per cashout plus diagnostic shots for stalls, unconfirmed bets and lag checks. Only Clear images removes them.
- `ocr_debug = 1` adds a final read shot for every round and DEBUG logging.

## How a round runs

A round is ready when `ball_start_color` holds a white pixel and `win_end_color` shows no red. The bot types into `bet_input` and `cashout_input` only
when their OCR reads differ from the planned values, then clicks `play_button`. It reads `profit_text` for up to three seconds, clicking again after
any read past the first that still shows `0.00`, and the bet is confirmed when the stake echo appears.
A 5 ms loop on `win_end_color` then waits for green, which latches a win, or red, which ends the round. One OCR of
`crash_text` after red gives the crashpoint, and the round settles once. When a confirmed bet lost and the badge read is far below what the round's
elapsed time implies, the screen froze, and the bot reads `lag_crash_strip` to recover the missed value before settling. Streaks of unconfirmed or
not-submitted rounds, and a stalled page, trigger a page refresh; after three refreshes in a row with no confirmed bet, the next refresh request switches
the bot to WAITING, where it only watches rounds. The balance on screen is an estimate kept from settled bets; it is never read from the page.
