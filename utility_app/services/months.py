import re
from typing import Optional

MONTH_PATTERN = re.compile(r'(\d{4})-(\d{1,2})')

def normalize_month(value: Optional[str]) -> Optional[str]:
    """
    Returns `value` as a zero-padded 'YYYY-MM' month, or None if it isn't a
    real month. '2026-9' becomes '2026-09' so it matches stored dates.
    """
    match = MONTH_PATTERN.fullmatch((value or '').strip())
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not (1900 <= year <= 2100 and 1 <= month <= 12):
        return None
    return f"{year}-{month:02d}"
