"""Close (M6) fed with this run's real upstream deliveries instead of golden fixtures.

Reuses the M6 handoff builder (``tools/m6_fixture.build``) with its loader pointed at ``deliverables/``,
completing the fields the builder reads that the delivery format does not carry: AP journal headers
(posting date = day received, inside the month), bank adjustment references, cash company and date,
billing item metadata. Needs the M6 engine (``kalmora.close``, PR #197) and ``tools/`` next to ``src/``.
"""
from __future__ import annotations

import json
import sys
from calendar import monthrange
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..data import PhaseData
from ..money import company_local_currency

TOOLS = Path(__file__).resolve().parents[3] / "tools"


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


def run_close(phase: Path, deliverables: Path, work: Path) -> Path:
    """Build the real-upstream handoff and run the close engine; returns the produced close.jsonl."""
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    import m6_fixture  # noqa: PLC0415 - M6 tool module, importable once tools/ is on the path
    from ..close.__main__ import execute
    from ..close.contracts import file_hash, seal

    data = PhaseData(phase)
    enrich = _enricher(phase, data)

    def load_upstream(_phase: Path, producer: str):
        path = deliverables / f"{producer}.jsonl"
        rows = [json.loads(line, parse_float=Decimal) for line in path.read_text().splitlines() if line.strip()]
        return enrich(producer, rows), file_hash(path)

    m6_fixture.load_upstream = load_upstream
    bundle = m6_fixture.build(phase)
    for dependency in bundle["dependencies"]:
        dependency["provenance"] = "real"
    bundle["adapter"].update(version="v0_real_handoff/v1", integration="real_upstream")
    work.mkdir(parents=True, exist_ok=True)
    handoff = work / "dependencies.json"
    handoff.write_bytes(m6_fixture.encoded(seal(bundle)))
    execute(phase, handoff, work / "frozen")
    return work / "frozen" / "close.jsonl"
