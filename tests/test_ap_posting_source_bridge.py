"""Source-only monetary planning uses real catalogs without posting or defaults."""
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kalmora.ap_coding import CodingCatalog
from kalmora.ap_erp import load_ap_erp_baseline
from kalmora.ap_invoice_context import resolve_ap_invoice_context
from kalmora.ap_journal import AdvanceBalance, AdvanceState
from kalmora.ap_line_source_bridge import APLineSourceBinding
from kalmora.ap_pipeline import evaluate_ap_invoice
from kalmora.ap_posting_source_bridge import (
    APGuaranteePostingPlan, prepare_ap_invoice_posting,
)
from kalmora.ap_tax import TaxCatalog
from kalmora.ap_transaction import APTransactionState
from kalmora.ap_withholding import WithholdingCatalog
from kalmora.data import PhaseData
from kalmora.documents.ap_sources import APAttachment, APMessage, APTaskSources
from kalmora.documents.classification import classify_document
from kalmora.documents.contracts import ParsedBlock, ParsedDocument
from kalmora.documents.normalization import normalize_document_facts
from kalmora.facts import DocumentFacts, Evidence, Fact
from kalmora.money import RateTable


class PostingSourceBridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.phase = Path(self.tmp.name) / "arbitrary-phase"
        (self.phase / "erp").mkdir(parents=True)
        (self.phase / "tasks").mkdir()
        (self.phase / "tasks/close.json").write_text(json.dumps({"month": "2044-02"}))
        self.path = "inbox/ap/DOC-ZETA-2044/invoice.pdf"
        self.vendor = dict(id="SUPPLIER-ZETA", tax_id="TAX-ZETA", companies=["1100"],
            default_gl_account="62300000", default_tax_code="S21", default_cost_center="CC-ZETA",
            reconciliation_account="41000000", withholding=None, po_required=True,
            guarantee_applicable=False, construction_subcontractor=False,
            bank={"iban": "ES00ZETA"})
        self.order = dict(id="PO-ZETA-X", company="1100", vendor="SUPPLIER-ZETA", currency="EUR",
            created_on="2044-01-09", items=[dict(item=41, uom="hours", unit_price=10000,
                gl_account="62300000", cost_center="CC-ZETA", tax_code="S21")])
        self.receipt = dict(id="SES-ZETA-X", company="1100", vendor="SUPPLIER-ZETA", po="PO-ZETA-X",
            po_item=41, type="SES", quantity_milli=2000, amount=20000, posting_date="2044-02-03")
        self.tax_source = dict(tax_codes={
            "S21": dict(country="ES", kind="input", rate=2100),
            "SEX": dict(country="ES", kind="exempt", rate=0),
            "SISP": dict(country="ES", kind="reverse", rate=2100),
            "P23": dict(country="PT", kind="input", rate=2300)},
            withholdings={"IRPF15": dict(rate=1500, account="47510000")})
        self.write("companies", [dict(code="1100", tax_id="BUYER-ZETA", country="ES"),
                                 dict(code="1200", tax_id="BUYER-OTHER", country="ES")], json_file=True)
        self.write("vendors", [self.vendor])
        self.write("purchase_orders", [self.order])
        self.write("goods_receipts", [self.receipt])
        for name in ("ap_invoices", "ap_document_log", "journal_entries", "projects"):
            self.write(name, [])
        self.write("chart_of_accounts", [dict(account=code) for code in (
            "62300000", "62900000", "40000000", "41000000", "40300000", "40090000",
            "47200000", "47510000", "40000900", "40700000")])
        self.write("cost_centers", [dict(id="CC-ZETA", company="1100"), dict(id="CC-OTHER", company="1200")])
        self.write("tax_codes", self.tax_source, json_file=True)
        self.fields = dict(document_type_hint="Invoice", supplier_tax_id="TAX-ZETA",
            recipient_tax_id="BUYER-ZETA", invoice_number="INV-ZETA-2044", invoice_date="2044-02-01",
            currency="EUR", net="100.00", tax="21.00", gross="121.00", payable="121.00",
            withholding="0.00", retention="0.00", advance_amount="0.00", advance_applicable=False,
            source_payable_basis="AFTER_APPLIED_ADVANCES", po_reference="PO-ZETA-X",
            isp_required=False, vat_check_applicable=False, withholding_required=False,
            certification_applicable=False, cfdi_applicable=False,
            bank_differs=False, signed_change_supported=False, factoring_supported=False, similar_domain=False,
            **{"line.1.po_item": 41, "line.1.net": "100.00", "line.1.quantity": "1",
               "line.1.uom": "hours", "line.1.unit_price": "100.00"})
        self.cutoff = Fact("2044-02-20", Evidence("run-manifest", "observed_receipt_cutoff"))
        self.posted = Fact("2044-02-21", Evidence("run-manifest", "selected_posting_date"))

    def write(self, stem, rows, json_file=False):
        path = self.phase / "erp" / (stem + (".json" if json_file else ".jsonl"))
        path.write_text(json.dumps(rows) if json_file else "".join(json.dumps(row) + "\n" for row in rows))

    def attachment(self, fields=None, path=None):
        path = path or self.path
        fields = self.fields if fields is None else fields
        raw = DocumentFacts("a" * 64, "synthetic-monetary-v1", {name: [Fact(value,
            Evidence(path, "observed:" + name, 1, str(value)))] for name, value in fields.items()})
        document = ParsedDocument(path, raw.source_sha256,
            "application/xml" if path.endswith(".xml") else "application/pdf", "synthetic-parser",
            (ParsedBlock("BLOCK-ZETA", "\n".join(str(value) for value in fields.values()), 1),))
        return APAttachment(path, document, raw, normalized=normalize_document_facts(raw),
                            classification=classify_document(raw))

    async def context(self, fields=None, attachments=None, state=None):
        attachments = tuple(attachments) if attachments is not None else (self.attachment(fields),)
        message = APMessage("inbox/ap/DOC-ZETA-2044/message.json", "b" * 64, "2044-02-10T09:00:00Z",
            "EMAIL", "ap@zeta.invalid", "buyer@group.invalid", "Invoice", "Observed invoice",
            tuple(attachment.path for attachment in attachments), {"doc_id": "DOC-ZETA-2044"})
        task = APTaskSources("DOC-ZETA-2044", message, attachments)
        self.data = PhaseData(self.phase)
        self.baseline = load_ap_erp_baseline(self.phase, grir_account="40090000")
        self.state = state or APTransactionState(consumption=self.baseline.history.consumption)
        return await resolve_ap_invoice_context(task, data=self.data, baseline=self.baseline,
            state=self.state, receipt_as_of=self.cutoff, financial_source_paths=(attachments[0].path,))

    def prepare(self, context, **changes):
        options = dict(data=self.data, baseline=self.baseline, state=self.state, posting_date=self.posted,
            coding_catalog=changes.get("coding_catalog") or CodingCatalog.from_phase(self.data), tax_catalog=TaxCatalog(self.tax_source),
            withholding_catalog=WithholdingCatalog(self.tax_source),
            advance_plan=Fact(False, Evidence(self.path, "observed:advance_applicable")))
        options.update(changes)
        return prepare_ap_invoice_posting(context, **options)

    async def test_exact_order_preview_reaches_real_atomic_coordinator_without_consuming_preview(self):
        context = await self.context()
        before = self.state
        result = self.prepare(context)
        self.assertEqual(result.status, "READY", result.diagnostics)
        self.assertEqual((result.header.company, result.header.vendor_id, result.header.net,
                          result.header.tax, result.header.payable), ("1100", "SUPPLIER-ZETA", 10000, 2100, 12100))
        self.assertEqual(result.posting.quantity_lines[0].portions[0].order.item, 41)
        self.assertEqual(result.posting.coded_lines[0].line["po"], "PO-ZETA-X")
        self.assertEqual(result.posting.posting_date, "2044-02-21")
        self.assertEqual((before.rows, before.consumption.usages, before.advances.events), ((), (), ()))
        self.assertIsNone(context.request.posting)
        self.assertTrue(any(e.field.startswith("tax_codes.S21") for e in result.evidence))
        request = replace(result.request, duplicate_inventory_complete=Fact(True, Evidence("manifest", "complete_AP_documents")))
        unknown_payment = evaluate_ap_invoice(request, before, baseline=self.baseline)
        self.assertEqual(unknown_payment.status, "UNKNOWN")
        self.assertIs(unknown_payment.state, before)
        inventory = {kind: (Evidence("synthetic-complete-notices", "empty_inventory"),) for kind in (
            "FACTORING_NOTICE", "TAX_GARNISHMENT_ORDER", "CONTRACTOR_TAX_CERTIFICATE", "BANK_DETAILS_CHANGE")}
        request = replace(request, event_inventory_evidence=inventory)
        committed = evaluate_ap_invoice(request, before, baseline=self.baseline,
            tax_catalog=TaxCatalog(self.tax_source), withholding_catalog=WithholdingCatalog(self.tax_source))
        self.assertEqual(committed.status, "COMMITTED", committed.diagnostics)
        self.assertEqual(committed.row["decision"], "POST")
        self.assertEqual(committed.state.consumption.usages[0].quantity_milli, 1000)
        self.assertEqual(before.consumption.usages, ())

    async def test_unknown_and_positive_advance_applicability_do_not_invent_empty_state(self):
        state = APTransactionState(advances=AdvanceState((AdvanceBalance("DEP-ZETA", "1100", "SUPPLIER-ZETA",
            "EUR", "DEPOSIT-ZETA", "2044-01-10", "PO-ZETA-X", 10000, 10000, 10000, 10000),)))
        context = await self.context(state=state)
        for plan, expected in ((None, "UNKNOWN"), (Fact(None, Evidence("contract", "applies")), "UNKNOWN"),
                               (Fact(True, Evidence("contract", "applies")), "UNSUPPORTED")):
            with self.subTest(plan=plan):
                result = self.prepare(context, advance_plan=plan)
                self.assertEqual(result.status, expected)
                self.assertIs(result.request, context.request)
                self.assertIsNone(result.posting)
                self.assertEqual(self.state, state)
        self.assertEqual(self.prepare(context).status, "READY")
        self.assertEqual(self.state.advances.balances[0].used_doc, 10000)
        contradictory = await self.context({**self.fields, "advance_applicable": True}, state=state)
        self.assertIn("SOURCE_ADVANCE_APPLICATION_CONFLICT", self.prepare(contradictory).diagnostics)

    async def test_missing_net_discount_or_missing_guarantee_stays_unknown(self):
        fields = dict(self.fields)
        del fields["line.1.net"]
        fields.update({"line.1.amount": "110.00", "line.1.discount": "10.00"})
        context = await self.context(fields)
        result = self.prepare(context)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertTrue(any("EXPLICIT_NET_REQUIRED" in diagnostic for diagnostic in result.diagnostics))
        self.assertIs(result.request, context.request)
        self.vendor.pop("guarantee_applicable")
        self.write("vendors", [self.vendor])
        context = await self.context()
        self.assertIn("GUARANTEE_APPLICABILITY_UNKNOWN", self.prepare(context).diagnostics)

    async def test_undiscounted_line_amount_is_the_line_net(self):
        fields = dict(self.fields)
        del fields["line.1.net"]
        for discount in ({}, {"line.1.discount": "0.00"}):
            context = await self.context({**fields, "line.1.amount": "100.00", **discount})
            result = self.prepare(context)
            self.assertEqual(result.status, "READY", result.diagnostics)
            self.assertEqual(result.posting.valuation_lines[0].amount_doc, 10000)

    async def test_wrong_addressee_keeps_structural_request_for_early_rejection(self):
        context = await self.context({**self.fields, "recipient_tax_id": "BUYER-OTHER"})
        result = self.prepare(context)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIs(result.request, context.request)
        request = replace(result.request, duplicate_inventory_complete=Fact(True, Evidence("manifest", "complete_AP_documents")))
        rejected = evaluate_ap_invoice(request, self.state, baseline=self.baseline)
        self.assertEqual((rejected.status, rejected.row["decision"], rejected.row["reasons"]),
                         ("DECIDED", "REJECT", ["WRONG_ADDRESSEE"]))
        self.assertIs(rejected.state, self.state)

    async def test_technical_ready_does_not_bypass_quantity_or_price_policy(self):
        cases = (({"line.1.quantity": "3", "line.1.net": "300.00", "net": "300.00",
                   "tax": "63.00", "gross": "363.00", "payable": "363.00"}, "QTY_NOT_RECEIVED"),
                 ({"line.1.unit_price": "200.00", "line.1.net": "200.00", "net": "200.00",
                   "tax": "42.00", "gross": "242.00", "payable": "242.00"}, "PRICE_VARIANCE"))
        for changed, reason in cases:
            with self.subTest(reason=reason):
                fields = {**self.fields, **changed}
                if reason == "QTY_NOT_RECEIVED":
                    del fields["line.1.unit_price"]  # The earlier shortage still wins.
                context = await self.context(fields)
                result = self.prepare(context)
                self.assertEqual(result.status, "READY", result.diagnostics)
                request = replace(result.request, duplicate_inventory_complete=Fact(True, Evidence("manifest", "complete_AP_documents")))
                held = evaluate_ap_invoice(request, self.state, baseline=self.baseline)
                self.assertEqual((held.status, held.row["decision"], held.row["reasons"]),
                                 ("DECIDED", "HOLD", [reason]))
                self.assertIs(held.state, self.state)

    async def test_multipart_line_and_missing_master_are_not_invented(self):
        context = await self.context()
        line = context.lines[0]
        quantity = line.match.quantity_line
        portion = replace(quantity.portions[0], quantity_milli=500)
        line = replace(line, match=replace(line.match, quantity_line=replace(quantity, portions=(portion, portion))))
        result = self.prepare(replace(context, lines=(line,)))
        self.assertEqual(result.status, "UNSUPPORTED")
        self.assertIn("MULTIPART_ORDER_LINE_NOT_IMPLEMENTED", result.diagnostics)
        catalog = CodingCatalog.from_phase(self.data)
        (self.phase / "erp/cost_centers.jsonl").unlink()
        result = self.prepare(context, coding_catalog=catalog)
        self.assertIn("ACTIVE_POSTING_MASTER_UNRESOLVED", result.diagnostics)

    async def test_document_foreign_cost_object_or_tax_code_cannot_fall_back_to_vendor(self):
        for additions in ({"line.1.cost_center": "CC-OTHER"}, {"line.1.tax_code": "P23"},
                          {"line.1.cost_center": None}):
            with self.subTest(additions=additions):
                context = await self.context({**self.fields, **additions})
                result = self.prepare(context)
                self.assertEqual(result.status, "UNKNOWN")
                self.assertIsNone(result.posting)
                self.assertIs(result.request, context.request)

    async def test_named_work_reaches_coding_by_active_id_while_source_name_stays_intact(self):
        self.write("projects", [dict(id="PROJECT-ZETA", company="1100", name="Edificio del Estuario",
                                     wbs=[dict(id="WBS-ZETA")])])
        self.order["project"] = "PROJECT-ZETA"
        self.order["items"][0].pop("cost_center")
        self.order["items"][0]["wbs"] = "WBS-ZETA"
        self.write("purchase_orders", [self.order])
        printed = " edificio DEL   estuario "
        context = await self.context({**self.fields, "line.1.project_reference": printed})
        self.assertEqual(context.lines[0].query.project, "PROJECT-ZETA")
        catalog = CodingCatalog.from_phase(self.data)
        with patch.object(catalog, "resolve", wraps=catalog.resolve) as resolve:
            result = self.prepare(context, coding_catalog=catalog)
            self.assertEqual(result.status, "READY", result.diagnostics)
            self.assertEqual(resolve.call_args.args[0].project, "PROJECT-ZETA")
        self.assertEqual(result.posting.valuation_lines[0].assignment.wbs, "WBS-ZETA")
        self.assertEqual(context.lines[0].source.field("project_reference").value, printed.strip())
        self.assertEqual(context.primary_source.raw.field("line.1.project_reference").value, printed)
        self.assertTrue(any(e.field == "id=PROJECT-ZETA.id" for e in result.evidence))

    async def test_independent_attachments_need_explicit_equivalences_and_coding_consensus(self):
        twin_path = "inbox/ap/DOC-ZETA-2044/twin.xml"
        context = await self.context(attachments=(self.attachment(), self.attachment(path=twin_path)))
        self.assertIn("FINANCIAL_ROW_EQUIVALENCES_REQUIRED", self.prepare(context).diagnostics)
        line_id = context.lines[0].source.line_id
        bindings = (APLineSourceBinding(line_id, self.path, 1), APLineSourceBinding(line_id, twin_path, 1))
        result = self.prepare(context, bindings=bindings)
        self.assertEqual(result.status, "READY", result.diagnostics)
        self.assertEqual(len(result.request.amount_sources), 2)
        self.assertEqual(result.header.net, 10000)
        self.assertEqual(len(result.posting.valuation_lines), 1)
        conflicting = {**self.fields, "line.1.account": "62900000"}
        original = {**self.fields, "line.1.account": "62300000"}
        context = await self.context(attachments=(self.attachment(original), self.attachment(conflicting, twin_path)))
        result = self.prepare(context, bindings=bindings)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertTrue(any("DOCUMENT_CODING_UNKNOWN" in diagnostic for diagnostic in result.diagnostics))
        context = await self.context(attachments=(self.attachment({**self.fields, "line.1.tax": "21.00"}),
            self.attachment({**self.fields, "line.1.tax": "20.00"}, twin_path)))
        result = self.prepare(context, bindings=bindings)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertTrue(any("SOURCE_LINE_TAX_UNKNOWN" in diagnostic for diagnostic in result.diagnostics))

    async def test_unclassified_companion_cannot_disappear_from_monetary_preparation(self):
        companion = self.attachment({"description": "uninterpreted financial attachment"},
                                    "inbox/ap/DOC-ZETA-2044/unknown.pdf")
        context = await self.context(attachments=(self.attachment(), companion))
        result = self.prepare(context)
        self.assertIn("FINANCIAL_SOURCE_INVENTORY_UNRESOLVED", result.diagnostics)
        self.assertIs(result.request, context.request)

    async def test_direct_expense_requires_positive_proof_of_no_quantity_gate(self):
        self.vendor["po_required"] = False
        self.write("vendors", [self.vendor])
        self.write("purchase_orders", [])
        self.write("goods_receipts", [])
        fields = {name: value for name, value in self.fields.items() if name not in {"po_reference", "line.1.po_item"}}
        fields["quantity_check_applicable"] = False
        context = await self.context(fields)
        result = self.prepare(context)
        self.assertEqual(result.status, "READY", result.diagnostics)
        self.assertEqual(result.posting.quantity_lines, ())
        self.assertIsNone(result.posting.valuation_lines[0].quantity_milli)
        del fields["quantity_check_applicable"]
        context = await self.context(fields)  # the master's PO-free vendor without any recorded order
        self.assertEqual(self.prepare(context).status, "READY")
        self.write("purchase_orders", [dict(self.order, id="PO-ZETA-OPTIONAL")])
        context = await self.context(fields)
        self.assertEqual(self.prepare(context).status, "UNKNOWN")
        self.write("purchase_orders", [])
        del self.vendor["po_required"]
        self.write("vendors", [self.vendor])
        context = await self.context(fields)
        self.assertEqual(self.prepare(context).status, "UNKNOWN")
        fields.update(quantity_check_applicable=False, po_reference="UNRESOLVED-PRINTED-PO")
        context = await self.context(fields)
        self.assertEqual(self.prepare(context).status, "UNKNOWN")

    async def test_withholding_preview_matches_observed_deductions_without_substituting_them(self):
        self.vendor["withholding"] = "IRPF15"
        self.write("vendors", [self.vendor])
        fields = {**self.fields, "withholding": "15.00", "payable": "106.00", "withholding_required": True}
        context = await self.context(fields)
        result = self.prepare(context)
        self.assertEqual((result.status, result.header.withholding, result.header.payable), ("READY", 1500, 10600))
        context = await self.context({**fields, "withholding": "14.00"})
        self.assertEqual(self.prepare(context).status, "UNKNOWN")
        context = await self.context({name: value for name, value in fields.items() if name != "source_payable_basis"})
        self.assertIn("SOURCE_PAYABLE_BASIS_UNKNOWN", self.prepare(context).diagnostics)

    async def test_guarantee_requires_source_bound_base_and_contract_reference(self):
        self.vendor["guarantee_applicable"] = True
        self.write("vendors", [self.vendor])
        fields = {**self.fields, "retention": "5.00", "payable": "116.00",
                  "guarantee_base_cents": 10000, "contract_reference": "CONTRACT-ZETA"}
        context = await self.context(fields)
        self.assertEqual(self.prepare(context).status, "UNKNOWN")
        base = context.financial_facts.integer("guarantee_base_cents").candidates[0]
        reference = context.financial_facts.text("contract_reference").candidates[0]
        plan = APGuaranteePostingPlan(base, reference)
        result = self.prepare(context, guarantee_plan=plan)
        self.assertEqual((result.status, result.header.retention, result.header.payable), ("READY", 500, 11600))
        invented = APGuaranteePostingPlan(Fact(10000, Evidence("other-contract", "base")),
                                        Fact("CONTRACT-ZETA", Evidence("other-contract", "id")))
        self.assertIn("GUARANTEE_PLAN_SOURCE_UNCONFIRMED", self.prepare(context, guarantee_plan=invented).diagnostics)

    async def test_invoice_date_fx_is_exact_source_bound_and_posting_date_never_defaulted(self):
        self.order["currency"] = "USD"
        self.write("purchase_orders", [self.order])
        fx = [dict(date="2044-01-31", base="EUR", currency="USD", rate="1.25"),
              dict(date="2044-02-09", base="EUR", currency="USD", rate="1.50")]
        self.write("fx_rates", fx)
        context = await self.context({**self.fields, "currency": "USD"})
        self.assertIn("SOURCE_FX_RATES_REQUIRED", self.prepare(context).diagnostics)
        result = self.prepare(context, rates=RateTable(fx))
        self.assertEqual(result.status, "READY", result.diagnostics)
        self.assertEqual(result.header.currency, "USD")
        self.assertTrue(any(e.field == "date=2044-01-31;currency=USD.rate" for e in result.evidence))
        wrong_rates = RateTable([dict(date="2044-01-31", base="EUR", currency="USD", rate=Decimal("2"))])
        self.assertIn("ACTIVE_FX_CATALOG_MISMATCH", self.prepare(context, rates=wrong_rates).diagnostics)
        result = self.prepare(context, posting_date=Fact(None, Evidence("run", "missing_posting_date")))
        self.assertEqual(result.status, "UNKNOWN")

    async def test_caller_catalogs_and_phase_snapshots_cannot_substitute_other_rules(self):
        context = await self.context()
        different = {**self.tax_source, "tax_codes": {**self.tax_source["tax_codes"],
            "S21": dict(country="ES", kind="input", rate=1000)}}
        self.assertIn("ACTIVE_TAX_CATALOG_MISMATCH", self.prepare(context, tax_catalog=TaxCatalog(different)).diagnostics)
        self.order["items"][0]["unit_price"] = 9999
        self.write("purchase_orders", [self.order])
        result = self.prepare(context)
        self.assertIn("ACTIVE_ERP_SNAPSHOT_CHANGED", result.diagnostics)
        self.assertIs(result.request, context.request)

    async def test_source_symlinks_are_rejected_before_any_forbidden_open(self):
        context = await self.context()
        catalog = CodingCatalog.from_phase(self.data)
        outside = Path(self.tmp.name) / "outside-phase"
        outside.mkdir()
        forbidden = self.phase / "golden"
        forbidden.mkdir()
        native_open = Path.open

        def guarded_open(path, *args, **kwargs):
            resolved = path.resolve()
            self.assertFalse(resolved.is_relative_to(outside), f"opened outside source: {path}")
            self.assertNotIn("golden", resolved.parts, f"opened Golden source: {path}")
            return native_open(path, *args, **kwargs)

        for relative in ("tasks/close.json", "erp/chart_of_accounts.jsonl", "erp/projects.jsonl"):
            source = self.phase / relative
            original = source.read_bytes()
            for directory in (outside, forbidden):
                with self.subTest(source=relative, target=directory.name):
                    target = directory / source.name
                    target.write_bytes(original)
                    source.unlink()
                    source.symlink_to(target)
                    try:
                        with patch.object(Path, "open", guarded_open):
                            result = self.prepare(context, coding_catalog=catalog)
                        self.assertEqual(result.status, "UNKNOWN")
                        self.assertIs(result.request, context.request)
                        self.assertIsNone(result.posting)
                    finally:
                        source.unlink()
                        source.write_bytes(original)

        self.order["currency"] = "USD"
        self.write("purchase_orders", [self.order])
        fx = [dict(date="2044-01-31", base="EUR", currency="USD", rate="1.25")]
        self.write("fx_rates", fx)
        context = await self.context({**self.fields, "currency": "USD"})
        catalog = CodingCatalog.from_phase(self.data)
        source = self.phase / "erp/fx_rates.jsonl"
        original = source.read_bytes()
        for directory in (outside, forbidden):
            with self.subTest(source="fx_rates", target=directory.name):
                target = directory / source.name
                target.write_bytes(original)
                source.unlink()
                source.symlink_to(target)
                try:
                    with patch.object(Path, "open", guarded_open):
                        result = self.prepare(context, coding_catalog=catalog, rates=RateTable(fx))
                    self.assertEqual(result.status, "UNKNOWN")
                    self.assertIn("SOURCE_FX_RATE_UNKNOWN", result.diagnostics)
                finally:
                    source.unlink()
                    source.write_bytes(original)

    async def test_master_redirected_after_calculation_is_rejected_before_revalidation_read(self):
        context = await self.context()
        catalog = CodingCatalog.from_phase(self.data)
        source = self.phase / "erp/chart_of_accounts.jsonl"
        outside = Path(self.tmp.name) / "outside-chart.jsonl"
        outside.write_bytes(source.read_bytes())
        original_resolve, native_open = catalog.resolve, Path.open

        def redirect_after_coding(query, **kwargs):
            result = original_resolve(query, **kwargs)
            source.unlink()
            source.symlink_to(outside)
            return result

        def guarded_open(path, *args, **kwargs):
            self.assertNotEqual(path.resolve(), outside, f"read redirected master: {path}")
            return native_open(path, *args, **kwargs)

        with patch.object(catalog, "resolve", side_effect=redirect_after_coding), patch.object(Path, "open", guarded_open):
            result = self.prepare(context, coding_catalog=catalog)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("ACTIVE_MASTER_SNAPSHOT_CHANGED", result.diagnostics)
        self.assertIs(result.request, context.request)
        self.assertEqual(self.state.consumption.usages, ())


if __name__ == "__main__":
    unittest.main()
