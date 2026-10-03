from typing import NotRequired, Required, TypedDict

from .journal_line import JournalLine
from .provenance import Provenance
from .scalars import CompanyCode, Currency, IsoDate


class JournalEntry(TypedDict, total=False):
    """Journal entry (*asiento*): an atomic, balanced record of one transaction of one company.

    **Invariants.** All lines belong to the entry's company, and total ``debit`` equals
    total ``credit``; an unbalanced entry is never valid. The record is atomic: it is
    posted whole or not at all.

    **Recorded vs. adjustment.** The company journal already contains the historical
    transactions (opening balances, receipts, invoices, payments...). Those are *not*
    recorded again. What the solver adds are adjustments, which carry ``provenance``
    and are summed with the recorded journal to compute the closing trial balance.
    The solver therefore reasons about what is *missing* (an unbooked bank fee, an
    unbilled accrual, an FX revaluation), never about re-posting what exists.

    ERP shape of ``erp/journal_entries.jsonl``.
    """

    company: Required[CompanyCode]
    """Company that records the entry and owns all of its lines."""

    lines: Required[list[JournalLine]]
    """Debit and credit lines. Never empty; their signed amounts sum to zero."""

    id: str
    """Unique identifier ``<company>-<year>-<number>`` (``1100-2024-5000000006``). Solver
    adjustments may omit it; when present it must not repeat within the book."""

    doc_type: str
    """Document class, as observed in the July journal: ``WE`` service-entry sheet (GR/IR),
    ``KR`` vendor invoice, ``KG`` vendor credit note, ``DR`` customer invoice, ``ZP`` payment
    (payment runs, direct debits, payroll, social security), ``ZB`` other bank-side items
    (factoring, UTE, VAT refund), ``DZ`` customer receipt / cash application, ``SB`` bank
    statement postings (fees, interest, card), ``IC`` intercompany (pooling, loans), ``SA`` general
    ledger (opening, payroll, close adjustments)."""

    posting_date: IsoDate
    """Date it is posted; determines the accounting period. Checked against the close window
    (``min_date``/``max_date``) when a validation context supplies it."""

    document_date: IsoDate
    """Date of the underlying document (invoice date). The FX rate and due dates run from here,
    not from the posting date."""

    reference: str
    """Reference of the source document: invoice number, ``SES-<order>``, remittance number,
    ``APERTURA`` for opening balances."""

    header_text: str
    """Human-readable description of the entry."""

    source: str
    """Process that produced it: ``MM`` purchasing, ``AP`` payables, ``SD`` sales billing,
    ``F110`` payment run, ``CASHAPP`` cash application, ``BANKFEE``/``BANKINT`` bank charges,
    ``POOL`` cash pooling, ``PAYROLL``, ``FACTORING``... Close adjustments are tagged
    ``CLOSE_ACCRUAL``, ``CLOSE_PREPAID``, ``CLOSE_FX``, ``CLOSE_WIP``, ``CLOSE_BADDEBT``,
    ``CLOSE_DOUBTFUL``. The ``:reversal`` suffix marks the automatic reversal booked on the
    first day of the next month."""

    currency: Currency
    """Document currency of the header (the line currencies may still differ)."""

    provenance: NotRequired[Provenance]
    """Present only on adjustments added through ``Ledger.add_entry``; absent on the recorded
    journal. Identifies the event and stage that justify the entry."""
