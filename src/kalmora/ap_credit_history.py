"""Positive historical credit usage from exact links and corroborated components."""
from collections import defaultdict
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import date

from .ap_credit_sources import CreditOriginalCatalog
from .ap_credit_state import CreditBalance, original_credit_sha256
from .ap_journal import AdvanceState, CreditReference, build_ap_journal
from .ap_tax import TaxResult
from .ap_valuation import ValuationResult
from .ap_withholding import WithholdingResult
from .facts import Evidence, Fact
from .money import RateTable, company_local_currency
from .validation import validate_entry


@dataclass(frozen=True)
class HistoricalCreditInput:
    entry_id: Fact
    original_number: Fact
    valuation: ValuationResult
    tax: TaxResult
    withholding: WithholdingResult
    references: tuple[CreditReference, ...]
    credit_number: Fact | None = None  # Same observed document as original_number.


@dataclass(frozen=True)
class CreditHistoryResolution:
    status: str
    balances: tuple[CreditBalance, ...]
    covered_entries: tuple[tuple[str, str], ...]
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[str, ...] = ()


def _iso(value):
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _projection(entry, local):
    """Observed accounting dimensions and signed local/document cents, not text."""
    grouped = defaultdict(lambda: [0, 0])
    for line in entry["lines"]:
        currency = line.get("currency") or entry.get("currency") or local
        amount = line.get("amount_doc", max(line["debit"], line["credit"]) if currency == local else None)
        if type(amount) is not int or amount < 0:
            raise ValueError("historical credit document cents unresolved")
        key = (line["account"], line.get("partner"), line.get("cost_center"), line.get("wbs"),
               line.get("tax_code"), currency,
               line.get("assignment") if line["account"] in {"40090000", "40700000"} else None)
        grouped[key][0] += line["debit"] - line["credit"]
        grouped[key][1] += amount * (1 if line["debit"] > line["credit"] else -1)
    return {key: tuple(value) for key, value in grouped.items() if any(value)}


