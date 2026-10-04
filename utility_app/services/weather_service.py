import urllib.request
import json
import time
from datetime import date, timedelta
from utility_app import db
from utility_app.models import DailyWeather

# The building's location (Open-Meteo grid point)
LATITUDE = 54.9385
LONGITUDE = -1.6104

# Degree-day base temperatures (°C), applied to the daily mean temperature
HDD_BASE = 16.0
CDD_BASE = 17.0

# The Open-Meteo archive only holds data up to roughly this many days ago.
# Requesting any later date makes the whole request fail.
ARCHIVE_LAG_DAYS = 5

# Seconds to wait for Open-Meteo before giving up
FETCH_TIMEOUT_SECONDS = 8
# After trying to download a stretch of missing days (successfully or not),
# don't try the same stretch again for this long, so pages load from the
# cache instead of waiting on a download that keeps failing
RETRY_COOLDOWN_SECONDS = 30 * 60
# (first missing day, last missing day) -> time of the last download attempt
_last_attempt = {}

def heating_degree_days(temp_mean: float) -> float:
    """How far the day's mean temperature fell below HDD_BASE (0 on warmer days)."""
    return max(0.0, HDD_BASE - temp_mean)

def cooling_degree_days(temp_mean: float) -> float:
    """How far the day's mean temperature rose above CDD_BASE (0 on cooler days)."""
    return max(0.0, temp_mean - CDD_BASE)

def fetch_and_cache_weather(start_date: str, end_date: str):
    """
    Downloads daily mean temperature, sunshine and solar radiation from the
    Open-Meteo archive and saves them into DailyWeather.
    """
    url = (
        f"https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={LATITUDE}&longitude={LONGITUDE}&"
        f"start_date={start_date}&end_date={end_date}&"
        f"daily=temperature_2m_mean,sunshine_duration,shortwave_radiation_sum&"
        f"timezone=Europe%2FLondon"
    )

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'CommercialUtilityTracker/1.0'})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode('utf-8'))

        daily = payload.get('daily', {})
        if 'time' not in daily:
            return False

        existing = {
            row.date: row for row in DailyWeather.query.filter(
                DailyWeather.date >= start_date,
                DailyWeather.date <= end_date
            )
        }

        for d_str, temp, sunshine_s, solar in zip(
            daily['time'], daily['temperature_2m_mean'],
            daily['sunshine_duration'], daily['shortwave_radiation_sum']
        ):
            # Skip incomplete days; they are downloaded again on a later attempt
            if temp is None or sunshine_s is None or solar is None:
                continue

            row = existing.get(d_str)
            if not row:
                row = DailyWeather(date=d_str)
                db.session.add(row)
            row.temp_mean = float(temp)
            row.sunshine_hours = round(float(sunshine_s) / 3600, 2)
            row.solar_mj = float(solar)

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
    Returns a dictionary of date -> {temp_mean, sunshine_hours, solar_mj} for start..end (inclusive).
    Days missing from the SQLite cache are downloaded from Open-Meteo in one
    request covering just the missing stretch, at most once per RETRY_COOLDOWN_SECONDS.
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

    def load_cached():
        return DailyWeather.query.filter(
            DailyWeather.date >= start_date,
            DailyWeather.date <= end_date
        ).all()

    # Check local SQLite cache first
    cached_rows = load_cached()
    cached_dates = {r.date for r in cached_rows}
    missing = [
        day for day in (start + timedelta(days=i) for i in range((range_end - start).days + 1))
        if day.isoformat() not in cached_dates
    ]

    # Download only the stretch of missing days, at most once per cooldown
    if missing:
        stretch = (missing[0].isoformat(), missing[-1].isoformat())
        last = _last_attempt.get(stretch)
        if last is None or time.monotonic() - last >= RETRY_COOLDOWN_SECONDS:
            _last_attempt[stretch] = time.monotonic()
            if fetch_and_cache_weather(*stretch):
                cached_rows = load_cached()

    return {
        r.date: {
            'temp_mean': r.temp_mean,
            'sunshine_hours': r.sunshine_hours,
            'solar_mj': r.solar_mj
        }
        for r in cached_rows
    }