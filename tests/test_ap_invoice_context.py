"""Invoice/ERP boundaries use source facts and arbitrary months/identities."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kalmora.ap_erp import load_ap_erp_baseline
from kalmora.ap_invoice_context import _prepare_invoice_context_batch, resolve_ap_invoice_context
from kalmora.ap_transaction import APTransactionState
from kalmora.data import PhaseData
from kalmora.documents.ap_sources import APAttachment, APMessage, APTaskSources
from kalmora.documents.classification import classify_document
from kalmora.documents.contracts import ParsedBlock, ParsedDocument
from kalmora.documents.normalization import normalize_document_facts
from kalmora.facts import DocumentFacts, Evidence, Fact


class ForbiddenResolver:
    def __init__(self):
        self.calls = 0

    async def resolve(self, request):
        self.calls += 1
        raise AssertionError("this exact/source-only scenario must not interpret")


class APInvoiceContextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.phase = Path(self.tmp.name) / "phase"
        (self.phase / "erp").mkdir(parents=True)
        (self.phase / "tasks").mkdir()
        (self.phase / "tasks" / "close.json").write_text(json.dumps({"month": "2031-11"}))
        self.vendor = dict(id="SUPPLIER-BETA", tax_id="TAX-SUPPLIER", companies=["CO-ALPHA"],
            bank={"iban": "ES01BETA"}, po_required=True, default_tax_code="S21")
        self.order = dict(id="ORDER-BETA", company="CO-ALPHA", vendor="SUPPLIER-BETA", currency="EUR",
            created_on="2031-10-01", items=[dict(item=25, uom="hours", unit_price=1000)])
        self.receipt = dict(id="RECEIPT-BETA", company="CO-ALPHA", vendor="SUPPLIER-BETA",
            po="ORDER-BETA", po_item=25, type="SES", quantity_milli=2000, amount=2000,
            posting_date="2031-11-05")
        self.write("vendors", [self.vendor])
        self.write("purchase_orders", [self.order])
        self.write("goods_receipts", [self.receipt])
        for table in ("ap_invoices", "ap_document_log", "journal_entries"):
            self.write(table, [])
        (self.phase / "erp" / "companies.json").write_text(json.dumps([
            dict(code="CO-ALPHA", tax_id="TAX-BUYER", country="ES"),
            dict(code="CO-OTHER", tax_id="TAX-OTHER", country="ES")]))
        self.path = "inbox/ap/TASK-ELSEWHERE/invoice.pdf"
        self.fields = {"document_type_hint": "Invoice", "supplier_tax_id": "TAX-SUPPLIER",
            "recipient_tax_id": "TAX-BUYER", "invoice_number": "INV-2031-B", "invoice_date": "2031-11-01",
            "currency": "EUR", "net": "10.00", "tax": "2.10", "gross": "12.10",
            "po_reference": "ORDER-BETA", "line.1.po_item": 25,
            "line.1.quantity": "1", "line.1.uom": "hours", "line.1.unit_price": "10.00"}
        self.cutoff = Fact("2031-11-20", Evidence("tasks/close.json", "observed_receipt_cutoff"))

    def write(self, table, rows):
        (self.phase / "erp" / (table + ".jsonl")).write_text("".join(json.dumps(row) + "\n" for row in rows))

    def attachment(self, fields=None, path=None, media="application/pdf"):
        path = path or self.path
        fields = self.fields if fields is None else fields
        raw = DocumentFacts("a" * 64, "synthetic-context-v1", {
            name: value if isinstance(value, list) and all(isinstance(f, Fact) for f in value)
            else [Fact(value, Evidence(path, "observed:" + name, 1, str(value)))]
            for name, value in fields.items()})
        document = ParsedDocument(path, raw.source_sha256, media, "synthetic-parser-v1",
            (ParsedBlock("B1", "\n".join(str(f.value) for facts in raw.fields.values() for f in facts), 1),))
        return APAttachment(path, document, raw, normalized=normalize_document_facts(raw),
                            classification=classify_document(raw))

    def task(self, attachments=None, received="2031-11-10T09:30:00Z"):
        attachments = (self.attachment(),) if attachments is None else tuple(attachments)
        message = APMessage("inbox/ap/TASK-ELSEWHERE/message.json", "b" * 64, received,
            "EMAIL", "accounts@vendor.invalid", "ap@buyer.invalid", "Invoice", "Observed invoice",
            tuple(a.path for a in attachments), {"doc_id": "TASK-ELSEWHERE", "received_at": received})
        return APTaskSources("TASK-ELSEWHERE", message, attachments)

    async def resolve(self, task=None, **options):
        baseline = load_ap_erp_baseline(self.phase, grir_account="40090000")
        kwargs = dict(data=PhaseData(self.phase), baseline=baseline,
            state=APTransactionState(consumption=baseline.history.consumption), receipt_as_of=self.cutoff)
        kwargs.update(options)
        return await resolve_ap_invoice_context(task or self.task(), **kwargs)

    async def test_exact_reference_scopes_to_erp_without_interpretation_or_consumption(self):
        resolver = ForbiddenResolver()
        context = await self.resolve(resolver=resolver)
        self.assertEqual((context.status, context.identity.expected_company), ("RESOLVED", "CO-ALPHA"))
        self.assertEqual((context.scope.company, context.scope.vendor, context.scope.currency),
                         ("CO-ALPHA", "SUPPLIER-BETA", "EUR"))
        line, = context.lines
        self.assertEqual((line.match.reference.status, line.match.quantity_status), ("RESOLVED", "AVAILABLE"))
        self.assertEqual(line.match.quantity_line.portions[0].receipt_ids, ("RECEIPT-BETA",))
        self.assertEqual(resolver.calls, 0)
        self.assertEqual(context.observation.amount_cents, 1210)
        self.assertEqual(context.invoice_date.value, "2031-11-01")
        self.assertEqual(context.received_at.evidence.document, "inbox/ap/TASK-ELSEWHERE/message.json")
        self.assertIsNone(context.request.posting)
        self.assertIsNone(context.request.header)
        self.assertIsNone(context.request.duplicate_inventory_complete)
        self.assertEqual(load_ap_erp_baseline(self.phase, grir_account="40090000").history.consumption.usages, ())

    async def test_printed_work_name_binds_active_project_id_without_rewriting_source(self):
        self.write("projects", [dict(id="PROJECT-UNRELATED-ID", company="CO-ALPHA", name="Planta Ribera Norte")])
        self.order["project"] = "PROJECT-UNRELATED-ID"
        self.write("purchase_orders", [self.order])
        printed = "  PLANTA  ribera norte "
        fields = {**self.fields, "line.1.project_reference": printed}
        context = await self.resolve(self.task((self.attachment(fields),)))
        self.assertEqual(context.lines[0].query.project, "PROJECT-UNRELATED-ID")
        self.assertEqual(context.lines[0].source.field("project_reference").value, printed.strip())
        self.assertEqual(context.primary_source.raw.field("line.1.project_reference").value, printed)
        self.assertTrue(any(e.field == "id=PROJECT-UNRELATED-ID.name" for e in context.evidence))
        (self.phase / "erp/projects.jsonl").unlink()
        context = await self.resolve(self.task((self.attachment(fields),)))
        self.assertIsNone(context.lines[0].query)
        self.assertEqual(context.status, "UNKNOWN")
        self.assertIn("PROJECT_MASTER_UNAVAILABLE", context.lines[0].diagnostics)

    async def test_batch_pins_available_projects_without_parsing_an_omitted_reference(self):
        self.write("projects", [dict(id="PROJECT-X", company="CO-ALPHA", name="Unreferenced work")])
        baseline = load_ap_erp_baseline(self.phase, grir_account="40090000")
        batch = _prepare_invoice_context_batch(PhaseData(self.phase), baseline)
        self.assertTrue(any(path.name == "projects.jsonl" for path, _ in batch.source_hashes))
        with patch.object(batch.data, "table", wraps=batch.data.table) as lookup:
            await resolve_ap_invoice_context(self.task(), data=batch.data, baseline=baseline,
                state=APTransactionState(consumption=baseline.history.consumption), receipt_as_of=self.cutoff, _batch=batch)
            self.assertFalse(any(call.args == ("projects",) for call in lookup.call_args_list))
        self.write("projects", [dict(id="PROJECT-X", company="CO-ALPHA", name="Changed work")])
        with self.assertRaisesRegex(ValueError, "sources changed"):
            batch.verify()

    async def test_missing_unit_and_cutoff_never_use_order_unit_or_month_end(self):
        fields = dict(self.fields)
        del fields["line.1.uom"]
        context = await self.resolve(self.task((self.attachment(fields),)), receipt_as_of=None)
        self.assertEqual(context.status, "UNKNOWN")
        self.assertIsNone(context.lines[0].query)
        self.assertIsNone(context.request.receipt_as_of)
        self.assertTrue(any("QUERY_FIELD_UNKNOWN:uom" in note for note in context.diagnostics))
        self.assertIn("RECEIPT_CUTOFF_UNKNOWN", context.diagnostics)

    async def test_unique_scoped_candidate_without_reference_is_unconfirmed(self):
        fields = dict(self.fields)
        del fields["po_reference"]
        del fields["line.1.po_item"]
        context = await self.resolve(self.task((self.attachment(fields),)),
            expected_company=Fact("CO-ALPHA", Evidence("tasks/ap_documents.json", "observed_company")))
        self.assertEqual(context.lines[0].match.reference.status, "UNCONFIRMED")
        self.assertEqual(len(context.lines[0].candidates), 1)
        self.assertIsNone(context.lines[0].match.quantity_line)
        self.assertEqual(context.status, "UNKNOWN")

    async def test_foreign_vendor_po_cannot_prove_ordering_company(self):
        self.write("purchase_orders", [dict(self.order, company="CO-OTHER", vendor="OTHER-VENDOR")])
        self.write("goods_receipts", [])
        context = await self.resolve()
        self.assertIsNone(context.expected_company)
        self.assertIsNone(context.identity.expected_company)
        self.assertEqual(context.rejection_fields["order_company"], ())
        self.assertEqual(context.scope.company, "CO-ALPHA")  # observed recipient, not ordering evidence
        self.assertNotEqual(context.lines[0].match.reference.status, "RESOLVED")
        self.assertEqual(context.status, "UNKNOWN")

    async def test_exact_scoped_po_proves_wrong_addressee_without_choosing_recipient_company(self):
        fields = dict(self.fields, recipient_tax_id="TAX-OTHER")
        context = await self.resolve(self.task((self.attachment(fields),)))
        self.assertTrue(context.identity.wrong_addressee)
        self.assertEqual(context.observation.company, "CO-ALPHA")
        self.assertEqual({f.value for f in context.rejection_fields["recipient_company"]}, {"CO-OTHER"})
        self.assertEqual({f.value for f in context.rejection_fields["order_company"]}, {"CO-ALPHA"})

    async def test_primary_selection_keeps_all_financial_sources_and_conflicting_identity(self):
        xml_path = "inbox/ap/TASK-ELSEWHERE/twin.xml"
        pdf = self.attachment()
        xml = self.attachment(dict(self.fields, supplier_tax_id="TAX-DIFFERENT", gross="13.10",
            **{"raw.xml./Comprobante/@TipoDeComprobante": "I"}), xml_path, "application/xml")
        context = await self.resolve(self.task((pdf, xml)), financial_source_paths=(self.path,))
        self.assertEqual(context.primary_source.source_path, self.path)
        self.assertEqual(len(context.financial_sources), 2)
        self.assertEqual(context.financial_facts.header.issuer_tax_id.status, "CONFLICT")
        self.assertEqual(context.financial_facts.header.gross_cents.status, "CONFLICT")
        self.assertIsNone(context.request)
        self.assertIsNone(context.observation)
        self.assertEqual(context.status, "UNKNOWN")
        self.assertEqual(context.rejection_fields["cfdi_xml"][0].value["gross_cents"], 1310)
        self.assertEqual(context.rejection_fields["cfdi_pdf"][0].value["gross_cents"], 1210)

    async def test_primary_selection_does_not_discard_untagged_or_failed_companions(self):
        failed = APAttachment("inbox/ap/TASK-ELSEWHERE/unknown.pdf", None, error="NO_CAPTURE")
        untyped = self.attachment({"description": "unidentified companion"}, "inbox/ap/TASK-ELSEWHERE/extra.pdf")
        context = await self.resolve(self.task((self.attachment(), failed, untyped)), financial_source_paths=(self.path,))
        self.assertIsNotNone(context.request)
        self.assertEqual(context.status, "UNKNOWN")
        self.assertEqual(len(context.bridge.source_issues), 1)
        self.assertEqual(len(context.bridge.unclassified_sources), 1)
        self.assertTrue(any("NO_CAPTURE" in note for note in context.diagnostics))
        self.assertTrue(any("extra.pdf" in note for note in context.diagnostics))

    async def test_multiple_financial_sources_require_explicit_row_projection(self):
        twin = self.attachment(path="inbox/ap/TASK-ELSEWHERE/twin.xml", media="application/xml")
        task = self.task((self.attachment(), twin))
        context = await self.resolve(task)
        self.assertEqual(context.lines, ())
        self.assertIsNone(context.primary_source)
        self.assertEqual(len(context.request.amount_sources), 2)
        context = await self.resolve(task, financial_source_paths=(self.path,))
        self.assertEqual(len(context.lines), 1)
        self.assertEqual(len(context.request.amount_sources), 2)
        with self.assertRaises(ValueError):
            await self.resolve(task, financial_source_paths=(self.path, twin.path))

    async def test_primary_selection_preserves_independent_arithmetic_and_conflicting_totals(self):
        twin = self.attachment(dict(self.fields, gross="13.10"),
            "inbox/ap/TASK-ELSEWHERE/twin.xml", "application/xml")
        context = await self.resolve(self.task((self.attachment(), twin)), financial_source_paths=(self.path,))
        self.assertEqual(len(context.request.amount_sources), 2)
        self.assertEqual([source.fields["gross_cents"][0].value for source in context.request.amount_sources],
                         [1210, 1310])
        self.assertIsNone(context.observation.amount_cents)
        self.assertEqual(context.status, "UNKNOWN")

    async def test_invalid_identifier_and_failed_normalization_remain_diagnosed_unknown(self):
        for invalid in (123, "@"):
            fields = dict(self.fields, supplier_tax_id=invalid, gross="malformed")
            context = await self.resolve(self.task((self.attachment(fields),)))
            self.assertEqual(context.status, "UNKNOWN")
            self.assertIsNone(context.request)
            self.assertTrue(any("SOURCE_OBSERVATION_UNKNOWN" in note for note in context.diagnostics))

    async def test_omitted_flags_withholding_guarantee_and_payable_basis_stay_unknown(self):
        context = await self.resolve()
        self.assertEqual(context.rejection_fields["withholding_required"], ())
        self.assertEqual(context.rejection_fields["cfdi_applicable"], ())
        self.assertEqual(context.rejection_fields["certification_applicable"], ())
        self.assertEqual(context.hold_fields["similar_domain"], ())
        self.assertEqual(context.hold_fields["signed_change_supported"], ())
        self.assertIsNone(context.request.guarantee_applicable)
        self.assertIsNone(context.request.source_payable_basis)
        self.assertIsNone(context.request.construction_subcontractor)

    async def test_observed_invoice_iban_reaches_strict_bank_certificate_validation(self):
        context = await self.resolve(self.task((self.attachment(dict(self.fields, iban="ES02NEW")),)))
        self.assertEqual(context.hold_fields["bank_differs"][0].value, True)
        candidates = context.request.hold_fields["invoice_bank_iban"]
        self.assertEqual({fact.value for fact in candidates}, {"ES02NEW"})
        self.assertEqual(candidates[0].evidence.document, self.path)

    async def test_explicit_master_absence_and_zero_are_distinct_from_omission(self):
        self.write("vendors", [dict(self.vendor, withholding=None, guarantee_retention_bp=0)])
        fields = dict(self.fields, source_payable_basis="AFTER_APPLIED_ADVANCES")
        context = await self.resolve(self.task((self.attachment(fields),)))
        self.assertEqual(context.rejection_fields["withholding_required"][0].value, False)
        self.assertEqual(context.rejection_fields["withholding_cents"], ())
        self.assertEqual(context.request.guarantee_applicable.value, False)
        self.assertEqual(context.request.source_payable_basis.value, "AFTER_APPLIED_ADVANCES")
        self.assertEqual(context.request.guarantee_applicable.evidence.document, "erp/vendors.jsonl")

    async def test_payable_is_never_filled_as_duplicate_gross(self):
        fields = dict(self.fields, payable="12.10")
        del fields["gross"]
        context = await self.resolve(self.task((self.attachment(fields),)))
        self.assertIsNone(context.observation.amount_cents)
        self.assertEqual(context.financial_facts.header.payable_cents.value, 1210)
        self.assertIsNone(context.request.source_payable_basis)
        self.assertEqual(context.status, "UNKNOWN")

    async def test_different_po_positions_do_not_become_an_invented_split(self):
        self.write("purchase_orders", [dict(self.order, items=[self.order["items"][0],
            dict(self.order["items"][0], item=50)])])
        fields = dict(self.fields)
        del fields["line.1.po_item"]
        context = await self.resolve(self.task((self.attachment(fields),)))
        match = context.lines[0].match
        self.assertEqual(match.reference.status, "AMBIGUOUS")
        self.assertEqual(len(match.reference.candidates), 2)
        self.assertIsNone(match.quantity_line)

    async def test_historical_partial_consumption_is_retained(self):
        invoice = dict(doc_id="OLD-DOC", company="CO-ALPHA", vendor="SUPPLIER-BETA", currency="EUR",
            kind="invoice", number="HIST-11", received_on="2031-11-06", posted_on="2031-11-07",
            gross=1000, decision="POST", journal_entry="OLD-JE")
        entry = dict(id="OLD-JE", company="CO-ALPHA", currency="EUR", source="AP", reference="HIST-11",
            posting_date="2031-11-07", document_date="2031-11-01", lines=[dict(account="40090000",
                debit=1000, credit=0, currency="EUR", amount_doc=1000, partner="SUPPLIER-BETA",
                assignment="ORDER-BETA/25")])
        self.write("ap_invoices", [invoice])
        self.write("ap_document_log", [invoice])
        self.write("journal_entries", [entry])
        context = await self.resolve()
        self.assertEqual(context.lines[0].match.reference.selected.available_milli, 1000)
        self.assertEqual(context.lines[0].match.quantity_status, "AVAILABLE")
        baseline = load_ap_erp_baseline(self.phase, grir_account="40090000")
        self.assertEqual(baseline.history.consumption.usages[0].quantity_milli, 1000)

    async def test_stale_erp_and_reception_outside_active_month_are_rejected(self):
        baseline = load_ap_erp_baseline(self.phase, grir_account="40090000")
        self.write("vendors", [dict(self.vendor, name="changed")])
        with self.assertRaisesRegex(ValueError, "differs from the active phase"):
            await self.resolve(baseline=baseline)
        context = await self.resolve(self.task(received="2031-12-10T09:30:00Z"))
        self.assertIsNone(context.request)
        self.assertIn("MESSAGE_RECEPTION_UNKNOWN", context.diagnostics)

    async def test_credit_and_advance_remain_explicitly_outside_this_adapter(self):
        for hint in ("Credit note", "Down payment request"):
            context = await self.resolve(self.task((self.attachment(dict(self.fields, document_type_hint=hint)),)))
            self.assertEqual(context.status, "UNSUPPORTED")
            self.assertIsNone(context.request)
            self.assertEqual(context.lines, ())


if __name__ == "__main__":
    unittest.main()
