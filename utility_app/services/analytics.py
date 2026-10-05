import math
import calendar
from datetime import date
from utility_app import db
from utility_app.models import MonthlyUtilityBill, ConfirmedRise
from utility_app.services.calculations import get_month_records, get_month_usage
from utility_app.services.model import (
    run_model, metered_expected, INPUT_LABELS, FLAG_MULTIPLE, HOLDOUT_MONTHS
)

def get_days_in_month(year: int, month: int) -> int:
    """Returns the total number of calendar days in a given month."""
    return calendar.monthrange(year, month)[1]

def sync_completed_month_bill(month_str: str):
    """
    Event-driven rollup:
    Creates the `monthly_utility_bill` row for `month_str` (YYYY-MM) from the
    readings once every meter's usage is known for the whole month, pro-rating
    across gaps. A month that already has a bill is never overwritten, so real
    statement figures are preserved.
    """
    if MonthlyUtilityBill.query.filter_by(month=month_str).first():
        return

    year, month = map(int, month_str.split('-'))
    total_days = get_days_in_month(year, month)
    month_start, month_end = date(year, month, 1), date(year, month, total_days)

    usage = {m: get_month_usage(m, month_start, month_end) for m in ('electricity', 'gas', 'water')}
    if not all(u['complete'] for u in usage.values()):
        return

    db.session.add(MonthlyUtilityBill(
        month=month_str,
        start_date=month_start.isoformat(),
        end_date=month_end.isoformat(),
        electricity_kwh=usage['electricity']['total'],
        gas_kwh=usage['gas']['total'],
        water_m3=usage['water']['total']
    ))
    db.session.commit()

def compute_variance(predicted: int, baseline: int | None) -> dict | None:
    """
    Computes absolute delta and direction.
    Higher consumption is red/unfavorable; Lower consumption is green/favorable.
    """
    if baseline is None:
        return None

    diff = predicted - baseline
    abs_formatted = f"{abs(diff):,d}"
    
    if diff > 0:
        return {
            'diff': diff,
            'direction': 'up',
            'arrow': '▲',
            'color': '#ef4444',      # Red / Unfavorable
            'bg': '#fee2e2',
            'label': f"{abs_formatted}"
        }
    elif diff < 0:
        return {
            'diff': diff,
            'direction': 'down',
            'arrow': '▼',
            'color': '#16a34a',      # Green / Favorable
            'bg': '#dcfce7',
            'label': f"{abs_formatted}"
        }
    else:
        return {
            'diff': 0,
            'direction': 'neutral',
            'arrow': '■',
            'color': '#64748b',
            'bg': '#f1f5f9',
            'label': "0"
        }
    

