from copy import deepcopy
from dataclasses import replace
import unittest
import test_ap_journal as journal_fixture
from kalmora.ap_credit_history import HistoricalCreditInput, resolve_historical_credits
from kalmora.ap_opening_state import resolve_ap_opening_state
from kalmora.ap_journal import CreditReference, build_ap_journal
from kalmora.ap_tax import TaxCatalog
from kalmora.facts import Evidence, Fact
from test_ap_tax import source_catalog


class CreditHistoryTests(unittest.TestCase):
    def setUp(self):
        fixture = journal_fixture.APJournalTests()
        original = fixture.build(inputs=fixture.inputs(net=10000, doc_id="O", invoice_number="ORIGINAL"))
        self.original = {**original.journal_entry, "id": "GL-O"}
        self.data = fixture.inputs(net=2000, doc_id="C1", invoice_number="CN1")
        self.references = (CreditReference("L", self.original, 1),)
        actual = build_ap_journal(**self.data, document_type="CREDIT_NOTE", credit_references=self.references)
        self.credit = {**actual.journal_entry, "id": "GL-C1"}
        def row(ident, entry_id, number, kind, net, tax, payable):
            return dict(company="1100", vendor="V1", currency="EUR", doc_id=ident, journal_entry=entry_id, number=number,
                        kind=kind, issue_date="2026-07-31", posted_on="2026-07-31", decision="POST",
                        net=net, tax=tax, gross=net+tax, withholding=0, retention=0, payable=payable)
        self.rows = [row("O", "GL-O", "ORIGINAL", "invoice", 10000, 2100, 12100),
                     row("C1", "GL-C1", "CN1", "credit_note", 2000, 420, 2420)]
        self.observation = HistoricalCreditInput(Fact("GL-C1", Evidence("erp", "credit_journal")),
                     Fact("ORIGINAL", Evidence("credit.xml", "original_number")),
                     self.data["valuation"], self.data["tax"], self.data["withholding"], self.references,
                     credit_number=Fact("CN1", Evidence("credit.xml", "number")))
        self.options = dict(company="1100", vendor="V1", currency="EUR", as_of=Fact("2026-07-31", Evidence("run", "cutoff")),
                 inventory_complete=Fact(True, Evidence("manifest", "full_history")), inputs=(self.observation,),
                 ap_invoices=self.rows, journal_entries=[self.original, self.credit])

    def test_real_factories_corroborate_positive_usage_and_opening_coverage(self):
        before = deepcopy(self.options)
        result = resolve_historical_credits(**self.options)
        self.assertEqual(result.status, "RESOLVED", result.diagnostics)
        self.assertEqual(result.covered_entries, (("1100", "GL-C1"),))
        self.assertEqual(next(b.used_doc for b in result.balances if b.bucket == "line:1"), 2000)
        opening = resolve_ap_opening_state(**{key: value for key, value in self.options.items() if key != "inputs"},
                     historical_credit_inputs=self.options["inputs"], purchase_orders=[], vendors=[dict(id="V1", companies=["1100"])],
                     tax_catalog=TaxCatalog(source_catalog()))
        self.assertEqual(opening.status, "RESOLVED", opening.diagnostics)
        self.assertEqual(opening.state.credits, result.balances)
        self.assertEqual(opening.state.events, ())
        self.assertEqual(self.options, before)

    def test_uncovered_history_stays_unknown_and_positive_baseline_limits_next_credit(self):
        result = resolve_historical_credits(**self.options)
        fixture = journal_fixture.APJournalTests()
        from kalmora.ap_journal import AdvanceState
        with self.assertRaises(ValueError):
            build_ap_journal(**fixture.inputs(net=9000, doc_id="C2"), document_type="CREDIT_NOTE",
                             credit_references=self.references, state=AdvanceState(credits=result.balances))
        extra = {**self.credit, "id": "UNOBSERVED"}
        opening = resolve_ap_opening_state(**{key: value for key, value in self.options.items() if key not in {"inputs", "journal_entries"}},
                 journal_entries=[self.original, self.credit, extra], historical_credit_inputs=self.options["inputs"],
                 purchase_orders=[], vendors=[dict(id="V1", companies=["1100"])], tax_catalog=TaxCatalog(source_catalog()))
        self.assertEqual((opening.status, opening.state), ("UNKNOWN", None))

    def test_missing_original_gl_changes_clock_duplicates_and_header_conflicts_abstain(self):
        for changes in ({"inputs": (replace(self.observation, original_number=Fact("ABSENT", Evidence("credit.xml", "original_number"))),)},
                        {"inputs": (self.observation, self.observation)},
                        {"journal_entries": [self.original]},
                        {"ap_invoices": [self.rows[0], {**self.rows[1], "payable": 2421}]},
                        {"ap_invoices": [self.rows[0], {**self.rows[1], "posted_on": "2026-07-30"}]},
                        {"journal_entries": [self.original, {**self.credit, "posting_date": "invalid"}]},
                        {"inventory_complete": Fact(False, Evidence("manifest", "partial"))}):
            result = resolve_historical_credits(**{**self.options, **changes})
            self.assertEqual((result.status, result.balances, result.covered_entries), ("UNKNOWN", (), ()), result.diagnostics)
        changed = deepcopy(self.credit)
        changed["lines"][0]["cost_center"] = "OTHER"
        self.assertEqual(resolve_historical_credits(**{**self.options, "journal_entries": [self.original, changed]}).status, "UNKNOWN")

    def test_cross_document_original_reference_cannot_become_a_link_by_matching_amounts(self):
        unrelated = replace(self.observation, original_number=Fact("ORIGINAL", Evidence("other-credit.xml", "original_number")))
        result = resolve_historical_credits(**{**self.options, "inputs": (unrelated,)})
        self.assertEqual((result.status, result.balances), ("UNKNOWN", ()))
        self.assertIn("HISTORICAL_CREDIT_ORIGINAL_ASSOCIATION_UNKNOWN", result.diagnostics)

    def test_generators_only_consumed_once(self):
        result = resolve_historical_credits(**{**self.options,
            "journal_entries": (row for row in self.options["journal_entries"]),
            "ap_invoices": (row for row in self.rows), "inputs": iter([self.observation])})
        self.assertEqual(result.status, "RESOLVED", result.diagnostics)
