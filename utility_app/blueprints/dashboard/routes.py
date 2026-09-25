from flask import Blueprint, render_template, request, abort
from datetime import datetime
from utility_app.services.analytics import get_dashboard_metrics, get_utility_daily_comparison
from utility_app.models import UtilityEntry

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
def index():
    selected_month = request.args.get('month', '')
    if not selected_month:
        latest = UtilityEntry.query.order_by(UtilityEntry.date.desc()).first()
        selected_month = latest.date[:7] if latest else datetime.today().strftime('%Y-%m')

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
        selected_month = latest.date[:7] if latest else datetime.today().strftime('%Y-%m')

    telemetry = get_utility_daily_comparison(utility, selected_month)
    return render_template('dashboard/analytics.html', data=telemetry, selected_month=selected_month)

