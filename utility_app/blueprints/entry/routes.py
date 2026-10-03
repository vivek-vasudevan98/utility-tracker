from datetime import date as date_cls, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash
from utility_app import db
from utility_app.services.calculations import METERS
from utility_app.services.excel_handler import process_excel_upload
from utility_app.services.readings import save_reading
from utility_app.services.analytics import sync_completed_month_bill

entry_bp = Blueprint('entry', __name__)

def sync_bills_around(month_str: str):
    """
    A new reading can complete its own month or, by closing a gap at the
    month boundary, the month before it; both get a bill if they lack one.
    """
    month_start = date_cls.fromisoformat(f"{month_str}-01")
    previous_month = (month_start - timedelta(days=1)).strftime('%Y-%m')
    for month in (previous_month, month_str):
        sync_completed_month_bill(month)

@entry_bp.route('/')
def index():
    selected_month = request.args.get('month', '')
    return render_template('entry/index.html', selected_month=selected_month)

@entry_bp.route('/add', methods=['POST'])
def add():
    date = request.form.get('date')
    month_prefix = date[:7] if date else ""

    values = {}
    for meter in METERS:
        raw = (request.form.get(meter) or '').strip()
        try:
            values[meter] = float(raw) if raw else None
        except ValueError:
            flash(f"{meter.capitalize()} reading '{raw}' is not a number.", "danger")
            return redirect(url_for('entry.index', month=month_prefix))

    if not date or all(v is None for v in values.values()):
        flash("Enter a date and at least one meter reading.", "danger")
        return redirect(url_for('entry.index', month=month_prefix))

    status, rejections = save_reading(date, values)
    db.session.commit()

    for reason in rejections:
        flash(f"Rejected {reason}", "danger")
    if status == 'added':
        flash(f"Saved reading for {date}.", "success")
    elif status == 'updated':
        flash(f"Updated existing entry for {date}.", "info")
    elif status == 'unchanged':
        flash(f"Entry for {date} already had these readings.", "info")

    if status in ('added', 'updated'):
        sync_bills_around(month_prefix)

    return redirect(url_for('entry.index', month=month_prefix))

@entry_bp.route('/upload', methods=['POST'])
def upload():
    selected_month = request.form.get('selected_month', '')
    if 'excel_file' not in request.files:
        flash("No file selected.", "danger")
        return redirect(url_for('entry.index', month=selected_month))

    file = request.files['excel_file']
    if file.filename == '':
        flash("No file selected.", "danger")
        return redirect(url_for('entry.index', month=selected_month))

    category, msg = process_excel_upload(file, target_month=selected_month)
    flash(msg, category)
    
    # Fill in bills for months the new readings completed
    if selected_month and category != 'danger':
        sync_bills_around(selected_month)
        
    return redirect(url_for('entry.index', month=selected_month))