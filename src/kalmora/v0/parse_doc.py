"""Parse an AP inbox document (PDF text / Facturae XML / CFDI XML) into a normalized dict.

All amounts returned in integer cents of the DOCUMENT currency, signed as printed.
"""
import json
import os
import re
import xml.etree.ElementTree as ET
from functools import lru_cache

from pypdf import PdfReader

NUM_RE = re.compile(r"^[-−]?\$?\s?[-−]?[0-9][0-9.,]*$")
DATE_RES = [
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})"), "ymd"),
    (re.compile(r"^(\d{2})[/.-](\d{2})[/.-](\d{4})"), "dmy"),
]


def to_cents(s, english=False):
    s = s.strip().replace("−", "-").replace("$", "").replace("€", "").replace("EUR", "").replace("USD", "").replace("MXN", "").replace(" ", "")
    neg = s.startswith("-")
    s = s.lstrip("-")
    if not s:
        return None
    if re.search(r"[.,]\d{2}$", s):  # amount with 2 decimals: last separator is decimal
        dec = s[-3]
        s = s[:-3].replace(".", "").replace(",", "") + "." + s[-2:]
    elif english:
        s = s.replace(",", "")
    else:
        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        elif "." in s:
            # spanish thousands separator only if groups of 3
            parts = s.split(".")
            if all(len(p) == 3 for p in parts[1:]):
                s = s.replace(".", "")
    try:
        v = round(float(s) * 100)
    except ValueError:
        return None
    return -v if neg else v


def to_milli(s, english=False):
    c = to_cents(s, english)
    return None if c is None else c * 10


MONTHS = {m: i + 1 for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"])}
MONTHS.update({m: i + 1 for i, m in enumerate(["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"])})
MONTHS.update({m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])})


def parse_date(s, english=False, ref=None):
    """ref: YYYY-MM-DD reception date used to disambiguate dd/mm vs mm/dd."""
    s = s.strip()
    m = re.match(r"^(\d{1,2}) de ([a-zçé]+) de (\d{4})", s.lower())
    if m and m.group(2) in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    m = re.match(r"^([a-z]+) (\d{1,2}),? (\d{4})", s.lower())
    if m and m.group(1) in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", s)
    if m and ref:
        a, b, y = m.groups()
        cands = []
        if int(b) <= 12:
            cands.append(f"{y}-{b}-{a}")
        if int(a) <= 12:
            cands.append(f"{y}-{a}-{b}")
        ok = [c for c in cands if c <= ref]
        if ok:
            return max(ok)
        if cands:
            return min(cands)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{2})[/.-](\d{2})[/.-](\d{4})", s)
    if m:
        a, b, y = m.groups()
        if english and "/" in s:  # US format MM/DD/YYYY
            return f"{y}-{a}-{b}"
        return f"{y}-{b}-{a}"
    return None


def is_num(s):
    s = s.strip()
    if not s or not NUM_RE.match(s.replace(" EUR", "").replace(" USD", "").replace(" MXN", "")):
        return False
    return any(ch.isdigit() for ch in s)


@lru_cache(maxsize=None)
def pdf_text(path):
    r = PdfReader(path)
    return "\n".join(p.extract_text() or "" for p in r.pages)


HEADER_LABELS = {
    "number": ["Nº Factura:", "Invoice No.:", "Fatura N.º:", "Nº Abono:", "Credit Note No.:"],
    "date": ["Fecha:", "Invoice Date:", "Data:"],
    "due": ["Vencimiento:", "Due Date:", "Vencimento:"],
    "period": ["Periodo:", "Período:", "Service period:"],
    "po": ["Su pedido:", "S/Ref.:", "Pedido:", "Ref. pedido:", "Nº pedido:", "PO:", "Pedido cliente:", "Your PO:", "Encomenda:"],
    "cert": ["Certificación nº:", "Auto de medição:"],
    "obra": ["Obra:", "Obra / centro:"],
    "contract": ["Contrato:"],
    "cups": ["CUPS:"],
}
TABLE_HEADS = {"Descripción", "Description", "Descrição", "Item", "Concepto"}
COL_HEADS = {"Cant.", "Ud.", "Precio", "Importe", "Qty", "Unit", "Unit Price", "Amount", "Qtd.", "Un.", "Preço", "Valor", "Description", "Descripción", "Descrição"}
TOTAL_START = re.compile(r"^(Base imponible|Subtotal|Incidência|Certificado a origen|Base imponible:)")


