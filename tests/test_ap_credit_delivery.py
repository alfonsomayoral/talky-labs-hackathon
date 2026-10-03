"""Real journal/output boundary for credit restoration, including failed delivery."""
from dataclasses import replace
import unittest

from kalmora.ap_allocation import ConsumptionState
from kalmora.ap_credit_delivery import build_ap_credit_delivery
from kalmora.ap_journal import (
    AdvanceApplication, AdvanceBalance, AdvanceState, CreditAdvanceRestoration,
    CreditReference, InvoiceLineOrder, build_ap_journal,
)
from kalmora.ap_output import APHeader, validate_ap_row
from kalmora.ap_restoration import ReceiptRestorationState
from kalmora.ap_tax import TaxCatalog
from kalmora.facts import Evidence, Fact
from test_ap_tax import source_catalog


class CreditDeliveryTests(unittest.TestCase):
    def setUp(self):
        from test_ap_journal import APJournalTests
        factories = APJournalTests()
        balance = AdvanceBalance("ADV-1", "1100", "V1", "EUR", "DEP-1",
                                 "2026-06-01", "PO-1", 3000, 3000)
        original_inputs = factories.inputs(doc_id="ORIGINAL", invoice_number="INV-ORIGINAL")
        original = build_ap_journal(**original_inputs, state=AdvanceState((balance,)),
            advances=(AdvanceApplication("ADV-1", 3000, "MONETARY", "contract.pdf:treatment", line_id="L"),),
            invoice_orders=("PO-1",), order_bindings=(InvoiceLineOrder("L", "PO-1", 10000, "invoice.pdf:PO"),))
        entry = dict(original.journal_entry, id="ORIGINAL-JE")
        advance_line = next(line.get("line", index) for index, line in enumerate(entry["lines"], 1)
                            if line["account"] == "40700000")
        self.arguments = dict(factories.inputs(net=5000, doc_id="CREDIT", invoice_number="CN-1"),
            document_type="CREDIT_NOTE", state=original.state,
            credit_references=(CreditReference("L", entry, 1),),
            credit_restorations=(CreditAdvanceRestoration("ADV-1", entry, advance_line, 1500,
                Fact(3000, Evidence("invoice.pdf", "advance_application")), "MONETARY", "contract.pdf:treatment", "L",
                classification_advance=Fact("ADV-1", Evidence("contract.pdf", "advance")),
                classification_treatment=Fact("MONETARY", Evidence("contract.pdf", "treatment"))),))
        self.header = APHeader("1100", "V1", "CN-1", "2026-07-31", "EUR", 5000, 1050, 6050, 0, 0, 4550)
        self.lines = (dict(amount=5000, account="62300000", cost_center="CC", wbs=None,
                           tax_code="S21", po=None, po_item=None),)
        self.consumption = ConsumptionState()
        self.sidecar = ReceiptRestorationState()
        self.catalog = TaxCatalog(source_catalog())

    def deliver(self, **changes):
        values = dict(journal_arguments=self.arguments, header=self.header, lines=self.lines,
            consumption=self.consumption, restoration_state=self.sidecar,
            evidence=(Evidence("credit.xml", "original_and_restoration"),), tax_catalog=self.catalog)
        values.update(changes)
        return build_ap_credit_delivery(**values)

    def test_real_restoration_and_output_validate_together_and_row_is_immutable(self):
        result = self.deliver()
        self.assertEqual(validate_ap_row(result.row, tax_catalog=self.catalog), ())
        self.assertEqual(result.advances.balances[0].used_doc, 1500)
        self.assertEqual(self.arguments["state"].balances[0].used_doc, 3000)
        self.assertEqual(result.consumption, self.consumption)
        self.assertEqual(result.restoration_state, self.sidecar)
        changed = result.row
        changed["journal_entry"]["lines"][0]["credit"] = 1
        self.assertEqual(result.row["journal_entry"]["lines"][0]["credit"], 5000)

    def test_failed_header_and_coding_do_not_restore_or_reserve_credit(self):
        for changes in (dict(header=replace(self.header, payable=4551)),
                        dict(lines=(dict(self.lines[0], account="62900000"),))):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.deliver(**changes)
            self.assertEqual(self.arguments["state"].balances[0].used_doc, 3000)
            self.assertEqual(self.arguments["state"].credits, ())
            self.assertEqual(self.sidecar.usages, ())
        self.assertEqual(self.deliver().advances.balances[0].used_doc, 1500)

    def test_returned_state_rejects_duplicate_credit_before_new_restoration(self):
        result = self.deliver()
        with self.assertRaisesRegex(ValueError, "already"):
            self.deliver(journal_arguments=dict(self.arguments, state=result.advances))
        self.assertEqual(result.advances.balances[0].used_doc, 1500)

    def test_scope_and_nonposting_are_rejected_without_any_journal(self):
        for changes in (dict(header=replace(self.header, vendor_id="OTHER")),
                        dict(journal_arguments=dict(self.arguments, decision="HOLD"))):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.deliver(**changes)
        self.assertEqual(self.arguments["state"].balances[0].used_doc, 3000)

    def test_invalid_delivery_cannot_release_an_evidenced_original_receipt(self):
        from test_ap_restoration import ReceiptRestorationTests
        case = ReceiptRestorationTests()
        case.setUp()
        values = dict(journal_arguments=case.arguments,
            header=APHeader("1100", "V1", "INV-1", "2026-07-31", "EUR", 40, 0, 40, 0, 0, 40),
            lines=(dict(amount=40, account="62300000", cost_center="CC", wbs=None,
                        tax_code="SEX", po="P", po_item=10),),
            consumption=case.consumption, receipt_restorations=(case.request,),
            evidence=(Evidence("credit.xml", "original_and_returned_quantity"),), tax_catalog=self.catalog)
        with self.assertRaises(ValueError):
            build_ap_credit_delivery(**dict(values, header=replace(values["header"], payable=41)))
        self.assertEqual(case.consumption.usages[0].quantity_milli, 700)
        result = build_ap_credit_delivery(**values)
        self.assertEqual(result.consumption.usages[0].quantity_milli, 300)
        self.assertEqual(result.restoration_state.usages[0].used_milli, 400)
        self.assertEqual(case.consumption.usages[0].quantity_milli, 700)


if __name__ == "__main__":
    unittest.main()
