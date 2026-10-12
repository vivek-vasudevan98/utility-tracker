"""
Imports the supplier's daily consumption exports into daily_usage (source
'supplier'). Two formats are recognised by their columns:

  - electricity half-hourly: 'Reading Date' plus 48 half-hour kWh columns
    ('00:30' ... '00:00'); a day's usage is the sum of its half-hours
  - gas AMR: 'ConsumptionProfileDate' and 'ProfileDateConsumption' (kWh)

Dates are UK style (day first) and cover midnight to midnight. Re-importing
a file replaces the supplier figures for the days it covers.
"""
import re
from flask import current_app
from utility_app import db
from utility_app.models import DailyUsage
from utility_app.services.events import known_stretches

HALF_HOUR = re.compile(r'^\d{2}:\d{2}$')


def _read(file_storage, filename: str):
    import pandas as pd
    if filename.lower().endswith('.csv'):
        df = pd.read_csv(file_storage, skipinitialspace=True)
    else:
        df = pd.read_excel(file_storage)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _uk_dates(series):
    import pandas as pd
    return pd.to_datetime(series.astype(str).str.strip(), dayfirst=True, errors='coerce')


def _electricity_days(df):
    """date -> kWh from a half-hourly export; days with a missing half-hour are left out."""
    import pandas as pd
    half_hours = [c for c in df.columns if HALF_HOUR.match(c)]
    if len(half_hours) < 46:
        raise ValueError("expected 48 half-hour columns")
    if 'Data Type' in df.columns:
        df = df[df['Data Type'].astype(str).str.strip().str.lower() == 'kwh']
    values = df[half_hours].apply(pd.to_numeric, errors='coerce')
    days, skipped = {}, 0
    for day, row in zip(_uk_dates(df['Reading Date']), values.itertuples(index=False)):
        if pd.isna(day) or any(pd.isna(v) for v in row):
            skipped += 1
            continue
        days[day.date()] = days.get(day.date(), 0.0) + float(sum(row))   # several meters add up
    return days, skipped


def _gas_days(df):
    """date -> kWh from an AMR export; zero days count as missing, a repeated date keeps its largest figure."""
    import pandas as pd
    if 'ReportingUnit' in df.columns:
        units = set(df['ReportingUnit'].dropna().astype(str).str.strip().str.lower())
        if units - {'kwh'}:
            raise ValueError(f"gas figures must be in kWh, not {', '.join(sorted(units))}")
    amounts = pd.to_numeric(df['ProfileDateConsumption'], errors='coerce')
    days, skipped = {}, 0
    for day, amount in zip(_uk_dates(df['ConsumptionProfileDate']), amounts):
        if pd.isna(day) or pd.isna(amount) or amount <= 0:
            skipped += 1
            continue
        days[day.date()] = max(days.get(day.date(), 0.0), float(amount))
    return days, skipped


def import_supplier_file(file_storage, filename: str):
    """
    Saves the supplier's daily figures from an electricity half-hourly or gas
    AMR export. Returns (category, message) where category is a flash category.
    """
    try:
        df = _read(file_storage, filename)
        if 'Reading Date' in df.columns:
            utility, (days, skipped) = 'electricity', _electricity_days(df)
        elif {'ConsumptionProfileDate', 'ProfileDateConsumption'} <= set(df.columns):
            utility, (days, skipped) = 'gas', _gas_days(df)
        else:
            return 'danger', ("This doesn't look like a supplier export: expected an electricity half-hourly "
                              "file ('Reading Date' and half-hour columns) or a gas AMR file "
                              "('ConsumptionProfileDate' and 'ProfileDateConsumption'). Nothing was imported.")
        if not days:
            return 'danger', "No complete days were found in the file. Nothing was imported."

        existing = {
            r.date: r for r in DailyUsage.query.filter(
                DailyUsage.utility == utility, DailyUsage.source == 'supplier',
                DailyUsage.date >= min(days).isoformat(), DailyUsage.date <= max(days).isoformat(),
            )
        }
        for day, amount in days.items():
            row = existing.get(day.isoformat())
            if row is None:
                db.session.add(DailyUsage(date=day.isoformat(), utility=utility, source='supplier', amount=amount))
            else:
                row.amount = amount
        db.session.commit()

        message = (f"{utility.capitalize()} supplier data saved: {len(days)} day(s), "
                   f"{min(days):%d %b %Y} – {max(days):%d %b %Y}.")
        if skipped:
            message += f" {skipped} row(s) were left out (incomplete, zero or unreadable)."
        return 'success', message

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Supplier data import failed")
        return 'danger', "Import failed: the file couldn't be read. Nothing was imported."


def supplier_coverage() -> dict:
    """utility -> stretches of consecutive days with supplier data, as [(first day, last day), ...]."""
    out = {}
    for utility in ('electricity', 'gas'):
        stretches = known_stretches(DailyUsage.date, DailyUsage.utility == utility, DailyUsage.source == 'supplier')
        if stretches:
            out[utility] = stretches
    return out
