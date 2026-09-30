import math
from itertools import product
from typing import List, Tuple, Dict, Any, Optional

# --- Weather model configuration ---
# Training window: sets the weather slope; older data is ignored
BASELINE_MONTHS = 12
# Recent window: gets its own base load level, fitted jointly with the slope
RECENT_MONTHS = 3
# The training window needs at least this many (degree-day, consumption) days
MIN_TRAINING_DAYS = 90
# Recent days needed before the recent base load is used in full
RECENT_FULL_WEIGHT_DAYS = 30
# Readings are taken each morning, so a reading on day D mostly reflects day D-1
WEATHER_LAG_DAYS = 1

# Below this weather R^2, consumption barely tracks degree days; flagged, not refitted
WEAK_FIT_R2 = 0.15

def compute_rmse(actuals: List[float], predictions: List[float]) -> float:
    """Calculates Root Mean Square Error (RMSE)."""
    if not actuals or len(actuals) != len(predictions):
        return 0.0
    mse = sum((a - p) ** 2 for a, p in zip(actuals, predictions)) / len(actuals)
    return math.sqrt(mse)

def fit_period_baseline(
    x_vals: List[float], y_vals: List[float], is_recent: List[bool]
) -> Tuple[Dict[bool, float], float, bool]:
    """
    Least-squares fit of  y = base[period] + slope * x  with one shared slope and a
    separate base load for the recent period and the earlier period, subject to
    every base >= 0 and slope >= 0.

    The problem is convex, so its optimum is the best feasible solution among the
    candidates where each constraint is either free or held at 0:
      - a free base is the period's mean of (y - slope * x),
      - the slope is fitted from within-period variation (sums centred on the
        period mean for a free base, raw sums for a base held at 0).
    Returns: ({is_recent: base}, slope, constrained) for the periods present.
    """
    periods = {}
    for x, y, recent in zip(x_vals, y_vals, is_recent):
        periods.setdefault(recent, ([], []))
        periods[recent][0].append(x)
        periods[recent][1].append(y)

    def solve(free_bases: Dict[bool, bool], free_slope: bool):
        slope = 0.0
        if free_slope:
            num = den = 0.0
            for p, (xs, ys) in periods.items():
                mx = sum(xs) / len(xs) if free_bases[p] else 0.0
                my = sum(ys) / len(ys) if free_bases[p] else 0.0
                num += sum((x - mx) * (y - my) for x, y in zip(xs, ys))
                den += sum((x - mx) ** 2 for x in xs)
            slope = num / den if den > 0 else 0.0
        bases = {
            p: (sum(y - slope * x for x, y in zip(xs, ys)) / len(xs) if free_bases[p] else 0.0)
            for p, (xs, ys) in periods.items()
        }
        return bases, slope

    def sse(bases: Dict[bool, float], slope: float) -> float:
        return sum(
            (y - bases[p] - slope * x) ** 2
            for p, (xs, ys) in periods.items() for x, y in zip(xs, ys)
        )

    keys = list(periods)
    unconstrained = solve({p: True for p in keys}, True)
    best, best_err = None, float('inf')
    for free_slope in (True, False):
        for flags in product((True, False), repeat=len(keys)):
            bases, slope = solve(dict(zip(keys, flags)), free_slope)
            if slope < 0 or any(b < 0 for b in bases.values()):
                continue
            err = sse(bases, slope)
            if err < best_err - 1e-9:
                best, best_err = (bases, slope), err

    bases, slope = best
    constrained = (bases, slope) != unconstrained
    return bases, slope, constrained

def weather_r_squared(x_vals: List[float], y_vals: List[float], is_recent: List[bool],
                      bases: Dict[bool, float], slope: float) -> float:
    """
    Share of the variation around each period's own average that the weather
    term explains, so a base-load shift between periods doesn't inflate it.
    """
    sums = {}
    for y, recent in zip(y_vals, is_recent):
        total, count = sums.get(recent, (0.0, 0))
        sums[recent] = (total + y, count + 1)
    means = {p: total / count for p, (total, count) in sums.items()}

    ss_within = sum((y - means[p]) ** 2 for y, p in zip(y_vals, is_recent))
    ss_res = sum((y - bases[p] - slope * x) ** 2 for x, y, p in zip(x_vals, y_vals, is_recent))
    if ss_within == 0:
        return 1.0 if ss_res == 0 else 0.0
    return round(max(0.0, 1.0 - ss_res / ss_within), 3)

def build_weather_normalized_model(
    x_vals: List[float], y_vals: List[float], is_recent: List[bool], utility_type: str
) -> Optional[Dict[str, Any]]:
    """
    Two-layer weather normalization model, fitted in one step over the last
    BASELINE_MONTHS: one weather slope shared by the whole window, plus separate
    base loads for the last RECENT_MONTHS and the months before them. The recent
    base load is used for predictions, blended in until RECENT_FULL_WEIGHT_DAYS.
    x values: previous-day Degree Days (HDD for Gas, CDD for Electricity)
    y values: Actual Daily Consumption (kWh)
    is_recent: whether each day falls in the recent window
    Returns None when there are fewer than MIN_TRAINING_DAYS points.
    """
    if len(x_vals) < MIN_TRAINING_DAYS:
        return None

    bases, slope, constrained = fit_period_baseline(x_vals, y_vals, is_recent)
    r2 = weather_r_squared(x_vals, y_vals, is_recent, bases, slope)

    model_type = (
        "Constrained Least Squares (bases ≥ 0, slope ≥ 0)" if constrained
        else "Ordinary Least Squares (OLS)"
    )
    if r2 < WEAK_FIT_R2:
        model_type += " — weak weather dependence"

    # Base load for predictions: recent level, blended in by recent sample size
    n_recent = sum(is_recent)
    earlier_base = bases.get(False, bases.get(True))
    recent_base = bases.get(True, earlier_base)
    weight = min(1.0, n_recent / RECENT_FULL_WEIGHT_DAYS)
    b0 = weight * recent_base + (1 - weight) * earlier_base

    # Accuracy of the final model on the most recent data available
    if n_recent:
        eval_pairs = [(x, y) for x, y, r in zip(x_vals, y_vals, is_recent) if r]
    else:
        eval_pairs = list(zip(x_vals, y_vals))
    rmse = compute_rmse([y for _, y in eval_pairs], [b0 + slope * x for x, _ in eval_pairs])

    dd_var = "HDD₁₆" if utility_type == 'gas' else "CDD₂₀"
    formula_str = f"Ŷ = {int(math.ceil(b0)):,d} + ({round(slope, 2)} × {dd_var} of previous day)"

    return {
        'beta_0': b0,
        'beta_1': slope,
        'r_squared': r2,
        'rmse': int(math.ceil(rmse)),
        'rmse_window': f"last {RECENT_MONTHS} months" if n_recent else f"{BASELINE_MONTHS}-month window",
        'training_days': len(x_vals),
        'recent_days': n_recent,
        'base_load_adjustment': int(round(b0 - earlier_base)),
        'model_type': model_type,
        'formula_str': formula_str
    }
