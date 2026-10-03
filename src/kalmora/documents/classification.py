"""Evidence-preserving classification of the nine AP document types (#40)."""
from dataclasses import dataclass
import re
import unicodedata

from kalmora.facts import DocumentFacts, Fact

CLASSIFICATION_VERSION = "ap-document-classification-v3"
DOCUMENT_TYPES = frozenset("""INVOICE CREDIT_NOTE DOWN_PAYMENT_REQUEST PROFORMA
VENDOR_STATEMENT FACTORING_NOTICE TAX_GARNISHMENT_ORDER BANK_DETAILS_CHANGE
CONTRACTOR_TAX_CERTIFICATE""".split())

# Specific lexical titles precede the general invoice title. These classify
# the stated document, never a referenced invoice mentioned inside a notice.
TITLE_RULES = (
    # An explicit deposit request remains a request when its literal title also
    # calls the attachment proforma; no approved-order/payment decision is made.
    ("DOWN_PAYMENT_REQUEST", r"pro ?forma invoice deposit request"),
    ("PROFORMA", r"(?:(?:factura|invoice|fatura) )?pro ?forma"),
    ("CREDIT_NOTE", r"factura (?:rectificativa|de abono)|nota de (?:credito|abono)|credit note|abono|fatura retificativa"),
    ("DOWN_PAYMENT_REQUEST", r"solicitud de anticipo|solicitud de pago anticipado|down payment request|deposit request|advance payment request"),
    ("FACTORING_NOTICE", r"notificacion de cesion de creditos|notificacion de cesion de credito|carta de cesion de creditos|cesion de creditos|factoring notice|notice of assignment"),
    ("TAX_GARNISHMENT_ORDER", r"diligencia de embargo|orden de embargo|tax garnishment order"),
    ("BANK_DETAILS_CHANGE", r"comunicacion de cambio de cuenta bancaria|cambio de datos bancarios|carta de cambio de cuenta|cambio de cuenta bancaria|cambio de cuenta|bank details change|bank account change"),
    ("CONTRACTOR_TAX_CERTIFICATE", r"certificado de estar al corriente|certificado de obligaciones tributarias|certificado de contratistas y subcontratistas|contractor tax certificate|certificado articulo 43"),
    ("VENDOR_STATEMENT", r"extracto de cuenta|recordatorio de pago|extracto de proveedor|vendor statement|statement of account|recordatorio de deuda|estado de cuentas del proveedor"),
    ("INVOICE", r"factura|invoice|facture|fatura|facturae|cfdi de ingreso|cfdi ingreso"),
)


@dataclass(frozen=True)
class ClassificationDiagnostic:
    code: str
    message: str
    evidence: tuple[Fact, ...] = ()


@dataclass(frozen=True)
class DocumentClassification:
    document_type: str | None
    status: str
    evidence: tuple[Fact, ...]
    diagnostics: tuple[ClassificationDiagnostic, ...]
    version: str = CLASSIFICATION_VERSION


def _title(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _lexical_type(value: str) -> str | None:
    if value.strip().upper() in DOCUMENT_TYPES:
        return value.strip().upper()
    # Subject markers are observed title framing, not permission to search body
    # prose for references to an invoice or another document.
    value = re.sub(r"^\s*(?:asunto|subject)\s*:\s*", "", value, flags=re.I)
    title = _title(value)
    if title in {"cfdi de egreso", "cfdi egreso"}:
        return "CREDIT_NOTE"
    for document_type, pattern in TITLE_RULES:
        if re.fullmatch(f"(?:{pattern})(?: .*|)", title):
            return document_type
    return None


def classify_document(facts: DocumentFacts) -> DocumentClassification:
    """Classify one attachment from literal hints; unknown is never NOT_INVOICE."""
    documents = {fact.evidence.document for candidates in facts.fields.values() for fact in candidates}
    if len(documents) > 1:
        diagnostic = ClassificationDiagnostic("MIXED_SOURCE", "classify each attachment independently")
        return DocumentClassification(None, "UNKNOWN", (), (diagnostic,))
    hints = tuple(fact for name in ("document_type_hint", "document_type", "type_hint", "notice_type_hint", "raw.document_type_hint")
                  for fact in facts.fields.get(name, ()))
    typed: dict[str, list[Fact]] = {}
    diagnostics = []
    for fact in hints:
        if not isinstance(fact.value, str):
            diagnostics.append(ClassificationDiagnostic("INVALID_HINT", "type hint must be literal text", (fact,)))
            continue
        document_type = _lexical_type(fact.value)
        if document_type:
            typed.setdefault(document_type, []).append(fact)
        else:
            diagnostics.append(ClassificationDiagnostic("UNKNOWN_HINT", "title does not establish one of the nine types", (fact,)))
    # CFDI alone is a format, not an invoice: I/E are explicit source attributes.
    for name in ("cfdi_type", "tipo_de_comprobante", "raw.cfdi_type", "raw.tipo_de_comprobante"):
        for fact in facts.fields.get(name, ()):
            document_type = {"I": "INVOICE", "E": "CREDIT_NOTE"}.get(fact.value) if isinstance(fact.value, str) else None
            if document_type:
                typed.setdefault(document_type, []).append(fact)
            else:
                diagnostics.append(ClassificationDiagnostic("UNSUPPORTED_CFDI_KIND", "CFDI kind is missing or outside invoice/credit-note scope", (fact,)))
    # Facturae: InvoiceClass OO is an original invoice and OR an original
    # corrective one, for complete (FC) or simplified (FA) invoice documents.
    kinds = facts.fields.get("raw.invoice_document_type", ())
    if any(fact.value in {"FC", "FA"} for fact in kinds):
        for fact in facts.fields.get("raw.invoice_class", ()):
            document_type = {"OO": "INVOICE", "OR": "CREDIT_NOTE"}.get(fact.value) if isinstance(fact.value, str) else None
            if document_type:
                typed.setdefault(document_type, []).append(fact)
            else:
                diagnostics.append(ClassificationDiagnostic("UNSUPPORTED_FACTURAE_CLASS", "Facturae class is outside original invoice/corrective scope", (fact,)))
    if len(typed) > 1:
        evidence = tuple(fact for candidates in typed.values() for fact in candidates)
        diagnostics.append(ClassificationDiagnostic("TYPE_CONFLICT", "source hints establish different document types", evidence))
        return DocumentClassification(None, "CONFLICT", evidence, tuple(diagnostics))
    if not typed:
        diagnostics.append(ClassificationDiagnostic("INSUFFICIENT_TYPE_EVIDENCE", "document type remains unknown", hints))
        return DocumentClassification(None, "UNKNOWN", hints, tuple(diagnostics))
    document_type, evidence = next(iter(typed.items()))
    return DocumentClassification(document_type, "CLASSIFIED", tuple(evidence), tuple(diagnostics))
