"""AP coding prototype: given a posted decision, produce header + lines + journal_entry.

usage: python proto.py dev|test
"""
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

from .common import load_phase, nn
from .header import extract_header, pick_source
from .grir import open_grs

INPUT_KINDS = {"input"}
REVERSE_KINDS = {"reverse"}
PO_RE = re.compile(r"\b(45\d{8})\b")
DN_RE = re.compile(r"\b((?:AL|REM|GR|LS|ALB|DN)-\d{4,})\b")


def strip_acc(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def toks(s):
    return set(t for t in strip_acc(s).split() if len(t) > 1)


# ------------------------------------------------------------------ history
def desc_sig(t):
    t = strip_acc(t or "")[:50]
    t = re.sub(r"\d+", " ", t)
    t = re.sub(r"\b(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|january|february|march|april|may|june|july|august|september|october|november|december|kwh|m3)\b", " ", t)
    return " ".join(t.split()[:6])

class History:
    def __init__(self, kb):
        self.kb = kb
        inv_by_je = {a["journal_entry"]: a for a in kb.ap_inv if a.get("journal_entry")}
        self.inv_by_je = inv_by_je
        self.cost = defaultdict(Counter)  # (vendor, company) -> Counter((acc, cc, wbs, tax))
        self.cost_last = {}
        self.by_vendor_number = {}
        self.inv_cost = defaultdict(list)  # (vendor, company) -> [(issue_date, net, key)]
        self.desc = defaultdict(Counter)  # (vendor, company, sig) -> Counter(key)
        for jid, je in kb.je.items():
            a = inv_by_je.get(jid)
            if not a:
                continue
            self.by_vendor_number[(a["vendor"], nn(a["number"]))] = (a, je)
            for l in je["lines"]:
                if (l["account"][0] in "62" and (l["cost_center"] or l["wbs"])) or (l["account"] == "47200000" and l["tax_code"] == "SIMP"):
                    self.desc[(a["vendor"], a["company"], desc_sig(l.get("text")))][(l["account"], l["cost_center"], l["wbs"], l["tax_code"])] += 1
            ks = [(l["account"], l["cost_center"], l["wbs"], l["tax_code"]) for l in je["lines"] if l["account"][0] in "62" and (l["cost_center"] or l["wbs"])]
            if ks and a.get("kind", "invoice") == "invoice":
                self.inv_cost[(a["vendor"], a["company"])].append((a["issue_date"], a["net"], Counter(ks).most_common(1)[0][0], nn(a["number"])))
            for l in je["lines"]:
                acc = l["account"]
                if acc[0] in "62" and not acc.startswith(("40", "41")) and (l["cost_center"] or l["wbs"]):
                    k = (a["vendor"], a["company"])
                    key = (acc, l["cost_center"], l["wbs"], l["tax_code"])
                    self.cost[k][key] += 1
                    if k not in self.cost_last or je["posting_date"] >= self.cost_last[k][0]:
                        self.cost_last[k] = (je["posting_date"], key)


# ------------------------------------------------------------------ PO matching
class POMatcher:
    def __init__(self, kb):
        self.kb = kb
        self.open = open_grs(kb)
        self.used = set()
        self.pos_by_vc = defaultdict(list)
        for p in kb.pos.values():
            self.pos_by_vc[(p["vendor"], p["company"])].append(p)

    def doc_refs(self, doc):
        txt = []
        for p in doc["pdf"]:
            txt += p["raw_lines"]
        if doc.get("facturae"):
            txt.append(doc["facturae"]["raw"])
        return set(PO_RE.findall("\n".join(txt)))

    def item_score(self, it, desc):
        d = strip_acc(desc)
        mat = strip_acc(it.get("material") or "")
        s = 0.0
        if mat and len(mat) > 4 and mat in d:
            s += 2
        idesc = strip_acc(it["description"])
        if idesc and idesc in d:
            s += 3
        a, b = toks(it["description"]), toks(desc)
        if a and b:
            s += len(a & b) / len(a)
        return s

    def match(self, doc, hdr, lines):
        kb = self.kb
        vendor, company = hdr["vendor_id"], hdr["company"]
        cited = self.doc_refs(doc)
        cand = [p for p in self.pos_by_vc.get((vendor, company), [])]
        for c in cited:
            p = kb.pos.get(c)
            if p and p["company"] == company and p not in cand:
                cand.append(p)
        src = pick_source(doc)
        cert = None
        for p in doc["pdf"]:
            if p.get("cert"):
                cert = re.sub(r"\D", "", p["cert"])
        obra = None
        for p in doc["pdf"]:
            if p.get("obra"):
                obra = strip_acc(p["obra"])
        period = None
        for p in doc["pdf"]:
            m = re.search(r"\d{2}/(\d{2})/(\d{4})", p.get("period") or "")
            if m:
                period = m.group(2) + m.group(1)
        if not period and src.get("period"):
            m = re.match(r"(\d{4})-(\d{2})", src["period"])
            if m:
                period = m.group(1) + m.group(2)
        if not period and hdr.get("invoice_date"):
            period = hdr["invoice_date"][:4] + hdr["invoice_date"][5:7]
        pool = []
        for p in cand:
            for it in p["items"]:
                for g in self.open.get((p["id"], it["item"]), []):
                    if g["id"] not in self.used:
                        pool.append((p, it, g))
        out = []
        for ln in lines:
            desc = ln["desc"] or ""
            res = None
            step = None
            # 1. delivery note reference
            refs = DN_RE.findall(desc)
            if refs:
                for p, it, g in pool:
                    if g["reference"] in refs and g["id"] not in self.used:
                        res = (p, it, g)
                        step = "1_delivery_note_ref"
                        break
            # a cited delivery note that has no open receipt -> do not guess another GR (QTY_NOT_RECEIVED signal)
            ln["_dn_missing"] = bool(refs) and res is None and any(DN_RE.fullmatch(g["reference"]) for _, _, g in pool + [(None, None, x) for p in cand for it in p["items"] for x in kb.gr_by_po.get((p["id"], it["item"]), [])])
            if ln["_dn_missing"]:
                pool_backup = pool
                pool = []
            # 2. PO item by description + receipt evidence, ranked jointly
            if res is None and cand:
                best = None
                for p in cand:
                    proj_ok = bool(obra) and p.get("project") and strip_acc(kb.projects.get(p["project"], {}).get("name", "")).startswith(obra[:25])
                    for it in p["items"]:
                        ds = self.item_score(it, desc)
                        if ds < 0.6:
                            continue
                        base = ds + (0.5 if p["id"] in cited else 0) + (2 if proj_ok else 0)
                        gl = [g for pp, ii, g in pool if pp["id"] == p["id"] and ii["item"] == it["item"] and g["id"] not in self.used]
                        if not gl:
                            if not kb.gr_by_po.get((p["id"], it["item"])) or ln.get("_dn_missing"):
                                cand_t = (base - 1, p["created_on"], (p, it, None))
                                if best is None or cand_t[:2] > best[:2]:
                                    best = cand_t
                            continue
                        for g in gl:
                            s_ = base
                            if cert and re.search(rf"CERT-0*{int(cert)}-", g["reference"]):
                                s_ += 4
                            if period and period in g["reference"]:
                                s_ += 3
                            if abs(g["amount"] - abs(ln["amount"])) <= 1:
                                s_ += 3
                            if ln.get("qty_milli") and g["quantity_milli"] == abs(ln["qty_milli"]):
                                s_ += 1
                            cand_t = (s_, -int(g["posting_date"].replace("-", "")), (p, it, g))
                            if best is None or cand_t[:2] > best[:2]:
                                best = cand_t
                if best:
                    res = best[2]
                    step = "2_desc+evidence" if res[2] else "2_desc_po_item_without_gr"
            # 3. amount equality fallback
            if res is None:
                for p, it, g in pool:
                    if g["id"] not in self.used and abs(g["amount"] - abs(ln["amount"])) <= 1:
                        res = (p, it, g)
                        step = "3_amount_only"
                        break
            if ln.get("_dn_missing"):
                pool = pool_backup
                if res is not None and res[2] is None and kb.gr_by_po.get((res[0]["id"], res[1]["item"])):
                    step = "2_desc_po_item_dn_not_received"
            if res and res[2]:
                self.used.add(res[2]["id"])
            ln["_match_step"] = step
            out.append(res)
        return out


# ------------------------------------------------------------------ multi-site recurring vendors (utilities)
def month_add(ym, k):
    y, m = int(ym[:4]), int(ym[5:7])
    m += k
    while m <= 0:
        m += 12; y -= 1
    while m > 12:
        m -= 12; y += 1
    return f"{y}-{m:02d}"


def multisite_assign(hist, items):
    """items: list of (doc_id, vendor, company, issue_date, net). Returns {doc_id: key} for vendor/company pairs
    whose recent history spans several cost objects. Each site gets one invoice per issue month; assignment by
    closest amount to the site's last invoice (exhaustive for small groups)."""
    import itertools
    res = {}
    groups = defaultdict(list)
    for it in items:
        groups[(it[1], it[2])].append(it)
    for (v, c), docs_ in groups.items():
        h = hist.inv_cost.get((v, c), [])
        if not h:
            continue
        for ym in sorted({d[3][:7] for d in docs_}):
            month_docs = [d for d in docs_ if d[3][:7] == ym]
            recent = [x for x in h if month_add(ym, -3) <= x[0][:7] < ym]
            keys = {x[2] for x in recent}
            if len(keys) <= 1:
                continue
            done = {x[2] for x in h if x[0][:7] == ym}
            last = {}
            for x in sorted(recent):
                last[x[2]] = x[1]
            sites = [k for k in last if k not in done] or list(last)
            if len(month_docs) > len(sites):
                sites = list(last)
            cost = lambda d, k: abs(d[4] - last[k]) / max(1, last[k])
            # stable batch order: average rank of each site's invoice number within its issue month
            rank = defaultdict(list)
            for mm in {x[0][:7] for x in recent}:
                xs = sorted((x for x in recent if x[0][:7] == mm), key=lambda x: x[3])
                for i, x in enumerate(xs):
                    rank[x[2]].append(i / max(1, len(xs) - 1))
            sites.sort(key=lambda k: sum(rank[k]) / len(rank[k]) if rank[k] else 0.5)
            month_docs.sort(key=lambda d: d[5])
            if len(sites) <= 12 and len(month_docs) <= len(sites):
                best = min(itertools.combinations(sites, len(month_docs)), key=lambda perm: sum(cost(d, k) for d, k in zip(month_docs, perm)))
                for d, k in zip(month_docs, best):
                    res[d[0]] = k
            else:
                for d in month_docs:
                    res[d[0]] = min(sites, key=lambda k: cost(d, k))
    return res


# ------------------------------------------------------------------ coding
def company_country(kb, company):
    return next((c["country"] for c in kb.companies if c["code"] == company), "ES")


def nonpo_coding(kb, hist, hdr, ln, src):
    v = kb.vendors.get(hdr["vendor_id"]) or {}
    acc = v.get("default_gl_account")
    tax = v.get("default_tax_code")
    ctry = company_country(kb, hdr["company"])
    # tax code adjustments by company country (intercompany / foreign)
    if ctry == "PT" and tax == "S21":
        tax = "PSIS"
    if ctry == "MX" and tax == "S21":
        tax = "M00"
    d = strip_acc(ln["desc"])
    dk = hist.desc.get((hdr["vendor_id"], hdr["company"], desc_sig(ln["desc"])))
    dtop = dk.most_common(1)[0] if dk else None
    if dtop:
        acc, tax = dtop[0][0], dtop[0][3]
    elif ("no sujeto" in d or "canon" in d and "sujeto" in d or d.startswith("suplido")) and acc != "63100000":
        acc, tax = "63100000", "SEX"
    # cost object from history
    k = (hdr["vendor_id"], hdr["company"])
    cc = wbs = None
    h = hist.cost.get(k)
    ms = getattr(hist, "site_of", {}).get(hdr.get("_doc_id"))
    src_acc = "desc_hist" if dtop else "vendor_default"
    # explicit obra (project) named in the line description or in the document "Obra:" label
    obra_wbs = None
    txt = strip_acc(ln["desc"])
    for pid, pr in kb.projects.items():
        if pr["company"] != hdr["company"]:
            continue
        pn = strip_acc(pr["name"])
        if pn and (pn[:25] in txt or (hdr.get("_obra") and pn.startswith(hdr["_obra"][:25]))):
            wbs_ids = [w["id"] for w in pr.get("wbs", [])]
            hist_w = [k[2] for k in (dk or {}) if k[2] and k[2].startswith(pid)]
            obra_wbs = hist_w[0] if hist_w else (f"{pid}.05" if f"{pid}.05" in wbs_ids else (wbs_ids[-1] if wbs_ids else None))
            break
    if acc is None:
        src_co = "none"
    elif acc.startswith("47"):
        src_co = "n/a"
    elif obra_wbs:
        cc, wbs = None, obra_wbs
        src_co = "obra_named"
    elif ms:
        cc, wbs = ms[1], ms[2]
        src_co = "site_assign"
    elif dtop and dtop[1] >= 2 and (dtop[0][1] or dtop[0][2]):
        cc, wbs = dtop[0][1], dtop[0][2]
        src_co = "desc_hist"
    elif h:
        top = h.most_common(1)[0][0]
        cc, wbs = top[1], top[2]
        src_co = "vendor_hist_top" if len(h) == 1 or h.most_common(1)[0][1] / sum(h.values()) > 0.6 else "vendor_hist_top_ambiguous"
    else:
        # fall back: company admin cost center
        cand = [c for c in kb.cc if c.startswith(f"CC-{hdr['company']}-ADM")]
        cc = cand[0] if cand else None
        src_co = "fallback_ADM"
    nonpo_coding.last_source = f"{src_acc}/{src_co}"
    return acc, cc, wbs, tax


CN_PREFIX = re.compile(r"^(anulacion parcial|regularizacion de precio|devolucion|abono|rectificacion)\s*", re.I)


def original_number(doc, src):
    if doc.get("facturae") and doc["facturae"].get("corrective_of"):
        return doc["facturae"]["corrective_of"]
    for p in doc["pdf"]:
        for l in p["raw_lines"]:
            m = re.search(r"Rectifica la factura n[ºo°]\s*([^\s.]+(?:\.[^\s.]+)*)\.?", l)
            if m:
                return m.group(1).rstrip(".")
    return None


def original_coding(kb, hist, month_out, hdr, number):
    """List of (desc, acc, cc, wbs, tax, amount) from the original invoice (this month's output, else history JE)."""
    if not number:
        return []
    key = (hdr["vendor_id"], nn(number))
    if key in month_out:
        return [(l["_desc"], l["account"], l["cost_center"], l["wbs"], l["tax_code"], l["amount"]) for l in month_out[key]]
    if key in hist.by_vendor_number:
        a, je = hist.by_vendor_number[key]
        res = []
        for l in je["lines"]:
            amt = l["debit"] - l["credit"]
            if l["account"] == "40090000" and l.get("assignment") and "/" in l["assignment"]:
                po, it = l["assignment"].split("/")
                p = kb.pos.get(po)
                item = next((i for i in p["items"] if str(i["item"]) == it), None) if p else None
                if item:
                    res.append((item["description"], item["gl_account"], item["cost_center"], item["wbs"], item["tax_code"], amt))
            elif l["account"][0] in "62" and (l["cost_center"] or l["wbs"]):
                res.append((l.get("text") or "", l["account"], l["cost_center"], l["wbs"], l["tax_code"], amt))
        return res
    return []


def code_credit_note(kb, hist, month_out, doc, hdr, src):
    orig = original_coding(kb, hist, month_out, hdr, original_number(doc, src))
    out = []
    for ln in src.get("lines") or []:
        amt = abs(ln["amount"])
        d = strip_acc(CN_PREFIX.sub("", strip_acc(ln["desc"])))
        best = None
        for od, acc, cc, wbs, tax, oamt in orig:
            o = strip_acc(od)
            sc = (3 if o and (o in d or d in o) else 0) + (len(toks(o) & toks(d)) / max(1, len(toks(o)))) + abs(oamt) / 1e12
            if best is None or sc > best[0]:
                best = (sc, acc, cc, wbs, tax)
        if best:
            _, acc, cc, wbs, tax = best
            srcname = "cn_original"
        else:
            acc, cc, wbs, tax = nonpo_coding(kb, hist, hdr, ln, src)
            srcname = "cn_no_original/" + nonpo_coding.last_source
        out.append(dict(amount=amt, account=acc, cost_center=cc, wbs=wbs, tax_code=tax, po=None, po_item=None, goods_receipts=[], _gr_amount=None, _desc=ln["desc"], _src=srcname))
    return out


def code_document(kb, hist, pom, doc, hdr, src, gold_doc_type=None, month_out=None):
    lines = src.get("lines") or []
    if gold_doc_type == "CREDIT_NOTE":
        return code_credit_note(kb, hist, month_out or {}, doc, hdr, src)
    matches = pom.match(doc, hdr, lines)
    out = []
    for ln, m in zip(lines, matches):
        amt = abs(ln["amount"])
        if m:
            p, it, g = m
            acc = it["gl_account"]
            if gold_doc_type == "DOWN_PAYMENT_REQUEST":
                acc = "40700000"
            out.append(dict(amount=amt, account=acc, cost_center=it["cost_center"], wbs=it["wbs"], tax_code=it["tax_code"],
                            po=p["id"], po_item=it["item"], goods_receipts=[g["id"]] if g else [], _gr_amount=g["amount"] if g else None, _desc=ln["desc"],
                            _src="po_item+gr" if g else "po_item_no_gr"))
        else:
            acc, cc, wbs, tax = nonpo_coding(kb, hist, hdr, ln, src)
            out.append(dict(amount=amt, account=acc, cost_center=cc, wbs=wbs, tax_code=tax, po=None, po_item=None, goods_receipts=[], _gr_amount=None, _desc=ln["desc"], _src=nonpo_coding.last_source))
    # non-PO lines on an invoice that also has PO lines inherit the PO lines' cost object (history: O&M "correctivo")
    pos_co = {(l["cost_center"], l["wbs"]) for l in out if l["po"]}
    if len(pos_co) == 1:
        cc, wbs = next(iter(pos_co))
        for l in out:
            if not l["po"] and l["account"] and l["account"][0] in "62" and (l["cost_center"], l["wbs"]) != (cc, wbs):
                l["cost_center"], l["wbs"] = cc, wbs
                l["_src"] = l["_src"].split("/")[0] + "/inherit_po_line"
    return out


# ------------------------------------------------------------------ journal entry
def fx_factor(kb, cur, local, date):
    if cur == local:
        return 1.0
    r_doc = 1.0 if cur == "EUR" else kb.rate("EUR", cur, date)[0]
    r_loc = 1.0 if local == "EUR" else kb.rate("EUR", local, date)[0]
    return r_loc / r_doc


def wht_split(kb, hdr, src, doc):
    """Return list of (code, amount_doc)."""
    total = hdr["withholding"]
    if not total:
        return []
    v = kb.vendors.get(hdr["vendor_id"]) or {}
    codes = (v.get("withholding") or "").split("+") if v.get("withholding") else []
    if len(codes) <= 1:
        return [(codes[0] if codes else "WHT", total)]
    W = kb.tax["withholdings"]
    parts = [(c, round(hdr["net"] * W[c]["rate"] / 10000)) for c in codes]
    diff = total - sum(a for _, a in parts)
    parts[-1] = (parts[-1][0], parts[-1][1] + diff)
    return parts


def build_je(kb, hdr, lines, src, doc, doc_type):
    company = hdr["company"]
    local = next((c["currency"] for c in kb.companies if c["code"] == company), "EUR")
    f = fx_factor(kb, hdr["currency"], local, hdr["invoice_date"])
    conv = lambda a: round(a * f)
    v = kb.vendors.get(hdr["vendor_id"]) or {}
    vend = hdr["vendor_id"]
    TC = kb.tax["tax_codes"]
    J = []  # (account, signed_local, partner, cc, wbs)

    def add(acc, amt, partner=None, cc=None, wbs=None):
        if amt:
            J.append([acc, amt, partner, cc, wbs])

    for l in lines:
        if l["po"] and not l["goods_receipts"] and kb.gr_by_po.get((l["po"], l["po_item"])) and l["account"] != "40700000":
            # GR-based item whose receipt is not (yet) in the data: clear GR/IR at invoice value
            add("40090000", conv(l["amount"]), vend)
        elif l["po"] and l["goods_receipts"] and l["_gr_amount"] is not None:
            gr = l["_gr_amount"]
            add("40090000", gr, vend)
            diff = conv(l["amount"]) - gr
            if diff:
                add(l["account"], diff, None, l["cost_center"], l["wbs"])
        elif l["account"] == "40700000":
            add("40700000", conv(l["amount"]))
        else:
            add(l["account"], conv(l["amount"]), None, l["cost_center"], l["wbs"])
    # VAT
    base_by_tc = defaultdict(int)
    for l in lines:
        base_by_tc[l["tax_code"]] += l["amount"]
    input_tcs = [tc for tc in base_by_tc if TC.get(tc, {}).get("kind") in INPUT_KINDS]
    for tc, base in base_by_tc.items():
        kind = TC.get(tc, {}).get("kind")
        if kind in REVERSE_KINDS:
            t = conv(round(base * TC[tc]["rate"] / 10000))
            add("47210000", t)
            add("47710000", -t)
    if input_tcs:
        if len(input_tcs) == 1:
            add("47200000", conv(hdr["tax"]))
        else:
            # split printed tax by rate
            for tc in input_tcs:
                add("47200000", conv(round(base_by_tc[tc] * TC[tc]["rate"] / 10000)))
    # withholdings
    for code, a in wht_split(kb, hdr, src, doc):
        add("47510000", -conv(a))
    if hdr["retention"]:
        add("40000900", -conv(hdr["retention"]), vend)
    # vendor line absorbs rounding
    bal = sum(x[1] for x in J)
    add(v.get("reconciliation_account", "40000000"), -bal, vend)
    if doc_type == "CREDIT_NOTE":
        for x in J:
            x[1] = -x[1]
    out = []
    for acc, amt, p, cc, w in J:
        out.append(dict(account=acc, debit=amt if amt > 0 else 0, credit=-amt if amt < 0 else 0, partner=p, cost_center=cc, wbs=w))
    return dict(company=company, lines=out)


# ------------------------------------------------------------------ document type (used when no golden)
def detect_doc_type(doc, hdr):
    t = " ".join((p.get("title") or "") for p in doc["pdf"]).upper()
    if doc.get("cfdi") and doc["cfdi"].get("tipo") == "E":
        return "CREDIT_NOTE"
    if doc.get("facturae") and (doc["facturae"].get("corrective_of") or doc["facturae"].get("doc_class") in ("OR", "CR")):
        return "CREDIT_NOTE"
    if any(k in t for k in ("RECTIFICATIVA", "NOTA DE CR", "CREDIT NOTE", "ABONO")) or hdr.get("sign", 1) < 0:
        return "CREDIT_NOTE"
    if "DEPOSIT REQUEST" in t or "ANTICIPO" in t:
        return "DOWN_PAYMENT_REQUEST"
    if "PROFORMA" in t:
        return "PROFORMA"
    return "INVOICE"


# ------------------------------------------------------------------ driver
def run(P, only_ids=None, gold=None, independent=False):
    """Code every document of the phase directory ``P``; ``gold`` holds this run's own AP decisions."""
    kb, docs = load_phase(P)
    hist = History(kb)
    pom = POMatcher(kb)
    order = sorted(docs, key=lambda d: (docs[d]["message"].get("received_at", ""), d))
    out = {}
    month_out = {}
    # pre-pass: multi-site assignment for recurring utility-type vendors
    items = []
    for did in order:
        if only_ids is not None and did not in only_ids:
            continue
        if ((gold or {}).get(did, {}).get("document_type") or "INVOICE") != "INVOICE":
            continue
        try:
            h, _ = extract_header(kb, docs[did])
        except Exception:
            continue
        if h["vendor_id"] and h["invoice_date"] and h["net"] is not None:
            items.append((did, h["vendor_id"], h["company"], h["invoice_date"], h["net"], nn(h["invoice_number"])))
    hist.site_of = multisite_assign(hist, items)
    for did in order:
        if only_ids is not None and did not in only_ids:
            continue
        doc = docs[did]
        g = (gold or {}).get(did, {})
        try:
            hdr, src = extract_header(kb, doc)
            hdr["_doc_id"] = did
            hdr["_obra"] = next((strip_acc(p["obra"]) for p in doc["pdf"] if p.get("obra")), None)
            if independent:
                pom.used = set()
            dtype = g.get("document_type") or detect_doc_type(doc, hdr)
            lines = code_document(kb, hist, pom, doc, hdr, src, dtype, month_out)
            month_out[(hdr["vendor_id"], nn(hdr["invoice_number"]))] = lines
            je = build_je(kb, hdr, lines, src, doc, dtype)
        except Exception as e:  # noqa
            print("ERR", did, repr(e))
            out[did] = {"doc_id": did, "error": repr(e)}
            continue
        row = {"doc_id": did, "document_type": dtype, "decision": g.get("decision", "POST"), "reasons": g.get("reasons", []),
               **{k: hdr[k] for k in ("company", "vendor_id", "invoice_number", "invoice_date", "currency", "net", "tax", "gross", "withholding", "retention", "payable")},
               "duplicate_of": None, "payee": g.get("payee"), "payment_block": g.get("payment_block"), "action": None,
               "lines": [{k: v for k, v in l.items() if not k.startswith("_")} for l in lines], "journal_entry": je,
               "_debug": [l["_desc"] for l in lines], "_src": [l.get("_src") for l in lines]}
        out[did] = row
    return out, kb, docs
