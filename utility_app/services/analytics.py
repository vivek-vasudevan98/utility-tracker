import math
import calendar
from datetime import date, timedelta
from utility_app import db
from utility_app.models import MonthlyUtilityBill
from utility_app.services.calculations import get_month_records_with_baseline, get_daily_usage
from utility_app.services.weather_service import get_weather_range
from utility_app.services.regression import (
    build_weather_normalized_model, BASELINE_MONTHS, RECENT_MONTHS,
    MIN_TRAINING_DAYS, WEATHER_LAG_DAYS
)

def get_days_in_month(year: int, month: int) -> int:
    """Returns the total number of calendar days in a given month."""
    return calendar.monthrange(year, month)[1]

def shift_months(month_start: date, months: int) -> date:
    """Returns the first day of the month `months` away from month_start (a 1st)."""
    years, month_index = divmod(month_start.month - 1 + months, 12)
    return date(month_start.year + years, month_index + 1, 1)

def build_weather_baseline(diff_key: str, weather_key: str, utility: str,
                           month_start: date, month_end: date) -> dict:
    """
    Trains the two-layer weather model on readings from before the target month
    (never the month itself) and projects the expected daily series for it.
    Each day's usage is paired with the previous day's weather (WEATHER_LAG_DAYS).
    """
    lag = timedelta(days=WEATHER_LAG_DAYS)
    long_start = shift_months(month_start, -BASELINE_MONTHS)
    recent_start = shift_months(month_start, -RECENT_MONTHS)
    train_end = month_start - timedelta(days=1)

    training_records = get_daily_usage(long_start, train_end)
    result = {
        'model': None,
        'expected': [None] * month_end.day,
        'training_days': len(training_records),
        'min_training_days': MIN_TRAINING_DAYS,
        'training_period': f"{long_start:%b %Y} – {train_end:%b %Y}",
        'recent_period': f"{recent_start:%b %Y} – {train_end:%b %Y}",
    }

    # Not enough readings to reach the minimum: skip the weather fetch entirely
    if len(training_records) < MIN_TRAINING_DAYS:
        return result

    # One cached weather lookup covering training days and the target month
    weather = get_weather_range(long_start - lag, month_end - lag)

    long_x, long_y, recent_x, recent_y = [], [], [], []
    for r in training_records:
        reading_day = date.fromisoformat(r['date'])
        w = weather.get((reading_day - lag).isoformat())
        if w is None:
            continue
        long_x.append(w[weather_key])
        long_y.append(r[diff_key])
        if reading_day >= recent_start:
            recent_x.append(w[weather_key])
            recent_y.append(r[diff_key])

    result['training_days'] = len(long_x)
    model = build_weather_normalized_model(long_x, long_y, recent_x, recent_y, utility)
    if model is None:
        return result

    result['model'] = model
    for i in range(month_end.day):
        w = weather.get((month_start + timedelta(days=i) - lag).isoformat())
        if w is not None:
            result['expected'][i] = math.ceil(model['beta_0'] + model['beta_1'] * w[weather_key])
    return result

