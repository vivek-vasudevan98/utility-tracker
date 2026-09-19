from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import math

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///utilities.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class UtilityEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(50), nullable=False)
    electricity = db.Column(db.Float, nullable=False)
    gas = db.Column(db.Float, nullable=False)
    water = db.Column(db.Float, nullable=False)

with app.app_context():
    db.create_all()

@app.route("/")
def home():
    selected_month = request.args.get("month", "")

    query = UtilityEntry.query.order_by(UtilityEntry.date.asc())
    raw_entries = query.all()
    
    entries_with_diffs = []
    for i in range(len(raw_entries)):
        current = raw_entries[i]
        
        if i == 0:
            diff_elec, diff_gas, diff_water = None, None, None
        else:
            previous = raw_entries[i - 1]
            
            raw_elec_diff = current.electricity - previous.electricity
            raw_gas_diff = current.gas - previous.gas
            raw_water_diff = current.water - previous.water
            
            # Apply formulas and round UP to the next integer using math.ceil
            diff_elec = math.ceil(raw_elec_diff * 10)
            diff_gas = math.ceil((raw_gas_diff * 40 * 1.03434) / 3.6)
            diff_water = math.ceil(raw_water_diff)
            
        entries_with_diffs.append({
            'id': current.id,
            'date': current.date,
            # Also round raw inputs to whole integers for clean presentation
            'electricity': int(round(current.electricity)),
            'gas': int(round(current.gas)),
            'water': int(round(current.water)),
            'diff_elec': diff_elec,
            'diff_gas': diff_gas,
            'diff_water': diff_water
        })

    if selected_month:
        filtered_entries = [e for e in entries_with_diffs if e['date'].startswith(selected_month)]
    else:
        filtered_entries = entries_with_diffs

    filtered_entries.reverse()
    
    return render_template("index.html", entries=filtered_entries, selected_month=selected_month)

@app.route("/add", methods=["POST"])
def add_entry():
    date = request.form.get("date")
    electricity = request.form.get("electricity")
    gas = request.form.get("gas")
    water = request.form.get("water")

    if date and electricity and gas and water:
        new_entry = UtilityEntry(
            date=date,
            electricity=float(electricity),
            gas=float(gas),
            water=float(water)
        )
        db.session.add(new_entry)
        db.session.commit()

    month_prefix = date[:7] if date else ""
    return redirect(url_for("home", month=month_prefix))

if __name__ == "__main__":
    app.run(debug=True)