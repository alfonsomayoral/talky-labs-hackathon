"""#88/#89: lossless local positions and separately comparable EUR positions."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from kalmora.ledger import Ledger
from kalmora.money import RateTable, integer

FAMILIES = {"43300000": "invoice", "40300000": "invoice", "40090000": "invoice",
            "55200000": "current_account", "24230000": "loan", "16330000": "loan",
            "55210000": "ute", "55220000": "ute"}


class Directory:
    """Master-backed aliases. Never infer a company by stripping 'V-IC'."""
    def __init__(self, companies: Iterable[dict], vendors=(), customers=()):
        self.companies = {r["code"]: dict(r) for r in companies}
        self.aliases = {c: c for c in self.companies}
        self.vendors = list(vendors)
        for row in [*self.vendors, *customers]:
            company = row.get("intercompany") or row.get("group")
            if not company:
                continue
            if company not in self.companies:
                raise ValueError(f"unknown company in partner master: {company}")
            alias = row["id"]
            if alias in self.aliases and self.aliases[alias] != company:
                raise ValueError(f"conflicting partner alias: {alias}")
            self.aliases[alias] = company

    def resolve(self, partner: str | None) -> str | None:
        return self.aliases.get(partner)

    def currency(self, company: str) -> str:
        return self.companies[company]["currency"]

    def vendor(self, issuer: str, receiver: str) -> dict | None:
        rows = [r for r in self.vendors if r.get("intercompany") == issuer
                and receiver in r.get("companies", [receiver])]
        if len(rows) > 1:
            raise ValueError("ambiguous intercompany vendor master")
        return rows[0] if rows else None


def signed_document_cents(line: dict) -> int:
    amount = integer(line["amount_doc"])
    local = integer(line["debit"]) - integer(line["credit"])
    if not local:
        if amount:
            raise ValueError("nonzero document amount has no debit/credit direction")
        return 0
    return abs(amount) if local > 0 else -abs(amount)


def is_valuation(entry: dict, explicit_ids=frozenset()) -> bool:
    return (entry.get("id") in explicit_ids
            or entry.get("source") in {"CLOSE_FX", "CLOSE_FX:reversal"}
            or entry.get("type") == "FX_REVAL")


def euro_cents(entry: dict, line: dict, directory: Directory, rates: RateTable,
               *, valuation_ids=frozenset()) -> tuple[int, bool]:
    """Use document EUR, not closing-rate division of accumulated local balances.

    Known local-only remeasurements affect local value, not foreign principal.
    The second return value marks such valuation-only lines for the audit.
    """
    local = integer(line["debit"]) - integer(line["credit"])
    currency = line.get("currency", entry.get("currency", directory.currency(entry["company"])))
    if is_valuation(entry, valuation_ids) and currency == directory.currency(entry["company"]) and currency != "EUR":
        return 0, True
    if "amount_doc" in line:
        amount = signed_document_cents(line)
    elif currency == directory.currency(entry["company"]):
        amount = local
    else:
        raise ValueError("foreign document line requires explicit amount_doc")
    day = entry.get("document_date") or entry.get("posting_date")
    if not day:
        raise ValueError("monetary comparison requires a document/posting date")
    return rates.convert_cents(amount, currency, "EUR", day), False


def snapshot(ledger: Ledger, directory: Directory, rates: RateTable, *, accounts: Iterable[str],
             pairs: Iterable[Iterable[str]], as_of: str, valuation_ids=frozenset()) -> dict:
    """Four-dimensional raw keys remain distinct even when aliases resolve equally."""
    date.fromisoformat(as_of)
    allowed = {tuple(sorted(p)) for p in pairs}
    account_set = set(accounts)
    raw, comparisons = {}, {}
    excluded = []
    for entry in ledger.iter_entries():
        if entry.get("posting_date", as_of) > as_of:
            continue
        company = entry["company"]
        for line in entry["lines"]:
            account, partner = line["account"], line.get("partner")
            if account not in account_set:
                continue
            other = directory.resolve(partner)
            pair = tuple(sorted((company, other))) if other else None
            if other == company or not other or pair not in allowed:
                excluded.append({"book_line": line.get("book_line"), "company": company,
                                 "account": account, "partner": partner,
                                 "reason": "self_partner" if other == company else "outside_task_pairs"})
                continue
            key = (company, account, partner, line.get("assignment"))
            if key not in raw:
                raw[key] = {"company": company, "account": account, "partner": partner,
                            "counterparty_company": other, "pair": list(pair),
                            "assignment": line.get("assignment"), "currency": directory.currency(company),
                            "local_cents": 0, "eur_cents": 0, "valuation_local_cents": 0,
                            "document_cents": {}, "source_lines": []}
            position = raw[key]
            local = line["debit"] - line["credit"]
            eur, valuation_only = euro_cents(entry, line, directory, rates, valuation_ids=valuation_ids)
            position["local_cents"] += local
            position["eur_cents"] += eur
            position["valuation_local_cents"] += local if valuation_only else 0
            doc_currency = line.get("currency", entry.get("currency", directory.currency(company)))
            signed = signed_document_cents(line) if "amount_doc" in line else local
            position["document_cents"][doc_currency] = position["document_cents"].get(doc_currency, 0) + signed
            ref = line.get("assignment") or entry.get("reference")
            position["source_lines"].append({"book_line": line.get("book_line"),
                "entry_id": entry.get("id"), "reference": entry.get("reference"),
                "assignment": line.get("assignment"), "comparison_reference": ref,
                "posting_date": entry.get("posting_date"), "currency": doc_currency,
                "local_cents": local, "eur_cents": eur, "valuation_only": valuation_only})
            ck = (pair, FAMILIES.get(account, account), ref)
            if ck not in comparisons:
                comparisons[ck] = {"pair": list(pair), "family": ck[1], "reference": ref,
                                   "currency": "EUR", "by_company": {c: 0 for c in pair},
                                   "accounts": set(), "source_lines": []}
            comp = comparisons[ck]
            comp["by_company"][company] += eur
            comp["accounts"].add(account)
            comp["source_lines"].append(line.get("book_line"))
    for comp in comparisons.values():
        comp["difference_cents"] = sum(comp["by_company"].values())
        comp["accounts"] = sorted(comp["accounts"])
    # Reuse Ledger's key model; do not mutate or silently merge its dimensions.
    return {"positions": sorted(raw.values(), key=lambda r: (r["company"], r["account"], r["partner"], r["assignment"] or "")),
            "comparisons": sorted(comparisons.values(), key=lambda r: (r["pair"], r["family"], r["reference"] or "")),
            "excluded": excluded}
