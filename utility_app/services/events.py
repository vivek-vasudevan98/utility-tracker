from datetime import date, timedelta
import pandas as pd
from flask import current_app
from utility_app import db
from utility_app.models import EventDay

def import_event_file(file_storage):
    """
    Loads an events spreadsheet with 'date' and 'load' columns (others are
    ignored). The file covers every day from its first date to its last: listed
    days get their load and unlisted days in between get 0 (no events). Those
    days replace anything stored before; days outside the file are untouched.
    Returns: (category, message) where category is a flash category.
    """
    try:
        df = pd.read_excel(file_storage)
        df.columns = [str(col).strip().lower() for col in df.columns]
        if not {'date', 'load'} <= set(df.columns):
            return 'danger', "Missing required columns. Expected: ['date', 'load']"

        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df['load'] = pd.to_numeric(df['load'], errors='coerce')
        df = df.dropna(subset=['date'])
        if df.empty:
            return 'danger', "No dates could be read from the file. Nothing was imported."

        bad = df[df['load'].isna() | (df['load'] < 0)]
        if not bad.empty:
            listed = ", ".join(d.strftime('%Y-%m-%d') for d in bad['date'][:5])
            return 'danger', f"Load must be a number of 0 or more; check {listed}. Nothing was imported."
        duplicated = df[df['date'].duplicated()]
        if not duplicated.empty:
            listed = ", ".join(sorted({d.strftime('%Y-%m-%d') for d in duplicated['date']})[:5])
            return 'danger', f"Each date may appear only once; repeated: {listed}. Nothing was imported."

        loads = {d.date(): float(v) for d, v in zip(df['date'], df['load'])}
        first, last = min(loads), max(loads)
        days = [first + timedelta(days=i) for i in range((last - first).days + 1)]

        existing = {
            row.date: row for row in EventDay.query.filter(
                EventDay.date >= first.isoformat(), EventDay.date <= last.isoformat()
            )
        }
        for day in days:
            row = existing.get(day.isoformat())
            if not row:
                row = EventDay(date=day.isoformat())
                db.session.add(row)
            row.load = loads.get(day, 0.0)
        db.session.commit()

        event_days = sum(1 for v in loads.values() if v > 0)
        return 'success', (f"Events saved for {first:%d %b %Y} – {last:%d %b %Y}: "
                           f"{event_days} day(s) with events, {len(days) - event_days} without.")

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Events import failed")
        return 'danger', ("Import failed: the file couldn't be read as an Excel sheet with "
                          "date / load columns. Nothing was imported.")

def get_event_loads(start: date, end: date) -> dict:
    """Returns date string -> event load for the known days in start..end (inclusive)."""
    rows = EventDay.query.filter(EventDay.date >= start.isoformat(), EventDay.date <= end.isoformat())
    return {r.date: r.load for r in rows}

def event_coverage() -> list:
    """The stretches of consecutive days with known events, as [(first day, last day), ...]."""
    stretches = []
    for (day_str,) in db.session.query(EventDay.date).order_by(EventDay.date):
        day = date.fromisoformat(day_str)
        if stretches and day - stretches[-1][1] == timedelta(days=1):
            stretches[-1][1] = day
        else:
            stretches.append([day, day])
    return [tuple(s) for s in stretches]
