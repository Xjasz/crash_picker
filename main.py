import configparser
import glob
import json
import logging
import math
import os
import random
import re
import string
import sys
import tempfile
import threading
import time
from datetime import datetime

import screen
import ui
from game_flow import GameConfig, GameFlow, Strategy, parse_confirmation_text

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, 'data')
LOGS_DIR = os.path.join(PROJECT_DIR, 'logs')
INI_PATH = os.path.join(DATA_DIR, 'crash_picker.ini')
JSON_PATH = os.path.join(DATA_DIR, 'crash_picker.json')
STRATS_PATH = os.path.join(DATA_DIR, 'crash_strats.json')
CRASH_CSV_PATH = os.path.join(DATA_DIR, 'crash_data.csv')
LOG_PATH = os.path.join(LOGS_DIR, 'crash_picker.log')
SCREENSHOT_DIR = os.path.join(DATA_DIR, 'screenshots')

TIER_COUNT = 10
FAST_POLL_SECONDS = 0.005
STALL_REFRESH_SECONDS = 240.0
CAPTURE_ERROR_LIMIT_SECONDS = 5.0
DIAG_LOG_INTERVAL_SECONDS = 30.0
FINAL_READ_DELAY_SECONDS = 0.5
CONFIRM_POLL_SECONDS = 1.0
INPUT_IDLE_SECONDS = 0.5
INPUT_IDLE_CAP_SECONDS = 2.0
AUTOPLAY_CLICK_LIMIT = 5
CRASHPOINT_WHITE_FLOOR = 222
MONO_OFFSET = time.time() - time.monotonic()
CRASHPOINT_PATTERN = re.compile(r'\d+\.\d{2}')
FIELD_PATTERN = re.compile(r'\d+\.\d+')
CRASH_GROWTH_PER_SECOND = 0.06006
CRASH_START_OFFSET_SECONDS = 8.04
BALL_LEAVE_SECONDS = 0.52
CLICK_GREEN_LIMIT_SECONDS = 2.0
BET_TEXT_POLL_SECONDS = 2.0
FORMULA_OFF_RATIO = 1.5
BEST_BAR_WIDTH = 20
CURRENT_STRATEGY_VALUE = re.compile(r'("current_strategy_id"\s*:\s*)"[^"]*"')
RANDOM_ID = 'random'

logger = logging.getLogger('crash_picker')
cfg = None
flow = None
strategies = ()
features = {}
inplay_objects = []
restart_objects = []
coordinate_lock = threading.Lock()
stop_event = threading.Event()
worker_thread = None
screenshot_region = None
window_start = None

