"""Real-engine integration of atomic AP output, receipts and advance consumption."""
from dataclasses import FrozenInstanceError, replace
import unittest
from unittest.mock import patch

from kalmora.ap_allocation import (
    ConsumptionState, InvoiceQuantityLine, OrderKey, OrderLine, OrderPortion,
    Receipt, ReceiptUsage,
)
from kalmora.ap_credit_state import CreditBalance
from kalmora.ap_journal import (
    AdvanceApplication, AdvanceBalance, AdvanceState, ApprovedAdvanceOrder, CreditReference, InvoiceLineOrder,
)
from kalmora.ap_output import APHeader, validate_ap_row
from kalmora.ap_tax import TaxCatalog, TaxLine
from kalmora.ap_transaction import (
    APDownPaymentInputs, APPostingInputs, APTransactionRequest, APTransactionState, CodedAPLine,
    commit_ap_transaction,
)
from kalmora.ap_valuation import CostAssignment, OrderPrice, ValuationLine
from kalmora.ap_withholding import ContractGuarantee, WithholdingBase, WithholdingCatalog
from kalmora.facts import Evidence
from kalmora.model.ap_component_scope import APComponentScope
from kalmora.model.ap_duplicate_record import DuplicateRecord
from kalmora.money import RateTable


class APTransactionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.order = OrderKey("1100", "SUP-OTHER", "EUR", "PO-OTHER", 10)
        self.receipt = Receipt("R-OTHER", self.order, 2000, "ud", "2026-09-03")
        self.coding = CostAssignment("1100", "62300000", "CC-OTHER")
        self.tax_catalog = TaxCatalog({"tax_codes": {
            "SEX": {"country": "ES", "kind": "exempt", "rate": 0},
            "S21": {"country": "ES", "kind": "input", "rate": 2100},
        }})
        self.withholding_catalog = WithholdingCatalog({"withholdings": {
            "IRPF15": {"rate": 1500, "account": "47510000"},
        }})
        self.context = {"companies": {"1100"}, "partners": {"SUP-OTHER"},
                        "accounts": {"40090000", "40000000", "41000000", "62300000", "40700000",
                                     "47200000", "47510000", "40000900"},
                        "cost_centers": {"CC-OTHER": {"company": "1100"}},
                        "min_date": "2026-09-01", "max_date": "2026-09-30"}
        self.baseline = APTransactionState(ConsumptionState(
            (ReceiptUsage(self.order, "R-OTHER", 1000),),
            (("1100", "SUP-OTHER", "EUR", "HIST-OTHER"),),
        ))

    def request(self, doc_id="I1", *, date="2026-09-01", currency="EUR"):
        order = replace(self.order, currency=currency)
        receipt = replace(self.receipt, order=order, posting_date=date[:8] + "03")
        header = APHeader("1100", "SUP-OTHER", "INV-" + doc_id, date, currency,
                          10000, 0, 10000, 0, 0, 10000)
        inputs = APPostingInputs(
            header=header, country="ES", posting_date=date[:8] + "11",
            reconciliation_account="41000000", gr_ir_account="40090000",
            valuation_lines=(ValuationLine("L-OTHER", 10000, self.coding, 1000),),
            tax_lines=(TaxLine("L-OTHER", 10000, "SEX", tax_doc=0),),
            withholding_bases=(WithholdingBase("L-OTHER", 10000, ()),),
            coded_lines=(CodedAPLine("L-OTHER", {
                "amount": 10000, "account": "62300000", "cost_center": "CC-OTHER",
                "wbs": None, "tax_code": "SEX", "po": "PO-OTHER", "po_item": 10,
            }),),
            quantity_lines=(InvoiceQuantityLine("L-OTHER", 1000, "ud", (
                OrderPortion(order, 1000, ("R-OTHER",)),)),),
            order_catalog=(OrderLine(order, "ud"),), receipt_catalog=(receipt,),
            order_prices=(OrderPrice(order, 10000),), receipt_as_of=date[:8] + "11",
        )
        return APTransactionRequest(
            scope=APComponentScope("1100", "SUP-OTHER", currency, doc_id, date, "POST"),
            document_type="INVOICE", posting=inputs,
            evidence=(Evidence(f"synthetic/{date}/{doc_id}.pdf", "resolved_scope_and_policy"),),
        )

    def commit(self, request, state=None, **overrides):
        options = dict(tax_catalog=self.tax_catalog, withholding_catalog=self.withholding_catalog,
                       context=self.context)
        options.update(overrides)
        return commit_ap_transaction(request, self.baseline if state is None else state, **options)

    def source_observation(self, request, *, received_at="2026-09-11T10:00:00"):
        scope, header = request.scope, request.posting.header
        return DuplicateRecord(scope.invoice_id, scope.company, scope.vendor, scope.currency,
            header.invoice_number, received_at, header.gross,
            (Evidence(f"synthetic/{scope.invoice_id}.pdf", "invoice_header"),
             Evidence(f"synthetic/{scope.invoice_id}/message.json", "received_at", quote=received_at)),
            status=scope.decision, document_type=request.document_type)

    def test_publication_observation_cannot_change_posted_identity_or_decision(self):
        request = self.request("OBSERVED-OTHER")
        observed = self.source_observation(request)
        for changed in (dict(company="1910"), dict(vendor="OTHER-SUPPLIER"), dict(currency="USD"),
                        dict(doc_id="OTHER-TASK"), dict(document_type="CREDIT_NOTE"),
                        dict(status="RECEIVED"), dict(status="HOLD"), dict(status="POST_PAYMENT_BLOCK")):
            with self.subTest(changed=changed), patch("kalmora.ap_transaction.allocate_receipts") as allocate:
                with self.assertRaisesRegex(ValueError, "observation differs from posting scope/decision"):
                    self.commit(replace(request, observation=replace(observed, **changed)))
                allocate.assert_not_called()
            self.assertEqual(self.baseline.observations, ())
            self.assertEqual(self.baseline.rows, ())
            self.assertEqual(self.baseline.consumption.usages[0].quantity_milli, 1000)

    def test_publication_observation_cannot_replace_invoice_number_or_gross(self):
        request = self.request("SOURCE-AMOUNTS-OTHER")
        observed = self.source_observation(request)
        for changed in (dict(number="OTHER-INVOICE"), dict(amount_cents=9999), dict(amount_cents=None)):
            with self.subTest(changed=changed), patch("kalmora.ap_transaction.allocate_receipts") as allocate:
                with self.assertRaisesRegex(ValueError, "observation differs from posting source amounts"):
                    self.commit(replace(request, observation=replace(observed, **changed)))
                allocate.assert_not_called()
            self.assertEqual(self.baseline.observations, ())
            self.assertEqual(self.baseline.rows, ())
            self.assertEqual(self.baseline.advances.events, ())

    def test_late_output_failure_does_not_publish_observation_or_replace_prior_publication(self):
        prior_request = self.request("PRIOR-OBSERVATION")
        prior_inputs = replace(prior_request.posting, quantity_lines=(),
            valuation_lines=(replace(prior_request.posting.valuation_lines[0], quantity_milli=None),),
            coded_lines=(replace(prior_request.posting.coded_lines[0], line=dict(
                prior_request.posting.coded_lines[0].line, po=None, po_item=None)),))
        prior_request = replace(prior_request, posting=prior_inputs,
                                observation=self.source_observation(prior_request))
        prior = self.commit(prior_request)
        request = self.request("FAILED-OBSERVATION")
        request = replace(request, observation=self.source_observation(request),
                          posting=replace(request.posting, payment_block="CONTRACTOR_CERTIFICATE_EXPIRED"))
        # All monetary factories can build their tentative results; the real
        # delivery validator rejects a POST carrying a payment block at the end.
        with self.assertRaisesRegex(ValueError, "payment block"):
            self.commit(request, prior.state)
        self.assertEqual(prior.state.observations, (prior_request.observation,))
        self.assertEqual([row["doc_id"] for row in prior.state.rows], ["PRIOR-OBSERVATION"])
        self.assertEqual(prior.state.consumption.usages[0].quantity_milli, 1000)
        self.assertEqual(prior.state.advances.events, (("1100", "SUP-OTHER", "EUR", "PRIOR-OBSERVATION"),))
        next_request = self.request("NEXT-OBSERVATION")
        next_request = replace(next_request, observation=self.source_observation(next_request))
        committed = self.commit(next_request, prior.state)
        self.assertEqual(committed.status, "COMMITTED")
        self.assertEqual([record.doc_id for record in committed.state.observations],
                         ["PRIOR-OBSERVATION", "NEXT-OBSERVATION"])
        self.assertEqual(committed.state.consumption.usages[0].quantity_milli, 2000)
        self.assertEqual(prior.state.observations, (prior_request.observation,))

    def test_published_source_observations_are_immutable_and_independent_of_later_snapshots(self):
        request = self.request("IMMUTABLE-OBSERVATION")
        request = replace(request, observation=self.source_observation(request))
        committed = self.commit(request)
        observations = committed.state.observations
        self.assertIsInstance(observations, tuple)
        self.assertEqual(observations, (request.observation,))
        with self.assertRaises(FrozenInstanceError):
            observations[0].number = "CHANGED-NUMBER"
        with self.assertRaises(FrozenInstanceError):
            observations[0].evidence[0].document = "changed-source.pdf"
        with self.assertRaises(TypeError):
            observations[0] = replace(observations[0], amount_cents=1)
        changed_request = replace(request, observation=replace(request.observation, amount_cents=1))
        self.assertEqual(changed_request.observation.amount_cents, 1)
        committed.row["gross"] = 1
        self.assertEqual(committed.state.observations[0].amount_cents, 10000)
        self.assertEqual(committed.row["gross"], 10000)
        next_request = self.request("DIRECT-LATER-OBSERVATION")
        inputs = replace(next_request.posting, quantity_lines=(),
            valuation_lines=(replace(next_request.posting.valuation_lines[0], quantity_milli=None),),
            coded_lines=(replace(next_request.posting.coded_lines[0], line=dict(
                next_request.posting.coded_lines[0].line, po=None, po_item=None)),))
        next_request = replace(next_request, posting=inputs, observation=self.source_observation(next_request))
        later = self.commit(next_request, committed.state)
        self.assertEqual(observations, committed.state.observations)
        self.assertEqual(len(committed.state.observations), 1)
        self.assertEqual(len(later.state.observations), 2)
        self.assertEqual(later.state.observations[0], observations[0])
        self.assertEqual(self.baseline.observations, ())

    def test_standalone_post_without_observation_cannot_claim_complete_pipeline_history(self):
        from kalmora.ap_erp import APERPBaseline
        from kalmora.ap_history import HistoricalReceipt, reconcile_receipt_history
        from kalmora.ap_pipeline import APInvoiceRequest, evaluate_ap_invoice
        from kalmora.facts import Fact

        request = self.request("STANDALONE-WITHOUT-OBSERVATION")
        standalone = self.commit(request, APTransactionState())
        self.assertEqual(standalone.status, "COMMITTED")
        self.assertEqual(standalone.state.observations, ())
        self.assertEqual([row["doc_id"] for row in standalone.state.rows], [request.scope.invoice_id])
        history = reconcile_receipt_history((HistoricalReceipt(self.receipt, 20000, 10000,
            (Evidence("synthetic/erp/receipts.jsonl", "R-OTHER"),)),), (),
            inventory_complete=Fact(True, Evidence("synthetic/erp/journal.jsonl", "complete source scan")))
        baseline = APERPBaseline("2026-09", (), request.posting.order_catalog,
            request.posting.receipt_catalog, request.posting.order_prices, history, (), ())
        later = self.request("LATER-PIPELINE-TASK")
        observation = replace(self.source_observation(later, received_at="2026-09-12T10:00:00"),
                              status="RECEIVED")
        invoice = APInvoiceRequest(observation=observation,
            duplicate_inventory_complete=Fact(True, Evidence("synthetic/inventory.json", "complete tasks")),
            rejection_fields={}, amount_sources=(), hold_fields={})
        result = evaluate_ap_invoice(invoice, standalone.state, baseline=baseline,
            tax_catalog=self.tax_catalog, withholding_catalog=self.withholding_catalog, context=self.context)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.diagnostics, ("POSTED_DUPLICATE_OBSERVATIONS_INCOMPLETE",))
        self.assertIsNone(result.row)
        self.assertIs(result.state, standalone.state)
        self.assertEqual(result.stages, ())
        self.assertEqual(standalone.state.observations, ())

    def test_failed_header_or_journal_does_not_reserve_receipts_for_next_invoice(self):
        first = self.request("I1")
        failures = (
            replace(first.posting, header=replace(first.posting.header, payable=9999)),
            replace(first.posting, reconciliation_account="43000000"),
        )
        for inputs in failures:
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                self.commit(replace(first, posting=inputs))
            self.assertEqual(self.baseline.consumption.usages[0].quantity_milli, 1000)
            self.assertEqual(self.baseline.rows, ())
            self.assertEqual(self.baseline.advances.events, ())
            second = self.commit(self.request("I2"))
            self.assertEqual(second.status, "COMMITTED")
            self.assertEqual(second.state.consumption.usages[0].quantity_milli, 2000)
            self.assertEqual(second.state.keys, (("1100", "SUP-OTHER", "EUR", "I2"),))
            self.assertEqual([row["doc_id"] for row in second.state.rows], ["I2"])
            self.assertEqual(second.state.advances.events, second.state.keys)
            self.assertEqual(validate_ap_row(second.row, self.context, tax_catalog=self.tax_catalog), ())
            retry = self.commit(first, second.state)
            self.assertEqual(retry.status, "BLOCKED")
            self.assertIs(retry.state, second.state)
            self.assertIsNone(retry.row)
            self.assertEqual([note.code for note in retry.diagnostics], ["INSUFFICIENT_RECEIPTS"])

    def test_same_key_or_task_id_cannot_publish_twice_even_with_changed_scope(self):
        request = self.request("I2")
        second = self.commit(request)
        other_scope = replace(request, scope=replace(request.scope, vendor="OTHER-SUPPLIER"))
        for replay in (request, other_scope):
            with self.subTest(scope=replay.scope), patch("kalmora.ap_transaction.allocate_receipts") as allocate:
                with self.assertRaisesRegex(ValueError, "already committed"):
                    self.commit(replay, second.state)
                allocate.assert_not_called()
            self.assertEqual(len(second.state.rows), 1)
            self.assertEqual(second.state.consumption.usages[0].quantity_milli, 2000)

    def test_historical_posted_id_cannot_bypass_guard_with_changed_supplier_or_currency(self):
        request = self.request("HIST-OTHER")
        for changed in ({}, dict(vendor="OTHER-SUPPLIER"), dict(currency="USD")):
            scope = replace(request.scope, **changed)
            inputs = replace(request.posting,
                header=replace(request.posting.header, vendor_id=scope.vendor, currency=scope.currency),
                valuation_lines=(replace(request.posting.valuation_lines[0], quantity_milli=None),),
                quantity_lines=(), coded_lines=(replace(request.posting.coded_lines[0], line=dict(
                    request.posting.coded_lines[0].line, po=None, po_item=None)),))
            replay = replace(request, scope=scope, posting=inputs)
            with self.subTest(changed=changed), patch("kalmora.ap_transaction.allocate_receipts") as allocate:
                with self.assertRaisesRegex(ValueError, "already committed"):
                    self.commit(replay, context=dict(self.context, partners={"SUP-OTHER", "OTHER-SUPPLIER"}))
                allocate.assert_not_called()
            self.assertEqual(self.baseline.rows, ())

    def test_nonposting_never_calls_factories_or_changes_state(self):
        names = ("allocate_receipts", "value_ap_lines", "calculate_ap_tax",
                 "calculate_ap_withholdings", "build_ap_journal", "build_ap_row")
        for decision in ("HOLD", "REJECT", "DUPLICATE", "NOT_INVOICE"):
            request = self.request()
            request = replace(request, scope=replace(request.scope, decision=decision), posting=None)
            mocks = [patch("kalmora.ap_transaction." + name, side_effect=AssertionError(name)) for name in names]
            with self.subTest(decision=decision):
                for mock in mocks:
                    mock.start()
                try:
                    result = commit_ap_transaction(request, self.baseline)
                finally:
                    for mock in reversed(mocks):
                        mock.stop()
                self.assertEqual(result.status, "NOT_POSTING")
                self.assertIs(result.state, self.baseline)
                self.assertIsNone(result.row)
        with self.assertRaisesRegex(ValueError, "UNKNOWN"):
            self.commit(replace(request, scope=replace(request.scope, decision="UNKNOWN")))

    def test_header_and_quantity_scopes_cannot_cross_invoice_identity(self):
        request = self.request()
        for changed in (dict(company="1910"), dict(vendor="OTHER-SUPPLIER"),
                        dict(currency="USD"), dict(invoice_date="2026-09-02")):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "header differs"):
                self.commit(replace(request, scope=replace(request.scope, **changed)))
        foreign = replace(self.order, vendor="OTHER-SUPPLIER")
        quantity = replace(request.posting.quantity_lines[0], portions=(OrderPortion(foreign, 1000, ("R-OTHER",)),))
        result = self.commit(replace(request, posting=replace(request.posting, quantity_lines=(quantity,))))
        self.assertEqual((result.status, result.state), ("BLOCKED", self.baseline))
        self.assertEqual([note.code for note in result.diagnostics], ["SCOPE_MISMATCH"])

    def test_advance_and_receipt_rollback_after_output_validation_fails(self):
        balance = AdvanceBalance("ADV-OTHER", "1100", "SUP-OTHER", "EUR", "DEP-OTHER",
                                 "2026-08-01", "PO-OTHER", 4000, 4000, 1000, 1000)
        baseline = APTransactionState(self.baseline.consumption, AdvanceState(
            (balance,), (("1100", "SUP-OTHER", "EUR", "ADV-OTHER"),),
        ))
        request = self.request("I1")
        inputs = replace(
            request.posting, header=replace(request.posting.header, payable=8000),
            advances=(AdvanceApplication("ADV-OTHER", 2000, "NON_MONETARY", "observed:contract",
                                         self.coding, "L-OTHER"),),
            invoice_orders=("PO-OTHER",),
            order_bindings=(InvoiceLineOrder("L-OTHER", "PO-OTHER", 10000, "observed:line-po-binding"),),
        )
        # Journal and tentative advance use are valid; POST plus this payment
        # block fails only in the real AP-row validator.
        invalid = replace(request, posting=replace(inputs, payment_block="CONTRACTOR_CERTIFICATE_EXPIRED"))
        with self.assertRaisesRegex(ValueError, "payment block"):
            self.commit(invalid, baseline)
        self.assertEqual(baseline.advances.balances, (balance,))
        self.assertEqual(baseline.consumption, self.baseline.consumption)
        self.assertEqual(baseline.rows, ())
        other = replace(request, scope=replace(request.scope, invoice_id="I2"), posting=inputs)
        committed = self.commit(other, baseline)
        self.assertEqual(committed.row["payable"], 8000)
        self.assertEqual(committed.state.advances.balances[0].used_doc, 3000)
        self.assertEqual(committed.state.advances.balances[0].used_local, 3000)
        self.assertEqual(committed.state.advances.events[-1], ("1100", "SUP-OTHER", "EUR", "I2"))
        retry = self.commit(replace(request, posting=inputs), committed.state)
        self.assertEqual(retry.status, "BLOCKED")
        self.assertIs(retry.state, committed.state)
        self.assertEqual(retry.state.advances.balances[0].used_doc, 3000)

    def test_explicit_receipt_ids_and_cutoff_are_required_without_inventing_dates(self):
        request = self.request()
        unspecified = replace(request.posting.quantity_lines[0], portions=(OrderPortion(self.order, 1000),))
        changes = (dict(quantity_lines=(unspecified,)), dict(receipt_as_of=None),
                   dict(receipt_as_of="2026-09-02"))
        for changed in changes:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.commit(replace(request, posting=replace(request.posting, **changed)))
            self.assertEqual(self.baseline.rows, ())
            self.assertEqual(self.baseline.consumption.usages[0].quantity_milli, 1000)
        with self.assertRaisesRegex(ValueError, "prior receipt consumption"):
            self.commit(replace(request, posting=replace(request.posting, receipt_catalog=())))

    def test_published_rows_and_journals_are_immutable_snapshots(self):
        request = self.request("I2")
        committed = self.commit(request)
        row = committed.row
        row["journal_entry"]["lines"][0]["debit"] = 1
        row["lines"][0]["amount"] = 1
        request.posting.coded_lines[0].line["amount"] = 2
        self.assertEqual(committed.row["journal_entry"]["lines"][0]["debit"], 10000)
        self.assertEqual(committed.state.rows[0]["lines"][0]["amount"], 10000)
        self.assertEqual(committed.state.evidence, (request.evidence,))
        with self.assertRaises(FrozenInstanceError):
            committed.state.advances = AdvanceState()
        with self.assertRaises(TypeError):
            APTransactionState(ConsumptionState(usages=[]))

    def test_coded_projection_cannot_change_a_real_factorys_fiscal_treatment(self):
        request = self.request()
        changed = CodedAPLine("L-OTHER", {**request.posting.coded_lines[0].line, "tax_code": "S21"})
        with self.assertRaisesRegex(ValueError, "fiscal treatment"):
            self.commit(replace(request, posting=replace(request.posting, coded_lines=(changed,))))

    def test_transaction_boundary_rejects_mutable_credit_snapshot(self):
        balance = CreditBalance("1100", "SUP-OTHER", "EUR", "ORIGINAL-OTHER",
                                "a" * 64, "line:1", 10000, 6000)
        credits = [balance]
        with self.assertRaisesRegex(TypeError, "immutable tuple"):
            APTransactionState(self.baseline.consumption, AdvanceState(credits=credits))
        snapshot = APTransactionState(self.baseline.consumption, AdvanceState(credits=tuple(credits)))
        credits.clear()
        self.assertEqual(snapshot.advances.credits, (balance,))
        self.assertEqual(self.baseline.advances.credits, ())

    def test_transaction_boundary_rejects_overconsumed_credit_without_changing_committed_state(self):
        balance = CreditBalance("1100", "SUP-OTHER", "EUR", "ORIGINAL-OTHER",
                                "a" * 64, "line:1", 10000, 6000)
        snapshot = APTransactionState(self.baseline.consumption, AdvanceState(credits=(balance,)))
        committed = self.commit(self.request("OTHER-INVOICE"), snapshot)
        with self.assertRaisesRegex(ValueError, "cumulative original credit consumption"):
            APTransactionState(committed.state.consumption,
                               replace(committed.state.advances,
                                       credits=(replace(balance, used_doc=10001),)))
        self.assertEqual(committed.state.advances.credits, (balance,))
        self.assertEqual([row["doc_id"] for row in committed.state.rows], ["OTHER-INVOICE"])
        self.assertEqual(snapshot.advances.credits, (balance,))

    def test_coded_po_cannot_move_to_other_invoice_line_with_identical_cost_dimensions(self):
        request = self.request("TWO-ORDERS")
        second_order = replace(self.order, po="PO-SECOND")
        second_receipt = Receipt("R-SECOND", second_order, 1000, "ud", "2026-09-03")
        second_coded = CodedAPLine("L-SECOND", {
            **request.posting.coded_lines[0].line, "amount": 20000, "po": "PO-SECOND",
        })
        inputs = replace(
            request.posting, header=replace(request.posting.header, net=30000, gross=30000, payable=30000),
            valuation_lines=(*request.posting.valuation_lines, ValuationLine("L-SECOND", 20000, self.coding, 1000)),
            tax_lines=(*request.posting.tax_lines, TaxLine("L-SECOND", 20000, "SEX", tax_doc=0)),
            withholding_bases=(*request.posting.withholding_bases, WithholdingBase("L-SECOND", 20000, ())),
            coded_lines=(*request.posting.coded_lines, second_coded),
            quantity_lines=(*request.posting.quantity_lines, InvoiceQuantityLine("L-SECOND", 1000, "ud", (
                OrderPortion(second_order, 1000, ("R-SECOND",)),))),
            order_catalog=(*request.posting.order_catalog, OrderLine(second_order, "ud")),
            receipt_catalog=(*request.posting.receipt_catalog, second_receipt),
            order_prices=(*request.posting.order_prices, OrderPrice(second_order, 20000)),
        )
        correctly_bound = self.commit(replace(request, posting=inputs), APTransactionState())
        self.assertEqual(correctly_bound.status, "COMMITTED")
        swapped = (
            CodedAPLine("L-OTHER", {**inputs.coded_lines[0].line, "po": "PO-SECOND"}),
            CodedAPLine("L-SECOND", {**second_coded.line, "po": "PO-OTHER"}),
        )
        baseline = APTransactionState()
        with self.assertRaisesRegex(ValueError, "coded PO"):
            self.commit(replace(request, posting=replace(inputs, coded_lines=swapped)), baseline)
        self.assertEqual(baseline.rows, ())
        self.assertEqual(baseline.consumption.usages, ())

    def test_payment_block_vat_withholding_and_guarantee_are_real_scoped_components(self):
        request = self.request("TAX-OTHER")
        inputs = replace(
            request.posting,
            header=replace(request.posting.header, tax=2100, gross=12100,
                           withholding=1500, retention=500, payable=10100),
            tax_lines=(TaxLine("L-OTHER", 10000, "S21", tax_doc=2100),),
            withholding_bases=(WithholdingBase("L-OTHER", 10000, ("IRPF15",)),),
            guarantee=ContractGuarantee(10000, "observed:contract-guarantee"),
            coded_lines=(CodedAPLine("L-OTHER", {
                **request.posting.coded_lines[0].line, "tax_code": "S21",
            }),),
            payment_block="CONTRACTOR_CERTIFICATE_EXPIRED",
        )
        request = replace(request, scope=replace(request.scope, decision="POST_PAYMENT_BLOCK"), posting=inputs)
        result = self.commit(request)
        self.assertEqual(result.status, "COMMITTED")
        self.assertEqual(validate_ap_row(result.row, self.context, tax_catalog=self.tax_catalog), ())
        postings = {line["account"]: line for line in result.row["journal_entry"]["lines"]}
        self.assertEqual(postings["47200000"]["debit"], 2100)
        self.assertEqual(postings["47510000"]["credit"], 1500)
        self.assertEqual(postings["40000900"]["credit"], 500)
        self.assertEqual(postings["41000000"]["credit"], 10100)
        self.assertEqual(postings["47510000"]["partner"], "SUP-OTHER")
        self.assertEqual(result.row["payment_block"], "CONTRACTOR_CERTIFICATE_EXPIRED")

    def test_import_vat_has_explicit_dua_reference_quota_and_zero_expense_base(self):
        request = self.request("IMPORT-OTHER")
        catalogue = TaxCatalog({"tax_codes": {
            "SEX": {"country": "ES", "kind": "exempt", "rate": 0},
            "SIMP": {"country": "ES", "kind": "import", "rate": 2100},
        }})
        inputs = replace(
            request.posting,
            header=replace(request.posting.header, tax=3000, gross=13000, payable=13000),
            valuation_lines=(*request.posting.valuation_lines, ValuationLine("DUA", 0, self.coding)),
            tax_lines=(*request.posting.tax_lines,
                       TaxLine("DUA", 0, "SIMP", tax_doc=3000, dua_reference="OBSERVED-DUA")),
            withholding_bases=(*request.posting.withholding_bases, WithholdingBase("DUA", 0, ())),
            coded_lines=(*request.posting.coded_lines, CodedAPLine("DUA", {
                **request.posting.coded_lines[0].line, "amount": 0, "tax_code": "SIMP",
                "po": None, "po_item": None,
            })),
        )
        result = self.commit(replace(request, posting=inputs), tax_catalog=catalogue)
        quota, = [line for line in result.row["journal_entry"]["lines"] if line["account"] == "47200000"]
        self.assertEqual((result.row["net"], result.row["tax"], quota["debit"]), (10000, 3000, 3000))
        self.assertEqual(quota["assignment"], "OBSERVED-DUA")
        self.assertFalse(any(line["account"] == "62300000" and line["debit"] for line in result.row["journal_entry"]["lines"]))
        no_reference = replace(inputs.tax_lines[-1], dua_reference=None)
        with self.assertRaisesRegex(ValueError, "DUA"):
            self.commit(replace(request, posting=replace(inputs, tax_lines=(*inputs.tax_lines[:-1], no_reference))),
                        tax_catalog=catalogue)

    def test_resolved_direct_credit_note_reverses_original_without_new_receipt_use(self):
        original_request = self.request("ORIGINAL-OTHER")
        inputs = replace(
            original_request.posting,
            valuation_lines=(replace(original_request.posting.valuation_lines[0], quantity_milli=None),),
            quantity_lines=(),
            coded_lines=(CodedAPLine("L-OTHER", {
                **original_request.posting.coded_lines[0].line, "po": None, "po_item": None,
            }),),
        )
        original = self.commit(replace(original_request, posting=inputs))
        entry = {**original.row["journal_entry"], "id": "POSTED-ORIGINAL"}
        credit_request = replace(
            original_request, scope=replace(original_request.scope, invoice_id="CREDIT-OTHER",
                                            invoice_date="2026-09-10"), document_type="CREDIT_NOTE",
            posting=replace(inputs, header=replace(inputs.header, invoice_date="2026-09-10",
                                                  invoice_number="CREDIT-INV-OTHER"),
                            credit_references=(CreditReference("L-OTHER", entry, 1),)),
        )
        credit = self.commit(credit_request, original.state)
        self.assertEqual(credit.status, "COMMITTED")
        self.assertIs(credit.state.consumption, original.state.consumption)
        self.assertEqual([row["doc_id"] for row in credit.state.rows], ["ORIGINAL-OTHER", "CREDIT-OTHER"])
        self.assertEqual(credit.row["journal_entry"]["lines"][0]["credit"], 10000)
        self.assertEqual(credit.row["journal_entry"]["lines"][-1]["debit"], 10000)
        with self.assertRaisesRegex(ValueError, "cannot consume new receipts"):
            self.commit(replace(credit_request, posting=replace(credit_request.posting,
                         quantity_lines=original_request.posting.quantity_lines)), original.state)

    def test_different_months_and_reused_ids_post_without_golden_and_fx_stays_invoice_date(self):
        for invoice_date, doc_id in (("2026-09-01", "OTHER-73"), ("2027-02-01", "API004469")):
            with self.subTest(invoice_date=invoice_date, doc_id=doc_id):
                request = self.request(doc_id, date=invoice_date, currency="USD")
                rates = RateTable([dict(currency="USD", date=invoice_date, rate="2"),
                                   dict(currency="USD", date=invoice_date[:8] + "11", rate="4")])
                result = self.commit(request, APTransactionState(), context=None, rates=rates)
                self.assertEqual(result.status, "COMMITTED")
                self.assertEqual(result.row["journal_entry"]["document_date"], invoice_date)
                supplier = result.row["journal_entry"]["lines"][-1]
                self.assertEqual((supplier["credit"], supplier["amount_doc"], supplier["currency"]),
                                 (5000, 10000, "USD"))
                self.assertEqual(result.state.consumption.usages[0].quantity_milli, 1000)

    def advance_request(self):
        return APTransactionRequest(
            scope=APComponentScope("1100", "SUP-OTHER", "EUR", "DEPOSIT-OTHER", "2026-09-01", "POST"),
            document_type="DOWN_PAYMENT_REQUEST",
            evidence=(Evidence("synthetic/request.pdf", "approved_order_and_vendor_master"),),
            posting=APDownPaymentInputs(
                header=APHeader("1100", "SUP-OTHER", "DEP-OTHER", "2026-09-01", "EUR",
                                4000, 0, 4000, 0, 0, 4000),
                posting_date="2026-09-11",
                order=ApprovedAdvanceOrder("1100", "SUP-OTHER", "EUR", "PO-OTHER", True, "OBSERVED-APPROVAL"),
                vendor_master=dict(id="SUP-OTHER", country="CN", companies=["1100"]),
                po_item=10, tax_code="SEX",
            ),
        )

    def test_approved_foreign_request_commits_both_supplier_dimensions_without_receipt_use(self):
        request = self.advance_request()
        result = self.commit(request)
        self.assertEqual(result.status, "COMMITTED")
        self.assertIs(result.state.consumption, self.baseline.consumption)
        self.assertEqual([line["account"] for line in result.row["journal_entry"]["lines"]],
                         ["40700000", "40000000"])
        self.assertTrue(all(line["partner"] == "SUP-OTHER" for line in result.row["journal_entry"]["lines"]))
        self.assertEqual(result.state.advances.balances[0].amount_doc, 4000)
        self.assertEqual(result.state.advances.events, result.state.keys)
        with self.assertRaisesRegex(ValueError, "already committed"):
            self.commit(request, result.state)

    def test_foreign_request_failed_output_validation_does_not_create_advance_balance(self):
        request = self.advance_request()
        invalid = replace(request, posting=replace(request.posting,
                          header=replace(request.posting.header, payable=3999)))
        with self.assertRaises(ValueError):
            self.commit(invalid)
        self.assertEqual(self.baseline.advances.balances, ())
        self.assertEqual(self.baseline.rows, ())
        self.assertEqual(self.commit(request).state.advances.balances[0].amount_doc, 4000)

    def test_foreign_request_requires_approval_and_correct_supplier_master_and_tax_treatment(self):
        request = self.advance_request()
        for changes in (
            dict(order=replace(request.posting.order, approved=None)),
            dict(vendor_master=dict(id="OTHER", country="CN", companies=["1100"])),
            dict(tax_code="S21"),
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.commit(replace(request, posting=replace(request.posting, **changes)))
        self.assertEqual(self.baseline.advances.balances, ())


if __name__ == "__main__":
    unittest.main()
