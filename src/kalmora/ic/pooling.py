"""#93: original ERP incidence, explicit bank-owned correction, never an IC entry."""
from __future__ import annotations

from collections import defaultdict

from kalmora.facts import Evidence
from .context import Context
from .model import Diagnostic, Finding, event_key


def pooling_not_booked(ctx: Context, projected_entries: tuple[dict, ...]) -> tuple[list[Finding], list[Diagnostic]]:
    agreement = ctx.agreements.get("cash_pooling")
    if not agreement:
        return [], []
    account_ids = [agreement["header"], *agreement["participants"]]
    accounts_by_company = defaultdict(list)
    for account_id in account_ids:
        bank = ctx.banks[account_id]
        accounts_by_company[bank["company"]].append(bank)
    groups = defaultdict(list)
    for entry in ctx.entries:
        if not ctx.current(entry) or not entry.get("reference"):
            continue
        controls = [l for l in entry["lines"] if l["account"] == "55200000"]
        cash = [l for l in entry["lines"] if l["account"].startswith("572")]
        if len(controls) != 1 or len(cash) != 1:
            continue
        if (entry["company"] not in accounts_by_company
                or cash[0]["account"] not in {b["gl_account"] for b in accounts_by_company[entry["company"]]}):
            continue
        if ctx.directory.resolve(controls[0].get("partner")) not in accounts_by_company:
            continue
        groups[entry["reference"]].append((entry, controls[0], cash[0]))
    findings, diagnostics = [], []
    for reference, legs in sorted(groups.items()):
        # A mirror with an incorrect partner belongs to #92, not to missing pooling.
        if len(legs) != 1:
            continue
        entry, control, cash = legs[0]
        source, target = entry["company"], ctx.directory.resolve(control["partner"])
        pair = ctx.pair(source, target)
        if not pair:
            continue
        event = event_key("POOLING_NOT_BOOKED", source, target, reference)
        target_banks = accounts_by_company[target]
        finding = Finding(event, pair, "POOLING_NOT_BOOKED", abs(ctx.eur(entry, control)), target, "EUR", None,
                          (ctx.evidence(entry, control), Evidence("erp/intercompany_agreements.json", "cash_pooling"),
                           Evidence("POLITICAS_CONTABLES.md", "§6")),
                          {"reference": reference, "original_missing_company": target,
                           "adjustment_owner": "banks", "bank_correction": None}, "pending_bank")
        findings.append(finding)
        if len(target_banks) != 1 or target_banks[0]["currency"] != ctx.directory.currency(source):
            diagnostics.append(Diagnostic("POOLING_BANK_MAPPING_AMBIGUOUS", reference, (73, 93), event))
            continue
        bank = target_banks[0]
        bank_amount = -(cash["debit"] - cash["credit"])
        expected_ic = -(control["debit"] - control["credit"])
        statements = [b for b in ctx.data.bank_lines(bank["id"], ctx.month)
                      if b["booking_date"] == entry["posting_date"] and b["amount"] == bank_amount
                      and b["currency"] == bank["currency"]]
        if len(statements) != 1:
            diagnostics.append(Diagnostic("POOLING_STATEMENT_EVIDENCE_PENDING",
                f"Need unique statement support for {reference} in {bank['id']}", (73, 93), event))
            continue
        statement = statements[0]
        bank_line = statement["bank_line"]
        finding.details.update(bank_line=bank_line, bank_account=bank["id"], expected_ic_local_cents=expected_ic,
                               expected_bank_local_cents=bank_amount)
        finding.evidence += (Evidence(f"bank/{bank['id']}/{ctx.month}.lines.jsonl", bank_line),)
        delivery = ctx.upstream.banks
        owner = delivery.pooling_links.get(bank_line) if delivery else None
        if owner is None:
            diagnostics.append(Diagnostic("POOLING_BANK_CORRECTION_PENDING",
                f"#73/#75 must provide the bank-owned correction linked to {bank_line} ({reference})",
                (73, 75, 93), event, finding.evidence))
            continue
        owned = next(o for o in delivery.entries if (o.event_id, o.stage) == tuple(owner))
        available = [e for e in projected_entries if e.get("provenance") == {"event_id": owner[0], "stage": owner[1]}]
        if len(available) != 1:
            diagnostics.append(Diagnostic("POOLING_CORRECTION_NOT_PROJECTED", bank_line, (75, 93), event))
            continue
        correction = available[0]
        ic_amount = sum(l["debit"] - l["credit"] for l in correction["lines"]
                        if l["account"] == "55200000" and l.get("partner") == source)
        cash_amount = sum(l["debit"] - l["credit"] for l in correction["lines"] if l["account"] == bank["gl_account"])
        if correction["company"] != target or ic_amount != expected_ic or cash_amount != bank_amount:
            diagnostics.append(Diagnostic("POOLING_CORRECTION_MISMATCH", bank_line, (73, 93), event, (owned.evidence,)))
            continue
        finding.status = "resolved_by_banks"
        finding.details["bank_correction"] = {"event_id": owner[0], "stage": owner[1], "entry_id": correction["id"]}
        finding.evidence += (owned.evidence,)
    return findings, diagnostics