def setup_logging():
    os.makedirs(LOGS_DIR, exist_ok=True)
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(LOG_PATH, mode='a', encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    logger.addHandler(logging.StreamHandler())
    logger.propagate = False
    logger.info('Starting crash_picker logger...')

def clear_images():
    removed = failed = 0
    for file in glob.glob(os.path.join(SCREENSHOT_DIR, '*.png')):
        try:
            os.remove(file)
            removed += 1
        except OSError as exc:
            logger.error('Could not remove %s: %s', file, exc)
            failed += 1
    logger.info('CLEAR_IMAGES removed=%d failed=%d', removed, failed)
    return removed, failed

def load_config(path):
    parser = configparser.ConfigParser()
    try:
        found = parser.read(path, encoding='utf-8')
    except configparser.Error as exc:
        raise ValueError(f'{path}: {exc}')
    if not found or not parser.has_section('GAME'):
        raise ValueError(f'{path}: missing [GAME] section')
    game = parser['GAME']

    def text(key):
        if key not in game:
            raise ValueError(f'{path}: [GAME] {key} is missing')
        return game[key].strip()

    def number(key, low, strict):
        try:
            value = float(text(key))
        except ValueError:
            raise ValueError(f'{path}: {key} must be a number') from None
        if not math.isfinite(value) or value < low or (strict and value == low):
            raise ValueError(f'{path}: {key} must be a finite number {">" if strict else ">="} {low}')
        return value

    def flag(key):
        if text(key) not in ('0', '1'):
            raise ValueError(f'{path}: {key} must be 0 or 1')
        return int(text(key))

    def count(key, low=0):
        raw = text(key)
        if not (raw.isascii() and raw.isdigit()) or int(raw) < low:
            raise ValueError(f'{path}: {key} must be an integer >= {low}')
        return int(raw)

    try:
        bounds = tuple(float(part) for part in text('min_max_init_bet').split(','))
    except ValueError:
        raise ValueError(f'{path}: min_max_init_bet must be comma-separated numbers') from None
    if len(bounds) != 2 or not all(math.isfinite(v) and v > 0 for v in bounds) or bounds[0] > bounds[1]:
        raise ValueError(f'{path}: min_max_init_bet must be two ascending positive numbers')
    return GameConfig(
        balance=number('balance', 0, False), bet_value=number('bet_value', 0, True), bankroll_betting=flag('bankroll_betting'),
        bankroll_betsize=number('bankroll_betsize', 0, True), min_max_init_bet=bounds,
        randomize_cashout=flag('randomize_cashout'), cashout_range=number('cashout_range', 0, False), bet_holding=flag('bet_holding'), max_loss_skipping=flag('max_loss_skipping'),
        move_mouse_back=flag('move_mouse_back'), ocr_debug=flag('ocr_debug'),
        ocr_timeout_seconds=number('ocr_timeout_seconds', 0, True), hold_range=count('hold_range'), skip_range=count('skip_range'), base_loss_multiplier=number('base_loss_multiplier', 0, True),
        submission_confirmation_seconds=number('submission_confirmation_seconds', 0, True), random_strategy_losses=count('random_strategy_losses', 1),
        failed_confirmation_limit=count('failed_confirmation_limit', 1), refresh_failure_limit=count('refresh_failure_limit', 1), normal_poll_seconds=number('normal_poll_seconds', 0, True),
        after_red_wait_seconds=number('after_red_wait_seconds', 0, False), refresh_wait_seconds=number('refresh_wait_seconds', 0, False),
        watch_mode=flag('watch_mode'), autoplay_mode=flag('autoplay_mode'), crashpoint_rate_enabled=flag('crashpoint_rate_enabled'),
        crashpoint_rate_threshold=number('crashpoint_rate_threshold', 0, True), crashpoint_rate_window=count('crashpoint_rate_window', 1),
        best_strategy_enabled=flag('best_strategy_enabled'), best_strategy_window=count('best_strategy_window', 1),
        manual_cashout=flag('manual_cashout'), backstop_multiplier=number('backstop_multiplier', 1, True), cashout_lead_seconds=number('cashout_lead_seconds', 0, False), random_backstop=flag('random_backstop'))

def load_strategies(path, floor):
    with open(path, encoding='utf-8') as source:
        data = json.load(source)
    entries = data.get('strategies') if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError(f'{path}: strategies must be a non-empty list')
    strategies = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or not isinstance(entry.get('label'), str):
            raise ValueError(f'{path}: every strategy needs a string id and label')
        ladder = {}
        for key in ('cashpoints', 'multipliers'):
            values = entry.get(key)
            numeric = isinstance(values, list) and all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in values)
            if not numeric or len(values) != TIER_COUNT:
                raise ValueError(f'{path}: {entry["id"]} {key} must be {TIER_COUNT} finite positive numbers')
            ladder[key] = tuple(float(v) for v in values)
        if ladder['multipliers'][0] != 1.0:
            raise ValueError(f'{path}: {entry["id"]} multipliers[0] must be 1.0')
        if min(ladder['cashpoints']) * floor < 1.01:
            raise ValueError(f'{path}: {entry["id"]} every cashpoint * {floor:g} must be at least 1.01')
        strategies.append(Strategy(entry['id'], entry['label'], ladder['cashpoints'], ladder['multipliers']))
    ids = [strategy.id for strategy in strategies]
    current = data.get('current_strategy_id')
    if len(set(ids)) != len(ids) or RANDOM_ID in ids or (current not in ids and current != RANDOM_ID):
        raise ValueError(f'{path}: strategy ids must be unique, none may be "{RANDOM_ID}", and current_strategy_id must name one or be "{RANDOM_ID}"')
    return tuple(strategies), None if current == RANDOM_ID else strategies[ids.index(current)]

