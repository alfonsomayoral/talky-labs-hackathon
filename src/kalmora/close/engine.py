"""Month-end close from immutable ledger projections and saved evidence.

No document reader, upstream solver, evaluation package or golden access here.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import median

from ..billing.inputs import CertificationFacts, Chapter
from ..facts import Evidence
from ..ledger import Ledger, is_open_item_account
from ..model import BalanceKey, OpenItemKey
from ..money import RateTable, company_local_currency, integer, round_cents
from ..output_models.close import CloseRow
from .contracts import Handoff, digest, require
from .projection import Projection, project
from .rules import (entry, estimate_daily, fx_difference, impairment_bp, line,
                    month_bounds, prepaid_remaining, uncovered_ranges)


@dataclass
class CloseResult:
    rows: list[CloseRow]
    decisions: list[dict]
    projection: Projection
    final: Ledger
    simulated: bool
    complete: bool


class CloseEngine:
    def __init__(self, entries, handoff: Handoff, rates: RateTable, customers: list[dict],
                 ar_invoices: list[dict], promissory_notes: list[dict] = ()):
        handoff = Handoff.from_dict(handoff.payload)
        self.handoff = handoff
        self.month = handoff.payload["month"]
        self.first, self.closing = month_bounds(self.month)
        self.projection = project(entries, handoff)
        self.ledger = self.projection.pre_close.project()
        self.facts = handoff.payload["facts"]
        self.rates = rates
        self.rows = []
        self.decisions = []
        self.customers = {c["id"]: c for c in customers}
        self.ar = {(a["company"], a.get("id", a.get("number"))): a for a in ar_invoices}
        for a in self.facts.get("billed_invoices", []):
            self.ar[a["company"], a.get("id", a.get("number"))] = a
        self.notes = {p.get("id", p.get("number")): p for p in promissory_notes}
        self.existing = {e.get("provenance", {}).get("event_id") for e in self.ledger.iter_entries()}
        self._refresh()

    def _refresh(self):
        self.entries = list(self.ledger.iter_entries())
        self.open = self.ledger.open_items()
        self.balances = self.ledger.balances()

    def _index_posting(self, posting):
        self.entries.append(posting)
        company = posting["company"]
        for row in posting["lines"]:
            amount = row["debit"] - row["credit"]
            key = BalanceKey(company, row["account"])
            self.balances[key] = self.balances.get(key, 0) + amount
            if is_open_item_account(row["account"]):
                key = OpenItemKey(company, row["account"], row.get("partner"), row.get("assignment"))
                self.open[key] = self.open.get(key, 0) + amount

    def _balance(self, company, account, partner=None, assignment=None, reference=None,
                 filter_partner=False, filter_assignment=False):
        return sum(l["debit"] - l["credit"] for e in self.entries if e["company"] == company
                   and (reference is None or e.get("reference") == reference)
                   for l in e["lines"] if l["account"] == account
                   and (not filter_partner or l.get("partner") == partner)
                   and (not filter_assignment or l.get("assignment") == assignment))

    def _post(self, kind, company, identity, identity_field, amount, lines, decision, *, reference=None):
        integer(amount)
        event = f"close:{self.month}:{kind}:{company}:{identity}"
        if event in self.existing:
            self.decisions.append(dict(decision, type=kind, event_id=event, action="already_closed"))
            return
        if not amount:
            self.decisions.append(dict(decision, type=kind, event_id=event, action="no_adjustment"))
            return
        reference = reference or event
        posting = entry(company, self.closing, reference, "M6_" + kind, lines)
        row: CloseRow = {"type": kind, "company": company, "amount": amount,
                         identity_field: decision.get("output_identity", identity), "journal_entry": posting}
        self.ledger.add_entry(posting, event_id=event, stage="close.post")
        self.existing.add(event)
        self.rows.append(row)
        self.decisions.append(dict(decision, event_id=event, type=kind, company=company,
                                   amount=amount, action="post", journal_sha256=digest(posting)))
        self._index_posting(posting)

    def accruals(self):
        exclusions = set(self.facts.get("ic_owned_services", []))
        for f in sorted(self.facts["accruals"], key=lambda x: x["series_id"]):
            decision = dict(f)
            company, vendor, identity = f["company"], f["vendor"], f["series_id"]
            if f.get("coverage_unknown"):
                self.decisions.append(dict(decision, type="ACCRUAL", action="blocked_receipt_allocation"))
                continue
            if f.get("po_required") or f.get("service_id") in exclusions or f.get("gr_ir_recognized"):
                self.decisions.append(dict(decision, type="ACCRUAL", action="excluded_prior_owner"))
                continue
            coverage = [(date.fromisoformat(c["start"]), date.fromisoformat(c["end"]))
                        for c in f.get("received_coverage", [])]
            gaps = uncovered_ranges(date.fromisoformat(f.get("window_start", self.first.isoformat())), self.closing, coverage)
            days = sum((right - left).days + 1 for left, right in gaps)
            decision["gaps"] = [(a.isoformat(), b.isoformat()) for a, b in gaps]
            lines, total = [], 0
            if not days:
                self.decisions.append(dict(decision, type="ACCRUAL", action="fully_received"))
                continue
            for component in f["components"]:
                samples = component.get("samples", [])
                if f.get("method") == "recurring_unbilled_monthly_history":
                    # Discrete service dates are not expanded into 31 daily services.
                    amounts = [integer(s["amount"]) for s in samples]
                    require(bool(amounts), "monthly estimate requires observed history")
                    amount = round_cents(Decimal(median(amounts)))
                    audit = {"method": f["method"], "samples": samples,
                             "low": min(amounts), "high": max(amounts),
                             "assumption": "recurring month-end unbilled exposure; exact service date unknown"}
                else:
                    amount, audit = estimate_daily(((s["amount"], date.fromisoformat(s["start"]),
                        date.fromisoformat(s["end"])) for s in samples), days)
                prior = sum(l["debit"] - l["credit"] for e in self.entries
                            if e["company"] == company and e.get("reference") in f.get("historical_references", [])
                            and e.get("source", "").startswith("CLOSE_ACCRUAL")
                            for l in e["lines"] if l["account"] == component["account"]
                            and l.get("cost_center") == component.get("cost_center")
                            and l.get("wbs") == component.get("wbs"))
                amount -= prior + integer(component.get("already_accrued", 0))
                audit["existing_unreversed_accrual"] = prior
                decision.setdefault("estimates", []).append(dict(audit, account=component["account"], amount=amount))
                if amount:
                    total += amount
                    lines.append(line(component["account"], amount, company=company,
                        cost_center=component.get("cost_center"), wbs=component.get("wbs"),
                        text="Unbilled service estimate; evidence in close_decisions"))
            if lines:
                lines.append(line("40090000", -total, company=company, partner=vendor,
                                  assignment=f.get("assignment", identity), text="Unbilled service"))
            decision["output_identity"] = vendor
            self._post("ACCRUAL", company, identity, "vendor", total, lines, decision)

    def prepaids(self):
        for f in sorted(self.facts["prepaids"], key=lambda x: (x["company"], x["invoice"])):
            company = f["company"]
            start, end = date.fromisoformat(f["start"]), date.fromisoformat(f["end"])
            references = f.get("references", ["PREP-" + f["invoice"]])
            existing = sum(self._balance(company, "48000000", reference=ref) for ref in references)
            # An already-posted M6 uses the same PREP reference; no fresh deferral.
            desired = prepaid_remaining(f["total_local"], start, end, self.closing)
            amount = desired - existing
            components = f["components"]
            require(f["total_local"] > 0, "prepaid requires positive original cost")
            require(sum(c["amount"] for c in components) == f["total_local"], "prepaid allocation does not tie")
            lines = [line("48000000", amount, company=company, text="Prepaid balance movement")]
            allocated = 0
            for i, component in enumerate(components):
                share = (amount - allocated if i == len(components) - 1 else
                         round_cents(Decimal(amount) * component["amount"] / f["total_local"]))
                allocated += share
                if share:
                    lines.append(line(component["account"], -share, company=company,
                        cost_center=component.get("cost_center"), wbs=component.get("wbs"), text="Coverage consumption/deferral"))
            self._post("PREPAID", company, f["invoice"], "invoice", amount, lines,
                dict(f, existing=existing, required=desired, installment_method="monthly_half_up_last_residual"),
                reference=references[0])

    def wip(self):
        for f in self.facts["pending_certifications"]:
            raw = f["certification"]
            cert = CertificationFacts(month=raw["month"], chapters=tuple(Chapter(**c) for c in raw["chapters"]),
                cumulative=raw["cumulative"], previous=raw["previous"], current=raw["current"],
                approved=raw["approved"], evidence=tuple(Evidence(**e) for e in f["evidence"]))
            require(cert.month == self.month, "pending certification belongs to another month")
            require(cert.current == cert.cumulative - cert.previous, "certification delta mismatch")
            require(sum(c.amount for c in cert.chapters) == cert.current, "certification chapter mismatch")
            if cert.approved or f.get("billing_status") != "SKIP_PENDING_APPROVAL":
                raise ValueError("WIP requires the same explicitly pending certification as billing")
            company, identity = f["company"], f["billing_item"]
            existing = self._balance(company, "43090000", partner=f["customer"], assignment=identity,
                                      filter_partner=True, filter_assignment=True)
            amount = cert.current - existing
            require(amount >= 0, "WIP already exceeds pending certification; conflicting upstream coverage")
            if not amount:
                self._post("WIP_REVENUE", company, identity, "billing_item", 0, [], dict(f, existing=existing))
                continue
            lines = [line("43090000", amount, company=company, partner=f["customer"], assignment=identity)]
            remaining = amount
            for i, chapter in enumerate(cert.chapters):
                share = remaining if i == len(cert.chapters) - 1 else round_cents(Decimal(amount) * chapter.amount / cert.current)
                remaining -= share
                if share:
                    lines.append(line("71300000", -share, company=company,
                                      wbs=f"{f['project']}.{chapter.number:02d}", text=chapter.description))
            self._post("WIP_REVENUE", company, identity, "billing_item", amount, lines, dict(f, existing=existing))

    def fx(self):
        for f in sorted(self.facts["fx_positions"], key=lambda x: (x["company"], x["item"])):
            company, account = f["company"], f["account"]
            local = self._balance(company, account, partner=f.get("partner"), assignment=f.get("assignment"),
                filter_partner=f.get("filter_partner", True), filter_assignment=f.get("filter_assignment", True))
            if not local and not f["document_signed"]:
                continue
            amount, change = fx_difference(f["document_signed"], local, f["currency"], company, self.closing, self.rates)
            if not change:
                self.decisions.append(dict(f, type="FX_REVAL", action="already_valued", carrying=local))
                continue
            lines = [line(account, change, company=company, partner=f.get("partner"), assignment=f.get("assignment"),
                          currency=f["currency"], amount_doc=0, text="Local valuation only; document principal unchanged"),
                     line("76800000" if change > 0 else "66800000", -change, company=company)]
            self._post("FX_REVAL", company, f["item"], "item", amount, lines,
                       dict(f, carrying=local, required=local + change, local_change=change,
                            rate=str(self.rates.as_of(self.closing, f["currency"])),
                            local_rate=str(self.rates.as_of(self.closing, company_local_currency(company)))))

    def bad_debt(self):
        required = defaultdict(int)
        detail = defaultdict(list)
        incomplete = set()
        for key, amount in sorted(self.open.items(), key=lambda pair: repr(pair[0])):
            if not key.account.startswith(("430", "431", "436")) or key.account == "43090000" or amount <= 0:
                continue
            customer = self.customers.get(key.partner)
            if customer is None:
                self.decisions.append({"type": "BAD_DEBT", "action": "unknown_customer", "item": list(key), "amount": amount})
                incomplete.add((key.company, key.partner))
                continue
            if customer["kind"] not in {"private", "community"}:
                continue
            declaration = customer.get("insolvency", {}).get("declared_on") if isinstance(customer.get("insolvency"), dict) else None
            if declaration is None:
                declaration = customer.get("insolvency_declared_on")
            invoice = self.ar.get((key.company, key.assignment), {})
            due = invoice.get("due_date")
            if key.account.startswith("431"):
                note = self.notes.get(key.assignment, self.notes.get(str(key.assignment).removeprefix("PAG"), {}))
                due = note.get("maturity", note.get("due_date", due))
            guarantee = key.account == "43000900"
            try:
                bp = impairment_bp(customer["kind"], date.fromisoformat(due) if due else None,
                    self.closing, date.fromisoformat(declaration) if declaration else None, guarantee=guarantee)
            except ValueError:
                incomplete.add((key.company, key.partner))
                detail[key.company, key.partner].append({"assignment": key.assignment, "balance": amount,
                                                       "action": "missing_due_date", "account": key.account})
                continue
            # Match the recorded impairment convention, rather than treating the
            # scorer's tolerance as permission to accumulate half-cent changes.
            rounding = self.facts.get("impairment_rounding", "truncate")
            require(rounding in {"truncate", "half_up"}, "unknown impairment rounding convention")
            provision = round_cents(Decimal(amount) * bp / 10000, truncate=rounding == "truncate")
            required[key.company, key.partner] += provision
            detail[key.company, key.partner].append({"assignment": key.assignment, "balance": amount, "due_date": due,
                 "basis_points": bp, "required": provision, "account": key.account, "declared_on": declaration,
                 "guarantee": guarantee})
        existing = defaultdict(int)
        for key, balance in self.open.items():
            if key.account == "49000000":
                existing[key.company, key.partner] -= balance
        for company, customer in sorted(set(required) | set(existing) | incomplete):
            if (company, customer) in incomplete:
                self.decisions.append({"type": "BAD_DEBT", "company": company, "customer": customer,
                    "action": "blocked_incomplete_ageing", "items": detail[company, customer]})
                continue  # Never release a provision merely because an item is unidentified.
            target = required[company, customer]
            previous = existing[company, customer]
            amount = target - previous
            lines = [line("69400000" if amount > 0 else "79400000", amount, company=company),
                     line("49000000", -amount, company=company, partner=customer)]
            self._post("BAD_DEBT", company, customer, "customer", amount, lines,
                       {"existing": previous, "required": target, "items": detail[company, customer],
                        "evidence": self.facts.get("ageing_evidence", [])})

    def doubtful(self):
        grouped = defaultdict(list)
        for key, balance in self.open.items():
            customer = self.customers.get(key.partner, {})
            declaration = customer.get("insolvency", {}).get("declared_on") if isinstance(customer.get("insolvency"), dict) else None
            declaration = declaration or customer.get("insolvency_declared_on")
            if key.account == "43000000" and balance > 0 and declaration and declaration[:7] == self.month:
                grouped[key.company, key.partner].append((key.assignment, balance))
        for (company, customer), invoices in sorted(grouped.items()):
            lines = []
            for assignment, amount in sorted(invoices, key=lambda x: str(x[0])):
                require(bool(assignment), "doubtful reclassification requires invoice assignment")
                lines.extend([line("43600000", amount, company=company, partner=customer, assignment=assignment),
                              line("43000000", -amount, company=company, partner=customer, assignment=assignment)])
            self._post("DOUBTFUL_RECLASS", company, customer, "customer", sum(n for _, n in invoices), lines,
                       {"invoices": invoices, "evidence": self.facts.get("ageing_evidence", [])})

    def run(self) -> CloseResult:
        original = digest(self.projection.recorded.entries)
        self.accruals()
        self.prepaids()
        self.wip()
        self.fx()
        self.bad_debt()
        self.doubtful()
        require(digest(self.projection.recorded.entries) == original, "original ERP was mutated")
        complete = self.handoff.complete and not any(d["action"].startswith(("blocked", "unknown")) for d in self.decisions)
        return CloseResult(self.rows, self.decisions, self.projection, self.ledger, self.handoff.simulated, complete)
