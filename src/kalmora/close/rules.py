"""Policy §5 primitives; pure functions, exact cents, no files or target access."""
from calendar import monthrange
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from ..model import JournalEntry, JournalLine
from ..money import RateTable, company_local_currency, integer, round_cents


def month_bounds(month: str) -> tuple[date, date]:
    first = date.fromisoformat(month + "-01")
    if first.strftime("%Y-%m") != month:
        raise ValueError("month must be YYYY-MM")
    return first, first.replace(day=monthrange(first.year, first.month)[1])


def month_number(day: date) -> int:
    return day.year * 12 + day.month - 1


def shift_month(day: date, count: int) -> date:
    year, month = divmod(month_number(day) + integer(count), 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def prepaid_remaining(total: int, start: date, end: date, closing: date) -> int:
    """Monthly straight line, rounded once per installment; remainder in the last.

    Coverage dates are observed, not guessed from invoice issue dates. A partial
    boundary month counts as a coverage month, as required by the monthly policy.
    """
    integer(total)
    if end < start or total < 0:
        raise ValueError("invalid prepaid coverage/amount")
    months = month_number(end) - month_number(start) + 1
    used = max(0, min(months, month_number(closing) - month_number(start) + 1))
    if used == months:
        return 0
    return total - round_cents(Decimal(total) / months) * used


def uncovered_ranges(start: date, end: date,
                     coverage: Iterable[tuple[date, date]]) -> list[tuple[date, date]]:
    """Union coverage before subtracting; overlapping invoices never hide extra days."""
    if end < start:
        return []
    cursor = start
    gaps = []
    for left, right in sorted(coverage):
        if right < left:
            raise ValueError("coverage end precedes start")
        if right < cursor or left > end:
            continue
        if left > cursor:
            gaps.append((cursor, min(end, left - timedelta(days=1))))
        cursor = max(cursor, right + timedelta(days=1))
        if cursor > end:
            break
    if cursor <= end:
        gaps.append((cursor, end))
    return gaps


def estimate_daily(samples: Iterable[tuple[int, date, date]], days: int) -> tuple[int, dict]:
    """Median of supplied observed daily rates, not a target-calibrated multiplier.

    The caller selects an explicitly documented, recent, comparable service
    series. Each sample's dates are required and retained in the audit output.
    """
    integer(days)
    if days < 0:
        raise ValueError("days must be nonnegative")
    rates = []
    observations = []
    for amount, start, end in samples:
        integer(amount)
        count = (end - start).days + 1
        if count <= 0 or amount < 0:
            raise ValueError("invalid observed daily-rate sample")
        rates.append(Decimal(amount) / count)
        observations.append({"amount": amount, "start": start.isoformat(),
                             "end": end.isoformat(), "days": count})
    if not rates:
        raise ValueError("an accrual requires observed comparable history")
    rate = median(rates)
    return round_cents(rate * days), {"method": "median_observed_daily_rate",
        "daily_rate": str(rate), "uncovered_days": days, "samples": observations,
        "low": round_cents(min(rates) * days), "high": round_cents(max(rates) * days)}


def fx_difference(document_signed: int, carrying_signed: int, currency: str,
                  company: str, closing: date, rates: RateTable) -> tuple[int, int]:
    """Return (policy amount, signed debit-minus-credit change to the position).

    Policy amount is the increase in the *value* of an asset or liability. A
    liability increase is therefore a credit, not a debit. Document principal
    never changes as a result of a local-currency revaluation.
    """
    integer(document_signed)
    integer(carrying_signed)
    if currency == company_local_currency(company):
        raise ValueError("local-currency positions must not be revalued")
    if document_signed and carrying_signed and (document_signed > 0) != (carrying_signed > 0):
        raise ValueError("document/local position signs contradict")
    if not document_signed:
        if carrying_signed:
            raise ValueError("zero document principal with unexplained local residual")
        return 0, 0
    target = rates.to_local(document_signed, currency, company, closing)
    change = target - carrying_signed
    return change * (1 if document_signed > 0 else -1), change


def impairment_bp(kind: str, due: date | None, closing: date,
                  declared: date | None = None, *, guarantee: bool = False) -> int:
    """Strict >180/>365 boundaries; insolvency includes guarantees, not public/group."""
    if kind not in {"private", "community"}:
        return 0
    if declared is not None and declared <= closing:
        return 10000
    if guarantee:
        return 0
    if due is None:
        raise ValueError("due date is required for ageing")
    overdue = (closing - due).days
    return 10000 if overdue > 365 else 5000 if overdue > 180 else 0


def line(account: str, signed: int, *, company: str, partner: str | None = None,
         assignment: str | None = None, cost_center: str | None = None,
         wbs: str | None = None, currency: str | None = None,
         amount_doc: int | None = None, text: str = "") -> JournalLine:
    integer(signed)
    if cost_center and wbs:
        raise ValueError("cost_center and wbs are mutually exclusive")
    return {"company": company, "account": account, "debit": max(signed, 0),
        "credit": max(-signed, 0), "currency": currency or company_local_currency(company),
        "amount_doc": abs(signed) if amount_doc is None else integer(amount_doc),
        "partner": partner, "assignment": assignment, "cost_center": cost_center,
        "wbs": wbs, "tax_code": None, "text": text}


def entry(company: str, closing: date, reference: str, source: str,
          lines: list[JournalLine]) -> JournalEntry:
    """Only month-end adjustments. Existing day-one reversals are input history."""
    from ..validation import validate_entry
    if closing.day != monthrange(closing.year, closing.month)[1]:
        raise ValueError("close posting date must be the final day of the month")
    result: JournalEntry = {"company": company, "doc_type": "SA",
        "posting_date": closing.isoformat(), "document_date": closing.isoformat(),
        "reference": reference, "source": source, "currency": company_local_currency(company),
        "header_text": reference, "lines": [dict(value, line=i) for i, value in enumerate(lines, 1)]}
    errors = validate_entry(result)
    if errors:
        raise ValueError("; ".join(errors))
    return result