def save_current_strategy(strategy_id):
    with open(STRATS_PATH, encoding='utf-8') as source:
        text = source.read()
    write_atomic(STRATS_PATH, lambda target: target.write(CURRENT_STRATEGY_VALUE.sub(f'\\g<1>"{strategy_id}"', text, count=1)))

def save_ini_flags(values):
    with open(INI_PATH, encoding='utf-8') as source:
        text = source.read()
    for key, value in values.items():
        text = re.sub(rf'^{key}\s*=.*$', f'{key} = {value}', text, count=1, flags=re.MULTILINE)
    write_atomic(INI_PATH, lambda target: target.write(text))
    logger.info('SAVE ok')

def set_feature(name, value):
    features[name] = value == 1
    logger.info('FEATURE %s=%d', name, value)

def set_best(value):
    flow.best_mode = value == 1
    if flow.best_mode:
        flow.random_mode = False
    flow.set_features(**features)
    logger.info('FEATURE best_strategy_enabled=%d', value)

def write_atomic(path, writer):
    directory = os.path.dirname(os.path.abspath(path))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory, prefix=os.path.basename(path) + '.', suffix='.tmp', delete=False) as target:
            temporary = target.name
            writer(target)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)

def load_json_data():
    with open(JSON_PATH, encoding='utf-8') as source:
        data = json.load(source)
    groups = {'inplay_objects': {'play_button', 'crash_text', 'win_end_color'}, 'restart_objects': {'profit_text', 'refresh_button', 'bet_input', 'cashout_input', 'ball_start_color'}}
    for group, required in groups.items():
        entries = data.get(group)
        if not isinstance(entries, list):
            raise ValueError(f'{group} must be a list')
        group_names = set()
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get('name'), str):
                raise ValueError(f'Invalid region in {group}')
            name = entry['name']
            if name not in required:
                continue
            if name in group_names:
                raise ValueError(f'Duplicate region name: {name}')
            for key in ('x', 'y', 'width', 'height'):
                if type(entry.get(key)) is not int:
                    raise ValueError(f'{name}.{key} must be an integer')
            if entry['width'] <= 0 or entry['height'] <= 0:
                raise ValueError(f'{name} dimensions must be positive')
            group_names.add(name)
        if not required <= group_names:
            raise ValueError(f'Missing regions in {group}: {sorted(required - group_names)}')
    inplay = [entry for entry in data['inplay_objects'] if entry['name'] in groups['inplay_objects']]
    restart = [entry for entry in data['restart_objects'] if entry['name'] in groups['restart_objects']]
    window = data.get('window')
    if window is not None and (type(window.get('x')) is not int or type(window.get('y')) is not int):
        raise ValueError('window.x and window.y must be integers')
    return inplay, restart, window

def save_json_data():
    with coordinate_lock:
        data = {'inplay_objects': [dict(item) for item in inplay_objects], 'restart_objects': [dict(item) for item in restart_objects], 'window': ui.window_position()}
    write_atomic(JSON_PATH, lambda target: json.dump(data, target, indent=4))

def snapshot_regions():
    with coordinate_lock:
        return {button['name']: dict(button) for button in inplay_objects + restart_objects}

def wall_time(ts):
    return datetime.fromtimestamp(ts + MONO_OFFSET).isoformat(timespec='seconds').replace(':', '-')

def crash_row(record, text):
    formula = f'{max(1.0, math.exp(CRASH_GROWTH_PER_SECOND * (record.end_ts - record.open_ts - CRASH_START_OFFSET_SECONDS))):.2f}'
    match = CRASHPOINT_PATTERN.search(text or '')
    crashpoint = match[0] if match else formula
    note = ' FORMULA_USED' if match is None else ' FORMULA_OFF' if float(formula) > FORMULA_OFF_RATIO * float(crashpoint) else ''
    return crashpoint, formula, note, match is not None

