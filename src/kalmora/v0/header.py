"""Header extraction: company, vendor, number, date, currency, amounts."""
import re
from .kb import norm_id

CUR_HINT = [("$", "USD"), ("USD", "USD"), ("£", "GBP"), ("GBP", "GBP"), ("MXN", "MXN"), ("EUR", "EUR"), ("€", "EUR")]


def pick_source(doc):
    """Primary structured source: Facturae > CFDI > first invoice-looking PDF."""
    if doc.get("facturae"):
        return doc["facturae"]
    if doc.get("cfdi"):
        return doc["cfdi"]
    pdfs = sorted(doc["pdf"], key=lambda p: (0 if re.match(r"(factura|invoice|fatura)", p.get("file", ""), re.I) else 1))
    for p in pdfs:
        if p.get("number") or p.get("lines"):
            return p
    return doc["pdf"][0] if doc["pdf"] else {}


def find_vendor(kb, src, doc):
    tid = norm_id(src.get("seller_tax_id"))
    cands = kb.vend_by_tax.get(tid, [])
    if not cands and tid:
        # try with country prefix stripped/added
        for k, v in kb.vend_by_tax.items():
            if k.endswith(tid) or tid.endswith(k):
                cands = v
                break
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1:
        return sorted(cands)[0]
    # fallback: name
    name = (src.get("seller_name") or "").lower()
    for v in kb.vendors.values():
        if v["name"].lower() == name:
            return v["id"]
    return None


def find_company(kb, src):
    return kb.comp_by_tax.get(norm_id(src.get("buyer_tax_id")))


def detect_currency(src, pdf, company_cur):
    if src.get("currency"):
        return src["currency"]
    tl = " ".join((pdf or {}).get("totals_lines", [])[:30])
    for k, c in CUR_HINT:
        if k in tl:
            return c
    return company_cur


def amounts(src, doc):
    """Return net, tax(printed, incl. 0 for reverse charge), gross, withholding, retention, payable in doc cents (abs)."""
    fmt = src.get("format")
    if fmt == "facturae":
        net = src["net"]
        tax = src["tax_total"] or 0
        gross = src["gross"]
        wht = src.get("wht_total") or 0
        ret = src.get("retention") or 0
        payable = src.get("payable")
        if payable is None:
            payable = gross - ret
        # facturae InvoiceTotal is already net of withholdings
        gross_b = net + tax
        payable = gross_b - wht - ret
        return dict(net=net, tax=tax, gross=gross_b, withholding=wht, retention=ret, payable=payable)
    if fmt == "cfdi":
        net = src["net"]
        tax = sum(t["amount"] or 0 for t in src["taxes"])
        wht = sum(w["amount"] or 0 for w in src["withholdings"])
        # retention (garantía) is in the PDF
        ret = 0
        for p in doc["pdf"]:
            ret = max(ret, p.get("retention") or 0)
        gross = net + tax
        return dict(net=net, tax=tax, gross=gross, withholding=wht, retention=ret, payable=gross - wht - ret)
    net = src.get("net")
    if net is None:
        net = sum(l["amount"] for l in src.get("lines", []))
    tax = sum(t["amount"] or 0 for t in src.get("taxes", []))
    gross = src.get("gross")
    wht = sum(w["amount"] for w in src.get("withholdings", []))
    ret = src.get("retention") or 0
    if gross is None:
        gross = net + tax
    payable = abs(gross) - abs(wht) - abs(ret)
    return dict(net=net, tax=tax, gross=gross, withholding=wht, retention=ret, payable=payable)


def extract_header(kb, doc):
    src = pick_source(doc)
    pdf = src if src.get("format") == "pdf" else (doc["pdf"][0] if doc["pdf"] else None)
    company = find_company(kb, src) or (find_company(kb, pdf) if pdf else None)
    vendor = find_vendor(kb, src, doc)
    if vendor is None and pdf:
        vendor = find_vendor(kb, pdf, doc)
    number = src.get("number")
    if src.get("format") == "cfdi" and pdf and pdf.get("number"):
        number = pdf["number"]
    date = src.get("date")
    eng = src.get("english", False)
    if src.get("format") == "pdf":
        from .parse_doc import parse_date
        date = parse_date(date or "", eng, ref=doc["message"].get("received_at", "")[:10] or None)
    comp_cur = next((c["currency"] for c in kb.companies if c["code"] == company), "EUR")
    cur = detect_currency(src, pdf, comp_cur)
    am = amounts(src, doc)
    sign = -1 if (am["net"] or 0) < 0 or (am["gross"] or 0) < 0 else 1
    am = {k: abs(v) if v is not None else None for k, v in am.items()}
    return dict(company=company, vendor_id=vendor, invoice_number=number, invoice_date=date, currency=cur, sign=sign, **am), src
