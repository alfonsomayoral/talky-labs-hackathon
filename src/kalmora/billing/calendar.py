"""Spanish national business days, for invoice dates the history moves off holidays.

Observed in ``ar_invoices``: PPA and market invoices are dated on a fixed day of the
month and rolled to the next business day (Dec 6 and Jan 6 roll; Good Friday rolls).
Only nationwide holidays are listed (BOE labour calendar); regional ones never applied.
"""
from datetime import date, timedelta


def _easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def national_holidays(year: int) -> frozenset[date]:
    fixed = [(1, 1), (1, 6), (5, 1), (8, 15), (10, 12), (11, 1), (12, 6), (12, 8), (12, 25)]
    return frozenset({date(year, m, d) for m, d in fixed} | {_easter(year) - timedelta(days=2)})


def is_business_day(day: date) -> bool:
    return day.weekday() < 5 and day not in national_holidays(day.year)


def roll_forward(day: date) -> date:
    """``day`` itself when it is a business day, else the next one."""
    while not is_business_day(day):
        day += timedelta(days=1)
    return day


def last_day_of_month(year: int, month: int) -> date:
    return (date(year + month // 12, month % 12 + 1, 1) if month < 12 else date(year + 1, 1, 1)) - timedelta(days=1)
