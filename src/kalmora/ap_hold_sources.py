"""Bind one invoice's normalized facts, message and phase masters to HOLD gates (#49).

No extraction, golden reads or state writes. The returned allocation is a
provisional snapshot: commit it only after the invoice actually posts.
"""
from calendar import monthrange
from collections.abc import Mapping, Sequence
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
    HoldScope, PriceLine, PricePortion, evaluate_holds, price_variance_check,
    receipt_quantity_check,
)
from .ap_identity import IdentityCatalog, normalize_tax_identifier
from .ap_orders import POCatalog, POQuery
from .ap_rejections import UNKNOWN, RuleStage, resolve_field
from .data import PhaseData
from .facts import DocumentFacts, Evidence, Fact
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


def resolve_hold_sources(*, doc_id: str, facts: DocumentFacts, message: Mapping, data: PhaseData,
                         support: Mapping[str, Sequence[Fact]] | None = None,
                         state: ConsumptionState = ConsumptionState()) -> HoldSources:
    """Evaluate the four HOLD gates for one ordinary invoice already clear of earlier stages.

    `support` carries #46 `event_support_facts` (signed change / factoring); absent
    support stays unknown. Receipts are visible up to the message arrival date,
    bounded by the phase month end.
    """
    fields, diagnostics = facts.fields, []
    message_doc = f"inbox/ap/{doc_id}/message.json"
    identity = IdentityCatalog.from_phase(data).resolve(
        supplier_tax_ids=fields.get("supplier_tax_id"), recipient_tax_ids=fields.get("recipient_tax_id"),
        expected_company=None)
    supplier = identity.supplier
    holds = {name: () for name in ("vendor_in_master", "bank_differs", "similar_domain",
                                   "quantity_check_applicable", "price_check_applicable")}
    holds.update({name: tuple((support or {}).get(name, ()))
                  for name in ("signed_change_supported", "factoring_supported")})
    if supplier.status == "RESOLVED":
        holds["vendor_in_master"] = _facts(True, *supplier.evidence)
    elif supplier.status == "NOT_FOUND":
        holds["vendor_in_master"] = _facts(False, *supplier.evidence, Evidence("erp/vendors.jsonl", "tax_id|vat_id"))
    vendor_id = supplier.identity
    company = identity.recipient.identity
    allocation = quantity_check = price_check = None
    if vendor_id is None:
        stage = evaluate_holds(holds)
        return HoldSources(stage, None, company, None, (f"SUPPLIER_{supplier.status}",))
    vendor = data.get("vendors", vendor_id)
    vendor_doc = f"erp/vendors.jsonl#id={vendor_id}"

    iban_facts = fields.get("iban", [])
    iban, iban_evidence = _value(fields, "iban")
    master_iban = (vendor.get("bank") or {}).get("iban")
    if iban_facts and all(fact.value is None for fact in iban_facts):
        holds["bank_differs"] = _facts(False, *iban_evidence)  # observed absence cannot differ
    elif iban is not None and master_iban:
        holds["bank_differs"] = _facts(normalize_tax_identifier(iban) != normalize_tax_identifier(master_iban),
                                       *iban_evidence, Evidence(vendor_doc, "bank.iban", quote=master_iban))
    elif iban is not None:
        diagnostics.append("MASTER_IBAN_MISSING")
    elif iban_facts:
        diagnostics.append("CONFLICT:iban")

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
    header_po, _ = _value(fields, "po_reference")
    po_evidence = [fact.evidence for name, facts_ in ((n, f) for n, f in fields.items()
                   if n == "po_reference" or re.fullmatch(r"line\.\d+\.po_reference", n)) for fact in facts_
                   if isinstance(fact.value, str) and fact.value]
    applicable = bool(po_evidence) or vendor.get("po_required") is True
    holds["quantity_check_applicable"] = holds["price_check_applicable"] = _facts(
        applicable, Evidence(vendor_doc, "po_required", quote=str(vendor.get("po_required"))), *po_evidence)
    currency = _value(fields, "currency")[0] or vendor.get("currency")
    invoice_date, date_evidence = _value(fields, "document_date")
    if not applicable:
        return HoldSources(evaluate_holds(holds), vendor_id, company, None, tuple(diagnostics))
    if company is None or invoice_date is None or not lines:
        diagnostics.append("QUANTITY_SCOPE_UNKNOWN")
        return HoldSources(evaluate_holds(holds), vendor_id, company, None, tuple(diagnostics))

    year, month = map(int, data.month.split("-"))
    cutoff = min(message["received_at"][:10], f"{data.month}-{monthrange(year, month)[1]:02d}")
    orders, receipts, uoms, catalog, rates = _catalog(data)
    scope = HoldScope(company, vendor_id, currency, doc_id)
    quantity_lines, price_lines, evidence, unresolved = [], [], [], False
    for index, line in lines.items():
        line_id = str(index)
        quantity, quantity_proof = _value(line, "quantity_milli")
        uom = _value(line, "uom")[0]
        uom = uoms.get(uom.casefold().rstrip("."), uom) if isinstance(uom, str) and uom else None
        item = _value(line, "po_item")[0]
        item = int(item) if isinstance(item, (int, str)) and str(item).isdigit() else None
        references = tuple(dict.fromkeys(
            fact.value for name, facts_ in line.items()
            if name in RECEIPT_REFERENCE_FIELDS or re.fullmatch(r"delivery\.\d+\.document_number", name)
            for fact in facts_ if isinstance(fact.value, str) and fact.value))
        evidence.extend(quantity_proof)
        if type(quantity) is not int or quantity <= 0 or uom is None:
            diagnostics.append(f"LINE_QUANTITY_UNKNOWN:{line_id}")
            unresolved = True
            continue
        query = POQuery(line_id, company, vendor_id, currency, quantity, uom, tuple(quantity_proof),
                        po_reference=_value(line, "po_reference")[0] or header_po, po_item=item,
                        receipt_references=references, material=_value(line, "material")[0])
        resolved = catalog.resolve(query, invoice_date=invoice_date, receipt_as_of=cutoff, state=state)
        selected = resolved.selected
        if (resolved.status == "UNKNOWN" and query.po_reference
                and all(d.startswith("UNRESOLVED_RECEIPT:") for d in resolved.diagnostics)):
            # An invoiced albarán absent from the complete receipt catalogue supplies
            # nothing: keep the explicit PO position with no eligible receipt.
            retry = catalog.resolve(replace(query, receipt_references=()), invoice_date=invoice_date,
                                    receipt_as_of=cutoff, state=state)
            selected = replace(retry.selected, receipts=()) if retry.status == "RESOLVED" else None
            diagnostics.extend(resolved.diagnostics)
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
    return HoldSources(stage, vendor_id, company, allocation, tuple(diagnostics))
