from copy import deepcopy
from dataclasses import replace
import unittest
import test_ap_journal as journal_fixture
from kalmora.ap_allocation import ConsumptionState, OrderKey, QuantityAllocation, Receipt, ReceiptUsage
from kalmora.ap_journal import (AdvanceApplication, AdvanceBalance, AdvanceState, CreditAdvanceRestoration,
                               CreditReference, InvoiceLineOrder, build_ap_journal)
from kalmora.ap_restoration import ReceiptRestoration, prepare_ap_credit_restoration
from kalmora.facts import Evidence, Fact
from kalmora.money import RateTable
from kalmora.validation import validate_entry


class AdvanceRestorationTests(unittest.TestCase):
    def setup_case(self, treatment="NON_MONETARY", *, carrying=80, amount=100, applied=50):
        self.factory = journal_fixture.APJournalTests()
        self.rates = RateTable([dict(currency="USD", date="2026-07-31", rate="1")])
        self.balance = AdvanceBalance("A", "1100", "V1", "USD", "DEPOSIT", "2026-06-01", "P", amount, carrying)
        original_inputs = self.factory.inputs(net=200, currency="USD", code="SEX", rates=self.rates, doc_id="O")
        coding = dict(original_inputs["valuation"].assignments)["L"]
        original = build_ap_journal(**original_inputs, state=AdvanceState((self.balance,)), invoice_orders=("P",),
                    order_bindings=(InvoiceLineOrder("L", "P", 200, "invoice:PO"),),
                    advances=(AdvanceApplication("A", applied, treatment, "contract:classification", coding if treatment == "NON_MONETARY" else None, "L"),))
        self.source = {**original.journal_entry, "id": "GL-O"}
        number = next(i for i, line in enumerate(self.source["lines"], 1) if line["account"] == "40700000")
        restoration = CreditAdvanceRestoration("A", self.source, number, 25,
                    Fact(applied, Evidence("invoice-original.xml", "explicit_advance_application_doc_cents")),
                    treatment, "contract:classification", "L", coding if treatment == "NON_MONETARY" else None,
                    Fact("A", Evidence("contract", "advance")), Fact(treatment, Evidence("contract", "treatment")))
        self.arguments = {**self.factory.inputs(net=100, currency="USD", code="SEX", rates=self.rates, doc_id="C1"),
                "document_type": "CREDIT_NOTE", "state": original.state,
                "credit_references": (CreditReference("L", self.source, 1),), "credit_restorations": (restoration,)}

    def test_partial_then_final_restoration_preserves_carrying_and_original_limits(self):
        for treatment in ("NON_MONETARY", "MONETARY"):
            self.setup_case(treatment)
            before = deepcopy({key: value for key, value in self.arguments.items() if key != "rates"})
            first = prepare_ap_credit_restoration(journal_arguments=self.arguments, consumption=ConsumptionState())
            self.assertEqual(validate_entry(first.journal.journal_entry), [])
            balance, = first.journal.state.balances
            self.assertEqual((balance.used_doc, balance.used_local), (25, 20))
            advance = next(line for line in first.journal.journal_entry["lines"] if line["account"] == "40700000")
            self.assertEqual((advance["amount_doc"], advance["debit"], advance["partner"]), (25, 20, "V1"))
            self.assertEqual(first.journal.payable_doc, 75)
            second = prepare_ap_credit_restoration(journal_arguments={**self.arguments,
                          **self.factory.inputs(net=100, currency="USD", code="SEX", rates=self.rates, doc_id="C2"),
                          "state": first.journal.state}, consumption=ConsumptionState())
            self.assertEqual((second.journal.state.balances[0].used_doc, second.journal.state.balances[0].used_local), (0, 0))
            self.assertEqual(next(credit.used_doc for credit in second.journal.state.credits if credit.bucket.startswith("advance:")), 50)
            self.assertEqual({key: value for key, value in self.arguments.items() if key != "rates"}, before)
            with self.assertRaises(ValueError):
                prepare_ap_credit_restoration(journal_arguments={**self.arguments, "state": second.journal.state}, consumption=ConsumptionState())

    def test_fully_prepaid_original_can_restore_without_inventing_supplier_capacity(self):
        self.setup_case(amount=200, carrying=160, applied=200)
        self.assertFalse(any(line["account"] == "41000000" for line in self.source["lines"]))
        request = replace(self.arguments["credit_restorations"][0], amount_doc=100)
        result = prepare_ap_credit_restoration(journal_arguments={**self.arguments, "credit_restorations": (request,)}, consumption=ConsumptionState())
        self.assertEqual((result.journal.payable_doc, result.journal.payable_local), (0, 0))
        self.assertFalse(any(line["account"] == "41000000" for line in result.journal.journal_entry["lines"]))
        self.assertEqual((result.journal.state.balances[0].used_doc, result.journal.state.balances[0].used_local), (100, 80))
        from kalmora.ap_credit_sources import CreditOriginalCatalog
        row = dict(company="1100", vendor="V1", currency="USD", doc_id="O", number=self.source["reference"],
                   kind="invoice", issue_date=self.source["document_date"], journal_entry=self.source["id"], payable=0)
        original = CreditOriginalCatalog(invoices=[row], journal_entries=[self.source], inventory_complete=True).resolve(
            company="1100", vendor="V1", currency="USD", invoice_date="2026-07-31",
            original_number=Fact(row["number"], Evidence("credit.xml", "original_number")))
        self.assertEqual((original.status, original.reconciliation_account), ("RESOLVED", None))
        row["payable"] = None
        self.assertEqual(CreditOriginalCatalog(invoices=[row], journal_entries=[self.source], inventory_complete=True).resolve(
            company="1100", vendor="V1", currency="USD", invoice_date="2026-07-31", original_number=Fact(row["number"], Evidence("credit.xml", "original_number"))).status,
            "CONFLICT")

    def test_explicit_document_split_handles_locally_booked_foreign_407(self):
        self.setup_case()
        source = deepcopy(self.source)
        line = next(line for line in source["lines"] if line["account"] == "40700000")
        line.update(currency="EUR", amount_doc=line["credit"])
        request = replace(self.arguments["credit_restorations"][0], original_entry=source)
        result = prepare_ap_credit_restoration(journal_arguments={**self.arguments,
                        "credit_references": (CreditReference("L", source, 1),), "credit_restorations": (request,)},
                        consumption=ConsumptionState())
        self.assertEqual(result.journal.state.balances[0].used_doc, 25)

    def test_unknown_changed_original_classification_scope_and_excess_abort_without_mutation(self):
        self.setup_case()
        request = self.arguments["credit_restorations"][0]
        before = deepcopy({key: value for key, value in self.arguments.items() if key != "rates"})
        for change in (dict(advance_id="OTHER"), dict(amount_doc=51), dict(application_doc=Fact(None, Evidence("src", "unknown"))),
                       dict(application_doc=Fact(49, Evidence("src", "different"))), dict(treatment="UNKNOWN"),
                       dict(line_id="OTHER"), dict(cost_assignment=None)):
            with self.assertRaises((ValueError, TypeError)):
                prepare_ap_credit_restoration(journal_arguments={**self.arguments, "credit_restorations": (replace(request, **change),)},
                                              consumption=ConsumptionState())
        self.assertEqual({key: value for key, value in self.arguments.items() if key != "rates"}, before)

    def test_classification_cannot_reverse_the_original_cost_and_fx_families(self):
        for original_kind, other_kind in (("NON_MONETARY", "MONETARY"), ("MONETARY", "NON_MONETARY")):
            self.setup_case(original_kind)
            request = self.arguments["credit_restorations"][0]
            coding = dict(self.arguments["valuation"].assignments)["L"] if other_kind == "NON_MONETARY" else None
            changed = replace(request, treatment=other_kind, cost_assignment=coding,
                              classification_treatment=Fact(other_kind, Evidence("contract", "treatment")))
            with self.assertRaisesRegex(ValueError, "original adjustment"):
                prepare_ap_credit_restoration(journal_arguments={**self.arguments, "credit_restorations": (changed,)}, consumption=ConsumptionState())
            with self.assertRaisesRegex(ValueError, "classification Fact"):
                prepare_ap_credit_restoration(journal_arguments={**self.arguments,
                    "credit_restorations": (replace(request, classification_treatment=None),)}, consumption=ConsumptionState())

    def test_same_deposit_number_different_po_cannot_restore_another_advance(self):
        self.setup_case()
        current = self.arguments["state"]
        other = replace(current.balances[0], advance_id="OTHER", po="OTHER-P")
        state = replace(current, balances=(*current.balances, other))
        request = self.arguments["credit_restorations"][0]
        changed = replace(request, advance_id="OTHER", classification_advance=Fact("OTHER", Evidence("contract", "advance")))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            prepare_ap_credit_restoration(journal_arguments={**self.arguments, "state": state, "credit_restorations": (changed,)}, consumption=ConsumptionState())
        facts = lambda value, field: Fact(value, Evidence(request.application_doc.evidence.document, field))
        linked = replace(request, application_original=facts(self.source["id"], "original_application"),
                         application_advance=facts("A", "advance"), application_po=facts("P", "po"))
        result = prepare_ap_credit_restoration(journal_arguments={**self.arguments, "state": state, "credit_restorations": (linked,)}, consumption=ConsumptionState())
        amounts = {balance.advance_id: balance.used_doc for balance in result.journal.state.balances}
        self.assertEqual(amounts, {"A": 25, "OTHER": 50})
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            prepare_ap_credit_restoration(journal_arguments={**self.arguments, "state": state,
                "credit_restorations": (replace(linked, application_po=facts("OTHER-P", "po")),)}, consumption=ConsumptionState())

    def test_zero_original_delta_never_supplies_missing_classification(self):
        self.setup_case(carrying=100)
        request = self.arguments["credit_restorations"][0]
        with self.assertRaisesRegex(ValueError, "classification Fact"):
            prepare_ap_credit_restoration(journal_arguments={**self.arguments,
                "credit_restorations": (replace(request, classification_advance=None),)}, consumption=ConsumptionState())
        result = prepare_ap_credit_restoration(journal_arguments=self.arguments, consumption=ConsumptionState())
        self.assertEqual(result.journal.state.balances[0].used_doc, 25)

    def test_grouped_day_carry_rounding_cannot_restore_unobserved_local_cent(self):
        self.setup_case(carrying=33, applied=20)
        # An earlier application can carry 3 cents while cumulative release of
        # its 10 doc cents now needs 4. No local cent is reassigned from another.
        source = deepcopy(self.source)
        line = next(line for line in source["lines"] if line["account"] == "40700000")
        line.update(amount_doc=10, credit=3)
        supplier = next(line for line in source["lines"] if line["account"] == "41000000")
        supplier["credit"] += 4
        request = replace(self.arguments["credit_restorations"][0], original_entry=source, amount_doc=10,
                          application_doc=Fact(10, Evidence("original", "application")))
        with self.assertRaisesRegex(ValueError, "carrying cents"):
            prepare_ap_credit_restoration(journal_arguments={**self.arguments, "credit_references": (CreditReference("L", source, 1),),
                               "credit_restorations": (request,)}, consumption=ConsumptionState())