def resolve_historical_credits(*, company: str, vendor: str, currency: str, as_of: Fact,
                               inventory_complete: Fact, inputs: Iterable[HistoricalCreditInput],
                               ap_invoices: Iterable[Mapping], journal_entries: Iterable[Mapping],
                               rates: RateTable | None = None) -> CreditHistoryResolution:
    """Reconstruct evidenced positive usage; the opening scanner owns coverage.

    Facts/components are supplied explicitly, never extracted or recovered by
    amount. Every supplied posting must match a unique AP register/GL link and
    an exact original number. Existing journal factories validate original fiscal
    treatments and reserve all buckets. Their reconstructed monetary projection
    must equal the actual historical KG before usage is exposed. Uncovered KG or
    manual reversals still make resolve_ap_opening_state abstain.
    """
    local = company_local_currency(company)
    if not isinstance(as_of, Fact) or not isinstance(inventory_complete, Fact):
        raise TypeError("historical credit cutoff/inventory require Fact/Evidence")
    if not isinstance(as_of.value, str) or date.fromisoformat(as_of.value).isoformat() != as_of.value:
        raise ValueError("ISO historical cutoff required")
    proof, diagnostics, covered = [as_of.evidence, inventory_complete.evidence], [], []
    if inventory_complete.value is not True:
        return CreditHistoryResolution("UNKNOWN", (), (), tuple(proof), ("CREDIT_INVENTORY_INCOMPLETE",))
    invoices, journals, observations = (deepcopy(tuple(rows)) for rows in (ap_invoices, journal_entries, inputs))
    catalog = CreditOriginalCatalog(invoices=invoices, journal_entries=journals, inventory_complete=True)
    entries = {(entry["company"], entry["id"]): entry for entry in journals}
    state, pending = AdvanceState(), []
    for observation in observations:
        if not isinstance(observation, HistoricalCreditInput) or not isinstance(observation.entry_id, Fact):
            raise TypeError("typed evidenced historical credit inputs required")
        proof.append(observation.entry_id.evidence)
        entry_id = observation.entry_id.value
        entry = entries.get((company, entry_id)) if isinstance(entry_id, str) else None
        rows = [row for row in invoices if row.get("company") == company and row.get("journal_entry") == entry_id]
        if entry is None or len(rows) != 1:
            diagnostics.append("HISTORICAL_CREDIT_LINK_UNRESOLVED")
            continue
        row = rows[0]
        if not isinstance(observation.original_number, Fact):
            raise TypeError("historical original reference requires Fact/Evidence")
        association = observation.credit_number or observation.entry_id
        if (not isinstance(association, Fact) or association.evidence.document != observation.original_number.evidence.document
                or association.value != (row.get("number") if observation.credit_number is not None else entry_id)):
            diagnostics.append("HISTORICAL_CREDIT_ORIGINAL_ASSOCIATION_UNKNOWN")
            continue
        proof.append(association.evidence)
        if validate_entry(entry):
            diagnostics.append("HISTORICAL_CREDIT_ENTRY_INVALID")
            continue
        if ((row.get("vendor"), row.get("currency"), row.get("kind")) != (vendor, currency, "credit_note")
                or (entry.get("source"), entry.get("doc_type"), entry.get("reference")) != ("AP", "KG", row.get("number"))
                or entry.get("document_date") != row.get("issue_date")):
            diagnostics.append("HISTORICAL_CREDIT_SCOPE_CONFLICT")
            continue
        posted = entry.get("posting_date")
        if (not _iso(posted)
                or row.get("posted_on") not in (None, posted)):
            diagnostics.append("HISTORICAL_CREDIT_CLOCK_UNRESOLVED")
            continue
        if posted > as_of.value:
            diagnostics.append("HISTORICAL_CREDIT_AFTER_CUTOFF")
            continue
        original = catalog.resolve(company=company, vendor=vendor, currency=currency,
                                   invoice_date=row["issue_date"], original_number=observation.original_number)
        proof.extend(original.evidence)
        if original.status != "RESOLVED":
            diagnostics.extend(original.diagnostics)
            continue
        original_posted = original.original_entry.get("posting_date")
        original_rows = [candidate for candidate in invoices if candidate.get("company") == company
                         and candidate.get("journal_entry") == original.original_entry.get("id")]
        if (not _iso(original_posted) or original_posted > posted or len(original_rows) != 1
                or original_rows[0].get("posted_on") not in (None, original_posted)):
            diagnostics.append("HISTORICAL_CREDIT_ORIGINAL_CLOCK_UNRESOLVED")
            continue
        if not observation.references or any(original_credit_sha256(ref.original_entry) != original.original_sha256
                                              for ref in observation.references):
            diagnostics.append("HISTORICAL_CREDIT_ORIGINAL_SNAPSHOT_CONFLICT")
            continue
        scopes = (observation.valuation.scope, observation.tax.scope, observation.withholding.scope)
        if any(scope is None or (scope.company, scope.vendor, scope.currency, scope.invoice_id, scope.invoice_date) !=
               (company, vendor, currency, row["doc_id"], row["issue_date"]) for scope in scopes):
            diagnostics.append("HISTORICAL_CREDIT_COMPONENT_SCOPE_CONFLICT")
            continue
        if entry_id in [key[1] for key in covered] or any(item[1]["id"] == entry_id for item in pending):
            diagnostics.append("HISTORICAL_CREDIT_DUPLICATE_OBSERVATION")
            continue
        pending.append((observation, entry, row, original.reconciliation_account))
    for observation, entry, row, account in sorted(pending, key=lambda item: (item[1]["posting_date"], item[1]["id"])):
        try:
            built = build_ap_journal(company=company, vendor=vendor, currency=currency, doc_id=row["doc_id"],
                invoice_number=row["number"], invoice_date=row["issue_date"], posting_date=entry["posting_date"],
                decision=observation.valuation.scope.decision, reconciliation_account=account,
                valuation=observation.valuation, tax=observation.tax, withholding=observation.withholding,
                document_type="CREDIT_NOTE", credit_references=observation.references, rates=rates, state=state)
            if (_projection(entry, local) != _projection(built.journal_entry, local)
                    or (row.get("net"), row.get("tax"), row.get("gross"), row.get("withholding"), row.get("retention"), row.get("payable")) !=
                       (observation.valuation.net_doc, observation.tax.tax_doc, observation.tax.gross_doc,
                        observation.withholding.withholding_doc, observation.withholding.retention_doc, built.payable_doc)):
                raise ValueError("historical credit header/journal differs from supplied components")
            state = built.state
            covered.append((company, entry["id"]))
            proof.append(Evidence("erp/journal_entries.jsonl", f"company={company};id={entry['id']}.lines"))
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            diagnostics.append("HISTORICAL_CREDIT_RECONSTRUCTION_UNRESOLVED:" + str(error))
    return CreditHistoryResolution("UNKNOWN" if diagnostics else "RESOLVED", () if diagnostics else state.credits,
             () if diagnostics else tuple(sorted(covered)), tuple(dict.fromkeys(proof)), tuple(sorted(set(diagnostics))))
