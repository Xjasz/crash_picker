# Crash Picker behavior specification

This is the original specification the project was built from. `CLAUDE.md` and `README.md` describe the shipped behavior where they differ.

This file defines the intended application. Implementation followed approval of the plan.

**The event sequence below defines the application.** The packaged helper excerpts are selected, already-written building blocks for UI and mechanical operations. Reuse their bodies by default, adapting dependency wiring only where necessary. They do not define game behavior. `data/crash_picker.ini` contains the user-supplied settings. The two exact color constants are given in section 2. Treat these inputs as settled requirements.

The package is deliberately sufficient for this task without a full previous application or historical logs. Do not request either, reconstruct earlier game logic, or audit historical failures. Design the game flow directly from this specification. Use the selected helpers that fit, adapting their dependencies to the new design. Write new helpers for the new game flow and genuinely missing operations. Replacing an included helper requires a concrete integration, correctness, or measured performance reason; stylistic rewriting is not a goal.

## 1. Two production files

Use the existing project layout. All paths are relative to the directory containing `main.py`. Complete that starter in place and create the second file only after implementation approval. Inspect the starter's existing methods as mechanical building blocks; its placeholder main body is not gameplay logic.

| File | Responsibility |
| --- | --- |
| `main.py` | Entry point, imports, shared dataclasses, configuration, coordinates, UI, overlays, input/capture/OCR/color helpers, saving/loading, logging, lifecycle controls, and the scheduling/main loop. |
| `game_flow.py` | Round decisions and transitions, submission confirmation, win/loss handling, accounting, tier progression, skip/hold countdowns, and recovery decisions. |

Main constructs the state and passes it to flow through a small explicit interface. Flow must not import the executable main module, depend on main's globals, or own a duplicate copy of state. Keep the game state under one owner and Tkinter operations on the UI thread. Define fields around actual distinct concepts, not several overlapping flags for the same fact.

Create the new loop and flow from this specification. Integrate selected helper code afterward. The Markdown helper groups are reference material, not extra runtime modules; the final application still has exactly two production Python files. Keep existing dependencies where suitable, justify additions, and avoid a framework or unrelated rewrites. Do not add explanatory comments throughout the eventual code.

Retain the existing UI capabilities. Names, internal structures, log formats, and settings may change to suit the new design.

## 2. Regions and color settings

`data/crash_picker.json` supplies desktop coordinates and dimensions, including negative coordinates on another monitor. Its array groupings organize the picker; identify region behavior by name. Do not infer game phases from those group names.

| Region | Size | Purpose |
| --- | --- | --- |
| `play_button` | 100 × 40 | Recognize exactly the word `Bet`; click once when submitting. |
| `crash_text` | 400 × 120 | Read the final crashpoint once, immediately after round-end red. |
| `win_end_color` | 10 × 10 | Detect green cashout and red round end. No OCR. |
| `profit_text` | 80 × 40 | Read the numeric Profit on Win value after a bet click. The crop excludes `$`. |
| `refresh_button` | 20 × 20 | Page refresh click. |
| `bet_input` | 160 × 40 | Bet amount entry. |
| `cashout_input` | 160 × 40 | Automatic cashout multiplier entry. |

Use only these two exact colors:

| Signal | HEX | RGB |
| --- | --- | --- |
| Red | `#BF2B3F` | `(191, 43, 63)` |
| Green | `#60DD3F` | `(96, 221, 63)` |

Compare unaltered captured pixels in the 10 × 10 `win_end_color` region. A color is present when at least one pixel exactly equals its RGB triple; all three channels must match on that same pixel. One matching frame is sufficient. Use simple equality and presence checks, without a tolerance range, approximate matching, a coverage percentage, a configurable pixel-count threshold, averaging, or consecutive-frame requirements. Do not add a palette or calibration controls. These exact values are settled, not proposed starting colors.

Keep RGB/BGR channel order consistent with the capture backend. Do not resize, blur, adjust contrast, or otherwise transform the color pixels before comparison. Exclude overlays and the cursor from the capture. The exact swatches match the supplied constants; screen-region placement and capture timing still need target-machine verification. Green anywhere outside `win_end_color` has no role in detecting the win.

If both exact colors are present in one frame, preserve any earlier green latch. If green was not already observed, that frame alone does not establish which appeared first; use the small unresolved-observation policy already required below. This does not require extra colors or a broader detector.

