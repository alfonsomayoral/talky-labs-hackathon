"""Replay-only July check of NOT_INVOICE actions and payment_block/payee (#50).

Golden is read only here, as evaluation. Earlier rule stages (duplicates,
rejections, holds) belong to other bindings and are passed as CLEAR, so this
measures payment metadata alone. Usage:
PYTHONPATH=src .venv/bin/python tools/validate_ap_payment_july.py
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from kalmora.ap_chronology import KINDS, receipt_key
from kalmora.ap_chronology_sources import notice_events
from kalmora.ap_identity_sources import resolve_ap_identity
from kalmora.ap_payment import ACTIONS
from kalmora.ap_payment_sources import (invoice_date_candidates, possible_notice_kinds,
                                        resolve_invoice_payment, resolve_notice)
from kalmora.data import PhaseData
from kalmora.documents.ap_sources import load_ap_sources
from kalmora.model.ap_scope import ApScope
from kalmora.model.ap_timeline_state import ApTimelineState


def bind(task):
    classified = [(a.normalized.facts, a.classification.document_type) for a in task.attachments
                  if a.normalized and a.classification and a.classification.status == "CLASSIFIED"]
    unresolved = len(task.attachments) - len(classified)
    types = {kind for _, kind in classified}
    return classified, unresolved, types.pop() if len(types) == 1 else None


def predict(phase_dir: Path, state_dir: Path):
    data, sources = PhaseData(phase_dir), load_ap_sources(phase_dir, state_dir)
    tasks = sorted(sources.values(), key=lambda t: (receipt_key(t.message.received_at), t.doc_id))
    state, hidden, out = ApTimelineState(), [], {}
    for task in tasks:  # Pass 1: register notices; remember what could hide one.
        classified, unresolved, kind = bind(task)
        vendor = resolve_ap_identity([f for f, _ in classified], task.message.raw, data).vendor_id
        if unresolved:
            hidden.append((task.doc_id, task.message.received_at, vendor, possible_notice_kinds(task.message.subject)))
        if kind in ACTIONS:
            binding = notice_events(task.message.raw, classified, data)
            if kind in KINDS and not binding.events:
                hidden.append((task.doc_id, task.message.received_at, vendor, (kind,)))
            result = resolve_notice(kind, binding.events, state)
            state = result.state
            out[task.doc_id] = {"type": kind, "decision": result.decision, "action": result.action,
                                "diagnostics": [*binding.diagnostics, *result.diagnostics]}
    for task in tasks:  # Pass 2: invoices against the whole month's simulated state.
        classified, unresolved, kind = bind(task)
        if task.doc_id in out:
            continue
        if kind != "INVOICE":
            out[task.doc_id] = {"type": kind, "decision": "NO_PAYMENT_METADATA" if kind else "UNKNOWN",
                                "diagnostics": [] if kind else ["DOCUMENT_TYPE_UNKNOWN"]}
            continue
        identity = resolve_ap_identity([f for f, _ in classified], task.message.raw, data)
        if identity.company is None or identity.vendor_id is None:
            out[task.doc_id] = {"type": kind, "decision": "UNKNOWN", "diagnostics": ["SCOPE_UNKNOWN"]}
            continue
        received = receipt_key(task.message.received_at)
        blocked = {k for doc_id, at, vendor, kinds in hidden if doc_id != task.doc_id
                   and receipt_key(at) <= received and vendor in (None, identity.vendor_id) for k in kinds}
        scope = ApScope(identity.company, identity.vendor_id, data.get("vendors", identity.vendor_id)["currency"])
        try:
            result = resolve_invoice_payment(
                data=data, scope=scope, invoice_dates=invoice_date_candidates(a.normalized for a in task.attachments if a.normalized), received_at=task.message.received_at,
                notices=state.events, complete_kinds=[k for k in KINDS if k not in blocked],
                duplicate_status="CLEAR", rejection_status="CLEAR", hold_status="CLEAR")
        except ValueError as error:
            out[task.doc_id] = {"type": kind, "decision": "UNKNOWN", "diagnostics": [f"INVALID:{error}"]}
            continue
        out[task.doc_id] = {"type": kind, "decision": result.decision, "payment_block": result.payment_block,
                            "payee": result.payee, "diagnostics": list(result.diagnostics)}
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="/Users/alfonsomayoral/Talky/participant/phase_dev")
    parser.add_argument("--state", default="/Users/alfonsomayoral/Talky/.kalmora-cache/july")
    args = parser.parse_args(argv)
    phase = Path(args.phase)
    predicted = predict(phase, Path(args.state))
    golden = {row["doc_id"]: row for row in map(json.loads, (phase / "golden/ap.jsonl").read_text().splitlines())}
    actions, payment, rows = Counter(), Counter(), []
    for doc_id, gold in sorted(golden.items()):
        mine = predicted.get(doc_id, {"decision": "UNKNOWN", "diagnostics": ["NOT_LOADED"]})
        if gold["decision"] == "NOT_INVOICE":
            outcome = "match" if mine.get("action") == gold.get("action") and mine["decision"] == "NOT_INVOICE" else "mismatch"
            actions[outcome] += 1
            if outcome != "match":
                rows.append({"doc_id": doc_id, "check": "action", "golden": gold.get("action"), **mine})
        expected = (gold.get("payment_block"), (gold.get("payee") or {}).get("type"))
        if mine["decision"] == "UNKNOWN":
            outcome = "unknown"
        else:
            outcome = "match" if (mine.get("payment_block"), mine.get("payee")) == expected else "mismatch"
        payment[outcome] += 1
        if outcome != "match":
            rows.append({"doc_id": doc_id, "check": "payment", "golden": [gold["decision"], *expected], **mine})
    print(json.dumps({"tasks": len(golden), "not_invoice_actions": dict(actions),
                      "payment_block_payee": dict(payment)}, sort_keys=True))
    for row in rows:
        print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
