"""Reconstruct evidenced recorded advance balances without posting or repairing them."""
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import date
from itertools import groupby
import re

from .ap_journal import AdvanceBalance
from .ap_tax import TaxCatalog
from .facts import Evidence
from .money import company_local_currency
from .validation import validate_entry


@dataclass(frozen=True)
class AdvanceHistoryResolution:
    status: str
    balances: tuple[AdvanceBalance, ...]
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[str, ...] = ()
    reference_entry_errors: tuple[str, ...] = ()


def _iso(value):
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _po(assignment):
    match = re.fullmatch(r"(.+)/([1-9]\d*)", assignment or "") if isinstance(assignment, str) else None
    return (match[1], int(match[2])) if match else None


def resolve_historical_advances(*, company: str, vendor: str, as_of: str,
                                journal_entries: Iterable[Mapping], purchase_orders: Iterable[Mapping],
                                vendors: Iterable[Mapping], ap_invoices: Iterable[Mapping],
                                tax_catalog: TaxCatalog,
                                inventory_complete: bool = False) -> AdvanceHistoryResolution:
    """Resolve one company's complete vendor advance baseline through a cutoff.

    Explicit PO/position and master vendor corroborate a recorded debit. Credits
    name that deposit literally. A local-currency credit against a foreign deposit
    needs a uniquely linked invoice's document gross/deductions/payable residual;
    booked EUR cents never become inferred USD cents. Any unresolved movement
    potentially belonging to this scope suppresses the entire usable baseline.
    The complete AP register also corroborates posting links, application residuals
    and posting clocks; a missing GL application never proves unused capacity.
    New-request approval and monetary/non-monetary treatment remain separate.
    """
    local = company_local_currency(company)
    if not isinstance(tax_catalog, TaxCatalog):
        raise TypeError("active tax catalogue required for historical header corroboration")
    country = "MX" if company == "3100" else "PT" if company == "2100" else "ES"
    if not isinstance(vendor, str) or not vendor.strip() or not _iso(as_of):
        raise ValueError("historical advance requires vendor and ISO cutoff")
    if type(inventory_complete) is not bool:
        raise TypeError("advance inventory completeness must be boolean")
    evidence, diagnostics, reference_errors = [], [], []

    def result(status, balances=()):
        proof = tuple(sorted(set(evidence), key=lambda e: (e.document, e.field, e.page or 0, e.quote or "")))
        return AdvanceHistoryResolution(status, tuple(balances), proof,
                                        tuple(sorted(set(diagnostics))), tuple(sorted(set(reference_errors))))

    if not inventory_complete:
        diagnostics.append("ADVANCE_INVENTORY_INCOMPLETE")
        return result("UNKNOWN")
    orders, masters, entries, invoices = {}, {}, {}, {}
    for rows, index, field in ((purchase_orders, orders, "id"), (vendors, masters, "id")):
        for row in deepcopy(tuple(rows)):
            key = row.get(field)
            if not isinstance(key, str) or not key or key in index:
                raise ValueError("advance masters require unique nonempty identities")
            index[key] = row
    invoice_rows = deepcopy(tuple(ap_invoices))
    for row in invoice_rows:
        key = (row.get("company"), row.get("journal_entry"))
        if any(value is not None and not isinstance(value, str) for value in key):
            diagnostics.append("ADVANCE_DOCUMENT_IDENTITY_UNRESOLVED")
            continue
        invoices.setdefault(key, []).append(row)
    for entry in deepcopy(tuple(journal_entries)):
        key = (entry.get("company"), entry.get("id"))
        if any(not isinstance(value, str) or not value for value in key) or key in entries:
            raise ValueError("recorded journal requires unique company/id")
        entries[key] = entry
    master = masters.get(vendor)
    evidence.append(Evidence("erp/vendors.jsonl", f"id={vendor}.companies"))
    if master is None or company not in master.get("companies", ()):
        diagnostics.append("ADVANCE_VENDOR_AFFILIATION_UNRESOLVED")
        return result("UNKNOWN")
    # Check the complete AP register, not only entries containing 407. A posted
    # ordinary header can observe consumption whose GL link is missing. Silence
    # in GL cannot turn that contradiction into a free deposit balance.
    for row in invoice_rows:
        if row.get("kind") in ("credit_note", "CREDIT_NOTE"):
            continue  # No positive credit restoration is reconstructed here.
        key = (row.get("company"), row.get("journal_entry"))
        entry = entries.get(key) if all(value is None or isinstance(value, str) for value in key) else None
        company_values, vendor_values = [row.get("company")], [row.get("vendor")]
        linked_lines = entry.get("lines") if entry is not None else []
        valid_lines = isinstance(linked_lines, list) and all(isinstance(line, Mapping) for line in linked_lines)
        if entry is not None:
            company_values.append(entry.get("company"))
            supplier = [line.get("partner") for line in linked_lines
                        if line.get("account") in {"40000000", "41000000", "40300000"}] if valid_lines else []
            vendor_values.extend(supplier or [None])
        # Exclusion requires agreement, including the observed journal. A
        # conflicting OTHER/OTHER2 pair does not prove another vendor's scope.
        if any(values and all(isinstance(value, str) and value and value != target for value in values)
               and len(set(values)) == 1
               for values, target in ((company_values, company), (vendor_values, vendor))):
            continue
        locator = f"doc_id={row.get('doc_id')}"
        clocks = [entry.get("posting_date")] if entry is not None else []
        if row.get("posted_on") is not None or entry is None:
            clocks.append(row.get("posted_on"))
        if clocks and all(_iso(day) for day in clocks) and len(set(clocks)) == 1 and clocks[0] > as_of:
            continue
        unposted = (entry is None and "journal_entry" in row and row["journal_entry"] is None
                    and "posted_on" in row and row["posted_on"] is None
                    and row.get("decision") in ("HOLD", "REJECT", "DUPLICATE", "NOT_INVOICE")
                    and isinstance(row.get("number"), str) and bool(row["number"])
                    and not any(other.get("company") in (None, row.get("company"))
                                and other.get("reference") == row["number"] for other in entries.values()))
        if unposted:
            continue
        evidence.append(Evidence("erp/ap_invoices.jsonl", locator + ".journal_entry"))
        if row.get("kind") not in ("invoice", "INVOICE", "down_payment_request", "DOWN_PAYMENT_REQUEST"):
            diagnostics.append(f"{locator}:ADVANCE_DOCUMENT_KIND_UNRESOLVED")
        if entry is None or len(invoices.get(key, ())) != 1:
            diagnostics.append(f"{locator}:ADVANCE_DOCUMENT_LINK_UNRESOLVED")
            continue
        if (any(value != company for value in company_values) or any(value != vendor for value in vendor_values)
                or not valid_lines):
            diagnostics.append(f"{locator}:ADVANCE_DOCUMENT_SCOPE_UNRESOLVED")
        if not clocks or any(not _iso(day) for day in clocks) or len(set(clocks)) != 1:
            diagnostics.append(f"{locator}:ADVANCE_DOCUMENT_POSTING_DATE_UNRESOLVED")
        if (row.get("number") != entry.get("reference") or row.get("issue_date") != entry.get("document_date")
                or not _iso(row.get("issue_date"))):
            diagnostics.append(f"{locator}:ADVANCE_DOCUMENT_REFERENCE_UNRESOLVED")
        if row.get("kind") in ("down_payment_request", "DOWN_PAYMENT_REQUEST"):
            continue  # Deposit amount/PO verification belongs to the 407 analysis.
        monetary = [row.get(field) for field in ("gross", "withholding", "retention", "payable")]
        if any(type(value) is not int or value < 0 for value in monetary):
            diagnostics.append(f"{locator}:ADVANCE_DOCUMENT_AMOUNTS_UNRESOLVED")
            continue
        document_currency = row.get("currency")
        supplier_lines = [line for line in linked_lines if line.get("account") in
                          {"40000000", "41000000", "40300000"}] if valid_lines else []
        if (not isinstance(document_currency, str) or not re.fullmatch(r"[A-Z]{3}", document_currency)
                or not supplier_lines
                or any((line.get("currency") or entry.get("currency") or local) != document_currency
                       for line in supplier_lines)):
            diagnostics.append(f"{locator}:ADVANCE_DOCUMENT_CURRENCY_UNRESOLVED")
        residual = monetary[0] - monetary[1] - monetary[2] - monetary[3]
        advances = [line for line in linked_lines if line.get("account") == "40700000"
                    and type(line.get("credit")) is int and line["credit"] > 0] if valid_lines else []
        if residual < 0 or bool(residual) != bool(advances):
            diagnostics.append(f"{locator}:ADVANCE_DOCUMENT_APPLICATION_UNCORROBORATED")
        # Direct document-currency 407 cents must agree with the observed header.
        # The existing foreign/local branch below owns its sole monetary fallback.
        if advances and all((line.get("currency") or entry.get("currency") or local) == row.get("currency")
                            for line in advances):
            amounts = [line.get("amount_doc", line.get("credit") if row.get("currency") == local else None)
                       for line in advances]
            if any(type(value) is not int or value <= 0 for value in amounts) or sum(amounts) != residual:
                diagnostics.append(f"{locator}:ADVANCE_DOCUMENT_APPLICATION_UNCORROBORATED")
    relevant = []
    for entry in entries.values():
        if entry["company"] != company:
            continue
        lines = entry.get("lines", [])
        if not isinstance(lines, list) or any(not isinstance(line, Mapping) for line in lines):
            diagnostics.append(f"{entry['id']}:ADVANCE_SOURCE_ENTRY_UNRESOLVED")
            continue
        advances = [line for line in lines if str(line.get("account", "")).startswith("407")]
        if not advances:
            continue
        parties = {line.get("partner") for line in lines
                   if line.get("account") in {"40000000", "41000000", "40700000"} and line.get("partner")}
        parties.update(row.get("vendor") for row in invoices.get((company, entry["id"]), ()) if row.get("vendor"))
        for line in advances:
            binding = _po(line.get("assignment"))
            order = orders.get(binding[0]) if binding else None
            if order is not None and order.get("company") == company and order.get("vendor"):
                parties.add(order["vendor"])
        if parties and vendor not in parties and len(parties) == 1:
            continue
        locator = f"company={company};id={entry['id']}"
        evidence.append(Evidence("erp/journal_entries.jsonl", locator))
        posted = entry.get("posting_date")
        clocks = [posted]
        clocks.extend(row["posted_on"] for row in invoices.get((company, entry["id"]), ())
                      if row.get("posted_on") is not None)
        if any(not _iso(day) for day in clocks) or len(set(clocks)) != 1:
            diagnostics.append(f"{entry['id']}:ADVANCE_POSTING_DATE_UNKNOWN")
            continue
        if posted > as_of:
            continue
        allowed = {f"lines[{i}].partner: required for open-item account"
                   for i, line in enumerate(lines, 1)
                   if line in advances and line.get("partner") is None}
        errors = validate_entry(entry)
        reference_errors.extend(f"{entry['id']}:{error}" for error in errors)
        if (set(errors) - allowed or len(advances) != 1 or advances[0]["account"] != "40700000"
                or not _iso(entry.get("document_date")) or not isinstance(entry.get("reference"), str)
                or not entry["reference"] or len(parties) > 1):
            diagnostics.append(f"{entry['id']}:ADVANCE_SOURCE_ENTRY_UNRESOLVED")
            continue
        relevant.append((entry, advances[0]))
    balances, origins, applications = {}, {}, []
    for entry, line in relevant:
        ident = entry["id"]
        if not line["debit"]:
            applications.append((entry, line))
            continue
        binding = _po(line.get("assignment"))
        order = orders.get(binding[0]) if binding else None
        currency = line.get("currency") or entry.get("currency") or local
        if (entry.get("doc_type") == "KG" or order is None or order.get("company") != company
                or order.get("vendor") != vendor or order.get("currency") != currency
                or not _iso(order.get("created_on")) or order["created_on"] > entry["document_date"]
                or not any(type(item.get("item")) is int and item["item"] == binding[1] for item in order.get("items", ()))
                or line.get("partner") not in (None, vendor)):
            diagnostics.append(f"{ident}:ADVANCE_ORIGINAL_PO_UNRESOLVED")
            continue
        evidence.extend((Evidence("erp/purchase_orders.jsonl", f"id={binding[0]}.vendor"),
                         Evidence("erp/purchase_orders.jsonl", f"id={binding[0]}.currency"),
                         Evidence("erp/purchase_orders.jsonl", f"id={binding[0]}.items[item={binding[1]}]")))
        amount = line.get("amount_doc", line["debit"] if currency == local else None)
        supplier = [other for other in entry["lines"] if other["account"] in {"40000000", "41000000"}]
        if (type(amount) is not int or amount <= 0 or not re.fullmatch("[A-Z]{3}", currency)
                or (currency == local and amount != line["debit"])
                or any(other.get("partner") != vendor
                       or (other.get("currency") or entry.get("currency") or local) != currency for other in supplier)
                or (supplier and (sum(other["credit"] - other["debit"] for other in supplier) != line["debit"]
                    or sum(other.get("amount_doc", other["credit"] if currency == local else -1) for other in supplier) != amount))):
            diagnostics.append(f"{ident}:ADVANCE_ORIGINAL_AMOUNTS_UNRESOLVED")
            continue
        balance = AdvanceBalance(ident, company, vendor, currency, entry["reference"], entry["document_date"],
                                 binding[0], amount, line["debit"])
        balances[ident] = balance
        origins[ident] = entry
    # Posting dates supply only day-level order. Validate each day's aggregate,
    # never invent ordering between same-day entries using their IDs/list order.
    applications.sort(key=lambda pair: pair[0]["posting_date"])
    for posted_day, movements in groupby(applications, key=lambda pair: pair[0]["posting_date"]):
        changed_balances = set()
        for entry, line in movements:
            ident = entry["id"]
            candidates = [b for b in balances.values() if b.invoice_number == line.get("assignment")]
            if len(candidates) != 1 or not line["credit"]:
                diagnostics.append(f"{ident}:ADVANCE_APPLICATION_REFERENCE_UNRESOLVED")
                continue
            balance = candidates[0]
            supplier = [other for other in entry["lines"] if other["account"] in {"40000000", "41000000"}]
            if (line.get("partner") not in (None, vendor)
                    or (line.get("partner") is None and not supplier)
                    or any(other.get("partner") != vendor for other in supplier)
                    or entry["document_date"] < balance.original_date
                    or entry["posting_date"] < origins[balance.advance_id]["posting_date"]):
                diagnostics.append(f"{ident}:ADVANCE_APPLICATION_SCOPE_UNRESOLVED")
                continue
            currency = line.get("currency") or entry.get("currency") or local
            amount = line.get("amount_doc", line["credit"] if currency == local else None)
            if currency == balance.currency:
                used_doc = amount
            elif currency == local and balance.currency != local and amount == line["credit"]:
                linked = invoices.get((company, ident), ())
                if len(linked) != 1:
                    diagnostics.append(f"{ident}:ADVANCE_APPLICATION_DOCUMENT_SPLIT_UNKNOWN")
                    continue
                invoice = linked[0]
                evidence.append(Evidence("erp/ap_invoices.jsonl", f"company={company};doc_id={invoice.get('doc_id')}.journal_entry"))
                monetary = [invoice.get(field) for field in ("net", "tax", "gross", "withholding", "retention", "payable")]
                if (invoice.get("kind") not in {"invoice", "INVOICE"}
                        or (invoice.get("vendor"), invoice.get("currency"), invoice.get("number"), invoice.get("issue_date")) !=
                           (vendor, balance.currency, entry["reference"], entry["document_date"])
                        or any(type(value) is not int or value < 0 for value in monetary)
                        or monetary[0] + monetary[1] != monetary[2]
                        or not supplier or any((other.get("currency") or entry.get("currency") or local) != balance.currency
                                               or type(other.get("amount_doc")) is not int for other in supplier)
                        or sum(other["amount_doc"] * (1 if other["credit"] > other["debit"] else -1) for other in supplier) != monetary[5]):
                    diagnostics.append(f"{ident}:ADVANCE_APPLICATION_DOCUMENT_AMOUNTS_UNRESOLVED")
                    continue
                # Infer no fiscal classification from a shared expense/tax account.
                # Only fully observed ordinary deductible/exempt journal components
                # can corroborate a header used to recover foreign consumption.
                base = tax = withheld = retained = 0
                unsupported = False
                for other in entry["lines"]:
                    account = other["account"]
                    if account == "40700000" or account in {"40000000", "41000000"}:
                        continue
                    document_amount = other.get("amount_doc")
                    if ((other.get("currency") or entry.get("currency") or local) != balance.currency
                            or type(document_amount) is not int or document_amount < 0):
                        unsupported = True
                        break
                    signed = document_amount * (1 if other["debit"] > other["credit"] else -1)
                    if account.startswith(("2", "6")) or account == "40090000":
                        try:
                            treatment = tax_catalog.get(other.get("tax_code"), country)
                        except ValueError:
                            unsupported = True
                            break
                        if treatment.kind not in {"exempt", "input"}:
                            unsupported = True
                            break
                        base += signed
                    elif account == "47200000":
                        try:
                            treatment = tax_catalog.get(other.get("tax_code"), country)
                        except ValueError:
                            unsupported = True
                            break
                        if treatment.kind != "input":
                            unsupported = True
                            break
                        tax += signed
                    elif account == "47510000":
                        withheld -= signed
                    elif account == "40000900":
                        if other.get("partner") != vendor:
                            unsupported = True
                            break
                        retained -= signed
                    else:
                        unsupported = True
                        break
                if unsupported or (base, tax, withheld, retained) != (monetary[0], monetary[1], monetary[3], monetary[4]):
                    diagnostics.append(f"{ident}:ADVANCE_APPLICATION_HEADER_JOURNAL_CONFLICT")
                    continue
                used_doc = monetary[2] - monetary[3] - monetary[4] - monetary[5]
                evidence.extend(Evidence("erp/ap_invoices.jsonl", f"company={company};doc_id={invoice['doc_id']}.{field}")
                                for field in ("gross", "withholding", "retention", "payable", "currency"))
            else:
                used_doc = None
            if type(used_doc) is not int or used_doc <= 0 or type(amount) is not int or amount <= 0:
                diagnostics.append(f"{ident}:ADVANCE_APPLICATION_DOCUMENT_AMOUNTS_UNRESOLVED")
                continue
            used_doc += balance.used_doc
            used_local = balance.used_local + line["credit"]
            if used_doc > balance.amount_doc or used_local > balance.amount_local:
                diagnostics.append(f"{ident}:ADVANCE_CONSUMPTION_INCONSISTENT")
                continue
            balances[balance.advance_id] = replace(balance, used_doc=used_doc, used_local=used_local)
            changed_balances.add(balance.advance_id)
        for advance_id in changed_balances:
            balance = balances[advance_id]
            carrying = (2 * balance.amount_local * balance.used_doc + balance.amount_doc) // (2 * balance.amount_doc)
            if balance.used_local != carrying:
                diagnostics.append(f"{posted_day}:{advance_id}:ADVANCE_CONSUMPTION_INCONSISTENT")
    if diagnostics:
        return result("UNKNOWN")
    return result("RESOLVED", (balances[key] for key in sorted(balances)))