def write_crash_row(record, crashpoint, confirmed):
    with open(CRASH_CSV_PATH, 'a', encoding='utf-8') as target:
        target.write(f'{crashpoint},{wall_time(record.open_ts)},{wall_time(record.end_ts)}\n')
    if confirmed and record.outcome != 'unknown' and record.close_reason != 'bet_gone' and flow.record_crashpoint(float(crashpoint)):
        log_best(*flow.pick_best())

def log_best(base, ranking):
    top = max(abs(row[0]) for row in ranking)
    lines = [f'BEST_STRATEGY window={cfg.best_strategy_window} base={base:.2f}']
    for rank, (net, wins, losses, holds, tier, at, strategy) in enumerate(ranking, 1):
        bar = ('#' if net > 0 else '-') * round(BEST_BAR_WIDTH * abs(net) / top)
        lines.append(f'{rank:>3} {strategy.id:<16}{net:>+10.2f} |{bar:<{BEST_BAR_WIDTH}}| W{wins} L{losses} T{tier}@r{at + 1} holds={",".join(map(str, holds)) or "-"}')
    logger.info('\n'.join(lines[:2]))
    logger.debug('\n' + '\n'.join(lines[2:]))

def save_debug_shot(name):
    try:
        screen.capture_region(screenshot_region).save(os.path.join(SCREENSHOT_DIR, f'{name}.png'), format='PNG', compress_level=1)
    except Exception:
        logger.exception('Debug screenshot failed')

def round_ready(regions):
    if not screen.has_color(screen.capture_rgb_fast(regions['ball_start_color']), screen.WHITE_RGB):
        return False
    return not screen.classify_colors(screen.capture_rgb_fast(regions['win_end_color']))[1]

def fail_submit(record, stage):
    flow.not_submitted()
    logger.warning('R#%d NOT_SUBMITTED stage=%s streak=%d', record.round_id, stage, flow.input_failure_streak)

def play_button_live(record, stage):
    if screen.has_color(screen.capture_rgb_fast(record.regions['play_button']), screen.BET_LIVE_RGB):
        return True
    fail_submit(record, stage)
    save_debug_shot(f'dark_button_R{record.round_id}_streak{flow.input_failure_streak}')
    return False

def submit_bet(record):
    bet = record.planned
    regions = record.regions
    screen.wait_for_idle(INPUT_IDLE_SECONDS, INPUT_IDLE_CAP_SECONDS)
    if not play_button_live(record, 'dark_before_typing'):
        return
    for name, value in (('bet_input', f'{bet.stake:.2f}'), ('cashout_input', f'{bet.typed:.2f}')):
        text = screen.ocr_text(name, screen.capture_region(regions[name]), cfg.ocr_timeout_seconds, whitelist='0123456789.')
        match = FIELD_PATTERN.search(text or '')
        if match and abs(float(match[0]) - float(value)) < 0.005:
            continue
        logger.info('R#%d FIELD %s reads %r, typing %s', record.round_id, name, text, value)
        if stop_event.is_set() or screen.click_button(regions[name], text=value, triple_click=True) is None:
            fail_submit(record, name)
            return
    if stop_event.is_set() or not round_ready(regions):
        fail_submit(record, 'recheck')
        return
    if not play_button_live(record, 'dark_before_click'):
        return
    click_ts = screen.click_button(regions['play_button'])
    if click_ts is None:
        fail_submit(record, 'click')
        return
    flow.submitted(click_ts)

