import math
from typing import List, Tuple, Dict, Any, Optional

# --- Weather model configuration ---
# Layer 1 (long-term) window: sets the weather slope; older data is ignored
BASELINE_MONTHS = 12
# Layer 2 (recent) window: recalibrates the base load with the slope held fixed
RECENT_MONTHS = 3
# Layer 1 needs at least this many (degree-day, consumption) days to fit
MIN_TRAINING_DAYS = 90
# Recent days needed before layer 2 fully replaces the long-term base load
RECENT_FULL_WEIGHT_DAYS = 30
# Readings are taken each morning, so a reading on day D mostly reflects day D-1
WEATHER_LAG_DAYS = 1

# Below this R^2, consumption barely tracks degree days; flagged, not refitted
WEAK_FIT_R2 = 0.15

def compute_rmse(actuals: List[float], predictions: List[float]) -> float:
    """Calculates Root Mean Square Error (RMSE)."""
    if not actuals or len(actuals) != len(predictions):
        return 0.0
    mse = sum((a - p) ** 2 for a, p in zip(actuals, predictions)) / len(actuals)
    return math.sqrt(mse)

def fit_ols(x_vals: List[float], y_vals: List[float]) -> Tuple[float, float, float]:
    """
    Closed-form Ordinary Least Squares (OLS):
    Returns: (beta_0 / Intercept, beta_1 / Slope, R_squared)
    """
    n = len(x_vals)
    mean_x = sum(x_vals) / n
    mean_y = sum(y_vals) / n

    cov_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_vals, y_vals))
    var_x = sum((x - mean_x) ** 2 for x in x_vals)
    var_y = sum((y - mean_y) ** 2 for y in y_vals)

    if var_x == 0:
        return mean_y, 0.0, 0.0

    beta_1 = cov_xy / var_x
    beta_0 = mean_y - (beta_1 * mean_x)

    # R^2 calculation
    if var_y == 0:
        r2 = 1.0
    else:
        ss_res = sum((y - (beta_0 + beta_1 * x)) ** 2 for x, y in zip(x_vals, y_vals))
        r2 = max(0.0, 1.0 - (ss_res / var_y))

    return beta_0, beta_1, round(r2, 3)

def fit_constrained_least_squares(x_vals: List[float], y_vals: List[float]) -> Tuple[float, float, float]:
    """
    Exact least-squares fit subject to beta_0 >= 0 and beta_1 >= 0.
    Only called when unconstrained OLS breaks a constraint, in which case the
    optimum lies on the boundary: slope fixed at 0 (flat line at the mean),
    intercept fixed at 0 (line through the origin), or both at 0.
    Returns: (beta_0, beta_1, R_squared)
    """
    mean_y = sum(y_vals) / len(y_vals)
    sum_xx = sum(x * x for x in x_vals)
    sum_xy = sum(x * y for x, y in zip(x_vals, y_vals))

    candidates = [
        (max(0.0, mean_y), 0.0),                                   # beta_1 = 0
        (0.0, max(0.0, sum_xy / sum_xx) if sum_xx > 0 else 0.0),   # beta_0 = 0
        (0.0, 0.0),
    ]

    def sse(b0: float, b1: float) -> float:
        return sum((y - (b0 + b1 * x)) ** 2 for x, y in zip(x_vals, y_vals))

    best_b0, best_b1 = min(candidates, key=lambda c: sse(*c))

    var_y = sum((y - mean_y) ** 2 for y in y_vals)
    ss_res = sum((y - (best_b0 + best_b1 * x)) ** 2 for x, y in zip(x_vals, y_vals))
    r2 = max(0.0, 1.0 - (ss_res / var_y)) if var_y > 0 else 0.0

    return best_b0, best_b1, round(r2, 3)

def build_weather_normalized_model(
    long_x: List[float], long_y: List[float],
    recent_x: List[float], recent_y: List[float],
    utility_type: str
) -> Optional[Dict[str, Any]]:
    """
    Two-layer weather normalization model.
      Layer 1 (long_x/long_y, last BASELINE_MONTHS): fits base load and weather
        slope, with a constrained least-squares fallback.
      Layer 2 (recent_x/recent_y, last RECENT_MONTHS): keeps the slope fixed and
        recalibrates the base load, blended in until RECENT_FULL_WEIGHT_DAYS.
    x values: previous-day Degree Days (HDD for Gas, CDD for Electricity)
    y values: Actual Daily Consumption (kWh)
    Returns None when layer 1 has fewer than MIN_TRAINING_DAYS points.
    """
    if len(long_x) < MIN_TRAINING_DAYS:
        return None

    # Layer 1: standard OLS over the long window
    b0_long, b1, r2 = fit_ols(long_x, long_y)
    model_type = "Ordinary Least Squares (OLS)"

    # Physics & Engineering Boundary Check:
    # Baseload cannot be negative (b0 >= 0), slope must be non-negative (b1 >= 0).
    # A low R^2 is not a constraint violation: OLS is already the best fit.
    if b0_long < 0 or b1 < 0:
        b0_long, b1, r2 = fit_constrained_least_squares(long_x, long_y)
        model_type = "Constrained Least Squares (β₀ ≥ 0, β₁ ≥ 0)"

    if r2 < WEAK_FIT_R2:
        model_type += " — weak weather dependence"

    # Layer 2: recalibrate base load on recent days, slope held fixed
    n_recent = len(recent_x)
    b0 = b0_long
    if n_recent:
        b0_recent = max(0.0, sum(y - b1 * x for x, y in zip(recent_x, recent_y)) / n_recent)
        weight = min(1.0, n_recent / RECENT_FULL_WEIGHT_DAYS)
        b0 = weight * b0_recent + (1 - weight) * b0_long

    # Accuracy of the final model on the most recent data available
    eval_x, eval_y = (recent_x, recent_y) if n_recent else (long_x, long_y)
    rmse = compute_rmse(eval_y, [b0 + b1 * x for x in eval_x])

    dd_var = "HDD₁₆" if utility_type == 'gas' else "CDD₂₀"
    formula_str = f"Ŷ = {int(math.ceil(b0)):,d} + ({round(b1, 2)} × {dd_var} of previous day)"

    return {
        'beta_0': b0,
        'beta_1': b1,
        'r_squared': r2,
        'rmse': int(math.ceil(rmse)),
        'rmse_window': f"last {RECENT_MONTHS} months" if n_recent else f"{BASELINE_MONTHS}-month window",
        'training_days': len(long_x),
        'recent_days': n_recent,
        'base_load_adjustment': int(round(b0 - b0_long)),
        'model_type': model_type,
        'formula_str': formula_str
    }