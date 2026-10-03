"""Task-order invoice IDs compatible with the existing v0 workflow.

This is an operational numbering convention, not evidence that ERP gaps were
reserved. The already built invoices supply series identities; only the active
ERP inventory supplies occupied positions. No company-prefix catalogue or golden
data is used, and no invoice/ledger/master object is mutated.
"""
from __future__ import annotations

import re
from typing import Sequence

from ..data import PhaseData
from .model import BillingItem, BillingRun, Decision


NUMBERING_VERSION = "ar-task-order-numbering-v1"


def allocate_invoice_numbers(data: PhaseData, items: Sequence[BillingItem],
                             preliminary: BillingRun) -> dict[str, str]:
    """Allocate only resolved invoices, in explicit billing task order.

    For each ERP-derived company/series, take the smallest unused positive
    position: fill existing gaps first, then append. Pending/unresolved items
    consume no number. Invoice dates/order do not change this task convention.
    The caller rebuilds its pure billing run with these explicit overrides so
    invoice numbers, journal references and receivable assignments agree.
    """
    inventory = {item.id: item for item in items}
    if len(inventory) != len(items):
        raise ValueError("billing task inventory IDs must be unique")
    results = {result.item.id: result for result in preliminary.results}
    if len(results) != len(preliminary.results) or not set(results) <= set(inventory):
        raise ValueError("preliminary billing results must uniquely belong to the task inventory")
    if any(inventory[identity] != result.item for identity, result in results.items()):
        raise ValueError("preliminary billing metadata differs from the task inventory")
    used: dict[tuple[str, str], set[int]] = {}
    for row in data.table("ar_invoices"):
        match = re.fullmatch(r"(.*?)([0-9]+)", row["id"])
        if match:
            used.setdefault((row["company"], match[1]), set()).add(int(match[2]))
    next_position: dict[tuple[str, str], int] = {}
    assigned: dict[str, str] = {}
    for item in items:
        result = results.get(item.id)
        if result is None or result.decision is not Decision.INVOICE:
            continue
        invoice = result.invoice
        if invoice is None:
            raise ValueError("resolved invoice result has no invoice")
        match = re.fullmatch(r"(.*?)([0-9]+)", invoice.number)
        if match is None:
            raise ValueError("preliminary invoice has no identifiable numeric series")
        prefix, width = match[1], len(match[2])
        scope = (item.company, prefix)
        occupied = used.setdefault(scope, set())
        position = next_position.get(scope, 1)
        while position in occupied:
            position += 1
        assigned[item.id] = f"{prefix}{position:0{width}d}"
        occupied.add(position)
        next_position[scope] = position + 1
    return assigned


__all__ = ["NUMBERING_VERSION", "allocate_invoice_numbers"]
