"""AP inbox extraction: message.json + PDF text (pypdf) + Facturae 3.2.2 XML + CFDI 4.0 XML -> one normalized dict.

Amounts are returned in integer cents, quantities as float. Prototype for research; read-only on the data.
"""
from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import date

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None

MONTHS = {
    # es / pt / en
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "janeiro": 1, "fevereiro": 2, "março": 3, "maio": 5, "junho": 6, "julho": 7, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def parse_date(s, style="es"):
    if not s:
        return None
    s = s.strip()
    if style == "en":
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
        if m:
            return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(r"(\d{1,2})\s+de\s+([a-zçáéíóú]+)\s+de\s+(\d{4})", s.lower())
    if m and m.group(2) in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"([a-z]+)\s+(\d{1,2}),?\s+(\d{4})", s.lower())
    if m and m.group(1) in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"
    return None


NUM_RE = re.compile(r"^[-−]?\s*(?:[$€]|EUR|USD|MXN|GBP)?\s*[-−]?\d[\d.,]*\s*(EUR|MXN|USD|GBP|€|\$)?$")


def is_num(tok):
    return bool(NUM_RE.match(tok.strip()))


def parse_num(tok, style="es"):
    """Return float or None. style 'es' (1.234,56) or 'en' (1,234.56)."""
    if tok is None:
        return None
    t = tok.strip().replace("−", "-")
    t = re.sub(r"(EUR|MXN|USD|GBP|€|\$|\s)", "", t)
    neg = t.startswith("-")
    t = t.lstrip("-")
    if not re.match(r"^\d[\d.,]*$", t):
        return None
    if "," in t and "." in t:
        dec = "," if t.rfind(",") > t.rfind(".") else "."
    elif "," in t:
        if style == "en" and re.match(r"^\d{1,3}(,\d{3})+$", t):
            dec = None
        else:
            dec = ","
    elif "." in t:
        if style != "en" and re.match(r"^\d{1,3}(\.\d{3})+$", t):
            dec = None
        else:
            dec = "."
    else:
        dec = None
    if dec is None:
        v = float(t.replace(",", "").replace(".", ""))
    else:
        th = "." if dec == "," else ","
        v = float(t.replace(th, "").replace(dec, "."))
    return -v if neg else v


def cents(x):
    return None if x is None else int(round(x * 100))


# ------------------------------------------------------------------ PDF
HEADER_LABELS = {
    "number": ["Nº Factura:", "Fatura N.º:", "Invoice No.:"],
    "date": ["Fecha:", "Data:", "Invoice Date:"],
    "due_date": ["Vencimiento:", "Vencimento:", "Due Date:"],
    "po": ["Su pedido:", "Pedido cliente:", "Nº pedido:", "PO:", "Ref. pedido:", "Pedido:", "S/Ref.:"],
    "period": ["Periodo:", "Período:", "Service period:"],
    "cert_no": ["Certificación nº:", "Auto de medição:"],
    "obra": ["Obra:"],
    "cups": ["CUPS:"],
    "contract": ["Contrato:"],
    "incoterm": ["Incoterm:"],
}
LABEL2FIELD = {l: f for f, ls in HEADER_LABELS.items() for l in ls}
BUYER_MARKERS = ("FACTURAR A", "FATURAR A", "BILL TO")
TABLE_START = ("Código", "Descripción", "Descrição", "Item", "Description")
TABLE_COLS = {"Código", "Descripción", "Descrição", "Item", "Description", "Cant.", "Qtd.", "Qty", "Ud.", "Un.", "Unit",
              "Precio", "Preço", "Unit Price", "Importe", "Valor", "Amount"}
TOTALS_START = re.compile(r"^(Certificado a origen|Base imponible|Incidência|Subtotal)\b")
TAXID_RE = re.compile(r"^(?:NIF|Tax ID|NIPC|RFC)\s*:?\s*([A-Z0-9][A-Z0-9\-]{5,20})\s*$")
IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}[A-Z0-9]{10,30})\b")
DOCREF_RE = re.compile(r"\b((?:AL|GR|REM|ALB|SES|HS)-\d{4,})\b")
PO_RE = re.compile(r"\b(45\d{8})\b")


def pdf_text_pages(path):
    r = PdfReader(path)
    return [p.extract_text() or "" for p in r.pages]


def clean_lines(text):
    out = []
    for l in text.split("\n"):
        l = l.strip()
        if not l:
            continue
        if l.startswith("Synthetic test document") or re.match(r"^(Página|Page)\s+\d+$", l):
            continue
        out.append(l)
    return out


