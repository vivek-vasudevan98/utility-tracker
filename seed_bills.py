import re
import math
from datetime import datetime
from utility_app import create_app, db
from utility_app.models import MonthlyUtilityBill

# Regex that matches a line starting with two dates: MM/DD/YYYY   MM/DD/YYYY   <consumption>...
# Group 1: Start Date
# Group 2: End Date
# Group 3: Consumption string (e.g. "3,107m3" or "180,930kWh")
ROW_PATTERN = re.compile(
    r'^\s*(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+([\d,.]+)\s*(?:m3|kWh)',
    re.IGNORECASE
)

def run_seed():
    app = create_app()
    with app.app_context():
        # Ensure the table is created
        db.create_all()

        with open('historical_bills.txt', 'r', encoding='utf-8') as f:
            lines = f.readlines()

        data_map = {}  # month_key ('YYYY-MM') -> dict of data
        current_utility = None

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            # Detect which utility section we are currently reading
            lower_line = line.lower()
            if 'water utility bills' in lower_line:
                current_utility = 'water'
                continue
            elif 'electric utility bills' in lower_line:
                current_utility = 'electricity'
                continue
            elif 'gas utility bills' in lower_line:
                current_utility = 'gas'
                continue

            # If we haven't hit a utility section header yet, skip
            if not current_utility:
                continue

            # Attempt regex match against date rows
            match = ROW_PATTERN.match(line)
            if not match:
                # This automatically skips header lines like "Status Start Date..."
                continue

            start_str, end_str, cons_str = match.groups()

            # Parse start date to derive 'YYYY-MM'
            dt_start = datetime.strptime(start_str, '%m/%d/%Y')
            dt_end = datetime.strptime(end_str, '%m/%d/%Y')
            
            month_key = dt_start.strftime('%Y-%m')
            start_date_iso = dt_start.strftime('%Y-%m-%d')
            end_date_iso = dt_end.strftime('%Y-%m-%d')

            # Clean consumption number: strip commas, float convert, math.ceil
            clean_num = float(cons_str.replace(',', ''))
            consumption_val = math.ceil(clean_num)

            # Initialize record dictionary if this month hasn't been seen yet
            if month_key not in data_map:
                data_map[month_key] = {
                    'start_date': start_date_iso,
                    'end_date': end_date_iso,
                    'electricity_kwh': 0,
                    'gas_kwh': 0,
                    'water_m3': 0
                }

            # Map the consumption to the proper column
            if current_utility == 'water':
                data_map[month_key]['water_m3'] = consumption_val
            elif current_utility == 'electricity':
                data_map[month_key]['electricity_kwh'] = consumption_val
            elif current_utility == 'gas':
                data_map[month_key]['gas_kwh'] = consumption_val

        # Upsert into database
        count = 0
        for m, data in data_map.items():
            record = MonthlyUtilityBill.query.filter_by(month=m).first()
            if not record:
                record = MonthlyUtilityBill(
                    month=m,
                    start_date=data['start_date'],
                    end_date=data['end_date'],
                    electricity_kwh=data['electricity_kwh'],
                    gas_kwh=data['gas_kwh'],
                    water_m3=data['water_m3']
                )
                db.session.add(record)
            else:
                record.start_date = data['start_date']
                record.end_date = data['end_date']
                # Only overwrite if non-zero
                if data['electricity_kwh']:
                    record.electricity_kwh = data['electricity_kwh']
                if data['gas_kwh']:
                    record.gas_kwh = data['gas_kwh']
                if data['water_m3']:
                    record.water_m3 = data['water_m3']

            count += 1

        db.session.commit()
        print(f"Successfully processed and seeded {count} months of historical utility statements (2005 - 2026)!")

if __name__ == '__main__':
    run_seed()