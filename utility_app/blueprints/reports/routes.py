from flask import Blueprint, render_template, request
from utility_app.models import MonthlyUtilityBill, UtilityEntry
from utility_app.services.calculations import get_month_records_with_baseline

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/')
def index():
    view_type = request.args.get('view', 'monthly')  # 'monthly' or 'daily'
    selected_month = request.args.get('month', '')
    selected_year = request.args.get('year', '')

    daily_records = []
    has_daily_data = False

    # Check if daily data exists for the selected month
    if selected_month:
        daily_count = UtilityEntry.query.filter(UtilityEntry.date.startswith(selected_month)).count()
        has_daily_data = daily_count > 0
        if has_daily_data:
            daily_records = get_month_records_with_baseline(selected_month)
            daily_records.reverse()
        else:
            # If no daily register exists, force monthly statement view
            view_type = 'monthly'

    # Query Monthly Statements
    query = MonthlyUtilityBill.query.order_by(MonthlyUtilityBill.month.desc())
    if selected_year:
        query = query.filter(MonthlyUtilityBill.month.startswith(selected_year))

    monthly_bills = query.all()

    # Extract list of available years for filter UI dropdown
    available_years = sorted(list(set(b.month[:4] for b in MonthlyUtilityBill.query.all())), reverse=True)

    return render_template(
        'reports/index.html',
        view_type=view_type,
        selected_month=selected_month,
        selected_year=selected_year,
        has_daily_data=has_daily_data,
        daily_entries=daily_records,
        monthly_bills=monthly_bills,
        available_years=available_years
    )