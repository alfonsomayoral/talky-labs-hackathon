from typing import Literal, Required, TypedDict

from ..model.journal_entry import JournalEntry
from ..model.scalars import AccountCode, Cents, CompanyCode, IsoDate


class ArFace(TypedDict, total=False):
    """FACe routing codes of a Spanish public customer."""

    oficina_contable: Required[str]
    organo_gestor: Required[str]
    unidad_tramitadora: Required[str]


class ArDeduction(TypedDict, total=False):
    """A deduction taken from the amount payable (advance amortization, withholdings)."""

    code: str
    amount: Cents
    account: AccountCode


class ArInvoiceLine(TypedDict, total=False):
    description: str
    amount: Cents
    account: AccountCode
    cost_center: str | None
    wbs: str | None


class ArInvoice(TypedDict, total=False):
    """The invoice to issue. Scored fields: ``tax_code``, ``due_date``, ``net``, ``tax``,
    ``retention``, ``payable`` and, for public customers, ``face``."""

    number: str
    currency: str
    gross: Cents
    legal_notice: str
    date: IsoDate
    due_date: Required[IsoDate]
    tax_code: Required[str]
    net: Required[Cents]
    tax: Required[Cents]
    retention: Required[Cents]
    deductions: list[ArDeduction]
    payable: Required[Cents]
    face: ArFace | None
    """Only for Spanish public customers."""

    lines: list[ArInvoiceLine]


class ArBillingRow(TypedDict, total=False):
    """One row of ``ar_billing.jsonl``: the outcome for one item of ``tasks/ar_billing_items.json``.

    Exactly one row per ``billing_item``.
    """

    billing_item: Required[str]
    expected: Required[Literal["INVOICE", "SKIP_PENDING_APPROVAL"]]
    company: CompanyCode
    """Optional: the entry's company is used when absent."""

    invoice: ArInvoice
    """Only when ``expected`` is ``INVOICE``."""

    journal_entry: JournalEntry
    """Only when ``expected`` is ``INVOICE``."""
