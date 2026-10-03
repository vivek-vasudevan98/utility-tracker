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
    Computes each meter's daily usage, rounded up, dated by the day the energy
    was used. Readings are taken each morning, so the usage on an entry's day
    is the next morning's reading minus this morning's reading.
    Meters are independent: a meter's usage is only known when it was read on
    this day and on the day after. Otherwise (latest reading, a gap in dates,
    or a blank reading on either day) that meter's delta is None.
    """
    processed = []

    for i, current in enumerate(entries):
        following = entries[i + 1] if i + 1 < len(entries) else None
        consecutive = following is not None and is_next_day(current.date, following.date)

        record = {'id': current.id, 'date': current.date}
        for meter, (diff_key, convert) in METERS.items():
            value = getattr(current, meter)
            next_value = getattr(following, meter) if consecutive else None
            record[meter] = int(round(value)) if value is not None else None
            record[diff_key] = (
                math.ceil(convert(next_value - value))
                if value is not None and next_value is not None else None
            )
        processed.append(record)

    return processed


def get_month_records(selected_month):
    """
    Retrieves records for a given month ('YYYY-MM') with each day's usage.
    The first reading after the month is included in the query so the month's
    last day can still get its usage, then dropped from the result.
    """
    month_entries = UtilityEntry.query.filter(
        UtilityEntry.date.startswith(selected_month)
    ).order_by(UtilityEntry.date.asc()).all()
    
    if not month_entries:
        return []

    next_entry = UtilityEntry.query.filter(
        UtilityEntry.date > month_entries[-1].date
    ).order_by(UtilityEntry.date.asc()).first()

    computed = calculate_deltas(month_entries + ([next_entry] if next_entry else []))
    return computed[:len(month_entries)]


def get_daily_usage(start: date, end: date):
    """
    Returns records dated start..end (inclusive) with each meter's daily usage
    (None where unknown). The reading from the day after `end` is included in
    the query so the last day can still get its usage.
    """
    entries = UtilityEntry.query.filter(
        UtilityEntry.date >= start.isoformat(),
        UtilityEntry.date <= (end + timedelta(days=1)).isoformat()
    ).order_by(UtilityEntry.date.asc()).all()

    return [r for r in calculate_deltas(entries) if r['date'] <= end.isoformat()]


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
    A meter's usage for a calendar month, pro-rated across gaps in the readings.
    Readings are taken each morning, so month usage = register on the 1st of
    the next month - register on the 1st of this month.
    For a month still in progress, usage runs to the latest reading.
    Returns {'total', 'covered_days', 'complete'}; total is None when there
    are no readings to measure the month with.
    """
    convert = METERS[meter][1]
    end_boundary = month_end + timedelta(days=1)

    # Needs at least one actual reading from the 1st to the next month's 1st
    latest = _nearest_reading(meter, end_boundary, before=True)
    if latest is None or latest.date < month_start.isoformat():
        return {'total': None, 'covered_days': 0, 'complete': False}

    start_day, start_value = month_start, meter_reading_at(meter, month_start)
    complete = start_value is not None
    if start_value is None:
        # No reading before the month: count from the first reading in it
        first_in_month = _nearest_reading(meter, month_start, before=False)
        if first_in_month is None or first_in_month.date > month_end.isoformat():
            return {'total': None, 'covered_days': 0, 'complete': False}
        start_day, start_value = date.fromisoformat(first_in_month.date), getattr(first_in_month, meter)

    end_day, end_value = end_boundary, meter_reading_at(meter, end_boundary)
    if end_value is None:
        # Month still in progress: run to the latest reading
        end_day, end_value = date.fromisoformat(latest.date), getattr(latest, meter)
        complete = False

    if end_day <= start_day:
        return {'total': None, 'covered_days': 0, 'complete': False}

    return {
        'total': math.ceil(convert(end_value - start_value)),
        'covered_days': (end_day - start_day).days,
        'complete': complete,
    }
