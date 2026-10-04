from flask import Blueprint, render_template, request, abort, flash, redirect, url_for
from datetime import date, datetime, timedelta
from sqlalchemy.exc import SQLAlchemyError
from utility_app import db
from utility_app.services.analytics import get_dashboard_metrics, get_utility_daily_comparison
from utility_app.models import UtilityEntry, ConfirmedRise
from utility_app.services.months import normalize_month

dashboard_bp = Blueprint('dashboard', __name__)

def latest_usage_month(latest):
    """
    Month of the latest day with usage. A morning reading closes the previous
    day, so the latest reading's usage day is the day before it.
    """
    if latest is None:
        return datetime.today().strftime('%Y-%m')
    return (date.fromisoformat(latest.date) - timedelta(days=1)).strftime('%Y-%m')

def requested_month():
    """
    The ?month= value as 'YYYY-MM': the latest usage month when it's missing,
    or None when it was given but isn't a real month.
    """
    raw = request.args.get('month', '')
    if not raw:
        latest = UtilityEntry.query.order_by(UtilityEntry.date.desc()).first()
        return latest_usage_month(latest)
    return normalize_month(raw)

@dashboard_bp.route('/')
def index():
    selected_month = requested_month()
    if selected_month is None:
        flash(f"'{request.args.get('month')}' isn't a valid month; showing the latest month instead.", "danger")
        return redirect(url_for('dashboard.index'))

    dashboard_data = get_dashboard_metrics(selected_month)
    return render_template('dashboard/index.html', data=dashboard_data, selected_month=selected_month)

VALID_UTILITIES = ('electricity', 'gas', 'water')

@dashboard_bp.route('/analytics/<utility>')
def analytics(utility):
    if utility not in VALID_UTILITIES:
        abort(404)

    selected_month = requested_month()
    if selected_month is None:
        flash(f"'{request.args.get('month')}' isn't a valid month; showing the latest month instead.", "danger")
        return redirect(url_for('dashboard.analytics', utility=utility))

    telemetry = get_utility_daily_comparison(utility, selected_month)
    return render_template('dashboard/analytics.html', data=telemetry, selected_month=selected_month)

@dashboard_bp.route('/analytics/<utility>/rise', methods=['POST'])
def rise(utility):
    """Confirms a sudden rise as the new normal (action=confirm), or takes that back (action=undo)."""
    if utility not in VALID_UTILITIES:
        abort(404)
    month = normalize_month(request.form.get('month', '')) or None
    back = redirect(url_for('dashboard.analytics', utility=utility, month=month))
    try:
        start = date.fromisoformat(request.form.get('start_date', '')).isoformat()
    except ValueError:
        flash("That rise couldn't be found; nothing was changed.", "danger")
        return back

    existing = ConfirmedRise.query.filter_by(utility=utility, start_date=start).first()
    try:
        if request.form.get('action') == 'confirm' and not existing:
            db.session.add(ConfirmedRise(utility=utility, start_date=start))
            db.session.commit()
            flash(f"Rise from {start} accepted as the new normal; the baseline now follows it.", "success")
        elif request.form.get('action') == 'undo' and existing:
            db.session.delete(existing)
            db.session.commit()
            flash(f"Rise from {start} is no longer accepted; it is held out of the baseline again.", "info")
    except SQLAlchemyError:
        db.session.rollback()
        flash("Couldn't save that: the database is busy. Nothing was changed; please try again.", "danger")
    return back