class ReceiptRestorationTests(unittest.TestCase):
    def setUp(self):
        self.factory = journal_fixture.APJournalTests()
        original = self.factory.build(inputs=self.factory.inputs(net=100, code="SEX", doc_id="O"))
        self.source = {**original.journal_entry, "id": "GL-O"}
        self.source["lines"][0].update(account="40090000", partner="V1", cost_center=None, assignment="P/10")
        self.order = OrderKey("1100", "V1", "EUR", "P", 10)
        self.receipt = Receipt("R", self.order, 1000, "EA", "2026-07-01")
        self.consumption = ConsumptionState((ReceiptUsage(self.order, "R", 700),), (("1100", "V1", "EUR", "O"),))
        data = self.factory.inputs(net=40, code="SEX", doc_id="C1")
        component = replace(data["valuation"].components[0], kind="GR_IR", account="40090000", partner="V1", cost_center=None, order=self.order)
        data["valuation"] = replace(data["valuation"], components=(component,))
        self.arguments = {**data, "document_type": "CREDIT_NOTE", "credit_references": (CreditReference("L", self.source, 1),)}
        self.request = ReceiptRestoration(Fact("L", Evidence("credit.xml", "line")), Fact("O", Evidence("credit.xml", "original")),
                    Fact(400, Evidence("credit.xml", "returned_quantity_milli")), self.source, self.receipt,
                    QuantityAllocation("ORIGINAL-L", self.order, "R", 600), Evidence("original-allocation", "receipt-portions"),
                    dict(company="1100", vendor="V1", currency="EUR", doc_id="O", journal_entry="GL-O", kind="invoice",
                         number=self.source["reference"], issue_date=self.source["document_date"]), Evidence("AP-register", "original_link"),
                    Fact("O", Evidence("original-allocation", "invoice_id")))

    def test_receipt_restoration_returns_tentative_state_and_preserves_original_events(self):
        before = deepcopy((self.arguments, self.consumption))
        first = prepare_ap_credit_restoration(journal_arguments=self.arguments, consumption=self.consumption, receipt_restorations=(self.request,))
        self.assertEqual(first.consumption.usages[0].quantity_milli, 300)
        self.assertEqual(first.consumption.invoices, self.consumption.invoices)
        self.assertEqual(first.restoration_state.usages[0].used_milli, 400)
        self.assertEqual((self.arguments, self.consumption), before)
        # Current usage still includes another invoice's 100 milli: cannot use
        # it to exceed this original allocation's remaining 200 milli.
        retry = {**self.arguments, "doc_id": "C2", "state": first.journal.state}
        for field in ("valuation", "tax", "withholding"):
            retry[field] = replace(retry[field], scope=replace(retry[field].scope, invoice_id="C2"))
        with self.assertRaisesRegex(ValueError, "original or committed"):
            prepare_ap_credit_restoration(journal_arguments=retry, consumption=first.consumption,
                    restoration_state=first.restoration_state, receipt_restorations=(replace(self.request, quantity_milli=Fact(300, self.request.quantity_milli.evidence)),))

    def test_other_consumed_invoice_cannot_supply_a_same_po_original_link(self):
        state = replace(self.consumption, invoices=(*self.consumption.invoices, ("1100", "V1", "EUR", "OTHER")))
        request = replace(self.request, original_invoice_id=Fact("OTHER", self.request.original_invoice_id.evidence))
        with self.assertRaisesRegex(ValueError, "AP-to-GL"):
            prepare_ap_credit_restoration(journal_arguments=self.arguments, consumption=state, receipt_restorations=(request,))
        request = replace(self.request, allocation_invoice_id=Fact("OTHER", self.request.allocation_invoice_id.evidence))
        with self.assertRaisesRegex(ValueError, "same AP invoice"):
            prepare_ap_credit_restoration(journal_arguments=self.arguments, consumption=state, receipt_restorations=(request,))

    def test_missing_unknown_quantity_po_or_original_allocation_cannot_release_receipts(self):
        for change in (dict(quantity_milli=Fact(None, self.request.quantity_milli.evidence)),
                       dict(quantity_milli=Fact(0, self.request.quantity_milli.evidence)),
                       dict(original_invoice_id=Fact("OTHER", self.request.original_invoice_id.evidence)),
                       dict(quantity_milli=Fact(100, Evidence("other.xml", "quantity"))),
                       dict(original_allocation=replace(self.request.original_allocation, receipt_id="OTHER"))):
            with self.assertRaises((ValueError, TypeError)):
                prepare_ap_credit_restoration(journal_arguments=self.arguments, consumption=self.consumption,
                                              receipt_restorations=(replace(self.request, **change),))
        with self.assertRaises(ValueError):
            prepare_ap_credit_restoration(journal_arguments=self.arguments, consumption=self.consumption,
                                          receipt_restorations=(self.request, self.request))
