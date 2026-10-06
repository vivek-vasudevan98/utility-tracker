from datetime import date
from flask import current_app
from utility_app import db
from utility_app.models import OccupancyDay
from utility_app.services.events import known_stretches

def import_occupancy_file(file_storage):
    """
    Loads an occupancy workbook: every sheet with 'date' and 'occupancy' columns
    (e.g. one sheet per month). Each day with a value is saved, replacing what
    was stored for it. Blank cells mean "not known" and change nothing.
    Returns: (category, message) where category is a flash category.
    """
    # pandas is only needed for uploads; loading it here keeps the running app ~40 MB smaller
    import pandas as pd
    try:
        frames = []
        for df in pd.read_excel(file_storage, sheet_name=None).values():
            df.columns = [str(col).strip().lower() for col in df.columns]
            if {'date', 'occupancy'} <= set(df.columns):
                frames.append(df[['date', 'occupancy']])
        if not frames:
            return 'danger', "No sheet has 'date' and 'occupancy' columns. Nothing was imported."

        df = pd.concat(frames)
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df = df.dropna(subset=['date'])
        blank = df['occupancy'].isna()
        df['occupancy'] = pd.to_numeric(df['occupancy'], errors='coerce')
        bad = df[~blank & (df['occupancy'].isna() | (df['occupancy'] < 0) | (df['occupancy'] > 100))]
        if not bad.empty:
            listed = ", ".join(d.strftime('%Y-%m-%d') for d in bad['date'][:5])
            return 'danger', f"Occupancy must be a percentage from 0 to 100; check {listed}. Nothing was imported."
        df = df[~blank]
        if df.empty:
            return 'info', "The file had no occupancy values (all blank). Nothing was changed."
        duplicated = df[df['date'].duplicated()]
        if not duplicated.empty:
            listed = ", ".join(sorted({d.strftime('%Y-%m-%d') for d in duplicated['date']})[:5])
            return 'danger', f"Each date may appear only once; repeated: {listed}. Nothing was imported."

        values = {d.date().isoformat(): float(v) for d, v in zip(df['date'], df['occupancy'])}
        existing = {r.date: r for r in OccupancyDay.query.filter(OccupancyDay.date.in_(list(values)))}
        for day, value in values.items():
            row = existing.get(day)
            if not row:
                row = OccupancyDay(date=day)
                db.session.add(row)
            row.occupancy = value
        db.session.commit()

        first, last = min(values), max(values)
        return 'success', f"Occupancy saved for {len(values)} day(s) between {first} and {last}."

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Occupancy import failed")
        return 'danger', ("Import failed: the file couldn't be read as an Excel workbook with "
                          "date / occupancy columns. Nothing was imported.")

def get_occupancy(start: date, end: date) -> dict:
    """Returns date string -> occupancy % for the known days in start..end (inclusive)."""
    rows = OccupancyDay.query.filter(OccupancyDay.date >= start.isoformat(), OccupancyDay.date <= end.isoformat())
    return {r.date: r.occupancy for r in rows}

def occupancy_coverage() -> list:
    """The stretches of consecutive days with known occupancy, as [(first day, last day), ...]."""
    return known_stretches(OccupancyDay.date)
