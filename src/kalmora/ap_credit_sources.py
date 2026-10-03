"""Bind an evidenced original number to a unique recorded AP invoice, literally."""
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import re

from .ap_credit_state import original_credit_sha256
from .facts import Evidence, Fact
from .model.journal_entry import JournalEntry
from .money import company_local_currency
from .validation import validate_entry


@dataclass(frozen=True)
class CreditOriginalResolution:
    status: str
    original_entry: JournalEntry | None
    reconciliation_account: str | None
    original_sha256: str | None
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[str, ...] = ()
    document_currency: str | None = None
    reference_evidence: Evidence | None = None


class CreditOriginalCatalog:
    """Caller supplies the complete active-phase invoices and recorded journal.

    No amount, vendor name, prefix stripping, series concatenation or UUID-to-
    number inference is used. Results expose copied source journals; they do not
    establish line allocation, fiscal eligibility or unused historical capacity.
    """

    def __init__(self, *, invoices: Iterable[Mapping], journal_entries: Iterable[Mapping],
                 inventory_complete: bool = False,
                 invoice_source: str = "erp/ap_invoices.jsonl",
                 journal_source: str = "erp/journal_entries.jsonl"):
        if type(inventory_complete) is not bool:
            raise TypeError("original inventory completeness must be boolean")
        Evidence(invoice_source, "inventory")
        Evidence(journal_source, "inventory")
        self._complete = inventory_complete
        self._invoice_source, self._journal_source = invoice_source, journal_source
        self._invoices = deepcopy(tuple(invoices))
        seen = set()
        for row in self._invoices:
            if not isinstance(row, Mapping) or any(not isinstance(row.get(k), str) or not row[k]
                    for k in ("company", "vendor", "currency", "number", "doc_id")):
                raise ValueError("invoice inventory requires explicit scope and document identity")
            key = (row["company"], row["doc_id"])
            if key in seen:
                raise ValueError("duplicate original invoice identity")
            seen.add(key)
        self._journals = {}
        for entry in deepcopy(tuple(journal_entries)):
            if not isinstance(entry, dict) or any(not isinstance(entry.get(k), str) or not entry[k]
                                                  for k in ("company", "id")):
                raise ValueError("recorded journal requires explicit company/id")
            key = (entry["company"], entry["id"])
            if key in self._journals:
                raise ValueError("duplicate recorded journal identity")
            self._journals[key] = entry

    def resolve(self, *, company: str, vendor: str, currency: str, invoice_date: str,
                original_number: Fact | None, original_series: Fact | None = None) -> CreditOriginalResolution:
        local = company_local_currency(company)
        if not isinstance(vendor, str) or not vendor.strip() or not isinstance(currency, str) or not re.fullmatch("[A-Z]{3}", currency):
            raise ValueError("resolved credit vendor/document currency required")
        if not isinstance(invoice_date, str) or date.fromisoformat(invoice_date).isoformat() != invoice_date:
            raise ValueError("credit invoice date must be ISO")
        evidence = []

        def stop(status, diagnostic):
            return CreditOriginalResolution(status, None, None, None, tuple(evidence), (diagnostic,))

        if original_number is None:
            return stop("UNKNOWN", "ORIGINAL_REFERENCE_UNKNOWN")
        for fact in (original_number, original_series):
            if fact is not None:
                if not isinstance(fact, Fact):
                    raise TypeError("original reference requires Fact/Evidence")
                evidence.append(fact.evidence)
        number = original_number.value
        if number is None or number == "":
            return stop("UNKNOWN", "ORIGINAL_REFERENCE_UNKNOWN")
        if not isinstance(number, str) or not number.strip():
            raise TypeError("original invoice number must be nonempty literal text")
        if original_series is not None and original_series.evidence.document != original_number.evidence.document:
            return stop("UNKNOWN", "ORIGINAL_REFERENCE_ASSOCIATION_UNKNOWN")
        series = original_series.value if original_series is not None else None
        if series is not None and not isinstance(series, str):
            raise TypeError("original invoice series must be literal text")
        matches = [row for row in self._invoices
                   if (row["company"], row["vendor"], row["currency"], row["number"]) ==
                      (company, vendor, currency, number)]
        for row in matches:
            evidence.extend(Evidence(self._invoice_source, f"company={company};doc_id={row['doc_id']}.{field}")
                            for field in ("number", "vendor", "currency", "kind", "issue_date", "journal_entry"))
        if not self._complete:
            return stop("UNKNOWN", "ORIGINAL_INVENTORY_INCOMPLETE")
        if not matches:
            return stop("NOT_FOUND", "EXACT_ORIGINAL_NOT_FOUND")
        if series:
            # A nonempty documentary series cannot be silently discarded when
            # the ERP has only a combined/unknown number representation.
            if any("series" not in row or row["series"] is None for row in matches):
                return stop("UNKNOWN", "ORIGINAL_SERIES_UNKNOWN")
            matches = [row for row in matches if row["series"] == series]
            if not matches:
                return stop("CONFLICT", "ORIGINAL_SERIES_DIFFERS")
        if len(matches) != 1:
            return stop("AMBIGUOUS", "MULTIPLE_EXACT_ORIGINALS")
        row = matches[0]
        if series:
            evidence.append(Evidence(self._invoice_source, f"company={company};doc_id={row['doc_id']}.series"))
        if row.get("kind") not in {"invoice", "INVOICE"}:
            return stop("CONFLICT", "ORIGINAL_IS_NOT_INVOICE")
        ident = row.get("journal_entry")
        if not isinstance(ident, str) or not ident:
            return stop("UNKNOWN", "ORIGINAL_POSTING_UNKNOWN")
        entry = self._journals.get((company, ident))
        if entry is None:
            return stop("UNKNOWN", "ORIGINAL_JOURNAL_NOT_FOUND")
        evidence.extend(Evidence(self._journal_source, f"company={company};id={ident}.{field}")
                        for field in ("source", "doc_type", "reference", "document_date", "currency", "lines"))
        if validate_entry(entry):
            return stop("UNKNOWN", "ORIGINAL_JOURNAL_INVALID")
        if (entry.get("source"), entry.get("doc_type"), entry.get("reference")) != ("AP", "KR", number):
            return stop("CONFLICT", "ORIGINAL_JOURNAL_IDENTITY_DIFFERS")
        issued = row.get("issue_date")
        if (not isinstance(issued, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", issued)
                or entry.get("document_date") != issued):
            return stop("UNKNOWN", "ORIGINAL_DATE_UNRESOLVED")
        if issued > invoice_date:
            return stop("CONFLICT", "ORIGINAL_IS_LATER_INVOICE")
        applied_advance = any(line["account"] == "40700000" and line["credit"] and not line["debit"] for line in entry["lines"])
        for line in entry["lines"]:
            line_currency = line.get("currency") or entry.get("currency") or local
            local_adjustment = (applied_advance and line_currency == local and line.get("tax_code") is None
                                and line["account"].startswith(("2", "6", "768")))
            if line["account"] == "40700000" and line["credit"] and not line["debit"] or local_adjustment:
                continue  # Original identity only; restoration must resolve these legs.
            if line_currency != currency or currency != local and "amount_doc" not in line or line.get("amount_doc", 0) < 0:
                return stop("UNKNOWN", "ORIGINAL_DOCUMENT_AMOUNTS_UNRESOLVED")
        supplier = [line for line in entry["lines"] if line["account"] in {"40000000", "41000000", "40300000"}]
        accounts = {line["account"] for line in supplier}
        fully_prepaid = (not supplier and row.get("payable") == 0 and type(row.get("payable")) is int
                         and applied_advance
                         and all(line.get("partner") == vendor for line in entry["lines"] if line["account"] == "40700000"))
        if not fully_prepaid and (len(accounts) != 1 or any(line.get("partner") != vendor for line in supplier)
                or sum(line["credit"] - line["debit"] for line in supplier) <= 0):
            return stop("CONFLICT", "ORIGINAL_SUPPLIER_IMPUTATION_DIFFERS")
        snapshot = deepcopy(entry)
        return CreditOriginalResolution("RESOLVED", snapshot, next(iter(accounts)) if accounts else None,
                                        original_credit_sha256(snapshot), tuple(evidence), document_currency=currency,
                                        reference_evidence=original_number.evidence)
