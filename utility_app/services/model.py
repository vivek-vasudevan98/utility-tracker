"""
Consumption model: judges each day's usage against what was expected.

    expected = baseline + effects

Effects: how much weather, Sun-Wed, events and occupancy add to (or take
off) a day's usage, with a separate level for each stretch between step
changes so a fix can't be mistaken for an effect.

Baseline: the recent level once effects are taken out, i.e. the average of
(usage - effects) over the last 28 good reads since the latest step change.
It follows gradual drift both ways.

Two passes over the history:

1. Step changes. Each day is tested as a possible start of a step: the
   effects are learned from the whole history allowing a step there (so
   neither the weather nor the step is mistaken for the other), then the 7
   reads from that day are compared with the 28 reads before it:
     - all 15%+ below expected (or below the same weeks last year): a fix.
       The baseline restarts from the first of those reads.
     - all 15%+ above expected: a rise. Those reads, and the rest of the
       rise, are kept out of the baseline until the user confirms it.
   Gas also checks that cold days aren't drifting away from mild days (a
   heating problem); those cold days are kept out of the baseline too.

2. Judging each day, with effects learned once a month from data 3 to 15
   months old. They are checked on the last 90 days, which they never saw:
   until they beat a plain 28-day average there, the utility is "still
   learning" and days are judged with the step-change pass's effects
   (learned from the whole history) instead. A day is flagged when it
   misses expected by more than twice the typical miss.
"""
from datetime import date, timedelta
from statistics import median
import numpy as np
from utility_app import db
from utility_app.models import UtilityEntry, ConfirmedRise
from utility_app.services.calculations import METERS, get_daily_usage
from utility_app.services.events import get_event_loads
from utility_app.services.occupancy import get_occupancy
from utility_app.services.weather_service import (
    get_weather_range, heating_degree_days, cooling_degree_days
)

# Inputs each utility's usage is explained by
INPUTS = {
    'gas': ('hdd', 'sun_hdd', 'sun_wed'),
    'electricity': ('hdd', 'cdd', 'event', 'solar', 'sun_wed'),
    'water': ('occupancy', 'sun_wed'),
}
INPUT_LABELS = {
    'hdd': 'per heating degree-day (below 16 °C)',
    'cdd': 'per cooling degree-day (above 17 °C)',
    'occupancy': 'per percentage point of occupancy',
    'sun_hdd': 'per hour of sunshine, per heating degree-day',
    'solar': 'per MJ/m² of solar radiation',
    'sun_wed': 'on Sun–Wed',
    'event': 'per point of event load',
}
# Inputs that come from the downloaded weather
WEATHER_INPUTS = {'hdd', 'cdd', 'temp', 'sun_hdd', 'solar'}
# Inputs that can be unknown on a day (not uploaded): they are learned only
# from days where they are known, and an unknown day is taken as typical
OPTIONAL_INPUTS = ('event', 'occupancy')
# Inputs learned at any value; the others need MIN_ACTIVE_DAYS days above 0
LEVEL_INPUTS = ('sun_wed', 'occupancy')
COLD_BASE = 8.0             # °C below which a day counts as cold in the gas heating check
LOW_DAYS = (6, 0, 1, 2)     # Sun, Mon, Tue, Wed (Python weekday numbers)

# Effects for judging days are learned from data this many months old and older...
HOLDOUT_MONTHS = 3
# ...going back this many months further
TRAINING_MONTHS = 12
MIN_TRAINING_DAYS = 90
# An input is only learned once this many training days have it (e.g. cold days)
MIN_ACTIVE_DAYS = 20

BASELINE_READS = 28
MIN_BASELINE_READS = 3
STEP_READS = 7
STEP_CHANGE = 0.15
# Same weeks last year: +/- this many days around the run, needing this many good reads
YOY_WINDOW_DAYS = 14
MIN_YOY_READS = 14

EVALUATION_DAYS = 90
MIN_EVALUATION_READS = 30
FLAG_MULTIPLE = 2

# Gas heating check: cold-day misses this far above mild-day misses (as a
# share of the baseline), with this many cold and mild reads in the last 28
HEATING_GAP = 0.15
MIN_HEATING_READS = 7

# Outlier days (e.g. a misread meter) are kept out of training and baselines:
# more than this many robust standard deviations from the surrounding median
OUTLIER_SPREAD = 4
OUTLIER_NEIGHBOURS = 7


def shift_months(day: date, months: int) -> date:
    """The 1st of the month `months` away from `day`'s month."""
    years, month_index = divmod(day.month - 1 + months, 12)
    return date(day.year + years, month_index + 1, 1)


