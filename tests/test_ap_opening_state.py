"""Opening credit absence and real advance history; synthetic + source-only ERP."""
from copy import deepcopy
from itertools import permutations
import json
import os
from pathlib import Path
import unittest

from kalmora.ap_journal import AdvanceState
from kalmora.ap_opening_state import resolve_ap_opening_state
from kalmora.ap_tax import TaxCatalog
from kalmora.facts import Evidence, Fact


class OpeningStateTests(unittest.TestCase):
    def setUp(self):
        self.catalog = TaxCatalog({"tax_codes": {"SEX": {"country": "ES", "kind": "exempt", "rate": 0}}})
        self.options = dict(company="1100", vendor="V1", currency="USD",
                            as_of=Fact("2026-06-30", Evidence("run", "historical_cutoff")),
                            inventory_complete=Fact(True, Evidence("erp-manifest", "complete_AP_and_manual_history")),
                            journal_entries=[], purchase_orders=[], ap_invoices=[],
                            vendors=[{"id": "V1", "companies": ["1100"]}], tax_catalog=self.catalog)

    def resolve(self, **changes):
        return resolve_ap_opening_state(**{**self.options, **changes})

    def credit(self, *, company="1100", vendor="V1", currency="USD", day="2026-06-01",
               source="AP", doc_type="KG", ident="C1"):
        return dict(company=company, id=ident, source=source, doc_type=doc_type,
                    posting_date=day, document_date=day, currency=currency, reference=ident, lines=[
            dict(account="62300000", debit=0, credit=100, amount_doc=100, currency=currency, cost_center="CC1"),
            dict(account="41000000", debit=100, credit=0, amount_doc=100, currency=currency, partner=vendor),
        ])

    def invoice(self, entry, **changes):
        return dict(company=entry["company"], doc_id="CREDIT-DOC", vendor="V1", currency="USD",
                    kind="credit_note", number=entry["reference"], posted_on=entry["posting_date"],
                    decision="POST", journal_entry=entry["id"], **changes)

    def deposit(self):
        return dict(company="1100", id="DEP", source="AP", doc_type="KR", posting_date="2026-01-02",
                    document_date="2026-01-02", currency="EUR", reference="DEPOSIT", lines=[
            dict(account="40700000", debit=80, credit=0, partner=None, assignment="PO1/10", currency="USD", amount_doc=100),
            dict(account="40000000", debit=0, credit=80, partner="V1", currency="USD", amount_doc=100),
        ])

    def assert_unknown(self, result, code=None):
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIsNone(result.state)
        if code:
            self.assertTrue(any(code in item for item in result.diagnostics), result.diagnostics)

    def test_evidenced_zero_is_scoped_and_adds_no_events_or_publications(self):
        result = self.resolve()
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual(result.state, AdvanceState())
        self.assertEqual((result.scope.company, result.scope.vendor, result.scope.currency, result.cutoff),
                         ("1100", "V1", "USD", "2026-06-30"))
        self.assertIn(self.options["as_of"].evidence, result.evidence)
        self.assertIn(self.options["inventory_complete"].evidence, result.evidence)

    def test_missing_false_unknown_nonboolean_inventory_never_proves_zero(self):
        for value in (False, None, 1, "true"):
            self.assert_unknown(self.resolve(inventory_complete=Fact(value, Evidence("manifest", "incomplete"))),
                                "INVENTORY_INCOMPLETE")
        for key in ("as_of", "inventory_complete"):
            with self.assertRaises(TypeError):
                self.resolve(**{key: True})
        for value in (None, "invalid", "2026-02-30", "20260630"):
            with self.assertRaises(ValueError):
                self.resolve(as_of=Fact(value, Evidence("run", "cutoff")))

    def test_historical_credit_and_manual_reversal_prevent_empty_credit_baseline(self):
        for entry in (self.credit(), self.credit(source="MANUAL", doc_type="SA")):
            self.assert_unknown(self.resolve(journal_entries=[entry]), "HISTORICAL_CREDIT_OR_REVERSAL")
        # A mislabeled ordinary header cannot hide a linked recorded KG.
        entry = self.credit()
        invoice = self.invoice(entry)
        invoice["kind"] = "invoice"
        self.assert_unknown(self.resolve(journal_entries=[entry], ap_invoices=[invoice]), "LINK_UNRESOLVED")

    def test_missing_posted_type_or_movement_amount_cannot_hide_a_reversal(self):
        unknown_kind = dict(company="1100", doc_id="UNKNOWN-KIND", vendor="V1", currency="USD",
                            decision="POST", posted_on="2026-06-01", journal_entry=None)
        self.assert_unknown(self.resolve(ap_invoices=[unknown_kind]))
        for missing in ((1, "debit"), (0, "credit")):
            entry = self.credit(doc_type="KR")
            entry["lines"][missing[0]].pop(missing[1])
            self.assert_unknown(self.resolve(journal_entries=[entry]))
        entry = self.credit()
        entry["lines"] = None
        self.assert_unknown(self.resolve(journal_entries=[entry]))

    def test_payable_credits_of_another_partner_cannot_net_away_the_requested_vendor_debit(self):
        entry = self.credit(source="MANUAL", doc_type="SA")
        entry["lines"].extend([
            dict(account="41000000", debit=0, credit=200, partner="OTHER", currency="USD"),
            dict(account="62300000", debit=200, credit=0, cost_center="CC1", currency="USD"),
        ])
        self.assert_unknown(self.resolve(journal_entries=[entry]), "HISTORICAL_CREDIT_OR_REVERSAL")

    def test_different_but_contradictory_scope_observations_do_not_prove_exclusion(self):
        entry = self.credit(vendor="OTHER")
        row = self.invoice(entry); row["vendor"] = "OTHER2"
        self.assert_unknown(self.resolve(journal_entries=[entry], ap_invoices=[row]), "SCOPE_UNRESOLVED")
        entry = self.credit(currency="EUR")
        row = self.invoice(entry); row["currency"] = "GBP"
        self.assert_unknown(self.resolve(journal_entries=[entry], ap_invoices=[row]), "SCOPE_UNRESOLVED")

    def test_unknown_company_vendor_currency_or_posting_date_does_not_favor_zero(self):
        for field, value in (("company", None), ("posting_date", None), ("posting_date", "2026-02-30")):
            entry = self.credit(); entry[field] = value
            self.assert_unknown(self.resolve(journal_entries=[entry]))
        entry = self.credit(vendor=None)
        self.assert_unknown(self.resolve(journal_entries=[entry]), "SCOPE_UNRESOLVED")
        entry = self.credit()
        entry.pop("currency")
        for line in entry["lines"]:
            line.pop("currency")
        self.assert_unknown(self.resolve(journal_entries=[entry]), "SCOPE_UNRESOLVED")
        entry = self.credit(source="MANUAL", doc_type="SA", vendor=None)
        self.assert_unknown(self.resolve(journal_entries=[entry]), "SCOPE_UNRESOLVED")

    def test_contradictory_linked_vendor_currency_dates_and_unknowns_abstain(self):
        entry = self.credit(vendor="OTHER", currency="EUR")
        # Neither the journal's different scope nor the header may win alone.
        row = self.invoice(entry)
        self.assert_unknown(self.resolve(journal_entries=[entry], ap_invoices=[row]), "SCOPE_UNRESOLVED")
        for field, value in (("vendor", None), ("currency", None), ("posted_on", "2026-07-01")):
            entry = self.credit()
            row = self.invoice(entry); row[field] = value
            self.assert_unknown(self.resolve(journal_entries=[entry], ap_invoices=[row]))
        future = self.credit(day="2026-07-01")
        row = self.invoice(future); row["posted_on"] = "2026-06-01"
        self.assert_unknown(self.resolve(journal_entries=[future], ap_invoices=[row]), "POSTING_DATE_UNRESOLVED")
        row["posted_on"] = "2026-07-02"
        self.assert_unknown(self.resolve(journal_entries=[future], ap_invoices=[row]), "POSTING_DATE_UNRESOLVED")

    def test_proven_other_scope_and_proven_future_movements_do_not_consume(self):
        for entry in (self.credit(company="1200"), self.credit(vendor="OTHER"),
                      self.credit(currency="EUR"), self.credit(day="2026-07-01")):
            self.assertEqual(self.resolve(journal_entries=[entry]).status, "RESOLVED")
        future = self.credit(day="2026-07-01", vendor=None)
        self.assertEqual(self.resolve(journal_entries=[future]).status, "RESOLVED")
        boundary = self.credit(day="2026-06-30")
        self.assert_unknown(self.resolve(journal_entries=[boundary]))

    def test_only_explicit_unposted_and_corroborated_absence_has_no_consumption(self):
        row = dict(company="1100", doc_id="UNPOSTED", vendor="V1", currency="USD", kind="credit_note",
                   number="UNPOSTED-NUMBER", decision="HOLD", journal_entry=None, posted_on=None)
        self.assertEqual(self.resolve(ap_invoices=[row]).status, "RESOLVED")
        for changed in ({**row, "journal_entry": "MISSING"}, {**row, "posted_on": "2026-06-01"},
                        {**row, "decision": "POST"}, {key: value for key, value in row.items() if key != "posted_on"}):
            self.assert_unknown(self.resolve(ap_invoices=[changed]))
        entry = self.credit(ident=row["number"])
        self.assert_unknown(self.resolve(ap_invoices=[row], journal_entries=[entry]))
        # Even an ordinary same-number posting contradicts the claimed absence.
        entry["doc_type"] = "KR"
        entry["lines"] = [{**line, "debit": line["credit"], "credit": line["debit"]} for line in entry["lines"]]
        self.assert_unknown(self.resolve(ap_invoices=[row], journal_entries=[entry]), "LINK_UNRESOLVED")

    def test_cash_payment_and_favorable_invoice_variance_are_not_credit_consumption(self):
        payment = self.credit(source="MANUAL", doc_type="SA")
        payment["lines"][0].update(account="57200000", debit=0, credit=100)
        self.assertEqual(self.resolve(journal_entries=[payment]).status, "RESOLVED")
        ordinary = self.credit(doc_type="KR")
        ordinary["lines"][0]["credit"] = 10
        ordinary["lines"][1].update(debit=0, credit=100)
        ordinary["lines"].append(dict(account="40090000", debit=110, credit=0, partner="V1", currency="USD"))
        self.assertEqual(self.resolve(journal_entries=[ordinary]).status, "RESOLVED")

    def test_real_advance_capacity_and_source_partner_diagnostic_are_retained(self):
        deposit = self.deposit()
        po = dict(id="PO1", company="1100", vendor="V1", currency="USD", created_on="2026-01-01", items=[dict(item=10)])
        result = self.resolve(journal_entries=[deposit], purchase_orders=[po])
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual((result.state.balances[0].amount_doc, result.state.balances[0].amount_local), (100, 80))
        self.assertEqual((result.state.events, result.state.credits), ((), ()))
        self.assertEqual(result.reference_entry_errors, ("DEP:lines[1].partner: required for open-item account",))
        self.assert_unknown(self.resolve(journal_entries=[deposit]), "ADVANCE_HISTORY_UNRESOLVED")

    def test_ordinary_posted_header_with_missing_application_link_cannot_free_a_deposit(self):
        row = dict(company="1100", doc_id="POSTED", vendor="V1", currency="USD", kind="invoice",
                   number="INV", issue_date="2026-06-01", posted_on="2026-06-01", decision="POST",
                   journal_entry="MISSING", gross=200, withholding=0, retention=0, payable=150)
        po = dict(id="PO1", company="1100", vendor="V1", currency="USD", created_on="2026-01-01", items=[dict(item=10)])
        self.assert_unknown(self.resolve(journal_entries=[self.deposit()], purchase_orders=[po], ap_invoices=[row]),
                            "ADVANCE_DOCUMENT_LINK_UNRESOLVED")

    def test_future_407_cannot_override_past_or_contradictory_down_request_header(self):
        deposit = self.deposit(); deposit["posting_date"] = "2026-07-01"
        row = dict(company="1100", doc_id="DOWN", vendor="V1", currency="USD", kind="down_payment_request",
                   number="DEPOSIT", issue_date=deposit["document_date"], posted_on="2026-06-01",
                   decision="POST", journal_entry="DEP")
        po = dict(id="PO1", company="1100", vendor="V1", currency="USD", created_on="2026-01-01", items=[dict(item=10)])
        self.assert_unknown(self.resolve(journal_entries=[deposit], purchase_orders=[po], ap_invoices=[row]),
                            "POSTING_DATE")
        row["posted_on"] = "2026-07-02"
        self.assert_unknown(self.resolve(journal_entries=[deposit], purchase_orders=[po], ap_invoices=[row]),
                            "POSTING_DATE")
        row["posted_on"] = "2026-07-01"
        self.assertEqual(self.resolve(journal_entries=[deposit], purchase_orders=[po], ap_invoices=[row]).status, "RESOLVED")

    def test_invalid_accounts_or_negative_cents_do_not_prove_harmless_movements(self):
        for changes in ({"debit": -100}, {"account": ""}, {"account": "410"}, {"credit": False}):
            entry = self.credit(source="MANUAL", doc_type="SA")
            entry["lines"][1].update(changes)
            self.assert_unknown(self.resolve(journal_entries=[entry]))
        entry = self.credit(source="MANUAL", doc_type="SA")
        entry["lines"][0]["credit"] = -100
        self.assert_unknown(self.resolve(journal_entries=[entry]))

    def test_manual_cash_refund_is_potential_reversal_but_explicit_opening_is_aggregate(self):
        refund = self.credit(source="MANUAL", doc_type="SA", vendor=None)
        refund["lines"][1].update(account="57200000", debit=100, credit=0)
        refund["lines"][1].pop("partner")
        self.assert_unknown(self.resolve(journal_entries=[refund]), "SCOPE_UNRESOLVED")
        opening = {**refund, "source": "OPENING"}
        self.assertEqual(self.resolve(journal_entries=[opening]).status, "RESOLVED")
        self.assert_unknown(self.resolve(journal_entries=[opening], inventory_complete=Fact(False, Evidence("manifest", "partial"))))
        # Opening classification cannot override an explicit linked AP credit.
        row = self.invoice(opening)
        self.assert_unknown(self.resolve(journal_entries=[opening], ap_invoices=[row]))
        self.assert_unknown(self.resolve(journal_entries=[{**opening, "doc_type": "KR"}]))
        self.assertEqual(self.resolve(journal_entries=[{**refund, "posting_date": "2026-07-01"}]).status, "RESOLVED")

    def test_one_shot_generators_inputs_immutability_and_permutation_stability(self):
        entries = [self.credit(vendor="OTHER"), self.credit(day="2026-07-01", ident="FUTURE")]
        before = deepcopy(entries)
        result = self.resolve(journal_entries=(entry for entry in entries),
                              vendors=(row for row in self.options["vendors"]),
                              purchase_orders=iter(()), ap_invoices=iter(()))
        self.assertEqual(result.status, "RESOLVED")
        for order in permutations(entries):
            self.assertEqual(self.resolve(journal_entries=order), result)
        self.assertEqual(entries, before)


class OpeningStateSourceTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("KALMORA_PHASE_ERP"), "original ERP not configured")
    def test_original_empty_credit_scopes_and_exhausted_advances_keep_sources_intact(self):
        erp = Path(os.environ["KALMORA_PHASE_ERP"])
        def rows(stem):
            return [json.loads(line) for line in (erp / f"{stem}.jsonl").read_text().splitlines()]
        inputs = dict(journal_entries=rows("journal_entries"), purchase_orders=rows("purchase_orders"),
                      vendors=rows("vendors"), ap_invoices=rows("ap_invoices"),
                      tax_catalog=TaxCatalog(json.loads((erp / "tax_codes.json").read_text())),
                      as_of=Fact("2026-06-30", Evidence("synthetic-run", "opening_cutoff")),
                      inventory_complete=Fact(True, Evidence("original-ERP-inventory", "AP+manual+PO+vendor")))
        before = deepcopy({key: inputs[key] for key in ("journal_entries", "purchase_orders", "vendors", "ap_invoices")})
        for vendor in ("V100160", "V100145"):
            result = resolve_ap_opening_state(company="1200", vendor=vendor, currency="EUR", **inputs)
            self.assertEqual((result.status, result.state), ("RESOLVED", AdvanceState()), result.diagnostics)
        result = resolve_ap_opening_state(company="1100", vendor="V100121", currency="USD", **inputs)
        self.assertEqual(result.status, "RESOLVED", result.diagnostics)
        self.assertEqual(len(result.state.balances), 3)
        self.assertEqual(len(result.reference_entry_errors), 3)
        self.assertTrue(all((b.used_doc, b.used_local) == (b.amount_doc, b.amount_local) for b in result.state.balances))
        self.assertEqual((result.state.events, result.state.credits), ((), ()))
        blocked = resolve_ap_opening_state(company="1100", vendor="V100020", currency="EUR", **inputs)
        self.assertEqual((blocked.status, blocked.state), ("UNKNOWN", None))
        self.assertTrue(any("HISTORICAL_CREDIT_OR_REVERSAL_PRESENT" in item for item in blocked.diagnostics))
        self.assertEqual({key: inputs[key] for key in before}, before)


if __name__ == "__main__":
    unittest.main()
