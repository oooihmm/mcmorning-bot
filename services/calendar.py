from functools import lru_cache
import holidays
from database import connect


@lru_cache(maxsize=8)
def korean_holidays(year):
    return holidays.country_holidays('KR', years=year, observed=True)


def is_study_day(day):
    if day.weekday() >= 5:
        return False
    with connect() as db:
        override = db.execute('SELECT is_holiday FROM calendar_overrides WHERE date=?', (day,)).fetchone()
    if override is not None:
        return not override[0]
    return day not in korean_holidays(day.year)


def set_holiday(day, is_holiday, reason):
    with connect() as db:
        if is_holiday is None:
            db.execute('DELETE FROM calendar_overrides WHERE date=?', (day,))
        else:
            db.execute('INSERT INTO calendar_overrides VALUES (?, ?, ?) ON CONFLICT(date) DO UPDATE SET is_holiday=excluded.is_holiday, reason=excluded.reason', (day, int(is_holiday), reason))