def confirmation_loop(record):
    deadline = record.click_ts + cfg.submission_confirmation_seconds
    next_read = time.monotonic()
    reads = 0
    while not stop_event.is_set():
        now = time.monotonic()
        if now >= deadline:
            flow.confirmation_timeout()
            logger.warning('R#%d UNCONFIRMED click_ts=%.3f streak=%d', record.round_id, record.click_ts, flow.failed_confirmation_streak)
            save_debug_shot(f'unconfirmed_R{record.round_id}_streak{flow.failed_confirmation_streak}')
            return
        if now < next_read:
            stop_event.wait(min(next_read - now, deadline - now))
            continue
        img = screen.capture_region(record.regions['profit_text'])
        budget = min(cfg.ocr_timeout_seconds, deadline - time.monotonic())
        if budget > 0.05:
            text = screen.ocr_text('profit_text', img, budget, whitelist='0123456789.,')
            value = parse_confirmation_text(text) if text is not None else None
            if value is not None:
                flow.confirmed(text, now)
                logger.info('R#%d SUBMIT click_ts=%.3f value=%s after %.2fs', record.round_id, record.click_ts, record.confirmed_text, record.confirmed_ts - record.click_ts)
                if abs(value - record.submitted.stake) > 0.005:
                    logger.warning('R#%d STAKE_MISMATCH page=%.2f planned=%.2f', record.round_id, value, record.submitted.stake)
                return
            reads += 1
            if reads > 1:
                button = screen.ocr_text('play_button', screen.capture_region(record.regions['play_button']), cfg.ocr_timeout_seconds, whitelist=string.ascii_letters)
                clicking = button is not None and button.strip().lower() == 'bet'
                logger.warning('R#%d BET_RETRY profit_text=%r play_button=%r click=%s at %.2fs', record.round_id, text, button, clicking, now - record.click_ts)
                if clicking:
                    screen.click_button(record.regions['play_button'])
        next_read = now + CONFIRM_POLL_SECONDS

def do_final_read(record):
    try:
        img = screen.capture_region(record.regions['crash_text'])
    except Exception:
        logger.exception('R#%d final capture failed', record.round_id)
        return None
    if cfg.ocr_debug:
        save_debug_shot(f'final_R{record.round_id}')
    return screen.ocr_text('crash_text', img, cfg.ocr_timeout_seconds, whitelist='0123456789.', white_floor=CRASHPOINT_WHITE_FLOOR)

