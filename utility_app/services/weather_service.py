import urllib.request
import json
from datetime import date, timedelta
from utility_app import db
from utility_app.models import DailyWeatherCache

# Coordinates for Newcastle upon Tyne, UK
LATITUDE = 54.9783
LONGITUDE = -1.6178

# The Open-Meteo archive only holds data up to roughly this many days ago.
# Requesting any later date makes the whole request fail.
ARCHIVE_LAG_DAYS = 5

def fetch_and_cache_weather(start_date: str, end_date: str):
    """
    Fetches daily temperatures from Open-Meteo Archive/Forecast APIs,
    computes HDD (16°C) and CDD (20°C), and saves them into DailyWeatherCache.
    """
    # Open-Meteo Historical Archive API supports dates up to ~5 days ago;
    # Forecast API covers recent and near-term days.
    url = (
        f"https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={LATITUDE}&longitude={LONGITUDE}&"
        f"start_date={start_date}&end_date={end_date}&"
        f"daily=temperature_2m_mean&timezone=Europe%2FLondon"
    )
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'CommercialUtilityTracker/1.0'})
        with urllib.request.urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode('utf-8'))
            
        if 'daily' not in payload or 'time' not in payload['daily']:
            return False

        dates = payload['daily']['time']
        temps = payload['daily']['temperature_2m_mean']

        for d_str, temp in zip(dates, temps):
            if temp is None:
                continue
            
            # Physics calculations
            hdd = max(0.0, round(16.0 - float(temp), 2))
            cdd = max(0.0, round(float(temp) - 20.0, 2))

            cached = DailyWeatherCache.query.filter_by(date=d_str).first()
            if not cached:
                cached = DailyWeatherCache(
                    date=d_str,
                    temp_mean=float(temp),
                    hdd_16=hdd,
                    cdd_20=cdd
                )
                db.session.add(cached)
            else:
                cached.temp_mean = float(temp)
                cached.hdd_16 = hdd
                cached.cdd_20 = cdd

        db.session.commit()
        return True

    except Exception as e:
        # Undo any half-saved rows, or the session refuses every later query
        # in this request (PendingRollbackError) and the page crashes
        db.session.rollback()
        print(f"Weather API Fetch Error ({start_date} to {end_date}): {e}")
        return False

def get_weather_range(start: date, end: date) -> dict:
    """
    Returns a dictionary of date -> {temp_mean, hdd_16, cdd_20} for start..end (inclusive).
    If dates are missing in SQLite cache, queries Open-Meteo once for the whole range.
    """
    # Cap the range at the latest day the archive can serve, so recent
    # periods still get weather for the days that are available.
    latest_available = date.today() - timedelta(days=ARCHIVE_LAG_DAYS)
    range_end = min(end, latest_available)

    if range_end < start:
        # Whole range is too recent (or in the future) for the archive
        return {}

    start_date = start.isoformat()
    end_date = range_end.isoformat()
    expected_days = (range_end - start).days + 1

    # Check local SQLite cache first
    cached_rows = DailyWeatherCache.query.filter(
        DailyWeatherCache.date >= start_date,
        DailyWeatherCache.date <= end_date
    ).all()

    # If cache is incomplete, fetch and reload
    if len(cached_rows) < expected_days:
        fetch_and_cache_weather(start_date, end_date)
        cached_rows = DailyWeatherCache.query.filter(
            DailyWeatherCache.date >= start_date,
            DailyWeatherCache.date <= end_date
        ).all()

    return {
        r.date: {
            'temp_mean': r.temp_mean,
            'hdd_16': r.hdd_16,
            'cdd_20': r.cdd_20
        }
        for r in cached_rows
    }