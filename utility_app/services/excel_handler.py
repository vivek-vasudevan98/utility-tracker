import pandas as pd
from flask import current_app
from utility_app import db
from utility_app.services.calculations import METERS
from utility_app.services.readings import save_reading

# How many rejected readings to list in the upload message
MAX_LISTED_REJECTIONS = 5

def _cell_value(cell):
    """Blank cells (NaN/NaT/None) become None; anything else must be a number."""
    if pd.isna(cell):
        return None
    return float(cell)

def process_excel_upload(file_storage, target_month=None):
    """
    Parses an uploaded Excel file, validates column headers,
    and adds or updates readings in the database. Blank cells are allowed:
    they're stored as missing and never erase an existing reading. Rows with
    no readings are skipped, and readings that would make a meter go
    backwards are rejected.
    Returns: (category, message) where category is a flash category:
    'success', 'info' (imported with rejected readings) or 'danger' (failed).
    """
    try:
        df = pd.read_excel(file_storage)
        df.columns = [str(col).strip().lower() for col in df.columns]

        required_cols = ['date', *METERS]
        if not all(col in df.columns for col in required_cols):
            return 'danger', f"Missing required columns. Expected: {required_cols}"

        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        bad_dates = int(df['date'].isna().sum())
        # Oldest first, so each reading is checked against the ones before it
        df = df.dropna(subset=['date']).sort_values('date')

        counts = {'added': 0, 'updated': 0, 'unchanged': 0, 'skipped': 0}
        rejections = []

        for _, row in df.iterrows():
            parsed_date = row['date'].strftime('%Y-%m-%d')

            if target_month and not parsed_date.startswith(target_month):
                continue

            values = {}
            for meter in METERS:
                try:
                    values[meter] = _cell_value(row[meter])
                except (ValueError, TypeError):
                    values[meter] = None
                    rejections.append(f"{parsed_date}: {meter} '{row[meter]}' is not a number")

            status, rejected = save_reading(parsed_date, values)
            counts[status] += 1
            rejections.extend(rejected)

        db.session.commit()

        message = (
            f"Imported: {counts['added']} added, {counts['updated']} updated, "
            f"{counts['unchanged']} unchanged, {counts['skipped']} skipped (no valid readings)."
        )
        if bad_dates:
            message += f" {bad_dates} row(s) had an unreadable date."
        if rejections:
            listed = "; ".join(rejections[:MAX_LISTED_REJECTIONS])
            more = len(rejections) - MAX_LISTED_REJECTIONS
            message += f" Rejected {len(rejections)} reading(s): {listed}" + (f"; and {more} more." if more > 0 else ".")
        return ('info' if rejections else 'success'), message

    except Exception:
        db.session.rollback()
        # Full details go to the server log; the page gets a plain explanation
        current_app.logger.exception("Excel import failed")
        return 'danger', ("Import failed: the file couldn't be read as an Excel sheet with "
                          "date / electricity / gas / water columns. Nothing was imported.")