def parse_pdf_text(txt):
    L = [l.strip() for l in txt.split("\n")]
    L = [l for l in L if l != ""]
    english = any(l in ("INVOICE", "Invoice No.:", "BILL TO") or l.startswith("PROFORMA INVOICE") or l == "CREDIT NOTE" for l in L[:40])
    d = {"format": "pdf", "english": english, "raw_lines": L}
    # seller: first NIF/Tax ID line before the title
    title_idx = None
    for i, l in enumerate(L[:20]):
        if re.match(r"^(FACTURA|INVOICE|FATURA|RECIBO|NOTA|ABONO|PROFORMA|CREDIT|PRO FORMA|OFERTA|PRESUPUESTO|EXTRACTO|STATEMENT)", l):
            title_idx = i
            break
    d["title"] = L[title_idx] if title_idx is not None else None
    seller_block = L[: title_idx if title_idx is not None else 8]
    d["seller_name"] = seller_block[1] if len(seller_block) > 1 else None
    for l in seller_block:
        m = re.match(r"^(NIF|Tax ID|CIF|RFC|NIPC|VAT)[:.]?\s*(\S+)", l)
        if m:
            d["seller_tax_id"] = m.group(2)
    # key/value labels
    for i, l in enumerate(L[:80]):
        ls = l.strip()
        for k, labels in HEADER_LABELS.items():
            if ls in labels and i + 1 < len(L) and k not in d:
                d[k] = L[i + 1]
                d.setdefault("label_" + k, ls)
    # buyer block
    for i, l in enumerate(L):
        if l in ("FACTURAR A", "BILL TO", "FATURAR A", "CLIENTE", "ADQUIRENTE"):
            for j in range(i + 1, min(i + 8, len(L))):
                m = re.match(r"^(NIF|Tax ID|CIF|RFC|NIPC|VAT)[:.]?\s*(\S+)", L[j])
                if m:
                    d["buyer_tax_id"] = m.group(2)
                    break
            d["buyer_name"] = L[i + 1] if i + 1 < len(L) else None
            break
    # table
    start = None
    for i, l in enumerate(L):
        if l in TABLE_HEADS and i > 5:
            start = i
            break
    rows = []
    totals = {}
    if start is not None:
        j = start
        heads = []
        while j < len(L) and (L[j] in COL_HEADS or L[j] in TABLE_HEADS):
            heads.append(L[j])
            j += 1
        d["table_heads"] = heads
        cur = None
        while j < len(L) and not TOTAL_START.match(L[j]):
            l = L[j]
            if is_num(l) and re.fullmatch(r"(19|20)\d\d", l) and cur is not None and not cur["nums"] and j + 1 < len(L) and is_num(L[j + 1]):
                cur["desc"] += " " + l  # wrapped description ending in a year
            elif is_num(l):
                if cur is None:
                    cur = {"desc": "", "nums": [], "unit": None}
                    rows.append(cur)
                cur["nums"].append(l)
            elif cur is not None and len(cur["nums"]) == 1 and len(l) <= 8 and " " not in l and cur["unit"] is None:
                cur["unit"] = l
            elif cur is not None and not cur["nums"]:
                cur["desc"] += " " + l
            else:
                cur = {"desc": l, "nums": [], "unit": None}
                rows.append(cur)
            j += 1
        # totals block
        tl = L[j:]
        d["totals_lines"] = tl
    lines = []
    for r in rows:
        nums = [to_cents(x, english) for x in r["nums"]]
        if not nums:
            continue
        amt = nums[-1]
        qty = None
        price = None
        if len(nums) >= 3:
            qty = to_milli(r["nums"][0], english)
            price = nums[-2]
        elif len(nums) == 2:
            qty = to_milli(r["nums"][0], english)
        lines.append({"desc": r["desc"].strip(), "qty_milli": qty, "unit": r["unit"], "price": price, "amount": amt})
    d["lines"] = lines
    # totals parse
    tl = d.get("totals_lines", [])
    taxes = []
    wht = []
    ret = 0
    i = 0
    while i < len(tl):
        l = tl[i]
        nxt = tl[i + 1] if i + 1 < len(tl) else ""
        if l.startswith("Base imponible:") and "Total:" in l:  # one-line summary
            m = re.findall(r"([-0-9.,]+) EUR", l)
            i += 1
            continue
        if re.match(r"^(Base imponible|Subtotal|Incidência)$", l):
            totals["net"] = to_cents(nxt, english)
            i += 2
            continue
        if l == "Certificado a origen":
            totals["cert_origin"] = to_cents(nxt, english); i += 2; continue
        if l == "Certificado anterior":
            totals["cert_prev"] = to_cents(nxt, english); i += 2; continue
        if l == "Importe de esta certificación":
            totals["cert_this"] = to_cents(nxt, english); i += 2; continue
        m = re.match(r"^(IVA|VAT|IGIC)\b(.*)$", l)
        if m and is_num(nxt):
            rate = re.search(r"(\d+(?:[.,]\d+)?)\s*%", l)
            taxes.append({"label": l, "rate": float(rate.group(1).replace(",", ".")) if rate else None, "amount": to_cents(nxt, english)})
            i += 2
            continue
        if re.match(r"^(TOTAL FACTURA|TOTAL)$", l):
            totals["gross"] = to_cents(nxt, english)
            i += 2
            continue
        if re.match(r"^(Retención garantía|Retenção \d|Retención de garantía|Retenção de garantia)", l):
            ret += abs(to_cents(nxt, english) or 0)
            i += 2
            continue
        if re.match(r"^(Retención|Retenção|Withholding)", l) and is_num(nxt):
            rate = re.search(r"(\d+(?:[.,]\d+)?)\s*%", l)
            wht.append({"label": l, "rate": float(rate.group(1).replace(",", ".")) if rate else None, "amount": abs(to_cents(nxt, english) or 0)})
            i += 2
            continue
        if re.match(r"^(Total a pagar|Total a pagar:|Amount due|Total liquidado)", l):
            totals["payable"] = to_cents(nxt, english)
            i += 2
            continue
        i += 1
    d["taxes"] = taxes
    d["withholdings"] = wht
    d["retention"] = ret
    d.update(totals)
    return d


