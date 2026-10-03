"""Exact document/local money; source FX rates are currency units per EUR.

Decode source JSON with ``parse_float=Decimal`` before constructing RateTable.
Round each line independently; the settlement line absorbs rounding differences.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, localcontext


def integer(value, name="cents"):
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer (not float or bool)")
    return value


def decimal(value):
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("use Decimal, integer or decimal text")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("decimal must be finite")
    return result


def round_cents(value, *, truncate=False):
    return int(decimal(value).quantize(Decimal(1), rounding=ROUND_DOWN if truncate else ROUND_HALF_UP))


def quantity_milli(value):
    scaled = decimal(value) * 1000
    if scaled != scaled.to_integral_value():
        raise ValueError("quantity has more than three decimal places")
    return int(scaled)


def line_amount(quantity, unit_price_cents, *, share=Decimal(1), truncate=False):
    with localcontext() as ctx:
        ctx.prec = 50
        return round_cents(Decimal(integer(quantity, "quantity milli")) / 1000 * decimal(unit_price_cents) * decimal(share), truncate=truncate)


def company_local_currency(company):
    return "MXN" if company == "3100" else "EUR"


class RateTable:
    def __init__(self, rows):
        self._rates = {}
        for row in rows:
            if row.get("base", "EUR") != "EUR":
                raise ValueError("source rates must have EUR base")
            day = date.fromisoformat(row["date"])
            rate = decimal(row["rate"])
            if rate <= 0:
                raise ValueError("rate must be positive")
            key = (row["currency"], day)
            if key in self._rates and self._rates[key] != rate:
                raise ValueError("conflicting rate for currency/date")
            self._rates[key] = rate

    def as_of(self, day, currency):
        day = date.fromisoformat(day) if isinstance(day, str) else day
        if currency == "EUR":
            return Decimal(1)
        days = [d for c, d in self._rates if c == currency and d <= day]
        if not days:
            raise ValueError(f"no {currency} rate on or before {day}")
        return self._rates[currency, max(days)]

    def convert_cents(self, amount, source, target, day, *, truncate=False):
        integer(amount)
        if source == target:
            return amount
        with localcontext() as ctx:
            ctx.prec = 50
            return round_cents(Decimal(amount) * self.as_of(day, target) / self.as_of(day, source), truncate=truncate)

    def to_local(self, amount_doc, currency, company, day):
        return self.convert_cents(amount_doc, currency, company_local_currency(company), day)