def day_inputs(day: date, weather, event_load, occupancy):
    """
    Every model input for one day. Weather inputs are None when the day's
    weather isn't downloaded; event and occupancy are None when not uploaded.
    """
    inputs = {
        'sun_wed': 1.0 if day.weekday() in LOW_DAYS else 0.0,
        'event': event_load,
        'occupancy': occupancy,
        'hdd': None, 'cdd': None, 'temp': None, 'sun_hdd': None, 'solar': None,
    }
    if weather:
        temp = weather['temp_mean']
        inputs.update({
            'hdd': heating_degree_days(temp),
            'cdd': cooling_degree_days(temp),
            'temp': temp,
            # Sun only saves gas when there is heating to save: none on a warm day
            'sun_hdd': weather['sunshine_hours'] * heating_degree_days(temp),
            'solar': weather['solar_mj'],
        })
    return inputs


def mark_outliers(values: list) -> list:
    """True for each value that sits within the normal spread of its neighbours."""
    good = []
    for i, value in enumerate(values):
        around = values[max(0, i - OUTLIER_NEIGHBOURS):i] + values[i + 1:i + 1 + OUTLIER_NEIGHBOURS]
        if len(around) < 3:
            good.append(True)
            continue
        mid = median(around)
        spread = median(abs(v - mid) for v in around) * 1.4826 or 1.0
        good.append(abs(value - mid) <= OUTLIER_SPREAD * spread)
    return good


def rms(values) -> float:
    return float(np.sqrt(np.mean(np.square(values))))


