import math
import calendar
from utility_app import db
from utility_app.models import UtilityEntry, MonthlyUtilityBill
from utility_app.services.calculations import get_month_records_with_baseline

def get_days_in_month(year: int, month: int) -> int:
    """Returns the total number of calendar days in a given month."""
    return calendar.monthrange(year, month)[1]

def sync_completed_month_bill(month_str: str):
    """
    Event-driven rollup:
    Checks if all calendar days of `month_str` (YYYY-MM) are logged in `utility_entry`.
    If complete, aggregates the monthly sum and commits/updates `monthly_utility_bill`.
    """
    year, month = map(int, month_str.split('-'))
    total_days = get_days_in_month(year, month)
    
    # Query distinct dates logged in that month
    entries = UtilityEntry.query.filter(UtilityEntry.date.startswith(month_str)).all()
    unique_dates = {e.date for e in entries}
    
    if len(unique_dates) >= total_days:
        # Month is 100% complete: calculate actual aggregate consumption
        records = get_month_records_with_baseline(month_str)
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
    days_logged = len(records)
    
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
    Maps utility keys to column names and handles baseline logic.
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
    
    # Check for macro statement fallback if daily data is absent
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

    # Compute high-level telemetry stats for current period
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
        'has_mom_daily': bool(prev_m_map),
        'has_yoy_daily': bool(prev_y_map),
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