def monitor_round(record):
    stall_at = record.open_ts + STALL_REFRESH_SECONDS
    win_end_color = record.regions['win_end_color']
    fail_since = None
    manual = flow.manual_cashout and flow.phase == 'playing'
    white_seen = False
    click_at = None
    bet_read_at = math.inf
    last_word = None
    while not stop_event.is_set():
        now = time.monotonic()
        if now >= stall_at:
            save_debug_shot(f'stall_R{record.round_id}')
            close_round('stalled')
            logger.warning('STALL R#%d no red for %.0fs outcome=%s balance=%.2f', record.round_id, now - record.open_ts, record.outcome, flow.balance)
            do_refresh('stalled')
            return
        due = click_at is not None and now >= click_at
        try:
            green, red = screen.classify_colors(screen.capture_rgb_fast(win_end_color))
            white = manual and record.launch_ts is None and screen.has_color(screen.capture_rgb_fast(record.regions['ball_start_color']), screen.WHITE_RGB)
            live = due and not red and screen.has_color(screen.capture_rgb_fast(record.regions['play_button']), screen.BET_LIVE_RGB)
            event = flow.colors(green, red, now)
            if manual and event is None and flow.phase == 'playing' and record.cash_click_ts is None and now >= bet_read_at and (click_at is None or now < click_at - cfg.ocr_timeout_seconds):
                bet_read_at = now + BET_TEXT_POLL_SECONDS
                text = screen.ocr_text('play_button', screen.capture_region(record.regions['play_button']), cfg.ocr_timeout_seconds, whitelist=string.ascii_letters)
                word = text.strip().lower() if text is not None else None
                if word == 'bet' or word == last_word == 'betnextround':
                    event = flow.end_round(now, 'loss', 'bet_gone')
                    logger.warning('R#%d BET_GONE play_button reads %r, crash missed', record.round_id, text)
                    save_debug_shot(f'bet_gone_R{record.round_id}')
                last_word = word
            fail_since = None
        except OSError:
            if fail_since is None:
                fail_since = now
                logger.exception('R#%d capture failed', record.round_id)
            if now - fail_since > CAPTURE_ERROR_LIMIT_SECONDS:
                close_round('capture_error')
                return
            stop_event.wait(cfg.normal_poll_seconds)
            continue
        if due:
            click_at = None
            if live and flow.phase == 'playing':
                record.cash_click_ts = screen.click_fast(record.regions['play_button'])
            else:
                logger.warning('R#%d CLICK_SKIPPED red=%s phase=%s', record.round_id, red, flow.phase)
        if white:
            white_seen = True
        elif white_seen:
            white_seen = False
            record.launch_ts = now - BALL_LEAVE_SECONDS
            bet_read_at = record.launch_ts + BET_TEXT_POLL_SECONDS
            click_at = record.launch_ts + math.log(record.submitted.actual_target) / CRASH_GROWTH_PER_SECOND - cfg.cashout_lead_seconds
        if event == 'green':
            logger.info('R#%d GREEN +%.2fs', record.round_id, record.green_ts - record.click_ts)
            bet = record.submitted
            save_debug_shot(f'cashout_R{record.round_id}_T{bet.tier}_{bet.stake:.2f}_{bet.actual_target:.2f}_{wall_time(record.open_ts)}')
            if manual:
                via = 'click' if record.cash_click_ts and record.green_ts - record.cash_click_ts <= CLICK_GREEN_LIMIT_SECONDS else 'backstop'
                flow.clicks[via] += 1
                record.realized = bet.actual_target if via == 'click' else bet.typed
                logger.info('R#%d CASHOUT via=%s click=%s clicks=%s', record.round_id, via, f'+{record.cash_click_ts - record.launch_ts:.3f}s' if record.cash_click_ts else 'none', '{click}/{backstop}/{lost}'.format(**flow.clicks))
        elif event == 'end':
            stop_event.wait(FINAL_READ_DELAY_SECONDS)
            try:
                red_still = screen.classify_colors(screen.capture_rgb_fast(win_end_color))[1]
            except OSError:
                red_still = True
            if not red_still and record.close_reason != 'bet_gone':
                logger.warning('R#%d RED_FLASH no red %.1fs after the end frame, round still live', record.round_id, FINAL_READ_DELAY_SECONDS)
                save_debug_shot(f'red_flash_R{record.round_id}')
                record.end_ts = record.close_reason = None
                continue
            text = do_final_read(record)
            crashpoint, formula, note, confirmed = crash_row(record, text)
            reason = flow.final_read(float(crashpoint))
            target = f' target={record.submitted.actual_target:.2f}' if record.submitted else ''
            logger.info('R#%d END +%.2fs outcome=%s crashpoint=%s%s net=%.2f balance=%.2f hold=%d skip=%d baseloss=%d/%d%s%s', record.round_id, record.end_ts - record.open_ts, record.outcome, crashpoint, target, record.net, flow.balance, flow.hold_remaining, flow.skip_remaining, flow.base_loss_count, flow.base_loss_trigger, f' formula={formula}' if note else '', note)
            if record.outcome == 'unknown' and record.realized:
                logger.warning('R#%d BACKSTOP_UNPAID typed=%.2f clicks=%s', record.round_id, record.realized, '{click}/{backstop}/{lost}'.format(**flow.clicks))
            if record.cash_click_ts and record.outcome == 'loss':
                flow.clicks['lost'] += 1
                logger.warning('R#%d CLICK_LOST click=+%.3fs clicks=%s', record.round_id, record.cash_click_ts - record.launch_ts, '{click}/{backstop}/{lost}'.format(**flow.clicks))
            write_crash_row(record, crashpoint, confirmed)
            if note and cfg.ocr_debug:
                save_debug_shot(f'check_R{record.round_id}')
            if reason is not None:
                do_refresh(reason)
            return
        if flow.phase == 'playing':
            time.sleep(FAST_POLL_SECONDS)
        else:
            stop_event.wait(cfg.normal_poll_seconds)

def do_refresh(reason):
    if not flow.refresh_started(reason):
        logger.warning('WAITING reason=%s after %d refreshes with no confirmed bet, watching rounds only', reason, flow.refresh_streak)
        save_debug_shot(f'waiting_R{flow.round_counter}')
        return
    logger.info('REFRESH reason=%s streak=%d', reason, flow.refresh_streak)
    save_debug_shot(f'refresh_{reason}_R{flow.round_counter}')
    if screen.click_button(snapshot_regions()['refresh_button']) is None:
        logger.error('Refresh click failed')
    stop_event.wait(cfg.refresh_wait_seconds)
    if not stop_event.is_set():
        flow.set_phase('syncing')