def parse_invoice_pdf(pages):
    """Parse the first page of a ReportLab invoice (es/pt/en). Returns dict with header, lines, totals."""
    full = "\n".join(pages)
    lines = clean_lines(pages[0]) if pages else []
    style = "en" if any(l in ("Invoice No.:", "BILL TO") for l in lines) else "es"
    d = {"style": style, "lines": [], "taxes": [], "withholdings": [], "po_refs": [], "doc_refs": [], "notes": []}
    # title: first all-caps line among known titles
    for l in lines[:15]:
        if l in ("FACTURA", "FATURA", "INVOICE", "FACTURA RECTIFICATIVA", "NOTA DE CRÉDITO", "RECIBO DE ARRENDAMIENTO",
                 "RECIBO DE PRIMA", "LIQUIDACIÓN MENSUAL", "CREDIT NOTE") or "PROFORMA" in l or "DEPOSIT" in l:
            d["title"] = l
            break
    # header label/value pairs
    i_buyer = next((i for i, l in enumerate(lines) if l in BUYER_MARKERS), None)
    for i, l in enumerate(lines):
        f = LABEL2FIELD.get(l)
        if f and i + 1 < len(lines) and f not in d:
            d[f] = lines[i + 1]
    # vendor tax id: first tax-id line before buyer block
    vend_block = lines[: i_buyer if i_buyer is not None else 10]
    for l in vend_block:
        m = TAXID_RE.match(l)
        if m:
            d["vendor_tax_id"] = m.group(1)
            break
    d["vendor_name"] = next((l for l in vend_block[:3] if len(l) > 3 and not TAXID_RE.match(l)), None)
    # vendor name = longest of first 2 lines (first line is a logo abbreviation / truncated name)
    if len(vend_block) >= 2:
        d["vendor_name"] = max(vend_block[:2], key=len)
    # buyer block
    if i_buyer is not None:
        d["buyer_name"] = lines[i_buyer + 1] if i_buyer + 1 < len(lines) else None
        j = i_buyer + 1
        while j < len(lines) and lines[j] not in TABLE_START:
            m = TAXID_RE.match(lines[j])
            if m:
                d["buyer_tax_id"] = m.group(1)
                break
            j += 1
    # table
    i_tab = None
    if i_buyer is not None:
        for j in range(i_buyer, len(lines)):
            if lines[j] in TABLE_START:
                i_tab = j
                break
    i_tot = next((j for j in range(i_tab or 0, len(lines)) if TOTALS_START.match(lines[j])), None) if i_tab is not None else None
    if i_tab is not None and i_tot is not None:
        cols = []
        j = i_tab
        while j < i_tot and lines[j] in TABLE_COLS:
            cols.append(lines[j])
            j += 1
        d["table_cols"] = cols
        d["lines"] = parse_rows(lines[j:i_tot], cols, style)
    # totals block
    if i_tot is not None:
        parse_totals(lines[i_tot:], d, style)
    # iban
    for l in lines:
        if re.search(r"(transferencia a|IBAN|bank details)", l, re.I):
            m = IBAN_RE.search(l.replace(" ", ""))
            if m:
                d["iban"] = m.group(1)
            else:
                m2 = re.search(r"[–-]\s*(\d{10,20})\s*$", l)  # CLABE / account number
                if m2:
                    d["iban"] = m2.group(1)
    d["po_refs"] = sorted(set(PO_RE.findall(full)))
    d["doc_refs"] = sorted(set(DOCREF_RE.findall(full)))
    m = re.search(r"Rectifica la factura n[ºo°]\s*([^\s.]+(?:\.[^\s]+)?)\.?\s*Motivo:\s*([^.]+)", full)
    if m:
        d["corrects"] = m.group(1).rstrip(".")
        d["correction_reason"] = m.group(2).strip()
    d["isp_legend"] = bool(re.search(r"inversión del sujeto pasivo|autoliquidação|Reverse charge", full))
    d["exempt_legend"] = bool(re.search(r"exenta|exento|no sujeto|isento", full, re.I))
    d["has_timesheet"] = "PARTE DE TRABAJO" in full
    d["date_iso"] = parse_date(d.get("date"), style)
    d["due_iso"] = parse_date(d.get("due_date"), style)
    return d


UNIT_MAX = 8


