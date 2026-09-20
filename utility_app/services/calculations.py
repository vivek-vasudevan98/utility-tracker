import math
from utility_app.models import UtilityEntry

def calculate_deltas(entries):
    """
    Computes consumption deltas between consecutive entries.
    Inputs are raw dial registers:
      - Electricity (kWh): math.ceil((Day_i - Day_{i-1}) * 10)
      - Gas (kWh): math.ceil(((Day_i - Day_{i-1}) * 40 * 1.03434) / 3.6)
      - Water (m³): math.ceil(Day_i - Day_{i-1})
    """
    processed = []
    
    for i in range(len(entries)):
        current = entries[i]
        
        if i == 0:
            diff_elec, diff_gas, diff_water = None, None, None
        else:
            previous = entries[i - 1]
            raw_elec = current.electricity - previous.electricity
            raw_gas = current.gas - previous.gas
            raw_water = current.water - previous.water
            
            diff_elec = math.ceil(raw_elec * 10)
            diff_gas = math.ceil((raw_gas * 40 * 1.03434) / 3.6)
            diff_water = math.ceil(raw_water)
            
        processed.append({
            'id': current.id,
            'date': current.date,
            'electricity': int(round(current.electricity)),
            'gas': int(round(current.gas)),
            'water': int(round(current.water)),
            'diff_elec': diff_elec,
            'diff_gas': diff_gas,
            'diff_water': diff_water
        })
        
    return processed


def get_month_records_with_baseline(selected_month):
    """
    Retrieves records for a given month ('YYYY-MM').
    If entries exist for that month, it queries for the single latest entry 
    strictly preceding the month to act as the true engineering baseline.
    """
    # 1. Fetch entries strictly within the selected month (sorted ascending)
    month_entries = UtilityEntry.query.filter(
        UtilityEntry.date.startswith(selected_month)
    ).order_by(UtilityEntry.date.asc()).all()
    
    if not month_entries:
        return []
        
    first_date_of_month = month_entries[0].date
    
    # 2. Fetch the immediate preceding entry to satisfy the Baseline Rule
    baseline_entry = UtilityEntry.query.filter(
        UtilityEntry.date < first_date_of_month
    ).order_by(UtilityEntry.date.desc()).first()
    
    # Combine: [baseline, day1, day2, ...]
    combined_query = [baseline_entry] + month_entries if baseline_entry else month_entries
    
    # Calculate deltas across the chained entries
    computed = calculate_deltas(combined_query)
    
    # If a baseline entry from the prior month was prepended, exclude it from
    # the display list, but its delta for Day 1 of the current month remains calculated!
    if baseline_entry:
        return computed[1:]
    
    return computed