def parse_facturae(path):
    t = ET.parse(path).getroot()
    def f(p):
        e = t.find(p)
        return e.text.strip() if e is not None and e.text else None
    d = {"format": "facturae"}
    d["seller_tax_id"] = f(".//SellerParty/TaxIdentification/TaxIdentificationNumber")
    d["seller_name"] = f(".//SellerParty//CorporateName") or f(".//SellerParty//Name")
    d["buyer_tax_id"] = f(".//BuyerParty/TaxIdentification/TaxIdentificationNumber")
    d["buyer_name"] = f(".//BuyerParty//CorporateName")
    inv = t.find(".//Invoices/Invoice")
    d["number"] = f(".//InvoiceHeader/InvoiceNumber")
    d["series"] = f(".//InvoiceHeader/InvoiceSeriesCode")
    d["doc_class"] = f(".//InvoiceHeader/InvoiceClass")
    d["corrective_of"] = f(".//InvoiceHeader/Corrective/InvoiceNumber")
    d["date"] = f(".//InvoiceIssueData/IssueDate")
    d["period"] = (f(".//InvoicingPeriod/StartDate") or "") + " – " + (f(".//InvoicingPeriod/EndDate") or "")
    d["currency"] = f(".//InvoiceIssueData/InvoiceCurrencyCode")
    c = lambda x: None if x is None else round(float(x) * 100)
    d["net"] = c(f(".//InvoiceTotals/TotalGrossAmountBeforeTaxes"))
    d["tax_total"] = c(f(".//InvoiceTotals/TotalTaxOutputs"))
    d["wht_total"] = c(f(".//InvoiceTotals/TotalTaxesWithheld"))
    d["gross"] = c(f(".//InvoiceTotals/InvoiceTotal"))
    d["payable"] = c(f(".//InvoiceTotals/TotalExecutableAmount"))
    d["taxes"] = []
    for tx in t.findall(".//Invoice/TaxesOutputs/Tax"):
        d["taxes"].append({"rate": float(tx.findtext("TaxRate")), "base": c(tx.findtext("TaxableBase/TotalAmount")), "amount": c(tx.findtext("TaxAmount/TotalAmount"))})
    d["withholdings"] = []
    for tx in t.findall(".//Invoice/TaxesWithheld/Tax"):
        d["withholdings"].append({"rate": float(tx.findtext("TaxRate")), "base": c(tx.findtext("TaxableBase/TotalAmount")), "amount": c(tx.findtext("TaxAmount/TotalAmount"))})
    # retention (garantía) may be in PaymentsOnAccount / AmountsWithheld
    aw = t.find(".//InvoiceTotals/AmountsWithheld")
    d["retention"] = c(aw.findtext("WithholdingAmount")) if aw is not None else 0
    d["po"] = f(".//Items/InvoiceLine/IssuerTransactionReference") or f(".//Items/InvoiceLine/ReceiverTransactionReference")
    d["lines"] = []
    for il in t.findall(".//Items/InvoiceLine"):
        d["lines"].append({
            "desc": il.findtext("ItemDescription"),
            "qty_milli": round(float(il.findtext("Quantity") or 0) * 1000),
            "price": c(il.findtext("UnitPriceWithoutTax")),
            "amount": c(il.findtext("GrossAmount") or il.findtext("TotalCost")),
            "tax_rate": float(il.findtext("TaxesOutputs/Tax/TaxRate") or 0),
            "po": il.findtext("ReceiverTransactionReference") or il.findtext("IssuerTransactionReference"),
            "delivery_note": il.findtext("DeliveryNotesReferences/DeliveryNote/DeliveryNoteNumber"),
        })
    d["additional_info"] = f(".//AdditionalData/InvoiceAdditionalInformation")
    d["raw"] = open(path, encoding="utf-8").read()
    return d


