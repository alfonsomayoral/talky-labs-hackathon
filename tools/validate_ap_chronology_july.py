#!/usr/bin/env python3
"""Evaluate chronology-driven payee/payment_block on July in replay mode (#46).

The solver path (loader, identity, notice binding, chronology, payment) never
reads golden; only this script reads golden/ap.jsonl, after predicting.
Inventory is complete = ERP snapshot + every notice of the month's inbox.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalmora.ap_chronology import KINDS
from kalmora.ap_chronology_sources import invoice_events, notice_events
from kalmora.ap_identity_sources import resolve_ap_identity
from kalmora.ap_payment import resolve_payment
from kalmora.data import PhaseData
from kalmora.documents.ap_sources import load_ap_sources
from kalmora.facts import Evidence
from kalmora.model.ap_scope import ApScope

INVOICE_TYPES = {"INVOICE", "CREDIT_NOTE", "DOWN_PAYMENT_REQUEST"}


def _single(documents, field):
    values = {fact.value for d in documents for fact in d.fields.get(field, ()) if fact.value is not None}
    return values.pop() if len(values) == 1 else None


def predict(phase_dir: Path, state_dir: Path) -> dict:
    data, sources = PhaseData(phase_dir), load_ap_sources(phase_dir, state_dir)
    classified = {doc_id: [(a.normalized.facts, a.classification.document_type) for a in task.attachments
                           if a.normalized is not None and a.classification is not None]
                  for doc_id, task in sources.items()}
    notices, notice_diagnostics, unknown_types = [], [], []
    for doc_id, task in sources.items():
        binding = notice_events(task.message.raw, classified[doc_id], data)
        notices += binding.events
        notice_diagnostics += binding.diagnostics
        if not any(kind is not None for _, kind in classified[doc_id]):
            unknown_types.append(doc_id)
    inventory = {kind: (Evidence("erp/vendors.jsonl", "snapshot"), Evidence("erp/contractor_certificates.jsonl", "snapshot"),
                        Evidence("inbox/ap", f"{len(sources)} month messages")) for kind in KINDS}
    predictions = {}
    for doc_id, task in sources.items():
        invoices = [facts for facts, kind in classified[doc_id] if kind in INVOICE_TYPES]
        if not invoices:
            predictions[doc_id] = {"status": "NOT_INVOICE_OR_UNKNOWN", "payee": None, "payment_block": None}
            continue
        identity = resolve_ap_identity(invoices, task.message.raw, data)
        invoice_date = _single(invoices, "document_date")
        if identity.vendor_id is None or identity.company is None or invoice_date is None:
            predictions[doc_id] = {"status": "UNKNOWN", "diagnostics": ["INVOICE_INPUT_UNKNOWN"]}
            continue
        vendor = data.get("vendors", identity.vendor_id)
        scope = ApScope(identity.company, vendor["id"], vendor["currency"])
        try:
            state = invoice_events(data, scope, notices, invoice_date, task.message.received_at,
                                   bank_iban=_single(invoices, "iban"), complete_kinds=KINDS)
        except ValueError as error:
            predictions[doc_id] = {"status": "UNKNOWN", "diagnostics": [str(error)]}
            continue
        payment = resolve_payment("CLEAR", "CLEAR", "CLEAR", vendor.get("default_tax_code") == "SISP",
                                  state, inventory_evidence=inventory)
        selected = [e for e in (state.certificate, state.factoring, state.embargo) if e is not None]
        predictions[doc_id] = {
            "status": payment.decision, "payee": payment.payee, "payment_block": payment.payment_block,
            "diagnostics": list(payment.diagnostics),
            # Evidence must identify the source document and the vigency it relies on.
            "evidence": [{"event": e.event_id, "kind": e.kind, "document": e.evidence[0].document,
                          "received_at": e.received_at, "valid_from": e.valid_from, "valid_until": e.valid_until}
                         for e in selected]}
    return {"predictions": predictions, "notices": len(notices), "notice_diagnostics": notice_diagnostics,
            "unclassified_tasks": unknown_types}


def evaluate(phase_dir: Path, state_dir: Path) -> dict:
    result = predict(phase_dir, state_dir)
    golden = {row["doc_id"]: row for row in map(json.loads, (phase_dir / "golden/ap.jsonl").open())}
    counts, mismatches = Counter(), []
    for doc_id, expected in sorted(golden.items()):
        got = result["predictions"][doc_id]
        want = ((expected.get("payee") or {}).get("type"), expected.get("payment_block"))
        have = (got.get("payee"), got.get("payment_block"))
        # Earlier rule stages (duplicates/rejections/holds) pre-empt payment metadata.
        stage = "posted" if expected["decision"] in ("POST", "POST_PAYMENT_BLOCK") else "other"
        if got["status"] == "UNKNOWN":
            outcome = "unknown"
        else:
            outcome = "match" if want == have or (stage == "other" and want == (None, None)) else "mismatch"
        counts[f"{stage}:{outcome}"] += 1
        if outcome != "match":
            mismatches.append({"doc_id": doc_id, "golden_decision": expected["decision"], "golden": want,
                               "predicted": have, "status": got["status"], "diagnostics": got.get("diagnostics")})
    with_vigency = sum(1 for p in result["predictions"].values() for e in p.get("evidence", ())
                       if e["document"] and e["valid_from"])
    return {"tasks": len(golden), "counts": dict(sorted(counts.items())), "notice_events": result["notices"],
            "notice_diagnostics": result["notice_diagnostics"], "unclassified_tasks": result["unclassified_tasks"],
            "selected_events_with_document_and_vigency": with_vigency,
            "selected_events": sum(len(p.get("evidence", ())) for p in result["predictions"].values()),
            "mismatches": mismatches}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", type=Path, default=Path("participant/phase_dev"))
    parser.add_argument("--state", type=Path, default=Path(".kalmora-cache/july"))
    args = parser.parse_args()
    print(json.dumps(evaluate(args.phase, args.state), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
