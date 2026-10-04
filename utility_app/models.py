from utility_app import db

class UtilityEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(50), nullable=False, unique=True)   # Format: "YYYY-MM-DD"
    electricity = db.Column(db.Float, nullable=True) # Raw cumulative register
    gas = db.Column(db.Float, nullable=True)         # Raw cumulative m³
    water = db.Column(db.Float, nullable=True)       # Raw cumulative m³

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

class DailyWeather(db.Model):
    """Daily weather downloaded from Open-Meteo (a cache: it can always be re-downloaded)."""
    __tablename__ = 'daily_weather'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), nullable=False, unique=True)  # Format: "YYYY-MM-DD"
    temp_mean = db.Column(db.Float, nullable=False)               # Mean daily air temperature (°C)
    sunshine_hours = db.Column(db.Float, nullable=False)          # Hours of sunshine
    solar_mj = db.Column(db.Float, nullable=False)                # Solar radiation (MJ/m²)

    def __repr__(self):
        return f"<DailyWeather {self.date}: T={self.temp_mean}°C>"

class EventDay(db.Model):
    """
    Event load (0 = no events) for each day covered by an uploaded events file.
    Days with no row are unknown, which is different from a day with no events.
    """
    __tablename__ = 'event_day'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), nullable=False, unique=True)  # Format: "YYYY-MM-DD"
    load = db.Column(db.Float, nullable=False)                    # Combined event load that day

    def __repr__(self):
        return f"<EventDay {self.date}: {self.load}>"

class OccupancyDay(db.Model):
    """Building occupancy (%) for each day it was uploaded; days with no row are unknown."""
    __tablename__ = 'occupancy_day'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), nullable=False, unique=True)  # Format: "YYYY-MM-DD"
    occupancy = db.Column(db.Float, nullable=False)               # 0-100 %

    def __repr__(self):
        return f"<OccupancyDay {self.date}: {self.occupancy}%>"

class ConfirmedRise(db.Model):
    """A sudden rise in usage the user has confirmed as the new normal for a utility."""
    __tablename__ = 'confirmed_rise'
    __table_args__ = (db.UniqueConstraint('utility', 'start_date'),)
    id = db.Column(db.Integer, primary_key=True)
    utility = db.Column(db.String(20), nullable=False)            # 'electricity', 'gas' or 'water'
    start_date = db.Column(db.String(10), nullable=False)         # First day of the rise, "YYYY-MM-DD"

    def __repr__(self):
        return f"<ConfirmedRise {self.utility} from {self.start_date}>"
