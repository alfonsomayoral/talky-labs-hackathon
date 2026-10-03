"""AR billing engine: resolved facts + masters + history -> in-memory ``BillingResult`` list.

Stages (policies §3.1): resolve the contract and cross-check the document, decide invoice or
skip, compute amounts, assemble invoice and journal entry, validate. Everything here is a
pure function of the inputs; document reading happens before (see ``inputs``). An item the
engine cannot decide is returned as ``Unresolved`` with its reasons, never guessed.
"""
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Mapping, Sequence

from ..data import PhaseData
from ..model import Diagnostic, ValidationContext
from ..money import company_local_currency
from ..validation import validate_entry
from . import compute
from .calendar import last_day_of_month, roll_forward
from .inputs import (BillingFacts, CertificationFacts, PpaFacts, RevisionFacts, ServiceFacts,
                     SettlementFacts)
from .journal import build_entry
from .model import (BillingItem, BillingResult, BillingRun, BillingType, Decision, Deduction, Face,
                    Invoice, InvoiceLine, PendingWip, Unresolved)

INCOME = {"OBRA": "70510000", "SERVICE": "70500000", "REVISION": "70520000", "ENERGY": "70530000"}
ENERGY_INVOICE_DAY = {BillingType.PPA: 3, BillingType.MARKET_SETTLEMENT: 6}
"""Day of the month after the period on which the history dates energy invoices (then rolled
to the next national business day). Observed in 40 of 40 historical invoices; not in the policy."""
REVISION_INVOICE_DAY = 4
"""Day of the decree's approval month on which the history dates revision invoices (12 of 12)."""


class _Blocked(Exception):
    def __init__(self, *reasons: Diagnostic) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass
class _Draft:
    item: BillingItem
    decision: Decision
    date: str = ""
    lines: tuple[InvoiceLine, ...] = ()
    notes: list[Diagnostic] = field(default_factory=list)
    evidence: tuple[Any, ...] = ()


def load_items(data: PhaseData) -> list[BillingItem]:
    """Billing items of the phase, in ``tasks/ar_billing_items.json`` order."""
    items = []
    for item_id in data.table("tasks/ar_billing_items"):
        meta = data.table(f"inbox/ar/billing/{item_id}/item.json")
        items.append(BillingItem(meta["billing_item"], BillingType(meta["type"]), meta["company"],
                                 meta["contract"], meta["customer"], meta["month"]))
    return items


def _previous_month(month: str) -> str:
    year, number = int(month[:4]), int(month[5:])
    return f"{year - 1}-12" if number == 1 else f"{year}-{number - 1:02d}"


def _month_range(first: str, last_exclusive: str) -> list[str]:
    months, current = [], first
    while current < last_exclusive:
        months.append(current)
        year, number = int(current[:4]), int(current[5:])
        current = f"{year + 1}-01" if number == 12 else f"{year}-{number + 1:02d}"
    return months


class _Context:
    """Masters and history of one phase, with point-in-time lookups."""

    def __init__(self, data: PhaseData, strict: bool,
                 invoice_numbers: Mapping[str, str] | None = None) -> None:
        self.data, self.strict = data, strict
        self.rates = {code: row for code, row in data.table("tax_codes")["tax_codes"].items()
                      if row["kind"] in {"output", "output_reverse"}}
        self.country = {c["code"]: c["country"] for c in data.companies}
        self.advance_used: dict[tuple[str, str], int] = {}
        self.series: dict[str, int] = {}
        self.invoice_numbers = dict(invoice_numbers or {})
        self.claimed_numbers: set[tuple[str, str, int]] = set()
        self._invoices: dict[str, list[dict[str, Any]]] = {}
        self.revised_fees: dict[tuple[str, str, str], int] = {}

    def invoices(self, contract: str) -> list[dict[str, Any]]:
        if contract not in self._invoices:
            self._invoices[contract] = sorted(self.data.find("ar_invoices", contract=contract),
                                              key=lambda r: (r["date"], r["id"]))
        return self._invoices[contract]

    def contract(self, item: BillingItem) -> dict[str, Any]:
        try:
            contract = self.data.get("sales_contracts", item.contract)
        except KeyError:
            raise _Blocked(f"contract: {item.contract} not in sales_contracts") from None
        if contract["company"] != item.company or contract["customer"] != item.customer:
            raise _Blocked("contract: company or customer differ from the billing item")
        return contract

    def cost_center_name(self, cost_center: str) -> str:
        try:
            return self.data.get("cost_centers", cost_center)["desc"]
        except KeyError:
            raise _Blocked(f"cost center {cost_center} not in the master") from None

    def advance_available(self, company: str, customer: str, before: str) -> int:
        """Advance received (gross) minus amortizations already taken, from the AR history."""
        balance = 0
        for row in self.data.find("ar_invoices", company=company, customer=customer):
            if row["date"] >= before:
                continue
            if row["kind"] == "advance":
                balance += row["gross"]
            balance -= sum(d["amount"] for d in row["deductions"] if d["code"] == "ADV_AMORT")
        return balance - self.advance_used.get((company, customer), 0)