class ConsumptionModel:
    """One utility's history: its step changes, and each day judged as it would have been at the time."""

    def __init__(self, utility: str):
        self.utility = utility
        self.inputs = INPUTS[utility]
        self.days = []            # dicts: date, usage, inputs, good, held, expected, flagged, mode
        self.confirmed = sorted(
            date.fromisoformat(r.start_date) for r in ConfirmedRise.query.filter_by(utility=utility)
        )
        self.boundaries = list(self.confirmed)   # where a new baseline stretch starts
        self.fixes = []
        self.rises = []
        self.heating_alerts = []
        self.step_effects = None  # effects learned from the whole history, with its step changes
        self.fit = None           # the current month's judging effects, mode and typical miss
        self.fits = {}            # month start -> that month's fit
        self.typical = {'event': 0.0}  # value used for an optional input on a day it's unknown

    # ---------- data ----------

    def load(self):
        first = db.session.query(db.func.min(UtilityEntry.date)).scalar()
        if first is None:
            return
        start, end = date.fromisoformat(first), date.today()
        diff_key = METERS[self.utility][0]
        usage = [r for r in get_daily_usage(start, end) if r[diff_key] is not None]
        # Only download weather for utilities that use it
        weather = get_weather_range(start, end) if set(self.inputs) & WEATHER_INPUTS else {}
        events = get_event_loads(start, end)
        occupancy = get_occupancy(start, end)
        if occupancy:
            self.typical['occupancy'] = sum(occupancy.values()) / len(occupancy)

        good = mark_outliers([r[diff_key] for r in usage])
        for r, is_good in zip(usage, good):
            w = weather.get(r['date'])
            day = date.fromisoformat(r['date'])
            self.days.append({
                'date': day,
                'usage': float(r[diff_key]),
                'inputs': day_inputs(day, w, events.get(r['date']), occupancy.get(r['date'])),
                'good': is_good,
                'held': False,
                'expected': None,
                'flagged': False,
                'mode': None,
            })

    # ---------- effects ----------

    def has_inputs(self, day: dict) -> bool:
        """True when every input this utility needs, apart from optional ones, is known."""
        return all(day['inputs'][n] is not None for n in self.inputs if n not in OPTIONAL_INPUTS)

    def stretch_start(self, day: date, boundaries=None):
        starts = [b for b in (self.boundaries if boundaries is None else boundaries) if b <= day]
        return starts[-1] if starts else date.min

    def train(self, start: date, end: date, boundaries=None):
        """
        Learns the effects from the good days in start..end (end exclusive),
        with one level per stretch between `boundaries` (default: the steps found).
        """
        boundaries = self.boundaries if boundaries is None else boundaries
        rows = [d for d in self.days
                if start <= d['date'] < end and d['good'] and not d['held'] and self.has_inputs(d)]

        used = []
        for name in self.inputs:
            candidate = rows
            if name in OPTIONAL_INPUTS:
                candidate = [d for d in rows if d['inputs'][name] is not None]
                if len(candidate) < MIN_TRAINING_DAYS:
                    continue      # not enough of it uploaded yet: leave it out
            if name not in LEVEL_INPUTS and sum(d['inputs'][name] > 0 for d in candidate) < MIN_ACTIVE_DAYS:
                continue
            rows = candidate
            used.append(name)
        # Re-check against the (possibly smaller) set of rows: an input that never varies can't be learned
        used = [n for n in used if np.ptp([d['inputs'][n] for d in rows] or [0]) > 0]

        if len(rows) < MIN_TRAINING_DAYS or not used:
            return None, len(rows)

        # One level per baseline stretch, so step changes don't leak into the effects
        row_stretch = [self.stretch_start(d['date'], boundaries) for d in rows]
        stretches = sorted(set(row_stretch))
        matrix = np.array([
            [1.0 if rs == s else 0.0 for s in stretches]
            + [d['inputs'][n] for n in used]
            for d, rs in zip(rows, row_stretch)
        ])
        target = np.array([d['usage'] for d in rows])
        coefs, *_ = np.linalg.lstsq(matrix, target, rcond=None)
        return dict(zip(used, coefs[len(stretches):].tolist())), len(rows)

    def effect(self, day: dict, effects: dict) -> float:
        if not effects:
            return 0.0
        total = 0.0
        for name, coef in effects.items():
            value = day['inputs'][name]
            # An unknown optional input counts as typical (no events, average occupancy)
            total += coef * (self.typical.get(name, 0.0) if value is None else value)
        return total

    # ---------- expectation ----------

    def usable(self, day: dict, effects) -> bool:
        return day['good'] and not day['held'] and (not effects or self.has_inputs(day))

    def baseline(self, i: int, effects):
        """Average of (usage - effects) over the good reads before day i in its stretch."""
        start = self.stretch_start(self.days[i]['date'])
        level = []
        for d in reversed(self.days[:i]):
            if d['date'] < start or len(level) == BASELINE_READS:
                break
            if self.usable(d, effects):
                level.append(d['usage'] - self.effect(d, effects))
        if len(level) < MIN_BASELINE_READS:
            return None
        return sum(level) / len(level)

    def expected(self, i: int, effects):
        day = self.days[i]
        if effects and not self.has_inputs(day):
            return None
        base = self.baseline(i, effects)
        return None if base is None else base + self.effect(day, effects)

    # ---------- pass 1: step changes ----------

    def find_steps(self):
        """Walks the history testing each day as the possible start of a step change."""
        i = 0
        while i + STEP_READS <= len(self.days):
            i = self.test_step(i)
        self.step_effects, _ = self.train(date.min, date.max)
        if self.utility == 'gas' and self.step_effects:
            self.check_heating(self.step_effects)

    def test_step(self, i: int) -> int:
        """Tests for a step starting at day i; returns the next day to test."""
        first = self.days[i]
        run = self.days[i:i + STEP_READS]
        start = self.stretch_start(first['date'])
        # Judge against a settled baseline: at least STEP_READS reads of this stretch before it
        settled = sum(1 for d in self.days[:i] if d['date'] >= start)
        if settled < STEP_READS or any(d['held'] or not self.has_inputs(d) for d in run):
            return i + 1

        effects, _ = self.train(date.min, date.max, sorted(self.boundaries + [first['date']]))
        if effects is None:
            return i + 1
        base = self.baseline(i, effects)
        if base is None:
            return i + 1
        actual = [d['usage'] for d in run]
        expect = [base + self.effect(d, effects) for d in run]
        if min(expect) <= 0:
            return i + 1

        change = sum(actual) / sum(expect) - 1
        is_fix = all(a <= (1 - STEP_CHANGE) * e for a, e in zip(actual, expect))
        if not is_fix:
            # Same weeks last year, only counting a drop that is new: if the
            # baseline had already come down that far, there's no step here
            last_year = self.last_year_level(run, effects)
            if last_year and base > (1 - STEP_CHANGE) * last_year:
                yoy = [last_year + self.effect(d, effects) for d in run]
                if min(yoy) > 0 and all(a <= (1 - STEP_CHANGE) * e for a, e in zip(actual, yoy)):
                    is_fix, change = True, sum(actual) / sum(yoy) - 1

        if is_fix:
            self.boundaries = sorted(self.boundaries + [first['date']])
            self.fixes.append({'start': first['date'], 'detected': run[-1]['date'], 'change': change})
            return i + STEP_READS

        if all(a >= (1 + STEP_CHANGE) * e for a, e in zip(actual, expect)):
            # Hold the rise for as long as it lasts
            j = i
            while j < len(self.days) and self.has_inputs(self.days[j]) and \
                    self.days[j]['usage'] >= (1 + STEP_CHANGE) * (base + self.effect(self.days[j], effects)):
                self.days[j]['held'] = True
                j += 1
            self.rises.append({
                'start': first['date'], 'detected': run[-1]['date'], 'last': self.days[j - 1]['date'],
                'ongoing': j == len(self.days), 'change': change,
            })
            return j
        return i + 1

    def last_year_level(self, run: list, effects):
        """The level (usage - effects) over the same weeks a year before the run, or None."""
        lo = run[0]['date'] - timedelta(days=364 + YOY_WINDOW_DAYS)
        hi = run[-1]['date'] - timedelta(days=364 - YOY_WINDOW_DAYS)
        level = [d['usage'] - self.effect(d, effects) for d in self.days
                 if lo <= d['date'] <= hi and self.usable(d, effects)]
        return sum(level) / len(level) if len(level) >= MIN_YOY_READS else None

    def check_heating(self, effects):
        """Holds cold days out of the baseline while they drift up compared with mild days."""
        for i, day in enumerate(self.days):
            if day['inputs']['temp'] is None or day['inputs']['temp'] >= COLD_BASE or day['held']:
                continue
            base = self.baseline(i, effects)
            if base is None or base <= 0:
                continue
            start = self.stretch_start(day['date'])
            cold, mild = [], []
            for j in range(max(0, i - BASELINE_READS), i):
                d = self.days[j]
                if d['date'] < start or not self.usable(d, effects):
                    continue
                expected = self.expected(j, effects)
                if expected is not None:
                    (cold if d['inputs']['temp'] < COLD_BASE else mild).append(d['usage'] - expected)
            if len(cold) < MIN_HEATING_READS or len(mild) < MIN_HEATING_READS:
                continue
            if sum(cold) / len(cold) - sum(mild) / len(mild) > HEATING_GAP * base:
                day['held'] = True
                alert = self.heating_alerts[-1] if self.heating_alerts else None
                if alert and (day['date'] - alert['last']).days <= STEP_READS:
                    alert['last'] = day['date']
                else:
                    self.heating_alerts.append({'start': day['date'], 'last': day['date']})

    # ---------- pass 2: judging each day ----------

    def retrain(self, i: int):
        """
        This month's effects (3 to 15 months old), checked on the last 90 days
        against a plain 28-day average. Until they beat it, the utility is
        still learning and days are judged with the step-change pass's effects
        (learned from the whole history) instead.
        """
        month_start = self.days[i]['date'].replace(day=1)
        window_start = shift_months(month_start, -(HOLDOUT_MONTHS + TRAINING_MONTHS))
        window_end = shift_months(month_start, -HOLDOUT_MONTHS)
        effects, training_days = self.train(window_start, window_end)

        eval_from = month_start - timedelta(days=EVALUATION_DAYS)
        model_miss, plain_miss, learning_miss = [], [], []
        for j in range(i - 1, -1, -1):
            d = self.days[j]
            if d['date'] < eval_from:
                break
            if not d['good'] or d['held']:
                continue
            plain = self.expected(j, None)
            modelled = self.expected(j, effects) if effects else None
            learning = self.expected(j, self.step_effects)
            if plain is None or learning is None or (effects and modelled is None):
                continue
            plain_miss.append(d['usage'] - plain)
            learning_miss.append(d['usage'] - learning)
            if effects:
                model_miss.append(d['usage'] - modelled)

        enough = len(plain_miss) >= MIN_EVALUATION_READS
        use_model = bool(effects) and enough and rms(model_miss) < rms(plain_miss)
        self.fit = {
            'month': month_start,
            'effects': effects,
            'mode': 'model' if use_model else 'learning',
            'training_days': training_days,
            'training_period': (window_start, window_end - timedelta(days=1)),
            'model_miss': rms(model_miss) if model_miss else None,
            'plain_miss': rms(plain_miss) if plain_miss else None,
            'evaluation_reads': len(plain_miss),
            'typical_miss': (rms(model_miss) if use_model else rms(learning_miss)) if enough else None,
        }
        self.fits[month_start] = self.fit

    def judge(self):
        for i, day in enumerate(self.days):
            if self.fit is None or day['date'].replace(day=1) != self.fit['month']:
                self.retrain(i)
            effects = self.fit['effects'] if self.fit['mode'] == 'model' else self.step_effects
            day['expected'] = self.expected(i, effects)
            day['mode'] = self.fit['mode']
            typical = self.fit['typical_miss']
            if day['expected'] is not None and typical:
                day['flagged'] = abs(day['usage'] - day['expected']) > FLAG_MULTIPLE * typical

    def run(self):
        self.load()
        self.find_steps()
        self.judge()
        return self


def run_model(utility: str) -> ConsumptionModel:
    """Builds the model for one utility ('electricity', 'gas' or 'water')."""
    return ConsumptionModel(utility).run()
