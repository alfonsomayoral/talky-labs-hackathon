from copy import deepcopy
from dataclasses import replace
import os
import json
from pathlib import Path
import unittest
from kalmora.ap_credit_bindings import CreditLineBinding, resolve_credit_line_bindings
from kalmora.ap_credit_sources import CreditOriginalCatalog
from kalmora.ap_journal import CreditReference, build_ap_journal
from kalmora.facts import Evidence, Fact
import test_ap_journal as journal_fixture


class CreditBindingTests(unittest.TestCase):
    def setUp(self):
        self.factory = journal_fixture.APJournalTests()
        self.entry = {**self.factory.build(inputs=self.factory.multi_inputs([5000, 5000])).journal_entry, "id": "ORIG"}
        row = dict(company="1100", vendor="V1", currency="EUR", doc_id="ORIGINAL", number="INV-1",
                   kind="invoice", issue_date="2026-07-31", journal_entry="ORIG")
        self.original = CreditOriginalCatalog(invoices=[row], journal_entries=[self.entry], inventory_complete=True).resolve(
            company="1100", vendor="V1", currency="EUR", invoice_date="2026-07-31",
            original_number=Fact("INV-1", Evidence("credit.xml", "original_number")))

    def binding(self, **changes):
        return resolve_credit_line_bindings(original=changes.pop("original", self.original),
                                           lines=(CreditLineBinding("L", **changes),))

    def test_equivalent_lines_resolve_unique_imputation_without_inventing_a_line(self):
        before = deepcopy(self.entry)
        bound = self.binding()
        self.assertEqual(bound.status, "RESOLVED")
        ref, = bound.references
        self.assertIsNone(ref.original_line)
        self.assertEqual(ref.original_lines, (1, 2))
        first = build_ap_journal(**self.factory.inputs(net=6000, doc_id="C1"), document_type="CREDIT_NOTE", credit_references=bound.references)
        second = build_ap_journal(**self.factory.inputs(net=4000, doc_id="C2"), document_type="CREDIT_NOTE", credit_references=bound.references, state=first.state)
        self.assertEqual(next(b.used_doc for b in second.state.credits if b.bucket == "lines:[1,2]"), 10000)
        with self.assertRaises(ValueError):
            build_ap_journal(**self.factory.inputs(net=1, doc_id="C3"), document_type="CREDIT_NOTE", credit_references=bound.references, state=second.state)
        self.assertEqual(self.entry, before)

    def test_groups_cannot_represent_different_cost_or_tax_imputations(self):
        for field, value in (("cost_center", "OTHER"), ("tax_code", "S10"), ("assignment", "PO2/10")):
            original = deepcopy(self.original.original_entry)
            original["lines"][1][field] = value
            from kalmora.ap_credit_state import original_credit_sha256
            resolved = replace(self.original, original_entry=original, original_sha256=original_credit_sha256(original))
            self.assertEqual(self.binding(original=resolved).status, "UNKNOWN")
            exact = self.binding(original=resolved, original_line=Fact(1, Evidence("credit.xml", "original_line")))
            self.assertEqual(exact.references[0].original_line, 1)

    def test_unknown_selectors_or_changed_snapshot_cannot_bind(self):
        self.assertEqual(self.binding(original_line=Fact(None, Evidence("credit", "line"))).status, "UNKNOWN")
        self.assertEqual(self.binding(original_line=Fact(1, Evidence("unrelated-credit.xml", "line"))).status, "UNKNOWN")
        original = deepcopy(self.original.original_entry); original["reference"] = "CHANGED"
        self.assertEqual(self.binding(original=replace(self.original, original_entry=original)).status, "UNKNOWN")

    def test_group_and_granular_usage_cannot_bypass_existing_consumption(self):
        grouped = self.binding().references
        first = build_ap_journal(**self.factory.inputs(net=1000, doc_id="G1"), document_type="CREDIT_NOTE", credit_references=grouped)
        with self.assertRaisesRegex(ValueError, "overlapping"):
            build_ap_journal(**self.factory.inputs(net=1000, doc_id="L1"), document_type="CREDIT_NOTE",
                             credit_references=(CreditReference("L", self.entry, 1),), state=first.state)
        granular = build_ap_journal(**self.factory.inputs(net=1000, doc_id="L2"), document_type="CREDIT_NOTE",
                                   credit_references=(CreditReference("L", self.entry, 1),))
        with self.assertRaisesRegex(ValueError, "overlapping"):
            build_ap_journal(**self.factory.inputs(net=1000, doc_id="G2"), document_type="CREDIT_NOTE", credit_references=grouped, state=granular.state)


class CreditBindingSourceTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.environ.get("KALMORA_PHASE_ERP"), "original ERP not configured")
    async def test_original_xml_two_bindings_have_unique_observed_imputation_without_line_guess(self):
        import json, os
        from pathlib import Path
        from kalmora.ap_identity import IdentityCatalog
        from kalmora.documents.router import DocumentRouter
        from kalmora.documents.xml_extractor import XMLDocumentExtractor
        erp = Path(os.environ["KALMORA_PHASE_ERP"])
        def rows(stem):
            return [json.loads(line) for line in (erp / f"{stem}.jsonl").read_text().splitlines()]
        catalog = CreditOriginalCatalog(invoices=rows("ap_invoices"), journal_entries=rows("journal_entries"), inventory_complete=True)
        identities = IdentityCatalog(vendors=rows("vendors"), companies=json.loads((erp / "companies.json").read_text()))
        router = DocumentRouter(erp.parent)
        from decimal import Decimal
        from kalmora.ap_allocation import ConsumptionState
        from kalmora.ap_credit_delivery import build_ap_credit_delivery
        from kalmora.ap_opening_state import resolve_ap_opening_state
        from kalmora.ap_output import APHeader, validate_ap_row
        from kalmora.ap_tax import TaxCatalog, TaxLine, calculate_ap_tax
        from kalmora.ap_valuation import CostAssignment, ValuationLine, value_ap_lines
        from kalmora.ap_withholding import WithholdingBase, WithholdingCatalog, calculate_ap_withholdings
        from kalmora.validation import validate_entry
        tax_catalog = TaxCatalog(json.loads((erp / "tax_codes.json").read_text()))
        withholding_catalog = WithholdingCatalog(json.loads((erp / "tax_codes.json").read_text()))
        found, deliveries = [], []
        for path in sorted((erp.parent / "inbox/ap").rglob("*.xml")):
            facts = await XMLDocumentExtractor().extract(router.parse(path.relative_to(erp.parent).as_posix()))
            reference = facts.fields.get("corrective.document_number", [])
            if not reference:
                continue
            identity = identities.resolve(supplier_tax_ids=facts.fields["supplier_tax_id"],
                                          recipient_tax_ids=facts.fields["recipient_tax_id"], expected_company=None)
            original = catalog.resolve(company=identity.recipient.identity, vendor=identity.supplier.identity,
                         currency=facts.fields["currency"][0].value, invoice_date=facts.fields["document_date"][0].value,
                         original_number=reference[0], original_series=next(iter(facts.fields.get("corrective.series", [])), None))
            binding = resolve_credit_line_bindings(original=original, lines=(CreditLineBinding("document-imputation"),))
            found.append((original.status, binding.status))
            if binding.status == "RESOLVED":
                ref, = binding.references
                self.assertTrue(ref.original_lines or ref.original_line)
                company, vendor, currency = identity.recipient.identity, identity.supplier.identity, facts.fields["currency"][0].value
                cutoff = Fact("2026-06-30", Evidence("test-run", "opening_cutoff"))
                opening = resolve_ap_opening_state(company=company, vendor=vendor, currency=currency, as_of=cutoff,
                            inventory_complete=Fact(True, Evidence("ERP-inventory", "complete_July_baseline")),
                            journal_entries=rows("journal_entries"), purchase_orders=rows("purchase_orders"),
                            vendors=rows("vendors"), ap_invoices=rows("ap_invoices"), tax_catalog=tax_catalog)
                self.assertEqual(opening.status, "RESOLVED", opening.diagnostics)
                def cents(field):
                    amount = Decimal(facts.fields[field][0].value) * 100
                    self.assertEqual(amount, amount.to_integral_value())
                    return int(amount)
                def scalar(field):
                    return facts.fields[field][0].value
                indexes = ref.original_lines or (ref.original_line,)
                line = next(line for index, line in enumerate(original.original_entry["lines"], 1) if line.get("line", index) == indexes[0])
                coding = CostAssignment(company, line["account"], line.get("cost_center"), line.get("wbs"))
                net, quota, payable = cents("net"), cents("tax"), cents("payable")
                self.assertEqual(cents("withholding"), 0)
                self.assertFalse(any(l["account"] in {"47510000", "40000900", "40700000", "40090000"} for l in original.original_entry["lines"]))
                date, number, ident = scalar("document_date"), scalar("document_number"), path.parent.name
                common = dict(company=company, vendor=vendor, currency=currency, invoice_date=date, decision="POST", invoice_id=ident)
                valuation = value_ap_lines(**common, lines=(ValuationLine("document-imputation", net, coding),), gr_ir_account="40090000")
                tax = calculate_ap_tax(**common, country="ES", catalog=tax_catalog,
                        lines=(TaxLine("document-imputation", net, line["tax_code"], tax_doc=quota),))
                deductions = calculate_ap_withholdings(**common, country="ES", invoice_number=number, catalog=withholding_catalog,
                              bases=(WithholdingBase("document-imputation", net, ()),))
                self.assertEqual((tax.gross_doc, deductions.deduction_doc), (payable, 0))
                arguments = dict(company=company, vendor=vendor, currency=currency, doc_id=ident, invoice_number=number,
                         invoice_date=date, posting_date=date, decision="POST", reconciliation_account=original.reconciliation_account,
                         valuation=valuation, tax=tax, withholding=deductions, document_type="CREDIT_NOTE",
                         credit_references=binding.references, state=opening.state)
                delivery = build_ap_credit_delivery(journal_arguments=arguments,
                    header=APHeader(company, vendor, number, date, currency, net, quota, payable, 0, 0, payable),
                    lines=(dict(amount=net, account=coding.account, cost_center=coding.cost_center, wbs=coding.wbs,
                                tax_code=line["tax_code"], po=None, po_item=None),),
                    consumption=ConsumptionState(), evidence=binding.evidence, tax_catalog=tax_catalog)
                self.assertEqual(validate_ap_row(delivery.row, tax_catalog=tax_catalog), ())
                self.assertEqual(validate_entry(delivery.row["journal_entry"]), [])
                self.assertTrue(delivery.advances.credits)
                self.assertEqual(opening.state.credits, ())
                deliveries.append((net, quota, payable))
        self.assertEqual(sorted(deliveries), [(5000, 1050, 6050), (118802, 0, 118802)])
        self.assertEqual(found.count(("RESOLVED", "RESOLVED")), 2)
        self.assertEqual(found.count(("NOT_FOUND", "UNKNOWN")), 1)
