"""M5 orchestration: immutable observations, append-only producer-owned projections.

Only the caller/evaluator may decide whether external interfaces are integrated.
This module never reads an expected answer, creates AP/bank decisions, or silently
replaces a missing delivery with an empty one.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Callable

from kalmora.data import PhaseData
from kalmora.ledger import Ledger, iter_entries
from kalmora.validation import validate_entry
from .context import Context, delivery_lines, financial_fingerprint
from .corrections import duplicate_postings, wrong_partners
from .interest import loan_interest
from .invoices import invoices_in_transit
from .model import Diagnostic, OwnedEntry, Result, Upstream, digest
from .pooling import pooling_not_booked
from .positions import snapshot

STAGE = "intercompany"


def _normalized(entry: dict, owner: tuple[str, str]) -> dict:
    result = next(iter_entries([entry]))
    result["provenance"] = {"event_id": owner[0], "stage": owner[1]}
    return result


class _ProjectionWriter:
    """Index only producer-owned additions, never clone the entire book per event."""
    def __init__(self, projection: Ledger, recorded: tuple[dict, ...], validation: dict):
        self.projection, self.validation = projection, validation
        self.owners, self.extra = {}, {}
        originals = {e["id"]: e for e in recorded}
        seen = set()
        for entry in projection.iter_entries():
            identity = entry["id"]
            seen.add(identity)
            if identity in originals:
                if entry != originals[identity]:
                    raise ValueError(f"Prior projection changed or removed recorded ERP entry {identity}")
            else:
                if not entry.get("provenance"):
                    raise ValueError(f"Prior projection entry {identity} has no producer ownership")
                errors = validate_entry(entry, validation)
                if errors:
                    raise ValueError(f"Invalid prior projection entry {identity}: {'; '.join(errors)}")
                self.extra[identity] = entry
            if entry.get("provenance"):
                p = entry["provenance"]
                self.owners[p["event_id"], p["stage"]] = entry
        missing = originals.keys() - seen
        if missing:
            raise ValueError(f"Prior projection changed or removed recorded ERP entry {min(missing)}")

    def add(self, owned: OwnedEntry) -> bool:
        owner = (owned.event_id, owned.stage)
        normalized = _normalized(owned.entry, owner)
        existing = self.owners.get(owner)
        if existing is not None:
            if existing != normalized:
                raise ValueError(f"Conflicting content for producer ownership {owner}")
            return False
        errors = validate_entry(owned.entry, self.validation)
        if errors:
            raise ValueError("; ".join(errors))
        self.projection.add_entry(owned.entry, event_id=owned.event_id, stage=owned.stage)
        self.owners[owner] = normalized
        self.extra[normalized["id"]] = normalized
        return True

    def view(self, originals: tuple[dict, ...]) -> tuple[dict, ...]:
        # Entries are treated read-only by rules. Ledger remains the write authority.
        return originals + tuple(self.extra.values())


def _consume_external_corrections(ctx: Context, writer: _ProjectionWriter,
                                  batch: list, diagnostics: list[Diagnostic]) -> None:
    """Respect complete AP/bank corrections with different producer ownership.

    The recorded incident remains a finding. A full financial match, including
    company, invoice reference, tax and cost objects, proves that its correction
    is already projected. Each external journal can cover only one incident;
    excess corrections are a conflict, never evidence of successful resolution.
    Own replays still go through the exact ownership/content check in add().
    """
    def key(entry):
        return (entry["company"], entry.get("reference"), financial_fingerprint(entry))

    def shape(entry):
        dimensions = ("account", "partner", "cost_center", "wbs", "assignment", "tax_code", "currency")
        lines = [tuple(str(l.get(k)) for k in dimensions) +
                 (str((l["debit"] > l["credit"]) - (l["debit"] < l["credit"])),)
                 for l in entry["lines"]]
        return (entry["company"], entry.get("reference"), tuple(sorted(lines)))

    groups = defaultdict(list)
    for finding in batch:
        if finding.proposed is not None and finding.cause in {"DUPLICATE_POSTING", "WRONG_TRADING_PARTNER"}:
            groups[key(finding.proposed)].append(finding)
    external = defaultdict(list)
    partial = defaultdict(list)
    for entry in writer.extra.values():
        if entry["provenance"]["stage"] != STAGE:
            external[key(entry)].append(entry)
            if key(entry) not in groups:
                partial[shape(entry)].append(entry)
    for identity, findings in groups.items():
        matches = sorted(external.get(identity, ()), key=lambda e: e["id"])
        conflicts = partial.get(shape(findings[0].proposed), ())
        pending = sorted((f for f in findings if (f.event_id, STAGE) not in writer.owners),
                         key=lambda f: f.event_id)
        if conflicts or len(matches) > len(pending):
            for finding in findings:
                finding.proposed = None
                finding.status = "blocked"
                diagnostics.append(Diagnostic("EXISTING_IC_CORRECTION_CONFLICT",
                    f"{identity[1]}: {len(matches)} exact external corrections for {len(pending)} uncorrected incidents; "
                    f"{len(conflicts)} corrections have matching dimensions/directions but different amounts",
                    (92, 94), finding.event_id, tuple(ctx.evidence(e) for e in [*matches, *conflicts])))
            continue
        for finding, correction in zip(pending, matches):
            finding.proposed = None
            finding.status = "already_corrected_externally"
            finding.details["external_correction"] = {"entry_id": correction["id"], **correction["provenance"]}
            finding.evidence += (ctx.evidence(correction),)


def reconcile(data: PhaseData, *, recorded: Ledger, upstream: Upstream,
              contract_validator: Callable[[dict], list[str]] | None = None,
              metadata: dict | None = None) -> Result:
    """Run M5 without mutating the caller's ledgers or upstream entries.

    `contract_validator`, when available from #32, receives each organizer-shaped
    record. It returns errors; none are suppressed. Accounting always uses the
    existing shared validator and Ledger. No shared scorer is implemented here.
    """
    original_entries = tuple(recorded.iter_entries())
    original_hash = digest(original_entries)
    upstream_hash = digest(tuple(upstream.prior_projection.iter_entries())) if upstream.prior_projection else None
    ctx = Context(data, recorded, upstream, original_entries)
    if upstream.ap_coverage is not None:
        if upstream.ap_coverage.month != ctx.month:
            raise ValueError("AP receipt coverage belongs to a different phase month")
        for receipt in upstream.ap_coverage.receipts:
            if receipt.company not in ctx.directory.companies or (receipt.issuer is not None and not ctx.pair(receipt.company, receipt.issuer)):
                raise ValueError("AP receipt must identify a configured company pair")
    projection = upstream.prior_projection.project() if upstream.prior_projection is not None else recorded.project()
    writer = _ProjectionWriter(projection, original_entries, ctx.validation)
    diagnostics: list[Diagnostic] = []
    if upstream.ap_entries is None:
        diagnostics.append(Diagnostic("AP_ENTRY_DELIVERY_PENDING", "#55 AP journal delivery is absent", (55, 88)))
    if upstream.banks is None or not upstream.banks.complete:
        diagnostics.append(Diagnostic("BANK_DELIVERY_PENDING", "#75 complete bank projection delivery is absent", (75, 88)))
    deliveries = [("AP", owned) for owned in (upstream.ap_entries or ())]
    if upstream.banks is not None:
        deliveries.extend(("bank", owned) for owned in upstream.banks.entries)
    for producer, owned in deliveries:
        if owned.stage == STAGE or owned.event_id.startswith("ic:"):
            raise ValueError(f"{producer} delivery cannot impersonate M5 ownership")
        if owned.entry.get("posting_date", "") > ctx.last.isoformat():
            raise ValueError(f"{producer} delivery is outside the phase")
        writer.add(owned)
    before_entries = writer.view(original_entries)
    options = {"accounts": ctx.tasks["accounts"], "pairs": ctx.tasks["pairs"],
               "as_of": ctx.last.isoformat(), "valuation_ids": upstream.valuation_entry_ids}
    def positions(book):
        return snapshot(book, ctx.directory, ctx.rates, **options)
    original_positions = positions(recorded)
    before_positions = positions(projection) if writer.extra else deepcopy(original_positions)
    # Evidence for externally projected entries refers to its producer, not ERP.
    ctx.external_evidence = {o.entry["id"]: o.evidence for _, o in deliveries}
    findings = []

    def apply_findings(batch):
        _consume_external_corrections(ctx, writer, batch, diagnostics)
        for finding in batch:
            if finding.proposed is None:
                continue
            proposal = finding.proposed
            errors = validate_entry(proposal, ctx.validation)
            if errors:
                finding.status = "blocked"
                diagnostics.append(Diagnostic("IC_ADJUSTMENT_INVALID", "; ".join(errors), (94,),
                                              finding.event_id, finding.evidence))
                continue
            owned = OwnedEntry(finding.event_id, STAGE, proposal, finding.evidence[0])
            added = writer.add(owned)
            finding.status = "adjustment_proposed" if added else "already_applied"
            finding.emitted_adjustment = delivery_lines(proposal) if added else []
        findings.extend(batch)

    for rule in (duplicate_postings, wrong_partners):
        found, issues = rule(ctx)
        apply_findings(found)
        diagnostics.extend(issues)
    found, issues = loan_interest(ctx, writer.view(original_entries))
    apply_findings(found)
    diagnostics.extend(issues)
    # A wrong-party correction can establish receipt; do not also accrue its
    # invoice. This is a corrected projection, while rule evidence stays original.
    found, issues = invoices_in_transit(ctx, writer.view(original_entries))
    apply_findings(found)
    diagnostics.extend(issues)
    found, issues = pooling_not_booked(ctx, before_entries)
    apply_findings(found)
    diagnostics.extend(issues)
    if len({f.event_id for f in findings}) != len(findings):
        raise ValueError("Rules proposed duplicate economic event identities")
    findings.sort(key=lambda f: (f.pair, f.cause, f.event_id))
    if contract_validator is not None:
        for finding in findings:
            errors = contract_validator(deepcopy(finding.record()))
            if errors:
                raise ValueError(f"Output contract rejected {finding.event_id}: {'; '.join(errors)}")
    result = Result(findings, diagnostics, original_positions,
                    before_positions, positions(projection), projection,
                    {**(metadata or {}), "month": ctx.month, "recorded_entries": len(original_entries),
                     "recorded_sha256": original_hash, "before_ic_sha256": digest(before_entries),
                     "before_hash_order": "recorded order followed by producer additions",
                     "corrected_sha256": digest(tuple(projection.iter_entries())),
                     "source_erp_preserved": True,
                     "prior_projection_supplied": upstream.prior_projection is not None,
                     "ap_delivery_supplied": upstream.ap_entries is not None,
                     "ap_coverage_complete": upstream.ap_coverage.complete if upstream.ap_coverage else None,
                     "bank_delivery_complete": upstream.banks.complete if upstream.banks else None,
                     "shared_contract_validator_supplied": contract_validator is not None,
                     "dependency_provenance": deepcopy(dict(upstream.provenance)),
                     "integration_mode": "simulated" if upstream.provenance.get("kind") == "golden_fixture" else "producer_deliveries" if upstream.provenance else "undeclared",
                     "real_flow_verified": False,
                     "real_flow_gate": "#159 requires independently verified real AP and bank outputs",
                     "output_contract": "FORMATO_ENTREGA.md / IC",
                     "emission_semantics": "incremental over before_ic; original incidents retained on replay"})
    # Positive coverage comes from a completed execution of all rules over the
    # configured pairs/accounts, including pairs producing no exception rows.
    result.metadata["task_coverage"] = {
        "month": ctx.month, "as_of": ctx.last.isoformat(),
        "pairs": [list(p) for p in sorted(ctx.pairs)],
        "accounts": sorted(ctx.tasks["accounts"]),
        "rules": ["duplicate_postings", "wrong_partners", "loan_interest",
                  "invoices_in_transit", "pooling_not_booked"],
        "complete": result.complete,
        "positions_sha256": digest({"recorded": result.original, "before_ic": result.before,
                                    "corrected": result.corrected})}
    if digest(tuple(recorded.iter_entries())) != original_hash:
        raise AssertionError("M5 mutated the original ERP ledger")
    if upstream.prior_projection and digest(tuple(upstream.prior_projection.iter_entries())) != upstream_hash:
        raise AssertionError("M5 mutated the caller's prior projection")
    return result