def parse_rows(rows, cols, style):
    has_code = "Código" in cols
    has_qty = any(c in cols for c in ("Cant.", "Qtd.", "Qty"))
    out = []
    i = 0
    n = len(rows)
    while i < n:
        row = {"code": None, "desc": "", "qty": None, "unit": None, "price": None, "amount": None}
        if has_code and i + 1 < n and re.match(r"^[A-Z0-9][A-Z0-9\-/]{1,15}$", rows[i]) and not is_num(rows[i]):
            row["code"] = rows[i]
            i += 1
        desc = []
        while i < n and not is_num(rows[i]):
            desc.append(rows[i])
            i += 1
        row["desc"] = " ".join(desc)
        nums = []
        unit = None
        while i < n:
            if is_num(rows[i]):
                nums.append(rows[i])
                i += 1
            elif nums and unit is None and len(nums) == 1 and len(rows[i]) <= UNIT_MAX and has_qty and not re.search(r"\s", rows[i]):
                unit = rows[i]
                i += 1
            else:
                break
        if not nums:
            break
        vals = [parse_num(x, style) for x in nums]
        row["amount"] = cents(vals[-1])
        if len(vals) >= 3:
            row["qty"], row["price"] = vals[0], vals[1]
        elif len(vals) == 2 and unit:
            row["qty"] = vals[0]
        elif len(vals) == 2:
            row["qty"], row["price"] = None, vals[0]
        row["unit"] = unit
        mref = DOCREF_RE.search(row["desc"])
        row["doc_ref"] = mref.group(1) if mref else None
        out.append(row)
    return out


def parse_totals(lines, d, style):
    i = 0
    while i < len(lines):
        l = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        v = cents(parse_num(nxt, style)) if nxt is not None and is_num(nxt) else None
        if l.startswith("Certificado a origen"):
            d["cert_origen"] = v
        elif l.startswith("Certificado anterior"):
            d["cert_anterior"] = v
        elif l.startswith("Importe de esta certificación"):
            d["cert_esta"] = v
        elif re.match(r"^(Base imponible|Incidência|Subtotal)$", l):
            d["net"] = v
        elif re.match(r"^(IVA|VAT|IGIC)\b", l):
            m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", l)
            rate = parse_num(m.group(1), "es") if m else None
            mb = re.search(r"s/\s*(-?[\d.,]+)", l)
            base = cents(parse_num(mb.group(1), style)) if mb else None
            d["taxes"].append({"label": l, "rate": rate, "base": base, "amount": v,
                               "isp": bool(re.search(r"ISP|autoliquida", l))})
        elif re.match(r"^(TOTAL FACTURA|TOTAL)$", l):
            d["gross"] = v
            m = re.search(r"(EUR|MXN|USD|GBP)", nxt or "")
            if "$" in (nxt or "") and not m:
                d["currency"] = "USD"
            elif m:
                d["currency"] = m.group(1)
        elif re.match(r"^(Retención|Retenção|Withholding)", l):
            m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", l)
            rate = parse_num(m.group(1), "es") if m else None
            kind = "guarantee" if re.search(r"garant", l, re.I) or re.match(r"^Retenção\s+\d", l) else "tax"
            d["withholdings"].append({"label": l, "rate": rate, "amount": v, "kind": kind})
        elif l.startswith("Total a pagar") or l.startswith("Amount due"):
            d["payable"] = v
        else:
            i += 1
            continue
        i += 2


# ------------------------------------------------------------------ XML
def _t(e, path):
    x = e.find(path)
    return x.text.strip() if x is not None and x.text else None


