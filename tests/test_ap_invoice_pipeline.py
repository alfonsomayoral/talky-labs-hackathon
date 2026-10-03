"""Real policy/factory composition, independent of task IDs and Golden."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from kalmora.ap_allocation import ConsumptionState
from kalmora.ap_erp import APERPBaseline
from kalmora.ap_history import HistoricalDemand, HistoricalReceipt, reconcile_receipt_history
from kalmora.ap_journal import AdvanceApplication, AdvanceBalance, AdvanceState, InvoiceLineOrder
from kalmora.ap_holds import PriceLine, PricePortion
from kalmora.ap_line_source_bridge import APLineSourceBinding
from kalmora.ap_output import validate_ap_row
from kalmora.ap_pipeline import APInvoiceRequest, evaluate_ap_invoice
from kalmora.ap_transaction import APTransactionState
from kalmora.ap_withholding import ContractGuarantee, WithholdingBase
from kalmora.facts import DocumentFacts, Evidence, Fact
from kalmora.model.ap_duplicate_record import DuplicateRecord
from kalmora.model.ap_event import ApEvent
from kalmora.model.ap_scope import ApScope
from kalmora.model.ap_timeline_state import ApTimelineState
from tests import test_ap_transaction as transaction_fixtures


class APInvoicePipelineTests(unittest.TestCase):
    def setUp(self):
        # Reuse monetary fixture data; this suite tests the new policy connection,
        # rather than running the transaction unit tests again.
        self.fixture = transaction_fixtures.APTransactionIntegrationTests()
        self.fixture.setUp()
        receipt = self.fixture.receipt
        snapshot = reconcile_receipt_history((HistoricalReceipt(receipt, 20000, 10000,
            (Evidence("erp/goods_receipts.jsonl", "id=R-OTHER"),)),),
            (HistoricalDemand(receipt.order, 10000, (Evidence("erp/journal_entries.jsonl", "GRIR"),)),),
            inventory_complete=self.fact(True, "complete ERP"))
        snapshot = replace(snapshot, consumption=self.fixture.baseline.consumption)
        posting = self.fixture.request().posting
        self.baseline = APERPBaseline("2026-09", (), posting.order_catalog, posting.receipt_catalog,
                                      posting.order_prices, snapshot, (), ())
        self.state = self.fixture.baseline

    def fact(self, value, name):
        return Fact(value, Evidence("synthetic/policy-context.json", name))

    def request(self, identifier="OPAQUE-SYNTHETIC"):
        posting = self.fixture.request(identifier).posting
        header = posting.header
        path = "synthetic/invoice.xml"
        amounts = DocumentFacts("a" * 64, "synthetic-normalized", {
            k: [Fact(v, Evidence(path, k))] for k, v in (
                ("net_cents", header.net), ("tax_cents", header.tax), ("gross_cents", header.gross),
                ("document_number", header.invoice_number), ("document_date", header.invoice_date),
                ("currency", header.currency), ("line.1.quantity_milli", 1000),
                ("line.1.unit_price_e4", 1000000), ("line.1.uom", "ud"), ("line.1.net_cents", 10000))})
        fields = {k: [self.fact(v, k)] for k, v in {
            "recipient_nif": "A-SOURCE", "recipient_company": "1100", "order_company": "1100",
            "isp_required": False, "vat_check_applicable": False, "withholding_required": False,
            "certification_applicable": False, "cfdi_applicable": False}.items()}
        fields.update(amounts.fields)
        holds = {k: [self.fact(v, k)] for k, v in {
            "vendor_in_master": True, "bank_differs": False, "similar_domain": False,
            "signed_change_supported": False, "factoring_supported": False,
            "quantity_check_applicable": True, "price_check_applicable": True}.items()}
        observation = DuplicateRecord(identifier, header.company, header.vendor_id, header.currency,
            header.invoice_number, "2026-09-11T10:00:00", header.gross,
            (Evidence(path, "invoice header"),), status="RECEIVED")
        inventory = {kind: (Evidence("synthetic/notices.json", "complete inventory"),) for kind in (
            "FACTORING_NOTICE", "TAX_GARNISHMENT_ORDER", "CONTRACTOR_TAX_CERTIFICATE", "BANK_DETAILS_CHANGE")}
        return APInvoiceRequest(observation=observation, duplicate_inventory_complete=self.fact(True, "duplicates"),
            rejection_fields=fields, amount_sources=(amounts,), hold_fields=holds,
            construction_subcontractor=self.fact(False, "construction"),
            event_inventory_evidence=inventory, invoice_date=Fact(header.invoice_date, Evidence(path, "document date")),
            header=header, posting=posting, quantity_evidence=(Evidence(path, "source line quantity"),),
            guarantee_applicable=self.fact(False, "observed no contractual guarantee"),
            line_source_bindings=(APLineSourceBinding("L-OTHER", path, 1),),
            receipt_inventory_complete=self.fact(True, "receipts"),
            receipt_as_of=Fact(posting.receipt_as_of, Evidence("synthetic/processing.json", "observed processing cutoff")),
            price_lines=(PriceLine("L-OTHER", (self.fact(10000, "invoice price"),), (
                PricePortion(self.fixture.order, 1000, (self.fact(10000, "PO price"),)),)),))

    def run_invoice(self, request, state=None, **options):
        return evaluate_ap_invoice(request, self.state if state is None else state, baseline=self.baseline,
            tax_catalog=self.fixture.tax_catalog, withholding_catalog=self.fixture.withholding_catalog,
            context=self.fixture.context, **options)

    def source_fields(self, request, **values):
        source = request.amount_sources[0]
        fields = dict(source.fields)
        fields.update({name: [Fact(value, Evidence("synthetic/invoice.xml", name))]
                       for name, value in values.items()})
        return replace(request, amount_sources=(replace(source, fields=fields),))

    def test_observed_deductions_cannot_be_ignored_by_zero_posting(self):
        request = self.direct(self.request())
        for name in ("withholding_cents", "retention_cents", "guarantee_amount_cents"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "deductions differ"):
                self.run_invoice(self.source_fields(request, **{name: 3000}))
        conflict = self.source_fields(request, withholding_cents=0)
        source = conflict.amount_sources[0]
        fields = dict(source.fields, withholding_cents=[
            Fact(0, Evidence("synthetic/invoice.xml", "quota/first")),
            Fact(3000, Evidence("synthetic/invoice.xml", "quota/second"))])
        result = self.run_invoice(replace(conflict, amount_sources=(replace(source, fields=fields),)))
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIs(result.state, self.state)

    def test_known_withholding_and_guarantee_reach_real_calculation(self):
        request = self.direct(self.request())
        wh = self.source_fields(request, withholding_cents=1500)
        wh = replace(wh, posting=replace(wh.posting, header=replace(wh.posting.header,
            withholding=1500, payable=8500), withholding_bases=(WithholdingBase("L-OTHER", 10000, ("IRPF15",)),)))
        self.assertEqual(self.run_invoice(wh).row["withholding"], 1500)
        retention = self.source_fields(request, retention_cents=500)
        retention = replace(retention, guarantee_applicable=self.fact(True, "signed contract guarantee"),
            posting=replace(retention.posting, header=replace(retention.posting.header,
                retention=500, payable=9500), guarantee=ContractGuarantee(10000, "CONTRACT-OBSERVED", rate=500)))
        self.assertEqual(self.run_invoice(retention).row["retention"], 500)
        missing = self.run_invoice(replace(request, guarantee_applicable=None))
        self.assertEqual(missing.diagnostics, ("GUARANTEE_APPLICABILITY_UNKNOWN",))

    def test_printed_payable_requires_evidenced_semantics_and_preserves_conflicts(self):
        request = self.source_fields(self.direct(self.request()), payable_cents=10000)
        unresolved = self.run_invoice(request)
        self.assertEqual(unresolved.diagnostics, ("SOURCE_PAYABLE_BASIS_UNKNOWN",))
        observed = replace(request, source_payable_basis=self.fact("AFTER_APPLIED_ADVANCES", "printed balance"))
        self.assertEqual(self.run_invoice(observed).status, "COMMITTED")
        with self.assertRaisesRegex(ValueError, "printed payable"):
            self.run_invoice(self.source_fields(observed, payable_cents=9999))

    def test_printed_payable_before_advance_is_compared_without_rewriting_source(self):
        request = self.source_fields(self.request(), payable_cents=10000)
        balance = AdvanceBalance("ADV-SOURCE", "1100", "SUP-OTHER", "EUR", "DEP-SOURCE",
                                 "2026-08-01", "PO-OTHER", 4000, 4000)
        state = APTransactionState(self.state.consumption, AdvanceState((balance,), (
            ("1100", "SUP-OTHER", "EUR", "ADV-SOURCE"),)))
        request = replace(request, source_payable_basis=self.fact("BEFORE_APPLIED_ADVANCES", "printed pre-application amount"),
            posting=replace(request.posting, header=replace(request.posting.header, payable=8000),
                advances=(AdvanceApplication("ADV-SOURCE", 2000, "NON_MONETARY", "observed:contract",
                                             self.fixture.coding, "L-OTHER"),), invoice_orders=("PO-OTHER",),
                order_bindings=(InvoiceLineOrder("L-OTHER", "PO-OTHER", 10000, "observed:source-po"),)))
        result = self.run_invoice(request, state)
        self.assertEqual(result.row["payable"], 8000)
        self.assertEqual(request.amount_sources[0].fields["payable_cents"][0].value, 10000)
        self.assertEqual(state.advances.balances[0].used_doc, 0)
        with self.assertRaisesRegex(ValueError, "printed payable"):
            self.run_invoice(replace(request, source_payable_basis=self.fact("AFTER_APPLIED_ADVANCES", "wrong basis")), state)

    def test_source_date_number_and_currency_cannot_be_replaced_by_posting_context(self):
        request = self.direct(self.request())
        for name, value in (("document_date", "2031-11-01"), ("document_number", "ANOTHER-INVOICE"),
                            ("currency", "USD")):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "identity/date/currency|posting currency"):
                self.run_invoice(self.source_fields(request, **{name: value}))

    def test_invoice_price_and_quantity_checks_are_bound_to_original_source_rows(self):
        request = self.request()
        source_price = self.source_fields(request, **{"line.1.unit_price_e4": 2000000})
        with self.assertRaisesRegex(ValueError, "price check contradicts"):
            self.run_invoice(source_price)
        source_quantity = self.source_fields(request, **{"line.1.quantity_milli": 2000})
        with self.assertRaisesRegex(ValueError, "quantity contradicts"):
            self.run_invoice(source_quantity)
        unknown = self.run_invoice(replace(request, line_source_bindings=()))
        self.assertEqual(unknown.status, "UNKNOWN")
        self.assertIsNone(unknown.row)
        self.assertIs(unknown.state, self.state)
        self.assertEqual(self.state.consumption.usages[0].quantity_milli, 1000)

    def test_real_post_commits_once_after_all_gates_and_replay_has_no_provider(self):
        request = self.request()
        with patch("socket.create_connection", side_effect=AssertionError("provider disabled")):
            first = self.run_invoice(request)
            replay = self.run_invoice(request)
        self.assertEqual(first.row, replay.row)
        self.assertEqual(first.status, "COMMITTED")
        self.assertEqual(first.stages, (("duplicate", "CLEAR"), ("rejection", "CLEAR"),
            ("hold", "CLEAR"), ("payment", "POST"), ("posting", "COMMITTED")))
        self.assertEqual(first.state.consumption.usages[0].quantity_milli, 2000)
        self.assertEqual(self.state.consumption.usages[0].quantity_milli, 1000)
        self.assertEqual(validate_ap_row(first.row, self.fixture.context, tax_catalog=self.fixture.tax_catalog), ())
        with self.assertRaisesRegex(ValueError, "already committed"):
            self.run_invoice(request, first.state)

    def test_duplicate_precedes_rejection_and_never_calls_posting(self):
        request = self.request()
        fields = dict(request.rejection_fields, recipient_nif=[self.fact(None, "observed missing NIF")])
        prior = replace(request.observation, doc_id="EARLIER", received_at="2026-09-10T10:00:00")
        with patch("kalmora.ap_pipeline.commit_ap_transaction", side_effect=AssertionError("no posting")):
            result = self.run_invoice(replace(request, rejection_fields=fields), history=(prior,))
        self.assertEqual(result.row["decision"], "DUPLICATE")
        self.assertEqual(result.row["duplicate_of"], "EARLIER")
        self.assertNotIn("journal_entry", result.row)
        self.assertIs(result.state, self.state)

    def test_rejection_precedes_bank_hold_and_unknown_does_not_become_hold(self):
        request = self.request()
        holds = dict(request.hold_fields, bank_differs=[self.fact(True, "observed changed bank")])
        fields = dict(request.rejection_fields, recipient_nif=[self.fact(None, "observed missing NIF")])
        with patch("kalmora.ap_pipeline.allocate_receipts", side_effect=AssertionError("no allocation")):
            rejected = self.run_invoice(replace(request, hold_fields=holds, rejection_fields=fields))
            unknown = self.run_invoice(replace(request, rejection_fields=dict(fields, recipient_nif=[])))
        self.assertEqual(rejected.row["reasons"], ["MANDATORY_FIELD_MISSING"])
        self.assertEqual(unknown.status, "UNKNOWN")
        self.assertIsNone(unknown.row)
        self.assertIs(unknown.state, self.state)

    def test_bank_hold_stops_before_allocation_and_price_hold_discards_tentative_consumption(self):
        request = self.request()
        with patch("kalmora.ap_pipeline.allocate_receipts", side_effect=AssertionError("no allocation")):
            bank = self.run_invoice(replace(request, hold_fields=dict(request.hold_fields,
                bank_differs=[self.fact(True, "changed bank")])))
        self.assertEqual(bank.row["reasons"], ["BANK_DETAILS_CHANGED"])
        line = replace(request.price_lines[0], invoice_unit_price_cents=(self.fact(10201, "actual excessive price"),))
        price_request = self.source_fields(replace(request, price_lines=(line,)), **{"line.1.unit_price_e4": 1020100})
        price = self.run_invoice(price_request)
        self.assertEqual(price.row["reasons"], ["PRICE_VARIANCE"])
        for result in (bank, price):
            self.assertIs(result.state, self.state)
            self.assertNotIn("journal_entry", result.row)

    def test_expired_certificate_blocks_payment_but_still_posts_real_journal(self):
        request = replace(self.request(), construction_subcontractor=self.fact(True, "subcontractor"))
        result = self.run_invoice(request)
        self.assertEqual(result.row["decision"], "POST_PAYMENT_BLOCK")
        self.assertEqual(result.row["payment_block"], "CONTRACTOR_CERTIFICATE_EXPIRED")
        self.assertIn("journal_entry", result.row)

    def test_unknown_historical_receipts_cannot_be_converted_to_quantity_hold(self):
        request = self.request()
        receipt = self.fixture.receipt
        receipts = (replace(receipt, quantity_milli=1000), replace(receipt, receipt_id="OTHER-R", quantity_milli=1000))
        history = reconcile_receipt_history(tuple(HistoricalReceipt(r, 10000, 10000,
            (Evidence("erp/goods_receipts.jsonl", r.receipt_id),)) for r in receipts),
            (HistoricalDemand(receipt.order, 10000, (Evidence("erp/journal_entries.jsonl", "GRIR"),)),),
            inventory_complete=self.fact(True, "complete ERP"))
        self.baseline = replace(self.baseline, receipts=receipts, history=history)
        self.state = APTransactionState(history.consumption)
        quantity = replace(request.posting.quantity_lines[0], portions=(replace(
            request.posting.quantity_lines[0].portions[0], receipt_ids=()),))
        request = replace(request, posting=replace(request.posting, receipt_catalog=receipts, quantity_lines=(quantity,)))
        result = self.run_invoice(request)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.diagnostics, ("HISTORICAL_RECEIPT_CAPACITY_UNKNOWN",))
        self.assertIs(result.state, self.state)
        self.assertIsNone(result.row)

    def test_late_output_failure_leaves_original_state_available_for_a_different_invoice(self):
        request = self.request()
        with self.assertRaises(ValueError):
            self.run_invoice(replace(request, posting=replace(request.posting,
                header=replace(request.posting.header, payable=9999))))
        next_result = self.run_invoice(self.request("UNRELATED-ID"))
        self.assertEqual(next_result.status, "COMMITTED")
        self.assertEqual(self.state.consumption.usages[0].quantity_milli, 1000)

    def test_phase_and_history_are_mandatory_even_without_po_posting(self):
        request = self.request()
        for bad_state, bad_month in ((APTransactionState(), None), (self.state, "2031-11")):
            baseline = self.baseline
            if bad_month:
                self.baseline = replace(baseline, month=bad_month)
            with self.assertRaises(ValueError):
                self.run_invoice(request, bad_state)
            self.baseline = baseline

    def direct(self, request):
        line = request.posting.coded_lines[0]
        posting = replace(request.posting, quantity_lines=(), valuation_lines=(replace(
            request.posting.valuation_lines[0], quantity_milli=None),), coded_lines=(replace(
                line, line=dict(line.line, po=None, po_item=None)),))
        return replace(request, posting=posting, hold_fields=dict(request.hold_fields,
            quantity_check_applicable=[self.fact(False, "direct invoice")],
            price_check_applicable=[self.fact(False, "direct invoice")]))

    def test_monthly_duplicate_is_detected_from_atomic_publication_without_manual_history(self):
        first_request = self.direct(self.request())
        first = self.run_invoice(first_request)
        second_request = replace(first_request, observation=replace(first_request.observation,
            doc_id="OTHER-CHANNEL", received_at="2026-09-12T10:00:00"))
        with patch("kalmora.ap_pipeline.commit_ap_transaction", side_effect=AssertionError("duplicate cannot post")):
            second = self.run_invoice(second_request, first.state)
        self.assertEqual(second.row["decision"], "DUPLICATE")
        self.assertEqual(second.row["duplicate_of"], first_request.observation.doc_id)
        self.assertEqual(len(second.state.rows), 1)
        self.assertIs(second.state, first.state)
        self.assertEqual(first.state.observations[0].received_at, first_request.observation.received_at)

    def test_company_and_po_price_candidates_cannot_contradict_resolved_scope_and_erp(self):
        request = self.request()
        fields = dict(request.rejection_fields, recipient_company=[self.fact("1910", "recipient")],
            order_company=[self.fact("1910", "ordering company")])
        with self.assertRaisesRegex(ValueError, "company differs"):
            self.run_invoice(replace(request, rejection_fields=fields))
        line = request.price_lines[0]
        forged = replace(line, portions=(replace(line.portions[0],
            po_unit_price_cents=(self.fact(20000, "forged PO price"),)),))
        with self.assertRaisesRegex(ValueError, "active ERP PO price"):
            self.run_invoice(replace(request, price_lines=(forged,)))
        self.assertEqual(self.state.rows, ())

    def test_header_and_resolved_context_cannot_replace_independent_attachment_amounts(self):
        request = self.direct(self.request())
        fields = dict(request.rejection_fields)
        for name in ("net_cents", "gross_cents"):
            fields[name] = [replace(f, value=20000) for f in fields[name]]
        header = replace(request.posting.header, net=20000, gross=20000, payable=20000)
        posting = replace(request.posting, header=header,
            valuation_lines=(replace(request.posting.valuation_lines[0], amount_doc=20000),),
            tax_lines=(replace(request.posting.tax_lines[0], base_doc=20000),),
            withholding_bases=(replace(request.posting.withholding_bases[0], base_doc=20000),),
            coded_lines=(replace(request.posting.coded_lines[0], line=dict(request.posting.coded_lines[0].line,
                                                                           amount=20000)),))
        request = replace(request, rejection_fields=fields, header=header, posting=posting,
                          observation=replace(request.observation, amount_cents=20000))
        with self.assertRaisesRegex(ValueError, "observed financial source line net"):
            self.run_invoice(request)
        self.assertEqual(self.state.rows, ())

    def test_foreign_scope_or_future_factoring_event_cannot_set_invoice_payee(self):
        request = self.request()
        for scope in (ApScope("1910", "OTHER-VENDOR", "USD"), ApScope("1100", "SUP-OTHER", "EUR")):
            event = ApEvent("UNRELATED-FACTOR", scope, "FACTORING_NOTICE",
                (Evidence("synthetic/letter.pdf", "actual scope and dates"),),
                received_at="2034-01-01T10:00:00", valid_from="2034-01-01", value="ES-FACTORED")
            result = self.run_invoice(replace(request, timeline=ApTimelineState((event,))))
            self.assertEqual(result.row["decision"], "POST")
            self.assertNotIn("payee", result.row)

    def test_future_cutoff_and_missing_cutoff_proof_never_consume_receipts(self):
        request = self.request()
        future = replace(request.posting, receipt_as_of="2034-01-01")
        with self.assertRaisesRegex(ValueError, "phase horizon"):
            self.run_invoice(replace(request, posting=future,
                receipt_as_of=self.fact("2034-01-01", "future processing")))
        missing = self.run_invoice(replace(request, receipt_as_of=None))
        self.assertEqual(missing.status, "UNKNOWN")
        self.assertIs(missing.state, self.state)

    def test_known_quantity_shortage_precedes_an_unresolved_price_candidate(self):
        first = self.run_invoice(self.request())
        second = self.request("DIFFERENT-INVOICE")
        line = second.price_lines[0]
        line = replace(line, portions=(replace(line.portions[0],
            po_unit_price_cents=(self.fact(None, "unresolved PO candidate"),)),))
        result = self.run_invoice(replace(second, price_lines=(line,)), first.state)
        self.assertEqual(result.row["decision"], "HOLD")
        self.assertEqual(result.row["reasons"], ["QTY_NOT_RECEIVED"])
        self.assertIs(result.state, first.state)

    def test_timezone_boundary_uses_the_same_clock_for_phase_and_receipt_cutoff(self):
        request = self.request()
        request = replace(request,
            observation=replace(request.observation, received_at="2026-10-01T00:30:00+02:00"),
            posting=replace(request.posting, posting_date="2026-09-30", receipt_as_of="2026-09-30"),
            receipt_as_of=self.fact("2026-09-30", "observed cutoff"))
        self.assertEqual(self.run_invoice(request).status, "COMMITTED")


if __name__ == "__main__":
    unittest.main()
