from collections import defaultdict
from dataclasses import replace
from decimal import Decimal
import json
import os
from pathlib import Path
import unittest

from kalmora.ap_journal import (
    AdvanceApplication, AdvanceBalance, AdvanceState, ApprovedAdvanceOrder,
    CreditReference, InvoiceLineOrder, build_ap_journal, build_down_payment_request,
)
from kalmora.ap_tax import TaxCatalog, TaxLine, calculate_ap_tax
from kalmora.ap_valuation import CostAssignment, ValuationLine, value_ap_lines
from kalmora.ap_withholding import ContractGuarantee, WithholdingBase, WithholdingCatalog, calculate_ap_withholdings
from kalmora.money import RateTable
from kalmora.validation import validate_entry
from test_ap_tax import source_catalog
from test_ap_withholding import withholding_source


class APJournalTests(unittest.TestCase):
    def inputs(self, *, company="1100", vendor="V1", currency="EUR", net=10000, code="S21", codes=(),
               invoice_date="2026-07-31", decision="POST", rates=None, account="62300000",
               cost_center="CC", wbs=None, guarantee=None, doc_id="DOC-1", invoice_number="INV-1"):
        country = "MX" if company == "3100" else "PT" if company == "2100" else "ES"
        coding = CostAssignment(company, account, cost_center, wbs)
        valuation = value_ap_lines(company=company, vendor=vendor, currency=currency, invoice_id=doc_id,
                                   invoice_date=invoice_date, decision=decision,
                                   lines=[ValuationLine("L", net, coding)], gr_ir_account="40090000", rates=rates)
        tax = calculate_ap_tax(company=company, country=country, currency=currency, invoice_date=invoice_date,
                               vendor=vendor, invoice_id=doc_id,
                               decision=decision, lines=[TaxLine("L", net, code, account=account,
                                                                cost_center=cost_center, wbs=wbs)],
                               catalog=TaxCatalog(source_catalog()), rates=rates)
        withholding = calculate_ap_withholdings(company=company, country=country, vendor=vendor,
                                                invoice_id=doc_id,
                                                currency=currency, invoice_number=invoice_number, invoice_date=invoice_date,
                                                decision=decision, bases=[WithholdingBase("L", net, codes)],
                                                catalog=WithholdingCatalog(withholding_source()),
                                                guarantee=guarantee, rates=rates)
        return dict(company=company, vendor=vendor, currency=currency, doc_id=doc_id, invoice_number=invoice_number,
                    invoice_date=invoice_date, posting_date=invoice_date, decision=decision,
                    reconciliation_account="41000000", valuation=valuation, tax=tax, withholding=withholding, rates=rates)

    def build(self, *, inputs=None, **kwargs):
        data = self.inputs() if inputs is None else inputs
        return build_ap_journal(**{**data, **kwargs})

    def advance(self, *, amount_doc=100, amount_local=50, advance_id="ADV-1", currency="USD", po="PO-1"):
        return AdvanceBalance(advance_id, "1100", "V1", currency, "DEP-1", "2026-06-01", po,
                              amount_doc, amount_local)

    def multi_inputs(self, amounts, *, tax_bases=None):
        data = self.inputs(net=sum(amounts), doc_id="MULTI")
        coding = CostAssignment("1100", "62300000", "CC")
        data["valuation"] = value_ap_lines(company="1100", vendor="V1", currency="EUR", invoice_id="MULTI",
                                            invoice_date="2026-07-31", decision="POST", gr_ir_account="40090000",
                                            lines=[ValuationLine(str(i), amount, coding) for i, amount in enumerate(amounts)])
        data["tax"] = calculate_ap_tax(company="1100", vendor="V1", currency="EUR", invoice_id="MULTI", country="ES",
                                        invoice_date="2026-07-31", decision="POST", catalog=TaxCatalog(source_catalog()),
                                        lines=[TaxLine(str(i), amount, "S21") for i, amount in enumerate(tax_bases or amounts)])
        return data

    def assert_balanced(self, result):
        self.assertEqual(validate_entry(result.journal_entry), [])
        self.assertEqual(sum(l["debit"] for l in result.journal_entry["lines"]),
                         sum(l["credit"] for l in result.journal_entry["lines"]))

    def test_complete_es_pt_mx_components_partner_cost_currency_assignment(self):
        for company, currency, code, codes in [
            ("1100", "EUR", "S21", ("IRPF7",)), ("1100", "EUR", "SISP", ()),
            ("2100", "EUR", "P23", ("PTIRS25",)),
            ("3100", "MXN", "M16", ("MXISR10", "MXIVAR")),
        ]:
            with self.subTest(company=company, code=code):
                data = self.inputs(company=company, currency=currency, code=code, codes=codes,
                                   guarantee=ContractGuarantee(10000, "CONTRACT-1"))
                result = self.build(inputs=data)
                self.assert_balanced(result)
                supplier = result.journal_entry["lines"][-1]
                self.assertEqual((supplier["partner"], supplier["assignment"], supplier["currency"]),
                                 ("V1", "INV-1", currency))
                self.assertEqual(result.payable_doc, data["tax"].gross_doc - data["withholding"].deduction_doc)
                self.assertEqual(result.journal_entry["lines"][0]["cost_center"], "CC")
                self.assertEqual(result.journal_entry["lines"][0]["tax_code"], code)
                self.assertEqual(result.state.events, ((company, "V1", currency, "DOC-1"),))

    def test_supplier_absorbs_fx_line_rounding(self):
        rates = RateTable([{"currency": "USD", "date": "2026-07-30", "rate": "1.2"}])
        result = self.build(inputs=self.inputs(currency="USD", rates=rates, net=106))
        self.assertEqual((result.payable_doc, result.payable_local), (128, 106))
        self.assertNotEqual(result.payable_local, rates.to_local(128, "USD", "1100", "2026-07-31"))
        self.assert_balanced(result)

    def test_partial_credit_preserves_original_imputation_and_reverses_all_sides(self):
        original = self.build(inputs=self.inputs(net=20000, account="21300000", cost_center=None, wbs="OB-1"))
        source = {**original.journal_entry, "id": "ORIGINAL-1"}
        data = self.inputs(net=5000, account="21300000", cost_center=None, wbs="OB-1", doc_id="CREDIT-1")
        result = self.build(inputs=data, document_type="CREDIT_NOTE",
                            credit_references=[CreditReference("L", source, 1)], invoice_number="CN-1")
        self.assert_balanced(result)
        asset, vat, supplier = result.journal_entry["lines"]
        self.assertEqual((asset["account"], asset["credit"], asset["wbs"], asset["debit"]),
                         ("21300000", 5000, "OB-1", 0))
        self.assertEqual(vat["credit"], 1050)
        self.assertEqual((supplier["debit"], supplier["partner"], supplier["assignment"]), (6050, "V1", "CN-1"))
        self.assertEqual(result.journal_entry["doc_type"], "KG")
        self.assertEqual(source["lines"][0]["debit"], 20000)

    def test_credit_reverses_reverse_vat_and_tax_guarantee_credits(self):
        for code, codes in [("SISP", ()), ("S21", ("IRPF15",))]:
            data = self.inputs(code=code, codes=codes, guarantee=ContractGuarantee(10000, "C"), doc_id="CN-1")
            original = self.build(inputs=data)
            source = {**original.journal_entry, "id": "ORIGINAL-1"}
            result = self.build(inputs=data, document_type="CREDIT_NOTE",
                                credit_references=[CreditReference("L", source, 1)])
            self.assert_balanced(result)
            self.assertEqual([(l["debit"], l["credit"]) for l in result.journal_entry["lines"]],
                             [(l["credit"], l["debit"]) for l in original.journal_entry["lines"]])

    def test_credit_deductions_cannot_appear_disappear_or_change_original_treatment(self):
        for original_codes, original_guarantee, credit_codes, credit_guarantee in [
            ((), None, ("IRPF15",), None), ((), None, (), ContractGuarantee(10000, "NEW")),
            (("IRPF15",), None, (), None), (("IRPF7",), None, ("IRPF15",), None),
            ((), ContractGuarantee(10000, "OLD"), (), None),
        ]:
            source = {**self.build(inputs=self.inputs(codes=original_codes, guarantee=original_guarantee)).journal_entry,
                      "id": "ORIGINAL-1"}
            credit = self.inputs(codes=credit_codes, guarantee=credit_guarantee, doc_id="CN-1")
            with self.subTest(original_codes=original_codes, credit_codes=credit_codes), self.assertRaises(ValueError):
                self.build(inputs=credit, document_type="CREDIT_NOTE", credit_references=[CreditReference("L", source, 1)])
        source = {**self.build(inputs=self.inputs(codes=("IRPF15",), guarantee=ContractGuarantee(10000, "OLD"))).journal_entry,
                  "id": "ORIGINAL-1"}
        credit = self.inputs(net=5000, codes=("IRPF15",), guarantee=ContractGuarantee(5000, "OLD"), doc_id="CN-1")
        self.assert_balanced(self.build(inputs=credit, document_type="CREDIT_NOTE",
                                       credit_references=[CreditReference("L", source, 1)]))

    def test_credit_gr_ir_without_tax_label_uses_original_vat_proof(self):
        source = {**self.build().journal_entry, "id": "ORIGINAL-1"}
        source["lines"] = [dict(l) for l in source["lines"]]
        source["lines"][0] = {**source["lines"][0], "account": "40090000", "partner": "V1",
                              "cost_center": None, "wbs": None, "tax_code": None}
        for code in ("S10", "S21"):
            credit = self.inputs(code=code, doc_id="CN-1")
            component = credit["valuation"].components[0]
            credit["valuation"] = replace(credit["valuation"], components=(replace(component, account="40090000", partner="V1", cost_center=None),))
            if code == "S10":
                with self.assertRaises(ValueError):
                    self.build(inputs=credit, document_type="CREDIT_NOTE", credit_references=[CreditReference("L", source, 1)])
            else:
                self.assert_balanced(self.build(inputs=credit, document_type="CREDIT_NOTE",
                                               credit_references=[CreditReference("L", source, 1)]))

    def test_credit_dua_requires_original_dua_reference_and_quota_cap(self):
        data = self.inputs(code="SEX")
        source = {**self.build(inputs=data).journal_entry, "id": "ORIGINAL-1"}
        for original_quota in (None, 400, 500):
            if original_quota is not None:
                source_tax = calculate_ap_tax(company="1100", vendor="V1", currency="EUR", invoice_id="DOC-1", country="ES",
                                              invoice_date="2026-07-31", decision="POST", catalog=TaxCatalog(source_catalog()),
                                              lines=[TaxLine("L", 10000, "SEX"), TaxLine("DUA", 0, "SIMP", tax_doc=original_quota, dua_reference="OLD-DUA")])
                source = {**self.build(inputs=data, tax=source_tax).journal_entry, "id": "ORIGINAL-1"}
            credit = self.inputs(code="SEX", doc_id="CN-1")
            credit["tax"] = calculate_ap_tax(company="1100", vendor="V1", currency="EUR", invoice_id="CN-1", country="ES",
                                             invoice_date="2026-07-31", decision="POST", catalog=TaxCatalog(source_catalog()),
                                             lines=[TaxLine("L", 10000, "SEX"), TaxLine("DUA", 0, "SIMP", tax_doc=500, dua_reference="NEW-DUA")])
            refs = [CreditReference("L", source, 1)]
            if original_quota is not None:
                refs.append(CreditReference("DUA", source, 2))
            if original_quota == 500:
                self.assert_balanced(self.build(inputs=credit, document_type="CREDIT_NOTE", credit_references=refs))
            else:
                with self.assertRaises(ValueError):
                    self.build(inputs=credit, document_type="CREDIT_NOTE", credit_references=refs)

    def test_credit_of_invoice_with_applied_advance_requires_restoration_evidence(self):
        rates = RateTable([{"currency": "USD", "date": "2026-07-31", "rate": 1}])
        state = AdvanceState((self.advance(),))
        for treatment in ("MONETARY", "NON_MONETARY"):
            with self.subTest(treatment=treatment):
                assignment = CostAssignment("1100", "21300000", "CC") if treatment == "NON_MONETARY" else None
                original = self.build(inputs=self.inputs(currency="USD", rates=rates, net=500,
                                      code="SEX", account="21300000"), state=state,
                    invoice_orders=("PO-1",), order_bindings=[InvoiceLineOrder("L", "PO-1", 500, "BINDING")],
                    advances=[AdvanceApplication("ADV-1", 100, treatment, "CONTRACT", assignment, "L")])
                source = {**original.journal_entry, "id": "ORIGINAL-ADVANCE-INVOICE"}
                credit = self.inputs(currency="USD", rates=rates, net=500, code="SEX",
                                     account="21300000", doc_id="CN-ADVANCE")
                with self.assertRaisesRegex(ValueError, "advance.*restoration"):
                    self.build(inputs=credit, document_type="CREDIT_NOTE", state=original.state,
                               credit_references=[CreditReference("L", source, 1)])
                self.assertEqual(original.state.balances[0].used_doc, 100)
                self.assertEqual(state.balances[0].used_doc, 0)

    def test_credit_missing_wrong_or_excessive_original_evidence_blocks(self):
        original = self.build(inputs=self.inputs(net=10000))
        source = {**original.journal_entry, "id": "ORIGINAL-1"}
        for data, refs in [
            (self.inputs(), []),
            (self.inputs(account="62900000"), [CreditReference("L", source, 1)]),
            (self.inputs(cost_center="OTHER"), [CreditReference("L", source, 1)]),
            (self.inputs(net=10001), [CreditReference("L", source, 1)]),
            (self.inputs(code="S10"), [CreditReference("L", source, 1)]),
            (self.inputs(), [CreditReference("L", source, 99)]),
        ]:
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                self.build(inputs=data, document_type="CREDIT_NOTE", credit_references=refs)

    def test_aggregate_credit_cap_and_ambiguous_original_mapping(self):
        source = {**self.build(inputs=self.inputs(net=100)).journal_entry, "id": "ORIGINAL-1"}
        refs = [CreditReference("0", source, 1), CreditReference("1", source, 1)]
        result = self.build(inputs=self.multi_inputs((40, 60)), document_type="CREDIT_NOTE", credit_references=refs)
        self.assert_balanced(result)
        with self.assertRaises(ValueError):
            self.build(inputs=self.multi_inputs((60, 60)), document_type="CREDIT_NOTE", credit_references=refs)
        other = {**source, "id": "ORIGINAL-2"}
        with self.assertRaises(ValueError):
            self.build(inputs=self.multi_inputs((40, 60)), document_type="CREDIT_NOTE",
                       credit_references=[*refs, CreditReference("0", other, 1)])

    def test_per_line_tax_bases_and_non_deductible_cost_must_match_valuation(self):
        with self.assertRaises(ValueError):
            self.build(inputs=self.multi_inputs((100, 200), tax_bases=(200, 100)))
        data = self.inputs(code="SND")
        other_tax = calculate_ap_tax(company="1100", vendor="V1", currency="EUR", invoice_id="DOC-1", country="ES",
                                      invoice_date="2026-07-31", decision="POST", catalog=TaxCatalog(source_catalog()),
                                      lines=[TaxLine("L", 10000, "SND", account="21300000", wbs="OTHER")])
        with self.assertRaises(ValueError):
            self.build(inputs=data, tax=other_tax)
        self.assert_balanced(self.build(inputs=data))

    def test_zero_base_dua_can_supplement_valued_freight(self):
        data = self.inputs(code="SEX")
        tax = calculate_ap_tax(company="1100", vendor="V1", currency="EUR", invoice_id="DOC-1", country="ES",
                               invoice_date="2026-07-31", decision="POST", catalog=TaxCatalog(source_catalog()),
                               lines=[TaxLine("L", 10000, "SEX"), TaxLine("DUA", 0, "SIMP", tax_doc=456, dua_reference="DUA-1")])
        result = self.build(inputs=data, tax=tax)
        self.assertEqual(result.payable_doc, 10456)
        self.assert_balanced(result)

    def test_foreign_request_needs_approved_order_and_partner_on_407(self):
        data = dict(company="1100", vendor="V1", vendor_country="CN", currency="USD", doc_id="DEP-1",
                    vendor_master={"id": "V1", "country": "CN", "companies": ["1100"]},
                    invoice_number="DEPOSIT", invoice_date="2026-06-01", posting_date="2026-06-01",
                    amount_doc=100, decision="POST", order=ApprovedAdvanceOrder("1100", "V1", "USD", "PO-1", True, "APPROVAL"),
                    rates=RateTable([{"currency": "USD", "date": "2026-06-01", "rate": 2}]))
        result = build_down_payment_request(**data)
        self.assert_balanced(result)
        self.assertEqual([l["account"] for l in result.journal_entry["lines"]], ["40700000", "40000000"])
        self.assertEqual((result.payable_doc, result.payable_local), (100, 50))
        self.assertTrue(all(l["partner"] == "V1" for l in result.journal_entry["lines"]))
        self.assertEqual(result.state.balances[0].amount_doc, 100)
        for kwargs in ({"vendor_country": "ES"}, {"vendor_country": "UNKNOWN"},
                       {"vendor_master": {"id": "V2", "country": "CN", "companies": ["1100"]}},
                       {"decision": "HOLD"},
                       {"order": replace(data["order"], approved=None)},
                       {"order": replace(data["order"], approved=False)},
                       {"order": replace(data["order"], approval_reference=None)},
                       {"order": replace(data["order"], vendor="V2")}, {"amount_doc": 0},
                       {"state": result.state}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_down_payment_request(**{**data, **kwargs})

    def test_non_monetary_historical_carrying_adjusts_cost_without_fx(self):
        rates = RateTable([{"currency": "USD", "date": "2026-07-31", "rate": 1}])
        state = AdvanceState((self.advance(),))
        result = self.build(inputs=self.inputs(currency="USD", rates=rates, net=500, code="SEX", account="21300000"),
                            state=state, invoice_orders=("PO-1",), order_bindings=[InvoiceLineOrder("L", "PO-1", 500, "EXPLICIT-BINDING")],
                            advances=[AdvanceApplication("ADV-1", 100, "NON_MONETARY", "NON-MONETARY-CONTRACT", CostAssignment("1100", "21300000", "CC"), "L")])
        self.assert_balanced(result)
        self.assertEqual((result.payable_doc, result.payable_local), (400, 400))
        self.assertEqual(sum(l["debit"] - l["credit"] for l in result.journal_entry["lines"] if l["account"] == "21300000"), 450)
        self.assertFalse({"66800000", "76800000"} & {l["account"] for l in result.journal_entry["lines"]})
        applied = next(l for l in result.journal_entry["lines"] if l["account"] == "40700000")
        self.assertEqual((applied["credit"], applied["amount_doc"], applied["currency"], applied["assignment"]), (50, 100, "USD", "DEP-1"))
        self.assertEqual(state.balances[0].used_doc, 0)
        self.assertEqual(result.state.balances[0].used_doc, 100)

    def test_monetary_settlement_records_gain_or_loss_only_when_evidenced(self):
        rates = RateTable([{"currency": "USD", "date": "2026-07-31", "rate": 1}])
        for historical, account, debit, credit in [(50, "76800000", 0, 50), (150, "66800000", 50, 0)]:
            result = self.build(inputs=self.inputs(currency="USD", rates=rates, net=500, code="SEX"),
                                state=AdvanceState((self.advance(amount_local=historical),)), invoice_orders=("PO-1",),
                                order_bindings=[InvoiceLineOrder("L", "PO-1", 500, "EXPLICIT-BINDING")],
                                advances=[AdvanceApplication("ADV-1", 100, "MONETARY", "MONETARY-CLAIM", line_id="L")])
            self.assert_balanced(result)
            fx = next(l for l in result.journal_entry["lines"] if l["account"] == account)
            self.assertEqual((fx["debit"], fx["credit"]), (debit, credit))
            self.assertEqual(result.payable_local, 400)

    def test_partial_exhaustion_preserves_original_rounding_cents(self):
        rates = RateTable([{"currency": "USD", "date": "2026-07-31", "rate": 2}])
        state = AdvanceState((self.advance(amount_doc=3, amount_local=2),))
        carrying = []
        for i, take in enumerate((1, 2)):
            result = self.build(inputs=self.inputs(currency="USD", rates=rates, net=10, code="SEX", doc_id=f"INV-{i}"),
                                state=state, invoice_orders=("PO-1",),
                                order_bindings=[InvoiceLineOrder("L", "PO-1", 10, "EXPLICIT-BINDING")],
                                advances=[AdvanceApplication("ADV-1", take, "NON_MONETARY", "CONTRACT", CostAssignment("1100", "62300000", "CC"), "L")])
            carrying.append(result.advance_usages[0].historical_local)
            self.assert_balanced(result)
            state = result.state
            if i == 0:
                with self.assertRaisesRegex(ValueError, "representable historical"):
                    self.build(inputs=self.inputs(currency="USD", rates=rates, net=10, code="SEX", doc_id="TOO-SMALL"),
                               state=state, invoice_orders=("PO-1",), order_bindings=[InvoiceLineOrder("L", "PO-1", 10, "BINDING")],
                               advances=[AdvanceApplication("ADV-1", 1, "MONETARY", "M", line_id="L")])
        self.assertEqual(carrying, [1, 1])
        self.assertEqual((state.balances[0].used_doc, state.balances[0].used_local), (3, 2))
        with self.assertRaises(ValueError):
            self.build(inputs=self.inputs(currency="USD", rates=rates, net=10, code="SEX", doc_id="NEXT"), state=state,
                       invoice_orders=("PO-1",), advances=[AdvanceApplication("ADV-1", 1, "MONETARY", "M")])

    def test_multiple_advances_consume_atomically_and_prevent_repeated_event(self):
        rates = RateTable([{"currency": "USD", "date": "2026-07-31", "rate": 1}])
        data = self.inputs(currency="USD", rates=rates, net=500, code="SEX")
        state = AdvanceState((self.advance(), self.advance(advance_id="ADV-2", amount_doc=200, amount_local=150)))
        apps = [AdvanceApplication("ADV-1", 100, "MONETARY", "M", line_id="L"), AdvanceApplication("ADV-2", 200, "MONETARY", "M", line_id="L")]
        bindings = [InvoiceLineOrder("L", "PO-1", 500, "BINDING")]
        result = self.build(inputs=data, state=state, invoice_orders=("PO-1",), advances=apps, order_bindings=bindings)
        self.assertEqual((result.payable_doc, result.payable_local), (200, 200))
        self.assertEqual([b.used_doc for b in result.state.balances], [100, 200])
        with self.assertRaises(ValueError):
            self.build(inputs=data, state=result.state, invoice_orders=("PO-1",), advances=apps)
        with self.assertRaises(ValueError):
            self.build(inputs=data, state=state, invoice_orders=("PO-1",), order_bindings=bindings, advances=[apps[0], replace(apps[1], amount_doc=201)])
        self.assertEqual([b.used_doc for b in state.balances], [0, 0])

    def test_unknown_advance_classification_scope_order_or_master_blocks(self):
        rates = RateTable([{"currency": "USD", "date": "2026-07-31", "rate": 1}])
        data = self.inputs(currency="USD", rates=rates, net=500, code="SEX")
        state = AdvanceState((self.advance(),))
        good = AdvanceApplication("ADV-1", 100, "MONETARY", "M", line_id="L")
        for kwargs in ({"advances": [replace(good, treatment=None)]},
                       {"advances": [replace(good, treatment_reference=None)]},
                       {"advances": [replace(good, treatment="NON_MONETARY")]},
                       {"invoice_orders": ("OTHER",)}, {"vendor": "V2"},
                       {"decision": "HOLD"}, {"context": {"accounts": {"62300000"}}},
                       {"advances": [good, good]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.build(inputs=data, **{"state": state, "invoice_orders": ("PO-1",), "advances": [good],
                                           "order_bindings": [InvoiceLineOrder("L", "PO-1", 500, "BINDING")], **kwargs})
        self.assertEqual(state.balances[0].used_doc, 0)

    def test_non_monetary_advance_requires_correct_line_and_po_cost_binding(self):
        rates = RateTable([{"currency": "USD", "date": "2026-07-31", "rate": 1}])
        data = self.inputs(currency="USD", rates=rates, net=500, code="SEX")
        state = AdvanceState((self.advance(),))
        application = AdvanceApplication("ADV-1", 100, "NON_MONETARY", "CONTRACT", CostAssignment("1100", "62300000", "CC"), "L")
        good = dict(state=state, invoice_orders=("PO-1",), advances=[application],
                    order_bindings=[InvoiceLineOrder("L", "PO-1", 500, "BINDING")])
        self.assert_balanced(self.build(inputs=data, **good))
        for changes in ({"order_bindings": []},
                        {"advances": [replace(application, line_id="OTHER")]},
                        {"advances": [replace(application, cost_assignment=CostAssignment("1100", "21300000", "CC"))]},
                        {"order_bindings": [InvoiceLineOrder("L", "PO-1", 500, "")]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.build(inputs=data, **{**good, **changes})

    def test_advances_cannot_consume_another_po_line_or_overallocate_shared_portion(self):
        data = self.multi_inputs((10, 490))
        state = AdvanceState((self.advance(currency="EUR", amount_doc=100, amount_local=100),))
        bindings = [InvoiceLineOrder("0", "PO-1", 10, "L0-PO1"), InvoiceLineOrder("1", "PO-2", 490, "L1-PO2")]
        for treatment in ("MONETARY", "NON_MONETARY"):
            app = AdvanceApplication("ADV-1", 100, treatment, "CONTRACT",
                                     CostAssignment("1100", "62300000", "CC") if treatment == "NON_MONETARY" else None, "0")
            with self.subTest(treatment=treatment), self.assertRaises(ValueError):
                self.build(inputs=data, state=state, invoice_orders=("PO-1", "PO-2"), order_bindings=bindings, advances=[app])
        data = self.inputs(net=500, code="SEX")
        state = AdvanceState((self.advance(currency="EUR", amount_local=100),
                              self.advance(currency="EUR", amount_local=100, advance_id="ADV-2")))
        apps = [AdvanceApplication("ADV-1", 60, "MONETARY", "M", line_id="L"), AdvanceApplication("ADV-2", 60, "MONETARY", "M", line_id="L")]
        with self.assertRaises(ValueError):
            self.build(inputs=data, state=state, invoice_orders=("PO-1",), order_bindings=[InvoiceLineOrder("L", "PO-1", 100, "PORTION")], advances=apps)

    def test_non_post_decisions_produce_no_journal_and_no_consumption(self):
        data = self.inputs()
        for decision in ("HOLD", "REJECT", "DUPLICATE", "NOT_INVOICE"):
            with self.subTest(decision=decision), self.assertRaises(ValueError):
                self.build(inputs=data, decision=decision)
        with self.assertRaises(ValueError):
            self.build(inputs=data, tax=replace(data["tax"], net_doc=10001))

    def test_factory_scopes_reject_mixed_documents_vendors_dates_and_legacy_results(self):
        data = self.inputs()
        for changed in ({"doc_id": "OTHER"}, {"vendor": "V2"}, {"invoice_date": "2026-07-30"},
                        {"decision": "POST_PAYMENT_BLOCK"}, {"company": "1000"}):
            other = self.inputs(**changed)
            for name in ("valuation", "tax", "withholding"):
                with self.subTest(changed=changed, component=name), self.assertRaises(ValueError):
                    self.build(inputs=data, **{name: other[name]})
        for name in ("valuation", "tax", "withholding"):
            with self.subTest(legacy=name), self.assertRaises(ValueError):
                self.build(inputs=data, **{name: replace(data[name], scope=None)})
        standalone = calculate_ap_tax(company="1100", country="ES", currency="EUR", invoice_date="2026-07-31",
                                      decision="POST", lines=[TaxLine("L", 10000, "S21")],
                                      catalog=TaxCatalog(source_catalog()))
        with self.assertRaises(ValueError):
            self.build(inputs=data, tax=standalone)

    def test_advance_state_reconstruction_limits_and_future_origin(self):
        rates = RateTable([{"currency": "USD", "date": "2026-07-31", "rate": 1}])
        data = self.inputs(currency="USD", rates=rates, net=100, code="SEX")
        good = self.advance()
        application = AdvanceApplication("ADV-1", 50, "MONETARY", "M", line_id="L")
        for balance in (replace(good, original_date="2026-08-01"), replace(good, used_doc=101),
                        replace(good, used_doc=1, used_local=40), replace(good, amount_doc=True)):
            with self.subTest(balance=balance), self.assertRaises((ValueError, TypeError)):
                self.build(inputs=data, state=AdvanceState((balance,)), invoice_orders=("PO-1",), advances=[application])
        with self.assertRaises(ValueError):
            self.build(inputs=data, state=AdvanceState((good, good)), invoice_orders=("PO-1",), advances=[application])
        posted = self.build(inputs=data, state=AdvanceState((good,)), invoice_orders=("PO-1",),
                            order_bindings=[InvoiceLineOrder("L", "PO-1", 100, "BINDING")], advances=[application])
        saved = AdvanceState(tuple(AdvanceBalance(**vars(b)) for b in posted.state.balances), tuple(posted.state.events))
        self.assertEqual(saved, posted.state)
        with self.assertRaises(ValueError):
            self.build(inputs=data, state=saved, invoice_orders=("PO-1",), advances=[application])

    def test_local_currency_advance_cannot_fabricate_fx_and_currency_must_be_iso(self):
        local = self.inputs(code="SEX", net=500)
        for balance in (self.advance(currency="EUR", amount_local=50), self.advance(currency="invalid")):
            with self.subTest(balance=balance), self.assertRaisesRegex(ValueError, "currency amounts"):
                self.build(inputs=local, state=AdvanceState((balance,)), invoice_orders=("PO-1",),
                           order_bindings=[InvoiceLineOrder("L", "PO-1", 500, "BINDING")],
                           advances=[AdvanceApplication("ADV-1", 100, "MONETARY", "SOURCE", line_id="L")])

    def test_positive_document_tax_cannot_disappear_when_local_rounding_is_zero(self):
        rates = RateTable([{"currency": "USD", "date": "2026-07-31", "rate": 3}])
        data = self.inputs(currency="USD", rates=rates, net=3, code="S21")
        self.assertEqual(data["tax"].tax_doc, 1)
        self.assertEqual(data["tax"].tax_local, 0)
        with self.assertRaisesRegex(ValueError, "representable local"):
            self.build(inputs=data)

    def test_conflicting_snapshots_of_same_original_do_not_erase_deductions(self):
        source = {**self.build(inputs=self.inputs(codes=("IRPF15",))).journal_entry, "id": "ORIGINAL-1"}
        other = {**source, "lines": [dict(l) for l in source["lines"] if l["account"] != "47510000"]}
        other["lines"][-1]["credit"] += 1500
        self.assertEqual(validate_entry(other), [])
        with self.assertRaisesRegex(ValueError, "conflicting original"):
            self.build(inputs=self.multi_inputs((4000, 6000)), document_type="CREDIT_NOTE",
                       credit_references=[CreditReference("0", source, 1), CreditReference("1", other, 1)])

    def test_notary_supplied_disbursement_excluded_from_irpf_base(self):
        coding = CostAssignment("1000", "62300000", "CC-1000-DIR")
        valuation = value_ap_lines(company="1000", vendor="V1", currency="EUR", invoice_id="NOTARY",
                                   invoice_date="2025-01-31", decision="POST", gr_ir_account="40090000",
                                   lines=[ValuationLine("fees", 204698, coding),
                                          ValuationLine("disbursement", 13523, CostAssignment("1000", "63100000", "CC-1000-DIR"))])
        tax = calculate_ap_tax(company="1000", country="ES", currency="EUR", invoice_date="2025-01-31",
                               vendor="V1", invoice_id="NOTARY",
                               decision="POST", lines=[TaxLine("fees", 204698, "S21"), TaxLine("disbursement", 13523, "SEX")],
                               catalog=TaxCatalog(source_catalog()))
        withholding = calculate_ap_withholdings(company="1000", country="ES", vendor="V1", currency="EUR",
                                                invoice_id="NOTARY",
                                                invoice_date="2025-01-31", invoice_number="N-1", decision="POST",
                                                bases=[WithholdingBase("fees", 204698, ("IRPF15",)), WithholdingBase("disbursement", 13523, ())],
                                                catalog=WithholdingCatalog(withholding_source()))
        result = build_ap_journal(company="1000", vendor="V1", currency="EUR", doc_id="NOTARY", invoice_number="N-1",
                                  invoice_date="2025-01-31", posting_date="2025-01-31", decision="POST",
                                  reconciliation_account="41000000", valuation=valuation, tax=tax, withholding=withholding)
        self.assert_balanced(result)
        self.assertEqual(withholding.withholding_doc, 30705)
        self.assertNotEqual(withholding.withholding_doc, (218221 * 1500 + 5000) // 10000)

    @unittest.skipUnless(os.environ.get("KALMORA_PHASE_ERP"), "original ERP not configured")
    def test_three_original_imports_preserve_historical_non_monetary_cost(self):
        erp = Path(os.environ["KALMORA_PHASE_ERP"])
        entries = {e["id"]: e for e in map(json.loads, (erp / "journal_entries.jsonl").read_text().splitlines())}
        rates = RateTable(json.loads(s, parse_float=Decimal) for s in (erp / "fx_rates.jsonl").read_text().splitlines())
        def signature(lines):
            totals = defaultdict(int)
            for l in lines:
                totals[(l["account"], l.get("partner"), l.get("cost_center"), l.get("wbs"))] += l["debit"] - l["credit"]
            return {key: amount for key, amount in totals.items() if amount}
        for advance_id, invoice_id, po in [
            ("1100-2025-5100000215", "1100-2025-5100000339", "4500014449"),
            ("1100-2025-5100000851", "1100-2025-5100000970", "4500016825"),
            ("1100-2026-5100000207", "1100-2026-5100000357", "4500020749"),
        ]:
            deposit, original = entries[advance_id], entries[invoice_id]
            advance = next(l for l in deposit["lines"] if l["account"] == "40700000")
            asset = next(l for l in original["lines"] if l["account"] == "21300000")
            balance = AdvanceBalance(advance_id, "1100", "V100121", "USD", deposit["reference"],
                                     deposit["document_date"], po, advance["amount_doc"], advance["debit"])
            result = self.build(inputs=self.inputs(vendor="V100121", currency="USD", rates=rates, net=asset["amount_doc"], code="SEX",
                                                  account="21300000", cost_center=asset["cost_center"],
                                                  invoice_date=original["document_date"], doc_id=invoice_id),
                                state=AdvanceState((balance,)), invoice_orders=(po,),
                                order_bindings=[InvoiceLineOrder("L", po, asset["amount_doc"], f"ERP:{invoice_id}#1")],
                                reconciliation_account="40000000", invoice_number=original["reference"],
                                advances=[AdvanceApplication(advance_id, advance["amount_doc"], "NON_MONETARY",
                                                             f"ERP:{invoice_id}", CostAssignment("1100", "21300000", asset["cost_center"]), "L")])
            self.assertEqual(signature(result.journal_entry["lines"]), signature(original["lines"]), invoice_id)
            self.assert_balanced(result)


if __name__ == "__main__":
    unittest.main()
