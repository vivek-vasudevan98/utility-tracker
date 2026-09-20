import pandas as pd
from utility_app import db
from utility_app.models import UtilityEntry

def process_excel_upload(file_storage, target_month=None):
    """
    Parses an uploaded Excel file, validates column headers,
    and commits or updates records in the database.
    Returns: (success: bool, message: str)
    """
    try:
        df = pd.read_excel(file_storage)
        df.columns = [str(col).strip().lower() for col in df.columns]
        
        required_cols = ['date', 'electricity', 'gas', 'water']
        if not all(col in df.columns for col in required_cols):
            return False, f"Missing required columns. Expected: {required_cols}"
            
        rows_added = 0
        rows_updated = 0
        
        for _, row in df.iterrows():
            parsed_date = pd.to_datetime(row['date']).strftime('%Y-%m-%d')
            
            if target_month and not parsed_date.startswith(target_month):
                continue
                
            elec = float(row['electricity'])
            gas = float(row['gas'])
            water = float(row['water'])
            
            existing = UtilityEntry.query.filter_by(date=parsed_date).first()
            if existing:
                existing.electricity = elec
                existing.gas = gas
                existing.water = water
                rows_updated += 1
            else:
                entry = UtilityEntry(
                    date=parsed_date,
                    electricity=elec,
                    gas=gas,
                    water=water
                )
                db.session.add(entry)
                rows_added += 1
                
        db.session.commit()
        return True, f"Imported successfully ({rows_added} added, {rows_updated} updated)."
        
    except Exception as e:
        db.session.rollback()
        return False, f"Import failed: {str(e)}"