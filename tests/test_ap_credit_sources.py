from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import unittest

from kalmora.ap_credit_sources import CreditOriginalCatalog
from kalmora.ap_identity import IdentityCatalog
from kalmora.ap_journal import CreditReference
from kalmora.ap_output import APHeader
from kalmora.ap_tax import TaxCatalog, TaxLine
from kalmora.ap_transaction import (
    APPostingInputs, APTransactionRequest, APTransactionState, CodedAPLine, commit_ap_transaction,
)
from kalmora.ap_valuation import CostAssignment, ValuationLine
from kalmora.ap_withholding import WithholdingBase, WithholdingCatalog
from kalmora.documents.router import DocumentRouter
from kalmora.documents.xml_extractor import XMLDocumentExtractor
from kalmora.facts import Evidence, Fact
from kalmora.model.ap_component_scope import APComponentScope


class CreditOriginalTests(unittest.TestCase):
    def setUp(self):
        self.invoice = dict(company="1100", vendor="V-NEW", currency="EUR", number="F-001",
                            doc_id="OLD-NEW", kind="invoice", issue_date="2026-06-02",
                            decision="HOLD", journal_entry="GL-NEW")
        self.entry = dict(company="1100", id="GL-NEW", source="AP", doc_type="KR",
                          reference="F-001", currency="EUR", document_date="2026-06-02",
                          posting_date="2026-06-03", lines=[
            dict(line=1, account="62300000", cost_center="CC-NEW", tax_code="SEX", debit=10000, credit=0),
            dict(line=2, account="41000000", partner="V-NEW", assignment="F-001", debit=0, credit=10000)])
        self.reference = Fact("F-001", Evidence("credit.xml", "Corrective.InvoiceNumber", quote="F-001"))

    def catalog(self, **changes):
        options = dict(invoices=[self.invoice], journal_entries=[self.entry], inventory_complete=True)
        options.update(changes)
        return CreditOriginalCatalog(**options)

    def resolve(self, catalog=None, **changes):
        options = dict(company="1100", vendor="V-NEW", currency="EUR", invoice_date="2026-07-01",
                       original_number=self.reference)
        options.update(changes)
        return (catalog or self.catalog()).resolve(**options)

    def test_exact_posted_hold_invoice_preserves_original_imputation_and_snapshots(self):
        before = deepcopy((self.invoice, self.entry))
        catalog = self.catalog()
        self.entry["lines"][0]["account"] = "60000000"
        resolved = self.resolve(catalog)
        self.assertEqual(resolved.status, "RESOLVED")
        self.assertEqual(resolved.reconciliation_account, "41000000")
        self.assertEqual(resolved.original_entry, before[1])
        self.assertIn(self.reference.evidence, resolved.evidence)
        self.assertTrue(any(e.document == "erp/ap_invoices.jsonl" and e.field.endswith("journal_entry")
                            for e in resolved.evidence))
        self.assertEqual(len(resolved.original_sha256), 64)
        resolved.original_entry["lines"][0]["account"] = "62900000"
        self.assertEqual(self.resolve(catalog).original_entry, before[1])

    def test_no_reference_completeness_or_literal_scope_never_guesses_an_original(self):
        for changes, status in ((dict(original_number=None), "UNKNOWN"),
                                (dict(original_number=Fact(None, self.reference.evidence)), "UNKNOWN"),
                                (dict(company="1200"), "NOT_FOUND"), (dict(vendor="OTHER"), "NOT_FOUND"),
                                (dict(currency="USD"), "NOT_FOUND"),
                                (dict(original_number=Fact("F001", self.reference.evidence)), "NOT_FOUND"),
                                (dict(original_number=Fact("001", self.reference.evidence)), "NOT_FOUND")):
            result = self.resolve(**changes)
            self.assertEqual(result.status, status)
            self.assertIsNone(result.original_entry)
        self.assertEqual(self.resolve(self.catalog(inventory_complete=False)).diagnostics,
                         ("ORIGINAL_INVENTORY_INCOMPLETE",))
        other = {**self.invoice, "doc_id": "SECOND", "journal_entry": "GL-SECOND"}
        self.assertEqual(self.resolve(self.catalog(invoices=[self.invoice, other])).status, "AMBIGUOUS")
        with self.assertRaises(ValueError):
            self.catalog(invoices=[self.invoice, self.invoice])
        with self.assertRaises(ValueError):
            self.catalog(journal_entries=[self.entry, self.entry])

    def test_series_requires_its_own_exact_evidence_without_concatenation(self):
        series = Fact("S", Evidence("credit.xml", "Corrective.InvoiceSeriesCode", quote="S"))
        self.assertEqual(self.resolve(original_series=series).diagnostics, ("ORIGINAL_SERIES_UNKNOWN",))
        catalog = self.catalog(invoices=[{**self.invoice, "series": "S"}])
        self.assertEqual(self.resolve(catalog, original_series=series).status, "RESOLVED")
        self.assertEqual(self.resolve(catalog, original_series=replace(series, value="OTHER")).status, "CONFLICT")
        self.assertEqual(self.resolve(catalog, original_series=replace(series, evidence=Evidence("other.xml", "series"))).status,
                         "UNKNOWN")

    def test_journal_link_type_dates_vendor_currency_and_amounts_are_corroborated(self):
        for row, entry, status in (
            ({**self.invoice, "journal_entry": None}, self.entry, "UNKNOWN"),
            ({**self.invoice, "journal_entry": "ABSENT"}, self.entry, "UNKNOWN"),
            ({**self.invoice, "kind": "credit_note"}, self.entry, "CONFLICT"),
            (self.invoice, {**self.entry, "source": "MM"}, "CONFLICT"),
            (self.invoice, {**self.entry, "doc_type": "KG"}, "CONFLICT"),
            (self.invoice, {**self.entry, "reference": "F001"}, "CONFLICT"),
            ({**self.invoice, "issue_date": "2026-06-01"}, self.entry, "UNKNOWN"),
            (self.invoice, {**self.entry, "lines": [self.entry["lines"][0],
                {**self.entry["lines"][1], "partner": "OTHER"}]}, "CONFLICT"),
            (self.invoice, {**self.entry, "currency": "USD"}, "UNKNOWN"),
            (self.invoice, {**self.entry, "lines": [{**self.entry["lines"][0], "debit": 9999},
                self.entry["lines"][1]]}, "UNKNOWN"),
        ):
            with self.subTest(row=row, entry=entry):
                result = self.resolve(self.catalog(invoices=[row], journal_entries=[entry]))
                self.assertEqual(result.status, status)
                self.assertIsNone(result.original_entry)
        self.assertEqual(self.resolve(invoice_date="2026-06-01").status, "CONFLICT")
        foreign = {**self.invoice, "currency": "USD"}
        gl = {**self.entry, "lines": [{**line, "currency": "USD", "amount_doc": 12000}
                                      for line in self.entry["lines"]]}
        self.assertEqual(self.resolve(self.catalog(invoices=[foreign], journal_entries=[gl]), currency="USD").status,
                         "RESOLVED")
        gl["lines"][0].pop("amount_doc")
        self.assertEqual(self.resolve(self.catalog(invoices=[foreign], journal_entries=[gl]), currency="USD").diagnostics,
                         ("ORIGINAL_DOCUMENT_AMOUNTS_UNRESOLVED",))

    def test_intercompany_reconciliation_is_an_observed_original_payable_account(self):
        entry = deepcopy(self.entry)
        entry["lines"][1]["account"] = "40300000"
        resolved = self.resolve(self.catalog(journal_entries=[entry]))
        self.assertEqual((resolved.status, resolved.reconciliation_account), ("RESOLVED", "40300000"))

    def test_resolved_original_reaches_atomic_output_without_consuming_a_failed_credit(self):
        original = self.resolve()
        tax = TaxCatalog({"tax_codes": {"SEX": {"country": "ES", "kind": "exempt", "rate": 0}}})
        withholding = WithholdingCatalog({"withholdings": {}})
        def request(ident, amount):
            inputs = APPostingInputs(
                header=APHeader("1100", "V-NEW", ident, "2026-07-01", "EUR", amount, 0, amount, 0, 0, amount),
                country="ES", posting_date="2026-07-02", reconciliation_account=original.reconciliation_account,
                gr_ir_account="40090000",
                valuation_lines=(ValuationLine("L", amount, CostAssignment("1100", "62300000", "CC-NEW")),),
                tax_lines=(TaxLine("L", amount, "SEX", tax_doc=0),),
                withholding_bases=(WithholdingBase("L", amount, ()),),
                coded_lines=(CodedAPLine("L", dict(amount=amount, account="62300000", cost_center="CC-NEW",
                                                  wbs=None, tax_code="SEX", po=None, po_item=None)),),
                credit_references=(CreditReference("L", original.original_entry, 1),),
            )
            return APTransactionRequest(scope=APComponentScope("1100", "V-NEW", "EUR", ident, "2026-07-01", "POST"),
                                        document_type="CREDIT_NOTE", evidence=original.evidence, posting=inputs)
        def commit(req, state):
            return commit_ap_transaction(req, state, tax_catalog=tax, withholding_catalog=withholding)
        first = commit(request("CN-NEW-A", 6000), APTransactionState())
        second = request("CN-NEW-B", 4000)
        with self.assertRaises(ValueError):
            commit(replace(second, posting=replace(second.posting,
                   header=replace(second.posting.header, payable=4001))), first.state)
        self.assertEqual(len(first.state.rows), 1)
        self.assertEqual(next(b.used_doc for b in first.state.advances.credits if b.bucket == "line:1"), 6000)
        finished = commit(second, first.state)
        self.assertEqual([r["doc_id"] for r in finished.state.rows], ["CN-NEW-A", "CN-NEW-B"])
        self.assertEqual(next(b.used_doc for b in finished.state.advances.credits if b.bucket == "line:1"), 10000)
        self.assertEqual({b.original_sha256 for b in finished.state.advances.credits}, {original.original_sha256})
        with self.assertRaisesRegex(ValueError, "remaining original line"):
            commit(request("CN-NEW-C", 1), finished.state)


class CreditOriginalSourceTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.environ.get("KALMORA_PHASE_ERP"), "original ERP not configured")
    async def test_original_xml_rectifications_bind_only_exact_scoped_erp_references(self):
        erp = Path(os.environ["KALMORA_PHASE_ERP"])
        def rows(stem):
            return [json.loads(line) for line in (erp / f"{stem}.jsonl").read_text().splitlines()]
        invoices, journals, vendors = rows("ap_invoices"), rows("journal_entries"), rows("vendors")
        companies = json.loads((erp / "companies.json").read_text())
        identity = IdentityCatalog(vendors=vendors, companies=companies)
        catalog = CreditOriginalCatalog(invoices=invoices, journal_entries=journals, inventory_complete=True)
        router = DocumentRouter(erp.parent)
        results = []
        for path in sorted((erp.parent / "inbox/ap").rglob("*.xml")):
            facts = await XMLDocumentExtractor().extract(router.parse(path.relative_to(erp.parent).as_posix()))
            references = facts.fields.get("corrective.document_number", [])
            if not references:
                continue
            counterpart = identity.resolve(supplier_tax_ids=facts.fields["supplier_tax_id"],
                                            recipient_tax_ids=facts.fields["recipient_tax_id"], expected_company=None)
            self.assertEqual((counterpart.supplier.status, counterpart.recipient.status), ("RESOLVED", "RESOLVED"))
            result = catalog.resolve(company=counterpart.recipient.identity, vendor=counterpart.supplier.identity,
                currency=facts.fields["currency"][0].value, invoice_date=facts.fields["document_date"][0].value,
                original_number=references[0], original_series=next(iter(facts.fields.get("corrective.series", [])), None))
            results.append(result.status)
            if result.status == "RESOLVED":
                self.assertEqual(result.original_entry["reference"], references[0].value)
                self.assertIn(references[0].evidence, result.evidence)
            else:
                self.assertIsNone(result.original_entry)
        self.assertEqual(sorted(results), ["NOT_FOUND", "RESOLVED", "RESOLVED"])


if __name__ == "__main__":
    unittest.main()