def parse_facturae(path):
    root = ET.parse(path).getroot()
    for el in root.iter():  # strip namespaces
        el.tag = el.tag.split("}")[-1]
    inv = root.find("Invoices/Invoice")
    d = {"format": "facturae", "lines": [], "taxes": [], "withholdings": []}
    d["vendor_tax_id"] = _t(root, "Parties/SellerParty/TaxIdentification/TaxIdentificationNumber")
    d["vendor_name"] = _t(root, "Parties/SellerParty/LegalEntity/CorporateName") or _t(root, "Parties/SellerParty/Individual/Name")
    d["buyer_tax_id"] = _t(root, "Parties/BuyerParty/TaxIdentification/TaxIdentificationNumber")
    d["buyer_name"] = _t(root, "Parties/BuyerParty/LegalEntity/CorporateName")
    d["number"] = _t(inv, "InvoiceHeader/InvoiceNumber")
    d["series"] = _t(inv, "InvoiceHeader/InvoiceSeriesCode")
    d["doc_type"] = _t(inv, "InvoiceHeader/InvoiceDocumentType")
    d["invoice_class"] = _t(inv, "InvoiceHeader/InvoiceClass")
    if inv.find("InvoiceHeader/Corrective") is not None:
        d["corrects"] = _t(inv, "InvoiceHeader/Corrective/InvoiceNumber")
        d["correction_reason"] = _t(inv, "InvoiceHeader/Corrective/ReasonDescription")
    d["date"] = _t(inv, "InvoiceIssueData/IssueDate")
    d["date_iso"] = d["date"]
    d["period"] = (_t(inv, "InvoiceIssueData/InvoicingPeriod/StartDate"), _t(inv, "InvoiceIssueData/InvoicingPeriod/EndDate"))
    d["currency"] = _t(inv, "InvoiceIssueData/InvoiceCurrencyCode")
    for tax in inv.findall("TaxesOutputs/Tax"):
        d["taxes"].append({"label": "IVA", "rate": float(_t(tax, "TaxRate") or 0), "base": cents(float(_t(tax, "TaxableBase/TotalAmount") or 0)),
                           "amount": cents(float(_t(tax, "TaxAmount/TotalAmount") or 0)), "isp": False})
    for tax in inv.findall("TaxesWithheld/Tax"):
        d["withholdings"].append({"label": "IRPF", "rate": float(_t(tax, "TaxRate") or 0), "amount": cents(float(_t(tax, "TaxAmount/TotalAmount") or 0)), "kind": "tax"})
    tot = inv.find("InvoiceTotals")
    d["net"] = cents(float(_t(tot, "TotalGrossAmountBeforeTaxes") or 0))
    d["tax_total"] = cents(float(_t(tot, "TotalTaxOutputs") or 0))
    d["withheld_total"] = cents(float(_t(tot, "TotalTaxesWithheld") or 0))
    d["gross"] = cents(float(_t(tot, "InvoiceTotal") or 0))
    d["payable"] = cents(float(_t(tot, "TotalExecutableAmount") or 0))
    for aw in tot.findall("AmountsWithheld"):
        d["withholdings"].append({"label": _t(aw, "WithholdingReason"), "rate": None, "amount": cents(float(_t(aw, "WithholdingAmount") or 0)),
                                  "kind": "guarantee" if "garant" in (_t(aw, "WithholdingReason") or "").lower() else "tax"})
    for ln in inv.findall("Items/InvoiceLine"):
        desc = _t(ln, "ItemDescription") or ""
        mref = DOCREF_RE.search(desc)
        d["lines"].append({"code": _t(ln, "ArticleCode"), "desc": desc, "qty": float(_t(ln, "Quantity") or 0),
                           "price": float(_t(ln, "UnitPriceWithoutTax") or 0), "amount": cents(float(_t(ln, "TotalCost") or 0)),
                           "po": _t(ln, "IssuerTransactionReference") or _t(ln, "ReceiverTransactionReference"),
                           "doc_ref": mref.group(1) if mref else None,
                           "line_tax_rate": float(_t(ln, "TaxesOutputs/Tax/TaxRate") or 0)})
    info = _t(inv, "AdditionalData/InvoiceAdditionalInformation") or ""
    d["notes"] = [info] if info else []
    d["isp_legend"] = "inversión del sujeto pasivo" in info
    d["exempt_legend"] = bool(re.search(r"exenta|no sujeto|REAV|agencias de viajes", info, re.I))
    d["po_refs"] = sorted({l["po"] for l in d["lines"] if l.get("po")} | set(PO_RE.findall(ET.tostring(root, encoding="unicode"))))
    d["doc_refs"] = sorted({l["doc_ref"] for l in d["lines"] if l.get("doc_ref")})
    iban = None
    for el in root.iter():
        if el.tag in ("IBAN", "AccountToBeCredited") and el.text:
            iban = el.text.strip()
    d["iban"] = iban
    return d


