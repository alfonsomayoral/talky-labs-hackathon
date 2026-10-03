"""Shared AP receipt and producer-owned projection contracts for IC adapters.

Inputs may be real deliveries or explicit fixtures. No reference output is read here.
"""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from datetime import date, datetime
import json
from pathlib import Path
from typing import Protocol

from kalmora.ledger import iter_entries
from kalmora.validation import validate_entry
from .context import Context
from .model import digest

POSTED = {"POST", "POST_PAYMENT_BLOCK"}
INVOICE_TYPES = {"INVOICE", "CREDIT_NOTE", "DOWN_PAYMENT_REQUEST"}


class Sources(Protocol):
    phase: Path
    manifest_name: str

    def verify(self, path: Path) -> bytes: ...
    def delivery_source(self, producer: str) -> str: ...
    def producer(self, producer: str) -> str: ...


def evidence(document, field, quote=None):
    return {"document": document, "field": field, "quote": quote, "page": None}


def rows(raw):
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def _unique(values: list[str], label: str) -> set[str]:
    if not all(isinstance(value, str) and value for value in values):
        raise ValueError(f"{label}: nonempty string IDs required")
    if len(set(values)) != len(values):
        raise ValueError(f"{label}: duplicate IDs")
    return set(values)


def receipt_coverage(ap: list[dict], ctx: Context, sources: Sources) -> tuple[dict, dict]:
    tasks = json.loads(sources.verify(ctx.data._path("tasks/ap_documents")))
    if not isinstance(tasks, list):
        raise ValueError("AP task inventory must be an array")
    task_ids = _unique(tasks, "AP tasks")
    row_ids = _unique([r.get("doc_id") for r in ap], "AP delivery")
    if task_ids != row_ids:
        raise ValueError(f"Incomplete AP coverage: missing={sorted(task_ids-row_ids)}, extra={sorted(row_ids-task_ids)}")
    paths = sorted((sources.phase / "inbox/ap").glob("*/message.json"))
    path_ids = _unique([p.parent.name for p in paths], "AP inbox")
    if path_ids != task_ids:
        raise ValueError("AP inbox/task ID sets differ; a partial inbox cannot prove nonreceipt")
    messages: dict[str, tuple[dict, str]] = {}
    for path in paths:
        message = json.loads(sources.verify(path))
        doc_id = path.parent.name
        if message.get("doc_id") != doc_id:
            raise ValueError(f"Inbox message ID mismatch: {doc_id}")
        received_at = message.get("received_at")
        if not isinstance(received_at, str) or "T" not in received_at:
            raise ValueError(f"{doc_id}: missing or invalid received_at; cannot certify nonreceipt")
        try:
            parsed = datetime.fromisoformat(received_at)
        except ValueError as exc:
            raise ValueError(f"{doc_id}: invalid received_at; no receipt-date fallback") from exc
        # A naive timestamp is the source-local date, as in the organizer's
        # messages. An offset-aware timestamp must remain its source-local date;
        # converting to UTC could move a last-day receipt across the cutoff.
        messages[doc_id] = (message, parsed.date().isoformat())
    receipts, inventory = [], []
    vendors = {v["id"]: v for v in ctx.data.table("vendors")}
    for row in sorted(ap, key=lambda r: r["doc_id"]):
        doc_id = row["doc_id"]
        message, day = messages[doc_id]
        audit = {"doc_id": doc_id, "decision": row.get("decision"),
                 "document_type": row.get("document_type"), "received_at": message["received_at"],
                 "message": f"inbox/ap/{doc_id}/message.json", "journal_supplied": bool(row.get("journal_entry"))}
        if row.get("document_type") not in INVOICE_TYPES:
            if row.get("decision") != "NOT_INVOICE":
                raise ValueError(f"{doc_id}: unresolved document classification")
            audit["receipt_scope"] = "verified_received_non_invoice_document"
        else:
            vendor_id = row.get("vendor_id")
            if row.get("company") not in ctx.directory.companies:
                raise ValueError(f"{doc_id}: unresolved recipient; coverage is not complete")
            issuer = ctx.directory.resolve(vendor_id)
            if issuer or vendor_id not in vendors:
                reference = row.get("invoice_number")
                if not isinstance(reference, str) or not reference or (issuer and not ctx.pair(issuer, row["company"])):
                    raise ValueError(f"{doc_id}: unresolved IC receipt identity")
                receipt = {"company": row["company"], "issuer": issuer, "reference": reference,
                           "received_on": day,
                           "evidence": evidence(f"inbox/ap/{doc_id}/message.json", "received_at",
                               f"{message['received_at']}; identity from {sources.delivery_source('ap')} doc_id={doc_id}")}
                receipts.append(receipt)
                audit.update(receipt_scope="verified_received_intercompany_invoice" if issuer else "verified_received_invoice_unknown_issuer",
                             issuer=issuer, company=row["company"], reference=reference)
            else:
                # Known external supplier, not an unknown/failed identity lookup.
                audit["receipt_scope"] = "verified_received_external_invoice"
        inventory.append(audit)
    # Prior received-but-held documents also prove receipt. Do not infer their
    # absence merely because they are not in this month's queue or posted book.
    history = rows(sources.verify(ctx.data._path("ap_document_log")))
    historical_receipts = []
    for record in history:
        issuer = ctx.directory.resolve(record.get("vendor"))
        if not issuer or record.get("kind") not in {"invoice", "credit_note", "down_payment_request"}:
            continue
        company, reference, day = record.get("company"), record.get("number"), record.get("received_on")
        if not ctx.pair(issuer, company) or not isinstance(reference, str) or not reference:
            raise ValueError("Historical IC document has unresolved identity")
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
            raise ValueError("Historical IC document has no valid reception date")
        historical_receipts.append({"company": company, "issuer": issuer, "reference": reference,
            "received_on": day, "evidence": evidence("erp/ap_document_log.jsonl", record["doc_id"],
                                                     f"received_on={day}; decision={record.get('decision')}")})
    coverage = {"month": ctx.month, "complete": True, "producer": sources.producer("ap"),
                "evidence": evidence(sources.manifest_name, "ap_receipt_coverage",
                                     "Exact task, result and inbox ID coverage; every receipt date is evidenced"),
                "receipts": receipts + historical_receipts, "unresolved_documents": []}
    audit = {"complete": True, "scope": "all task documents and all inbox/AP messages, irrespective of AP decision",
             "task_count": len(task_ids), "result_count": len(row_ids), "message_count": len(messages),
             "task_ids": sorted(task_ids), "task_ids_sha256": digest(sorted(task_ids)),
             "task_result_message_ids_exact": True, "ic_receipts": sum(r["issuer"] is not None for r in receipts),
             "unknown_issuer_receipts": sum(r["issuer"] is None for r in receipts),
             "historical_ic_receipts": len(historical_receipts),
             "decision_counts": dict(sorted(Counter(r["decision"] for r in ap).items())), "documents": inventory}
    return coverage, audit