## 3. The complete event sequence

### Open one round

After the previous round's red observation, read its final crashpoint as described below. Begin checking `play_button` about one second after the red timestamp, at approximately 1–2 checks per second. If the final read already consumed that second, do not add another full second. Expect the next betting window within roughly ten seconds. If it takes longer, keep waiting with bounded diagnostics; do not invent a round or click blindly.

Use trimmed, case-normalized equality with `bet`. One valid recognition opens one round and records its start timestamp. This is the time its betting window was first observed. Repeated `Bet` observations must not create extra rounds, redraw decisions, or repeat clicks. Choose exactly one action for the round: play, skip, or hold.

At initial startup or after refresh, synchronize before acting. Define the smallest boundary guard needed to prevent leftover red from ending a newly opened round. The 100-pixel crop must recognize the complete ready label without confusing a cropped portion of `Bet Next Round` with readiness. Check placement and include a targeted runtime check.

### Play: submit and confirm

Determine the bet's tier, amount, and actual automatic cashout multiplier once. Enter the amount in `bet_input`, enter the multiplier in `cashout_input`, and click `play_button` once. Keep an immutable snapshot of the values actually submitted, separate from nominal tier settings and future decisions. If input preparation takes time, a final readiness check may authorize the same round's click; it must not create another round.

Record the actual submission-click time. Immediately start checking `profit_text`, with a hard three-second monotonic deadline measured from that click. Use roughly 1–2 checks per second, starting the first immediately. A valid positive numeric value confirms participation. Zero, unreadable/blank text, malformed values, negative values, and non-finite values do not. Parse legitimate displayed formatting without fabricating digits or decimal points.

Stop reading `profit_text` as soon as confirmation occurs, or when three seconds expire. Read it again only after a later bet click. Budget individual OCR calls against the remaining deadline and define how delayed results are rejected so an old frame cannot confirm a different round.

The operating observation is that a successful bet makes `profit_text` positive before the game starts. Treat that as the intended screen contract. Check the confirmation-to-monitoring transition for very fast rounds in the validation plan. A timeout is an unconfirmed attempt; do not turn missing confirmation into a made-up win or loss. There is no second submission in the same round.

### Confirmed play: monitor green/red

Once participation is confirmed, capture and classify only `win_end_color` as fast as the selected capture method reliably supports. Keep OCR, synchronous UI calls, file writes, screenshot saving, and normal polling delays out of this critical path.

If green appears, latch `won` and its observation timestamp immediately. Red later cannot clear the win. After green, reduce monitoring to normal speed and watch only for red. A later Stop, refresh, capture error, or missing red must not erase already observed cashout evidence. A known cashout and an observed round end are distinct facts; specify how incomplete end reporting and once-only financial settlement are handled without changing the normal event sequence.

When red appears for the active, armed round, record the end timestamp exactly once. A latched green means win. If no green was observed during otherwise valid monitoring, the result is loss. An actual monitoring interruption or conflicting signal needs a small, explicit unresolved-observation policy; do not silently invent certainty. Red's continued presence must not settle the round again.

The specified fast-monitoring phase starts after confirmation. Explain any concrete timing gap that requires a change to this sequence; do not silently add continuous observation of other regions or reopen the established flow because of hypothetical possibilities.

### End a round

The first accepted red observation immediately triggers one final-read operation: exactly one `crash_text` capture and, if that capture succeeds, exactly one OCR invocation. Mark the operation as attempted before invoking capture/OCR so an exception cannot re-enter it through a generic retry loop. Capture before slower accounting, logging, screenshots, or UI work. Do not recapture, retry OCR, or run a second OCR pass. A capture failure means zero OCR invocations and no retry for that round; an OCR failure still consumes the single allowed OCR attempt. Either failure must allow the known result and next-round handling to proceed.

Save the final crashpoint as a string. Empty/unreadable output can remain empty/unreadable; it does not change a win/loss or strategy decision. Keep this recorded value immutable. Its only purpose is reporting.

Settle accounting and apply the next strategy decision once. Then return to checking `play_button` after the post-red interval described above.

### Skip, hold, or unconfirmed participation

Skipping and holding place no bet. An unconfirmed attempt stops confirmation checks at its deadline. For all these cases, watch `win_end_color` for red at normal speed. Do not perform fast green monitoring or hypothetical win/loss calculations.

