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