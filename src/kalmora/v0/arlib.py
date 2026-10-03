"""AR billing prototype (Kalmora hackathon) - research code, not production.

Pure rules: parse the billing document (PDF text) into a normalised dict shaped like
erp/billing_history.jsonl, then compute invoice + journal entry from contract master data.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import re
from collections import defaultdict

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
RATE_BP = {"R21": 2100, "R10": 1000, "RISP": 0, "REX": 0, "PR23": 2300, "PR06": 600, "PRAUT": 0, "MR16": 1600}
REVENUE_ACC = {"OBRA_CERTIFICATION": "70510000", "SERVICE_MONTHLY": "70500000", "PRICE_REVISION": "70520000",
               "PPA": "70530000", "MARKET_SETTLEMENT": "70530000"}
LEGEND = {"RISP": "Operación con inversión del sujeto pasivo, art. 84.Uno.2º f) LIVA",
          "PRAUT": "IVA - autoliquidação, art. 2.º n.º 1 j) CIVA"}

# Spanish national holidays (what the history needs; PPA/MKT invoice dates roll over them)
HOLIDAYS = {f"{y}-{md}" for y in range(2024, 2028) for md in
            ("01-01", "01-06", "05-01", "08-15", "10-12", "11-01", "12-06", "12-08", "12-25")}
HOLIDAYS |= {"2024-03-29", "2025-04-18", "2026-04-03", "2027-03-26"}  # Viernes Santo


# ------------------------------------------------------------------ helpers
def rhu(num: int, den: int) -> int:
    """round half up (away from zero) of num/den with integers."""
    sign = -1 if (num < 0) != (den < 0) else 1
    num, den = abs(num), abs(den)
    return sign * ((2 * num + den) // (2 * den))


def last_day(month: str) -> str:
    y, m = map(int, month.split("-"))
    return dt.date(y, m, calendar.monthrange(y, m)[1]).isoformat()


def add_days(d: str, n: int) -> str:
    return (dt.date.fromisoformat(d) + dt.timedelta(days=n)).isoformat()


def next_business_day(d: dt.date) -> dt.date:
    while d.weekday() >= 5 or d.isoformat() in HOLIDAYS:
        d += dt.timedelta(days=1)
    return d


def parse_money(s: str) -> int:
    """'1.234.567,89' / '-14.603,36' / '41.50' / '2,737.65' -> cents."""
    s = s.strip().replace(" ", "").replace(" ", "")
    neg = s.startswith("-") or s.startswith("−")
    s = s.lstrip("-−")
    m = re.match(r"^([\d.,]*?)(?:[.,](\d{1,2}))?$", s)
    ip, dp = m.group(1), m.group(2) or ""
    v = int(re.sub(r"\D", "", ip) or 0) * 100 + int((dp + "00")[:2])
    return -v if neg else v


def parse_milli(s: str) -> int:
    """MWh with exactly 3 decimals in either locale ('8.652,582', '2,737.647') -> milli-MWh."""
    s = s.strip()
    m = re.match(r"^(-?)([\d.,]*?)[.,](\d{3})$", s)
    if not m:  # integer MWh
        return int(re.sub(r"\D", "", s)) * 1000
    return int(re.sub(r"\D", "", m.group(2)) or 0) * 1000 + int(m.group(3))


def load_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


# ------------------------------------------------------------------ context
class Ctx:
    def __init__(self, phase_dir: str):
        e = f"{phase_dir}/erp"
        self.phase_dir = phase_dir
        self.contracts = {c["id"]: c for c in load_jsonl(f"{e}/sales_contracts.jsonl")}
        self.customers = {c["id"]: c for c in load_jsonl(f"{e}/customers.jsonl")}
        self.projects = {p["id"]: p for p in load_jsonl(f"{e}/projects.jsonl")}
        self.cost_centers = {c["id"]: c for c in load_jsonl(f"{e}/cost_centers.jsonl")}
        self.history = load_jsonl(f"{e}/billing_history.jsonl")
        self.ar_invoices = load_jsonl(f"{e}/ar_invoices.jsonl")
        # advance (anticipo) balance per (company, customer) from GL 43800000 (credit balance -> positive)
        self.adv_balance = defaultdict(int)
        with open(f"{e}/journal_entries.jsonl", encoding="utf-8") as f:
            for l in f:
                j = json.loads(l)
                for x in j["lines"]:
                    if x["account"] == "43800000":
                        self.adv_balance[(j["company"], x["partner"])] += x["credit"] - x["debit"]
        # catalogue of full extra-service descriptions (PDF truncates them)
        self.extra_desc = sorted({x["desc"] for h in self.history if h["type"] == "SERVICE_MONTHLY"
                                  for x in h["extra_services"]}, key=len, reverse=True)
        self._numbers = None

    # last approved cumulative for a contract (from billing history) -> 'anterior'
    def last_approved_cumulative(self, contract: str, before_month: str):
        best = None
        for h in self.history:
            if h["type"] == "OBRA_CERTIFICATION" and h["contract"] == contract and h["month"] < before_month \
                    and h["cert"]["approved"]:
                if best is None or h["month"] > best["month"]:
                    best = h
        return (best["cert"]["cumulative"], best["cert"]["number"]) if best else (0, 0)

    def fees_billed(self, contract: str):
        return {h["month"]: h["fee"] for h in self.history if h["type"] == "SERVICE_MONTHLY" and h["contract"] == contract}

    # invoice numbering: fill gaps in this year's series first (ERP reserves them), then max+1
    def next_number(self, company: str, year: int, kind: str) -> str:
        yy = str(year)[2:]
        prefix = {"1100": f"OB{yy}-", "1200": f"SU{yy}-", "1300": f"EN{yy}-", "1910": f"UL9-{yy}-",
                  "2100": f"FT OB{yy}-", "3100": f"EST-{year}-"}[company]
        if self._numbers is None:
            self._numbers = defaultdict(set)
            for r in self.ar_invoices:
                m = re.match(r"^(.*?)(\d+)$", r["id"])
                self._numbers[m.group(1)].add(int(m.group(2)))
        used = self._numbers[prefix]
        n = next((i for i in range(1, max(used, default=0) + 1) if i not in used), max(used, default=0) + 1)
        used.add(n)
        return f"{prefix}{n:05d}"


# ------------------------------------------------------------------ PDF -> normalised doc
def pdf_text(path: str) -> str:
    import pypdf
    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(path).pages)


def parse_document(item: dict, text: str) -> dict:
    t = item["type"]
    flat = re.sub(r"\s+", " ", text)
    doc = {k: item[k] for k in ("billing_item", "type", "company", "contract", "customer", "month")}
    if t == "OBRA_CERTIFICATION":
        lines = [{"desc": d.strip(), "chapter": n, "amount": parse_money(a)}
                 for d, n, a in [(m.group(1), m.group(2), m.group(3)) for m in
                                 re.finditer(r"(Cap[ií]tulo (\d{2}) [–-] [^\n]+)\n(-?[\d.,]+) (?:EUR|MXN)", text)]]
        g = lambda lab: parse_money(re.search(lab + r":\s*(-?[\d.,]+)", flat).group(1))
        status_block = flat.split("Revisión de precios no incluida.")[-1]
        approved = bool(re.search(r"\bCONFORME\b", status_block)) and "PENDIENTE" not in status_block.upper()
        num = re.search(r"N[ºo°]\s*(\d+)", flat)
        appr_date = re.search(r"(\d{2})/(\d{2})/(\d{4})", status_block)
        doc["cert"] = {"number": int(num.group(1)) if num else None,
                       "cumulative": g("Certificado a origen"), "previous": g("Certificado anterior"),
                       "current": g("Importe de la presente certificación"), "approved": approved,
                       "approved_on": f"{appr_date.group(3)}-{appr_date.group(2)}-{appr_date.group(1)}" if appr_date and approved else None,
                       "lines": lines, "currency": "MXN" if " MXN" in text else "EUR"}
    elif t == "SERVICE_MONTHLY":
        canon = re.search(r"Canon mensual\n[^\n]*\n(-?[\d.,]+) EUR\n([^\n]+)", text)
        extras = [{"desc": m.group(1).strip(), "order": m.group(2), "amount": parse_money(m.group(3)),
                   "approved": m.group(4).strip().lower() == "conforme", "status": m.group(4).strip()}
                  for m in re.finditer(r"([^\n]+)\n(OT-\d{4}-\d+)\n(-?[\d.,]+) EUR\n([^\n]+)", text)]
        doc["fee"] = parse_money(canon.group(1))
        doc["fee_status"] = canon.group(2).strip()
        doc["extra_services"] = extras
    elif t == "PRICE_REVISION":
        m = re.search(r"nuevo canon mensual en (-?[\d.,]+) EUR \(anterior: (-?[\d.,]+) EUR\)", flat)
        months = re.findall(r"\d{4}-\d{2}(?!-)", re.search(r"desde la fecha de efectos \(([^)]*)\)", flat).group(1))
        doc["revision"] = {"new_fee": parse_money(m.group(1)), "old_fee": parse_money(m.group(2)),
                           "effective": re.search(r"con efectos (\d{4}-\d{2}-\d{2})", flat).group(1),
                           "approved_on": re.search(r"Fecha de aprobación: (\d{4}-\d{2}-\d{2})", flat).group(1),
                           "months": months, "decree": (re.search(r"(Decreto de [^\n]+?\d{4}/\d+)", text) or [None, None])[1]}
    elif t == "PPA":
        plants = [{"name": m.group(1).strip(), "mwh_milli": parse_milli(m.group(2))}
                  for m in re.finditer(r"(PSF [^\n]+?\))\n([\d.,]+)\s*\n", text)]
        doc["production"] = {"period": re.search(r"Periodo:?\s*(\d{4}-\d{2})", flat).group(1), "plants": plants,
                             "share_bp": int(re.search(r"en el PPA:\s*(\d+(?:[.,]\d+)?)\s*%", flat).group(1).replace(",", ".").split(".")[0]) * 100,
                             "price_cents": parse_money(re.search(r"Precio fijo:\s*([\d.,]+)", flat).group(1))}
    elif t == "MARKET_SETTLEMENT":
        plants = [{"name": m.group(1).strip(), "mwh_milli": parse_milli(m.group(2)), "amount": parse_money(m.group(3))}
                  for m in re.finditer(r"(PSF [^\n]+?\))\n([\d.,]+)\n(-?[\d.,]+) EUR", text)]
        dev = re.search(r"desv[ií]os[^:]*:\s*(-?[\d.,]+)", flat)
        doc["settlement"] = {"period": re.search(r"Periodo:?\s*(\d{4}-\d{2})", flat).group(1), "plants": plants,
                             "deviations": -abs(parse_money(dev.group(1))) if dev else 0,
                             "avg_price": re.search(r"Precio medio ponderado:\s*([\d.,]+)", flat).group(1)}
    return doc


# ------------------------------------------------------------------ compute invoice
def plant_cc(ctx: Ctx, name: str, company: str):
    for c in ctx.cost_centers.values():
        if c["company"] == company and c["desc"] == name:
            return c["id"]
    return None


def compute(ctx: Ctx, doc: dict, number: str | None = None, adv_remaining: int | None = None):
    """Returns (row for ar_billing.jsonl, close row or None, review flags)."""
    t, company, contract_id = doc["type"], doc["company"], doc["contract"]
    k = ctx.contracts[contract_id]
    cust = ctx.customers[doc["customer"]]
    flags = []
    if k["customer"] != doc["customer"]:
        flags.append(f"CUSTOMER_MISMATCH contract={k['customer']} item={doc['customer']}")
    tax_code = k["tax"]
    currency = cust.get("currency", "EUR")
    lines = []
    month = doc["month"]
    y, m = map(int, month.split("-"))

    if t == "OBRA_CERTIFICATION":
        c = doc["cert"]
        proj = k["project"]
        # checks
        if sum(l["amount"] for l in c["lines"]) != c["current"]:
            flags.append(f"CHAPTERS_SUM {sum(l['amount'] for l in c['lines'])} != current {c['current']}")
        if c["cumulative"] - c["previous"] != c["current"]:
            flags.append(f"ORIGEN_MINUS_ANTERIOR {c['cumulative'] - c['previous']} != current {c['current']}")
        prev_ok, prev_num = ctx.last_approved_cumulative(contract_id, month)
        if prev_ok and prev_ok != c["previous"]:
            flags.append(f"ANTERIOR_vs_HISTORY pdf={c['previous']} last_approved_cum={prev_ok}")
        net_calc = c["cumulative"] - (prev_ok or c["previous"])
        if not c["approved"]:
            close = {"type": "WIP_REVENUE", "company": company, "billing_item": doc["billing_item"], "amount": net_calc,
                     "journal_entry": {"company": company, "lines": [
                         {"account": "43090000", "debit": net_calc, "credit": 0, "partner": doc["customer"],
                          "cost_center": None, "wbs": None},
                         {"account": "71300000", "debit": 0, "credit": net_calc, "partner": None,
                          "cost_center": None, "wbs": f"{proj}.01"}]}}
            flags.append("PENDING_APPROVAL -> WIP_REVENUE")
            return {"billing_item": doc["billing_item"], "expected": "SKIP_PENDING_APPROVAL"}, close, flags
        date = last_day(month)
        for l in c["lines"]:
            lines.append({"description": l["desc"], "amount": l["amount"], "account": "70510000",
                          "cost_center": None, "wbs": f"{proj}.{l['chapter']}"})
    elif t == "SERVICE_MONTHLY":
        date = last_day(month)
        if doc.get("fee_status", "Conforme").lower() != "conforme":
            flags.append(f"CANON_STATUS {doc.get('fee_status')}")
        lines.append({"description": f"{k['name']} – servicio de {MESES[m - 1]} de {y} (canon mensual)",
                      "amount": doc["fee"], "account": "70500000", "cost_center": k["cc"], "wbs": None})
        last_fee = max(ctx.fees_billed(contract_id).items(), default=(None, None))[1]
        if last_fee is not None and last_fee != doc["fee"]:
            flags.append(f"CANON_CHANGED vs last billed {last_fee} -> {doc['fee']} (revision?)")
        for x in doc["extra_services"]:
            if not x["approved"]:
                flags.append(f"EXTRA_WITHOUT_CONFORMITY {x['order']} {x['amount']} excluded")
                continue
            full = next((d for d in ctx.extra_desc if d.startswith(x["desc"])), x["desc"])
            lines.append({"description": full, "amount": x["amount"], "account": "70500000",
                          "cost_center": k["cc"], "wbs": None})
    elif t == "PRICE_REVISION":
        r = doc["revision"]
        date = add_days(r["approved_on"], 3)
        diff = r["new_fee"] - r["old_fee"]
        billed = ctx.fees_billed(contract_id)
        for mo in r["months"]:
            if mo in billed and billed[mo] != r["old_fee"]:
                flags.append(f"REV_OLD_FEE_MISMATCH {mo}: billed {billed[mo]} vs decree old {r['old_fee']}")
            yy, mm = map(int, mo.split("-"))
            lines.append({"description": f"Revisión de precios {r['effective'][:4]} – {k['name']} – diferencia {MESES[mm - 1]} {yy}",
                          "amount": diff, "account": "70520000", "cost_center": k["cc"], "wbs": None})
        exp_months = []
        ey, em = map(int, r["effective"][:7].split("-"))
        ay, am = map(int, r["approved_on"][:7].split("-"))
        while (ey, em) < (ay, am):
            exp_months.append(f"{ey}-{em:02d}")
            em += 1
            if em == 13:
                ey, em = ey + 1, 1
        if exp_months != r["months"]:
            flags.append(f"REV_MONTHS listed={r['months']} expected={exp_months}")
    elif t == "PPA":
        p = doc["production"]
        tot = sum(x["mwh_milli"] for x in p["plants"])
        share_bp = p.get("share_bp") or k["share_bp"]
        price = p.get("price_cents") or k["price_mwh"]
        if share_bp != k["share_bp"] or price != k["price_mwh"]:
            flags.append(f"PPA_TERMS_vs_CONTRACT doc={share_bp}/{price} contract={k['share_bp']}/{k['price_mwh']}")
        mwh = tot * share_bp // 10000                      # truncate MWh to 3 decimals
        amount = mwh * price // 1000                        # truncate to the cent
        py, pm = map(int, p["period"].split("-"))
        date = next_business_day(dt.date(y, m, 3)).isoformat()
        mwh_s = f"{mwh // 1000:,}".replace(",", ".") + f",{mwh % 1000:03d}"
        lines.append({"description": f"Energía suministrada PPA {pm:02d}/{py}: {mwh_s} MWh × {price // 100},{price % 100:02d} €/MWh",
                      "amount": amount, "account": "70530000", "cost_center": k["plants"][0], "wbs": None})
    elif t == "MARKET_SETTLEMENT":
        s = doc["settlement"]
        py, pm = map(int, s["period"].split("-"))
        date = next_business_day(dt.date(y, m, 6)).isoformat()
        for x in s["plants"]:
            cc = x.get("plant") or plant_cc(ctx, x["name"], company)
            lines.append({"description": f"Venta de energía en mercado {pm:02d}/{py} – {x['name']}", "amount": x["amount"],
                          "account": "70530000", "cost_center": cc, "wbs": None})
        if s["deviations"]:
            lines.append({"description": f"Coste de desvíos {pm:02d}/{py}", "amount": s["deviations"],
                          "account": "70530000", "cost_center": f"CC-{company}-ADM", "wbs": None})
    else:
        raise ValueError(t)

    net = sum(l["amount"] for l in lines)
    tax = rhu(net * RATE_BP[tax_code], 10000)
    gross = net + tax
    retention = rhu(net * k.get("retention_bp", 0), 10000)
    deductions = []
    if k.get("mx5mill"):
        deductions.append({"code": "MX5MILL", "amount": rhu(net * 50, 10000), "account": "63100000"})
    if k.get("advance_bp"):
        want = rhu(gross * k["advance_bp"], 10000)
        remaining = adv_remaining if adv_remaining is not None else ctx.adv_balance.get((company, doc["customer"]), 0)
        amt = max(0, min(want, remaining))
        if amt != want:
            flags.append(f"ADVANCE_CAPPED want={want} remaining={remaining}")
        if amt:
            deductions.append({"code": "ADV_AMORT", "amount": amt, "account": "43800000"})
    payable = gross - retention - sum(d["amount"] for d in deductions)
    due = add_days(date, k["terms_days"])
    face = None
    if cust.get("country") == "ES" and cust.get("kind") == "public":
        if cust.get("dir3"):
            face = {kk: cust["dir3"][kk] for kk in ("oficina_contable", "organo_gestor", "unidad_tramitadora")}
        else:
            flags.append("PUBLIC_ES_WITHOUT_DIR3")
    number = number or ctx.next_number(company, int(date[:4]), t)
    inv = {"number": number, "date": date, "due_date": due, "tax_code": tax_code, "net": net, "tax": tax, "gross": gross,
           "retention": retention, "deductions": deductions, "payable": payable, "currency": currency, "face": face,
           "lines": lines}
    if tax_code in LEGEND:
        inv["legend"] = LEGEND[tax_code]
    je = [{"account": "43000000", "debit": payable, "credit": 0, "partner": doc["customer"], "cost_center": None,
           "wbs": None, "assignment": number, "text": f"Factura {number}"}]
    if retention:
        je.append({"account": "43000900", "debit": retention, "credit": 0, "partner": doc["customer"], "cost_center": None,
                   "wbs": None, "assignment": number, "text": "Retención de garantía 5 %"})
    for d in deductions:
        je.append({"account": d["account"], "debit": d["amount"], "credit": 0,
                   "partner": doc["customer"] if d["account"].startswith("43") else None, "cost_center": None, "wbs": None,
                   "text": "Derecho de inspección 5 al millar" if d["code"] == "MX5MILL" else "Amortización de anticipo"})
    for l in lines:
        a = l["amount"]
        je.append({"account": l["account"], "debit": max(0, -a), "credit": max(0, a), "partner": None,
                   "cost_center": l["cost_center"], "wbs": l["wbs"], "tax_code": tax_code, "text": l["description"][:50]})
    if tax:
        je.append({"account": "47700000", "debit": 0, "credit": tax, "partner": None, "cost_center": None, "wbs": None,
                   "tax_code": tax_code, "text": f"IVA repercutido {tax_code}"})
    assert sum(x["debit"] for x in je) == sum(x["credit"] for x in je), doc["billing_item"]
    row = {"billing_item": doc["billing_item"], "expected": "INVOICE", "invoice": inv,
           "journal_entry": {"company": company, "posting_date": date, "currency": currency, "reference": number, "lines": je}}
    return row, None, flags