def check_autoplay(record):
    text = screen.ocr_text('play_button', screen.capture_region(record.regions['play_button']), cfg.ocr_timeout_seconds, whitelist=string.ascii_letters)
    if text is None:
        return
    if 'start' not in text.lower():
        flow.autoplay_clicks = 0
    elif flow.autoplay_clicks < AUTOPLAY_CLICK_LIMIT:
        flow.autoplay_clicks += 1
        logger.info('R#%d AUTOPLAY_CLICK streak=%d', record.round_id, flow.autoplay_clicks)
        screen.wait_for_idle(INPUT_IDLE_SECONDS, INPUT_IDLE_CAP_SECONDS)
        screen.click_button(record.regions['play_button'])
    else:
        flow.waiting = True
        logger.warning('WAITING reason=autoplay_clicks after %d clicks with play_button still reading start, watching rounds only', flow.autoplay_clicks)
        save_debug_shot(f'waiting_R{record.round_id}')

def begin_round(regions):
    flow.set_features(**features)
    queued = flow.queued
    if queued is not None and (flow.pending is None or flow.pending.tier == 0):
        activate_strategy(queued)
    green, red = screen.classify_colors(screen.capture_rgb_fast(regions['win_end_color']))
    record = flow.open_round(time.monotonic(), regions, green, red)
    bet = record.planned
    typed = f' typed={bet.typed:.2f}' if bet and bet.typed != bet.actual_target else ''
    bet_text = f'tier={bet.tier} stake={bet.stake:.2f} target={bet.actual_target:.2f}{typed}' if bet else ''
    pattern = ('(R)' if flow.random_mode else '(B)' if flow.best_mode else '') + flow.strategy.label.lower().replace(' ', '_')
    logger.info('R#%d START action=%s %s hold=%d skip=%d pattern=%s', record.round_id, record.action, bet_text, flow.hold_remaining, flow.skip_remaining, pattern)
    if green or red:
        logger.warning('R#%d START stale color present green=%s red=%s', record.round_id, green, red)
    if record.action == 'play':
        submit_bet(record)
    elif record.action == 'autoplay':
        check_autoplay(record)

def run_worker():
    flow.set_phase('syncing')
    ready_since = None
    last_diag = None
    while not stop_event.is_set():
        phase = flow.phase
        record = flow.round
        if phase in ('syncing', 'ready'):
            now = time.monotonic()
            if ready_since is None:
                ready_since = last_diag = now
            regions = snapshot_regions()
            if round_ready(regions):
                ready_since = None
                begin_round(regions)
                continue
            if now - ready_since >= STALL_REFRESH_SECONDS:
                logger.warning('STALL no ready signal for %.0fs', now - ready_since)
                save_debug_shot(f'stall_ready_R{flow.round_counter}')
                close_round('stalled')
                do_refresh('stalled')
                ready_since = None
                continue
            if now - last_diag >= DIAG_LOG_INTERVAL_SECONDS:
                logger.info('DIAG waiting for ready signal %.0fs', now - ready_since)
                last_diag = now
            time.sleep(FAST_POLL_SECONDS)
        elif phase == 'confirming':
            confirmation_loop(record)
        elif phase in ('playing', 'cashed', 'watching'):
            monitor_round(record)
        elif phase == 'post_red':
            remaining = record.end_ts + cfg.after_red_wait_seconds - time.monotonic()
            if remaining > 0:
                stop_event.wait(remaining)
            flow.set_phase('ready')
    close_round('stop')
    logger.info('STOP')

def close_round(reason):
    queued = flow.queued
    if reason == 'stop' and queued is not None:
        activate_strategy(queued)
    record = flow.round
    unsettled = record is not None and not record.settled
    flow.interrupt(reason)
    if unsettled:
        logger.info('R#%d INTERRUPT reason=%s outcome=%s balance=%.2f', record.round_id, reason, record.outcome, flow.balance)
        if record.outcome == 'unknown':
            save_debug_shot(f'unknown_R{record.round_id}')

def game_worker():
    try:
        run_worker()
    except Exception:
        logger.exception('Worker crashed')
        close_round('stop')
    stop_event.set()