Each observed round still has one start timestamp, one red/end timestamp, and one final crashpoint read. Skipped/held rounds have no stake, payout, win, or loss. Decrement their remaining count only once when the corresponding round ends. Define resynchronization for a missing boundary without counting guessed rounds.

## 4. Holds and skips

### User-selected ranges

`hold_range` and `skip_range` are independently user-configurable nonnegative integers. Each value is the inclusive endpoint of its own random draw, not an application-imposed ceiling. Accept any valid user-chosen value without an arbitrary cap. For example, either setting may be 90 or larger; a setting of 90 produces a uniform draw from 0 through 90, inclusive. Zero is a valid setting and always produces a zero count. Reject malformed, fractional, or negative inputs instead of clamping them.

The supplied INI sets `hold_range = 3` and `skip_range = 4`. Load these as the initial user-selected values: hold draws include 0, 1, 2, 3; skip draws include 0, 1, 2, 3, 4. Keep both editable and persist later valid selections. These current values are not hard caps on what the user can configure. No initial setup question is needed. Draw an integer directly; do not allocate a list of every candidate value.

Snapshot the applicable setting when an eligible trigger is handled. A later settings edit affects future draws and must not redraw or resize an existing countdown.

### Holding after a win

When a confirmed played win leaves another tiered bet pending and `bet_holding` is enabled, draw `hold_count = randint(0, hold_range)` once, with equal probability for every integer including both endpoints.

- Zero: play the next tier at the next eligible betting window.
- Two: place no bet in the next two complete rounds, then play the pending next tier.
- Keep the chosen count and pending progression. Do not redraw during held rounds or at hold completion.
- Held-round crashpoints do not affect the pending bet, payout, or countdown.

### Base-loss trigger derived at initialization

At application initialization, after loading and validating the configuration, compute `base_loss_trigger = floor(1.5 * initial_cashpoints[0])` once. Use the initial configured nominal base-tier cashpoint, not a randomized submitted target or another tier's value. Floor/truncation for this positive value follows the user's example: 25 × 1.5 = 37.5 becomes 37. The supplied base cashpoint remains 26.3, which gives 39; 25 was an example, not a replacement configuration value.

Keep the derived trigger fixed for the initialized application. Do not recalculate it on polls, bets, wins, losses, skip completion, Stop/Start, page refresh, or final-tier reset. Changing settings does not change this initialization-derived value during the current run; it is recomputed when the application is initialized again with the loaded configuration. It is derived state, not a separately editable INI threshold or random selection. Validate the initial cashpoint so the derived count is positive.

### Skipping after base-tier losses

Maintain a counter of confirmed losses incurred on base-tier bets. Identify base tier by index, not equal dollar amounts. Increment the counter once per eligible loss. Higher-tier losses do not increment it. Any confirmed win resets it to zero. Completing a skip block also resets it to zero.

After incrementing for the current eligible loss, compare the counter with the initialization-derived `base_loss_trigger`. When loss-triggered skipping is enabled and the trigger is reached, draw `skip_count = randint(0, skip_range)` once, with equal probability for every integer including both endpoints.

- Zero: there are no skipped rounds. Treat this zero-length block as completed immediately, reset the base-loss counter to zero, and play the next eligible round using normal base-tier progression. Consume the triggering decision once; do not redraw on the next poll or next ready observation.
- A positive count: skip exactly that many future complete rounds. Scheduling consumes none. Decrement only at each actual skipped round's end; reset the base-loss counter when the block completes.
- Do not stop early, extend the block, or change the draw because of crashpoints. Holds/skips neither increment base losses nor create hypothetical outcomes.

The derived loss trigger decides when to draw; `skip_range` decides the possible countdown values. These are distinct concepts. The same zero-through-setting rule applies to holds and skips, while their triggering events remain different.

## 5. Amounts, progression, and settlement

Use the exact schema and values in `data/crash_picker.ini`, including `min_max_init_bet = 0.15,1.0`. This is the canonical initial/base-bet bounds setting in configuration, dataclasses, helpers, saving/loading, and any default-file initialization. Do not introduce a duplicate alias. Validate it as two finite positive values in ascending order. Preserve the supplied settings; flag any necessary behavior change for review instead of silently changing them.

Use this intended progression contract:

