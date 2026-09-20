from flask import Blueprint, render_template, request, redirect, url_for, flash
from utility_app import db
from utility_app.models import UtilityEntry
from utility_app.services.excel_handler import process_excel_upload

entry_bp = Blueprint('entry', __name__)

@entry_bp.route('/')
def index():
    selected_month = request.args.get('month', '')
    return render_template('entry/index.html', selected_month=selected_month)

@entry_bp.route('/add', methods=['POST'])
def add():
    date = request.form.get('date')
    electricity = request.form.get('electricity')
    gas = request.form.get('gas')
    water = request.form.get('water')

    if date and electricity and gas and water:
        existing = UtilityEntry.query.filter_by(date=date).first()
        if existing:
            existing.electricity = float(electricity)
            existing.gas = float(gas)
            existing.water = float(water)
            flash(f"Updated existing entry for {date}.", "info")
        else:
            new_entry = UtilityEntry(
                date=date,
                electricity=float(electricity),
                gas=float(gas),
                water=float(water)
            )
            db.session.add(new_entry)
            flash(f"Saved reading for {date}.", "success")
        db.session.commit()

    month_prefix = date[:7] if date else ""
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

    success, msg = process_excel_upload(file, target_month=selected_month)
    flash(msg, "success" if success else "danger")
    return redirect(url_for('entry.index', month=selected_month))