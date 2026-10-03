"""Calendar and exact contractual accruals; no phase constants."""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, localcontext
import re

from kalmora.money import integer, round_cents


def month_bounds(month: str) -> tuple[date, date]:
    """Inclusive first/last calendar dates."""
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("month must be YYYY-MM")
    first = date.fromisoformat(month + "-01")
    return first, first.replace(day=monthrange(first.year, first.month)[1])


def actual_360(principal_cents: int, rate_bp: int, start: date, end_exclusive: date) -> dict:
    integer(principal_cents, "principal cents")
    integer(rate_bp, "rate basis points")
    if principal_cents < 0 or rate_bp < 0 or end_exclusive < start:
        raise ValueError("invalid interest principal, rate or interval")
    days = (end_exclusive - start).days
    with localcontext() as ctx:
        ctx.prec = 50
        exact = Decimal(principal_cents) * Decimal(rate_bp) / 10000 * days / 360
        return {"principal_cents": principal_cents, "rate_bp": rate_bp,
                "start_inclusive": start.isoformat(), "end_exclusive": end_exclusive.isoformat(),
                "days": days, "basis": "act/360", "unrounded_cents": str(exact),
                "rounded_cents": round_cents(exact)}


def monthly_interest(loan: dict, month: str) -> dict:
    if loan.get("basis") != "act/360":
        raise ValueError("unsupported loan basis; explicit act/360 agreement required")
    first, last = month_bounds(month)
    end = last + timedelta(days=1)
    start = max(first, date.fromisoformat(loan["start"]))
    if loan.get("end_exclusive"):
        end = min(end, date.fromisoformat(loan["end_exclusive"]))
    # A loan outside the period accrues nothing; never a negative day count.
    if start >= end:
        end = start
    return actual_360(loan["principal"], loan["rate_bp"], start, end)
