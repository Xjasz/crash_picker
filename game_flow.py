import math
import re
from collections import deque
from dataclasses import dataclass
from decimal import Decimal

CONFIRMATION_PATTERN = re.compile(r'^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$')
KEEP_TIER_REASONS = {'confirmation_failures', 'input_failures'}
BEST_HOLD_MAX = 3
BACKSTOP_RANGE = (2, 1000)

@dataclass(frozen=True)
class GameConfig:
    balance: float
    bet_value: float
    bankroll_betting: int
    bankroll_betsize: float
    min_max_init_bet: tuple
    randomize_cashout: int
    cashout_range: float
    bet_holding: int
    max_loss_skipping: int
    move_mouse_back: int
    ocr_debug: int
    ocr_timeout_seconds: float
    hold_range: int
    skip_range: int
    base_loss_multiplier: float
    random_strategy_losses: int
    submission_confirmation_seconds: float
    failed_confirmation_limit: int
    refresh_failure_limit: int
    normal_poll_seconds: float
    after_red_wait_seconds: float
    refresh_wait_seconds: float
    watch_mode: int
    autoplay_mode: int
    crashpoint_rate_enabled: int
    crashpoint_rate_threshold: float
    crashpoint_rate_window: int
    best_strategy_enabled: int
    best_strategy_window: int
    manual_cashout: int
    backstop_multiplier: float
    cashout_lead_seconds: float
    random_backstop: int

@dataclass(frozen=True)
class Strategy:
    id: str
    label: str
    cashpoints: tuple
    multipliers: tuple

@dataclass(frozen=True)
class PlannedBet:
    tier: int
    stake: float
    actual_target: float
    typed: float

@dataclass
class RoundRecord:
    round_id: int
    open_ts: float
    regions: dict
    action: str
    planned: PlannedBet | None = None
    submitted: PlannedBet | None = None
    click_ts: float | None = None
    confirmed_ts: float | None = None
    confirmed_text: str | None = None
    armed: bool = False
    green_ts: float | None = None
    launch_ts: float | None = None
    cash_click_ts: float | None = None
    realized: float | None = None
    crashpoint: float | None = None
    end_ts: float | None = None
    outcome: str | None = None
    close_reason: str | None = None
    net: float = 0.0
    settled: bool = False

@dataclass
class Climb:
    start: int
    strategy: Strategy
    rows: list
    won: float = 0.0
    net: float = 0.0
    end: str = 'open'

def calculate_base_bet(cfg, balance):
    if cfg.bankroll_betting == 1 and balance > 0:
        low, high = cfg.min_max_init_bet
        return min(max(round(round(balance, 2) / cfg.bankroll_betsize, 2), low), high)
    return cfg.bet_value

def parse_confirmation_text(text):
    text = text.strip()
    if not CONFIRMATION_PATTERN.match(text):
        return None
    value = float(text.replace(',', ''))
    return value if value > 0 and math.isfinite(value) else None

def best_holds(strategy, crashes, base):
    tiers = len(strategy.cashpoints)
    stakes = [base]
    for multiplier in strategy.multipliers[1:]:
        stakes.append(round(stakes[-1] * multiplier, 2))

    def run(i, tier, holds):
        if i >= len(crashes):
            return 0.0, 0, 0, holds, -1, 0
        stake, target = stakes[tier], strategy.cashpoints[tier]
        won = crashes[i] >= target
        if not won or tier + 1 == tiers:
            nxt = run(i + 1, 0, holds)
        elif tier < len(holds):
            nxt = run(i + 1 + holds[tier], tier + 1, holds)
        else:
            nxt = max((run(i + 1 + hold, tier + 1, holds + (hold,)) for hold in range(BEST_HOLD_MAX + 1)), key=lambda result: result[0])
        net, wins, losses, plan, top, at = nxt
        gain = round(round(stake * target, 2) - stake, 2) if won else -stake
        if top <= tier:
            top, at = tier, i
        return round(net + gain, 2), wins + won, losses + (not won), plan, top, at
    return run(0, 0, ())

