"""Load ERP masters + history for one phase."""
import json
import os
import re
from collections import defaultdict


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def norm_id(s):
    s = re.sub(r"[^0-9A-Z]", "", str(s or "").upper())
    for pre in ("ES", "PT"):
        if s.startswith(pre) and len(s) > 9:
            s = s[len(pre):]
    return s


class KB:
    def __init__(self, phase_dir):
        self.dir = phase_dir
        e = lambda f: os.path.join(phase_dir, "erp", f)
        self.companies = json.load(open(e("companies.json")))
        self.comp_by_tax = {}
        for c in self.companies:
            for k in ("tax_id", "vat_id"):
                if c.get(k):
                    self.comp_by_tax[norm_id(c[k])] = c["code"]
        self.vendors = {v["id"]: v for v in jl(e("vendors.jsonl"))}
        self.vend_by_tax = defaultdict(list)
        for v in self.vendors.values():
            for k in ("tax_id", "vat_id"):
                if v.get(k):
                    if v["id"] not in self.vend_by_tax[norm_id(v[k])]:
                        self.vend_by_tax[norm_id(v[k])].append(v["id"])
        self.tax = json.load(open(e("tax_codes.json")))
        self.pos = {p["id"]: p for p in jl(e("purchase_orders.jsonl"))}
        self.grs = jl(e("goods_receipts.jsonl"))
        self.gr_by_id = {g["id"]: g for g in self.grs}
        self.gr_by_po = defaultdict(list)
        for g in self.grs:
            self.gr_by_po[(g["po"], g["po_item"])].append(g)
        self.ap_inv = jl(e("ap_invoices.jsonl"))
        self.ap_log = jl(e("ap_document_log.jsonl"))
        self.cc = {c["id"]: c for c in jl(e("cost_centers.jsonl"))}
        self.projects = {p["id"]: p for p in jl(e("projects.jsonl"))}
        self.fx = defaultdict(dict)
        for r in jl(e("fx_rates.jsonl")):
            self.fx[(r["base"], r["currency"])][r["date"]] = r["rate"]
        self.coa = {a["account"] if "account" in a else a.get("id"): a for a in jl(e("chart_of_accounts.jsonl"))}
        self._je = None

    @property
    def je(self):
        if self._je is None:
            self._je = {}
            with open(os.path.join(self.dir, "erp", "journal_entries.jsonl"), encoding="utf-8") as f:
                for l in f:
                    j = json.loads(l)
                    if j.get("source") in ("AP",) or j.get("doc_type") in ("KR", "KG"):
                        self._je[j["id"]] = j
        return self._je

    def rate(self, base, cur, date):
        """SYN-BCE rate for date or last published before."""
        tab = self.fx.get((base, cur), {})
        if date in tab:
            return tab[date], date
        ds = sorted(d for d in tab if d <= date)
        return (tab[ds[-1]], ds[-1]) if ds else (None, None)