def worker_is_running():
    return worker_thread is not None and worker_thread.is_alive()

def start_game():
    global worker_thread, screenshot_region
    stop_event.clear()
    flow.watch_mode = ui.watch_var.get() == 1
    flow.autoplay_mode = ui.autoplay_var.get() == 1
    flow.manual_cashout = ui.manual_var.get() == 1
    flow.random_backstop = ui.backstop_var.get() == 1
    win_end_color = snapshot_regions()['win_end_color']
    screenshot_region = screen.monitor_region(win_end_color['x'], win_end_color['y'])
    ui.set_running(True)
    mode = ' random' if flow.random_mode else f' best every {cfg.best_strategy_window}' if flow.best_mode else ''
    logger.info('START watch_mode=%d autoplay_mode=%d manual_cashout=%d random_backstop=%d strategy=%s%s screenshot monitor=%s', flow.watch_mode, flow.autoplay_mode, flow.manual_cashout, flow.random_backstop, flow.strategy.id, mode, screenshot_region)
    worker_thread = threading.Thread(target=game_worker, daemon=True)
    worker_thread.start()

def stop_game():
    stop_event.set()

def activate_strategy(strategy):
    losses = flow.strategy_losses
    flow.set_strategy(strategy)
    logger.info('STRATEGY active %s trigger=%d%s', strategy.id, flow.base_loss_trigger, f' random after {losses} losses' if flow.random_mode else '')

def select_strategy(index):
    flow.random_mode = index == 0
    strategy = flow.pick_random() if flow.random_mode else strategies[index - 1]
    if strategy is flow.strategy:
        flow.queued = None
    elif worker_is_running():
        flow.queued = strategy
        logger.info('STRATEGY queued %s', strategy.id)
    else:
        activate_strategy(strategy)

def save_changes():
    try:
        save_json_data()
        save_current_strategy(RANDOM_ID if flow.random_mode else (flow.queued or flow.strategy).id)
        save_ini_flags({'watch_mode': ui.watch_var.get(), 'autoplay_mode': ui.autoplay_var.get(), 'best_strategy_enabled': int(flow.best_mode), 'bet_holding': int(features['bet_holding']), 'max_loss_skipping': int(features['max_loss_skipping']), 'crashpoint_rate_enabled': int(features['crashpoint_rate_enabled']), 'randomize_cashout': int(features['randomize_cashout']), 'manual_cashout': ui.manual_var.get(), 'random_backstop': ui.backstop_var.get()})
    except Exception as exc:
        logger.exception('SAVE error')
        ui.show_error(f'Save failed: {exc}')

def exit_program():
    logger.info('Exiting Program...')
    stop_event.set()
    if worker_is_running():
        worker_thread.join(10)
    save_changes()
    ui.root.destroy()

def main():
    global cfg, flow, strategies, inplay_objects, restart_objects, window_start
    setup_logging()
    try:
        cfg = load_config(INI_PATH)
        strategies, current = load_strategies(STRATS_PATH, 1 - cfg.cashout_range / 100)
        inplay_objects, restart_objects, window_start = load_json_data()
    except (ValueError, OSError) as exc:
        logger.error('INIT failed: %s', exc)
        ui.show_error(str(exc))
        raise SystemExit(1)
    features.update({'bet_holding': cfg.bet_holding == 1, 'max_loss_skipping': cfg.max_loss_skipping == 1, 'crashpoint_rate_enabled': cfg.crashpoint_rate_enabled == 1, 'randomize_cashout': cfg.randomize_cashout == 1})
    logger.setLevel(logging.DEBUG if cfg.ocr_debug else logging.INFO)
    screen.move_mouse_back = cfg.move_mouse_back
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    flow = GameFlow(cfg, strategies, current, random.Random())
    logger.info('INIT strategy=%s base cashpoint %s x %s -> base_loss_trigger %d', flow.strategy.id, flow.strategy.cashpoints[0], cfg.base_loss_multiplier, flow.base_loss_trigger)
    ui.build_ui(sys.modules[__name__])
    ui.root.mainloop()

if __name__ == '__main__':
    main()
