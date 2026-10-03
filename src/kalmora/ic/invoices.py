"""#90: nonreceipt is an AP inventory fact, not absence from the recorded book."""
from __future__ import annotations

from collections import defaultdict

from kalmora.facts import Evidence
from .context import Context
from .model import Allocation, Diagnostic, Finding, event_key


def _history_allocation(ctx: Context, issuer: str, receiver: str) -> Allocation | None:
    """Require one consistent, evidenced historical expense/cost-object pattern.

    This is not an AP extractor or a default-CC heuristic. Mixed patterns require
    the caller's explicit document allocation instead of guessing the latest one.
    """
    patterns = {}
    issued_refs = {e.get("reference") for e in ctx.entries if e["company"] == issuer
                   and any(l["account"] == "43300000" and ctx.directory.resolve(l.get("partner")) == receiver
                           for l in e["lines"])}
    for entry in ctx.entries:
        if entry["company"] != receiver or entry.get("reference") not in issued_refs:
            continue
        if not any(l["account"] == "40300000" and l["credit"] > l["debit"]
                   and ctx.directory.resolve(l.get("partner")) == issuer for l in entry["lines"]):
            continue
        expenses = [l for l in entry["lines"] if l["account"].startswith("6") and l["debit"] > l["credit"]]
        if len(expenses) != 1 or bool(expenses[0].get("cost_center")) == bool(expenses[0].get("wbs")):
            continue
        line = expenses[0]
        key = (line["account"], line.get("cost_center"), line.get("wbs"))
        patterns[key] = ctx.evidence(entry, line)
    if len(patterns) != 1:
        return None
    (account, cc, wbs), evidence = next(iter(patterns.items()))
    return Allocation(account, cc, wbs, evidence)


