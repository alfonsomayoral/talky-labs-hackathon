"""Explicit JSON hand-off for AP, bank and prior-projection producers.

This adapter only decodes producer facts/entries; it does not extract invoices,
run AP/bank rules, or certify an absent receipt inventory. All file access reuses
the existing solver-safe data readers (including symlink/golden rejection).
"""
from __future__ import annotations

from pathlib import Path

from kalmora.data import load_json, read_jsonl
from kalmora.facts import Evidence
from kalmora.ledger import Ledger
from .model import Allocation, BankDelivery, OwnedEntry, Receipt, ReceiptCoverage, Upstream


def evidence(value: dict) -> Evidence:
    return Evidence(**value)


def owned(value: dict) -> OwnedEntry:
    return OwnedEntry(value["event_id"], value["stage"], value["entry"], evidence(value["evidence"]))


def allocation(value: dict) -> Allocation:
    return Allocation(value["account"], value.get("cost_center"), value.get("wbs"), evidence(value["evidence"]))


def load_upstream(path: Path) -> Upstream:
    payload = load_json(path)
    if payload.get("schema_version") != 1:
        raise ValueError("M5 upstream hand-off schema_version must be 1")
    prior_path = payload.get("prior_projection")
    prior = Ledger.from_entries(read_jsonl(path.parent / prior_path)) if prior_path is not None else None
    ap_rows = payload.get("ap_entries")
    ap = tuple(owned(row) for row in ap_rows) if ap_rows is not None else None
    raw = payload.get("ap_coverage")
    coverage = None if raw is None else ReceiptCoverage(raw["month"], raw["complete"],
        tuple(Receipt(row["company"], row["issuer"], row["reference"], row["received_on"], evidence(row["evidence"]))
              for row in raw["receipts"]), raw["producer"], evidence(raw["evidence"]),
        tuple(raw.get("unresolved_documents", [])))
    raw = payload.get("banks")
    banks = None if raw is None else BankDelivery(raw["producer"], raw["complete"],
        tuple(owned(row) for row in raw["entries"]),
        {line: tuple(owner) for line, owner in raw["pooling_links"].items()}, evidence(raw["evidence"]))
    allocations = {}
    for row in payload.get("invoice_allocations", []):
        identity = (row["issuer"], row["receiver"], row["reference"])
        if identity in allocations:
            raise ValueError("duplicate invoice allocation identity")
        allocations[identity] = allocation(row)
    return Upstream(prior, ap, coverage, banks, allocations,
                    {company: allocation(row) for company, row in payload.get("interest_allocations", {}).items()},
                    frozenset(payload.get("valuation_entry_ids", [])), payload.get("provenance", {}))
