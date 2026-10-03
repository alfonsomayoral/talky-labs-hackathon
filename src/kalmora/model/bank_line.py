from typing import TypedDict

from .scalars import Cents, Currency, IsoDate


class BankLine(TypedDict):
    """One line of a bank statement (``bank/<account>/<YYYY-MM>.lines.jsonl``).

    A fact reported by the bank, **not** a journal entry: it implies no posting. Bank
    reconciliation matches each line to a posting in the company's 572 account (1:1,
    N:1 for a remittance paying several invoices, or 1:N) and classifies whatever is
    left unmatched by cause — an unbooked fee, interest, a returned direct debit, an
    outstanding payment — deciding whether each needs an adjustment (policy §4).
    """

    bank_line: str
    """Statement-line identifier (``BL0002743``). The natural ``event_id`` of the adjustment a
    line triggers, which keeps re-runs idempotent."""

    booking_date: IsoDate
    value_date: IsoDate
    """Date the bank values the movement; may differ from the booking date."""

    amount: Cents
    """Signed, in cents of the account's currency, from the company's point of view on the
    bank: positive = money in (credit to the account), negative = money out (charge)."""

    currency: Currency
    text: str
    """Bank narrative. Carries the matching hints: remittance number, invoice reference,
    settlement id (``CONFIRMING VTO 010426 REMESA CF110026021058``, ``LIQUIDACION FACTORING``)."""
