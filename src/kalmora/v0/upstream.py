"""Real producer deliveries for IC and M6, with immutable source inventories."""
from __future__ import annotations
from calendar import monthrange
from decimal import Decimal
import json
from pathlib import Path

from ..data import PhaseData
from ..facts import atomic_json
from ..ic.context import Context
from ..ic.handoff import ap_delivery, bank_delivery, receipt_coverage
from ..ic.model import Upstream
from ..ledger import Ledger, iter_entries
from ..money import company_local_currency
from ..close.contracts import file_hash, digest


def _enricher(phase: Path, data: PhaseData):
    month = data.month
    last = f"{month}-{monthrange(int(month[:4]), int(month[5:]))[1]:02d}"
    received = {m["doc_id"]: str(m.get("received_at", ""))[:10] for m in data.table("document_messages") if m.get("doc_id")}
    bank_dates = {line["bank_line"]: line["booking_date"] for line in data.table("bank_lines")}

    def enrich(producer: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for row in rows:
            if producer == "ap" and row.get("journal_entry"):
                entry = row["journal_entry"]
                day = min(max(received.get(row["doc_id"]) or last, f"{month}-01"), last)
                entry.setdefault("posting_date", day)
                entry.setdefault("document_date", row.get("invoice_date") or day)
                entry.setdefault("currency", company_local_currency(entry["company"]))
                entry.setdefault("reference", row.get("invoice_number"))
                entry.setdefault("doc_type", "KG" if row.get("document_type") == "CREDIT_NOTE" else "KR")
                entry.setdefault("source", "AP")
                if row.get("currency") and row["currency"] != entry["currency"]:
                    # FX revaluation needs the document-currency principal on each line.
                    local = sum(l["credit"] - l["debit"] for l in entry["lines"] if l.get("partner") == row.get("vendor_id"))
                    if local:
                        ratio = Decimal(row["payable"]) / abs(local)
                        for line in entry["lines"]:
                            line.setdefault("currency", row["currency"])
                            line.setdefault("amount_doc", int((abs(line["debit"] - line["credit"]) * ratio).to_integral_value()))
            elif producer == "bank_rec":
                for index, adjustment in enumerate(row.get("adjustments", [])):
                    adjustment.setdefault("ref", f"{row['account']}:{adjustment['category']}:{index}")
            elif producer == "ar_cash":
                if row.get("adjustment"):
                    row.setdefault("company", row["adjustment"][0]["company"])
                row.setdefault("date", bank_dates.get(row["bank_line"]))
            elif producer == "ar_billing":
                item = json.loads((phase / "inbox" / "ar" / "billing" / row["billing_item"] / "item.json").read_text())
                for key in ("company", "customer", "contract", "type"):
                    row.setdefault(key, item[key])
        return rows
    return enrich



class Sources:
    manifest_name = "producer-manifest.json"

    def __init__(self, phase, deliverables):
        self.phase, self.deliverables = phase.resolve(), deliverables.resolve()
        self.files = {}

    def verify(self, path):
        path = path.resolve()
        if not path.is_relative_to(self.phase) or "golden" in path.parts:
            raise ValueError("producer source must be an original non-reference phase input")
        raw = path.read_bytes()
        self.files[path.relative_to(self.phase).as_posix()] = file_hash(path)
        return raw

    def delivery_source(self, producer):
        return f"delivery:{producer}.jsonl@{file_hash(self.deliverables / (producer + '.jsonl'))}"

    def producer(self, producer):
        return "real/" + producer


def load_deliveries(phase, deliverables, producers):
    data = PhaseData(phase)
    enrich = _enricher(phase, data)
    return {p: enrich(p, [json.loads(line, parse_float=Decimal)
                         for line in (deliverables / (p + ".jsonl")).read_text().splitlines() if line.strip()])
            for p in producers}


def build_ic_upstream(phase: Path, deliverables: Path, destination: Path) -> Path:
    data = PhaseData(phase)
    sources = Sources(phase, deliverables)
    for table in ("tasks/close", "tasks/intercompany", "companies", "vendors", "customers", "fx_rates",
                  "cost_centers", "projects", "chart_of_accounts", "intercompany_agreements",
                  "bank_accounts", "journal_entries"):
        sources.verify(data._path(table))
    ctx = Context(data, Ledger.from_entries(data.iter_journal()), Upstream.missing())
    rows = load_deliveries(phase, deliverables, ("ap", "bank_rec"))
    # Canonical headers and line metadata do not change any accounting cents.
    for row in rows["ap"]:
        entry = row.get("journal_entry")
        if row.get("decision") in {"POST", "POST_PAYMENT_BLOCK"} and not entry:
            raise ValueError(f"{row['doc_id']}: AP posting delivery missing")
        if entry:
            entry.setdefault("id", "REAL-AP-" + digest(row["doc_id"])[:24])
            for line in entry["lines"]:
                if line["account"] == "40700000" and not line.get("partner"):
                    line["partner"] = row.get("vendor_id")
            row["journal_entry"] = next(iter_entries([entry]))
    coverage, receipt_audit = receipt_coverage(rows["ap"], ctx, sources)
    ap_entries, ap_audit = ap_delivery(rows["ap"], ctx, "full", sources)
    banks, bank_audit = bank_delivery(rows["bank_rec"], ctx, sources)
    destination.mkdir(parents=True, exist_ok=True)
    hashes = {p: file_hash(deliverables / (p + ".jsonl")) for p in rows}
    manifest = {"schema_version": 1, "kind": "real", "phase": phase.name, "month": data.month,
                "sources": sources.files, "deliveries_sha256": hashes,
                "producer_code_sha256": {p.relative_to(Path(__file__).parents[1]).as_posix(): file_hash(p)
                                        for p in sorted(Path(__file__).parents[1].rglob("*.py"))},
                "ap_receipt_coverage": receipt_audit, "ap_projection": ap_audit,
                "bank_projection": bank_audit}
    atomic_json(destination / "producer-manifest.json", manifest)
    payload = {"schema_version": 1, "prior_projection": None, "ap_entries": ap_entries,
               "ap_coverage": coverage, "banks": banks, "invoice_allocations": [],
               "interest_allocations": {}, "valuation_entry_ids": [],
               "provenance": {"kind": "real", "integration_mode": "producer_deliveries",
                              "phase": phase.name, "month": data.month, "deliveries_sha256": hashes,
                              "producer_manifest_sha256": file_hash(destination / "producer-manifest.json")}}
    atomic_json(destination / "upstream.json", payload)
    return destination / "upstream.json"
