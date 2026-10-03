"""Bind one invoice's normalized facts, message and phase masters to HOLD gates (#49).

No extraction, golden reads or state writes. The returned allocation is a
provisional snapshot: commit it only after the invoice actually posts.
"""
from calendar import monthrange
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from difflib import SequenceMatcher
from email.utils import parseaddr
from functools import lru_cache
import re

from .ap_allocation import (
    AllocationResult, ConsumptionState, InvoiceQuantityLine, OrderKey, OrderLine,
    OrderPortion, Receipt, allocate_receipts,
)
from .ap_holds import (
    HOLD_CODES, HoldScope, PriceLine, PricePortion, evaluate_holds, price_variance_check,
    receipt_quantity_check,
)
from .ap_chronology import event_support_facts
from .ap_chronology_sources import invoice_events
from .ap_identity import normalize_tax_identifier
from .ap_identity_sources import resolve_ap_identity
from .ap_orders import POCatalog, POQuery
from .ap_rejections import UNKNOWN, RuleCheck, RuleStage, resolve_field
from .data import PhaseData
from .facts import DocumentFacts, Evidence, Fact
from .model.ap_event import ApEvent
from .model.ap_scope import ApScope
from .money import RateTable

RECEIPT_REFERENCE_FIELDS = ("delivery_reference", "receipt_reference")


@dataclass(frozen=True)
class HoldSources:
    stage: RuleStage
    vendor: str | None
    company: str | None
    allocation: AllocationResult | None  # provisional; never commit for non-posting results
    diagnostics: tuple[str, ...] = ()


def _facts(value, *evidence):
    return tuple(Fact(value, item) for item in evidence)


def _domain(address):
    _, email = parseaddr(address or "")
    return email.rpartition("@")[2].casefold() if "@" in email else None


def similar_domain(sender: str, master: str) -> bool:
    """Look-alike, not merely different: one label embeds the other or nearly matches."""
    if sender == master:
        return False
    a, b = sender.rsplit(".", 1)[0], master.rsplit(".", 1)[0]
    return a == b or a in b or b in a or SequenceMatcher(None, a, b).ratio() >= 0.8


@lru_cache(maxsize=2)
def _catalog(data: PhaseData):
    """Complete order/receipt catalogue required by #44 to validate prior usage."""
    orders, uoms = [], {}
    for row in data.table("purchase_orders"):
        for item in row["items"]:
            key = OrderKey(row["company"], row["vendor"], row["currency"], row["id"], item["item"])
            orders.append(OrderLine(key, item["uom"]))
            uoms[(key.company, key.po, key.item)] = (key, item["uom"])
    receipts = tuple(Receipt(r["id"], uoms[(r["company"], r["po"], r["po_item"])][0], r["quantity_milli"],
                             uoms[(r["company"], r["po"], r["po_item"])][1], r["posting_date"], r["type"])
                     for r in data.table("goods_receipts"))
    return (tuple(orders), receipts, {u.casefold(): u for _, u in uoms.values()},
            POCatalog.from_phase(data), RateTable(data.table("fx_rates")))


def _po_uom(data, po):
    """Lines without a printed unit (Facturae) take the unit only when the PO has one."""
    try:
        units = {item["uom"] for item in data.get("purchase_orders", po)["items"]} if po else set()
    except KeyError:
        return None
    return units.pop() if len(units) == 1 else None


def _po_item(data, order):
    return next(i for i in data.get("purchase_orders", order.po)["items"] if i["item"] == order.item)


def _concept(value):
    return " ".join(value.casefold().split())


def _references(line):
    """Explicit albarán references; a printed "AL-1 (12/06)" carries its date beside it."""
    return {re.sub(r"\s*\([^)]*\)$", "", fact.value): fact for name, facts in line.items()
            if name in RECEIPT_REFERENCE_FIELDS or re.fullmatch(r"delivery\.\d+\.document_number", name)
            for fact in facts if isinstance(fact.value, str) and fact.value}


def _lines(fields):
    lines = {}
    for name, facts in fields.items():
        match = re.fullmatch(r"line\.(\d+)\.(.+)", name)
        if match:
            lines.setdefault(int(match[1]), {})[match[2]] = facts
    return dict(sorted(lines.items()))


def _value(fields, name):
    value, evidence, _ = resolve_field(fields, name)
    return None if value is UNKNOWN else value, evidence


