from flask import Blueprint, render_template, request, abort
from datetime import date, datetime, timedelta
from utility_app.services.analytics import get_dashboard_metrics, get_utility_daily_comparison
from utility_app.models import UtilityEntry

dashboard_bp = Blueprint('dashboard', __name__)

def latest_usage_month(latest):
    """
    Month of the latest day with usage. A morning reading closes the previous
    day, so the latest reading's usage day is the day before it.
    """
    if latest is None:
        return datetime.today().strftime('%Y-%m')
    return (date.fromisoformat(latest.date) - timedelta(days=1)).strftime('%Y-%m')

@dashboard_bp.route('/')
def index():
    selected_month = request.args.get('month', '')
    if not selected_month:
        latest = UtilityEntry.query.order_by(UtilityEntry.date.desc()).first()
        selected_month = latest_usage_month(latest)

    dashboard_data = get_dashboard_metrics(selected_month)
    return render_template('dashboard/index.html', data=dashboard_data, selected_month=selected_month)

@dashboard_bp.route('/analytics/<utility>')
def analytics(utility):
    valid_utilities = ['electricity', 'gas', 'water']
    if utility not in valid_utilities:
        abort(404)

    selected_month = request.args.get('month', '')
    if not selected_month:
        latest = UtilityEntry.query.order_by(UtilityEntry.date.desc()).first()
        selected_month = latest_usage_month(latest)

    telemetry = get_utility_daily_comparison(utility, selected_month)
    return render_template('dashboard/analytics.html', data=telemetry, selected_month=selected_month)