def parse_cfdi(path):
    ns = {"cfdi": "http://www.sat.gob.mx/cfd/4", "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital"}
    t = ET.parse(path).getroot()
    a = t.attrib
    c = lambda x: None if x is None else round(float(x) * 100)
    d = {"format": "cfdi"}
    d["number"] = a.get("Folio")
    d["series"] = a.get("Serie")
    d["date"] = a.get("Fecha", "")[:10]
    d["currency"] = a.get("Moneda")
    d["net"] = c(a.get("SubTotal"))
    d["gross_cfdi_total"] = c(a.get("Total"))
    d["tipo"] = a.get("TipoDeComprobante")
    em = t.find("cfdi:Emisor", ns)
    re_ = t.find("cfdi:Receptor", ns)
    d["seller_tax_id"] = em.get("Rfc")
    d["seller_name"] = em.get("Nombre")
    d["buyer_tax_id"] = re_.get("Rfc")
    d["lines"] = []
    for cc in t.findall("cfdi:Conceptos/cfdi:Concepto", ns):
        d["lines"].append({"desc": cc.get("Descripcion"), "qty_milli": round(float(cc.get("Cantidad")) * 1000), "price": c(cc.get("ValorUnitario")), "amount": c(cc.get("Importe"))})
    imp = t.find("cfdi:Impuestos", ns)
    d["taxes"] = []
    d["withholdings"] = []
    if imp is not None:
        for tr in imp.findall("cfdi:Traslados/cfdi:Traslado", ns):
            d["taxes"].append({"rate": float(tr.get("TasaOCuota") or 0) * 100, "base": c(tr.get("Base")), "amount": c(tr.get("Importe"))})
        for rt in imp.findall("cfdi:Retenciones/cfdi:Retencion", ns):
            d["withholdings"].append({"impuesto": rt.get("Impuesto"), "amount": c(rt.get("Importe"))})
    rel = t.find("cfdi:CfdiRelacionados", ns)
    if rel is not None:
        d["related"] = [x.get("UUID") for x in rel.findall("cfdi:CfdiRelacionado", ns)]
        d["relation_type"] = rel.get("TipoRelacion")
    tfd = t.find(".//tfd:TimbreFiscalDigital", ns)
    d["uuid"] = tfd.get("UUID") if tfd is not None else None
    return d


def parse_doc_dir(ddir):
    msg = json.load(open(os.path.join(ddir, "message.json"), encoding="utf-8"))
    files = sorted(os.listdir(ddir))
    out = {"doc_id": msg["doc_id"], "message": msg, "files": files}
    pdfs = [f for f in files if f.endswith(".pdf")]
    xmls = [f for f in files if f.endswith(".xml")]
    fe = [f for f in xmls if "facturae" in open(os.path.join(ddir, f), encoding="utf-8").read(400).lower()]
    cf = [f for f in xmls if "cfdi:Comprobante" in open(os.path.join(ddir, f), encoding="utf-8").read(400)]
    out["pdf"] = [dict(parse_pdf_text(pdf_text(os.path.join(ddir, p))), file=p) for p in pdfs]
    out["facturae"] = parse_facturae(os.path.join(ddir, fe[0])) if fe else None
    out["cfdi"] = parse_cfdi(os.path.join(ddir, cf[0])) if cf else None
    out["other_xml"] = [f for f in xmls if f not in fe and f not in cf]
    return out