def parse_cfdi(path):
    root = ET.parse(path).getroot()
    ns = lambda tag: [e for e in root.iter() if e.tag.split("}")[-1] == tag]
    a = root.attrib
    d = {"format": "cfdi", "lines": [], "taxes": [], "withholdings": []}
    em, rc = ns("Emisor")[0].attrib, ns("Receptor")[0].attrib
    d["vendor_tax_id"], d["vendor_name"] = em.get("Rfc"), em.get("Nombre")
    d["buyer_tax_id"], d["buyer_name"] = rc.get("Rfc"), rc.get("Nombre")
    d["series"], d["number"] = a.get("Serie"), a.get("Folio")
    d["date"] = parse_date(a.get("Fecha"))
    d["date_iso"] = d["date"]
    d["currency"] = a.get("Moneda")
    d["doc_type"] = a.get("TipoDeComprobante")  # I ingreso, E egreso (nota de crédito), P pago
    d["net"] = cents(float(a.get("SubTotal", 0)))
    d["gross"] = cents(float(a.get("Total", 0)))
    d["discount"] = cents(float(a.get("Descuento", 0)))
    for c in ns("Concepto"):
        ca = c.attrib
        d["lines"].append({"code": ca.get("ClaveProdServ"), "desc": ca.get("Descripcion"), "qty": float(ca.get("Cantidad", 0)),
                           "price": float(ca.get("ValorUnitario", 0)), "amount": cents(float(ca.get("Importe", 0)))})
    imp = [e for e in ns("Impuestos") if "TotalImpuestosTrasladados" in e.attrib or "TotalImpuestosRetenidos" in e.attrib]
    for t in ns("Traslado"):
        ta = t.attrib
        if "Base" in ta and t in list(imp[0].iter()) if imp else True:
            d["taxes"].append({"label": "IVA", "rate": float(ta.get("TasaOCuota", 0)) * 100, "base": cents(float(ta.get("Base", 0))),
                               "amount": cents(float(ta.get("Importe", 0))), "isp": False})
    for t in ns("Retencion"):
        ta = t.attrib
        if "Importe" in ta:
            d["withholdings"].append({"label": {"001": "ISR", "002": "IVA"}.get(ta.get("Impuesto"), ta.get("Impuesto")),
                                      "rate": None, "amount": cents(float(ta["Importe"])), "kind": "tax"})
    tfd = ns("TimbreFiscalDigital")
    d["uuid"] = tfd[0].attrib.get("UUID") if tfd else None
    d["po_refs"], d["doc_refs"] = [], []
    return d


# ------------------------------------------------------------------ document
def kind_from_filename(a):
    a = a.lower()
    for k in ("certificate_art43", "proforma", "statement", "letter_cession", "letter_bank_change", "letter_embargo", "dua", "facturae", "factura", "invoice"):
        if a.startswith(k):
            return k
    if a.endswith(".xml"):
        return "cfdi_xml"
    return "other"


def number_from_filename(a):
    m = re.match(r"^(?:factura|invoice|facturae)_(.+)\.(pdf|xml)$", a, re.I)
    return m.group(1) if m else None


def load_doc(inbox_dir, doc_id, text_cache=None):
    p = os.path.join(inbox_dir, doc_id)
    m = json.load(open(os.path.join(p, "message.json"), encoding="utf-8"))
    doc = {"doc_id": doc_id, "channel": m["channel"], "received_at": m["received_at"], "received_on": m["received_at"][:10],
           "from": m.get("from"), "subject": m.get("subject") or "", "body": m.get("body") or "", "uploaded_by": m.get("uploaded_by"),
           "source": m.get("source"), "attachments": m["attachments"]}
    sender = doc["from"] or doc["uploaded_by"]
    doc["sender_domain"] = sender.split("@")[-1].lower() if sender else None
    doc["att_kinds"] = [kind_from_filename(a) for a in m["attachments"]]
    doc["pdf"], doc["xml"], doc["pdf_texts"] = {}, None, {}
    for a in m["attachments"]:
        fp = os.path.join(p, a)
        k = kind_from_filename(a)
        if a.lower().endswith(".pdf"):
            pages = text_cache[doc_id][a] if text_cache and doc_id in text_cache and a in text_cache[doc_id] else pdf_text_pages(fp)
            doc["pdf_texts"][a] = pages
            if k in ("factura", "invoice", "facturae"):
                doc["pdf"] = parse_invoice_pdf(pages) if "".join(pages).strip() else {"scan": True}
                doc["pdf"]["filename_number"] = number_from_filename(a)
        elif a.lower().endswith(".xml"):
            if k == "facturae":
                doc["xml"] = parse_facturae(fp)
            else:
                doc["xml"] = parse_cfdi(fp)
    doc["text"] = "\n".join("\n".join(pg) for pg in doc["pdf_texts"].values())
    doc["is_scan"] = bool(doc["pdf_texts"]) and not doc["text"].strip() and doc["xml"] is None
    # primary structured source: Facturae XML > PDF; for CFDI both are kept (PDF primary, XML compared)
    if doc["channel"] == "facturae" and doc["xml"]:
        doc["inv"] = doc["xml"]
    else:
        doc["inv"] = doc["pdf"] or {}
    inv = doc["inv"]
    # ambiguous NN/NN/YYYY dates (US vendors write MM/DD): take the reading closest before reception
    raw = inv.get("date") or ""
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", raw.strip())
    if m and int(m.group(1)) <= 12 and int(m.group(2)) <= 12:
        a, b, y = int(m.group(1)), int(m.group(2)), m.group(3)
        cands = [f"{y}-{b:02d}-{a:02d}", f"{y}-{a:02d}-{b:02d}"]
        before = [c for c in cands if c <= doc["received_on"]]
        inv["date_iso"] = max(before) if before else min(cands)
    return doc
