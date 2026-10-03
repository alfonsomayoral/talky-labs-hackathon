"""Read-only challenge context and shared-accounting adapters for M5."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass

from kalmora.data import PhaseData
from kalmora.facts import Evidence
from kalmora.ledger import Ledger
from kalmora.money import RateTable
from .calculation import month_bounds
from .model import Upstream
from .positions import Directory, euro_cents


@dataclass
class Context:
    data: PhaseData
    recorded: Ledger
    upstream: Upstream
    recorded_entries: tuple[dict, ...] | None = None

    def __post_init__(self):
        self.month = self.data.month
        self.first, self.last = month_bounds(self.month)
        self.directory = Directory(self.data.companies, self.data.table("vendors"), self.data.table("customers"))
        self.rates = RateTable(self.data.table("fx_rates"))
        self.tasks = self.data.table("tasks/intercompany")
        self.pairs = {tuple(sorted(p)) for p in self.tasks["pairs"]}
        if any(len(p) != 2 or p[0] == p[1] or not set(p) <= self.directory.companies.keys() for p in self.pairs):
            raise ValueError("task pairs must contain two distinct known companies")
        self.agreements = self.data.table("intercompany_agreements")
        observed = self.recorded_entries if self.recorded_entries is not None else self.recorded.iter_entries()
        self.entries = tuple(e for e in observed if e.get("posting_date", "") <= self.last.isoformat())
        self.by_id = {e["id"]: e for e in self.entries}
        self.banks = {b["id"]: b for b in self.data.table("bank_accounts")}
        wbs = {w["id"]: {**w, "company": p["company"]}
               for p in self.data.table("projects") for w in p.get("wbs", [])}
        partners = set(self.directory.aliases)
        # Shared policy §1 assigns this literal to factoring (55300000).
        # Bank deliveries can contain those valid non-IC adjustments too.
        partners.add("FACTOR-BAE")
        partners.update(r["id"] for r in self.data.table("vendors"))
        partners.update(r["id"] for r in self.data.table("customers"))
        self.validation = {"companies": self.directory.companies,
                           "accounts": {r["account"]: r for r in self.data.table("chart_of_accounts")},
                           "partners": partners, "cost_centers": {r["id"]: r for r in self.data.table("cost_centers")},
                           "wbs": wbs, "min_date": self.first.isoformat(), "max_date": self.last.isoformat()}

    def current(self, entry: dict) -> bool:
        return self.first.isoformat() <= entry.get("posting_date", "") <= self.last.isoformat()

    def pair(self, a: str, b: str) -> tuple[str, str] | None:
        p = tuple(sorted((a, b)))
        return p if p in self.pairs else None

    def eur(self, entry, line):
        return euro_cents(entry, line, self.directory, self.rates,
                          valuation_ids=self.upstream.valuation_entry_ids)[0]

    def evidence(self, entry, line=None) -> Evidence:
        external = getattr(self, "external_evidence", {}).get(entry["id"])
        if external is not None:
            return external
        if entry["id"] not in self.by_id:
            return Evidence("upstream/prior_projection", entry["id"])
        field = line.get("book_line") if line else entry["id"]
        return Evidence("erp/journal_entries.jsonl", field or entry["id"])

    def new_entry(self, event: str, company: str, lines: list[dict], *, reference: str) -> dict:
        result = {"id": "M5-" + event.rsplit(":", 1)[-1], "company": company,
                  "posting_date": self.last.isoformat(), "document_date": self.last.isoformat(),
                  "currency": self.directory.currency(company), "reference": reference,
                  "source": "M5_IC", "lines": []}
        for original in lines:
            line = deepcopy(original)
            # Keep the old book reference as evidence, never masquerade as that line.
            if line.get("book_line"):
                line["source_book_line"] = line.pop("book_line")
            line.pop("line", None)
            line["company"] = company
            result["lines"].append(line)
        return result


def reverse_line(line: dict) -> dict:
    result = deepcopy(line)
    result["debit"], result["credit"] = line["credit"], line["debit"]
    return result


def financial_fingerprint(entry: dict) -> tuple:
    """Exact multiset, including tax and allocation; no descriptive text/dates."""
    keys = ("account", "debit", "credit", "partner", "cost_center", "wbs",
            "tax_code", "assignment", "currency", "amount_doc")
    return tuple(sorted((tuple(str(line.get(k)) for k in keys) for line in entry["lines"])))


def delivery_lines(entry: dict) -> list[dict]:
    """Serialize shared JournalLine dimensions, without leaking internal book IDs.

    IcRow.adjustment reuses JournalLine in the upstream output contract. Its
    assignment, tax and document-currency dimensions must survive serialization;
    they are copied from the generated entry, never inferred from a reference.
    Provenance and source_book_line remain in the separate projection/audit.
    """
    required = ("account", "debit", "credit", "partner", "cost_center", "wbs")
    dimensions = ("assignment", "tax_code", "currency", "amount_doc")
    return [{"company": entry["company"], **{k: l.get(k) for k in required},
             **{k: l[k] for k in dimensions if k in l}}
            for l in entry["lines"]]