def get_dashboard_metrics(target_month: str) -> dict:
    """
    Retrieves MTD data for target_month, projects full-month totals,
    and pulls historical benchmarks directly from MonthlyUtilityBill.
    """
    year, month = map(int, target_month.split('-'))
    total_days = get_days_in_month(year, month)
    
    # 1. Month-to-date usage per meter, pro-rated across gaps in the readings
    usage = {
        m: get_month_usage(m, date(year, month, 1), date(year, month, total_days))
        for m in ('electricity', 'gas', 'water')
    }
    mtd = {m: u['total'] or 0 for m, u in usage.items()}

    # 2. Linear projection for the rest of the month from the days covered
    predicted = {}
    for m, u in usage.items():
        if u['complete'] or not u['covered_days']:
            predicted[m] = mtd[m]
        else:
            predicted[m] = math.ceil(mtd[m] * total_days / u['covered_days'])
    days_logged = min(total_days, max(u['covered_days'] for u in usage.values()))
    mtd_elec, mtd_gas, mtd_water = mtd['electricity'], mtd['gas'], mtd['water']
    pred_elec, pred_gas, pred_water = predicted['electricity'], predicted['gas'], predicted['water']
        
    # 3. Benchmark Keys: Prior Month (MoM) & Prior Year Same Month (YoY)
    prev_month_str = f"{year - 1}-12" if month == 1 else f"{year}-{str(month - 1).zfill(2)}"
    prev_year_str = f"{year - 1}-{str(month).zfill(2)}"
    
    # Single-table queries against MonthlyUtilityBill
    prev_month_bill = MonthlyUtilityBill.query.filter_by(month=prev_month_str).first()
    prev_year_bill = MonthlyUtilityBill.query.filter_by(month=prev_year_str).first()
    
    return {
        'month': target_month,
        'days_logged': days_logged,
        'total_days': total_days,
        'is_complete': all(u['complete'] for u in usage.values()),
        'prev_month_label': prev_month_str,
        'prev_year_label': prev_year_str,
        'utilities': {
            'electricity': {
                'mtd': mtd_elec,
                'predicted': pred_elec,
                'mom': compute_variance(pred_elec, prev_month_bill.electricity_kwh if prev_month_bill else None),
                'yoy': compute_variance(pred_elec, prev_year_bill.electricity_kwh if prev_year_bill else None)
            },
            'gas': {
                'mtd': mtd_gas,
                'predicted': pred_gas,
                'mom': compute_variance(pred_gas, prev_month_bill.gas_kwh if prev_month_bill else None),
                'yoy': compute_variance(pred_gas, prev_year_bill.gas_kwh if prev_year_bill else None)
            },
            'water': {
                'mtd': mtd_water,
                'predicted': pred_water,
                'mom': compute_variance(pred_water, prev_month_bill.water_m3 if prev_month_bill else None),
                'yoy': compute_variance(pred_water, prev_year_bill.water_m3 if prev_year_bill else None)
            }
        }
    }

def get_utility_daily_comparison(utility: str, target_month: str) -> dict:
    """
    Builds aligned daily time-series data (Days 1 to 31) for:
      - Current target month
      - Prior month (MoM)
      - Prior year same month (YoY)
      - The consumption model's expected usage and flagged days
    """
    attr_map = {
        'electricity': ('diff_elec', 'electricity_kwh', 'kWh', '#eab308'),
        'gas': ('diff_gas', 'gas_kwh', 'kWh', '#f97316'),
        'water': ('diff_water', 'water_m3', 'm³', '#0284c7')
    }
    
    if utility not in attr_map:
        utility = 'electricity'
        
    diff_key, bill_col, unit, color = attr_map[utility]
    year, month = map(int, target_month.split('-'))
    total_days = get_days_in_month(year, month)
    
    # 1. Target Month Daily Series
    cur_records = get_month_records(target_month)
    cur_map = {int(r['date'].split('-')[2]): r[diff_key] for r in cur_records if r[diff_key] is not None}
    
    # 2. Prior Month Keys
    prev_m_str = f"{year - 1}-12" if month == 1 else f"{year}-{str(month - 1).zfill(2)}"
    prev_m_records = get_month_records(prev_m_str)
    prev_m_map = {int(r['date'].split('-')[2]): r[diff_key] for r in prev_m_records if r[diff_key] is not None}
    
    # 3. Prior Year Keys
    prev_y_str = f"{year - 1}-{str(month).zfill(2)}"
    prev_y_records = get_month_records(prev_y_str)
    prev_y_map = {int(r['date'].split('-')[2]): r[diff_key] for r in prev_y_records if r[diff_key] is not None}
    
    # Check for macro statement fallback
    prev_m_bill = MonthlyUtilityBill.query.filter_by(month=prev_m_str).first()
    prev_y_bill = MonthlyUtilityBill.query.filter_by(month=prev_y_str).first()
    
    prev_m_fallback = None
    if not prev_m_map and prev_m_bill:
        pm_y, pm_m = map(int, prev_m_str.split('-'))
        prev_m_fallback = math.ceil(getattr(prev_m_bill, bill_col) / get_days_in_month(pm_y, pm_m))

    prev_y_fallback = None
    if not prev_y_map and prev_y_bill:
        py_y, py_m = map(int, prev_y_str.split('-'))
        prev_y_fallback = math.ceil(getattr(prev_y_bill, bill_col) / get_days_in_month(py_y, py_m))

    # Assemble aligned 1..total_days series
    labels = []
    current_series = []
    mom_series = []
    yoy_series = []
    
    for day in range(1, total_days + 1):
        labels.append(f"Day {day}")
        current_series.append(cur_map.get(day, None))
        
        # MoM series
        if prev_m_map:
            mom_series.append(prev_m_map.get(day, None))
        else:
            mom_series.append(prev_m_fallback)
            
        # YoY series
        if prev_y_map:
            yoy_series.append(prev_y_map.get(day, None))
        else:
            yoy_series.append(prev_y_fallback)

    valid_cur = [v for v in current_series if v is not None]
    mtd_total = sum(valid_cur)
    daily_avg = math.ceil(mtd_total / len(valid_cur)) if valid_cur else 0
    peak_val = max(valid_cur) if valid_cur else 0
    peak_day = labels[current_series.index(peak_val)] if valid_cur else "—"

    return {
        'utility': utility,
        'unit': unit,
        'model': get_model_view(utility, target_month, unit),
        'color': color,
        'target_month': target_month,
        'prev_month_label': prev_m_str,
        'prev_year_label': prev_y_str,
        'stats': {
            'mtd_total': mtd_total,
            'daily_avg': daily_avg,
            'peak_val': peak_val,
            'peak_day': peak_day,
            'days_logged': len(valid_cur),
            'total_days': total_days
        },
        'chart_data': {
            'labels': labels,
            'current': current_series,
            'mom': mom_series,
            'yoy': yoy_series
        }
    }
