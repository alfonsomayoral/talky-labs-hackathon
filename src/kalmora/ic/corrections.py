"""#92: evidence-backed partner reclassification and full duplicate reversal."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

from kalmora.facts import Evidence
from .context import Context, financial_fingerprint, reverse_line
from .model import Diagnostic, Finding, event_key
from .positions import FAMILIES, is_valuation


def duplicate_postings(ctx: Context) -> tuple[list[Finding], list[Diagnostic]]:
    groups = defaultdict(list)
    diagnostics, findings = [], []
    for entry in ctx.entries:
        # Local FX revaluation/reversal is not a repeated invoice.
        if is_valuation(entry, ctx.upstream.valuation_entry_ids):
            continue
        # Invoice transactions, not payments, monthly accruals or equal-value rents.
        controls = [l for l in entry["lines"] if l["account"] in {"40300000", "43300000"}
                    and ctx.directory.resolve(l.get("partner"))]
        if not controls or not any(l["account"].startswith(("6", "7")) for l in entry["lines"]):
            continue
        reference = entry.get("reference")
        if not reference:
            continue
        counterparties = tuple(sorted({ctx.directory.resolve(l.get("partner")) for l in controls}))
        key = (entry["company"], counterparties, reference, entry.get("currency"))
        groups[key].append(entry)
    for (company, others, ref, _), entries in sorted(groups.items()):
        if len(entries) < 2:
            continue
        entries.sort(key=lambda e: (e["posting_date"], e["id"]))
        original = entries[0]
        for duplicate in entries[1:]:
            if not ctx.current(duplicate):
                continue
            if financial_fingerprint(original) != financial_fingerprint(duplicate):
                diagnostics.append(Diagnostic("DUPLICATE_REFERENCE_CONFLICT",
                    f"Same reference {ref} has different full postings; no automatic reversal", (92,),
                    evidence=(ctx.evidence(original), ctx.evidence(duplicate))))
                continue
            if len(others) != 1 or not ctx.pair(company, others[0]):
                diagnostics.append(Diagnostic("DUPLICATE_COUNTERPARTY_AMBIGUOUS", ref, (92,)))
                continue
            other = others[0]
            event = event_key("DUPLICATE_POSTING", company, original["id"], duplicate["id"])
            amount = abs(sum(l["debit"] - l["credit"] for l in duplicate["lines"]
                             if l["account"] in {"40300000", "43300000"}))
            adjustment = ctx.new_entry(event, company, [reverse_line(l) for l in duplicate["lines"]], reference=ref)
            findings.append(Finding(event, ctx.pair(company, other), "DUPLICATE_POSTING", amount,
                company, ctx.directory.currency(company), adjustment,
                (ctx.evidence(original), ctx.evidence(duplicate), Evidence("POLITICAS_CONTABLES.md", "§6")),
                {"original_entry": original["id"], "duplicate_entry": duplicate["id"],
                 "reversed_lines": len(duplicate["lines"]), "adjustment_currency": ctx.directory.currency(company)}))
    return findings, diagnostics


def wrong_partners(ctx: Context) -> tuple[list[Finding], list[Diagnostic]]:
    groups = defaultdict(list)
    diagnostics, findings = [], []
    for entry in ctx.entries:
        if not ctx.current(entry) or not entry.get("reference") or is_valuation(entry, ctx.upstream.valuation_entry_ids):
            continue
        for line in entry["lines"]:
            if line["account"] in {"55200000", "55210000", "55220000", "24230000", "16330000", "40300000", "43300000"}:
                if ctx.directory.resolve(line.get("partner")):
                    groups[FAMILIES[line["account"]], entry["reference"]].append((entry, line))
    done = set()
    for (_, reference), legs in sorted(groups.items()):
        for entry, line in legs:
            # A peer points unambiguously at this company and carries the opposite
            # value. Its *actual* company, not an ID prefix, establishes the party.
            candidates = [(e, l) for e, l in legs if e["company"] != entry["company"]
                          and ctx.directory.resolve(l.get("partner")) == entry["company"]
                          and _compatible_accounts(l["account"], line["account"])
                          and ctx.eur(e, l) == -ctx.eur(entry, line)]
            correct = [x for x in candidates if x[0]["company"] == ctx.directory.resolve(line.get("partner"))]
            if correct or not candidates:
                continue
            if len(candidates) != 1:
                diagnostics.append(Diagnostic("PARTNER_MIRROR_AMBIGUOUS", reference, (92,), evidence=(ctx.evidence(entry, line),)))
                continue
            peer, mirror = candidates[0]
            expected = peer["company"]
            pair = ctx.pair(entry["company"], expected)
            if not pair or line.get("book_line") in done:
                continue
            done.add(line.get("book_line"))
            event = event_key("WRONG_TRADING_PARTNER", entry["company"], line.get("book_line"), expected)
            corrected = deepcopy(line)
            expected_partner = expected
            if line["account"] == "40300000":
                vendor = ctx.directory.vendor(expected, entry["company"])
                if vendor is None:
                    diagnostics.append(Diagnostic("PARTNER_VENDOR_MAPPING_PENDING", reference, (92,), event))
                    continue
                expected_partner = vendor["id"]
            corrected["partner"] = expected_partner
            adjustment = ctx.new_entry(event, entry["company"], [reverse_line(line), corrected], reference=reference)
            # The erroneous leg is absent from the intended pair. Its peer is
            # the signed residual left in that pair (debit minus credit in EUR).
            # Sorting the pair or reversing the cash direction must not lose the
            # sign. The reclassification contributes the opposite signed leg.
            residual_eur = ctx.eur(peer, mirror)
            findings.append(Finding(event, pair, "WRONG_TRADING_PARTNER", residual_eur,
                entry["company"], "EUR", adjustment,
                (ctx.evidence(entry, line), ctx.evidence(peer, mirror), Evidence("POLITICAS_CONTABLES.md", "§6")),
                {"old_partner": line["partner"], "expected_partner": expected_partner, "expected_company": expected, "reference": reference,
                 "source_book_line": line.get("book_line"),
                 "amount_basis": "signed remaining mirror in the intended pair, debit minus credit",
                 "original_pair_residual_eur_cents": residual_eur,
                 "correction_to_intended_pair_eur_cents": ctx.eur(entry, line),
                 "corrected_event_residual_eur_cents": residual_eur + ctx.eur(entry, line),
                 "misassigned_signed_local_cents": line["debit"] - line["credit"],
                 "adjustment_currency": ctx.directory.currency(entry["company"])}))
    return findings, diagnostics


def _compatible_accounts(a: str, b: str) -> bool:
    return frozenset((a, b)) in {frozenset(("40300000", "43300000")),
        frozenset(("24230000", "16330000")), frozenset(("55210000", "55220000")),
        frozenset(("55200000",))}
