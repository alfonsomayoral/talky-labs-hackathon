"""#91: both parties are checked against the supplied act/360 loan agreement."""
from __future__ import annotations

from decimal import Decimal, localcontext

from kalmora.facts import Evidence
from kalmora.money import round_cents
from .calculation import monthly_interest
from .context import Context
from .model import Diagnostic, Finding, event_key


def loan_interest(ctx: Context, projected_entries: tuple[dict, ...] | None = None) -> tuple[list[Finding], list[Diagnostic]]:
    loan = ctx.agreements.get("loan")
    if not loan:
        return [], []
    calc = monthly_interest(loan, ctx.month)
    lender, borrower = loan["lender"], loan["borrower"]
    pair = ctx.pair(lender, borrower)
    if not pair:
        return [], []
    def accruals(entries):
        observed = {lender: 0, borrower: 0}
        evidence = {lender: [], borrower: []}
        for entry in entries:
            company = entry["company"]
            if company not in observed or not ctx.current(entry):
                continue
            # Accrued interest, not cash settlements or FX. Numeric accrual and
            # trading-partner classification are independent checks: a wrong
            # partner is not evidence of zero interest having been accrued.
            income_account = "76210000" if company == lender else "66210000"
            if not any(l["account"] == income_account for l in entry["lines"]):
                continue
            for line in entry["lines"]:
                if line["account"] == "55200000" and line.get("assignment") == loan["id"]:
                    signed = ctx.eur(entry, line)
                    observed[company] += signed if company == lender else -signed
                    evidence[company].append(ctx.evidence(entry, line))
        return observed, evidence
    observed, evidence = accruals(ctx.entries)
    effective, _ = accruals(projected_entries if projected_entries is not None else ctx.entries)
    expected = calc["rounded_cents"]
    findings, diagnostics = [], []
    for company, other, account in [(lender, borrower, "76210000"), (borrower, lender, "66210000")]:
        delta = expected - observed[company]
        if not delta:
            if effective[company] != expected:
                diagnostics.append(Diagnostic("EXISTING_INTEREST_CORRECTION_CONFLICT",
                    f"Prior projection changes already-correct {company} loan interest", (91,)))
            continue
        # The amount is expressed in comparison EUR; the journal is local currency.
        event = event_key("INTEREST_DAY_COUNT", loan["id"], company, ctx.month)
        local_delta = ctx.rates.convert_cents(delta, "EUR", ctx.directory.currency(company), ctx.last)
        debit_account, credit_account = (("55200000", account) if company == lender else (account, "55200000"))
        lines = []
        for acc, signed in [(debit_account, local_delta), (credit_account, -local_delta)]:
            line = {"account": acc, "debit": max(signed, 0), "credit": max(-signed, 0),
                    "currency": "EUR", "amount_doc": abs(delta),
                    "partner": other if acc == "55200000" else None,
                    "assignment": loan["id"] if acc == "55200000" else None,
                    "cost_center": None, "wbs": None}
            allocation = ctx.upstream.interest_allocations.get(company)
            if allocation and acc != "55200000":
                if allocation.account != acc:
                    raise ValueError("interest allocation account differs from loan account")
                line.update(cost_center=allocation.cost_center, wbs=allocation.wbs)
            lines.append(line)
        with localcontext() as lc:
            lc.prec = 50
            daily = Decimal(loan["principal"]) * Decimal(loan["rate_bp"]) / 10000 / 360
            implied = str(Decimal(observed[company]) / daily) if daily else None
        adjustment = ctx.new_entry(event, company, lines, reference=loan["id"])
        details = {"calculation": calc, "observed_eur_cents": observed,
                   "projected_accrual_eur_cents": effective,
                   "pair_difference_eur_cents": observed[lender] - observed[borrower],
                   "correction_eur_cents": delta, "correction_local_cents": local_delta,
                   "adjustment_currency": ctx.directory.currency(company),
                   "fx_date": ctx.last.isoformat(), "fx_units_per_eur": str(ctx.rates.as_of(ctx.last, ctx.directory.currency(company))),
                   "implied_actual_360_days": implied}
        finding = Finding(event, pair, "INTEREST_DAY_COUNT", abs(delta), company, "EUR", adjustment,
            tuple(evidence[lender] + evidence[borrower]) +
            (Evidence("erp/intercompany_agreements.json", "loan"), Evidence("POLITICAS_CONTABLES.md", "§6")), details)
        prior_owner = any(e.get("provenance") == {"event_id": event, "stage": "intercompany"}
                          for e in (projected_entries or ()))
        if effective[company] != observed[company]:
            if effective[company] == expected:
                if not prior_owner:
                    finding.proposed = None
                    finding.status = "already_corrected_externally"
                # Exact own replay still flows through Ledger ownership checking.
            else:
                finding.proposed = None
                finding.status = "blocked"
                diagnostics.append(Diagnostic("EXISTING_INTEREST_CORRECTION_CONFLICT",
                    f"Existing correction leaves {company} interest at {effective[company]}, expected {expected}",
                    (91,), event))
        findings.append(finding)
    return findings, diagnostics
