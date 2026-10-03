from typing import Dict, List, Optional, Tuple
from utility_app import db
from utility_app.models import UtilityEntry
from utility_app.services.calculations import METERS

def _neighbour(meter: str, day: str, before: bool) -> Optional[UtilityEntry]:
    """Closest other entry before (or after) `day` with a reading for `meter`."""
    column = getattr(UtilityEntry, meter)
    query = UtilityEntry.query.filter(column.isnot(None))
    if before:
        return query.filter(UtilityEntry.date < day).order_by(UtilityEntry.date.desc()).first()
    return query.filter(UtilityEntry.date > day).order_by(UtilityEntry.date.asc()).first()

def check_reading(meter: str, day: str, value: float) -> Optional[str]:
    """
    Registers only count up, so a reading must lie between the meter's nearest
    readings either side. Returns the reason it's rejected, or None if valid.
    """
    if value < 0:
        return f"{meter} {value:,.0f} is negative"
    prev = _neighbour(meter, day, before=True)
    if prev is not None and value < getattr(prev, meter):
        return f"{meter} {value:,.0f} is lower than {getattr(prev, meter):,.0f} on {prev.date}"
    nxt = _neighbour(meter, day, before=False)
    if nxt is not None and value > getattr(nxt, meter):
        return f"{meter} {value:,.0f} is higher than {getattr(nxt, meter):,.0f} on {nxt.date}"
    return None

def save_reading(day: str, values: Dict[str, Optional[float]]) -> Tuple[str, List[str]]:
    """
    Adds or updates the entry for `day` ('YYYY-MM-DD') without committing.
    `values` maps meter -> reading, or None for a blank. Blank readings never
    erase a stored one, and readings failing check_reading are rejected while
    the day's other readings are still saved.
    Returns (status, rejections): status is 'added', 'updated', 'unchanged'
    or 'skipped' (nothing to save).
    """
    rejections = []
    accepted = {}
    for meter in METERS:
        value = values.get(meter)
        if value is None:
            continue
        reason = check_reading(meter, day, value)
        if reason:
            rejections.append(f"{day}: {reason}")
        else:
            accepted[meter] = value

    if not accepted:
        return 'skipped', rejections

    entry = UtilityEntry.query.filter_by(date=day).first()
    if entry is None:
        db.session.add(UtilityEntry(date=day, **accepted))
        return 'added', rejections

    changed = False
    for meter, value in accepted.items():
        if getattr(entry, meter) != value:
            setattr(entry, meter, value)
            changed = True
    return ('updated' if changed else 'unchanged'), rejections
