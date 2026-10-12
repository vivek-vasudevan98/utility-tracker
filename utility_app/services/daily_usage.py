"""
Daily usage per utility, kept in the daily_usage table and used by everything
that works with days or month totals (model, charts, dashboard).

Usage comes from two sources: the daily meter readings (worked out here
whenever readings change) and the supplier's daily data (uploaded). When a
day has both, the supplier figure is used: it is measured by the supplier
and always runs midnight to midnight.
"""
import math
from datetime import date, timedelta
from utility_app import db
from utility_app.models import DailyUsage, UtilityEntry
from utility_app.services.calculations import METERS, get_daily_usage, get_month_usage

# Preferred source first
SOURCES = ('supplier', 'meter')


def refresh_meter_usage(start: date, end: date):
    """
    Recomputes the meter-reading usage for days start..end (inclusive) from the
    stored readings and saves it, without committing. A reading on day D
    changes the usage of D-1 and D, so callers pass at least that range.
    """
    computed = {r['date']: r for r in get_daily_usage(start, end)}
    existing = {
        (r.date, r.utility): r for r in DailyUsage.query.filter(
            DailyUsage.source == 'meter',
            DailyUsage.date >= start.isoformat(),
            DailyUsage.date <= end.isoformat(),
        )
    }
    day = start
    while day <= end:
        record = computed.get(day.isoformat(), {})
        for utility, (diff_key, _) in METERS.items():
            value = record.get(diff_key)
            row = existing.get((day.isoformat(), utility))
            if value is None:
                if row is not None:
                    db.session.delete(row)
            elif row is None:
                db.session.add(DailyUsage(date=day.isoformat(), utility=utility, source='meter', amount=float(value)))
            else:
                row.amount = float(value)
        day += timedelta(days=1)


def rebuild_meter_usage():
    """Recomputes the meter-reading usage for every day with readings, without committing."""
    first = db.session.query(db.func.min(UtilityEntry.date)).scalar()
    last = db.session.query(db.func.max(UtilityEntry.date)).scalar()
    if first:
        refresh_meter_usage(date.fromisoformat(first), date.fromisoformat(last))


def first_usage_date(utility: str):
    """The earliest day with usage for `utility`, or None."""
    first = db.session.query(db.func.min(DailyUsage.date)).filter(DailyUsage.utility == utility).scalar()
    return date.fromisoformat(first) if first else None


def get_usage(utility: str, start: date, end: date) -> list:
    """
    One row per day with usage in start..end, oldest first:
    {'date': 'YYYY-MM-DD', 'amount', 'source', 'meter_amount'}. 'source' is the
    one used (supplier preferred); 'meter_amount' is the meter-reading figure
    for the day when there is one, whichever source is used.
    """
    rows = DailyUsage.query.filter(
        DailyUsage.utility == utility,
        DailyUsage.date >= start.isoformat(),
        DailyUsage.date <= end.isoformat(),
    ).all()
    by_day = {}
    for r in rows:
        by_day.setdefault(r.date, {})[r.source] = r.amount
    out = []
    for day in sorted(by_day):
        sources = by_day[day]
        source = next(s for s in SOURCES if s in sources)
        out.append({'date': day, 'amount': sources[source], 'source': source, 'meter_amount': sources.get('meter')})
    return out


def month_usage(utility: str, month_start: date, month_end: date) -> dict:
    """
    A utility's usage for a calendar month: the sum of its daily usage when
    every day is known, otherwise worked out from the meter registers as
    before (pro-rated across gaps). Months with no readings but some daily
    usage (e.g. supplier data only) sum the days that are known.
    Returns {'total', 'covered_days', 'complete'}.
    """
    days = get_usage(utility, month_start, month_end)
    total_days = (month_end - month_start).days + 1
    daily_sum = sum(d['amount'] for d in days)
    if len(days) == total_days:
        return {'total': math.ceil(daily_sum), 'covered_days': total_days, 'complete': True}
    from_registers = get_month_usage(utility, month_start, month_end)
    if from_registers['total'] is not None:
        return from_registers
    if days:
        return {'total': math.ceil(daily_sum), 'covered_days': len(days), 'complete': False}
    return from_registers
