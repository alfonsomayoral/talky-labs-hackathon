#!/usr/bin/env python3
"""Authorized M5 dependency-fixture adapter (#159), never an IC solver.

Only AP and bank reference outputs are readable here. Every receipt is reconciled
with the task queue AND inbox evidence. Expected IC output is not an input. Use
an explicit AP projection scope; receipt coverage always covers the entire queue.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from kalmora.data import PhaseData
from kalmora.ic.context import Context
from kalmora.ic.model import Upstream, digest
from kalmora.ic.handoff import (receipt_coverage, ap_delivery as _ap_delivery, bank_delivery,
                                _already_recorded, _pool_link)
from kalmora.ledger import Ledger

PHASE = "phase_dev"
REFERENCE_MEMBERS = {
    "ap": f"participant/{PHASE}/golden/ap.jsonl",
    "bank_rec": f"participant/{PHASE}/golden/bank_rec.jsonl",
}


def encode(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def evidence(document: str, field: str, quote: str | None = None) -> dict:
    return {"document": document, "field": field, "quote": quote, "page": None}


def rows(raw: bytes) -> list[dict]:
    result = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if not all(isinstance(row, dict) for row in result):
        raise ValueError("Fixture JSONL must contain object rows")
    return result


class Sources:
    """Allowlisted archive reads plus hash-verified, non-reference phase files."""
    def __init__(self, archive: zipfile.ZipFile, phase: Path):
        self.archive, self.phase = archive, phase.resolve()
        self.files: dict[str, dict] = {}
        self.access_log: list[str] = []

    manifest_name = "fixture-manifest.json"

    def delivery_source(self, producer):
        return "golden_fixture:" + REFERENCE_MEMBERS[producer]

    def producer(self, producer):
        return "golden_fixture/" + {"ap": "AP", "bank_rec": "banks"}[producer]

    def _read(self, member: str) -> bytes:
        parts = Path(member).parts
        if ("golden" in parts and member not in REFERENCE_MEMBERS.values()) or ".." in parts:
            raise ValueError("This adapter may only open the two authorized AP/bank fixtures")
        if member not in REFERENCE_MEMBERS.values() and not member.startswith(f"participant/{PHASE}/"):
            raise ValueError("Source lies outside the authorized phase")
        if self.archive.getinfo(member).file_size > 256 * 1024 * 1024:
            raise ValueError("Source member exceeds the size limit")
        data = self.archive.read(member)
        self.access_log.append(member)
        self.files[member] = {"sha256": sha(data), "size": len(data)}
        return data

    def fixture(self, name: str) -> list[dict]:
        if name not in REFERENCE_MEMBERS:
            raise ValueError("Not an authorized dependency fixture")
        return rows(self._read(REFERENCE_MEMBERS[name]))

    def verify(self, path: Path) -> bytes:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.phase) or "golden" in resolved.parts:
            raise ValueError("Source escapes the non-reference phase")
        relative = path.relative_to(self.phase).as_posix()
        member = f"participant/{PHASE}/{relative}"
        raw = path.read_bytes()
        if raw != self._read(member):
            raise ValueError(f"Solver source differs from the original package: {relative}")
        return raw




def ap_delivery(ap, ctx, scope, sources=None):
    # Preserve the fixture tool's public helper signature for external harnesses.
    if sources is None:
        from types import SimpleNamespace
        sources = SimpleNamespace(delivery_source=lambda producer: "golden_fixture:" + REFERENCE_MEMBERS[producer])
    return _ap_delivery(ap, ctx, scope, sources)


def build(package: Path, phase: Path, destination: Path, *, ap_projection_scope: str) -> dict:
    """Build explicit hand-offs, refusing partial receipt inventories or overwrites."""
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Fixture destination must be new")
    if destination.resolve().is_relative_to(phase.resolve()):
        raise ValueError("Fixtures must not overwrite the source phase")
    with package.open("rb") as stream:
        archive_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            sources = Sources(archive, phase)
            data = PhaseData(phase)
            for table in ("tasks/close", "tasks/intercompany", "companies", "vendors", "customers", "fx_rates",
                          "cost_centers", "projects", "chart_of_accounts", "intercompany_agreements", "bank_accounts", "journal_entries"):
                sources.verify(data._path(table))
            book = Ledger.from_entries(data.iter_journal())
            original_hash = digest(tuple(book.iter_entries()))
            ctx = Context(data, book, Upstream.missing())
            ap, banks = sources.fixture("ap"), sources.fixture("bank_rec")
            coverage, coverage_audit = receipt_coverage(ap, ctx, sources)
            ap_entries, ap_audit = ap_delivery(ap, ctx, ap_projection_scope, sources)
            bank, bank_audit = bank_delivery(banks, ctx, sources)
            assert digest(tuple(book.iter_entries())) == original_hash
            manifest = {"schema_version": 1, "kind": "golden_fixture", "integration_mode": "simulated",
                        "phase": PHASE, "month": data.month, "package_sha256": archive_sha,
                        "ap_receipt_coverage": coverage_audit, "ap_projection": ap_audit,
                        "bank_projection": bank_audit, "recorded_ledger_sha256": original_hash,
                        "sources": dict(sorted(sources.files.items())), "archive_members_opened": sorted(set(sources.access_log)),
                        "real_flow_verified": False, "real_flow_gate": "#159", "milestone_acceptance_proven": False}
    manifest_bytes = encode(manifest)
    provenance = {"kind": "golden_fixture", "integration_mode": "simulated", "phase": PHASE, "month": data.month,
                  "package_sha256": archive_sha, "fixture_manifest_sha256": sha(manifest_bytes),
                  "fixture_hashes": {k: manifest["sources"][v]["sha256"] for k, v in REFERENCE_MEMBERS.items()},
                  "ap_receipt_scope": coverage_audit["scope"], "ap_projection_scope": ap_projection_scope,
                  "bank_projection_scope": bank_audit["scope"], "real_flow_gate": "#159", "real_flow_verified": False}
    payload = {"schema_version": 1, "prior_projection": None, "ap_entries": ap_entries,
               "ap_coverage": coverage, "banks": bank, "invoice_allocations": [],
               "interest_allocations": {}, "valuation_entry_ids": [], "provenance": provenance}
    destination.mkdir(parents=True)
    (destination / "fixture-manifest.json").write_bytes(manifest_bytes)
    (destination / "upstream.json").write_bytes(encode(payload))
    return {"kind": "golden_fixture", "phase": PHASE, "month": data.month, "receipt_documents": coverage_audit["task_count"],
            "ic_receipts": coverage_audit["ic_receipts"], "unknown_issuer_receipts": coverage_audit["unknown_issuer_receipts"], "ap_projection_scope": ap_projection_scope,
            "ap_entries": len(ap_entries), "bank_entries": len(bank["entries"]), "pooling_links": bank["pooling_links"],
            "upstream_sha256": sha(encode(payload)), "manifest_sha256": sha(manifest_bytes), "real_flow_verified": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--phase", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ap-projection-scope", choices=("intercompany", "full"), required=True,
                        help="Receipt coverage is always full. Intercompany projects all AP entries carrying a group partner.")
    args = parser.parse_args()
    print(json.dumps(build(args.package, args.phase, args.out, ap_projection_scope=args.ap_projection_scope), sort_keys=True))