- Tier zero uses the configured base bet, or the bankroll-sized base bet when enabled.
- Bankroll sizing is the estimated balance divided by the configured bankroll divisor, rounded to cents and clamped to `min_max_init_bet`. These limits apply when calculating an initial/base bet, not to higher-tier stakes. They apply again when progression returns to base.
- A win with another tier available advances to that tier. Its stake is the winning round's stake multiplied by the destination tier's `multiplys` entry, rounded to cents. Its nominal target is that tier's `cashpoints` entry.
- Example: base stake 0.15 wins; destination multiplier 14 gives next stake 2.10. That stake wins; destination multiplier 2.5 gives next stake 5.25. Holding postpones the pending bet without changing those progression steps.
- A confirmed played loss returns progression to base tier. A failed confirmation is not a loss and must not silently reset a pending higher-tier bet.
- A confirmed win at the final configured tier requires the full refresh/reset workflow described below. Do not advance beyond the tier arrays or draw a hold when no higher tier exists.
- With cashout randomization enabled, select the actual target once per planned bet from ±5% of its nominal target, rounded to two decimals. Keep the actual submitted value distinct. Do not repeatedly randomize while polling or holding.

For automatic cashout, estimated gross return is submitted stake × actual submitted cashout multiplier. Net profit subtracts the stake. Define the exact numerical representation, rounding rule, and rounding stage, then update balance/counters once. Base-bet bounds apply to base sizing; do not silently apply them as new limits on higher-tier stakes. A confirmed loss subtracts the stake once. Non-playing rounds change no balance.

The specified flow relies on automatic cashout through `cashout_input`. A manual early cashout can still produce green, but the configured target cannot establish its actual payout. State the scope of accounting rather than inventing an amount or adding continuous multiplier OCR.

Keep tier index, statistical counters, the initialization-derived base-loss trigger, the mutable base-loss counter, and remaining hold/skip counts distinct wherever their meanings differ. Freeze a round's submitted values; later UI/config updates must not rewrite that round's history.

## 6. Recovery, timing, and logging

### Final-tier win: full refresh/reset

This behavior is settled: after the last tier wins, return the game strategy to its initial base state through the page-refresh/reset workflow. In the normal sequence, latch green, wait for red, perform the one final read, and settle the win once before requesting one `refresh_button` page refresh. Do not refresh immediately on green or skip normal round completion. If observation is interrupted before red, preserve the win and apply the documented recovery policy without fabricating a final read or settling twice.

Use one central refresh workflow with an explicit reason. The final-tier reason clears the tier progression back to index zero, pending higher-tier values, hold/skip countdowns, base-loss counter, failed-confirmation streak, and completed-round transient flags after the round record has been retained. Recalculate the next base stake with the existing base-sizing rule from the settled balance. Prepare a fresh base-tier actual target when that bet is planned. Page reload must finish and round boundaries must be synchronized before another submission.

Resetting game strategy does not erase already settled winnings, replace the estimated balance with the original seed balance, delete logs/history, or discard saved settings/coordinates. Preserve the initialization-derived `base_loss_trigger`; this reset is not another application initialization. Define the field-level reset list in the plan. An input-recovery refresh after an unconfirmed higher-tier attempt must still follow the specified pending-tier preservation rule; do not accidentally apply the final-tier strategy reset to every refresh reason.

### Submission recovery and lifecycle

Five consecutive unconfirmed submission attempts, across five distinct played rounds, request one `refresh_button` refresh. A successful confirmation resets this failure streak. Skips/holds neither add failures nor pretend to confirm a bet. Repeated OCR errors or frames in one round count as at most that one failed attempt.

Specify refresh timing, cooldown, resynchronization, and which pending progression/statistics survive it. Keep Stop/Exit responsive. An interrupted round must preserve already observed facts without inventing a result. Define Start after Stop, page refresh, process restart, and a deliberate new session as separate lifecycle cases; do not assume they all reset the same state. Configuration and coordinate edits must take effect at a defined boundary, with the current round retaining a consistent snapshot. Keep slow waits monotonic and interruptible.

Measure actual capture throughput on the intended Windows multi-monitor setup. The helper returning a 10 × 10 image is a baseline, not a promise about native capture cost. Keep color classification small and avoid allocating or dispatching unnecessary work per frame. Screenshot persistence must not block the critical green-detection phase.

Design concise console/file logs for the new events: round ID, action/tier, submitted values, click/confirmation timing, green/red timestamps, outcome, final crashpoint string, settled balance, remaining hold/skip count, and recovery reason. Log transitions rather than every frame. Keep diagnostics bounded.
