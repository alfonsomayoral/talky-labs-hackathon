"""Synthetic real-engine AP pipelines through export; no reference journals."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from kalmora.ap_allocation import (
    InvoiceQuantityLine, OrderKey, OrderLine, OrderPortion, Receipt, allocate_receipts,
)
from kalmora.ap_chronology import KINDS, invoice_state
from kalmora.ap_journal import (
    AdvanceApplication, AdvanceBalance, AdvanceState, ApprovedAdvanceOrder, CreditAdvanceRestoration, CreditReference, InvoiceLineOrder,
    build_ap_journal, build_down_payment_request,
)
from kalmora.ap_output import APHeader, build_ap_row, validate_ap_row, write_ap_jsonl
from kalmora.ap_payment import ACTIONS, apply_notice, resolve_payment
from kalmora.ap_tax import TaxCatalog, TaxLine, calculate_ap_tax
from kalmora.ap_valuation import CostAssignment, OrderPrice, ValuationLine, value_ap_lines
from kalmora.ap_withholding import (
    ContractGuarantee, WithholdingBase, WithholdingCatalog, calculate_ap_withholdings,
)
from kalmora.evaluation.structure import check_structure
from kalmora.facts import Evidence, Fact
from kalmora.model.ap_event import ApEvent
from kalmora.model.ap_scope import ApScope
from kalmora.money import RateTable
from kalmora.validation import validate_entry
from test_ap_tax import source_catalog
from test_ap_withholding import withholding_source


class APOutputIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = TaxCatalog(source_catalog())
        self.withholding_catalog = WithholdingCatalog(withholding_source())

    def invoice(self, doc_id, *, company="1100", currency="EUR", code="S21",
                net=10000, account="62300000", cost_center="CC1", wbs=None,
                codes=(), guarantee=None, decision="POST", rates=None,
                document_type="INVOICE", allocation=None, prices=(), quantity=None,
                coded_lines=None, payment_block=None, **journal_options):
        """Keep every component's document/vendor/date scope identical."""
        country = {"1100": "ES", "2100": "PT", "3100": "MX"}[company]
        number, day = f"INV-{doc_id}", "2026-07-31"
        cost = CostAssignment(company, account, cost_center, wbs)
        valuation = value_ap_lines(
            company=company, vendor="V1", currency=currency, invoice_id=doc_id,
            invoice_date=day, decision=decision, gr_ir_account="40090000",
            lines=[ValuationLine("L", net, cost, quantity)], allocation=allocation,
            prices=prices, rates=rates,
        )
        tax = calculate_ap_tax(
            company=company, country=country, vendor="V1", currency=currency,
            invoice_id=doc_id, invoice_date=day, decision=decision,
            lines=[TaxLine("L", net, code, account=account,
                           cost_center=cost_center, wbs=wbs)],
            catalog=self.catalog, rates=rates,
        )
        deductions = calculate_ap_withholdings(
            company=company, country=country, vendor="V1", currency=currency,
            invoice_id=doc_id, invoice_date=day, invoice_number=number,
            decision=decision, bases=[WithholdingBase("L", net, codes)],
            guarantee=guarantee, catalog=self.withholding_catalog, rates=rates,
        )
        result = build_ap_journal(
            company=company, vendor="V1", currency=currency, doc_id=doc_id,
            invoice_number=number, invoice_date=day, posting_date=day,
            decision=decision, document_type=document_type,
            reconciliation_account="41000000", valuation=valuation, tax=tax,
            withholding=deductions, rates=rates, **journal_options,
        )
        header = APHeader(company, "V1", number, day, currency, tax.net_doc,
                          tax.tax_doc, tax.gross_doc, deductions.withholding_doc,
                          deductions.retention_doc, result.payable_doc)
        lines = coded_lines if coded_lines is not None else [
            dict(amount=net, account=account, cost_center=cost_center, wbs=wbs,
                 tax_code=code, po=None, po_item=None)
        ]
        row = build_ap_row(
            doc_id=doc_id, document_type=document_type, decision=decision,
            header=header, lines=lines, journal_entry=result.journal_entry,
            payment_block=payment_block, tax_catalog=self.catalog,
        )
        self.assertEqual(validate_entry(result.journal_entry), [])
        self.assertEqual(check_structure({"ap": [row]}), [])
        return row, result

    def export(self, rows):
        """Exercise complete inventory and validate the serialized M0 shape."""
        ids = [row["doc_id"] for row in rows]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ap.jsonl"
            write_ap_jsonl(path, reversed(rows), expected_doc_ids=ids,
                           tax_catalog=self.catalog)
            payload = path.read_bytes()
            restored = [json.loads(line) for line in payload.splitlines()]
            self.assertEqual(check_structure({"ap": restored}), [])
            self.assertEqual(restored, sorted(rows, key=lambda row: row["doc_id"]))
            # A coverage failure cannot overwrite the complete deliverable.
            with self.assertRaises(ValueError):
                write_ap_jsonl(path, rows[:-1], expected_doc_ids=ids,
                               tax_catalog=self.catalog, overwrite=True)
            self.assertEqual(path.read_bytes(), payload)
        return restored

    def test_es_pt_tax_treatments_and_mx_deductions_export_real_journals(self):
        rows = []
        cases = [
            ("ES-INPUT", "1100", "EUR", "S21", (), None, 2100, 12100),
            ("ES-ND", "1100", "EUR", "SND", (), None, 2100, 12100),
            ("ES-REVERSE", "1100", "EUR", "SISP", (), None, 0, 10000),
            ("PT-INPUT", "2100", "EUR", "P23", (), None, 2300, 12300),
            ("PT-REVERSE", "2100", "EUR", "PAUT", (), None, 0, 10000),
            ("MX", "3100", "MXN", "M16", ("MXISR10", "MXIVAR"),
             ContractGuarantee(10000, "CONTRACT-MX"), 1600, 9033),
        ]
        for doc, company, currency, code, codes, guarantee, quota, payable in cases:
            with self.subTest(code=code):
                row, result = self.invoice(doc, company=company, currency=currency,
                                           code=code, codes=codes, guarantee=guarantee)
                self.assertEqual((row["tax"], row["payable"]), (quota, payable))
                accounts = [line["account"] for line in result.journal_entry["lines"]]
                if code == "SND":
                    self.assertNotIn("47200000", accounts)
                    self.assertEqual(sum(line["debit"] for line in result.journal_entry["lines"]
                                         if line["account"] == "62300000"), 12100)
                if "REVERSE" in doc:
                    self.assertIn("47210000", accounts)
                    self.assertIn("47710000", accounts)
                if doc == "MX":
                    self.assertEqual((row["withholding"], row["retention"]), (2067, 500))
                rows.append(row)
        self.export(rows)

    def test_credit_uses_original_asset_tax_and_partial_amount_before_export(self):
        original_row, original = self.invoice("ORIGINAL", net=20000, account="21300000",
                                               cost_center=None, wbs="OB1")
        source = {**deepcopy(original.journal_entry), "id": "ORIGINAL-JOURNAL"}
        before = deepcopy(source)
        credit, result = self.invoice(
            "CREDIT", net=5000, account="21300000", cost_center=None, wbs="OB1",
            document_type="CREDIT_NOTE", credit_references=[CreditReference("L", source, 1)],
        )
        self.assertEqual((credit["net"], credit["tax"], credit["payable"]), (5000, 1050, 6050))
        self.assertEqual(result.journal_entry["lines"][0]["credit"], 5000)
        self.assertEqual(source, before)
        self.export([original_row, credit])

    def fully_prepaid(self):
        state = AdvanceState(balances=(AdvanceBalance(
            "HIST", "1100", "V1", "EUR", "DEP-NUM", "2026-06-01", "PO1", 10000, 10000),))
        row, result = self.invoice(
            "PREPAID", code="SEX", state=state, invoice_orders=("PO1",),
            order_bindings=(InvoiceLineOrder("L", "PO1", 10000, "INVOICE-LINE-PO"),),
            advances=(AdvanceApplication("HIST", 10000, "MONETARY", "CONTRACT", line_id="L"),),
            coded_lines=[dict(amount=10000, account="62300000", cost_center="CC1",
                             tax_code="SEX", po="PO1", po_item=10)],
        )
        return row, result, state

    def test_fully_prepaid_invoice_and_evidenced_credit_export_without_supplier_leg(self):
        row, original, state = self.fully_prepaid()
        source = {**deepcopy(original.journal_entry), "id": "ORIGINAL-PREPAID"}
        before = deepcopy(source)
        advance_line = next(index for index, line in enumerate(source["lines"], 1)
                            if line["account"] == "40700000")
        restoration = CreditAdvanceRestoration(
            "HIST", source, advance_line, 10000,
            Fact(10000, Evidence("original.xml", "explicit_application_doc_cents")),
            "MONETARY", "CONTRACT", "L",
            classification_advance=Fact("HIST", Evidence("contract", "advance")),
            classification_treatment=Fact("MONETARY", Evidence("contract", "treatment")),
        )
        credit, restored = self.invoice(
            "PREPAID-CREDIT", code="SEX", document_type="CREDIT_NOTE", state=original.state,
            credit_references=(CreditReference("L", source, 1),),
            credit_restorations=(restoration,),
        )
        for exported in (row, credit):
            self.assertEqual(exported["payable"], 0)
            self.assertFalse(any(line["account"] in {"40000000", "41000000", "40300000"}
                                 for line in exported["journal_entry"]["lines"]))
        self.assertEqual((state.balances[0].used_doc, original.state.balances[0].used_doc,
                          restored.state.balances[0].used_doc), (0, 10000, 0))
        self.assertEqual(source, before)
        self.export([row, credit])

    def test_zero_payable_does_not_bypass_conservation_or_supplier_scope(self):
        prepaid, _, _ = self.fully_prepaid()
        normal, _ = self.invoice("UNPAID", code="SEX")
        no_supplier = deepcopy(normal)
        no_supplier["journal_entry"]["lines"] = [line for line in no_supplier["journal_entry"]["lines"]
                                                  if line["account"] != "41000000"]
        self.assertIn("exactly one scoped supplier line required", validate_ap_row(no_supplier, tax_catalog=self.catalog))
        # A forged zero header remains invalid even if the journal is balanced.
        forged = deepcopy(normal)
        forged["payable"] = 0
        self.assertIn("payable does not conserve gross less deductions and applied advances",
                      validate_ap_row(forged, tax_catalog=self.catalog))
        contradicted = deepcopy(prepaid)
        contradicted["journal_entry"]["lines"].append(
            dict(account="41000000", partner="V1", debit=0, credit=1, currency="EUR", amount_doc=0))
        self.assertIn("supplier side/document payable differs from header",
                      validate_ap_row(contradicted, tax_catalog=self.catalog))
        wrong_currency = deepcopy(prepaid)
        wrong_currency["journal_entry"]["lines"][0]["currency"] = "USD"
        self.assertIn("journal line currency is outside invoice/local scope",
                      validate_ap_row(wrong_currency, tax_catalog=self.catalog))

    def test_foreign_request_then_nonmonetary_application_preserves_historical_cost(self):
        rates = RateTable([
            {"currency": "USD", "date": "2026-06-01", "rate": "2"},
            {"currency": "USD", "date": "2026-07-31", "rate": "1"},
        ])
        request = build_down_payment_request(
            company="1100", vendor="V1", vendor_country="CN",
            vendor_master={"id": "V1", "country": "CN", "companies": ["1100"]},
            currency="USD", doc_id="DEPOSIT", invoice_number="DEP-1",
            invoice_date="2026-06-01", posting_date="2026-06-01", amount_doc=10000,
            decision="POST", order=ApprovedAdvanceOrder("1100", "V1", "USD", "PO1", True, "APPROVED"),
            rates=rates,
        )
        request_row = build_ap_row(
            doc_id="DEPOSIT", document_type="DOWN_PAYMENT_REQUEST", decision="POST",
            header=APHeader("1100", "V1", "DEP-1", "2026-06-01", "USD", 10000, 0, 10000, 0, 0, 10000),
            lines=[dict(amount=10000, account="40700000", tax_code="SEX", po="PO1", po_item=10)],
            journal_entry=request.journal_entry, tax_catalog=self.catalog,
        )
        row, applied = self.invoice(
            "IMPORT", currency="USD", code="SEX", net=50000, account="21300000", rates=rates,
            state=request.state, invoice_orders=("PO1",),
            order_bindings=[InvoiceLineOrder("L", "PO1", 50000, "EXPLICIT-PO-BINDING")],
            advances=[AdvanceApplication("DEPOSIT", 10000, "NON_MONETARY", "CONTRACT",
                                         CostAssignment("1100", "21300000", "CC1"), "L")],
        )
        entry = applied.journal_entry["lines"]
        self.assertEqual(row["payable"], 40000)
        self.assertEqual(sum(line["debit"] - line["credit"] for line in entry
                             if line["account"] == "21300000"), 45000)
        self.assertTrue(any(line["account"] == "21300000" and line["currency"] == "EUR"
                            and line["credit"] == 5000 for line in entry))
        self.assertFalse({"66800000", "76800000"} & {line["account"] for line in entry})
        self.assertEqual(request.state.balances[0].used_doc, 0)
        self.assertEqual(applied.state.balances[0].used_doc, 10000)
        self.export([request_row, row])

    def test_multi_po_quantity_allocation_favorable_variance_and_explicit_delivery_split(self):
        key1 = OrderKey("1100", "V1", "EUR", "PO1", 10)
        key2 = OrderKey("1100", "V1", "EUR", "PO2", 20)
        allocation = allocate_receipts(
            company="1100", vendor="V1", currency="EUR", invoice_id="MULTI",
            lines=[InvoiceQuantityLine("L", 3000, "ud", (OrderPortion(key1, 1000), OrderPortion(key2, 2000)))],
            orders=[OrderLine(key1, "ud"), OrderLine(key2, "ud")],
            receipts=[Receipt("R1", key1, 1000, "ud", "2026-07-01"),
                      Receipt("R2", key2, 2000, "ud", "2026-07-02")],
        )
        # These invoice portions are explicit observations, not inferred by export.
        split = [dict(amount=98, account="60700000", wbs="OB1", tax_code="S21", po="PO1", po_item=10),
                 dict(amount=392, account="60700000", wbs="OB1", tax_code="S21", po="PO2", po_item=20)]
        row, result = self.invoice(
            "MULTI", net=490, account="60700000", cost_center=None, wbs="OB1",
            quantity=3000, allocation=allocation,
            prices=[OrderPrice(key1, 100), OrderPrice(key2, 200)], coded_lines=split,
        )
        self.assertEqual(row["lines"], split)
        journal = result.journal_entry["lines"]
        self.assertEqual(sum(line["debit"] for line in journal if line["account"] == "40090000"), 500)
        self.assertEqual(next(line["credit"] for line in journal if line["account"] == "60700000"), 10)
        self.assertEqual({line["assignment"] for line in journal if line["account"] == "40090000"}, {"PO1/10", "PO2/20"})
        self.export([row])

    def test_payment_and_notice_resolutions_export_a_complete_mixed_inventory(self):
        scope = ApScope("1100", "V1", "EUR")
        proof = (Evidence("synthetic-integration", "explicit-inventory"),)
        events = invoice_state([], scope, "2026-07-31", "2026-07-31T10:00:00", "2026-07", complete_kinds=KINDS)
        inventories = {kind: proof for kind in KINDS}
        block = resolve_payment("CLEAR", "CLEAR", "CLEAR", True, events, inventory_evidence=inventories)
        row, _ = self.invoice("BLOCK", decision=block.decision, payment_block=block.payment_block)
        rows = [row]
        for doc, stages, reason in [
            ("DUP", ("DUPLICATE", "REJECT", "HOLD"), None),
            ("REJECT", ("CLEAR", "REJECT", "HOLD"), "ARITHMETIC_ERROR"),
            ("HOLD", ("CLEAR", "CLEAR", "HOLD"), "PRICE_VARIANCE"),
        ]:
            decision = resolve_payment(*stages, False, events).decision
            rows.append(build_ap_row(doc_id=doc, document_type="INVOICE", decision=decision,
                                     reasons=[reason] if reason else [], duplicate_of="BLOCK" if doc == "DUP" else None))
        for kind, action in ACTIONS.items():
            event = None if action == "NONE" else ApEvent(
                f"NOTICE-{kind}", scope, kind, proof, received_at="2026-07-01T10:00:00",
                valid_from="2026-07-01", valid_until="2027-07-01", verified=True, value="ES-SYNTHETIC-IBAN",
            )
            notice = apply_notice(kind, event)
            rows.append(build_ap_row(doc_id=f"NOTICE-{kind}", document_type=kind,
                                     decision=notice.decision, action=notice.action))
        restored = self.export(rows)
        self.assertEqual({r["decision"] for r in restored}, {"POST_PAYMENT_BLOCK", "HOLD", "REJECT", "DUPLICATE", "NOT_INVOICE"})
        self.assertTrue(all("journal_entry" not in r for r in restored if r["decision"] != "POST_PAYMENT_BLOCK"))


if __name__ == "__main__":
    unittest.main()