def _owned(entry: dict, event: str, stage: str, source: str, field: str) -> dict:
    return {"entry": deepcopy(entry), "event_id": event, "stage": stage, "evidence": evidence(source, field)}


def _already_recorded(entry: dict, recorded: dict[str, dict]) -> bool:
    original = recorded.get(entry["id"])
    if original is None:
        return False
    candidate = next(iter_entries([entry]))
    if candidate != original:
        raise ValueError(f"Delivery/recorded entry ID conflict: {entry['id']}")
    return True


def ap_delivery(ap: list[dict], ctx: Context, scope: str, sources) -> tuple[list[dict], dict]:
    if scope not in {"intercompany", "full"}:
        raise ValueError("Explicit AP projection scope must be intercompany or full")
    recorded = {e["id"]: e for e in ctx.entries}
    delivered, inventory, ids = [], [], set()
    for row in sorted(ap, key=lambda r: r["doc_id"]):
        entry = row.get("journal_entry")
        if not entry:
            continue
        if row.get("decision") not in POSTED or not isinstance(entry, dict):
            raise ValueError(f"{row['doc_id']}: non-posting decision carries an entry")
        if not isinstance(entry.get("id"), str) or entry["id"] in ids:
            raise ValueError("Duplicate or missing AP journal ID")
        ids.add(entry["id"])
        if entry.get("company") != row.get("company"):
            raise ValueError("AP row/journal company mismatch")
        normalized = next(iter_entries([entry]))
        relevant = any(ctx.directory.resolve(l.get("partner")) for l in normalized["lines"])
        problems = validate_entry(entry, ctx.validation)
        item = {"doc_id": row["doc_id"], "entry_id": entry["id"], "ic_relevant": bool(relevant),
                "entry_sha256": digest(entry), "validation_diagnostics": problems}
        if scope == "intercompany" and not relevant:
            item["projection"] = "outside_declared_IC_projection_scope"
        elif _already_recorded(entry, recorded):
            item["projection"] = "already_recorded_identically_not_reposted"
        else:
            if problems:
                raise ValueError(f"Invalid AP delivery {row['doc_id']}: {'; '.join(problems)}")
            delivered.append(_owned(entry, row["doc_id"], "ap_invoice",
                                    sources.delivery_source("ap"), row["doc_id"]))
            item["projection"] = "delivered"
        inventory.append(item)
    return delivered, {"scope": scope, "complete_for_declared_scope": True,
                       "source_entries": len(inventory), "delivered_entries": len(delivered),
                       "excluded_entries": [r for r in inventory if r["projection"].startswith("outside")],
                       "already_recorded": [r for r in inventory if r["projection"].startswith("already")],
                       "entries": inventory}