def sync_completed_month_bill(month_str: str):
    """
    Event-driven rollup:
    Checks if every calendar day of `month_str` (YYYY-MM) has a known usage figure,
    i.e. a reading preceded by one from the day before (including the last day of
    the prior month for day 1). If so, aggregates the monthly sum and
    commits/updates `monthly_utility_bill`; otherwise the bill is left untouched.
    """
    year, month = map(int, month_str.split('-'))
    total_days = get_days_in_month(year, month)

    records = get_month_records_with_baseline(month_str)
    days_with_usage = sum(1 for r in records if r['diff_elec'] is not None)

    if days_with_usage >= total_days:
        # Month is 100% complete: calculate actual aggregate consumption
        total_elec = sum(r['diff_elec'] for r in records if r['diff_elec'] is not None)
        total_gas = sum(r['diff_gas'] for r in records if r['diff_gas'] is not None)
        total_water = sum(r['diff_water'] for r in records if r['diff_water'] is not None)
        
        start_date = f"{month_str}-01"
        end_date = f"{month_str}-{str(total_days).zfill(2)}"
        
        bill = MonthlyUtilityBill.query.filter_by(month=month_str).first()
        if not bill:
            bill = MonthlyUtilityBill(
                month=month_str,
                start_date=start_date,
                end_date=end_date,
                electricity_kwh=total_elec,
                gas_kwh=total_gas,
                water_m3=total_water
            )
            db.session.add(bill)
        else:
            bill.start_date = start_date
            bill.end_date = end_date
            bill.electricity_kwh = total_elec
            bill.gas_kwh = total_gas
            bill.water_m3 = total_water
            
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
    
    # 1. Pull current month's daily records for MTD
    records = get_month_records_with_baseline(target_month)
    # Only days with a known usage figure count (a reading after a gap has none)
    days_logged = sum(1 for r in records if r['diff_elec'] is not None)

    mtd_elec = sum(r['diff_elec'] for r in records if r['diff_elec'] is not None)
    mtd_gas = sum(r['diff_gas'] for r in records if r['diff_gas'] is not None)
    mtd_water = sum(r['diff_water'] for r in records if r['diff_water'] is not None)
    
    # 2. Linear projection for the rest of the month
    if days_logged > 0:
        scale = total_days / days_logged
        pred_elec = math.ceil(mtd_elec * scale)
        pred_gas = math.ceil(mtd_gas * scale)
        pred_water = math.ceil(mtd_water * scale)
    else:
        pred_elec, pred_gas, pred_water = 0, 0, 0
        
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
        'is_complete': days_logged >= total_days,
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
      - Weather-Normalized Regression Expected (HDD16 for Gas, CDD20 for Elec)
    """
    attr_map = {
        'electricity': ('diff_elec', 'electricity_kwh', 'kWh', '#eab308', 'cdd_20'),
        'gas': ('diff_gas', 'gas_kwh', 'kWh', '#f97316', 'hdd_16'),
        'water': ('diff_water', 'water_m3', 'm³', '#0284c7', None)
    }
    
    if utility not in attr_map:
        utility = 'electricity'
        
    diff_key, bill_col, unit, color, weather_key = attr_map[utility]
    year, month = map(int, target_month.split('-'))
    total_days = get_days_in_month(year, month)
    
    # 1. Target Month Daily Series
    cur_records = get_month_records_with_baseline(target_month)
    cur_map = {int(r['date'].split('-')[2]): r[diff_key] for r in cur_records if r[diff_key] is not None}
    
    # 2. Prior Month Keys
    prev_m_str = f"{year - 1}-12" if month == 1 else f"{year}-{str(month - 1).zfill(2)}"
    prev_m_records = get_month_records_with_baseline(prev_m_str)
    prev_m_map = {int(r['date'].split('-')[2]): r[diff_key] for r in prev_m_records if r[diff_key] is not None}
    
    # 3. Prior Year Keys
    prev_y_str = f"{year - 1}-{str(month).zfill(2)}"
    prev_y_records = get_month_records_with_baseline(prev_y_str)
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

    # 4. Weather-Normalized Baseline (Excluded for Water)
    baseline = None
    if weather_key:
        baseline = build_weather_baseline(
            diff_key, weather_key, utility,
            date(year, month, 1), date(year, month, total_days)
        )
    regression_model = baseline['model'] if baseline else None
    weather_expected_series = baseline['expected'] if baseline else [None] * total_days

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
        'color': color,
        'target_month': target_month,
        'prev_month_label': prev_m_str,
        'prev_year_label': prev_y_str,
        'weather_applicable': weather_key is not None,
        'has_weather_model': regression_model is not None,
        'regression_model': regression_model,
        'weather_baseline': baseline,
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
            'yoy': yoy_series,
            'weather_expected': weather_expected_series
        }
    }