"""Drivers of the v0 engines: one phase directory in, delivery rows out. Golden is never read."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import ap_decide, proto
from .arlib import Ctx, compute, parse_document, pdf_text

POSTING = ("POST", "POST_PAYMENT_BLOCK")
AP_FIELDS = ("doc_id", "document_type", "decision", "reasons", "company", "vendor_id", "invoice_number", "invoice_date",
             "currency", "net", "tax", "gross", "withholding", "retention", "payable", "duplicate_of", "payee",
             "payment_block", "action", "action_data")
CODED_FIELDS = ("company", "vendor_id", "invoice_number", "invoice_date", "currency", "net", "tax", "gross",
                "withholding", "retention", "payable")
NULLABLE_FIELDS = {"vendor_id", "invoice_number", "duplicate_of", "payee", "payment_block"}


def solve_ap(phase: Path) -> tuple[list[dict[str, Any]], int]:
    """Decide every AP task, then code and post the POST/POST_PAYMENT_BLOCK ones (goods receipts are
    consumed only by posted invoices). Returns the rows in task order and the number of coding errors."""
    decisions, _, context = ap_decide.process_phase(str(phase))
    by_id = {row["doc_id"]: row for row in decisions}
    posted = {doc for doc, row in by_id.items() if row["decision"] in POSTING}
    coded, _, _ = proto.run(str(phase), only_ids=posted, gold=by_id)
    # Keep factual service allocation for received invoices even when AP cannot
    # post them. This independent pass cannot consume a posted invoice's GR.
    factual = {doc for doc, row in by_id.items()
               if doc not in posted and row["document_type"] == "INVOICE"
               and row.get("vendor_id") in context.vendors
               and not context.vendors[row["vendor_id"]].get("po_required")}
    observed, _, _ = proto.run(str(phase), only_ids=factual, gold=by_id, independent=True) if factual else ({}, None, None)
    rows, errors = [], 0
    for doc in json.loads((phase / "tasks" / "ap_documents.json").read_text(encoding="utf-8")):
        row = {key: value for key in AP_FIELDS
               if (value := by_id[doc].get(key)) is not None or key in NULLABLE_FIELDS}
        if doc in posted:
            result = coded.get(doc) or {}
            if not result or "error" in result:
                errors += 1
            else:
                row.update({key: result[key] for key in CODED_FIELDS})
                row["lines"], row["journal_entry"] = result["lines"], result["journal_entry"]
                for line in row["journal_entry"]["lines"]:
                    if line["account"] == "40700000" and not line.get("partner"):
                        line["partner"] = row["vendor_id"]
        elif doc in observed and "error" not in observed[doc]:
            row["lines"] = observed[doc]["lines"]
        rows.append(row)
    return rows, errors


def solve_billing(phase: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Invoice every billing item from its documents; returns the rows and the pending certifications (WIP)."""
    ctx = Ctx(str(phase))
    rows, pending = [], []
    for item_id in json.loads((phase / "tasks" / "ar_billing_items.json").read_text(encoding="utf-8")):
        folder = phase / "inbox" / "ar" / "billing" / item_id
        item = json.loads((folder / "item.json").read_text(encoding="utf-8"))
        text = "\n".join(pdf_text(str(folder / name)) for name in item["documents"] if name.lower().endswith(".pdf"))
        row, wip, _ = compute(ctx, parse_document(item, text))
        rows.append(row)
        if wip:
            pending.append(wip)
    return rows, pending


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows),
                         encoding="utf-8")
    temporary.replace(path)
    return path