class GameFlow:
    def __init__(self, cfg, strategies, strategy, rng):
        self.cfg = cfg
        self.rng = rng
        self.phase = 'stopped'
        self.watch_mode = False
        self.autoplay_mode = False
        self.manual_cashout = False
        self.random_backstop = False
        self.clicks = {'click': 0, 'backstop': 0, 'lost': 0}
        self.round = None
        self.round_counter = 0
        self.best_mode = cfg.best_strategy_enabled == 1
        self.crashpoints = deque(maxlen=cfg.crashpoint_rate_window)
        self.rate_hits = 0
        self.window = []
        self.queued_plan = ()
        self.climbs = []
        self.climb = None
        self.strategies = strategies
        self.random_mode = strategy is None and not self.best_mode
        self.set_strategy(strategy or self.rng.choice(strategies))
        self.set_features(cfg.bet_holding == 1, cfg.max_loss_skipping == 1, cfg.crashpoint_rate_enabled == 1, cfg.randomize_cashout == 1)
        self.failed_confirmation_streak = 0
        self.input_failure_streak = 0
        self.autoplay_clicks = 0
        self.refresh_streak = 0
        self.waiting = False
        self.balance = cfg.balance
        self.wins = 0
        self.losses = 0
        self.unknown = 0
        self.unknown_stake = 0.0
        self.last_refresh_reason = None
        self.update_text()

    def set_strategy(self, strategy):
        self.queued = None
        self.strategy = strategy
        self.strategy_losses = 0
        self.hold_plan, self.queued_plan = self.queued_plan, ()
        self.base_loss_trigger = int(Decimal(repr(strategy.cashpoints[0])) * Decimal(repr(self.cfg.base_loss_multiplier)))
        self.reset_ladder()

    def pick_random(self):
        return self.rng.choice([item for item in self.strategies if item is not self.strategy])

    def reset_ladder(self):
        self.pending = None
        self.hold_remaining = 0
        self.skip_remaining = 0
        self.base_loss_count = 0
        if self.climb is not None:
            self.close_climb('reset')

    def close_climb(self, end):
        self.climb.end = end
        self.climbs.append(self.climb)
        self.climb = None

    def track_climb(self, record):
        if self.climb is None:
            self.climb = Climb(record.round_id, self.strategy, [])
        self.climb.rows.append(record)
        self.climb.net = round(self.climb.net + record.net, 2)
        if record.outcome == 'win':
            self.climb.won = round(self.climb.won + record.net, 2)
        if self.pending is None or self.pending.tier == 0:
            self.close_climb('final_tier' if record.outcome == 'win' else record.outcome)

    def set_features(self, bet_holding, max_loss_skipping, crashpoint_rate_enabled, randomize_cashout):
        free = not self.best_mode
        self.holding, self.skipping, self.rate_on, self.randomizing = free and bet_holding, free and max_loss_skipping, crashpoint_rate_enabled, randomize_cashout
        if not self.holding and not self.hold_plan:
            self.hold_remaining = 0
        if not self.skipping:
            self.skip_remaining = 0

    def record_crashpoint(self, value):
        self.crashpoints.append(value)
        self.rate_hits = sum(1 for point in self.crashpoints if point >= self.cfg.crashpoint_rate_threshold)
        if not self.best_mode:
            return False
        self.window.append(value)
        return len(self.window) == self.cfg.best_strategy_window

    def pick_best(self):
        base = calculate_base_bet(self.cfg, self.balance)
        ranking = sorted(((*best_holds(strategy, self.window, base), strategy) for strategy in self.strategies), key=lambda row: row[0], reverse=True)
        self.window = []
        self.queued, self.queued_plan = ranking[0][6], ranking[0][3]
        return base, ranking

    def plan_cashout(self, nominal):
        spread = self.cfg.cashout_range / 100
        target = round(nominal * self.rng.uniform(1 - spread, 1 + spread), 2) if self.randomizing else nominal
        typed = round(target * (self.rng.uniform(*BACKSTOP_RANGE) if self.random_backstop else self.cfg.backstop_multiplier), 2) if self.manual_cashout else target
        return target, typed

    def set_phase(self, phase):
        self.phase = phase
        self.update_text()

    def open_round(self, ts, regions, green, red):
        self.round_counter += 1
        action = 'autoplay' if self.autoplay_mode and not self.waiting else 'watch' if self.watch_mode or self.waiting else 'skip' if self.skip_remaining > 0 else 'hold' if self.hold_remaining > 0 else 'play'
        record = RoundRecord(self.round_counter, ts, regions, action, armed=not green and not red)
        if action == 'play':
            if self.pending is None:
                self.pending = PlannedBet(0, calculate_base_bet(self.cfg, self.balance), *self.plan_cashout(self.strategy.cashpoints[0]))
            record.planned = self.pending
            self.phase = 'submitting'
        else:
            record.outcome = 'no_bet'
            self.phase = 'watching'
        self.round = record
        self.update_text()
        return record

    def not_submitted(self):
        self.round.outcome = 'not_submitted'
        self.input_failure_streak += 1
        self.set_phase('watching')

    def submitted(self, click_ts):
        self.round.submitted = self.pending
        self.round.click_ts = click_ts
        self.input_failure_streak = 0
        self.set_phase('confirming')

    def confirmed(self, text, frame_ts):
        self.round.confirmed_text = text
        self.round.confirmed_ts = frame_ts
        self.failed_confirmation_streak = 0
        self.refresh_streak = 0
        self.set_phase('playing')

    def confirmation_timeout(self):
        self.round.outcome = 'unconfirmed'
        self.failed_confirmation_streak += 1
        self.set_phase('watching')

    def colors(self, green, red, ts):
        record = self.round
        if not record.armed:
            record.armed = not green and not red
            return None
        if self.phase == 'playing':
            if green and not red:
                record.green_ts = ts
                self.set_phase('cashed')
                return 'green'
            if green and red:
                return self.end_round(ts, 'unknown', 'ambiguous')
            if red:
                return self.end_round(ts, 'loss', 'red')
            return None
        if red:
            return self.end_round(ts, 'win' if self.phase == 'cashed' else record.outcome, 'red')
        return None

    def end_round(self, ts, outcome, reason):
        self.round.end_ts = ts
        self.round.outcome = outcome
        self.round.close_reason = reason
        return 'end'

    def final_read(self, crashpoint):
        reason = self.settle(crashpoint)
        self.set_phase('post_red')
        return reason

    def settle(self, crashpoint):
        record = self.round
        if record.settled:
            return None
        record.settled = True
        bet = record.submitted
        cfg = self.cfg
        strategy = self.strategy
        reason = None
        if record.outcome == 'win' and record.realized is not None and record.realized > bet.actual_target and record.realized > crashpoint:
            record.outcome = 'unknown'
            self.clicks['backstop'] -= 1
        if record.outcome == 'win':
            gross = round(bet.stake * (record.realized or bet.actual_target), 2)
            record.net = round(gross - bet.stake, 2)
            self.balance = round(self.balance + record.net, 2)
            self.wins += 1
            self.base_loss_count = 0
            nxt = bet.tier + 1
            if nxt < len(strategy.cashpoints):
                stake = round(bet.stake * strategy.multipliers[nxt], 2)
                self.pending = PlannedBet(nxt, stake, *self.plan_cashout(strategy.cashpoints[nxt]))
                if self.holding:
                    self.hold_remaining = self.rng.randint(0, cfg.hold_range)
                elif bet.tier < len(self.hold_plan):
                    self.hold_remaining = self.hold_plan[bet.tier]
            else:
                self.pending = None
                reason = 'final_tier'
        elif record.outcome == 'loss':
            record.net = -bet.stake
            self.balance = round(self.balance - bet.stake, 2)
            self.losses += 1
            self.strategy_losses += 1
            if self.random_mode and self.strategy_losses >= self.cfg.random_strategy_losses:
                self.queued = self.pick_random()
            self.pending = None
            if bet.tier == 0:
                self.pending = PlannedBet(0, calculate_base_bet(cfg, self.balance), bet.actual_target, bet.typed)
                self.base_loss_count += 1
                if self.skipping and self.base_loss_count >= self.base_loss_trigger:
                    self.skip_remaining = self.rng.randint(0, cfg.skip_range)
                    if self.skip_remaining == 0:
                        self.base_loss_count = 0
        elif record.outcome == 'no_bet' and record.close_reason == 'red':
            if record.action == 'hold':
                self.hold_remaining -= 1
            elif record.action == 'skip':
                self.skip_remaining -= 1
                if self.skip_remaining == 0:
                    self.base_loss_count = 0
                    self.pending = None
        elif record.outcome == 'unconfirmed':
            if self.failed_confirmation_streak >= cfg.failed_confirmation_limit:
                reason = 'confirmation_failures'
        elif record.outcome == 'not_submitted':
            if self.input_failure_streak >= cfg.failed_confirmation_limit:
                reason = 'input_failures'
        elif record.outcome == 'unknown':
            self.unknown += 1
            self.unknown_stake = round(self.unknown_stake + bet.stake, 2)
            self.pending = None
        record.crashpoint = crashpoint
        if record.outcome in ('win', 'loss', 'unknown') and (self.climb is not None or record.outcome == 'win'):
            self.track_climb(record)
        return reason

    def interrupt(self, reason):
        record = self.round
        if record is not None and not record.settled:
            if record.end_ts is None:
                if self.phase == 'submitting':
                    record.outcome = 'not_submitted'
                    self.input_failure_streak += 1
                elif self.phase in ('confirming', 'playing'):
                    record.outcome = 'unknown'
                elif self.phase == 'cashed':
                    record.outcome = 'win'
                record.close_reason = reason
            self.settle(0.0)
        self.round = None
        if reason == 'stop':
            self.reset_ladder()
            self.window = []
            self.hold_plan = ()
            self.strategy_losses = 0
            self.failed_confirmation_streak = 0
            self.input_failure_streak = 0
            self.autoplay_clicks = 0
            self.refresh_streak = 0
            self.waiting = False
        self.set_phase('stopped' if reason == 'stop' else 'syncing')

    def refresh_started(self, reason):
        if reason not in KEEP_TIER_REASONS:
            self.reset_ladder()
        self.failed_confirmation_streak = 0
        self.input_failure_streak = 0
        self.round = None
        self.last_refresh_reason = reason
        self.waiting = self.refresh_streak >= self.cfg.refresh_failure_limit
        if self.waiting:
            self.set_phase('syncing')
            return False
        self.refresh_streak += 1
        self.set_phase('refreshing')
        return True

    def update_text(self):
        record = self.round
        bet = record.planned if record is not None else None
        bet_text = f'{bet.stake:.2f}@{bet.actual_target:.2f}' if bet is not None else ''
        if self.phase == 'watching':
            labels = {'hold': 'Holding', 'skip': 'Skipping', 'watch': 'Watch mode', 'autoplay': 'Autoplay mode'}
            self.phase_text = labels.get(record.action, f'Watching ({record.outcome})')
        elif self.phase in ('submitting', 'playing', 'cashed', 'confirming'):
            self.phase_text = f'{self.phase.capitalize()} {bet_text}'
        elif self.phase == 'refreshing':
            self.phase_text = f'Refreshing {self.last_refresh_reason}'
        else:
            labels = {'syncing': 'Syncing', 'ready': 'Ready wait', 'post_red': 'Round over'}
            self.phase_text = labels.get(self.phase, 'Stopped')
