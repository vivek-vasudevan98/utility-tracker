from flask import Blueprint, render_template
from datetime import datetime
from utility_app.services.calculations import get_month_records_with_baseline

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
def index():
    # Default to the current month in "YYYY-MM" format
    current_month = datetime.today().strftime('%Y-%m')
    records = get_month_records_with_baseline(current_month)

    # Compute aggregate consumption for available delta entries
    total_elec = sum(r['diff_elec'] for r in records if r['diff_elec'] is not None)
    total_gas = sum(r['diff_gas'] for r in records if r['diff_gas'] is not None)
    total_water = sum(r['diff_water'] for r in records if r['diff_water'] is not None)

    summary = {
        'month': current_month,
        'entry_count': len(records),
        'total_elec': total_elec,
        'total_gas': total_gas,
        'total_water': total_water
    }

    return render_template('dashboard/index.html', summary=summary)