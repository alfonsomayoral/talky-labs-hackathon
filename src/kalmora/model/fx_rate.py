from decimal import Decimal
from typing import Literal, TypedDict

from .scalars import Currency, IsoDate


class FxRate(TypedDict):
    """SYN-BCE exchange rate for one day (``erp/fx_rates.jsonl``).

    Quoted as **currency units per 1 EUR** (the base is always EUR): ``USD 1.0667`` means
    1 EUR buys 1.0667 USD. Conversions go through EUR, so a MXN->USD amount is
    ``amount x rate(USD) / rate(MXN)``.

    Two uses, two dates: a foreign-currency document is converted at the rate of its
    **invoice date** (the latest published one if that day has none), whereas the
    year-end/close revaluation of open monetary items uses the **last day of the month**.
    ``(date, base, currency)`` is the identity; conflicting rates for it are rejected.
    """

    date: IsoDate
    base: Literal["EUR"]
    currency: Currency
    rate: Decimal
    """Strictly positive. Parsed as ``Decimal`` — a float would corrupt cent-level conversion."""

    source: str
    """Origin of the series (``SYN-BCE (sintético)``)."""
