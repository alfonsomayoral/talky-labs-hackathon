"""Direct Facturae/CFDI leaf facts, without provider calls or accounting inference."""
from decimal import Decimal, InvalidOperation
import re

from kalmora.facts import DocumentFacts, Evidence, Fact
from .contracts import ParsedDocument

XML_EXTRACTOR_VERSION = "xml-source-extractor-v1"
_INVOICE = "/Facturae/Invoices[1]/Invoice[1]"


class XMLExtractionError(ValueError):
    def __init__(self, document: ParsedDocument, code: str):
        self.path, self.code = document.path, code
        super().__init__(f"{document.path}: {code}")


def _leaves(document: ParsedDocument) -> tuple[str, dict[str, Fact]]:
    if document.media_type not in {"application/xml", "text/xml"}:
        raise XMLExtractionError(document, "UNSUPPORTED_MEDIA_TYPE")
    if not document.blocks:
        raise XMLExtractionError(document, "EMPTY_XML")
    leaves = {}
    for block in document.blocks:
        path = block.source_field
        if not path or not path.startswith("/"):
            raise XMLExtractionError(document, "MISSING_XML_LOCATOR")
        if path in leaves:
            raise XMLExtractionError(document, "DUPLICATE_XML_LOCATOR")
        leaves[path] = Fact(block.text, Evidence(document.path, path, block.page, block.text))
    roots = {path.split("/", 2)[1] for path in leaves}
    if len(roots) != 1 or not roots <= {"Facturae", "Comprobante"}:
        raise XMLExtractionError(document, "UNSUPPORTED_XML_ROOT")
    root = next(iter(roots))
    if root == "Facturae":
        version = leaves.get("/Facturae/FileHeader[1]/SchemaVersion[1]")
        if version is None or version.value != "3.2.2":
            raise XMLExtractionError(document, "UNSUPPORTED_FACTURAE_VERSION")
        invoices = {match.groups() for path in leaves
                    if (match := re.match(r"^/Facturae/Invoices\[(\d+)\]/Invoice\[(\d+)\](?:/|$)", path))}
        if invoices != {("1", "1")}:
            raise XMLExtractionError(document, "UNSUPPORTED_INVOICE_BATCH")
    else:
        version = leaves.get("/Comprobante/@Version")
        if version is None or version.value != "4.0":
            raise XMLExtractionError(document, "UNSUPPORTED_CFDI_VERSION")
    return root, leaves


def _no_discount(leaves: dict[str, Fact], path: str) -> bool:
    """Alias a subtotal as net only when no discount is present or it is zero."""
    fact = leaves.get(path)
    if fact is None:
        return True
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", fact.value):
        return False
    try:
        return Decimal(fact.value) == 0
    except InvalidOperation:
        return False


def _facturae_field(path: str) -> str | None:
    parties = {
        "/Facturae/Parties[1]/SellerParty[1]/TaxIdentification[1]/TaxIdentificationNumber[1]": "supplier_tax_id",
        "/Facturae/Parties[1]/BuyerParty[1]/TaxIdentification[1]/TaxIdentificationNumber[1]": "recipient_tax_id",
        "/Facturae/Parties[1]/SellerParty[1]/LegalEntity[1]/CorporateName[1]": "supplier_name",
        "/Facturae/Parties[1]/BuyerParty[1]/LegalEntity[1]/CorporateName[1]": "recipient_name",
    }
    if path in parties:
        return parties[path]
    if not path.startswith(_INVOICE + "/"):
        return None
    relative = path[len(_INVOICE) + 1:]
    header = {
        "InvoiceHeader[1]/InvoiceNumber[1]": "document_number",
        "InvoiceHeader[1]/InvoiceSeriesCode[1]": "raw.series",
        "InvoiceHeader[1]/InvoiceDocumentType[1]": "raw.invoice_document_type",
        "InvoiceHeader[1]/InvoiceClass[1]": "raw.invoice_class",
        "InvoiceIssueData[1]/IssueDate[1]": "document_date",
        "InvoiceIssueData[1]/InvoiceCurrencyCode[1]": "currency",
        "InvoiceIssueData[1]/InvoicingPeriod[1]/StartDate[1]": "period_start",
        "InvoiceIssueData[1]/InvoicingPeriod[1]/EndDate[1]": "period_end",
        "InvoiceTotals[1]/TotalGrossAmountBeforeTaxes[1]": "net",
        "InvoiceTotals[1]/TotalTaxOutputs[1]": "tax",
        "InvoiceTotals[1]/TotalTaxesWithheld[1]": "withholding",
        "InvoiceTotals[1]/InvoiceTotal[1]": "payable",
    }
    if relative in header:
        return header[relative]
    prefix = ""
    line = re.fullmatch(r"Items\[1\]/InvoiceLine\[(\d+)\]/(.+)", relative)
    if line:
        prefix, relative = f"line.{int(line[1])}.", line[2]
        fields = {"ItemDescription[1]": "description", "Quantity[1]": "quantity",
                  "UnitPriceWithoutTax[1]": "unit_price", "GrossAmount[1]": "amount"}
        if relative in fields:
            return prefix + fields[relative]
    tax = re.fullmatch(r"(TaxesOutputs|TaxesWithheld)\[1\]/Tax\[(\d+)\]/(.+)", relative)
    if tax:
        direction = "charge" if tax[1] == "TaxesOutputs" else "withheld"
        fields = {"TaxTypeCode[1]": "code", "TaxRate[1]": "tax_rate",
                  "TaxableBase[1]/TotalAmount[1]": "net",
                  "TaxAmount[1]/TotalAmount[1]": "tax" if direction == "charge" else "withholding"}
        field = fields.get(tax[3])
        return f"{prefix}tax.{direction}.{int(tax[2])}.{field}" if field else None
    payment = re.fullmatch(r"PaymentDetails\[1\]/Installment\[(\d+)\]/(.+)", relative)
    if payment:
        field = {"InstallmentDueDate[1]": "due_date", "InstallmentAmount[1]": "amount",
                 "PaymentMeans[1]": "means", "AccountToBeCredited[1]/IBAN[1]": "iban"}.get(payment[2])
        return f"payment.{int(payment[1])}.{field}" if field else None
    return None


