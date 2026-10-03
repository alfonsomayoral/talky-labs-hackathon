"""AP decision engine prototype (research). Rules only, no LLM.

Computes for every doc in tasks/ap_documents.json: document_type, decision, reasons, duplicate_of, payee, payment_block,
action, action_data, company, vendor_id (+ debug signals). Driven by ``kalmora solve-ap``; never reads golden.
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys
from datetime import date, timedelta

from .ap_extract import load_doc, parse_date, parse_num, cents, IBAN_RE  # noqa: E402

DECISION_ORDER = ["DUPLICATE", "REJECT", "HOLD", "POST_PAYMENT_BLOCK", "POST"]
REJECT_ORDER = ["MANDATORY_FIELD_MISSING", "WRONG_ADDRESSEE", "ISP_NOT_APPLIED", "VAT_RATE_INCORRECT", "WITHHOLDING_MISSING",
                "ARITHMETIC_ERROR", "CERTIFICATION_CUMULATIVE_BILLED", "CFDI_MISMATCH"]
HOLD_ORDER = ["VENDOR_NOT_IN_MASTER", "BANK_DETAILS_CHANGED", "QTY_NOT_RECEIVED", "PRICE_VARIANCE"]
RATE_OF_CODE = {"S21": 21.0, "S10": 10.0, "S04": 4.0, "P23": 23.0, "P13": 13.0, "P06": 6.0, "M16": 16.0, "M08": 8.0}
SPANISH_SUBCONTRACTOR = ("SUB_STRUCT", "SUB_MEP", "SUB_FINISH", "SUB_EARTH")
ABLATE = set(filter(None, os.environ.get("ABLATE", "").split(",")))  # research ablations: no_newanomaly, no_qtydate, strict_amount


def jl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def norm_tax(x):
    return re.sub(r"^(ES|PT)", "", re.sub(r"[\s\-]", "", (x or "").upper()))


def norm_num(s):  # score.py definition
    return re.sub(r"[^0-9A-Z]", "", str(s or "").upper()).lstrip("0")


def num_match(a, b):
    """Invoice numbers equal after normalisation, allowing a short alphabetic prefix ('F-', 'FRA') on either side."""
    a, b = norm_num(a), norm_num(b)
    if not a or not b:
        return False
    if a == b:
        return True
    for x, y in ((a, b), (b, a)):  # 'F0009557' vs '9557', 'FF2611803' vs 'F2611803'
        for k in (1, 2, 3):
            if len(x) > k and x[:k].isalpha() and x[k:].lstrip("0") == y and len(y) >= 4:
                return True
    return False


def domain(email):
    return email.split("@")[-1].lower() if email else None


# ------------------------------------------------------------------ context
class Ctx:
    def __init__(self, phase):
        e = lambda f: os.path.join(phase, "erp", f)
        self.phase = phase
        self.vendors = {v["id"]: v for v in jl(e("vendors.jsonl"))}
        self.companies = json.load(open(e("companies.json"), encoding="utf-8"))
        self.company_by_tax = {norm_tax(c["tax_id"]): c["code"] for c in self.companies}
        self.company_by_name = {c["name"].lower(): c["code"] for c in self.companies}
        self.vendor_by_tax = collections.defaultdict(list)
        self.vendor_by_domain = collections.defaultdict(list)
        for v in self.vendors.values():
            for k in {norm_tax(v.get("tax_id")), norm_tax(v.get("vat_id"))} - {""}:
                self.vendor_by_tax[k].append(v["id"])
            if v.get("email"):
                self.vendor_by_domain[domain(v["email"])].append(v["id"])
        self.pos = {p["id"]: p for p in jl(e("purchase_orders.jsonl"))}
        self.pos_by_vendor = collections.defaultdict(list)
        for p in self.pos.values():
            self.pos_by_vendor[p["vendor"]].append(p)
        self.grs = jl(e("goods_receipts.jsonl"))
        self.gr_by_vref = collections.defaultdict(list)
        self.gr_by_po = collections.defaultdict(list)
        for g in self.grs:
            self.gr_by_vref[(g["vendor"], g["reference"])].append(g)
            self.gr_by_po[(g["po"], g["po_item"])].append(g)
        self.certs = collections.defaultdict(list)
        for c in jl(e("contractor_certificates.jsonl")):
            self.certs[c["vendor"]].append(c)
        self.ap_inv = {x["doc_id"]: x for x in jl(e("ap_invoices.jsonl"))}
        self.ap_log = {x["doc_id"]: x for x in jl(e("ap_document_log.jsonl"))}
        # history of received documents (vendor, number, gross, decision)
        self.history = []
        for did, x in self.ap_log.items():
            inv = self.ap_inv.get(did, {})
            self.history.append({"doc_id": did, "vendor": x["vendor"], "company": x["company"], "number": x["number"], "kind": x["kind"],
                                 "gross": inv.get("gross"), "decision": x["decision"], "reasons": x["reasons"], "received_on": x["received_on"]})
        self.hist_by_vendor = collections.defaultdict(list)
        for h in self.history:
            if h["number"]:
                self.hist_by_vendor[h["vendor"]].append(h)


# ------------------------------------------------------------------ classification
def classify(doc):
    """Return document_type from structural + textual signals (filename prefix is NOT used, see report)."""
    t = doc["text"]
    inv = doc.get("inv") or {}
    title = (inv.get("title") or "").upper()
    if re.search(r"DILIGENCIA DE EMBARGO", t):
        return "TAX_GARNISHMENT_ORDER"
    if re.search(r"Certificado de estar al corriente", t) and "AGENCIA TRIBUTARIA" in t:
        return "CONTRACTOR_TAX_CERTIFICATE"
    if re.search(r"CESIÓN DE CRÉDITOS|cesión de créditos", t):
        return "FACTORING_NOTICE"
    if re.search(r"cambio de cuenta bancaria", t, re.I):
        return "BANK_DETAILS_CHANGE"
    if re.search(r"EXTRACTO DE CUENTA|RECORDATORIO DE PAGO|STATEMENT OF ACCOUNT", t):
        return "VENDOR_STATEMENT"
    if re.search(r"DEPOSIT REQUEST|SOLICITUD DE ANTICIPO|T/T deposit", t, re.I):
        return "DOWN_PAYMENT_REQUEST"
    if re.search(r"FACTURA PROFORMA|PROFORMA", t) and not re.search(r"DEPOSIT", t):
        return "PROFORMA"
    x = doc.get("xml") or {}
    if (x.get("format") == "facturae" and (x.get("corrects") or x.get("invoice_class") in ("OR", "CR"))) or (x.get("format") == "cfdi" and x.get("doc_type") == "E"):
        return "CREDIT_NOTE"
    if re.search(r"RECTIFICATIVA|NOTA DE CRÉDITO|CREDIT NOTE", title) or inv.get("corrects") or (inv.get("gross") or 0) < 0:
        return "CREDIT_NOTE"
    return "INVOICE"


# ------------------------------------------------------------------ non-invoice parsing
def parse_letter(doc, ctx, dtype):
    t = doc["text"]
    flat = re.sub(r"\s+", " ", t)
    out = {"action_data": {}}
    nifs = re.findall(r"NIF:?\s*([A-Z0-9]{8,12})", flat)
    vid = None
    if dtype == "TAX_GARNISHMENT_ORDER":
        m = re.search(r"Obligado al pago[^:]*:\s*(.+?)\s+–\s+NIF\s+([A-Z0-9]+)", flat)
        if m:
            vid = (ctx.vendor_by_tax.get(norm_tax(m.group(2))) or [None])[0]
        m2 = re.search(r"Destinatario:.*?NIF\s+([A-Z0-9]+)", flat)
        out["company"] = ctx.company_by_tax.get(norm_tax(m2.group(1))) if m2 else None
        ref = re.search(r"Nº\s*([0-9A-Z]{10,})", flat)
        amt = re.search(r"Importe total pendiente[^:]*:\s*([\d.,]+)\s*EUR", flat)
        out["action_data"] = {"ref": ref.group(1) if ref else None, "amount": cents(parse_num(amt.group(1))) if amt else None}
    else:
        for n in nifs:
            if ctx.vendor_by_tax.get(norm_tax(n)):
                vid = ctx.vendor_by_tax[norm_tax(n)][0]
                break
    if not vid:  # letter without NIF: old IBAN / legal name in the letterhead, then sender domain
        ibans = set(re.findall(r"\b([A-Z]{2}\d{2}[A-Z0-9]{12,30})\b", flat))
        hit = [v["id"] for v in ctx.vendors.values() if v["bank"].get("iban") in ibans]
        if not hit:
            head = t[:400]
            hit = sorted((v["id"] for v in ctx.vendors.values() if v["name"] in head), key=lambda i: -len(ctx.vendors[i]["name"]))
        if hit:
            vid = hit[0]
    if not vid and doc["sender_domain"]:
        vid = (ctx.vendor_by_domain.get(doc["sender_domain"]) or [None])[0]
    out["vendor_id"] = vid
    # letter date: "<Ciudad>, 12 de julio de 2026"
    m = re.search(r",\s*(\d{1,2} de [a-záéíóú]+ de \d{4})", flat)
    out["date"] = parse_date(m.group(1)) if m else None
    if dtype == "FACTORING_NOTICE":
        f = re.search(r"cedido a (.+?) la totalidad", flat)
        ib = re.search(r"IBAN\s+([A-Z]{2}\d{2}[A-Z0-9]+)", flat)
        eff = re.search(r"con efectos desde el (\d{2}/\d{2}/\d{4})", flat)
        out["action_data"] = {"factor": f.group(1).strip() if f else None, "iban": ib.group(1) if ib else None, "effective": parse_date(eff.group(1)) if eff else None}
    elif dtype == "BANK_DETAILS_CHANGE":
        new = re.search(r"nueva cuenta:\s*IBAN:\s*([A-Z]{2}\d{2}[A-Z0-9]+)", flat)
        old = re.search(r"Cuenta anterior[^:]*:\s*([A-Z]{2}\d{2}[A-Z0-9]+)", flat)
        eff = re.search(r"a partir del (\d{2}/\d{2}/\d{4})", flat)
        out["action_data"] = {"old_iban": old.group(1) if old else None, "new_iban": new.group(1) if new else None,
                              "certificate": "CERTIFICADO DE TITULARIDAD" in t, "effective": parse_date(eff.group(1)) if eff else None}
    elif dtype == "CONTRACTOR_TAX_CERTIFICATE":
        ref = re.search(r"Referencia:\s*(CERT-[\d-]+)", flat)
        iss = re.search(r"Fecha de emisión:\s*(\d{2}/\d{2}/\d{4})", flat)
        until = re.search(r"hasta (\d{2}/\d{2}/\d{4})", flat)
        out["date"] = parse_date(iss.group(1)) if iss else None
        out["action_data"] = {"valid_until": parse_date(until.group(1)) if until else None, "reference": ref.group(1) if ref else None}
    elif dtype == "PROFORMA":
        n = re.search(r"PROFORMA Nº\s*(\S+)", flat)
        f = re.search(r"Fecha:\s*(\d{2}/\d{2}/\d{4})", flat)
        vd = re.search(r"Validez\s*(\d+)\s*días", flat)
        out["number"] = n.group(1) if n else None
        out["date"] = parse_date(f.group(1)) if f else None
        out["action_data"] = {"valid_days": int(vd.group(1)) if vd else None}
    elif dtype == "VENDOR_STATEMENT":
        a = re.search(r"situación a (\d{2}/\d{2}/\d{4})", flat)
        out["date"] = doc["received_on"]
        out["action_data"] = {"as_of": parse_date(a.group(1)) if a else None}
    if not out.get("company"):
        m = re.search(r"(Kalmora [^–\n]+?, S\.[A-Z.]+|UTE Kalmora[^\n]+?Valdemora\))", t)
        if m:
            out["company"] = ctx.company_by_name.get(m.group(1).strip().lower())
        if not out.get("company") and vid:
            out["company"] = (ctx.vendors[vid]["companies"] or [None])[0]
    return out


# ------------------------------------------------------------------ invoice checks
def resolve_vendor(doc, ctx, processed=()):
    inv = doc["inv"]
    tid = norm_tax(inv.get("vendor_tax_id"))
    if tid and ctx.vendor_by_tax.get(tid):
        return ctx.vendor_by_tax[tid][0], "tax_id"
    if tid:
        return None, "tax_id_unknown"
    num = (doc.get("pdf") or {}).get("filename_number")
    cands = ctx.vendor_by_domain.get(doc["sender_domain"] or "", [])
    if len(cands) == 1:
        return cands[0], "domain"
    if len(cands) > 1 and num:  # shared mailbox domain (e.g. 5 'Señalizaciones Viales' vendors): disambiguate by invoice history
        hit = [v for v in cands if any(num_match(h["number"], num) for h in ctx.hist_by_vendor.get(v, []))]
        if not hit:  # ...or by documents already processed this month
            hit = sorted({p["vendor_id"] for p in processed if p.get("vendor_id") in cands and num_match(p["inv"].get("number"), num)})
        if len(hit) == 1:
            return hit[0], "domain+history"
        return cands[0], "domain_ambiguous"
    if num:
        cands = {h["vendor"] for vs in ctx.hist_by_vendor.values() for h in vs if num_match(h["number"], num)}
        if len(cands) == 1:
            return cands.pop(), "history_number"
    return None, "unresolved"


def resolve_company(doc, ctx):
    inv = doc["inv"]
    tid = norm_tax(inv.get("buyer_tax_id"))
    if tid and tid in ctx.company_by_tax:
        return ctx.company_by_tax[tid]
    name = (inv.get("buyer_name") or "").lower()
    for n, c in ctx.company_by_name.items():
        if name and (name == n or n.startswith(name[:25])):
            return c
    return None


def po_items_for_line(line, vid, inv, ctx):
    """Map an invoice line to (po, item) via GR reference, else via cited PO + description."""
    if line.get("doc_ref"):
        grs = ctx.gr_by_vref.get((vid, line["doc_ref"]))
        if grs:
            return grs[0]["po"], grs[0]["po_item"], "gr"
    cands = [ctx.pos[p] for p in inv.get("po_refs", []) if p in ctx.pos and ctx.pos[p]["vendor"] == vid]
    desc = (line.get("desc") or "").lower()
    for p in cands:
        for it in p["items"]:
            d = it["description"].lower()
            if d[:30] and (desc.startswith(d[:30]) or d.startswith(desc[:30])):
                return p["id"], it["item"], "po_desc"
    return None, None, None


def po_item(ctx, po, item):
    p = ctx.pos.get(po)
    if not p:
        return None
    return next((i for i in p["items"] if i["item"] == item), None)


def run_checks(doc, ctx, month):
    """All §2.2 checks except DUPLICATE. Returns dict reason -> evidence (only failing ones)."""
    inv, vid = doc["inv"], doc["vendor_id"]
    v = ctx.vendors.get(vid)
    fails = {}
    if doc["is_scan"]:
        return fails
    company = doc["company"]
    # ---- REJECT
    if not inv.get("buyer_tax_id"):
        fails["MANDATORY_FIELD_MISSING"] = "buyer tax id missing"
    po_companies = {ctx.pos[p]["company"] for p in inv.get("po_refs", []) if p in ctx.pos}
    for l in inv.get("lines", []):
        if l.get("doc_ref") and vid:
            for g in ctx.gr_by_vref.get((vid, l["doc_ref"]), []):
                po_companies.add(g["company"])
    if company and po_companies and company not in po_companies:
        fails["WRONG_ADDRESSEE"] = f"addressed to {company}, PO company {sorted(po_companies)}"
    elif company and v and v["companies"] and company not in v["companies"]:
        fails["WRONG_ADDRESSEE"] = f"addressed to {company}, vendor serves {v['companies']}"
    else:
        for k in ("cups", "contract"):  # utility supply point / contract previously billed (and accepted) for another company
            key = inv.get(k)
            if company and key and month.get("cups_company", {}).get(key) not in (None, company):
                fails["WRONG_ADDRESSEE"] = f"{k} {key} previously billed to {month['cups_company'][key]}"
                break
    charged = [t for t in inv.get("taxes", []) if (t.get("rate") or 0) > 0 and not t.get("isp")]
    if v and v["default_tax_code"] == "SISP" and charged and doc["dtype"] == "INVOICE":
        fails["ISP_NOT_APPLIED"] = f"subcontractor charged VAT {[t['rate'] for t in charged]}"
    elif v and v["default_tax_code"] in RATE_OF_CODE and charged:
        exp = RATE_OF_CODE[v["default_tax_code"]]
        bad = [t["rate"] for t in charged if abs(t["rate"] - exp) > 0.01]
        if bad:
            fails["VAT_RATE_INCORRECT"] = f"charged {bad}, expected {exp}"
    if v and v.get("withholding") and doc["dtype"] == "INVOICE":
        wh = [w for w in inv.get("withholdings", []) if w["kind"] == "tax" and (w.get("amount") or 0) != 0]
        if not wh:
            fails["WITHHOLDING_MISSING"] = f"vendor withholding {v['withholding']} not applied"
    net, gross = inv.get("net"), inv.get("gross")
    tax = sum(t.get("amount") or 0 for t in inv.get("taxes", []) if not t.get("isp"))
    if net is not None and gross is not None and abs(gross - (net + tax)) > 2:
        fails["ARITHMETIC_ERROR"] = f"gross {gross} != net {net} + tax {tax}"
    elif net is not None and inv.get("lines") and doc["channel"] != "facturae":
        s = sum(l.get("amount") or 0 for l in inv["lines"])
        if abs(s - net) > 2 and abs(s - net) > 0.001 * abs(net):
            fails["ARITHMETIC_ERROR?"] = f"sum lines {s} != net {net}"  # parse-quality signal, not used for decision
    if inv.get("cert_origen") is not None and inv.get("cert_esta") is not None and net is not None:
        tol = max(2, 0.001 * abs(inv["cert_origen"]))
        if abs(net - inv["cert_origen"]) <= tol and abs(net - inv["cert_esta"]) > tol:
            fails["CERTIFICATION_CUMULATIVE_BILLED"] = f"net {net} = a origen, esta certificación {inv['cert_esta']}"
    if doc["channel"] == "cfdi" and doc.get("xml") and doc.get("pdf"):
        x, p = doc["xml"], doc["pdf"]
        diffs = []
        # CFDI Total = SubTotal - Descuento + traslados - retenciones -> compare with PDF 'Total a pagar' when present
        ptotal = (p.get("gross") or 0) - sum(abs(w.get("amount") or 0) for w in p.get("withholdings", []) if w["kind"] == "tax") if p.get("gross") is not None else None
        if x.get("gross") is not None and ptotal is not None and abs(abs(x["gross"]) - abs(ptotal)) > 1:
            diffs.append("total")
        if x.get("net") is not None and p.get("net") is not None and abs(abs(x["net"]) - abs(p["net"])) > 1:
            diffs.append("subtotal")
        xt = sum(t.get("amount") or 0 for t in x.get("taxes", []))
        pt = sum(t.get("amount") or 0 for t in p.get("taxes", []))
        if abs(abs(xt) - abs(pt)) > 1:
            diffs.append("tax")
        if norm_num(x.get("number")) != norm_num(p.get("number")):
            diffs.append("number")
        if norm_tax(x.get("vendor_tax_id")) != norm_tax(p.get("vendor_tax_id")) or norm_tax(x.get("buyer_tax_id")) != norm_tax(p.get("buyer_tax_id")):
            diffs.append("rfc")
        if diffs:
            fails["CFDI_MISMATCH"] = f"XML vs PDF differ in {diffs}"
    # ---- HOLD
    if not vid:
        fails["VENDOR_NOT_IN_MASTER"] = f"tax id {inv.get('vendor_tax_id')} not in vendor master"
    if v:
        reasons = []
        vdom = domain(v.get("email"))
        if doc["sender_domain"] and vdom and doc["sender_domain"] != vdom and not doc["sender_domain"].endswith("kalmora.example"):
            reasons.append(f"sender domain {doc['sender_domain']} != {vdom}")
        iban = inv.get("iban")
        master = {x for k, x in v["bank"].items() if k in ("iban", "clabe", "account") and x}
        if iban and master and iban not in master:
            ok = False
            ap = v.get("alternative_payee")
            if ap and ap.get("iban") == iban:  # registered factoring cession
                ok = True
            for L in month["letters"]:  # bank-change letter or cession received this month
                if L["vendor_id"] == vid and L["dtype"] in ("BANK_DETAILS_CHANGE", "FACTORING_NOTICE"):
                    ad = L["action_data"]
                    if iban in (ad.get("new_iban"), ad.get("iban")):
                        ok = True
            if not ok:
                hist = [h.get("iban") for h in v.get("bank_history") or []]
                reasons.append(f"account {iban} != master {sorted(master)}" + (" (old account in bank_history)" if iban in hist else ""))
        if reasons:
            fails["BANK_DETAILS_CHANGED"] = "; ".join(reasons)
        # QTY: invoiced delivery note with no goods receipt at close
        has_gr = [l for l in inv.get("lines", []) if l.get("doc_ref") and ctx.gr_by_vref.get((vid, l["doc_ref"]))]
        missing = []
        for l in inv.get("lines", []):
            r = l.get("doc_ref")
            if not r or ctx.gr_by_vref.get((vid, r)):
                continue
            m = re.search(r"\((\d{2})/(\d{2})\)", l.get("desc") or "")
            idate = inv.get("date_iso") or doc["received_on"]
            ddate = f"{idate[:4]}-{m.group(2)}-{m.group(1)}" if m else None
            if "no_qtydate" in ABLATE or (ddate and ddate < min(idate, doc["received_on"])):
                missing.append(r)
        if missing and has_gr:
            fails["QTY_NOT_RECEIVED"] = f"no GR for {missing}"
        # PRICE: unit price vs PO price (>2 % or >150 per line)
        over = []
        for l in inv.get("lines", []):
            if l.get("price") is None:
                continue
            po, item, how = po_items_for_line(l, vid, inv, ctx)
            it = po_item(ctx, po, item) if po else None
            if not it or not it["unit_price"]:
                continue
            pp = it["unit_price"] / 100.0
            ip = l["price"]
            qty = l.get("qty") or 1.0
            if ip > pp + 1e-9 and ((ip - pp) / pp > 0.02 or (ip - pp) * qty > 150):
                over.append((l.get("doc_ref") or l["desc"][:30], ip, pp))
        if over:
            fails["PRICE_VARIANCE"] = f"{over[:3]}"
    return fails


def cert_valid(ctx, month, vid, d):
    certs = list(ctx.certs.get(vid, []))
    for L in month["letters"]:
        if L["vendor_id"] == vid and L["dtype"] == "CONTRACTOR_TAX_CERTIFICATE" and L.get("date"):
            certs.append({"issued_on": L["date"], "valid_until": L["action_data"].get("valid_until") or "9999"})
    return any(c["issued_on"] <= d <= c["valid_until"] for c in certs)


def payee_for(doc, ctx, month):
    v = ctx.vendors.get(doc["vendor_id"])
    if not v:
        return None
    d = doc["inv"].get("date_iso") or doc["received_on"]
    ap = v.get("alternative_payee")
    if ap and ap.get("type") == "FACTOR" and ap.get("from_date") and ap["from_date"] <= d:
        return {"type": "FACTOR", "name": ap.get("name"), "iban": ap.get("iban")}
    for L in month["letters"]:
        if L["vendor_id"] == v["id"] and L["dtype"] == "FACTORING_NOTICE" and (L["action_data"].get("effective") or "9999") <= d:
            return {"type": "FACTOR", "name": L["action_data"].get("factor"), "iban": L["action_data"].get("iban")}
    for gq in v.get("garnishments") or []:
        if gq.get("from_date") and gq["from_date"] <= doc["received_on"]:
            return {"type": "AEAT_EMBARGO", "ref": gq.get("ref"), "limit": gq.get("amount")}
    for L in month["letters"]:
        if L["vendor_id"] == v["id"] and L["dtype"] == "TAX_GARNISHMENT_ORDER" and L["received_at"] < doc["received_at"]:
            return {"type": "AEAT_EMBARGO", "ref": L["action_data"].get("ref"), "limit": L["action_data"].get("amount")}
    return None


# ------------------------------------------------------------------ duplicates
def find_duplicate(doc, ctx, processed, order):
    """Earliest non-rejected document (history or earlier in month) with same vendor + number (+ amount when readable)."""
    vid = doc["vendor_id"]
    if not vid:
        return None
    num = doc["inv"].get("number") or (doc.get("pdf") or {}).get("filename_number")
    gross = doc["inv"].get("gross")
    if not num:
        return None
    def amount_ok(g2):
        if gross is None or g2 is None:
            return True
        return abs(abs(gross) - abs(g2)) <= (2 if "strict_amount" in ABLATE else max(2, 0.01 * abs(g2)))
    # history first (always earlier)
    for h in sorted(ctx.hist_by_vendor.get(vid, []), key=lambda h: h["received_on"]):
        if h["decision"] in ("REJECT",) or h["kind"] != ("credit_note" if doc["dtype"] == "CREDIT_NOTE" else "invoice"):
            continue
        if num_match(h["number"], num) and amount_ok(h["gross"]):
            return {"doc_id": h["doc_id"], "decision": h["decision"], "reasons": h["reasons"], "src": "history"}
    for p in processed:
        if p["vendor_id"] != vid or p["decision"] in ("REJECT", "NOT_INVOICE") or (p["dtype"] == "CREDIT_NOTE") != (doc["dtype"] == "CREDIT_NOTE"):
            continue
        pnum = p["inv"].get("number") or (p.get("pdf") or {}).get("filename_number")
        if num_match(pnum, num) and amount_ok(p["inv"].get("gross")):
            orig = p["duplicate_of"] or p["doc_id"]
            return {"doc_id": orig, "decision": p["decision"], "reasons": p["reasons"], "src": "month"}
    return None


# ------------------------------------------------------------------ main pipeline
def process_phase(phase, text_cache=None, order="docid", cups_company=None):
    ctx = Ctx(phase)
    ids = json.load(open(os.path.join(phase, "tasks", "ap_documents.json")))
    inbox = os.path.join(phase, "inbox", "ap")
    docs = [load_doc(inbox, d, text_cache) for d in ids]
    for doc in docs:
        doc["dtype"] = classify(doc)
    # letters/certificates received in the month (support IBAN changes, factoring, embargo, art.43)
    month = {"letters": [], "cups_company": cups_company or {}}
    for doc in docs:
        if doc["dtype"] in ("FACTORING_NOTICE", "BANK_DETAILS_CHANGE", "TAX_GARNISHMENT_ORDER", "CONTRACTOR_TAX_CERTIFICATE", "PROFORMA", "VENDOR_STATEMENT"):
            info = parse_letter(doc, ctx, doc["dtype"])
            doc.update(vendor_id=info["vendor_id"], company=info.get("company"), letter=info)
            month["letters"].append({"doc_id": doc["doc_id"], "dtype": doc["dtype"], "vendor_id": info["vendor_id"], "received_at": doc["received_at"],
                                     "date": info.get("date"), "action_data": info["action_data"]})
    key = (lambda d: d["doc_id"]) if order == "docid" else (lambda d: (d["received_at"], d["doc_id"]))
    processed, out = [], []
    for doc in sorted(docs, key=key):
        r = {"doc_id": doc["doc_id"], "document_type": doc["dtype"], "reasons": [], "duplicate_of": None, "payee": None,
             "payment_block": None, "action": None, "action_data": None}
        if doc["dtype"] in ("PROFORMA", "VENDOR_STATEMENT", "FACTORING_NOTICE", "TAX_GARNISHMENT_ORDER", "BANK_DETAILS_CHANGE", "CONTRACTOR_TAX_CERTIFICATE"):
            L = doc["letter"]
            r.update(decision="NOT_INVOICE", company=L.get("company"), vendor_id=L["vendor_id"], invoice_number=L.get("number"),
                     invoice_date=L.get("date"), action={"PROFORMA": "NONE", "VENDOR_STATEMENT": "NONE", "FACTORING_NOTICE": "REGISTER_ALTERNATIVE_PAYEE",
                                                         "TAX_GARNISHMENT_ORDER": "REGISTER_EMBARGO", "BANK_DETAILS_CHANGE": "UPDATE_BANK_DETAILS",
                                                         "CONTRACTOR_TAX_CERTIFICATE": "UPDATE_CONTRACTOR_CERTIFICATE"}[doc["dtype"]],
                     action_data=L["action_data"])
            doc.update(decision="NOT_INVOICE", reasons=[], duplicate_of=None)
            processed.append(doc)
            out.append(r)
            continue
        doc["vendor_id"], doc["vendor_how"] = resolve_vendor(doc, ctx, processed)
        doc["company"] = resolve_company(doc, ctx)
        if doc["company"] is None and doc["vendor_id"]:
            doc["company"] = (ctx.vendors[doc["vendor_id"]]["companies"] or [None])[0]
        fails = run_checks(doc, ctx, month)
        decision_fails = {k: v for k, v in fails.items() if not k.endswith("?")}
        dup = find_duplicate(doc, ctx, processed, order)
        is_dup = False
        if dup:
            # a re-submission that introduces NEW reject/hold problems (other IBAN, missing NIF...) is judged on its own
            new = set(decision_fails) - set(dup.get("reasons") or [])
            is_dup = not new or "no_newanomaly" in ABLATE
            r["dup_candidate"] = dup["doc_id"]
        rej = [k for k in REJECT_ORDER if k in decision_fails]
        hold = [k for k in HOLD_ORDER if k in decision_fails]
        if is_dup:
            decision, reasons = "DUPLICATE", ["DUPLICATE"]
            r["duplicate_of"] = dup["doc_id"]
        elif rej:
            decision, reasons = "REJECT", rej
        elif hold:
            decision, reasons = "HOLD", hold
        else:
            v = ctx.vendors.get(doc["vendor_id"])
            d = doc["inv"].get("date_iso") or doc["received_on"]
            if v and v["archetype"] in SPANISH_SUBCONTRACTOR and doc["dtype"] == "INVOICE" and not cert_valid(ctx, month, v["id"], d):
                decision, reasons = "POST_PAYMENT_BLOCK", ["CONTRACTOR_CERTIFICATE_EXPIRED"]
                r["payment_block"] = "CONTRACTOR_CERTIFICATE_EXPIRED"
            else:
                decision, reasons = "POST", []
        if decision in ("POST", "POST_PAYMENT_BLOCK"):
            r["payee"] = payee_for(doc, ctx, month)
        if doc["dtype"] == "CREDIT_NOTE":
            ref = doc["inv"].get("corrects")
            cand = [h["doc_id"] for h in ctx.hist_by_vendor.get(doc["vendor_id"], []) if h["kind"] == "invoice" and h["decision"] != "REJECT" and num_match(h["number"], ref)]
            cand += [p["doc_id"] for p in processed if p.get("vendor_id") == doc["vendor_id"] and p["dtype"] == "INVOICE" and p.get("decision") not in ("REJECT", "DUPLICATE") and num_match(p["inv"].get("number"), ref)]
            r["credit_note_of"] = cand[0] if cand else None
        inv = doc["inv"]
        r.update(decision=decision, reasons=reasons, company=doc["company"], vendor_id=doc["vendor_id"],
                 invoice_number=inv.get("number") or (doc.get("pdf") or {}).get("filename_number"), invoice_date=inv.get("date_iso"),
                 currency=inv.get("currency"), net=inv.get("net"), gross=inv.get("gross"), all_fails=fails, vendor_how=doc["vendor_how"],
                 channel=doc["channel"])
        doc.update(decision=decision, reasons=reasons, duplicate_of=r["duplicate_of"])
        processed.append(doc)
        out.append(r)
    return out, docs, ctx
