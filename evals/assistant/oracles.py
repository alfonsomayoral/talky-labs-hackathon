"""Expected values computed from the raw phase files with plain code. They never call the MCP tools, so a tool bug
cannot hide behind a grader that shares it. The same oracles serve the synthetic fixture and a real phase directory."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.is_file() else []


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


class Data:
    """Raw files of one phase directory."""

    def __init__(self, phase_dir: Path) -> None:
        self.dir = Path(phase_dir)
        self.journal = _rows(self.dir / "erp/journal_entries.jsonl")
        self.chart = {r["account"]: r for r in _rows(self.dir / "erp/chart_of_accounts.jsonl")}
        self.companies = {c["code"]: c for c in (_json(self.dir / "erp/companies.json") or [])}
        self.fx = _rows(self.dir / "erp/fx_rates.jsonl")
        self.vendors = {r["id"]: r for r in _rows(self.dir / "erp/vendors.jsonl")}
        self.bank_accounts = {r["id"]: r for r in _rows(self.dir / "erp/bank_accounts.jsonl")}
        self.tasks = {p.stem: _json(p) for p in (self.dir / "tasks").glob("*.json")}
        self._balances: dict[tuple[str, str], int] | None = None
        self._open: dict[tuple[str, str, Any, Any], int] | None = None

    # books ---------------------------------------------------------------
    @property
    def balances(self) -> dict[tuple[str, str], int]:
        if self._balances is None:
            totals: dict[tuple[str, str], int] = defaultdict(int)
            for e in self.journal:
                for l in e["lines"]:
                    totals[(e["company"], l["account"])] += l["debit"] - l["credit"]
            self._balances = dict(totals)
        return self._balances

    def balance(self, company: str, account: str) -> int | None:
        return self.balances.get((company, account))

    def totals(self, company: str) -> dict[str, int]:
        debit = sum(l["debit"] for e in self.journal if e["company"] == company for l in e["lines"])
        credit = sum(l["credit"] for e in self.journal if e["company"] == company for l in e["lines"])
        return {"debit": debit, "credit": credit, "net": debit - credit}

    @property
    def open_items(self) -> dict[tuple[str, str, Any, Any], int]:
        if self._open is None:
            prefixes = ("400", "410", "403", "407", "430", "431", "433", "436", "438", "552", "2423", "1633")
            totals: dict[tuple[str, str, Any, Any], int] = defaultdict(int)
            for e in self.journal:
                for l in e["lines"]:
                    if l["account"].startswith(prefixes) or l["account"] in ("49000000", "55300000"):
                        totals[(e["company"], l["account"], l.get("partner"), l.get("assignment"))] += l["debit"] - l["credit"]
            self._open = dict(totals)
        return self._open

    def open_item(self, company: str, account: str, partner: str) -> list[tuple[Any, int]]:
        return [(k[3], v) for k, v in self.open_items.items() if k[:3] == (company, account, partner)]

    def entries(self, **filters: Any) -> list[dict[str, Any]]:
        out = []
        for e in self.journal:
            if filters.get("company") and e["company"] != filters["company"]:
                continue
            if filters.get("doc_type") and e.get("doc_type") != filters["doc_type"]:
                continue
            if filters.get("partner") and not any(l.get("partner") == filters["partner"] for l in e["lines"]):
                continue
            if filters.get("account") and not any(l["account"] == filters["account"] for l in e["lines"]):
                continue
            out.append(e)
        return out

    def latest_entry(self, company: str) -> dict[str, Any]:
        return max(self.entries(company=company), key=lambda e: (e.get("posting_date") or "", e.get("id") or ""))

    def entry(self, entry_id: str) -> dict[str, Any]:
        return next(e for e in self.journal if e.get("id") == entry_id)

    # fx and bank ------------------------------------------------------------
    def fx_on(self, currency: str, day: str) -> dict[str, Any] | None:
        candidates = [r for r in self.fx if r["currency"] == currency and r["date"] <= day]
        return max(candidates, key=lambda r: r["date"]) if candidates else None

    def bank_lines(self, account: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted((self.dir / "bank" / account).glob("*.lines.jsonl")):
            rows += _rows(path)
        return rows

    def queue(self, task: str) -> Any:
        return self.tasks.get(task)

    def currency(self, company: str) -> str:
        return self.companies[company]["currency"]


def deliverable(run_dir: Path, run_id: str, task: str) -> list[dict[str, Any]]:
    return _rows(Path(run_dir) / run_id / "deliverables" / f"{task}.jsonl")
