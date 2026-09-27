import math
from typing import List, Tuple, Dict, Any

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

def fit_constrained_rmse_failsafe(x_vals: List[float], y_vals: List[float]) -> Tuple[float, float, float]:
    """
    Failsafe Optimizer:
    Runs when OLS violates physical engineering bounds (e.g., negative slope or negative base load).
    Performs grid search to find beta_0 >= 0 and beta_1 >= 0 that minimizes RMSE.
    """
    min_y = min(y_vals)
    mean_y = sum(y_vals) / len(y_vals)
    max_x = max(x_vals) if max(x_vals) > 0 else 1.0

    # Search bounds
    b0_candidates = [0.0, min_y * 0.25, min_y * 0.5, min_y * 0.75, min_y, mean_y]
    max_slope = (max(y_vals) - min(y_vals)) / max_x if max_x > 0 else 10.0
    b1_candidates = [0.0] + [max_slope * (i / 10.0) for i in range(1, 11)]

    best_b0 = mean_y
    best_b1 = 0.0
    min_error = float('inf')

    for b0 in b0_candidates:
        for b1 in b1_candidates:
            preds = [b0 + (b1 * x) for x in x_vals]
            err = compute_rmse(y_vals, preds)
            if err < min_error:
                min_error = err
                best_b0 = b0
                best_b1 = b1

    # Approximate R^2 for failsafe fit
    var_y = sum((y - mean_y) ** 2 for y in y_vals)
    ss_res = sum((y - (best_b0 + best_b1 * x)) ** 2 for x, y in zip(x_vals, y_vals))
    r2 = max(0.0, 1.0 - (ss_res / var_y)) if var_y > 0 else 0.0

    return best_b0, best_b1, round(r2, 3)

def build_weather_normalized_model(x_vals: List[float], y_vals: List[float], utility_type: str) -> Dict[str, Any]:
    """
    Main Weather Normalization Pipeline with RMSE minimization failsafe.
    x_vals: Degree Days (HDD for Gas, CDD for Electricity)
    y_vals: Actual Daily Consumption (kWh)
    """
    n = len(x_vals)
    if n < 3:
        avg = int(math.ceil(sum(y_vals) / n)) if n > 0 else 0
        return {
            'beta_0': avg, 'beta_1': 0.0, 'r_squared': 0.0,
            'rmse': 0, 'model_type': 'Insufficient Data Fallback',
            'formula_str': f"Y = {avg:,d} kWh (Neutral Baseline)"
        }

    # 1. Attempt standard OLS
    b0, b1, r2 = fit_ols(x_vals, y_vals)
    preds = [b0 + (b1 * x) for x in x_vals]
    rmse = compute_rmse(y_vals, preds)
    model_type = "Ordinary Least Squares (OLS)"

    # 2. Physics & Engineering Boundary Check:
    # Baseload cannot be negative (b0 >= 0), slope must be non-negative (b1 >= 0)
    if b0 < 0 or b1 < 0 or r2 < 0.15:
        # Failsafe Activated: minimize RMSE with physical constraints
        b0, b1, r2 = fit_constrained_rmse_failsafe(x_vals, y_vals)
        preds = [b0 + (b1 * x) for x in x_vals]
        rmse = compute_rmse(y_vals, preds)
        model_type = "Constrained RMSE-Minimization Failsafe"

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