"""Exact document/local money; source FX rates are currency units per EUR.

Decode source JSON with ``parse_float=Decimal`` before constructing RateTable.
Round each line independently; the settlement line absorbs rounding differences.
"""
from collections.abc import Iterable, Mapping
from typing import Any
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, localcontext
from .model import Cents, CompanyCode, Currency, IsoDate, Milli

type DecimalLike = Decimal | int | str
"""Values ``decimal`` accepts: never ``float`` or ``bool``."""


def integer(value: int, name: str = "cents") -> int:
    """Return ``value`` if it is a real ``int``; TypeError for ``float`` and ``bool``."""
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer (not float or bool)")
    return value


def decimal(value: DecimalLike) -> Decimal:
    """Exact finite Decimal; rejects float, bool, NaN and Infinity."""
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("use Decimal, integer or decimal text")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("decimal must be finite")
    return result


def round_cents(value: DecimalLike, *, truncate: bool = False) -> Cents:
    """Round to whole cents, half up; ``truncate`` rounds toward zero (explicit PPA rule)."""
    return int(decimal(value).quantize(Decimal(1), rounding=ROUND_DOWN if truncate else ROUND_HALF_UP))


def quantity_milli(value: DecimalLike) -> Milli:
    """Quantity in thousandths; ValueError if it has more than three decimals."""
    scaled = decimal(value) * 1000
    if scaled != scaled.to_integral_value():
        raise ValueError("quantity has more than three decimal places")
    return int(scaled)


def line_amount(quantity: Milli, unit_price_cents: DecimalLike, *, share: DecimalLike = Decimal(1),
                truncate: bool = False) -> Cents:
    """quantity (thousandths) x unit price x share, rounded once to cents."""
    with localcontext() as ctx:
        ctx.prec = 50
        return round_cents(Decimal(integer(quantity, "quantity milli")) / 1000 * decimal(unit_price_cents) * decimal(share), truncate=truncate)


def company_local_currency(company: CompanyCode) -> Currency:
    """MXN for company 3100, EUR for the other six; ValueError for an unknown company."""
    if not isinstance(company,str) or company not in {"1000","1100","1200","1300","1910","2100","3100"}:
        raise ValueError("unknown company: local currency requires a supported company")
    return "MXN" if company == "3100" else "EUR"


class RateTable:
    """SYN-BCE rates in currency units per EUR, looked up by date."""

    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self._rates: dict[tuple[Currency, date], Decimal] = {}
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

    def as_of(self, day: IsoDate | date, currency: Currency) -> Decimal:
        """Latest rate on or before ``day`` (1 for EUR); ValueError if none exists."""
        day = date.fromisoformat(day) if isinstance(day, str) else day
        if currency == "EUR":
            return Decimal(1)
        days = [d for c, d in self._rates if c == currency and d <= day]
        if not days:
            raise ValueError(f"no {currency} rate on or before {day}")
        return self._rates[currency, max(days)]

    def convert_cents(self, amount: Cents, source: Currency, target: Currency, day: IsoDate | date,
                      *, truncate: bool = False) -> Cents:
        """Convert via EUR, rounding once; the same currency returns ``amount`` unchanged."""
        integer(amount)
        if source == target:
            return amount
        with localcontext() as ctx:
            ctx.prec = 50
            return round_cents(Decimal(amount) * self.as_of(day, target) / self.as_of(day, source), truncate=truncate)

    def to_local(self, amount_doc: Cents, currency: Currency, company: CompanyCode,
                 day: IsoDate | date) -> Cents:
        """Document cents into the company's local currency."""
        return self.convert_cents(amount_doc, currency, company_local_currency(company), day)
