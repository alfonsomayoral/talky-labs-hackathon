"""Bind one invoice's normalized attachments and ERP masters to rejection gates (#48).

``sources`` are the invoice's financial attachments (PDF and/or XML), each
normalized independently and classified as an invoice upstream. Nothing is
guessed: a prerequisite that documents or masters cannot resolve is omitted, so
its gate stays unknown. Rule calculation stays in ``ap_rejections``.
"""
from collections.abc import Sequence
from decimal import Decimal
import re

from .ap_identity import IdentityCatalog
from .ap_pipeline import source_rejection_stage
from .ap_rejections import RuleStage
from .data import PhaseData
from .facts import DocumentFacts, Evidence, Fact

VENDORS, ORDERS, COMPANIES = "erp/vendors.jsonl", "erp/purchase_orders.jsonl", "erp/companies.json"
WORKS_REVERSE_CODES = frozenset({"SISP", "PAUT"})  # construction reverse charge (ES/PT)
_PO_FIELD = re.compile(r"(?:line\.\d+\.)?po_reference")
_RATE_FIELD = re.compile(r"(?:.+\.)?tax_rate_e4")


def _charged_rate(row: dict | None):
    """VAT the supplier must charge under a catalogue code; None when not charged by rate."""
    if row is None:
        return "UNKNOWN_CODE"
    if row["kind"] in {"input", "nondeductible"}:
        return Decimal(row["rate"]) / 10000
    return Decimal(0) if row["kind"] == "exempt" else None


def _one(source: DocumentFacts, name: str) -> Fact | None:
    """The source's value when its candidates agree; contradictions stay unresolved."""
    facts = source.fields.get(name, [])
    if facts and all(type(f.value) is type(facts[0].value) and f.value == facts[0].value for f in facts):
        return facts[0]
    return None


def _document(source: DocumentFacts) -> str:
    return next(f.evidence.document for facts in source.fields.values() for f in facts)


def _is_cfdi(source: DocumentFacts) -> bool:
    return any(name.startswith("raw.xml./Comprobante") for name in source.fields)


def _is_xml(source: DocumentFacts) -> bool:
    return any(name.startswith("raw.xml./") for name in source.fields)


def _withholding(source: DocumentFacts) -> Fact | None:
    fact = _one(source, "withholding_cents")
    if fact is not None:
        return fact
    gross, payable = _one(source, "gross_cents"), _one(source, "payable_cents")
    if gross is not None and payable is not None and gross.value == payable.value:
        return Fact(0, payable.evidence)  # payable = gross - nonnegative deductions
    if _is_cfdi(source) and not any("Retencion" in name for name in source.fields):
        # CFDI 4.0 requires TotalImpuestosRetenidos whenever a retention exists.
        return Fact(0, Evidence(_document(source), "/Comprobante/Impuestos[1]/@TotalImpuestosRetenidos"))
    return None


def _gross(source: DocumentFacts) -> Fact | None:
    """Observed gross; XML totals (Facturae InvoiceTotal, CFDI Total) are net of withholding."""
    gross = _one(source, "gross_cents")
    payable = _one(source, "payable_cents")
    if gross is not None or payable is None or not _is_xml(source):
        return gross
    withheld = _withholding(source)
    if withheld is None or type(payable.value) is not int or type(withheld.value) is not int:
        return None
    proof = payable.evidence
    return Fact(payable.value + withheld.value,
                Evidence(proof.document, f"{proof.field}+{withheld.evidence.field}", proof.page))


def _certification(source: DocumentFacts) -> tuple[Fact | None, Fact | None]:
    current, previous, cumulative = (_one(source, f"certification_{name}_cents")
                                     for name in ("current", "previous", "cumulative"))
    if current is None and previous is not None and cumulative is not None:
        current = Fact(cumulative.value - previous.value, cumulative.evidence)
    if cumulative is None and previous is not None and current is not None:
        cumulative = Fact(current.value + previous.value, current.evidence)
    return current, cumulative


def _cfdi_view(source: DocumentFacts, pdf_number: str | None) -> dict:
    def value(name):
        fact = _one(source, name)
        return None if fact is None else fact.value
    number = value("document_number")
    if isinstance(number, str):
        number = re.sub(r"[^0-9A-Z]", "", number.upper())
        series = value("raw.series")
        if _is_cfdi(source) and isinstance(series, str) and number != pdf_number:
            number = re.sub(r"[^0-9A-Z]", "", series.upper()) + number
    gross = _gross(source)
    return {"number": number, "date": value("document_date"), "issuer_tax_id": value("supplier_tax_id"),
            "recipient_tax_id": value("recipient_tax_id"), "currency": value("currency"),
            "net_cents": value("net_cents"), "tax_cents": value("tax_cents"),
            "gross_cents": None if gross is None else gross.value}