def _pool_link(bank: dict, adjustment: dict, ctx: Context, statements: dict[str, dict]) -> tuple[str, dict]:
    """Join a supplied bank correction to the original statement and ERP mirror.

    The bank delivery supplies its category and unmatched IDs, not an IC answer.
    Ambiguous, absent or contradictory source links are hard failures.
    """
    registry = ctx.banks[bank["account"]]
    agreement = ctx.agreements.get("cash_pooling") or {}
    if bank["account"] not in agreement.get("participants", []):
        raise ValueError("Pooling delivery account is not an agreement participant")
    header = ctx.banks[agreement["header"]]
    signed_cash = sum(l["debit"] - l["credit"] for l in adjustment["lines"] if l["account"] == registry["gl_account"])
    signed_ic = sum(l["debit"] - l["credit"] for l in adjustment["lines"]
                    if l["account"] == "55200000" and l.get("partner") == header["company"])
    if not signed_cash or signed_ic != -signed_cash or registry["currency"] != header["currency"]:
        raise ValueError("Unsupported pooling correction or monetary basis")
    candidates = []
    for unmatched in bank.get("unmatched_bank", []):
        if unmatched.get("category") != adjustment["category"]:
            continue
        ident = unmatched.get("bank_line")
        statement = statements.get(ident)
        if statement is None:
            raise ValueError(f"Bank delivery references absent statement {ident}")
        if (statement["currency"] == registry["currency"] and statement["amount"] == signed_cash
                and ("amount" not in unmatched or unmatched["amount"] == statement["amount"])):
            candidates.append(statement)
    if len(candidates) != 1:
        raise ValueError("Pooling statement link is not unique")
    statement, = candidates
    mirrors = []
    for original in ctx.entries:
        if original["company"] != header["company"] or original["posting_date"] != statement["booking_date"]:
            continue
        cash = sum(l["debit"] - l["credit"] for l in original["lines"] if l["account"] == header["gl_account"])
        ic = sum(l["debit"] - l["credit"] for l in original["lines"]
                 if l["account"] == "55200000" and l.get("partner") == registry["company"])
        if cash == -signed_cash and ic == -signed_ic and original.get("reference"):
            mirrors.append(original)
    if len(mirrors) != 1:
        raise ValueError("Pooling statement has no unique original ERP mirror")
    mirror, = mirrors
    return statement["bank_line"], {"bank_account": bank["account"], "statement": deepcopy(statement),
        "bank_delivery_ref": adjustment["ref"], "original_mirror_entry": mirror["id"],
        "original_mirror_reference": mirror["reference"], "signed_bank_local_cents": signed_cash,
        "signed_ic_local_cents": signed_ic, "source_currency": registry["currency"],
        "link_basis": "bank unmatched ID + signed statement amount/currency + agreement + same-date ERP mirror"}


