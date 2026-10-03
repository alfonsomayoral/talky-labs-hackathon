from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from kalmora.ap_advance_history import resolve_historical_advances
from kalmora.ap_journal import AdvanceState
from kalmora.ap_tax import TaxCatalog


class AdvanceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.vendor = dict(id="V-NEW", companies=["1100"])
        self.po = dict(id="PO-NEW", company="1100", vendor="V-NEW", currency="USD",
                       created_on="2026-01-01", items=[dict(item=20)])
        self.deposit = dict(company="1100", id="DEP-NEW", source="AP", doc_type="KR", currency="EUR",
                            reference="DEPOSIT-REF", document_date="2026-02-01", posting_date="2026-02-02", lines=[
            dict(account="40700000", partner=None, debit=80, credit=0, currency="USD", amount_doc=100,
                 assignment="PO-NEW/20"),
            dict(account="40000000", partner="V-NEW", debit=0, credit=80, currency="USD", amount_doc=100)])
        self.application = dict(company="1100", id="APP-NEW", source="AP", doc_type="KR", currency="EUR",
                                reference="INV-NEW", document_date="2026-03-01", posting_date="2026-03-02", lines=[
            dict(account="62300000", cost_center="CC-NEW", debit=160, credit=0, currency="USD", amount_doc=200,
                 assignment="PO-NEW/20", tax_code="SEX"),
            dict(account="40000000", partner="V-NEW", debit=0, credit=120, currency="USD", amount_doc=150),
            dict(account="40700000", partner="V-NEW", debit=0, credit=40, currency="EUR", amount_doc=40,
                 assignment="DEPOSIT-REF")])
        self.invoice = dict(company="1100", doc_id="I-NEW", vendor="V-NEW", currency="USD", kind="invoice",
                            number="INV-NEW", issue_date="2026-03-01", journal_entry="APP-NEW", net=200,
                            tax=0, gross=200, withholding=0, retention=0, payable=150)

    def resolve(self, **changes):
        options = dict(company="1100", vendor="V-NEW", as_of="2026-07-31",
                       journal_entries=[self.deposit, self.application], purchase_orders=[self.po],
                       vendors=[self.vendor], ap_invoices=[self.invoice], inventory_complete=True)
        options["tax_catalog"] = TaxCatalog({"tax_codes": {"SEX": {"country": "ES", "kind": "exempt", "rate": 0}}})
        options.update(changes)
        return resolve_historical_advances(**options)

    def test_foreign_local_application_uses_document_residual_and_keeps_source_partner_error(self):
        before = deepcopy((self.deposit, self.application, self.po, self.invoice))
        result = self.resolve()
        self.assertEqual(result.status, "RESOLVED")
        balance, = result.balances
        self.assertEqual((balance.currency, balance.amount_doc, balance.amount_local,
                          balance.used_doc, balance.used_local), ("USD", 100, 80, 50, 40))
        self.assertEqual((balance.advance_id, balance.po, balance.vendor), ("DEP-NEW", "PO-NEW", "V-NEW"))
        self.assertEqual(result.reference_entry_errors,
                         ("DEP-NEW:lines[1].partner: required for open-item account",))
        self.assertTrue(any(e.document == "erp/ap_invoices.jsonl" and e.field.endswith("payable") for e in result.evidence))
        self.assertEqual((self.deposit, self.application, self.po, self.invoice), before)
        state = AdvanceState(result.balances)
        self.assertEqual(state.balances[0].used_doc, 50)

    def test_cutoff_uses_posted_dates_and_never_infers_approval_or_classification(self):
        result = self.resolve(as_of="2026-02-28")
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual((result.balances[0].used_doc, result.balances[0].used_local), (0, 0))
        self.assertEqual(self.resolve(as_of="2026-01-31").balances, ())
        self.assertFalse(hasattr(result.balances[0], "treatment"))
        self.assertEqual(self.resolve(inventory_complete=False).status, "UNKNOWN")
        with self.assertRaises(ValueError):
            self.resolve(as_of="2026-02-30")
        with self.assertRaises(TypeError):
            self.resolve(inventory_complete=1)

    def test_posted_header_missing_gl_link_cannot_prove_unused_advance(self):
        row = {**self.invoice, "decision": "POST", "posted_on": "2026-03-02", "journal_entry": "MISSING"}
        result = self.resolve(journal_entries=[self.deposit], ap_invoices=[row])
        self.assertEqual((result.status, result.balances), ("UNKNOWN", ()))
        self.assertTrue(any("DOCUMENT_LINK_UNRESOLVED" in item for item in result.diagnostics))
        for kind in (None, "unknown"):
            unknown = {**row, "kind": kind}
            if kind is None:
                unknown.pop("kind")
            result = self.resolve(journal_entries=[self.deposit], ap_invoices=[unknown])
            self.assertEqual((result.status, result.balances), ("UNKNOWN", ()))
            self.assertTrue(any("DOCUMENT_KIND_UNRESOLVED" in item for item in result.diagnostics))
        # A linked ordinary posting without the observed 50 document cents of
        # advance application is also a contradiction, not proof of zero use.
        ordinary = deepcopy(self.application)
        ordinary["lines"] = ordinary["lines"][:2]
        ordinary["lines"][1]["credit"] = 160
        result = self.resolve(journal_entries=[self.deposit, ordinary])
        self.assertEqual((result.status, result.balances), ("UNKNOWN", ()))
        self.assertTrue(any("APPLICATION_UNCORROBORATED" in item for item in result.diagnostics))
        other = {**row, "company": "1200", "vendor": "OTHER"}
        self.assertEqual(self.resolve(journal_entries=[self.deposit], ap_invoices=[other]).status, "RESOLVED")
        future = {**row, "posted_on": "2026-08-01"}
        self.assertEqual(self.resolve(journal_entries=[self.deposit], ap_invoices=[future]).status, "RESOLVED")
        unposted = {**row, "posted_on": None, "journal_entry": None, "decision": "HOLD"}
        self.assertEqual(self.resolve(journal_entries=[self.deposit], ap_invoices=[unposted]).status, "RESOLVED")

    def test_407_and_ordinary_application_clocks_require_concordance_before_future_exclusion(self):
        deposit = {**self.deposit, "posting_date": "2026-08-01"}
        down = dict(company="1100", doc_id="DOWN", vendor="V-NEW", currency="USD", kind="down_payment_request",
                    number=deposit["reference"], issue_date=deposit["document_date"], decision="POST",
                    journal_entry=deposit["id"], posted_on="2026-03-01")
        for day in ("2026-03-01", "2026-08-02", "invalid"):
            result = self.resolve(journal_entries=[deposit], ap_invoices=[{**down, "posted_on": day}])
            self.assertEqual((result.status, result.balances), ("UNKNOWN", ()))
            self.assertTrue(any("POSTING_DATE" in item for item in result.diagnostics))
        self.assertEqual(self.resolve(journal_entries=[deposit], ap_invoices=[{**down, "posted_on": "2026-08-01"}]).status,
                         "RESOLVED")
        application = {**self.application, "posting_date": "2026-08-01"}
        row = {**self.invoice, "posted_on": "2026-03-02"}
        result = self.resolve(journal_entries=[self.deposit, application], ap_invoices=[row])
        self.assertEqual((result.status, result.balances), ("UNKNOWN", ()))

    def test_header_linked_scope_conflicts_and_iterable_snapshots_are_preserved(self):
        row = {**self.invoice, "currency": "EUR"}
        result = self.resolve(ap_invoices=[row])
        self.assertEqual((result.status, result.balances), ("UNKNOWN", ()))
        ordinary = deepcopy(self.application)
        ordinary["lines"][1]["partner"] = "OTHER"
        row = {**self.invoice, "vendor": "OTHER2"}
        self.assertEqual(self.resolve(journal_entries=[self.deposit, ordinary], ap_invoices=[row]).status, "UNKNOWN")
        before = deepcopy((self.deposit, self.application, self.invoice))
        result = self.resolve(journal_entries=(entry for entry in (self.deposit, self.application)),
                              purchase_orders=iter([self.po]), vendors=iter([self.vendor]), ap_invoices=iter([self.invoice]))
        self.assertEqual(result.status, "RESOLVED", result.diagnostics)
        self.assertEqual((self.deposit, self.application, self.invoice), before)

    def test_unknown_po_manual_movement_or_missing_affiliation_suppresses_usable_baseline(self):
        for changes in (dict(purchase_orders=[]), dict(vendors=[]),
                        dict(purchase_orders=[{**self.po, "items": [dict(item=10)]}]),
                        dict(purchase_orders=[{**self.po, "currency": "EUR"}]),
                        dict(purchase_orders=[{**self.po, "created_on": "2026-02-10"}])):
            result = self.resolve(**changes)
            self.assertEqual((result.status, result.balances), ("UNKNOWN", ()))
        manual = deepcopy(self.deposit)
        manual.update(id="MANUAL-NEW", reference="MANUAL-REF", source="MANUAL_PAYMENT")
        manual["lines"][0].update(partner="V-NEW", assignment="UNTIED")
        result = self.resolve(journal_entries=[self.deposit, self.application, manual])
        self.assertEqual((result.status, result.balances), ("UNKNOWN", ()))
        self.assertTrue(any("ORIGINAL_PO_UNRESOLVED" in d for d in result.diagnostics))

    def test_unknown_document_split_or_mixed_currency_never_converts_local_cents(self):
        for invoices in ([], [self.invoice, self.invoice], [{**self.invoice, "payable": 160}],
                         [{**self.invoice, "currency": "EUR"}], [{**self.invoice, "gross": True}]):
            result = self.resolve(ap_invoices=invoices)
            self.assertEqual((result.status, result.balances), ("UNKNOWN", ()))
        direct = deepcopy(self.application)
        direct["lines"][2].update(currency="USD", amount_doc=50)
        resolved = self.resolve(journal_entries=[self.deposit, direct], ap_invoices=[])
        self.assertEqual(resolved.status, "RESOLVED")
        self.assertEqual(resolved.balances[0].used_doc, 50)
        direct["lines"][2].pop("amount_doc")
        self.assertEqual(self.resolve(journal_entries=[self.deposit, direct], ap_invoices=[]).status, "UNKNOWN")

    def test_ambiguous_deposit_reference_changed_partner_and_invalid_dates_abstain(self):
        duplicate = {**self.deposit, "id": "DEP-SECOND"}
        self.assertEqual(self.resolve(journal_entries=[self.deposit, duplicate, self.application]).status, "UNKNOWN")
        with self.assertRaises(ValueError):
            self.resolve(journal_entries=[self.deposit, self.deposit])
        for changes in (dict(posting_date="invalid"), dict(document_date="2026-02-30")):
            changed = {**self.deposit, **changes}
            self.assertEqual(self.resolve(journal_entries=[changed, self.application]).status, "UNKNOWN")
        changed = deepcopy(self.deposit)
        changed["lines"][0]["partner"] = "OTHER"
        self.assertEqual(self.resolve(journal_entries=[changed, self.application]).status, "UNKNOWN")
        changed = deepcopy(self.application)
        changed["lines"][2]["assignment"] = "DEPOSITREF"
        self.assertEqual(self.resolve(journal_entries=[self.deposit, changed]).status, "UNKNOWN")

    def test_carrying_amount_overconsumption_and_other_vendor_scope(self):
        excess = deepcopy(self.application)
        excess["lines"][2].update(credit=90, amount_doc=90)
        excess["lines"][0]["debit"] = 210
        self.assertEqual(self.resolve(journal_entries=[self.deposit, excess]).status, "UNKNOWN")
        no_other = self.resolve(company="1200", vendors=[dict(id="V-NEW", companies=["1200"])])
        self.assertEqual((no_other.status, no_other.balances), ("RESOLVED", ()))
        other = deepcopy(self.deposit)
        other.update(id="OTHER-DEP", reference="OTHER-REF")
        other["lines"][1]["partner"] = "OTHER"
        other["lines"][0]["assignment"] = "OTHER-PO/10"
        result = self.resolve(journal_entries=[self.deposit, self.application, other])
        self.assertEqual(result.status, "RESOLVED")

    def test_partial_application_order_and_same_day_grouping_do_not_use_ids_for_rounding(self):
        deposit = deepcopy(self.deposit)
        for line in deposit["lines"]:
            line["debit"], line["credit"] = (33, 0) if line["account"] == "40700000" else (0, 33)
        first = deepcopy(self.application)
        first.update(id="Z-FIRST", posting_date="2026-03-02")
        first["lines"][0].update(debit=20, amount_doc=50)
        first["lines"][1].update(credit=17, amount_doc=40)
        first["lines"][2].update(credit=3, currency="USD", amount_doc=10)
        second = deepcopy(first)
        second.update(id="A-SECOND", posting_date="2026-03-03")
        second["lines"][1]["credit"] = 16
        second["lines"][2]["credit"] = 4
        for same_day in (False, True):
            if same_day:
                second["posting_date"] = first["posting_date"]
            observed = []
            for entries in ([deposit, first, second], [second, deposit, first]):
                result = self.resolve(journal_entries=entries, ap_invoices=[])
                observed.append(result)
                self.assertEqual(result.status, "RESOLVED", result.diagnostics)
                self.assertEqual((result.balances[0].used_doc, result.balances[0].used_local), (20, 7))
            self.assertEqual(observed[0], observed[1])

    def test_header_journal_contradiction_is_not_hidden_by_foreign_carrying_rounding(self):
        deposit = deepcopy(self.deposit)
        deposit["lines"][0]["debit"] = 10
        deposit["lines"][1]["credit"] = 10
        application = deepcopy(self.application)
        application["lines"][0].update(debit=10, amount_doc=100)
        application["lines"][1].update(credit=7, amount_doc=70)
        application["lines"][2].update(credit=3, amount_doc=3)
        for amounts in (dict(net=101, tax=0, gross=101, withholding=0, retention=0),
                        dict(net=100, tax=1, gross=101, withholding=0, retention=0),
                        dict(net=100, tax=0, gross=100, withholding=1, retention=0),
                        dict(net=100, tax=0, gross=100, withholding=0, retention=1)):
            linked = {**self.invoice, **amounts, "payable": 70}
            result = self.resolve(journal_entries=[deposit, application], ap_invoices=[linked])
            self.assertEqual((result.status, result.balances), ("UNKNOWN", ()))
            self.assertTrue(any("HEADER_JOURNAL_CONFLICT" in d for d in result.diagnostics))
        linked = {**self.invoice, "net": 100, "tax": 0, "gross": 100, "payable": 70}
        result = self.resolve(journal_entries=[deposit, application], ap_invoices=[linked])
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual((result.balances[0].used_doc, result.balances[0].used_local), (30, 3))


class AdvanceHistorySourceTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("KALMORA_PHASE_ERP"), "original ERP not configured")
    def test_original_advance_balances_are_exhausted_without_source_repair_or_reposting(self):
        erp = Path(os.environ["KALMORA_PHASE_ERP"])
        def rows(stem):
            return [json.loads(line) for line in (erp / f"{stem}.jsonl").read_text().splitlines()]
        journals, orders, vendors, invoices = (rows(stem) for stem in
                                              ("journal_entries", "purchase_orders", "vendors", "ap_invoices"))
        before = deepcopy(journals)
        result = resolve_historical_advances(company="1100", vendor="V100121", as_of="2026-07-31",
                    journal_entries=journals, purchase_orders=orders, vendors=vendors, ap_invoices=invoices,
                    tax_catalog=TaxCatalog(json.loads((erp / "tax_codes.json").read_text())),
                    inventory_complete=True)
        self.assertEqual(result.status, "RESOLVED", result.diagnostics)
        self.assertEqual(len(result.balances), 3)
        self.assertEqual(len(result.reference_entry_errors), 3)
        for balance in result.balances:
            self.assertEqual((balance.used_doc, balance.used_local), (balance.amount_doc, balance.amount_local))
            self.assertEqual((balance.vendor, balance.currency), ("V100121", "USD"))
        manual = resolve_historical_advances(company="1100", vendor="V100003", as_of="2026-07-31",
                    journal_entries=journals, purchase_orders=orders, vendors=vendors, ap_invoices=invoices,
                    tax_catalog=TaxCatalog(json.loads((erp / "tax_codes.json").read_text())), inventory_complete=True)
        self.assertEqual((manual.status, manual.balances), ("UNKNOWN", ()))
        self.assertTrue(any("ADVANCE_ORIGINAL_PO_UNRESOLVED" in d for d in manual.diagnostics))
        self.assertEqual(journals, before)


if __name__ == "__main__":
    unittest.main()