def rejection_stage(sources: Sequence[DocumentFacts], data: PhaseData) -> RuleStage:
    """Ordered rejection gates for one invoice from its attachments and phase masters."""
    sources = tuple(sources)
    if any(not isinstance(source, DocumentFacts) or not source.fields for source in sources):
        raise TypeError("rejection sources require nonempty normalized DocumentFacts")
    every = lambda name: [f for s in sources for f in s.fields.get(name, [])]
    agreed = lambda pick: [f for f in map(pick, sources) if f is not None]
    fields: dict[str, list[Fact]] = {}

    orders = {row["id"]: row for row in data.table("purchase_orders")}
    refs = sorted({f.value for s in sources for name, facts in s.fields.items()
                   if _PO_FIELD.fullmatch(name) for f in facts if isinstance(f.value, str)})
    found = [orders[ref] for ref in refs if ref in orders]
    identity = IdentityCatalog.from_phase(data).resolve(
        supplier_tax_ids=every("supplier_tax_id"), recipient_tax_ids=every("recipient_tax_id"),
        expected_company=None)
    vendor = None
    if identity.supplier.status == "RESOLVED":
        vendor = data.get("vendors", identity.supplier.identity)
    # The ordering company is the referenced PO's; without a PO, a vendor enabled
    # for a single company can only have been engaged by that company.
    fields["order_company"] = [Fact(po["company"], Evidence(ORDERS, f"id={po['id']}.company")) for po in found]
    if not found and vendor is not None and len(vendor.get("companies") or ()) == 1:
        fields["order_company"] = [Fact(vendor["companies"][0], Evidence(VENDORS, f"id={vendor['id']}.companies"))]
    ordering = {f.value for f in fields["order_company"]}

    recipient = identity.recipient
    nif = every("recipient_tax_id")
    if recipient.status not in {"CONFLICT", "UNKNOWN"}:  # presence only; formats may differ
        fields["recipient_nif"] = [f if f.value is None or not str(f.value).strip() else Fact("PRESENT", f.evidence)
                                   for f in nif]
    if recipient.status == "RESOLVED":
        fields["recipient_company"] = [Fact(recipient.identity, e) for e in recipient.evidence]

    company = next(iter(ordering)) if len(ordering) == 1 else None
    if found:
        codes = [Fact(item["tax_code"], Evidence(ORDERS, f"id={po['id']}.items[item={item['item']}].tax_code"))
                 for po in found for item in po["items"]]
    elif vendor is not None:
        codes = [Fact(vendor["default_tax_code"], Evidence(VENDORS, f"id={vendor['id']}.default_tax_code"))]
    else:
        codes = []
    names = {f.value for f in codes}
    if names and (names <= WORKS_REVERSE_CODES or not names & WORKS_REVERSE_CODES):
        works = names <= WORKS_REVERSE_CODES
        fields["isp_required"] = [Fact(works, f.evidence) for f in codes]
        fields["certification_applicable"] = [Fact(works, f.evidence) for f in codes]
    fields["charged_vat_cents"] = agreed(lambda s: _one(s, "tax_cents"))

    catalogue = data.table("tax_codes")["tax_codes"]
    expected = {_charged_rate(catalogue.get(n)) for n in names}
    if names and expected == {None}:
        fields["vat_check_applicable"] = [Fact(False, f.evidence) for f in codes]
    elif len(expected) == 1 and isinstance(next(iter(expected)), Decimal):
        fields["vat_check_applicable"] = [Fact(True, f.evidence) for f in codes]
        rates = [f for s in sources for name, facts in s.fields.items()
                 if _RATE_FIELD.fullmatch(name) and ".withheld." not in name
                 for f in facts if type(f.value) is int]
        applicable = next(iter(expected))
        lines = [{"applied_rate": Decimal(rate) / 10000, "applicable_rate": applicable}
                 for rate in sorted({f.value for f in rates})]
        fields["vat_lines"] = [Fact(lines, f.evidence) for f in rates]

    if vendor is not None:
        fields["withholding_required"] = [Fact(vendor["withholding"] is not None,
                                               Evidence(VENDORS, f"id={vendor['id']}.withholding"))]
    fields["withholding_cents"] = agreed(_withholding)

    fields["billed_net_cents"] = agreed(lambda s: _one(s, "net_cents"))
    fields["certification_current_cents"] = agreed(lambda s: _certification(s)[0])
    fields["certification_cumulative_cents"] = agreed(lambda s: _certification(s)[1])

    if company is not None:
        country = next(row["country"] for row in data.companies if row["code"] == company)
        xml = [s for s in sources if _is_cfdi(s)]
        pdf = [s for s in sources if not _is_xml(s)]
        applicable = country == "MX" and bool(xml) and bool(pdf)
        fields["cfdi_applicable"] = [Fact(applicable, Evidence(COMPANIES, f"code={company}.country"))]
        if applicable:
            pdf_views = [_cfdi_view(s, None) for s in pdf]
            number = pdf_views[0]["number"]
            fields["cfdi_pdf"] = [Fact(view, Evidence(_document(s), "cfdi_view")) for s, view in zip(pdf, pdf_views)]
            fields["cfdi_xml"] = [Fact(_cfdi_view(s, number), Evidence(_document(s), "cfdi_view")) for s in xml]

    amount_sources = [DocumentFacts(s.source_sha256, s.extractor_version, {**s.fields, "gross_cents": [g]})
                      if (g := _gross(s)) is not None and "gross_cents" not in s.fields else s for s in sources]
    return source_rejection_stage(fields, amount_sources=amount_sources)
