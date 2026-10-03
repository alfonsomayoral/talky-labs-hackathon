"""In-memory ``PhaseRepository`` and ``JobStore``.

One ``PhaseData`` + ``Ledger`` per phase, indexed at load time. Packages stay extracted on
disk, so this is a rebuildable cache: a database repository can replace it by implementing
the same port.
"""
import calendar
import threading
import uuid
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..app.errors import DomainError
from ..app.ports import Filters, Row
from ..app.types import Job, LoadIssue, LoadReport, Meta, PhaseSummary, SCHEMA_VERSION
from ..data import PhaseData, load_json
from ..ledger import Ledger, is_open_item_account
from ..model import Manifest, ValidationContext
from ..money import RateTable

COLLECTIONS: dict[str, tuple[str, str]] = {
    "companies": ("companies", "code"),
    "accounts": ("chart_of_accounts", "account"),
    "cost-centers": ("cost_centers", "id"),
    "vendors": ("vendors", "id"),
    "customers": ("customers", "id"),
    "projects": ("projects", "id"),
    "tax-codes": ("tax_codes", "id"),
}
OPEN_ITEM_KEY = ("company", "account", "partner", "assignment")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_golden(phase_dir: Path) -> bool:
    golden = phase_dir / "golden"
    return golden.is_dir() and any(golden.iterdir())


class _Phase:
    """Everything loaded for one phase."""

    def __init__(self, package_id: str, phase_dir: Path, manifest: Manifest) -> None:
        self.package_id = package_id
        self.phase_dir = phase_dir
        self.name = phase_dir.name
        self.prefix = f"{phase_dir.parent.name}/{phase_dir.name}"
        self.files = {item["path"]: item["sha256"] for item in manifest["files"]}
        self.data = PhaseData(phase_dir)
        self.month = self.data.month
        self.ledger = Ledger.from_entries(self.data.iter_journal())
        self.entries: list[Row] = list(self.ledger.iter_entries())
        self.entries.sort(key=lambda e: (e.get("posting_date") or "", e.get("id") or ""))
        self.by_id: dict[str, Row] = {e["id"]: e for e in self.entries if e.get("id")}
        self.by_company: dict[str, list[int]] = defaultdict(list)
        self.by_account: dict[str, list[int]] = defaultdict(list)
        self.by_partner: dict[str, list[int]] = defaultdict(list)
        totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for position, entry in enumerate(self.entries):
            self.by_company[entry["company"]].append(position)
            for account in {line["account"] for line in entry["lines"]}:
                self.by_account[account].append(position)
            for partner in {line["partner"] for line in entry["lines"] if line.get("partner")}:
                self.by_partner[partner].append(position)
            for line in entry["lines"]:
                totals[entry["company"]][0] += line["debit"]
                totals[entry["company"]][1] += line["credit"]
        balances = self.ledger.balances()
        self.balance_rows: list[Row] = [{"company": k.company, "account": k.account, "balance": v}
                                        for k, v in sorted(balances.items())]
        self.summary_rows: list[Row] = [{"company": c, "debit_total": d, "credit_total": cr, "net": d - cr}
                                        for c, (d, cr) in sorted(totals.items())]
        open_items = self.ledger.open_items()
        self.open_item_rows: list[Row] = [
            {"company": k.company, "account": k.account, "partner": k.partner,
             "assignment": k.assignment, "balance": v}
            for k, v in sorted(open_items.items(), key=lambda kv: tuple(x or "" for x in kv[0]))]
        self.golden = _has_golden(phase_dir)
        self.lock = threading.Lock()
        self.cache: dict[str, Any] = {}
        self.documents = self._documents()
        self.counts = {"companies": len(self.data.companies), "journal_entries": len(self.entries),
                       "balance_accounts": len(self.balance_rows), "open_item_keys": len(open_items),
                       "document_messages": len(self.documents),
                       "bank_lines": len(self.data.table("bank_lines"))}
        self.report: LoadReport = {"phase": self.name, "counts": self.counts,  # type: ignore[typeddict-item]
                                   "issues": self._issues(open_items)}

    def _documents(self) -> list[Row]:
        rows = []
        for path in sorted(self.phase_dir.glob("inbox/*/*/message.json")):
            row = dict(load_json(path))
            row["kind"] = path.parent.parent.name
            rows.append(row)
        return rows

    def _issues(self, computed: dict[Any, int]) -> list[LoadIssue]:
        issues: list[LoadIssue] = []
        master: dict[tuple[Any, ...], int] = defaultdict(int)
        for row in self.data.table("open_items"):
            master[tuple(row.get(k) for k in OPEN_ITEM_KEY)] += row["balance"]
        master = {k: v for k, v in master.items() if v}
        ledger = {tuple(k): v for k, v in computed.items() if v}
        missing = [k for k in master if k not in ledger]
        extra = [k for k in ledger if k not in master]
        different = [k for k in master if k in ledger and master[k] != ledger[k]]
        if missing or extra or different:
            sample = (missing or extra or different)[0]
            issues.append({"code": "open_items.master_mismatch", "severity": "warning",
                           "detail": f"ERP open_items vs ledger: {len(missing)} only in master, "
                                     f"{len(extra)} only in ledger, {len(different)} with a different balance.",
                           "ref": "/".join(str(x) for x in sample)})
        else:
            issues.append({"code": "open_items.master_match", "severity": "info",
                           "detail": f"ERP open_items agree with the ledger on {len(ledger)} non-zero items."})
        no_partner = [k for k in computed if k.partner is None and is_open_item_account(k.account)]
        if no_partner:
            sample = no_partner[0]
            issues.append({"code": "open_items.partner_null", "severity": "warning",
                           "detail": f"{len(no_partner)} open-item keys have no partner (historical data).",
                           "ref": f"{sample.company}/{sample.account}/{sample.assignment}"})
        return issues

    def summary(self, detail: bool = False) -> PhaseSummary:
        result: PhaseSummary = {"phase": self.name, "month": self.month, "package_id": self.package_id,
                                "status": "loaded", "has_golden": self.golden,
                                "counts": self.counts,  # type: ignore[typeddict-item]
                                "tasks": sorted(self.data.tasks)}
        if detail:
            result["load_report"] = self.report
        return result


