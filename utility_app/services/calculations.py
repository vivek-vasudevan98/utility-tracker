import math
from datetime import date, timedelta
from typing import Optional
from utility_app.models import UtilityEntry

# Meter column -> (usage key, conversion from raw register delta to billed units)
#   - Electricity (kWh): register delta * 10
#   - Gas (kWh): register delta (m³) * 40 * 1.03434 / 3.6
#   - Water (m³): register delta
METERS = {
    'electricity': ('diff_elec', lambda d: d * 10),
    'gas': ('diff_gas', lambda d: d * 40 * 1.03434 / 3.6),
    'water': ('diff_water', lambda d: d),
}

def is_next_day(previous_date: str, current_date: str) -> bool:
    """True when current_date ('YYYY-MM-DD') is exactly one day after previous_date."""
    return (date.fromisoformat(current_date) - date.fromisoformat(previous_date)).days == 1

def calculate_deltas(entries):
    """
    Computes each meter's daily usage between consecutive entries, rounded up.
    Meters are independent: a meter's usage is only known when it was read on
    this day and on the day before. Otherwise (first reading, a gap in dates,
    or a blank reading on either day) that meter's delta is None.
    """
    processed = []

    for i, current in enumerate(entries):
        previous = entries[i - 1] if i > 0 else None
        consecutive = previous is not None and is_next_day(previous.date, current.date)

        record = {'id': current.id, 'date': current.date}
        for meter, (diff_key, convert) in METERS.items():
            value = getattr(current, meter)
            prev_value = getattr(previous, meter) if consecutive else None
            record[meter] = int(round(value)) if value is not None else None
            record[diff_key] = (
                math.ceil(convert(value - prev_value))
                if value is not None and prev_value is not None else None
            )
        processed.append(record)

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


def get_daily_usage(start: date, end: date):
    """
    Returns records dated start..end (inclusive) with each meter's daily usage
    (None where unknown). The reading from the day before `start` is included
    in the query so the first day can still get a delta.
    """
    entries = UtilityEntry.query.filter(
        UtilityEntry.date >= (start - timedelta(days=1)).isoformat(),
        UtilityEntry.date <= end.isoformat()
    ).order_by(UtilityEntry.date.asc()).all()

    return [r for r in calculate_deltas(entries) if r['date'] >= start.isoformat()]


def _nearest_reading(meter: str, day: date, before: bool) -> Optional[UtilityEntry]:
    """Closest entry on/before (or on/after) `day` that has a reading for `meter`."""
    column = getattr(UtilityEntry, meter)
    query = UtilityEntry.query.filter(column.isnot(None))
    if before:
        return query.filter(UtilityEntry.date <= day.isoformat()).order_by(UtilityEntry.date.desc()).first()
    return query.filter(UtilityEntry.date >= day.isoformat()).order_by(UtilityEntry.date.asc()).first()


def meter_reading_at(meter: str, day: date) -> Optional[float]:
    """
    The meter's register on `day`: the actual reading if there is one, otherwise
    pro-rated linearly between the nearest readings either side. None when there
    is no reading on one of the sides.
    """
    before = _nearest_reading(meter, day, before=True)
    after = _nearest_reading(meter, day, before=False)
    if before is None or after is None:
        return None
    v0, v1 = getattr(before, meter), getattr(after, meter)
    d0, d1 = date.fromisoformat(before.date), date.fromisoformat(after.date)
    if d0 == d1:
        return v0
    return v0 + (v1 - v0) * (day - d0).days / (d1 - d0).days


def get_month_usage(meter: str, month_start: date, month_end: date) -> dict:
    """
    A meter's usage for a month, pro-rated across gaps in the readings.
    Month usage = register at the month's last day - register at the previous
    month's last day (a reading dated D covers usage up to that morning).
    For a month still in progress, usage runs to the latest reading in it.
    Returns {'total', 'covered_days', 'complete'}; total is None when the
    meter has no reading in the month.
    """
    convert = METERS[meter][1]
    start_day = month_start - timedelta(days=1)

    last_in_month = _nearest_reading(meter, month_end, before=True)
    if last_in_month is None or last_in_month.date < month_start.isoformat():
        return {'total': None, 'covered_days': 0, 'complete': False}

    start_value = meter_reading_at(meter, start_day)
    complete = start_value is not None
    if start_value is None:
        # No reading before the month: count from the first reading in it
        first_in_month = _nearest_reading(meter, month_start, before=False)
        start_day, start_value = date.fromisoformat(first_in_month.date), getattr(first_in_month, meter)

    end_value = meter_reading_at(meter, month_end)
    end_day = month_end
    if end_value is None:
        # Month still in progress: run to the latest reading
        end_day, end_value = date.fromisoformat(last_in_month.date), getattr(last_in_month, meter)
        complete = False

    return {
        'total': math.ceil(convert(end_value - start_value)),
        'covered_days': (end_day - start_day).days,
        'complete': complete,
    }