def _cfdi_field(path: str, leaves: dict[str, Fact]) -> str | None:
    header = {
        "/Comprobante/@Folio": "document_number", "/Comprobante/@Serie": "raw.series",
        "/Comprobante/@Fecha": "document_date", "/Comprobante/@Moneda": "currency",
        "/Comprobante/@TipoDeComprobante": "raw.cfdi_type",
        "/Comprobante/@Total": "payable", "/Comprobante/@Descuento": "discount",
        "/Comprobante/Emisor[1]/@Rfc": "supplier_tax_id",
        "/Comprobante/Emisor[1]/@Nombre": "supplier_name",
        "/Comprobante/Receptor[1]/@Rfc": "recipient_tax_id",
        "/Comprobante/Receptor[1]/@Nombre": "recipient_name",
        "/Comprobante/Impuestos[1]/@TotalImpuestosTrasladados": "tax",
        "/Comprobante/Impuestos[1]/@TotalImpuestosRetenidos": "withholding",
        "/Comprobante/Complemento[1]/TimbreFiscalDigital[1]/@UUID": "raw.cfdi_uuid",
    }
    if path in header:
        return header[path]
    if path == "/Comprobante/@SubTotal" and _no_discount(leaves, "/Comprobante/@Descuento"):
        return "net"
    relative = path.removeprefix("/Comprobante/")
    prefix = ""
    line = re.fullmatch(r"Conceptos\[1\]/Concepto\[(\d+)\]/(.+)", relative)
    if line:
        prefix, relative = f"line.{int(line[1])}.", line[2]
        fields = {"@Cantidad": "quantity", "@ValorUnitario": "unit_price",
                  "@Descripcion": "description", "@Descuento": "discount"}
        if relative in fields:
            return prefix + fields[relative]
        if relative == "@Importe" and _no_discount(leaves, path.rsplit("/", 1)[0] + "/@Descuento"):
            return prefix + "net"
    tax = re.fullmatch(r"Impuestos\[1\]/(Traslados|Retenciones)\[1\]/(Traslado|Retencion)\[(\d+)\]/@(.+)", relative)
    if tax and (tax[1], tax[2]) in {("Traslados", "Traslado"), ("Retenciones", "Retencion")}:
        direction = "charge" if tax[1] == "Traslados" else "withheld"
        if tax[4] == "TasaOCuota":
            factor = leaves.get(path.rsplit("/", 1)[0] + "/@TipoFactor")
            if factor is None or factor.value != "Tasa":
                return None  # A fixed quota or exemption is not a fractional rate.
        field = {"Impuesto": "code", "Base": "net", "TasaOCuota": "tax_rate",
                 "TipoFactor": "factor", "Importe": "tax" if direction == "charge" else "withholding"}.get(tax[4])
        return f"{prefix}tax.{direction}.{int(tax[3])}.{field}" if field else None
    return None


class XMLDocumentExtractor:
    """Implement DocumentExtractor for supported parsed XML, one source at a time.

    All leaves remain under raw.xml.<exact locator>. Aliases keep the identical
    literal and evidence; no tax treatment, document type or monetary conversion
    is decided here. Unsupported versions/batches raise instead of guessing.
    """
    version = XML_EXTRACTOR_VERSION

    async def extract(self, document: ParsedDocument) -> DocumentFacts:
        root, leaves = _leaves(document)
        fields = {}
        for path, fact in sorted(leaves.items()):
            fields["raw.xml." + path] = [fact]
            name = _facturae_field(path) if root == "Facturae" else _cfdi_field(path, leaves)
            if name:
                fields.setdefault(name, []).append(fact)
        return DocumentFacts(document.source_sha256, self.version, fields)