def _decide_certification(ctx: _Context, item: BillingItem, contract: Mapping[str, Any],
                          facts: CertificationFacts) -> _Draft:
    if type(facts.approved) is not bool:
        raise _Blocked("certification approval must be an observed boolean")
    if facts.month != item.month:
        raise _Blocked(f"certification month {facts.month} differs from item month {item.month}")
    if sum(c.amount for c in facts.chapters) != facts.current:
        raise _Blocked("chapters do not add up to the current certification")
    if facts.cumulative - facts.previous != facts.current:
        raise _Blocked("current certification differs from cumulative minus previous")
    if facts.current < 0:
        raise _Blocked("negative certifications are not invoice decisions")
    project = ctx.data.get("projects", contract["project"])["wbs"]
    lines = []
    for chapter in facts.chapters:
        if not 1 <= chapter.number <= len(project):
            raise _Blocked(f"chapter {chapter.number} has no WBS element in {contract['project']}")
        lines.append(InvoiceLine(chapter.description, chapter.amount, INCOME["OBRA"],
                                 wbs=project[chapter.number - 1]["id"]))
    if not facts.approved:
        return _Draft(item, Decision.SKIP_PENDING_APPROVAL, lines=tuple(lines), evidence=facts.evidence)
    year, month = int(item.month[:4]), int(item.month[5:])
    day = last_day_of_month(year, month).isoformat()
    notes: list[Diagnostic] = []
    earlier = sorted((h["cert"] for h in ctx.data.find("billing_history", contract=item.contract,
                                                       type="OBRA_CERTIFICATION")
                      if h["cert"]["month"] < item.month), key=lambda c: c["month"])
    if earlier:
        approved = [c["cumulative"] for c in earlier if c["approved"]]
        expected = approved[-1] if approved else 0
        if expected != facts.previous:
            raise _Blocked(f"previous certified {facts.previous} differs from the last approved "
                           f"cumulative {expected}")
    else:
        notes.append("previous certified not verifiable: the contract has no earlier certification in the history")
    if ctx.strict and any(r["kind"] == "invoice" and r["date"] >= day for r in ctx.invoices(item.contract)):
        raise _Blocked("a certification of this month or later is already invoiced")
    return _Draft(item, Decision.INVOICE, day, tuple(lines), notes, facts.evidence)


def _decide_service(ctx: _Context, item: BillingItem, contract: Mapping[str, Any],
                    facts: ServiceFacts) -> _Draft:
    if facts.month != item.month:
        raise _Blocked(f"service month {facts.month} differs from item month {item.month}")
    day = last_day_of_month(int(item.month[:4]), int(item.month[5:])).isoformat()
    if ctx.strict and any(r["kind"] == "invoice" and r["date"][:7] == item.month
                          for r in ctx.invoices(item.contract)):
        raise _Blocked("a monthly service of this period is already invoiced")
    revised = ctx.revised_fees.get((item.company, item.contract, item.month))
    if revised is not None and facts.canon != revised:
        raise _Blocked(f"service canon {facts.canon} differs from approved revision {revised}")
    lines = [InvoiceLine(f"{contract['name']} – servicio mensual {item.month}", facts.canon,
                         INCOME["SERVICE"], cost_center=contract["cc"])]
    draft = _Draft(item, Decision.INVOICE, day, evidence=facts.evidence)
    for extra in facts.extras:
        if type(extra.approved) is not bool:
            raise _Blocked("extra service conformity must be an observed boolean")
        if extra.approved:
            lines.append(InvoiceLine(extra.description, extra.amount, INCOME["SERVICE"],
                                     cost_center=contract["cc"]))
        else:
            draft.notes.append(f"extra service {extra.order} omitted: pending municipal conformity")
    draft.lines = tuple(lines)
    return draft


