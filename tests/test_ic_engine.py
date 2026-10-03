"""Synthetic, independently computed examples. No organizer expected answers."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kalmora.data import PhaseData
from kalmora.facts import Evidence
from kalmora.ledger import Ledger
from kalmora.validation import validate_entry
from kalmora.ic import (Allocation, BankDelivery, OwnedEntry, Receipt, ReceiptCoverage,
                       Upstream, reconcile)
from kalmora.ic.adapters import load_upstream
from kalmora.ic.__main__ import main

E = Evidence("synthetic/independent-fixture", "not-organizer-output")


def line(account, amount, partner=None, cc=None, wbs=None, **extra):
    return {"account": account, "debit": max(amount, 0), "credit": max(-amount, 0),
            "partner": partner, "cost_center": cc, "wbs": wbs, **extra}


def entry(id, company, lines, reference="REF", day="2028-02-29", source="SYNTHETIC"):
    return {"id": id, "company": company, "posting_date": day, "document_date": day,
            "currency": "MXN" if company == "3100" else "EUR", "reference": reference,
            "source": source, "lines": lines}


def issued(reference="INV", net=100, receiver="1100", tax=21):
    return entry("ISS-" + reference, "1000", [line("43300000", net + tax, receiver, assignment=reference),
        line("70540000", -net, cc="CC-1000"), line("47700000", -tax)], reference)


def received(reference="INV", company="1100", partner="V-HOLD", day="2028-02-29", id=None):
    return entry(id or "REC-" + reference, company, [line("62940000", 100, cc="CC-" + company),
        line("47210000", 23, tax_code="RC"), line("47710000", -23, tax_code="RC"),
        line("40300000", -100, partner, assignment=reference)], reference, day)


class SyntheticFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.phase = self.root / "phase"
        (self.phase / "erp").mkdir(parents=True)
        (self.phase / "tasks").mkdir()
        self.companies = ("1000", "1100", "1200", "1300", "1910", "2100", "3100")
        self.put("companies", [{"code": c, "currency": "MXN" if c == "3100" else "EUR"} for c in self.companies])
        self.put("vendors", [{"id": "V-HOLD", "intercompany": "1000", "companies": list(self.companies)},
                             {"id": "V-OTHER", "intercompany": "1200", "companies": list(self.companies)}])
        self.put("customers", [{"id": "C-1100", "group": "1100"}])
        self.put("fx_rates", [{"date": "2028-02-01", "currency": "MXN", "rate": "20"},
                              {"date": "2028-02-28", "currency": "MXN", "rate": "20.1234"}])
        self.put("cost_centers", [{"id": "CC-" + c, "company": c} for c in self.companies])
        self.put("projects", [{"company": "2100", "id": "P", "wbs": [{"id": "WBS-P"}]}])
        accounts = ["43300000", "40300000", "40090000", "55200000", "55210000", "55220000",
                    "24230000", "16330000", "57200001", "62940000", "70540000", "47210000",
                    "47700000", "47710000", "66210000", "76210000", "66800000", "76800000"]
        self.put("chart_of_accounts", [{"account": a} for a in accounts])
        self.put("bank_accounts", [{"id": "B-" + c, "company": c, "currency": "EUR", "gl_account": "57200001"}
                                   for c in ("1000", "1100", "1200")])
        self.put("intercompany_agreements", {})
        self.put("tasks/close", {"month": "2028-02"})
        self.put("tasks/intercompany", {"pairs": [["1000", c] for c in self.companies if c != "1000"]
                  + [["1100", "1200"], ["1100", "1910"]], "accounts": accounts[:8]})
        self.upstream = Upstream(None, (), ReceiptCoverage("2028-02", True, (), "synthetic-AP", E),
                                 BankDelivery("synthetic-banks", True, (), {}, E))

    def put(self, name, obj):
        path = self.phase / (name if "/" in name else "erp/" + name)
        path.with_suffix(".json").write_text(json.dumps(obj), encoding="utf-8")

    def solve(self, entries=(), upstream=None, **kw):
        self.book = Ledger.from_entries(entries)
        return reconcile(PhaseData(self.phase), recorded=self.book, upstream=upstream or self.upstream, **kw)

    def allocation(self, receiver="1100", reference="INV", account="62940000"):
        return replace(self.upstream, invoice_allocations={("1000", receiver, reference): Allocation(account, "CC-" + receiver, None, E)})

    def setup_pool(self, *, include_wrong=False):
        self.put("intercompany_agreements", {"cash_pooling": {"header": "B-1000", "participants": ["B-1100", "B-1200"]}})
        entries = [entry("POOL-H", "1000", [line("57200001", 777), line("55200000", -777, "1200")], "POOL-MISSING", "2028-02-22")]
        folder = self.phase / "bank/B-1200"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "2028-02.lines.jsonl").write_text(json.dumps({"bank_line": "BANK-MISSING", "booking_date": "2028-02-22",
            "value_date": "2028-02-22", "currency": "EUR", "amount": -777, "text": "POOL"}) + "\n")
        correction = entry("BANK-FIX", "1200", [line("55200000", 777, "1000"), line("57200001", -777)], "POOL-MISSING")
        owned = OwnedEntry("bank:pool-missing", "banks", correction, E)
        bank = BankDelivery("synthetic-banks", True, (owned,), {"BANK-MISSING": (owned.event_id, owned.stage)}, E)
        if include_wrong:
            entries += [entry("WRONG-H", "1000", [line("57200001", 333), line("55200000", -333, "1100")], "POOL-WRONG"),
                        entry("WRONG-S", "1100", [line("57200001", -333), line("55200000", 333, "1200")], "POOL-WRONG")]
        return entries, replace(self.upstream, banks=bank)

    def setup_loan(self, lender_amount=1740, borrower_amount=1680):
        self.put("intercompany_agreements", {"loan": {"id": "LOAN", "basis": "act/360", "principal": 360000,
            "rate_bp": 600, "start": "2027-01-10", "lender": "1000", "borrower": "3100"}})
        entries = [entry("INT-H", "1000", [line("55200000", lender_amount, "3100", assignment="LOAN", currency="EUR", amount_doc=lender_amount),
                        line("76210000", -lender_amount, cc="CC-1000", currency="EUR", amount_doc=lender_amount)], "INTEREST"),
                   entry("INT-B", "3100", [line("66210000", borrower_amount * 20, currency="EUR", amount_doc=borrower_amount),
                        line("55200000", -borrower_amount * 20, "1000", assignment="LOAN", currency="EUR", amount_doc=borrower_amount)], "INTEREST")]
        upstream = replace(self.upstream, interest_allocations={"1000": Allocation("76210000", "CC-1000", None, E)})
        return entries, upstream


class InvoiceTests(SyntheticFixture):
    def test_net_not_gross_and_receiver_allocation(self):
        r = self.solve([issued()], self.allocation())
        self.assertTrue(r.complete)
        f, = r.findings
        self.assertEqual((f.cause, f.amount, f.responsible), ("INVOICE_IN_TRANSIT", 121, "1100"))
        self.assertEqual([l["debit"] for l in f.emitted_adjustment], [100, 0])
        self.assertEqual(f.emitted_adjustment[1]["partner"], "1000")
        self.assertEqual(f.emitted_adjustment[0]["cost_center"], "CC-1100")
        self.assertEqual(validate_entry(f.proposed), [])

    def test_foreign_receiver_invoice_date_fx_not_close(self):
        e = issued(receiver="3100", net=101, tax=0)
        e["document_date"] = "2028-02-10"
        f, = self.solve([e], self.allocation("3100")).findings
        self.assertEqual(f.amount, 101)
        self.assertEqual(f.emitted_adjustment[0]["debit"], 2020)  # Invoice rate 20, not 20.1234.
        self.assertEqual(f.details["adjustment_currency"], "MXN")

    def test_received_but_not_posted_is_not_in_transit(self):
        u = replace(self.allocation(), ap_coverage=ReceiptCoverage("2028-02", True,
              (Receipt("1100", "1000", "INV", "2028-02-29", E),), "AP-test", E))
        self.assertEqual(self.solve([issued()], u).records, [])

    def test_unknown_issuer_matching_reference_blocks_absence_inference(self):
        coverage = ReceiptCoverage("2028-02", True,
            (Receipt("1100", None, "INV", "2028-02-20", E),), "AP-test", E)
        result = self.solve([issued()], replace(self.allocation(), ap_coverage=coverage))
        self.assertEqual(result.records, [])
        self.assertFalse(result.complete)
        self.assertIn("AP_RECEIPT_IDENTITY_AMBIGUOUS", [d.code for d in result.diagnostics])

    def test_unknown_issuer_other_reference_does_not_invent_nonreceipt_or_receipt(self):
        coverage = ReceiptCoverage("2028-02", True,
            (Receipt("1100", None, "UNRELATED", "2028-02-20", E),), "AP-test", E)
        result = self.solve([issued()], replace(self.allocation(), ap_coverage=coverage))
        self.assertTrue(result.complete)
        self.assertEqual(result.findings[0].cause, "INVOICE_IN_TRANSIT")

    def test_receipt_after_close_does_not_remove_transit(self):
        u = replace(self.allocation(), ap_coverage=ReceiptCoverage("2028-02", True,
              (Receipt("1100", "1000", "INV", "2028-03-01", E),), "AP-test", E))
        self.assertEqual(len(self.solve([issued()], u).findings), 1)

    def test_missing_ap_coverage_is_blocked_not_assumed_empty(self):
        for coverage in (None, ReceiptCoverage("2028-02", False, (), "AP-test", E, ("UNREAD",))):
            with self.subTest(coverage=coverage):
                r = self.solve([issued()], replace(self.allocation(), ap_coverage=coverage))
                self.assertEqual(r.records, [])
                self.assertFalse(r.complete)
                self.assertIn("AP_RECEIPT_COVERAGE_PENDING", [d.code for d in r.diagnostics])

    def test_complete_coverage_cannot_hide_unresolved_documents(self):
        with self.assertRaises(ValueError):
            ReceiptCoverage("2028-02", True, (), "AP-test", E, ("UNREAD",))

    def test_mismatched_phase_is_rejected(self):
        u = replace(self.upstream, ap_coverage=ReceiptCoverage("2028-03", True, (), "AP-test", E))
        with self.assertRaisesRegex(ValueError, "different phase"):
            self.solve([], u)

    def test_allocation_absent_is_explicit_block(self):
        r = self.solve([issued()])
        self.assertFalse(r.complete)
        self.assertIn("INVOICE_ALLOCATION_PENDING", [d.code for d in r.diagnostics])

    def test_foreign_company_cost_object_is_blocked(self):
        u = replace(self.upstream, invoice_allocations={("1000", "1100", "INV"): Allocation("62940000", "CC-1200", None, E)})
        r = self.solve([issued()], u)
        self.assertFalse(r.complete)
        self.assertEqual(r.records[0]["adjustment"], [])
        self.assertIn("belongs to another company", r.diagnostics[0].message)

    def test_consistent_historical_allocation_is_used(self):
        past_issued = issued("OLD", tax=0)
        past_issued["posting_date"] = past_issued["document_date"] = "2028-02-01"
        r = self.solve([past_issued, received("OLD", day="2028-02-02"), issued()])
        self.assertTrue(r.complete)
        self.assertEqual(r.records[0]["adjustment"][0]["cost_center"], "CC-1100")

    def test_already_accrued_by_close_engine_is_not_duplicated(self):
        accrual = entry("ACCRUAL", "1100", [line("62940000", 100, cc="CC-1100"),
                          line("40090000", -100, "V-HOLD", assignment="INV")], "INV")
        owned = OwnedEntry("close:INV", "close", accrual, E)
        r = self.solve([issued()], replace(self.allocation(), ap_entries=(owned,)))
        self.assertEqual(r.findings[0].status, "already_accrued")
        self.assertEqual(r.records[0]["adjustment"], [])
        self.assertEqual(len(r.projection.entries), 2)

    def test_partial_existing_accrual_is_not_overwritten(self):
        a = entry("ACCRUAL", "1100", [line("62940000", 80, cc="CC-1100"), line("40090000", -80, "1000", assignment="INV")], "INV")
        r = self.solve([issued()], replace(self.allocation(), ap_entries=(OwnedEntry("close:INV", "close", a, E),)))
        self.assertFalse(r.complete)
        self.assertEqual(r.records[0]["adjustment"], [])
        self.assertIn("EXISTING_ACCRUAL_CONFLICT", [d.code for d in r.diagnostics])

    def test_invoice_replay_does_not_accrue_again(self):
        r = self.solve([issued()], self.allocation())
        again = self.solve([issued()], replace(self.allocation(), prior_projection=r.projection))
        self.assertTrue(again.complete)
        self.assertEqual(again.records[0]["adjustment"], [])
        self.assertEqual(again.projection.balances(), r.projection.balances())

    def test_carried_accrual_from_previous_month_is_not_duplicated(self):
        a = entry("CARRIED", "1100", [line("62940000", 100, cc="CC-1100"),
                    line("40090000", -100, "1000", assignment="INV")], "INV", day="2028-01-31")
        r = self.solve([issued(), a], self.allocation())
        self.assertTrue(r.complete)
        self.assertEqual(r.findings[0].status, "already_accrued")
        self.assertEqual(r.records[0]["adjustment"], [])

    def test_same_accrual_amount_wrong_allocation_is_not_certified(self):
        a = entry("BAD-ALLOCATION", "1100", [line("62940000", 100, cc="CC-1200"),
                    line("40090000", -100, "1000", assignment="INV")], "INV")
        r = self.solve([issued(), a], self.allocation())
        self.assertFalse(r.complete)
        self.assertEqual(r.findings[0].status, "blocked")

    def test_invoice_must_accrue_expense_not_a_tax_account(self):
        r = self.solve([issued()], self.allocation(account="47210000"))
        self.assertFalse(r.complete)
        self.assertIn("INVOICE_ALLOCATION_NOT_EXPENSE", [d.code for d in r.diagnostics])


class CorrectionTests(SyntheticFixture):
    def test_full_duplicate_reversal_includes_self_tax_and_wbs(self):
        a = received("DUP", "2100", day="2028-01-05", id="ORIGINAL")
        a["lines"][0].update(cost_center=None, wbs="WBS-P")
        b = copy.deepcopy(a)
        b.update(id="DUPLICATE", posting_date="2028-02-07", document_date="2028-02-07")
        r = self.solve([b, a])
        f, = r.findings
        self.assertEqual(f.cause, "DUPLICATE_POSTING")
        self.assertEqual(f.amount, 100)
        self.assertEqual(len(f.emitted_adjustment), 4)
        for old, new in zip(b["lines"], f.proposed["lines"]):
            self.assertEqual((old["debit"], old["credit"]), (new["credit"], new["debit"]))
            for key in ("tax_code", "cost_center", "wbs", "assignment", "partner"):
                self.assertEqual(old.get(key), new.get(key))
        self.assertEqual(f.proposed["lines"][0]["source_book_line"], "DUPLICATE#1")

    def test_same_value_different_reference_or_company_is_not_duplicate(self):
        self.assertEqual(self.solve([received("ONE"), received("TWO"), received("ONE", "2100", id="2100-ONE")]).records, [])

    def test_same_reference_different_content_does_not_trigger_reversal(self):
        a, b = received("REF", id="A"), received("REF", id="B")
        b["lines"][0]["cost_center"] = "CC-1200"
        r = self.solve([a, b])
        self.assertEqual(r.records, [])
        self.assertIn("DUPLICATE_REFERENCE_CONFLICT", [d.code for d in r.diagnostics])

    def test_fx_revaluation_and_reversal_are_not_duplicate_invoices(self):
        a = entry("FX-OLD", "3100", [line("66800000", 20), line("40300000", -20, "V-HOLD")], "FX-REF", source="CLOSE_FX")
        b = copy.deepcopy(a)
        b.update(id="FX-REVERSE", source="CLOSE_FX:reversal")
        for l in b["lines"]:
            l["debit"], l["credit"] = l["credit"], l["debit"]
        r = self.solve([a, b])
        self.assertTrue(r.complete)
        self.assertEqual(r.records, [])

    def test_multiple_duplicates_are_reversed_once_each(self):
        originals = [received("REF", id=id) for id in ("A", "B", "C")]
        r = self.solve(originals)
        self.assertEqual(len(r.records), 2)
        again = self.solve(originals, replace(self.upstream, prior_projection=r.projection))
        self.assertTrue(all(f.status == "already_applied" for f in again.findings))
        self.assertTrue(all(not row["adjustment"] for row in again.records))
        self.assertEqual(again.projection.entries, r.projection.entries)

    def test_external_duplicate_reversal_is_consumed_and_replayed_once(self):
        entries = [received("DUP", id=k) for k in ("ORIG", "DUP")]
        reversal = copy.deepcopy(entries[1])
        reversal["id"] = "AP-REVERSAL"
        for l in reversal["lines"]:
            l["debit"], l["credit"] = l["credit"], l["debit"]
        owned = OwnedEntry("ap:reverse-duplicate", "ap_reversal", reversal, E)
        upstream = replace(self.upstream, ap_entries=(owned,))
        result = self.solve(entries, upstream)
        self.assertTrue(result.complete)
        self.assertEqual(result.records[0]["adjustment"], [])
        self.assertEqual(result.findings[0].status, "already_corrected_externally")
        self.assertEqual(len(result.projection.entries), 3)
        # A restored external correction remains authoritative even if the new
        # AP delivery no longer repeats it.
        replay = self.solve(entries, replace(self.upstream, prior_projection=result.projection))
        self.assertEqual(replay.records, result.records)
        self.assertEqual(replay.projection.entries, result.projection.entries)

    def test_one_external_reversal_cannot_cover_two_duplicates(self):
        entries = [received("DUP", id=k) for k in ("ORIG", "DUP-1", "DUP-2")]
        reversal = copy.deepcopy(entries[1])
        reversal["id"] = "AP-REVERSAL"
        for l in reversal["lines"]:
            l["debit"], l["credit"] = l["credit"], l["debit"]
        upstream = replace(self.upstream, ap_entries=(OwnedEntry("ap:reverse", "ap_reversal", reversal, E),))
        result = self.solve(entries, upstream)
        self.assertTrue(result.complete)
        self.assertEqual(sum(bool(r["adjustment"]) for r in result.records), 1)
        self.assertEqual(len(result.projection.entries), 5)
        replay = self.solve(entries, replace(upstream, prior_projection=result.projection))
        self.assertTrue(replay.complete)
        self.assertTrue(all(not r["adjustment"] for r in replay.records))
        self.assertEqual(replay.projection.entries, result.projection.entries)

    def test_excess_external_reversals_are_blocked(self):
        entries = [received("DUP", id=k) for k in ("ORIG", "DUP")]
        reversals = []
        for identity in ("AP-REVERSAL-1", "AP-REVERSAL-2"):
            reversal = copy.deepcopy(entries[1])
            reversal["id"] = identity
            for l in reversal["lines"]:
                l["debit"], l["credit"] = l["credit"], l["debit"]
            reversals.append(OwnedEntry(identity, "ap_reversal", reversal, E))
        result = self.solve(entries, replace(self.upstream, ap_entries=tuple(reversals)))
        self.assertFalse(result.complete)
        self.assertEqual(result.records[0]["adjustment"], [])
        self.assertIn("EXISTING_IC_CORRECTION_CONFLICT", [d.code for d in result.diagnostics])

    def test_reversal_of_a_different_invoice_does_not_cover_duplicate(self):
        entries = [received("DUP", id=k) for k in ("ORIG", "DUP")]
        reversal = received("OTHER", id="AP-OTHER-REVERSAL")
        for l in reversal["lines"]:
            l["debit"], l["credit"] = l["credit"], l["debit"]
        result = self.solve(entries, replace(self.upstream, ap_entries=(OwnedEntry("ap:other", "ap_reversal", reversal, E),)))
        self.assertTrue(result.records[0]["adjustment"])

    def test_partial_external_reversal_blocks_a_full_second_reversal(self):
        entries = [received("DUP", id=k) for k in ("ORIG", "DUP")]
        reversal = copy.deepcopy(entries[1])
        reversal["id"] = "AP-PARTIAL-REVERSAL"
        for l in reversal["lines"]:
            l["debit"], l["credit"] = l["credit"], l["debit"]
            l["debit"] //= 2
            l["credit"] //= 2
        result = self.solve(entries, replace(self.upstream, ap_entries=(OwnedEntry("ap:partial", "ap_reversal", reversal, E),)))
        self.assertFalse(result.complete)
        self.assertEqual(result.records[0]["adjustment"], [])
        self.assertIn("EXISTING_IC_CORRECTION_CONFLICT", [d.code for d in result.diagnostics])

    def test_bank_owned_partner_reclassification_is_not_posted_again(self):
        entries, upstream = self.setup_pool(include_wrong=True)
        correction = entry("BANK-PARTNER-FIX", "1100", [line("55200000", -333, "1200"),
            line("55200000", 333, "1000")], "POOL-WRONG")
        owned = OwnedEntry("bank:partner", "banks", correction, E)
        upstream = replace(upstream, banks=replace(upstream.banks, entries=(*upstream.banks.entries, owned)))
        result = self.solve(entries, upstream)
        self.assertTrue(result.complete)
        finding = next(f for f in result.findings if f.cause == "WRONG_TRADING_PARTNER")
        self.assertEqual(finding.status, "already_corrected_externally")
        self.assertEqual(finding.emitted_adjustment, [])
        for position in result.corrected["comparisons"]:
            if position["reference"] == "POOL-WRONG":
                self.assertEqual(position["difference_cents"], 0)
        replay = self.solve(entries, replace(upstream, prior_projection=result.projection))
        self.assertTrue(replay.complete)
        self.assertEqual(replay.projection.entries, result.projection.entries)

    def test_partial_bank_partner_reclassification_is_blocked(self):
        entries, upstream = self.setup_pool(include_wrong=True)
        correction = entry("BANK-PARTIAL-FIX", "1100", [line("55200000", -100, "1200"),
            line("55200000", 100, "1000")], "POOL-WRONG")
        owned = OwnedEntry("bank:partial-partner", "banks", correction, E)
        result = self.solve(entries, replace(upstream, banks=replace(upstream.banks, entries=(*upstream.banks.entries, owned))))
        self.assertFalse(result.complete)
        finding = next(f for f in result.findings if f.cause == "WRONG_TRADING_PARTNER")
        self.assertEqual(finding.status, "blocked")
        self.assertEqual(finding.emitted_adjustment, [])

    def test_external_and_own_reversal_together_are_a_conflict(self):
        entries = [received("DUP", id=k) for k in ("ORIG", "DUP")]
        first = self.solve(entries)
        reversal = copy.deepcopy(entries[1])
        reversal["id"] = "AP-REVERSAL"
        for l in reversal["lines"]:
            l["debit"], l["credit"] = l["credit"], l["debit"]
        upstream = replace(self.upstream, prior_projection=first.projection,
            ap_entries=(OwnedEntry("ap:reverse", "ap_reversal", reversal, E),))
        result = self.solve(entries, upstream)
        self.assertFalse(result.complete)
        self.assertEqual(result.records[0]["adjustment"], [])

    def test_pooling_wrong_partner_has_mirror_evidence_and_no_tax_changes(self):
        entries, u = self.setup_pool(include_wrong=True)
        r = self.solve(entries, u)
        f = next(f for f in r.findings if f.cause == "WRONG_TRADING_PARTNER")
        self.assertEqual(f.pair, ("1000", "1100"))
        self.assertEqual(f.amount, -333)
        self.assertEqual([(l["partner"], l["debit"], l["credit"]) for l in f.emitted_adjustment], [("1200", 0, 333), ("1000", 333, 0)])

    def test_wrong_partner_signed_residual_both_directions_and_company_orientations(self):
        for responsible, peer in (("1100", "1000"), ("1000", "1100")):
            for amount in (719, -719):
                with self.subTest(responsible=responsible, amount=amount):
                    reference = "SYNTHETIC-MIRROR"
                    entries = [entry("MISASSIGNED", responsible,
                        [line("55200000", amount, "1200"), line("57200001", -amount)], reference),
                        entry("MIRROR", peer,
                        [line("55200000", -amount, responsible), line("57200001", amount)], reference)]
                    result = self.solve(entries)
                    finding, = result.findings
                    self.assertEqual(finding.cause, "WRONG_TRADING_PARTNER")
                    self.assertEqual(finding.amount, -amount)
                    self.assertEqual(finding.amount_currency, "EUR")
                    self.assertEqual(finding.details["corrected_event_residual_eur_cents"], 0)
                    self.assertEqual(finding.responsible, responsible)
                    # Signed intended pair position is nonzero before, zero after.
                    def pair_sum(book):
                        return sum(l["debit"] - l["credit"] for e in book.entries for l in e["lines"]
                                   if l["account"] == "55200000" and
                                   ((e["company"] == responsible and l.get("partner") == peer) or
                                    (e["company"] == peer and l.get("partner") == responsible)))
                    self.assertEqual(pair_sum(self.book), -amount)
                    self.assertEqual(pair_sum(result.projection), 0)
                    self.assertEqual(self.solve(list(reversed(entries))).records, result.records)

    def test_wrong_partner_uses_compatible_eur_not_local_mxn(self):
        for amount in (719, -719):
            with self.subTest(amount=amount):
                entries = [entry("MISASSIGNED-MXN", "3100", [
                    line("55200000", amount * 20, "1200", currency="EUR", amount_doc=abs(amount)),
                    line("57200001", -amount * 20)], "FX-MIRROR"),
                    entry("MIRROR-EUR", "1000", [line("55200000", -amount, "3100"),
                    line("57200001", amount)], "FX-MIRROR")]
                finding, = self.solve(entries).findings
                self.assertEqual(finding.amount, -amount)
                self.assertEqual(finding.amount_currency, "EUR")
                self.assertEqual(finding.details["misassigned_signed_local_cents"], amount * 20)
                self.assertEqual(finding.proposed["lines"][1]["amount_doc"], abs(amount))

    def test_invoice_wrong_partner_uses_vendor_master_not_company_alias(self):
        i, r = issued(tax=0), received(partner="V-OTHER")
        result = self.solve([i, r])
        self.assertEqual(len(result.findings), 1)
        self.assertTrue(result.complete)
        f = next(f for f in result.findings if f.cause == "WRONG_TRADING_PARTNER")
        self.assertEqual(f.details["expected_partner"], "V-HOLD")
        self.assertEqual(f.proposed["lines"][1]["partner"], "V-HOLD")
        self.assertEqual(f.responsible, "1100")

    def test_same_side_ute_accounts_not_accepted_as_mirrors(self):
        entries = [entry("U1", "1100", [line("55210000", 10, "1200"), line("57200001", -10)], "UTE"),
                   entry("U2", "1910", [line("55210000", -10, "1100"), line("57200001", 10)], "UTE")]
        self.assertEqual(self.solve(entries).records, [])

    def test_permutation_does_not_change_records_or_owners(self):
        entries, u = self.setup_pool(include_wrong=True)
        a = self.solve(entries, u)
        b = self.solve(list(reversed(entries)), u)
        self.assertEqual(a.records, b.records)
        self.assertEqual([f.event_id for f in a.findings], [f.event_id for f in b.findings])


class InterestTests(SyntheticFixture):
    def test_leap_month_short_accrual_eur_difference_local_adjustment(self):
        entries, u = self.setup_loan()
        r = self.solve(entries, u)
        self.assertTrue(r.complete)
        f, = r.findings
        self.assertEqual((f.cause, f.amount, f.responsible), ("INTEREST_DAY_COUNT", 60, "3100"))
        self.assertEqual(f.emitted_adjustment[0]["debit"], 1207)  # 60 * 20.1234 = 1207.404
        self.assertEqual(f.details["calculation"]["days"], 29)
        self.assertEqual(f.amount_currency, "EUR")

    def test_both_parties_are_checked_against_contract(self):
        entries, u = self.setup_loan(1680, 1680)
        r = self.solve(entries, u)
        self.assertTrue(r.complete)
        self.assertEqual({f.responsible for f in r.findings}, {"1000", "3100"})
        self.assertTrue(all(f.amount == 60 for f in r.findings))

    def test_overaccrual_is_reduced_not_increased(self):
        entries, u = self.setup_loan(1740, 1800)
        f, = self.solve(entries, u).findings
        self.assertEqual(f.amount, 60)
        self.assertEqual((f.emitted_adjustment[0]["debit"], f.emitted_adjustment[0]["credit"]), (0, 1207))

    def test_agreement_interest_rate_is_not_fixed(self):
        entries, u = self.setup_loan(1740, 1680)
        agreement = json.loads((self.phase / "erp/intercompany_agreements.json").read_text())
        agreement["loan"]["rate_bp"] = 1200
        self.put("intercompany_agreements", agreement)
        r = self.solve(entries, u)
        self.assertEqual([f.details["calculation"]["rounded_cents"] for f in r.findings], [3480, 3480])

    def test_missing_lender_cost_allocation_remains_explicit_validation_block(self):
        entries, u = self.setup_loan(1680, 1740)
        r = self.solve(entries, replace(u, interest_allocations={}))
        self.assertFalse(r.complete)
        self.assertEqual(r.records[0]["adjustment"], [])
        self.assertIn("cost object required", r.diagnostics[0].message)

    def test_interest_exact_replay_preserves_original_and_projection(self):
        entries, u = self.setup_loan()
        recorded = Ledger.from_entries(entries)
        original = recorded.entries
        r = reconcile(PhaseData(self.phase), recorded=recorded, upstream=u)
        projected = r.projection.entries
        again = reconcile(PhaseData(self.phase), recorded=recorded, upstream=replace(u, prior_projection=r.projection))
        self.assertEqual(recorded.entries, original)
        self.assertEqual(r.projection.entries, projected)
        self.assertEqual(again.projection.entries, projected)
        self.assertEqual(again.findings[0].status, "already_applied")
        self.assertEqual(again.records[0]["adjustment"], [])

    def test_existing_external_interest_correction_is_not_duplicated(self):
        entries, u = self.setup_loan()
        fix = entry("EXTERNAL-INTEREST", "3100", [line("66210000", 1207, currency="EUR", amount_doc=60),
            line("55200000", -1207, "1000", assignment="LOAN", currency="EUR", amount_doc=60)], "LOAN")
        r = self.solve(entries, replace(u, ap_entries=(OwnedEntry("close:interest", "close", fix, E),)))
        self.assertTrue(r.complete)
        self.assertEqual(r.findings[0].status, "already_corrected_externally")
        self.assertEqual(r.records[0]["adjustment"], [])

    def test_partial_external_interest_correction_is_explicit_conflict(self):
        entries, u = self.setup_loan()
        fix = entry("EXTERNAL-INTEREST", "3100", [line("66210000", 604, currency="EUR", amount_doc=30),
            line("55200000", -604, "1000", assignment="LOAN", currency="EUR", amount_doc=30)], "LOAN")
        r = self.solve(entries, replace(u, ap_entries=(OwnedEntry("close:interest", "close", fix, E),)))
        self.assertFalse(r.complete)
        self.assertIn("EXISTING_INTEREST_CORRECTION_CONFLICT", [d.code for d in r.diagnostics])
        self.assertEqual(r.records[0]["adjustment"], [])

    def test_wrong_partner_is_not_interpreted_as_zero_accrual(self):
        entries, u = self.setup_loan(1740, 1740)
        entries[1]["lines"][1]["partner"] = "1200"
        r = self.solve(entries, u)
        self.assertTrue(r.complete)
        self.assertEqual([f.cause for f in r.findings], ["WRONG_TRADING_PARTNER"])


class PoolingTests(SyntheticFixture):
    def test_bank_owns_adjustment_and_original_incidence_is_preserved(self):
        entries, u = self.setup_pool()
        r = self.solve(entries, u)
        self.assertTrue(r.complete)
        f, = r.findings
        self.assertEqual((f.cause, f.amount, f.status), ("POOLING_NOT_BOOKED", 777, "resolved_by_banks"))
        self.assertEqual(f.emitted_adjustment, [])
        self.assertEqual(len(r.projection.entries), 2)
        self.assertEqual(r.projection.entries[-1]["provenance"]["stage"], "banks")
        original = next(c for c in r.original["comparisons"] if c["reference"] == "POOL-MISSING")
        fixed = next(c for c in r.corrected["comparisons"] if c["reference"] == "POOL-MISSING")
        self.assertEqual((original["difference_cents"], fixed["difference_cents"]), (-777, 0))

    def test_missing_bank_correction_is_visible_and_never_proposed_by_ic(self):
        entries, _ = self.setup_pool()
        r = self.solve(entries, replace(self.upstream, banks=None))
        self.assertFalse(r.complete)
        self.assertEqual(r.records[0]["adjustment"], [])
        self.assertEqual(len(r.projection.entries), 1)
        self.assertIn("POOLING_BANK_CORRECTION_PENDING", [d.code for d in r.diagnostics])

    def test_bank_projection_already_applied_is_consumed_once(self):
        entries, u = self.setup_pool()
        first = self.solve(entries, u)
        second = self.solve(entries, replace(u, prior_projection=first.projection))
        self.assertTrue(second.complete)
        self.assertEqual(first.records, second.records)
        self.assertEqual(first.projection.entries, second.projection.entries)

    def test_wrong_bank_amount_is_not_claimed_resolved(self):
        entries, u = self.setup_pool()
        correction = copy.deepcopy(u.banks.entries[0].entry)
        correction["lines"][0]["debit"] = correction["lines"][1]["credit"] = 778
        changed = replace(u.banks.entries[0], entry=correction)
        r = self.solve(entries, replace(u, banks=replace(u.banks, entries=(changed,))))
        self.assertFalse(r.complete)
        self.assertIn("POOLING_CORRECTION_MISMATCH", [d.code for d in r.diagnostics])
        self.assertEqual(r.records[0]["adjustment"], [])

    def test_unbalanced_external_bank_entry_is_rejected(self):
        entries, u = self.setup_pool()
        correction = copy.deepcopy(u.banks.entries[0].entry)
        correction["lines"][0]["debit"] += 1
        changed = replace(u.banks.entries[0], entry=correction)
        with self.assertRaisesRegex(ValueError, "unbalanced"):
            self.solve(entries, replace(u, banks=replace(u.banks, entries=(changed,))))

    def test_unknown_bank_event_link_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "supplied bank entry"):
            BankDelivery("bank", True, (), {"B": ("missing", "banks")}, E)

    def test_nonunique_statement_does_not_guess(self):
        entries, u = self.setup_pool()
        p = self.phase / "bank/B-1200/2028-02.lines.jsonl"
        p.write_text(p.read_text() * 2)
        r = self.solve(entries, u)
        self.assertFalse(r.complete)
        self.assertIn("POOLING_STATEMENT_EVIDENCE_PENDING", [d.code for d in r.diagnostics])


class BoundaryTests(SyntheticFixture):
    def test_missing_interfaces_are_not_empty_success(self):
        r = self.solve([], Upstream.missing())
        self.assertFalse(r.complete)
        self.assertEqual({d.code for d in r.diagnostics}, {"AP_ENTRY_DELIVERY_PENDING", "AP_RECEIPT_COVERAGE_PENDING", "BANK_DELIVERY_PENDING"})

    def test_changed_original_in_prior_projection_is_rejected(self):
        e = received()
        changed = copy.deepcopy(e)
        changed["reference"] = "OTHER"
        with self.assertRaisesRegex(ValueError, "changed or removed"):
            self.solve([e], replace(self.upstream, prior_projection=Ledger.from_entries([changed])))

    def test_removed_original_in_prior_projection_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "changed or removed"):
            self.solve([received()], replace(self.upstream, prior_projection=Ledger()))

    def test_external_entries_need_explicit_producer_ownership(self):
        with self.assertRaisesRegex(ValueError, "no producer ownership"):
            self.solve([], replace(self.upstream, prior_projection=Ledger.from_entries([received()])))

    def test_external_producer_cannot_impersonate_ic(self):
        with self.assertRaisesRegex(ValueError, "impersonate"):
            self.solve([], replace(self.upstream, ap_entries=(OwnedEntry("ic:fake", "AP", received(), E),)))

    def test_changed_external_event_on_replay_is_rejected(self):
        e = received()
        owned = OwnedEntry("ap:receipt", "AP", e, E)
        u = replace(self.upstream, ap_entries=(owned,))
        first = self.solve([], u)
        changed = copy.deepcopy(e)
        changed["reference"] = "CHANGED"
        with self.assertRaisesRegex(ValueError, "Conflicting content"):
            self.solve([], replace(u, prior_projection=first.projection, ap_entries=(replace(owned, entry=changed),)))

    def test_shared_contract_hook_is_consumed_and_enforced(self):
        seen = []
        def validate(record):
            seen.append(record)
            return []
        r = self.solve([issued()], self.allocation(), contract_validator=validate)
        self.assertEqual(seen, r.records)
        with self.assertRaisesRegex(ValueError, "Output contract rejected"):
            self.solve([issued()], self.allocation(), contract_validator=lambda _: ["mock shared rejection"])

    def test_solver_reader_rejects_golden_and_symlink(self):
        forbidden = self.root / "golden"
        forbidden.mkdir()
        (forbidden / "upstream.json").write_text('{"schema_version":1}')
        link = self.root / "innocent.json"
        link.symlink_to(forbidden / "upstream.json")
        for p in (link, forbidden / "upstream.json"):
            with self.assertRaises(ValueError):
                load_upstream(p)

    def test_cli_requires_explicit_dependency_mode(self):
        with self.assertRaises(SystemExit) as caught:
            main(["--phase", str(self.phase), "--out", str(self.root / "out"), "--backend-commit", "synthetic"])
        self.assertEqual(caught.exception.code, 2)

    def test_cli_produces_incomplete_artifacts_and_runrecorder(self):
        (self.phase / "erp/journal_entries.jsonl").write_text("")
        out = self.root / "out"
        code = main(["--phase", str(self.phase), "--out", str(out), "--backend-commit", "synthetic", "--recorded-only"])
        self.assertEqual(code, 3)
        audit = json.loads((out / "audit.json").read_text())
        run = json.loads(next((out / "runs").glob("*.json")).read_text())
        self.assertFalse(audit["complete"])
        self.assertEqual(run["exit_code"], 3)
        self.assertEqual(run["cost"]["status"], "no_llm")
        self.assertEqual((out / "ic.jsonl").read_text(), "")

    def test_json_adapter_keeps_absent_deliveries_absent(self):
        p = self.root / "upstream.json"
        p.write_text(json.dumps({"schema_version": 1}))
        u = load_upstream(p)
        self.assertIsNone(u.ap_entries)
        self.assertIsNone(u.banks)
        self.assertIsNone(u.ap_coverage)


if __name__ == "__main__":
    unittest.main()


class EndToEndSyntheticTests(SyntheticFixture):
    def test_five_causes_all_fields_replay_and_unchanged_erp(self):
        pool_entries, pool_upstream = self.setup_pool(include_wrong=True)
        pool_agreement = json.loads((self.phase / "erp/intercompany_agreements.json").read_text())
        loan_entries, loan_upstream = self.setup_loan()
        loan_agreement = json.loads((self.phase / "erp/intercompany_agreements.json").read_text())
        self.put("intercompany_agreements", {**pool_agreement, **loan_agreement})
        original = received("DUP", "2100", day="2028-01-05", id="ORIG")
        duplicate = copy.deepcopy(original)
        duplicate.update(id="DUP", posting_date="2028-02-10", document_date="2028-02-10")
        entries = [*pool_entries, *loan_entries, original, duplicate, issued()]
        u = replace(self.allocation(), banks=pool_upstream.banks, interest_allocations=loan_upstream.interest_allocations)
        r = self.solve(entries, u)
        self.assertTrue(r.complete, [d.to_dict() for d in r.diagnostics])
        self.assertEqual(len(r.records), 5)
        self.assertEqual(sum(bool(row["adjustment"]) for row in r.records), 4)
        self.assertEqual({f.cause: f.amount for f in r.findings}, {
            "INVOICE_IN_TRANSIT": 121, "INTEREST_DAY_COUNT": 60,
            "WRONG_TRADING_PARTNER": -333, "DUPLICATE_POSTING": 100, "POOLING_NOT_BOOKED": 777})
        for row in r.records:
            self.assertEqual(set(row), {"pair", "cause", "amount", "responsible", "adjustment"})
            self.assertIn(row["responsible"], row["pair"])
            self.assertEqual(sum(l["debit"] - l["credit"] for l in row["adjustment"]), 0)
        recorded = Ledger.from_entries(entries)
        self.assertEqual(self.book.entries, recorded.entries)
        again = self.solve(entries, replace(u, prior_projection=r.projection))
        self.assertTrue(again.complete)
        self.assertTrue(all(not row["adjustment"] for row in again.records))
        self.assertEqual(again.projection.entries, r.projection.entries)
        # Bank correction remains a single bank-owned entry, never an IC entry.
        bank_entries = [e for e in again.projection.entries if e.get("provenance", {}).get("stage") == "banks"]
        self.assertEqual(len(bank_entries), 1)