def bank_delivery(banks: list[dict], ctx: Context, sources: Sources) -> tuple[dict, dict]:
    task_banks = json.loads(sources.verify(ctx.data._path("tasks/bank_accounts")))
    bank_ids = _unique([b.get("account") for b in banks], "bank delivery")
    task_ids = _unique(task_banks, "bank tasks")
    if bank_ids != task_ids:
        raise ValueError("Bank delivery does not cover all bank task accounts")
    entries, links, owners, link_audit = [], {}, set(), []
    recorded = {e["id"]: e for e in ctx.entries}
    skipped = []
    for bank in sorted(banks, key=lambda b: b["account"]):
        registry = ctx.banks[bank["account"]]
        if bank["company"] != registry["company"]:
            raise ValueError("Bank delivery/master company mismatch")
        path = sources.phase / "bank" / bank["account"] / f"{ctx.month}.lines.jsonl"
        statement_rows = rows(sources.verify(path))
        _unique([r["bank_line"] for r in statement_rows], "statement")
        statements = {r["bank_line"]: r for r in statement_rows}
        for adjustment in sorted(bank.get("adjustments", []), key=lambda a: (a["ref"], a["category"])):
            reference = adjustment.get("ref")
            if not isinstance(reference, str) or not reference:
                raise ValueError("Bank correction needs its source reference")
            stage, event = "bank_adjustment", f"bank:{bank['account']}:{reference}"
            day = ctx.last.isoformat()  # Flat bank output is a close adjustment, unless its event is dated.
            link = None
            if adjustment["category"] == "POOLING_NOT_BOOKED":
                event, link = _pool_link(bank, adjustment, ctx, statements)
                day = link["statement"]["booking_date"]
            elif reference in statements:
                event, day = reference, statements[reference]["booking_date"]
            owner = (event, stage)
            if owner in owners:
                raise ValueError("Duplicate bank correction event/stage")
            owners.add(owner)
            entry = {"id": "M5DEP-BANK-" + digest(owner)[:24], "company": bank["company"],
                     "posting_date": day, "document_date": day,
                     "reference": link["original_mirror_reference"] if link else reference,
                     "currency": ctx.directory.currency(bank["company"]), "source": "BANK_DELIVERY",
                     "lines": deepcopy(adjustment["lines"])}
            problems = validate_entry(entry, ctx.validation)
            if problems:
                raise ValueError(f"Invalid bank delivery {bank['account']}/{reference}: {'; '.join(problems)}")
            item = _owned(entry, event, stage, sources.delivery_source("bank_rec"),
                          f"{bank['account']}/adjustments/ref={reference}")
            # A projected entry has its own ID; ref can name an original being reversed.
            # Never mistake that original ref for the correction's identity.
            if _already_recorded(entry, recorded):
                skipped.append(entry["id"])
            entries.append(item)  # Ownership restores idempotence for supplied pre-existing producer entries.
            if link is not None:
                if event in links:
                    raise ValueError("Duplicate pooling link")
                links[event] = list(owner)
                link_audit.append({**link, "owner": list(owner), "entry_id": entry["id"]})
    delivery = {"producer": sources.producer("bank_rec"), "complete": True, "entries": entries,
                "pooling_links": links, "evidence": evidence(sources.manifest_name, "bank_projection")}
    return delivery, {"scope": "all bank task accounts and all supplied corrections", "accounts": sorted(bank_ids),
                       "adjustments": len(entries), "pooling_links": link_audit,
                       "already_recorded": skipped, "currency_semantics": "flat adjustment cents are local; no document amount/currency invented",
                       "reference_semantics": "pooling header uses the independently verified ERP mirror reference; original bank delivery ref retained in evidence",
                       "undated_non_statement_adjustments": "posted at the declared phase close; input lines copied unchanged"}
