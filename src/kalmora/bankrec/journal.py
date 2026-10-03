"""Expose M3 adjustments to cash application and close with stable ledger ownership."""
from calendar import monthrange

from ..model import JournalEntry
from ..money import company_local_currency
from ..validation import validate_entry
from .model import BankRecRun


def journal_entries(run: BankRecRun) -> tuple[JournalEntry, ...]:
    """Closing entries in local cents; no recorded ERP entry is emitted again.

    Unrecorded receipts own bank_import; the consumer only applies 555 to AR under
    cash_application. Pooling is already owned by bank_rec and must not be posted
    again by an IC consumer. Ledger enforces these owners on replay/restoration.
    """
    if run.unresolved:
        raise ValueError("cannot expose an unresolved reconciliation")
    entries, owners = [], set()
    for result in run.results:
        # Equal candidates paired in stable order and historical groups left open
        # are matching notes, and deferred direct debits wait for AP. Accounting/coverage
        # diagnostics block publication.
        if any(not d.startswith(("ambiguous ", "group ", "deferred ")) for d in result.diagnostics):
            raise ValueError("cannot expose a reconciliation with diagnostics")
        year, month = (int(x) for x in result.month.split("-"))
        day = f"{result.month}-{monthrange(year, month)[1]:02d}"
        currency = company_local_currency(result.account.company)
        for adjustment in result.adjustments:
            event, stage = adjustment.owner
            if adjustment.owner in owners:
                raise ValueError("duplicate bank adjustment owner")
            owners.add(adjustment.owner)
            entry = JournalEntry(
                company=result.account.company, currency=currency, posting_date=day, document_date=day,
                doc_type="SB", source="BANK_REC", reference=";".join(adjustment.causes),
                header_text=adjustment.category.value, provenance=dict(event_id=event, stage=stage),
                lines=[dict(line=i, company=x.company, account=x.account, debit=x.debit, credit=x.credit,
                            currency=currency, amount_doc=max(x.debit, x.credit), partner=x.partner,
                            assignment=x.assignment, cost_center=x.cost_center)
                       for i, x in enumerate(adjustment.lines, 1)])
            problems = validate_entry(entry)
            if problems:
                raise ValueError("; ".join(problems))
            entries.append(entry)
    return tuple(entries)
