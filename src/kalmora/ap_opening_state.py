"""Evidence-bound, one-time advance/credit opening state for an AP scope (#54)."""
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import re

from .ap_advance_history import resolve_historical_advances
from .ap_journal import AdvanceState
from .ap_tax import TaxCatalog
from .facts import Evidence, Fact
from .model.ap_scope import ApScope
from .money import company_local_currency


@dataclass(frozen=True)
class APOpeningStateResolution:
    status: str
    state: AdvanceState | None
    scope: ApScope
    cutoff: str
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[str, ...] = ()
    reference_entry_errors: tuple[str, ...] = ()


_PAYABLES = {"40000000", "41000000", "40300000"}
_AP_PARTNERS = _PAYABLES | {"40700000", "40000900", "40090000"}
_NONPOSTING = {"HOLD", "REJECT", "DUPLICATE", "NOT_INVOICE"}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _iso(value):
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _credit(row):
    return row.get("kind") in ("credit_note", "CREDIT_NOTE")


def _possible_credit(row):
    # An absent/unknown type is not proof that a posted document was an invoice.
    return row.get("kind") not in ("invoice", "INVOICE", "down_payment_request", "DOWN_PAYMENT_REQUEST")


def _account(line):
    value = line.get("account")
    return value if isinstance(value, str) and re.fullmatch(r"[0-9]{8}", value) else None


def _key(row, field):
    # Unknown scalar identities stay unknown, not hashable pseudo-identities.
    return tuple(value if _text(value) else None for value in (row.get("company"), row.get(field)))


def _positive(value):
    return type(value) is int and value > 0


def _potential_reversal(entry):
    """A liability reduction against AP base/tax/advance can be an unlinked credit.

    Paying a supplier against cash is not an invoice reversal. A favorable price
    difference in an ordinary invoice still increases its supplier liability.
    No credit is inferred from a number prefix, free text or matching amount.
    """
    lines = entry.get("lines")
    if not isinstance(lines, list) or any(not isinstance(line, Mapping) for line in lines):
        return True  # Cannot prove that malformed recorded movements are harmless.
    if any(_account(line) is None or any(type(line.get(side)) is not int or line[side] < 0
                                         for side in ("debit", "credit")) for line in lines):
        return True
    payable = [line for line in lines if _account(line) in _PAYABLES]
    # Never net a supplier debit against another supplier's credit. Even an
    # entry with a net credit can include a separately credited original.
    reducing = any(type(line.get("debit")) is not int or _positive(line.get("debit")) for line in payable)
    reversed_component = any(
        (type(line.get("credit")) is not int or _positive(line.get("credit"))) and (
            isinstance(line.get("account"), str) and line["account"].startswith(("2", "6"))
            and line["account"] not in {"66800000", "76800000"}
            or _account(line) in {"40090000", "40700000", "47200000", "47210000"}
        ) for line in lines
    )
    # A manual refund may omit the AP partner entirely: cash received against
    # reversed expense/asset is not the usual supplier payment (Dr AP / Cr cash).
    # OPENING/SA explicitly denotes an aggregate opening balance, not an AP
    # transaction. It never proves a complete history or suppresses linked KG.
    opening = entry.get("source") == "OPENING" and entry.get("doc_type") == "SA"
    cash_received = any(_account(line).startswith("572") and _positive(line["debit"]) for line in lines)
    refunded_base = any(_account(line).startswith(("2", "6")) and _account(line) != "66800000"
                        and _positive(line["credit"]) for line in lines)
    return reducing and reversed_component or cash_received and refunded_base and not opening