class InMemoryPhaseRepository:
    def __init__(self) -> None:
        self._phases: dict[str, _Phase] = {}
        self._pending: dict[str, tuple[str, str]] = {}
        self._lock = threading.Lock()

    # loading ------------------------------------------------------------
    def load_phase(self, package_id: str, phase_dir: Path, manifest: Manifest) -> LoadReport:
        self._check_free(phase_dir.name, package_id)
        phase = _Phase(package_id, phase_dir, manifest)
        with self._lock:
            self._check_free(phase.name, package_id)
            self._phases[phase.name] = phase
            self._pending.pop(phase.name, None)
        return phase.report

    def _check_free(self, name: str, package_id: str) -> None:
        current = self._phases.get(name)
        if current is not None and current.package_id != package_id:
            raise DomainError("phase.conflict",
                              f"Phase '{name}' is already loaded from package {current.package_id[:12]}.")

    def mark(self, phase: str, package_id: str, status: str) -> None:
        with self._lock:
            if status == "loaded":
                self._pending.pop(phase, None)
            else:
                self._pending[phase] = (package_id, status)

    def _get(self, name: str) -> _Phase:
        phase = self._phases.get(name)
        if phase is not None:
            return phase
        if name in self._pending:
            raise DomainError("phase.not_loaded", f"Phase '{name}' is {self._pending[name][1]}, not loaded yet.")
        raise DomainError("phase.not_found", f"No phase named '{name}' in any registered package.")

    # catalogue ----------------------------------------------------------
    def phases(self) -> list[PhaseSummary]:
        return [p.summary() for _, p in sorted(self._phases.items())]

    def phase(self, phase: str) -> PhaseSummary:
        return self._get(phase).summary(detail=True)

    def location(self, phase: str) -> Path:
        return self._get(phase).phase_dir

    def meta(self, phase: str, sources: list[str]) -> Meta:
        ph = self._get(phase)
        refs = []
        for rel in sources:
            path = f"{ph.prefix}/{rel}"
            if path in ph.files:
                refs.append({"path": path, "sha256": ph.files[path]})
        return {"schema_version": SCHEMA_VERSION, "phase": ph.name, "month": ph.month,
                "package_id": ph.package_id, "sources": refs}

    # master data --------------------------------------------------------
    def _collection(self, collection: str) -> tuple[str, str]:
        if collection not in COLLECTIONS:
            raise DomainError("request.invalid", f"Unknown collection '{collection}'.")
        return COLLECTIONS[collection]

    def records(self, phase: str, collection: str, filters: Filters) -> list[Row]:
        ph = self._get(phase)
        table, key = self._collection(collection)
        rows = ph.data.find(table)
        company, query = filters.get("company"), (filters.get("q") or "").casefold()
        result = []
        for row in rows:
            if company and company != row.get("company") and company not in (row.get("companies") or []):
                continue
            if "type" in filters and row.get("type") != filters["type"]:
                continue
            if "open_items" in filters and bool(row.get("open_items")) != filters["open_items"]:
                continue
            if "prefix" in filters and not str(row.get("account", "")).startswith(filters["prefix"]):
                continue
            if query and query not in str(row.get("name", "")).casefold():
                continue
            result.append(row)
        return sorted(result, key=lambda r: str(r.get(key)))

    def record(self, phase: str, collection: str, record_id: str) -> Row:
        ph = self._get(phase)
        table, key = self._collection(collection)
        for row in ph.data.find(table):
            if str(row.get(key)) == record_id:
                return row
        raise DomainError("record.not_found", f"No {collection} record '{record_id}'.")

    def tasks(self, phase: str) -> dict[str, Any]:
        return self._get(phase).data.tasks

    def documents(self, phase: str, kind: str | None) -> list[Row]:
        return [d for d in self._get(phase).documents if kind is None or d["kind"] == kind]

    # accounting ---------------------------------------------------------
    @staticmethod
    def _candidates(ph: _Phase, filters: Filters) -> list[int]:
        found = [ph.by_company.get(filters["company"], []) if "company" in filters else None,
                 ph.by_account.get(filters["account"], []) if "account" in filters else None,
                 ph.by_partner.get(filters["partner"], []) if "partner" in filters else None]
        lists = sorted((f for f in found if f is not None), key=len)
        if not lists:
            return list(range(len(ph.entries)))
        result = set(lists[0])
        for other in lists[1:]:
            result &= set(other)
        return sorted(result)

    @staticmethod
    def _entry_matches(entry: Row, filters: Filters) -> bool:
        for key in ("doc_type", "source", "reference"):
            if key in filters and entry.get(key) != filters[key]:
                return False
        day = entry.get("posting_date") or ""
        return not (("date_from" in filters and day < filters["date_from"])
                    or ("date_to" in filters and day > filters["date_to"]))

    def journal_entries(self, phase: str, filters: Filters) -> list[Row]:
        ph = self._get(phase)
        return [ph.entries[i] for i in self._candidates(ph, filters)
                if self._entry_matches(ph.entries[i], filters)]

    def journal_entry(self, phase: str, entry_id: str) -> Row:
        entry = self._get(phase).by_id.get(entry_id)
        if entry is None:
            raise DomainError("entry.not_found", f"No journal entry '{entry_id}'.")
        return entry

    def journal_lines(self, phase: str, filters: Filters) -> list[Row]:
        ph = self._get(phase)
        result = []
        for entry in self.journal_entries(phase, filters):
            for line in entry["lines"]:
                if "account" in filters and line["account"] != filters["account"]:
                    continue
                if "partner" in filters and line.get("partner") != filters["partner"]:
                    continue
                result.append({**line, "entry_id": entry.get("id"), "posting_date": entry.get("posting_date"),
                               "doc_type": entry.get("doc_type")})
        return result

    def balances(self, phase: str, filters: Filters) -> list[Row]:
        rows = self._get(phase).balance_rows
        return [r for r in rows
                if ("company" not in filters or r["company"] == filters["company"])
                and ("account" not in filters or r["account"] == filters["account"])
                and ("account_prefix" not in filters or r["account"].startswith(filters["account_prefix"]))
                and (not filters.get("nonzero") or r["balance"] != 0)]

    def balance_summary(self, phase: str, company: str | None) -> list[Row]:
        return [r for r in self._get(phase).summary_rows if company is None or r["company"] == company]

    def open_items(self, phase: str, filters: Filters) -> list[Row]:
        ph = self._get(phase)
        if filters.get("source") == "master":
            merged: dict[tuple[Any, ...], int] = defaultdict(int)
            for row in ph.data.table("open_items"):
                merged[tuple(row.get(k) for k in OPEN_ITEM_KEY)] += row["balance"]
            rows = [dict(zip(OPEN_ITEM_KEY, k), balance=v)
                    for k, v in sorted(merged.items(), key=lambda kv: tuple(x or "" for x in kv[0]))]
        else:
            rows = ph.open_item_rows
        return [r for r in rows
                if all(key not in filters or r[key] == filters[key] for key in OPEN_ITEM_KEY)
                and (not filters.get("only_open") or r["balance"] != 0)]

    def ledger_projection(self, phase: str) -> Ledger:
        return self._get(phase).ledger.project()

    def validation_context(self, phase: str) -> ValidationContext:
        ph = self._get(phase)
        with ph.lock:
            if "context" not in ph.cache:
                data = ph.data
                companies = {c["code"] for c in data.companies}
                partners = {r["id"] for r in data.table("vendors")} | {r["id"] for r in data.table("customers")}
                year, month = (int(x) for x in ph.month.split("-"))
                ph.cache["context"] = {
                    "companies": companies,
                    "accounts": {r["account"] for r in data.table("chart_of_accounts")},
                    "partners": partners | companies | {"FACTOR-BAE"},
                    "cost_centers": {r["id"]: {"company": r["company"]} for r in data.table("cost_centers")},
                    "wbs": {w["id"]: {"company": p["company"]} for p in data.table("projects") for w in p.get("wbs") or []},
                    "min_date": f"{ph.month}-01",
                    "max_date": f"{ph.month}-{calendar.monthrange(year, month)[1]:02d}",
                }
            return ph.cache["context"]

    # bank and fx --------------------------------------------------------
    def bank_accounts(self, phase: str, company: str | None) -> list[Row]:
        ph = self._get(phase)
        rows = []
        for row in ph.data.table("bank_accounts"):
            if company is not None and row.get("company") != company:
                continue
            folder = ph.phase_dir / "bank" / row["id"]
            months = sorted(p.name.removesuffix(".lines.jsonl") for p in folder.glob("*.lines.jsonl"))
            rows.append({**row, "months": months})
        return rows

    def bank_lines(self, phase: str, account: str, filters: Filters) -> list[Row]:
        ph = self._get(phase)
        if account not in {r["id"] for r in ph.data.table("bank_accounts")}:
            raise DomainError("bank_account.not_found", f"No bank account '{account}'.")
        lines = [{"account": account, **line} for line in ph.data.bank_lines(account, filters.get("month"))]
        query = (filters.get("q") or "").casefold()
        return [l for l in lines
                if ("date_from" not in filters or l["booking_date"] >= filters["date_from"])
                and ("date_to" not in filters or l["booking_date"] <= filters["date_to"])
                and ("min_amount" not in filters or l["amount"] >= filters["min_amount"])
                and ("max_amount" not in filters or l["amount"] <= filters["max_amount"])
                and (not query or query in l["text"].casefold())]

    def _fx(self, ph: _Phase) -> tuple[list[Row], RateTable, dict[str, list[str]]]:
        with ph.lock:
            if "fx" not in ph.cache:
                rows = sorted(ph.data.table("fx_rates"), key=lambda r: (r["date"], r["currency"]))
                days: dict[str, list[str]] = defaultdict(list)
                for row in rows:
                    days[row["currency"]].append(row["date"])
                ph.cache["fx"] = (rows, RateTable(rows), days)
            return ph.cache["fx"]

    def fx_rates(self, phase: str, filters: Filters) -> list[Row]:
        rows, _, _ = self._fx(self._get(phase))
        return [r for r in rows
                if ("currency" not in filters or r["currency"] == filters["currency"])
                and ("date_from" not in filters or r["date"] >= filters["date_from"])
                and ("date_to" not in filters or r["date"] <= filters["date_to"])]

    def fx_rate_at(self, phase: str, currency: str, day: str) -> Row:
        _, table, days = self._fx(self._get(phase))
        if currency == "EUR":
            return {"date": day, "base": "EUR", "currency": "EUR", "rate": Decimal(1),
                    "source": "identity", "effective_date": day}
        series = days.get(currency, [])
        position = bisect_right(series, day)
        if not position:
            raise DomainError("fx_rate.not_found", f"No {currency} rate on or before {day}.")
        effective = series[position - 1]
        row = next(r for r in self.fx_rates(phase, {"currency": currency, "date_from": effective, "date_to": effective}))
        return {**row, "rate": table.as_of(effective, currency), "effective_date": effective}


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, package_id: str) -> Job:
        job: Job = {"job_id": str(uuid.uuid4()), "package_id": package_id, "status": "received",
                    "started_at": _now(), "ended_at": None, "phases": [], "error": None, "load_reports": []}
        with self._lock:
            self._jobs[job["job_id"]] = job
        return dict(job)  # type: ignore[return-value]

    def update(self, job_id: str, **fields: Any) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            job.update(fields)  # type: ignore[typeddict-item]
            return dict(job)  # type: ignore[return-value]

    def get(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise DomainError("job.not_found", f"No job '{job_id}'.")
        return dict(job)  # type: ignore[return-value]

    def active(self) -> Job | None:
        with self._lock:
            return next((dict(j) for j in self._jobs.values() if j["status"] not in ("loaded", "failed")), None)  # type: ignore[misc]

    def latest_for(self, package_id: str) -> Job | None:
        jobs = [j for j in self._jobs.values() if j["package_id"] == package_id]
        return dict(max(jobs, key=lambda j: j["started_at"])) if jobs else None  # type: ignore[return-value]

    def restore(self, job: Job) -> None:
        with self._lock:
            self._jobs[job["job_id"]] = job
