from datetime import date as date_cls, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy.exc import SQLAlchemyError
from utility_app import db
from utility_app.services.calculations import METERS
from utility_app.services.excel_handler import process_excel_upload
from utility_app.services.events import import_event_file, event_coverage
from utility_app.services.readings import save_reading
from utility_app.services.months import normalize_month
from utility_app.services.analytics import sync_completed_month_bill

entry_bp = Blueprint('entry', __name__)

ALLOWED_UPLOAD_EXTENSIONS = ('.xlsx', '.xls')

def sync_bills_around(month_str: str):
    """
    A new reading can complete its own month or, by closing a gap at the
    month boundary, the month before it; both get a bill if they lack one.
    """
    month_start = date_cls.fromisoformat(f"{month_str}-01")
    previous_month = (month_start - timedelta(days=1)).strftime('%Y-%m')
    for month in (previous_month, month_str):
        try:
            sync_completed_month_bill(month)
        except SQLAlchemyError:
            db.session.rollback()
            flash(f"Readings saved, but the {month} bill couldn't be updated (database busy). "
                  "It will be filled in next time a reading for that month is saved.", "info")

@entry_bp.route('/')
def index():
    raw = request.args.get('month', '')
    selected_month = normalize_month(raw) if raw else ''
    if selected_month is None:
        flash(f"'{raw}' isn't a valid month.", "danger")
        return redirect(url_for('entry.index'))
    return render_template('entry/index.html', selected_month=selected_month,
                           event_coverage=event_coverage())

@entry_bp.route('/add', methods=['POST'])
def add():
    date = (request.form.get('date') or '').strip()
    try:
        date_cls.fromisoformat(date)
    except ValueError:
        flash("Enter a valid reading date.", "danger")
        return redirect(url_for('entry.index'))
    month_prefix = date[:7]

    values = {}
    for meter in METERS:
        raw = (request.form.get(meter) or '').strip()
        try:
            values[meter] = float(raw) if raw else None
        except ValueError:
            flash(f"{meter.capitalize()} reading '{raw}' is not a number.", "danger")
            return redirect(url_for('entry.index', month=month_prefix))

    if all(v is None for v in values.values()):
        flash("Enter at least one meter reading.", "danger")
        return redirect(url_for('entry.index', month=month_prefix))

    try:
        status, rejections = save_reading(date, values)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("Couldn't save the reading: the database is busy (OneDrive syncing or another "
              "save in progress). Nothing was changed; please try again.", "danger")
        return redirect(url_for('entry.index', month=month_prefix))

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

def uploaded_excel_file(field: str):
    """The uploaded file in `field`, or None (with a message flashed) if it's missing or not Excel."""
    file = request.files.get(field)
    if file is None or file.filename == '':
        flash("No file selected.", "danger")
        return None
    if not file.filename.lower().endswith(ALLOWED_UPLOAD_EXTENSIONS):
        flash("Upload an Excel file (.xlsx or .xls).", "danger")
        return None
    return file

@entry_bp.route('/upload', methods=['POST'])
def upload():
    raw = request.form.get('selected_month', '')
    selected_month = normalize_month(raw)
    if selected_month is None:
        flash("Select a valid target month before uploading.", "danger")
        return redirect(url_for('entry.index'))
    file = uploaded_excel_file('excel_file')
    if file is None:
        return redirect(url_for('entry.index', month=selected_month))

    category, msg = process_excel_upload(file, target_month=selected_month)
    flash(msg, category)
    
    # Fill in bills for months the new readings completed
    if category != 'danger':
        sync_bills_around(selected_month)
        
    return redirect(url_for('entry.index', month=selected_month))

@entry_bp.route('/events', methods=['POST'])
def upload_events():
    month = normalize_month(request.form.get('selected_month', '')) or ''
    file = uploaded_excel_file('events_file')
    if file is not None:
        category, msg = import_event_file(file)
        flash(msg, category)
    return redirect(url_for('entry.index', month=month))
