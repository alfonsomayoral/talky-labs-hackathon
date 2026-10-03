"""Single-application projection on the shared Ledger, without changing ERP.

A producer's transient ID is not an accounting identity. The handoff supplies
business keys and original aliases; a financial fingerprint detects conflicting
representations of the same event instead of posting both.
"""
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from typing import Iterable

from ..ledger import Ledger
from ..model import JournalEntry
from .contracts import Handoff, digest, require

LINE_DIMENSIONS = ("account", "debit", "credit", "partner", "assignment", "cost_center", "wbs", "tax_code")


def financial_signature(entry: JournalEntry) -> str:
    # Currency/document amounts are checked separately on FX facts. This signature
    # deliberately tolerates a producer enriching a legacy local-only journal.
    values = [{key: row.get(key) for key in LINE_DIMENSIONS} for row in entry["lines"]]
    return digest({"company": entry["company"], "lines": sorted(values, key=digest)})


def dense_balances(ledger: Ledger) -> list[dict]:
    """Account, partner, assignment, document currency and cost grain retained."""
    keys = ("account", "partner", "assignment", "currency", "cost_center", "wbs", "tax_code")
    balances: dict[tuple, int] = defaultdict(int)
    for entry in ledger.iter_entries():
        for row in entry["lines"]:
            key = (entry["company"], *(row.get(k) for k in keys))
            balances[key] += row["debit"] - row["credit"]
    return [dict(zip(("company", *keys), key), balance=amount)
            for key, amount in sorted(balances.items(), key=lambda pair: repr(pair[0])) if amount]


def account_balances(ledger: Ledger) -> list[dict]:
    return [{"company": key.company, "account": key.account, "balance": amount}
            for key, amount in sorted(ledger.balances().items()) if amount]


def position(ledger: Ledger, company: str, account: str, *, partner: str | None = None,
             assignment: str | None = None, reference: str | None = None,
             filter_partner: bool = False, filter_assignment: bool = False) -> int:
    result = 0
    for entry in ledger.iter_entries():
        if entry["company"] != company:
            continue
        if reference is not None and entry.get("reference") != reference:
            continue
        for row in entry["lines"]:
            if row["account"] != account:
                continue
            if filter_partner and row.get("partner") != partner:
                continue
            if filter_assignment and row.get("assignment") != assignment:
                continue
            result += row["debit"] - row["credit"]
    return result


@dataclass
class Projection:
    recorded: Ledger
    pre_close: Ledger
    log: list[dict]


def project(entries: Iterable[JournalEntry], handoff: Handoff) -> Projection:
    closing = handoff.payload["closing_date"]
    original = Ledger.from_entries(e for e in entries if e["posting_date"] <= closing)
    baseline = digest(original.entries)
    current = original.project()
    by_id = {e["id"]: e for e in original.iter_entries() if e.get("id")}
    by_reference: dict[tuple, list] = defaultdict(list)
    for e in original.iter_entries():
        by_reference[e["company"], e.get("reference")].append(e)
    semantic = {}
    for item in handoff.payload.get("recorded_events", []):
        identifiers = item["journal_ids"]
        require(all(i in by_id for i in identifiers), "recorded alias not present in ERP")
        semantic[item["business_key"]] = [by_id[i] for i in identifiers]
    restored = {tuple(e["provenance"][key] for key in ("event_id", "stage")): e
                for e in original.iter_entries() if e.get("provenance")}
    log = []
    for dependency in handoff.payload["dependencies"]:
        for event in dependency["postings"]:
            journal = deepcopy(event["journal_entry"])
            signature = financial_signature(journal)
            owner = event["event_id"], event["stage"]
            business_owner = event["business_key"], event["stage"]
            item = {"producer": dependency["producer"], "event_id": owner[0], "stage": owner[1],
                    "business_key": event["business_key"], "provenance": dependency["provenance"],
                    "signature": signature, "evidence": event["evidence"]}
            candidates = list(semantic.get(event["business_key"], []))
            candidates += [by_id[i] for i in event.get("recorded_ids", []) if i in by_id]
            if owner in restored:
                candidates.append(restored[owner])
            # A changed adapter event ID with the same business key must not post twice.
            if business_owner in restored:
                candidates.append(restored[business_owner])
            if candidates:
                require(any(financial_signature(e) == signature for e in candidates),
                        f"conflicting representation of {event['business_key']}")
                item["action"] = "already_recorded"
                item["recorded_ids"] = [e.get("id") for e in candidates]
            else:
                matches = [e for e in by_reference[journal["company"], journal.get("reference")]
                           if financial_signature(e) == signature]
                if matches:
                    item["action"] = "equivalent_recorded_reference"
                    item["recorded_ids"] = [e.get("id") for e in matches]
                else:
                    # Stable ID depends on business identity, not mock/real source label.
                    journal["id"] = "M6-PRE-" + digest(business_owner)[:24]
                    current.add_entry(journal, event_id=event["business_key"], stage=event["stage"])
                    item["action"] = "projected"
                    by_reference[journal["company"], journal.get("reference")].append(journal)
                restored[business_owner] = journal
            log.append(item)
    require(digest(original.entries) == baseline, "ERP changed during projection")
    return Projection(original, current, log)