def _decide_revision(ctx: _Context, item: BillingItem, contract: Mapping[str, Any],
                     facts: RevisionFacts) -> _Draft:
    if facts.approved_on[:7] != item.month:
        raise _Blocked("decree approval month differs from the item month")
    expected = _month_range(facts.effective[:7], item.month)
    if list(facts.months) != expected:
        raise _Blocked(f"decree months {list(facts.months)} differ from effective-to-approval months {expected}")
    if facts.new_fee <= facts.old_fee:
        raise _Blocked("revision does not increase the fee; credit notes are not decided here")
    if ctx.strict:
        for row in ctx.data.find("billing_history", contract=item.contract, type="PRICE_REVISION"):
            if set(row["revision"]["months"]) & set(facts.months):
                raise _Blocked("a revision of these months was already invoiced")
    diff = facts.new_fee - facts.old_fee
    lines = tuple(InvoiceLine(f"Revisión de precios {m} – {contract['name']}", diff, INCOME["REVISION"],
                              cost_center=contract["cc"]) for m in facts.months)
    return _Draft(item, Decision.INVOICE, f"{item.month}-{REVISION_INVOICE_DAY:02d}", lines, evidence=facts.evidence)


def _energy_date(item: BillingItem) -> str:
    return roll_forward(date(int(item.month[:4]), int(item.month[5:]), ENERGY_INVOICE_DAY[item.type])).isoformat()


def _check_energy(ctx: _Context, item: BillingItem, contract: Mapping[str, Any], period: str,
                  plants: Sequence[str]) -> None:
    if period != _previous_month(item.month):
        raise _Blocked(f"energy period {period} is not the month before {item.month}")
    unknown = sorted(set(plants) - set(contract["plants"]))
    if unknown or len(set(plants)) != len(plants):
        raise _Blocked(f"plants {unknown or 'repeated'} do not belong to contract {item.contract}")
    if ctx.strict and any(r["date"][:7] == item.month for r in ctx.invoices(item.contract)):
        raise _Blocked("an energy invoice of this month is already issued")


def _decide_ppa(ctx: _Context, item: BillingItem, contract: Mapping[str, Any], facts: PpaFacts) -> _Draft:
    _check_energy(ctx, item, contract, facts.period, [p.plant for p in facts.plants])
    if facts.share_bp != contract["share_bp"]:
        raise _Blocked(f"document share {facts.share_bp} differs from contract {contract['share_bp']}")
    if facts.price_mwh_cents != Decimal(contract["price_mwh"]):
        raise _Blocked(f"document price {facts.price_mwh_cents} differs from contract {contract['price_mwh']}")
    milli = tuple(p.mwh_milli for p in facts.plants)
    net = compute.ppa_net(mwh_milli=milli, share_bp=facts.share_bp, price_mwh_cents=facts.price_mwh_cents)
    contracted = sum(milli) * facts.share_bp // 10000
    mwh = f"{contracted / 1000:,.3f}".replace(",", "#").replace(".", ",").replace("#", ".")
    year, month = facts.period[:4], facts.period[5:]
    line = InvoiceLine(f"Energía suministrada PPA {month}/{year}: {mwh} MWh × {facts.price_mwh_cents / 100:.2f} €/MWh",
                       net, INCOME["ENERGY"], cost_center=contract["plants"][0])
    return _Draft(item, Decision.INVOICE, _energy_date(item), (line,), evidence=facts.evidence)


def _decide_market(ctx: _Context, item: BillingItem, contract: Mapping[str, Any],
                   facts: SettlementFacts) -> _Draft:
    _check_energy(ctx, item, contract, facts.period, [p.plant for p in facts.plants])
    year, month = facts.period[:4], facts.period[5:]
    lines = [InvoiceLine(f"Venta de energía en mercado {month}/{year} – {ctx.cost_center_name(p.plant)}",
                         p.amount, INCOME["ENERGY"], cost_center=p.plant) for p in facts.plants]
    if facts.deviations:
        lines.append(InvoiceLine(f"Coste de desvíos {month}/{year}", facts.deviations, INCOME["ENERGY"],
                                 cost_center=f"CC-{item.company}-ADM"))
    return _Draft(item, Decision.INVOICE, _energy_date(item), tuple(lines), evidence=facts.evidence)


_DECIDERS = {BillingType.OBRA_CERTIFICATION: (CertificationFacts, _decide_certification),
             BillingType.SERVICE_MONTHLY: (ServiceFacts, _decide_service),
             BillingType.PRICE_REVISION: (RevisionFacts, _decide_revision),
             BillingType.PPA: (PpaFacts, _decide_ppa),
             BillingType.MARKET_SETTLEMENT: (SettlementFacts, _decide_market)}