def resolve_hold_sources(*, doc_id: str, documents: Sequence[DocumentFacts], message: Mapping, data: PhaseData,
                         notices: Iterable[ApEvent] = (),
                         state: ConsumptionState = ConsumptionState()) -> HoldSources:
    """Evaluate the four HOLD gates for one ordinary invoice already clear of earlier stages.

    `documents` are the invoice attachment(s) (e.g. CFDI XML + PDF); `notices` are
    the month's #46 `notice_events`, a complete inbox inventory. Goods receipts are
    visible up to the phase month end (the close), not the message arrival.
    """
    fields, diagnostics = {}, []
    for document in documents:
        for name, candidates in document.fields.items():
            fields.setdefault(name, []).extend(candidates)
    message_doc = f"inbox/ap/{doc_id}/message.json"
    binding = resolve_ap_identity(documents, message, data)
    holds = {name: () for name in ("vendor_in_master", "bank_differs", "similar_domain", "signed_change_supported",
                                   "factoring_supported", "quantity_check_applicable", "price_check_applicable")}
    vendor_id, company = binding.vendor_id, binding.company
    if vendor_id is not None:
        holds["vendor_in_master"] = _facts(True, *binding.evidence)
    elif binding.identity.supplier.status == "NOT_FOUND":
        holds["vendor_in_master"] = _facts(False, *binding.identity.supplier.evidence,
                                           Evidence("erp/vendors.jsonl", "tax_id|vat_id"))
    allocation = quantity_check = price_check = None
    if vendor_id is None:
        return HoldSources(evaluate_holds(holds), None, company, None, binding.diagnostics)
    vendor = data.get("vendors", vendor_id)
    vendor_doc = f"erp/vendors.jsonl#id={vendor_id}"
    invoice_date, date_evidence = _value(fields, "document_date")

    iban_facts = fields.get("iban", [])
    iban, iban_evidence = _value(fields, "iban")
    bank = vendor.get("bank") or {}
    master_accounts = {normalize_tax_identifier(bank[k]): k for k in ("iban", "clabe", "account") if bank.get(k)}
    xml_sources = sorted({fact.evidence.document for d in documents for facts_ in d.fields.values() for fact in facts_})
    if iban_facts and all(fact.value is None for fact in iban_facts):
        holds["bank_differs"] = _facts(False, *iban_evidence)  # observed absence cannot differ
    elif not iban_facts and xml_sources and all(name.lower().endswith(".xml") for name in xml_sources):
        # A deterministically parsed e-invoice without PaymentDetails states no account.
        holds["bank_differs"] = _facts(False, *(Evidence(name, "PaymentDetails", quote="absent") for name in xml_sources))
    elif iban is not None and master_accounts:
        holds["bank_differs"] = _facts(normalize_tax_identifier(iban) not in master_accounts, *iban_evidence,
                                       *(Evidence(vendor_doc, f"bank.{k}", quote=bank[k]) for k in master_accounts.values()))
    elif iban is not None:
        diagnostics.append("MASTER_BANK_ACCOUNT_MISSING")
    elif iban_facts:
        diagnostics.append("CONFLICT:iban")
    if holds["bank_differs"] and holds["bank_differs"][0].value and company in vendor["companies"] and invoice_date:
        kinds = ("FACTORING_NOTICE", "BANK_DETAILS_CHANGE")
        events = invoice_events(data, ApScope(company, vendor_id, vendor["currency"]), notices, invoice_date,
                                message["received_at"], invoice_number=_value(fields, "document_number")[0],
                                bank_iban=iban, complete_kinds=kinds)
        inventory = (Evidence("inbox/ap", f"notices received {data.month}"),
                     Evidence(vendor_doc, "alternative_payee"))
        support = event_support_facts(events, {kind: inventory for kind in kinds})
        holds["signed_change_supported"] = support["signed_change_supported"]
        holds["factoring_supported"] = support["factoring_supported"]
        diagnostics.extend(events.diagnostics)

    sender, master_domain = _domain(message.get("from")), _domain(vendor.get("email"))
    if "from" not in message:
        holds["similar_domain"] = _facts(False, Evidence(message_doc, "channel", quote=message.get("channel")))
    elif sender and master_domain:
        holds["similar_domain"] = _facts(similar_domain(sender, master_domain),
                                         Evidence(message_doc, "from", quote=message["from"]),
                                         Evidence(vendor_doc, "email", quote=vendor["email"]))
    else:
        diagnostics.append("SENDER_DOMAIN_UNKNOWN")

    lines = _lines(fields)
    year, month = map(int, data.month.split("-"))
    cutoff = f"{data.month}-{monthrange(year, month)[1]:02d}"
    # Policy §2.2: an invoiced albarán of a PO-managed vendor with no goods receipt in
    # the complete ERP catalogue by the close is QTY_NOT_RECEIVED, whatever its PO position.
    # Vendors without PO requirement have no goods receipts to match.
    received = {value for row in data.table("goods_receipts")
                if row["vendor"] == vendor_id and row["posting_date"] <= cutoff
                for value in (row["id"], row.get("reference")) if value}
    references = {index: _references(line) for index, line in lines.items()}
    missing = [fact for refs in references.values() for ref, fact in refs.items()
               if ref not in received and vendor.get("po_required") is True]
    header_po, _ = _value(fields, "po_reference")
    po_evidence = [fact.evidence for name, facts_ in fields.items()
                   if name == "po_reference" or re.fullmatch(r"line\.\d+\.po_reference", name)
                   for fact in facts_ if isinstance(fact.value, str) and fact.value]
    applicable = bool(po_evidence) or vendor.get("po_required") is True
    holds["quantity_check_applicable"] = holds["price_check_applicable"] = _facts(
        applicable, Evidence(vendor_doc, "po_required", quote=str(vendor.get("po_required"))), *po_evidence)
    currency = _value(fields, "currency")[0] or vendor.get("currency")
    if missing:
        quantity_check = RuleCheck(HOLD_CODES[2], True, (*(fact.evidence for fact in missing),
                                   Evidence("erp/goods_receipts.jsonl", f"vendor={vendor_id};posting_date<={cutoff}")))
        diagnostics.extend(f"ALBARAN_WITHOUT_RECEIPT:{fact.value}" for fact in missing)
        return HoldSources(evaluate_holds(holds, quantity_check=quantity_check), vendor_id, company, None,
                           (*binding.diagnostics, *diagnostics))
    if not applicable:
        return HoldSources(evaluate_holds(holds), vendor_id, company, None, (*binding.diagnostics, *diagnostics))
    if company is None or invoice_date is None or not lines:
        diagnostics.append("QUANTITY_SCOPE_UNKNOWN")
        return HoldSources(evaluate_holds(holds), vendor_id, company, None, (*binding.diagnostics, *diagnostics))

    orders, receipts, uoms, catalog, rates = _catalog(data)
    scope = HoldScope(company, vendor_id, currency, doc_id)
    quantity_lines, price_lines, evidence, unresolved = [], [], [], False
    for index, line in lines.items():
        line_id = str(index)
        quantity, quantity_proof = _value(line, "quantity_milli")
        po = _value(line, "po_reference")[0] or header_po or _value(line, "issuer_transaction_reference")[0]
        uom = _value(line, "uom")[0]
        uom = uoms.get(uom.casefold().rstrip("."), uom) if isinstance(uom, str) and uom else _po_uom(data, po)
        item = _value(line, "po_item")[0]
        item = int(item) if isinstance(item, (int, str)) and str(item).isdigit() else None
        evidence.extend(quantity_proof)
        if type(quantity) is not int or quantity <= 0 or uom is None:
            diagnostics.append(f"LINE_QUANTITY_UNKNOWN:{line_id}")
            unresolved = True
            continue
        query = POQuery(line_id, company, vendor_id, currency, quantity, uom, tuple(quantity_proof),
                        po_reference=po, po_item=item, receipt_references=tuple(references[index]),
                        material=_value(line, "material")[0])
        resolved = catalog.resolve(query, invoice_date=invoice_date, receipt_as_of=cutoff, state=state)
        description = _value(line, "description")[0]
        if resolved.status == "AMBIGUOUS" and isinstance(description, str):
            # The printed concept starts with the PO item text ("<item> – <albarán>").
            items = {c.order for c in resolved.candidates if _concept(description).startswith(
                _concept(_po_item(data, c.order)["description"]))}
            if len(items) == 1:
                order = items.pop()
                resolved = catalog.resolve(replace(query, po_reference=order.po, po_item=order.item),
                                           invoice_date=invoice_date, receipt_as_of=cutoff, state=state)
        selected = resolved.selected
        if selected is None:
            diagnostics.append(f"PO_{resolved.status}:{line_id}")
            unresolved = True
            continue
        evidence.extend(selected.evidence)
        quantity_lines.append(InvoiceQuantityLine(line_id, quantity, uom, (OrderPortion(
            selected.order, quantity, tuple(r.receipt_id for r in selected.receipts)),)))
        unit_price, price_proof = _value(line, "unit_price_e4")
        po_price = Fact(selected.unit_price_cents, Evidence(
            "erp/purchase_orders.jsonl", f"id={selected.order.po}.items[{selected.order.item}].unit_price"))
        price_lines.append(PriceLine(
            line_id, tuple(Fact(Decimal(unit_price) / 100, e) for e in price_proof) if type(unit_price) is int else (),
            (PricePortion(selected.order, quantity, (po_price,)),)))
    if not unresolved:
        allocation = allocate_receipts(company=company, vendor=vendor_id, currency=currency, invoice_id=doc_id,
                                       lines=quantity_lines, orders=orders, receipts=receipts, state=state)
    quantity_check = receipt_quantity_check(scope, allocation, evidence=tuple(evidence),
        catalog_complete=Fact(True, Evidence("erp/goods_receipts.jsonl", f"posting_date<={cutoff}")))
    if allocation is not None and allocation.status == "ALLOCATED":
        price_check = price_variance_check(scope, Fact(invoice_date, date_evidence[0]), tuple(price_lines),
            allocation=allocation, rates=rates,
            rate_evidence=(Evidence("erp/fx_rates.jsonl", f"currency={currency};date<={invoice_date}"),))
    stage = evaluate_holds(holds, quantity_check=quantity_check, price_check=price_check)
    return HoldSources(stage, vendor_id, company, allocation, (*binding.diagnostics, *diagnostics))