def resolve_ap_opening_state(*, company: str, vendor: str, currency: str, as_of: Fact,
                             journal_entries: Iterable[Mapping], purchase_orders: Iterable[Mapping],
                             vendors: Iterable[Mapping], ap_invoices: Iterable[Mapping],
                             tax_catalog: TaxCatalog, inventory_complete: Fact) -> APOpeningStateResolution:
    """Prove zero prior credits for this scope and retain its real advance history.

    A complete inventory includes manual movements and unposted AP documents.
    This initializes a baseline once; it is not a reset between new tasks. The
    caller preserves receipt state, prior publications/events and committed
    credits separately. Empty credits are proved only for the returned scope
    and cutoff, never for another currency/vendor or the whole phase.
    """
    company_local_currency(company)
    if not _text(vendor) or not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("opening state requires an explicit vendor and ISO document currency")
    if not isinstance(as_of, Fact) or not isinstance(inventory_complete, Fact):
        raise TypeError("opening cutoff and complete inventory require Fact/Evidence")
    if not _iso(as_of.value):
        raise ValueError("opening cutoff requires an evidenced ISO date")
    if not isinstance(tax_catalog, TaxCatalog):
        raise TypeError("active AP tax catalogue required")
    scope, cutoff = ApScope(company, vendor, currency), as_of.value
    evidence = [as_of.evidence, inventory_complete.evidence]
    diagnostics, reference_errors = [], []

    def finish(state=None):
        proof = tuple(sorted(set(evidence), key=lambda e: (e.document, e.field, e.page or 0, e.quote or "")))
        return APOpeningStateResolution("RESOLVED" if state is not None else "UNKNOWN", state,
                                        scope, cutoff, proof, tuple(sorted(set(diagnostics))),
                                        tuple(sorted(set(reference_errors))))

    if inventory_complete.value is not True:
        diagnostics.append("OPENING_INVENTORY_INCOMPLETE")
        return finish()
    # Materialize each caller iterable once. Both analyses see the same copied
    # snapshot even for one-shot generators; neither can mutate source records.
    journals, orders, masters, invoices = (
        deepcopy(tuple(rows)) for rows in (journal_entries, purchase_orders, vendors, ap_invoices)
    )
    if any(not isinstance(row, Mapping) for rows in (journals, orders, masters, invoices) for row in rows):
        diagnostics.append("OPENING_SOURCE_RECORD_INVALID")
        return finish()
    linked = {}
    for row in invoices:
        if _text(row.get("journal_entry")):
            linked.setdefault(_key(row, "journal_entry"), []).append(row)
    journal_keys = {_key(entry, "id") for entry in journals
                    if _text(entry.get("id"))}

    def assess(entry, rows, locator, *, missing_link=False):
        """Do not choose a convenient observation over an unknown/conflicting one."""
        observed = {"company": [], "vendor": [], "currency": []}
        dates, invalid_date = [], False
        if entry is not None:
            observed["company"].append(entry.get("company"))
            lines = entry.get("lines", [])
            if not isinstance(lines, list) or any(not isinstance(line, Mapping) for line in lines):
                lines = []
            partners = [line.get("partner") for line in lines if _account(line) in _AP_PARTNERS]
            observed["vendor"].extend(partners or [None])
            document_lines = [line for line in lines if _account(line) in _AP_PARTNERS
                              or isinstance(line.get("account"), str) and line["account"].startswith(("2", "6", "472", "477", "475"))]
            observed["currency"].extend(
                line.get("currency", entry.get("currency")) for line in document_lines
            )
            if not document_lines:
                observed["currency"].append(entry.get("currency"))
            posted = entry.get("posting_date")
            if _iso(posted):
                dates.append(posted)
            else:
                invalid_date = True
        for row in rows:
            for field in observed:
                observed[field].append(row.get(field))
            posted = row.get("posted_on")
            if posted is not None:
                if _iso(posted):
                    dates.append(posted)
                else:
                    invalid_date = True
            elif entry is None:
                invalid_date = True
        # A fully observed different dimension excludes this requested scope.
        # Missing observations cannot corroborate an otherwise different scope.
        for field, target in (("company", company), ("vendor", vendor), ("currency", currency)):
            values = observed[field]
            if (values and all(_text(value) and (field != "currency" or re.fullmatch(r"[A-Z]{3}", value))
                               and value != target for value in values)
                    and len(set(values)) == 1):
                return
        evidence.append(Evidence("erp/journal_entries.jsonl" if entry is not None else "erp/ap_invoices.jsonl", locator))
        # Every observed clock must put the movement beyond the cutoff before
        # excluding it. An invalid/contradictory clock cannot establish futurity.
        if dates and not invalid_date and len(set(dates)) == 1 and all(day > cutoff for day in dates):
            return
        unknown_scope = any(not values or any(not _text(value) or
                            field == "currency" and not re.fullmatch(r"[A-Z]{3}", value)
                            for value in values) for field, values in observed.items())
        contradictory = any(len(set(value for value in values if _text(value))) > 1
                            for values in observed.values())
        if unknown_scope or contradictory:
            diagnostics.append(f"{locator}:CREDIT_HISTORY_SCOPE_UNRESOLVED")
        if invalid_date or not dates or len(set(dates)) > 1:
            diagnostics.append(f"{locator}:CREDIT_HISTORY_POSTING_DATE_UNRESOLVED")
        if missing_link or len(rows) > 1 or entry is not None and any(not _credit(row) for row in rows):
            diagnostics.append(f"{locator}:CREDIT_HISTORY_LINK_UNRESOLVED")
        diagnostics.append(f"{locator}:HISTORICAL_CREDIT_OR_REVERSAL_PRESENT")

    for entry in journals:
        rows = linked.get(_key(entry, "id"), ())
        entry_lines = entry.get("lines") if isinstance(entry.get("lines"), list) else []
        is_ap_credit = entry.get("doc_type") == "KG" and (
            entry.get("source") != "AR" or any(
                isinstance(line, Mapping) and _account(line) in _AP_PARTNERS
                for line in entry_lines
            )
        )
        if is_ap_credit or any(_possible_credit(row) for row in rows) or _potential_reversal(entry):
            assess(entry, rows, f"company={entry.get('company')};id={entry.get('id')}")
    for row in invoices:
        if not _possible_credit(row) or _key(row, "journal_entry") in journal_keys:
            continue
        locator = f"company={row.get('company')};doc_id={row.get('doc_id')}"
        # Explicit nonposting metadata plus the complete journal's absence of
        # this credit number corroborates non-consumption. A missing field,
        # dangling posting link, or observed same-number journal does not.
        unposted = ("journal_entry" in row and row["journal_entry"] is None
                    and "posted_on" in row and row["posted_on"] is None
                    and row.get("decision") in tuple(_NONPOSTING) and _text(row.get("number")))
        contradicting = any((row.get("company") is None or entry.get("company") in (None, row.get("company")))
                            and entry.get("reference") == row.get("number") for entry in journals)
        if unposted and not contradicting:
            evidence.append(Evidence("erp/ap_invoices.jsonl", locator + ".unposted"))
            continue
        assess(None, (row,), locator, missing_link=True)
    # Preserve the complete recorded inventory. The historical engine checks
    # ordinary AP headers too: an absent 407 cannot disprove an observed header
    # application when its posting link or clock is unresolved.
    try:
        history = resolve_historical_advances(
            company=company, vendor=vendor, as_of=cutoff, journal_entries=journals,
            purchase_orders=orders, vendors=masters, ap_invoices=invoices,
            tax_catalog=tax_catalog, inventory_complete=True,
        )
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        diagnostics.append(f"ADVANCE_HISTORY_SOURCE_UNRESOLVED:{type(error).__name__}")
        return finish()
    evidence.extend(history.evidence)
    diagnostics.extend(history.diagnostics)
    reference_errors.extend(history.reference_entry_errors)
    if history.status != "RESOLVED":
        diagnostics.append("ADVANCE_HISTORY_UNRESOLVED")
    if diagnostics:
        return finish()
    return finish(AdvanceState(balances=history.balances))
