from utility_app import db

class UtilityEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(50), nullable=False)   # Format: "YYYY-MM-DD"
    electricity = db.Column(db.Float, nullable=False) # Raw cumulative register
    gas = db.Column(db.Float, nullable=False)         # Raw cumulative m³
    water = db.Column(db.Float, nullable=False)       # Raw cumulative m³

    def __repr__(self):
        return f"<UtilityEntry {self.date}>"

class MonthlyUtilityBill(db.Model):
    __tablename__ = 'monthly_utility_bill'
    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.String(7), nullable=False, unique=True)  # Format: "YYYY-MM"
    start_date = db.Column(db.String(10), nullable=False)         # "YYYY-MM-DD"
    end_date = db.Column(db.String(10), nullable=False)           # "YYYY-MM-DD"
    electricity_kwh = db.Column(db.Integer, nullable=False)       # Monthly billed total
    gas_kwh = db.Column(db.Integer, nullable=False)               # Monthly thermal total
    water_m3 = db.Column(db.Integer, nullable=False)              # Monthly volume total

    def __repr__(self):
        return f"<MonthlyUtilityBill {self.month}>"