def _next_number(ctx: _Context, item: BillingItem, day: str) -> str:
    """Next invoice number of the contract's series (best effort; the scorer ignores it)."""
    last = next((r for r in reversed(ctx.invoices(item.contract)) if r["kind"] == "invoice"), None)
    if last is None:
        prefix, from_year = f"FA{day[2:4]}-", None
    else:
        match = re.match(r"^(.*?)(\d+)$", last["id"])
        prefix, from_year = (match.group(1), last["date"][:4]) if match else (f"FA{day[2:4]}-", None)
        year = day[:4]
        if from_year and year != from_year:
            prefix = prefix.replace(from_year, year).replace(from_year[2:], year[2:])
    if item.id in ctx.invoice_numbers:
        number = ctx.invoice_numbers[item.id]
        selected = re.fullmatch(r"(.*?)([0-9]+)", number)
        if selected is None or selected[1] != prefix or int(selected[2]) < 1:
            raise _Blocked("invoice number override differs from the ERP-derived series")
        position = (item.company, prefix, int(selected[2]))
        occupied = any((match := re.fullmatch(r"(.*?)([0-9]+)", row["id"]))
                       and match[1] == prefix and int(match[2]) == position[2]
                       for row in ctx.data.find("ar_invoices", company=item.company))
        if occupied or position in ctx.claimed_numbers:
            raise _Blocked("invoice number override collides with an existing or current invoice")
        ctx.claimed_numbers.add(position)
        return number
    if prefix not in ctx.series:
        top = 0
        for company_row in ctx.data.find("ar_invoices", company=item.company):
            tail = re.match(r"^(.*?)(\d+)$", company_row["id"])
            if tail and tail.group(1) == prefix:
                top = max(top, int(tail.group(2)))
        ctx.series[prefix] = top
    ctx.series[prefix] += 1
    while (item.company, prefix, ctx.series[prefix]) in ctx.claimed_numbers:
        ctx.series[prefix] += 1
    ctx.claimed_numbers.add((item.company, prefix, ctx.series[prefix]))
    return f"{prefix}{ctx.series[prefix]:05d}"


def _finish(ctx: _Context, draft: _Draft, contract: Mapping[str, Any]) -> BillingResult:
    item = draft.item
    code = contract["tax"]
    if code not in ctx.rates or ctx.rates[code]["country"] != ctx.country[item.company]:
        raise _Blocked(f"tax code {code} is not an output code of company {item.company}'s country")
    customer = ctx.data.get("customers", item.customer)
    net = sum(line.amount for line in draft.lines)
    key = (item.company, item.customer)
    advance_bp = contract.get("advance_bp", 0)
    try:
        amounts = compute.invoice_amounts(
            net=net, tax_rate_bp=ctx.rates[code]["rate"], retention_bp=contract.get("retention_bp", 0),
            mx_levy=bool(contract.get("mx5mill")), advance_bp=advance_bp,
            advance_available=ctx.advance_available(*key, draft.date) if advance_bp else 0)
    except ValueError as error:
        raise _Blocked(f"amounts: {error}") from None
    deductions = tuple(Deduction(c, a, acc) for c, a, acc in
                       (("MX5MILL", amounts.levy, "63100000"), ("ADV_AMORT", amounts.advance, "43800000")) if a)
    due = (date.fromisoformat(draft.date) + timedelta(days=contract["terms_days"])).isoformat()
    dir3 = customer.get("dir3")
    if customer["kind"] == "public" and customer["country"] == "ES" and (
            not dir3 or any(not dir3.get(k) for k in ("oficina_contable", "organo_gestor", "unidad_tramitadora"))):
        raise _Blocked("public Spanish customer is missing required DIR3 codes")
    face = Face(**{k: dir3[k] for k in ("oficina_contable", "organo_gestor", "unidad_tramitadora")}) \
        if customer["kind"] == "public" and customer["country"] == "ES" and dir3 else None
    invoice = Invoice(_next_number(ctx, item, draft.date), draft.date, due, code, amounts.net, amounts.tax,
                      amounts.gross, amounts.retention, deductions, amounts.payable,
                      company_local_currency(item.company), draft.lines, face)
    entry = build_entry(invoice, company=item.company, customer=item.customer, customer_name=customer["name"])
    context = ValidationContext(companies=ctx.country, partners={r["id"] for r in ctx.data.table("customers")},
                                cost_centers={r["id"]: r for r in ctx.data.table("cost_centers")},
                                wbs={w["id"] for p in ctx.data.table("projects") for w in p["wbs"]})
    problems = validate_entry(entry, context)
    if problems:
        raise _Blocked(*problems)
    if ctx.strict:  # consume only after the invoice and journal entry validate
        ctx.advance_used[key] = ctx.advance_used.get(key, 0) + amounts.advance
    entry["provenance"] = {"event_id": item.id, "stage": "ar_billing"}
    return BillingResult(item, Decision.INVOICE, invoice, entry, draft.evidence, tuple(draft.notes))


