"""Open GR/IR per PO item, from the journal (GR credits minus invoice debits on 40090000)."""
from collections import defaultdict
import json, os


def open_grs(kb, all_je_path=None):
    # invoice clearings: 40090000 debits from AP entries, by (company, assignment)
    cleared = defaultdict(list)
    for je in kb.je.values():
        for l in je["lines"]:
            if l["account"] == "40090000" and l.get("assignment") and "/" in l["assignment"]:
                amt = l["debit"] - l["credit"]
                if amt > 0:
                    cleared[(je["company"], l["assignment"])].append(amt)
                elif amt < 0:  # credit-note reversal of clearing re-opens
                    cleared[(je["company"], l["assignment"])].append(amt)
    res = {}
    for (po, it), grs in kb.gr_by_po.items():
        grs = sorted(grs, key=lambda g: (g["posting_date"], g["id"]))
        comp = grs[0]["company"]
        cl = list(cleared.get((comp, f"{po}/{it}"), []))
        open_ = list(grs)
        # remove exact-amount matches first, oldest GR first
        rest = []
        for a in sorted([x for x in cl if x > 0]):
            m = next((g for g in open_ if g["amount"] == a), None)
            if m:
                open_.remove(m)
            else:
                rest.append(a)
        # remaining clearings (rounding/partial): consume oldest
        for a in rest:
            if open_:
                open_.pop(0)
        res[(po, it)] = open_
    return res