def describe_effects(effects: dict, unit: str) -> list:
    """Each effect in words, e.g. '-630 kWh on Sun–Wed'."""
    lines = []
    for name, coef in (effects or {}).items():
        amount = f"{coef:+,.2f}" if abs(coef) < 1 else f"{coef:+,.1f}" if abs(coef) < 10 else f"{coef:+,.0f}"
        lines.append(f"{amount} {unit} {INPUT_LABELS[name]}")
    return lines

def get_model_view(utility: str, target_month: str, unit: str) -> dict:
    """
    The consumption model's verdict for the month: expected usage and flags
    for each day, how the days are being judged, and the step changes found.
    """
    model = run_model(utility)
    year, month = map(int, target_month.split('-'))
    total_days = get_days_in_month(year, month)
    month_start = date(year, month, 1)

    expected = [None] * total_days
    flagged = [False] * total_days
    actual_sum = expected_sum = 0.0
    flagged_days = []
    for d in model.days:
        if d['date'].strftime('%Y-%m') != target_month or d['expected'] is None:
            continue
        # Shown as metered: expected over the hours the day's reads span
        exp = metered_expected(d)
        i = d['date'].day - 1
        expected[i] = math.ceil(exp)
        flagged[i] = d['flagged']
        actual_sum += d['metered']
        expected_sum += exp
        if d['flagged']:
            flagged_days.append({'date': d['date'], 'actual': d['metered'], 'expected': exp})

    fit = model.fits.get(month_start)
    if fit is None:
        status, effects = 'none', None
    elif fit['mode'] == 'model':
        status, effects = 'model', fit['effects']
    elif model.step_effects:
        status, effects = 'learning', model.step_effects
    else:
        status, effects = 'plain', None

    confirmed = ConfirmedRise.query.filter_by(utility=utility).order_by(ConfirmedRise.start_date).all()
    return {
        'status': status,
        'fit': fit,
        'effects': describe_effects(effects, unit),
        'expected': expected,
        'flagged': flagged,
        'flagged_days': flagged_days,
        'has_expected': any(v is not None for v in expected),
        'typical_miss': fit['typical_miss'] if fit else None,
        'flag_band': fit['typical_miss'] * FLAG_MULTIPLE if fit and fit['typical_miss'] else None,
        'month_actual': actual_sum,
        'month_expected': expected_sum,
        'month_change': actual_sum / expected_sum - 1 if expected_sum else None,
        'fixes': model.fixes,
        'rises': model.rises,
        'confirmed_rises': [date.fromisoformat(r.start_date) for r in confirmed],
        'heating_alerts': model.heating_alerts,
        'holdout_months': HOLDOUT_MONTHS,
    }