def invoices_in_transit(ctx: Context, before_entries: tuple[dict, ...]) -> tuple[list[Finding], list[Diagnostic]]:
    coverage = ctx.upstream.ap_coverage
    if coverage is None or not coverage.complete:
        return [], [Diagnostic("AP_RECEIPT_COVERAGE_PENDING",
            "#55 must supply complete, phase-matched AP receipt coverage; missing postings do not prove nonreceipt",
            (55, 88, 90), evidence=(() if coverage is None else (coverage.evidence,)))]
    if coverage.month != ctx.month:
        raise ValueError("AP receipt coverage belongs to a different phase month")
    received = {(r.issuer, r.company, r.reference) for r in coverage.receipts
                if r.received_on <= ctx.last.isoformat()}
    for entry in before_entries:
        if entry.get("posting_date", "") > ctx.last.isoformat():
            continue
        for line in entry["lines"]:
            if line["account"] == "40300000" and line["credit"] > line["debit"]:
                issuer = ctx.directory.resolve(line.get("partner"))
                reference = line.get("assignment") or entry.get("reference")
                if issuer and reference:
                    received.add((issuer, entry["company"], reference))
    issued = defaultdict(list)
    for entry in before_entries:
        if entry.get("posting_date", "") > ctx.last.isoformat():
            continue
        income = [l for l in entry["lines"] if l["account"].startswith("7") and l["credit"] > l["debit"]]
        controls = [l for l in entry["lines"] if l["account"] == "43300000" and l["debit"] > l["credit"]]
        if not income or len(controls) != 1:
            continue
        other = ctx.directory.resolve(controls[0].get("partner"))
        ref = controls[0].get("assignment") or entry.get("reference")
        if other and ref and ctx.pair(entry["company"], other):
            issued[entry["company"], other, ref].append((entry, controls[0], income))
    findings, diagnostics = [], []
    for identity, versions in sorted(issued.items()):
        if identity in received:
            continue
        issuer, receiver, ref = identity
        versions.sort(key=lambda item: (item[0]["posting_date"], item[0]["id"]))
        entry, control, income = versions[0]
        amounts = {(ctx.eur(e, c), -sum(ctx.eur(e, l) for l in inc)) for e, c, inc in versions}
        if len(amounts) != 1:
            diagnostics.append(Diagnostic("ISSUED_INVOICE_CONFLICT", ref, (90,), evidence=(ctx.evidence(entry),)))
            continue
        gross_eur, net_eur = next(iter(amounts))
        if net_eur <= 0 or gross_eur < net_eur:
            diagnostics.append(Diagnostic("INVOICE_NET_NOT_SUPPORTED", ref, (90,), evidence=(ctx.evidence(entry),)))
            continue
        allocation = ctx.upstream.invoice_allocations.get(identity) or _history_allocation(ctx, issuer, receiver)
        if not allocation:
            diagnostics.append(Diagnostic("INVOICE_ALLOCATION_PENDING",
                f"No unique evidenced expense allocation for {issuer}->{receiver} {ref}", (90,),
                evidence=(ctx.evidence(entry),)))
            continue
        if not allocation.account.startswith("6"):
            diagnostics.append(Diagnostic("INVOICE_ALLOCATION_NOT_EXPENSE", ref, (90,), evidence=(allocation.evidence,)))
            continue
        # Price basis is issued net (corroborated by agreement when applicable),
        # never the receivable's VAT-inclusive amount.
        invoice_day = entry.get("document_date") or entry["posting_date"]
        net_local = ctx.rates.convert_cents(net_eur, "EUR", ctx.directory.currency(receiver), invoice_day)
        event = event_key("INVOICE_IN_TRANSIT", issuer, receiver, ref)
        lines = [{"account": allocation.account, "debit": net_local, "credit": 0,
                  "partner": None, "cost_center": allocation.cost_center, "wbs": allocation.wbs,
                  "currency": "EUR", "amount_doc": net_eur},
                 {"account": "40090000", "debit": 0, "credit": net_local, "partner": issuer,
                  "cost_center": None, "wbs": None, "assignment": ref,
                  "currency": "EUR", "amount_doc": net_eur}]
        adjustment = ctx.new_entry(event, receiver, lines, reference=ref)
        adjustment["document_date"] = invoice_day
        existing = []
        for prior in before_entries:
            if prior["company"] != receiver or prior.get("posting_date", "") > ctx.last.isoformat():
                continue
            matches = [l for l in prior["lines"] if l["account"] == "40090000"
                       and ctx.directory.resolve(l.get("partner")) == issuer
                       and (l.get("assignment") or prior.get("reference")) == ref]
            if matches:
                existing.append((prior, sum(l["credit"] - l["debit"] for l in matches)))
        accrued_local = sum(a for _, a in existing)
        details = {"issuer_entry": entry["id"], "reference": ref, "gross_eur_cents": gross_eur,
                   "expense_net_eur_cents": net_eur, "expense_net_local_cents": net_local,
                   "adjustment_currency": ctx.directory.currency(receiver), "fx_date": invoice_day,
                   "already_accrued_local_cents": accrued_local,
                   "existing_accrual_entries": [e["id"] for e, _ in existing]}
        fee = ctx.agreements.get("management_fees", {}).get(receiver)
        if fee and fee.get("issuer") == issuer:
            contract_amount = fee.get("monthly_eur_" + invoice_day[:4])
            details["agreement_monthly_eur_cents"] = contract_amount
            details["agreement_matches_issued_net"] = contract_amount == net_eur if contract_amount is not None else None
        finding = Finding(event, ctx.pair(issuer, receiver), "INVOICE_IN_TRANSIT", gross_eur,
                          receiver, "EUR", adjustment,
                          (ctx.evidence(entry, control), allocation.evidence, coverage.evidence,
                           Evidence("POLITICAS_CONTABLES.md", "§6")), details)
        if accrued_local:
            finding.proposed = None
            expense_local = sum(l["debit"] - l["credit"] for prior, _ in existing for l in prior["lines"]
                                if (l["account"], l.get("cost_center"), l.get("wbs")) ==
                                (allocation.account, allocation.cost_center, allocation.wbs))
            if accrued_local == net_local and expense_local == net_local:
                finding.status = "already_accrued"
            else:
                finding.status = "blocked"
                diagnostics.append(Diagnostic("EXISTING_ACCRUAL_CONFLICT",
                    f"Accrual for {ref}: liability={accrued_local}, allocated expense={expense_local}, expected={net_local}; preserve external ownership",
                    (90,), event, tuple(ctx.evidence(e) for e, _ in existing)))
        findings.append(finding)
    return findings, diagnostics
