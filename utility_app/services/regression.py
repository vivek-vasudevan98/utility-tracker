import math
from typing import List, Tuple, Dict, Any, Optional

# Fewer paired (degree-day, consumption) points than this can't support a fit
MIN_TRAINING_POINTS = 3

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

def build_weather_normalized_model(x_vals: List[float], y_vals: List[float], utility_type: str) -> Optional[Dict[str, Any]]:
    """
    Main Weather Normalization Pipeline with a constrained least-squares fallback.
    x_vals: Degree Days (HDD for Gas, CDD for Electricity)
    y_vals: Actual Daily Consumption (kWh)
    Returns None when there are too few points to fit a model.
    """
    n = len(x_vals)
    if n < MIN_TRAINING_POINTS:
        return None

    # 1. Attempt standard OLS
    b0, b1, r2 = fit_ols(x_vals, y_vals)
    model_type = "Ordinary Least Squares (OLS)"

    # 2. Physics & Engineering Boundary Check:
    # Baseload cannot be negative (b0 >= 0), slope must be non-negative (b1 >= 0).
    # A low R^2 is not a constraint violation: OLS is already the best fit.
    if b0 < 0 or b1 < 0:
        b0, b1, r2 = fit_constrained_least_squares(x_vals, y_vals)
        model_type = "Constrained Least Squares (β₀ ≥ 0, β₁ ≥ 0)"

    if r2 < WEAK_FIT_R2:
        model_type += " — weak weather dependence"

    preds = [b0 + (b1 * x) for x in x_vals]
    rmse = compute_rmse(y_vals, preds)

    b0_int = int(math.ceil(b0))
    b1_round = round(b1, 2)
    dd_var = "HDD₁₆" if utility_type == 'gas' else "CDD₂₀"
    
    formula_str = f"Ŷ = {b0_int:,d} + ({b1_round} × {dd_var})"

    return {
        'beta_0': b0_int,
        'beta_1': b1_round,
        'r_squared': r2,
        'rmse': int(math.ceil(rmse)),
        'model_type': model_type,
        'formula_str': formula_str
    }