def build_ar_billing(data: PhaseData, items: Sequence[BillingItem], facts: Mapping[str, BillingFacts],
                     *, strict_duplicates: bool = True,
                     invoice_numbers: Mapping[str, str] | None = None) -> BillingRun:
    """Resolve every item that has facts. ``strict_duplicates=False`` replays past months
    (invoices on or after the item's date are ignored instead of rejected).
    Optional explicit numbers preserve an upstream task-order allocation; each
    number is checked against the ERP-derived series and existing/current IDs.
    Without overrides the historical max-plus-one convention is unchanged.
    """
    if len({i.id for i in items}) != len(items):
        raise ValueError("billing item IDs must be unique")
    if invoice_numbers is not None:
        if (not isinstance(invoice_numbers, Mapping) or not set(invoice_numbers) <= {i.id for i in items}
                or any(not isinstance(number, str) or not number.strip() for number in invoice_numbers.values())):
            raise ValueError("invoice numbers require known billing item IDs and nonempty strings")
        invoice_numbers = dict(invoice_numbers)
    ctx = _Context(data, strict_duplicates, invoice_numbers)
    drafts: list[tuple[BillingItem, _Draft | _Blocked, Mapping[str, Any] | None]] = []
    coverage: set[tuple[str, str, BillingType, str]] = set()
    # The decree is checked before monthly service, independent of task order.
    for item in sorted(items, key=lambda i: i.type is not BillingType.PRICE_REVISION):
        try:
            contract = ctx.contract(item)
            expected, decide = _DECIDERS[item.type]
            found = facts.get(item.id)
            if not isinstance(found, expected):
                raise _Blocked(f"no {expected.__name__} supplied for this {item.type.value} item")
            covered = (item.company, item.contract, item.type, item.month)
            if ctx.strict and covered in coverage:
                raise _Blocked("another billing item already covers this contract, type and period")
            draft = decide(ctx, item, contract, found)  # type: ignore[operator]
            drafts.append((item, draft, contract))
            if draft.decision is Decision.INVOICE:
                coverage.add(covered)
                if isinstance(found, RevisionFacts):
                    ctx.revised_fees[(item.company, item.contract, item.month)] = found.new_fee
        except _Blocked as blocked:
            drafts.append((item, blocked, None))
        except (KeyError, ValueError, TypeError) as error:
            drafts.append((item, _Blocked(f"inputs: {error}"), None))
    done: dict[str, BillingResult | Unresolved] = {}
    ordered = sorted((d for d in drafts if isinstance(d[1], _Draft) and d[1].decision is Decision.INVOICE),
                     key=lambda d: (d[1].date, d[0].contract, d[0].id))  # type: ignore[union-attr]
    for item, draft, terms in ordered:
        try:
            done[item.id] = _finish(ctx, draft, terms)  # type: ignore[arg-type]
        except _Blocked as blocked:
            done[item.id] = Unresolved(item, blocked.reasons)
        except (KeyError, ValueError, TypeError) as error:
            done[item.id] = Unresolved(item, (f"inputs: {error}",))
    for item, outcome, _ in drafts:
        if isinstance(outcome, _Blocked):
            done[item.id] = Unresolved(item, outcome.reasons)
        elif outcome.decision is Decision.SKIP_PENDING_APPROVAL:
            done[item.id] = BillingResult(item, Decision.SKIP_PENDING_APPROVAL, evidence=outcome.evidence,
                                          diagnostics=tuple(outcome.notes))
    results = tuple(done[i.id] for i in items if isinstance(done[i.id], BillingResult))
    unresolved = tuple(done[i.id] for i in items if isinstance(done[i.id], Unresolved))
    pending = {item.id: PendingWip(item, sum(x.amount for x in outcome.lines), outcome.lines, outcome.evidence)
               for item, outcome, _ in drafts
               if isinstance(outcome, _Draft) and outcome.decision is Decision.SKIP_PENDING_APPROVAL}
    return BillingRun(results, unresolved, tuple(pending[i.id] for i in items if i.id in pending))  # type: ignore[arg-type]
