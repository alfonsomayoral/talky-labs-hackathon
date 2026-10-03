"""Exact/source-grounded PO resolution connected to historical quantity state."""
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kalmora.ap_allocation import ConsumptionState, OrderKey, OrderLine, Receipt, ReceiptUsage, allocate_receipts
from kalmora.ap_erp import load_ap_erp_baseline
from kalmora.ap_history import (HistoricalDemand, HistoricalReceipt, HistoricalReceiptSnapshot,
                               ReceiptCertainty, reconcile_receipt_history)
from kalmora.ap_order_bridge import APOrderBridge
from kalmora.ap_orders import POQuery, POQueryLine
from kalmora.documents.contracts import ParsedBlock, ParsedDocument, ResolutionResult
from kalmora.documents.replay import RecordedResolver, RecordingConfig, RecordingStore, ReplayError, ResolutionCapture
from kalmora.facts import DocumentFacts, Evidence, Fact


class Resolver:
    def __init__(self, make=None):
        self.requests = []
        self.make = make or self.select

    async def resolve(self, request):
        self.requests.append(request)
        return self.make(request)

    @staticmethod
    def select(request):
        candidate = request.candidates[0]
        description = request.context["query"]["description"]
        return ResolutionResult("SELECTED", (candidate.id,), (dict(
            candidate_id=candidate.id, candidate_attribute="description",
            candidate_value=candidate.attributes["description"], source_sha256=request.document.source_sha256,
            block_id="B1", quote=description, source_value=description),), "same observed service")


class APOrderBridgeIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.orders = [dict(id="PO-NEW", company="1100", vendor="V-NEW", currency="EUR",
            created_on="2031-10-01", project="PROJECT-NEW", items=[dict(
                item=10, uom="hours", unit_price=1000, material="FORMWORK",
                description="Wall formwork panel hire")])]
        self.receipts = [dict(id="R-NEW", company="1100", vendor="V-NEW", po="PO-NEW", po_item=10,
            quantity_milli=2000, posting_date="2031-11-05", type="SES", amount=2000)]
        self.path = "inbox/ap/OTHER/invoice.pdf"
        self.description = "Steel wall mould rental"
        self.proof = Evidence(self.path, "line1.description", 1, self.description)
        self.query = POQuery("L-NEW", "1100", "V-NEW", "EUR", 1000, "hours", (self.proof,),
                             description=self.description)
        self.doc = ParsedDocument(self.path, "a" * 64, "application/pdf", "synthetic-v1",
                                 (ParsedBlock("B1", "Supplier V-NEW\n" + self.description, 1),))
        self.resolver = Resolver()

    def bridge(self, demands=()):
        keys = {(row["company"], row["id"], item["item"]): (
            OrderKey(row["company"], row["vendor"], row["currency"], row["id"], item["item"]), item)
            for row in self.orders for item in row["items"]}
        receipts = []
        for row in self.receipts:
            key, item = keys[(row["company"], row["po"], row["po_item"])]
            receipts.append(HistoricalReceipt(Receipt(row["id"], key, row["quantity_milli"],
                item["uom"], row["posting_date"], row["type"]), row["amount"], item["unit_price"],
                (Evidence("erp/goods_receipts.jsonl", row["id"]),)))
        history = reconcile_receipt_history(tuple(receipts), tuple(demands),
            inventory_complete=Fact(True, Evidence("erp/journal_entries.jsonl", "complete_AP_scan")))
        return APOrderBridge(orders=self.orders, receipts=self.receipts, history=history)

    async def resolve(self, query=None, bridge=None, **options):
        kwargs = dict(invoice_date="2031-11-01", receipt_as_of="2031-11-09",
                      document=self.doc, resolver=self.resolver)
        kwargs.update(options)
        return await (bridge or self.bridge()).resolve(query or self.query, **kwargs)

    async def test_exact_order_material_and_receipt_associations_make_no_semantic_call(self):
        for fields in (dict(po_reference="PO-NEW", po_item=10), dict(material="FORMWORK"),
                       dict(receipt_references=("R-NEW",)), dict(description="Wall formwork panel hire")):
            query = replace(self.query, description=None, **fields) if "description" not in fields else replace(self.query, **fields)
            match = await self.resolve(query)
            self.assertEqual((match.reference.status, match.quantity_status), ("RESOLVED", "AVAILABLE"))
            self.assertFalse(match.semantic_called)
            self.assertEqual(match.quantity_line.portions[0].receipt_ids, ("R-NEW",))
        self.assertEqual(self.resolver.requests, [])

    async def test_scope_only_unique_candidate_stays_unconfirmed_without_calling_model(self):
        match = await self.resolve(replace(self.query, description=None))
        self.assertEqual((match.reference.status, match.quantity_status, match.quantity_line),
                         ("UNCONFIRMED", "UNKNOWN", None))
        self.assertEqual(self.resolver.requests, [])

    async def test_semantic_description_is_bounded_revalidated_then_allocated_by_real_engine(self):
        self.orders += [dict(self.orders[0], id="PO-OTHER-CURRENCY", currency="USD"),
                        dict(self.orders[0], id="PO-OTHER-VENDOR", vendor="V-OTHER")]
        bridge = self.bridge()
        match = await self.resolve(bridge=bridge)
        self.assertEqual((match.reference.status, match.quantity_status, match.semantic_called),
                         ("RESOLVED", "AVAILABLE", True))
        request, = self.resolver.requests
        self.assertEqual(len(request.candidates), 1)
        self.assertEqual(request.candidates[0].attributes["po"], "PO-NEW")
        self.assertEqual(match.request_sha256, request.sha256)
        result = allocate_receipts(company="1100", vendor="V-NEW", currency="EUR", invoice_id="NEW-ID",
            lines=(match.quantity_line,), orders=(OrderLine(match.reference.selected.order, "hours"),),
            receipts=tuple(c.receipt for c in bridge.history.certainties), state=bridge.history.consumption)
        self.assertEqual(result.status, "ALLOCATED")
        self.assertEqual(result.allocations[0].quantity_milli, 1000)
        self.assertEqual(bridge.history.consumption.usages, ())
        self.assertTrue(any(e.document == self.path and e.page == 1 for e in match.reference.selected.evidence))

    async def test_exact_order_position_with_different_wording_needs_no_semantic_confirmation(self):
        match = await self.resolve(replace(self.query, po_reference="PO-NEW", po_item=10))
        self.assertEqual((match.reference.status, match.semantic_called), ("RESOLVED", False))
        self.assertFalse(match.reference.reference_recovered)

    async def test_exact_material_and_delivery_anchor_ignore_nonexact_description_without_model(self):
        for changes in (dict(material="FORMWORK"), dict(receipt_references=("R-NEW",))):
            match = await self.resolve(replace(self.query, **changes))
            self.assertEqual((match.reference.status, match.semantic_called), ("RESOLVED", False))
        self.assertEqual(self.resolver.requests, [])

    async def test_hard_conflicts_unresolved_receipts_and_missing_source_never_reach_model(self):
        for changes in (dict(po_reference="PO-NEW", project="OTHER"),
                        dict(po_reference="PO-NEW", material="OTHER"),
                        dict(po_reference="PO-NEW", uom="ud"),
                        dict(receipt_references=("NOT-IN-ERP",)),
                        dict(evidence=(Evidence("other.pdf", "description", quote=self.description),))):
            match = await self.resolve(replace(self.query, **changes))
            self.assertIsNone(match.quantity_line)
            self.assertFalse(match.semantic_called)
        self.assertEqual(self.resolver.requests, [])

    async def test_exact_po_number_cannot_semantically_invent_which_position_was_invoiced(self):
        item = dict(self.orders[0]["items"][0], item=20)
        self.orders[0] = dict(self.orders[0], items=[self.orders[0]["items"][0], item])
        query = replace(self.query, description=None, po_reference="PO-NEW",
                        evidence=(Evidence(self.path, "po", 1, "PO-NEW"),))
        document = replace(self.doc, blocks=(ParsedBlock("B1", "PO-NEW", 1),))
        match = await self.resolve(query, document=document)
        self.assertEqual(match.reference.status, "AMBIGUOUS")
        self.assertEqual(self.resolver.requests, [])

    async def test_candidate_limit_and_missing_resolver_preserve_unknown(self):
        self.orders.append(dict(self.orders[0], id="PO-ANOTHER"))
        match = await self.resolve(max_candidates=1)
        self.assertEqual(match.diagnostics, ("SEMANTIC_CANDIDATE_LIMIT_EXCEEDED",))
        match = await self.resolve(resolver=None)
        self.assertEqual(match.diagnostics, ("SEMANTIC_RESOLVER_UNAVAILABLE",))
        self.assertEqual(self.resolver.requests, [])

    async def test_semantic_abstention_does_not_create_an_association_or_quantity(self):
        for status, expected in (("NO_MATCH", "NOT_FOUND"), ("AMBIGUOUS", "AMBIGUOUS")):
            resolver = Resolver(lambda request: ResolutionResult(status, (), (), "no supporting match"))
            match = await self.resolve(resolver=resolver)
            self.assertEqual((match.reference.status, match.quantity_line), (expected, None))
            self.assertTrue(match.semantic_called)

    async def test_semantic_ids_proof_constraints_and_unobserved_splits_are_rejected(self):
        self.orders.append(dict(self.orders[0], id="PO-ANOTHER"))
        def outside(request):
            return replace(Resolver.select(request), selected_ids=("INVENTED-ID",))
        def split(request):
            a = Resolver.select(request)
            b = request.candidates[1]
            proof = dict(a.evidence[0], candidate_id=b.id, candidate_value=b.attributes["description"])
            return replace(a, selected_ids=(a.selected_ids[0], b.id), evidence=(*a.evidence, proof))
        def scope_only(request):
            result = Resolver.select(request)
            return replace(result, evidence=(dict(result.evidence[0], candidate_attribute="vendor",
                candidate_value="V-NEW", source_value="V-NEW", quote="V-NEW"),))
        def false_source(request):
            result = Resolver.select(request)
            return replace(result, evidence=(dict(result.evidence[0], source_sha256="b" * 64),))
        for make in (outside, split, scope_only, false_source):
            with self.subTest(make=make), self.assertRaises(ValueError):
                await self.resolve(resolver=Resolver(make))

    async def test_mutable_resolver_request_cannot_change_the_erp_candidate_proof(self):
        def mutate(request):
            request.candidates[0].attributes["description"] = "Invented description"
            return Resolver.select(request)
        bridge = self.bridge()
        with self.assertRaisesRegex(ValueError, "changed its bounded source request"):
            await self.resolve(bridge=bridge, resolver=Resolver(mutate))
        match = await self.resolve(bridge=bridge)
        self.assertEqual(match.semantic_result.evidence[0]["candidate_value"], "Wall formwork panel hire")

    async def test_unknown_historical_capacity_is_not_quantity_hold_and_model_cannot_restore_it(self):
        self.receipts = [dict(self.receipts[0], quantity_milli=1000, amount=1000),
                         dict(self.receipts[0], id="R-SECOND", quantity_milli=1000, amount=1000)]
        key = OrderKey("1100", "V-NEW", "EUR", "PO-NEW", 10)
        demand = HistoricalDemand(key, 1000, (Evidence("erp/journal_entries.jsonl", "OLD"),))
        bridge = self.bridge((demand,))
        match = await self.resolve(bridge=bridge)
        self.assertEqual((match.reference.status, match.quantity_status), ("RESOLVED", "UNKNOWN"))
        self.assertEqual(match.reference.selected.available_milli, 0)
        self.assertIsNone(match.quantity_line)
        self.assertEqual(match.diagnostics, ("HISTORICAL_RECEIPT_CAPACITY_UNKNOWN",))
        self.assertEqual(bridge.history.consumption.usages, ())

    async def test_proven_receipts_only_are_selected_when_other_historical_capacity_is_unknown(self):
        self.orders.append(dict(self.orders[0], id="PO-KNOWN", items=[dict(self.orders[0]["items"][0],
            description="Different service", material="OTHER")]))
        self.receipts.append(dict(self.receipts[0], id="R-KNOWN", po="PO-KNOWN"))
        key = OrderKey("1100", "V-NEW", "EUR", "PO-NEW", 10)
        # Monetary rounding cannot determine the first position's consumed quantity.
        self.orders[0] = dict(self.orders[0], items=[dict(self.orders[0]["items"][0], unit_price=10)])
        self.receipts[0] = dict(self.receipts[0], amount=20)
        demand = HistoricalDemand(key, 10, (Evidence("erp/journal_entries.jsonl", "OLD"),))
        bridge = self.bridge((demand,))
        match = await self.resolve(replace(self.query, description=None, po_reference="PO-KNOWN", po_item=10),
                                   bridge=bridge)
        self.assertEqual((match.reference.status, match.quantity_status), ("RESOLVED", "AVAILABLE"))
        self.assertEqual(match.quantity_line.portions[0].receipt_ids, ("R-KNOWN",))

    async def test_insufficient_proven_capacity_and_observed_cutoff_remain_allocator_decisions(self):
        exact = replace(self.query, description=None, po_reference="PO-NEW", po_item=10)
        for kwargs in (dict(query=replace(exact, quantity_milli=3000)), dict(query=exact, receipt_as_of="2031-11-01")):
            query = kwargs.pop("query")
            match = await self.resolve(query, **kwargs)
            self.assertEqual((match.reference.status, match.quantity_status), ("RESOLVED", "INSUFFICIENT"))
            self.assertIsNotNone(match.quantity_line)
        self.assertEqual(self.resolver.requests, [])

    async def test_current_state_cannot_discard_historical_usage_or_invent_unknown_consumption(self):
        key = OrderKey("1100", "V-NEW", "EUR", "PO-NEW", 10)
        bridge = self.bridge((HistoricalDemand(key, 1000, (Evidence("history", "OLD"),)),))
        with self.assertRaisesRegex(ValueError, "discard historical receipt consumption"):
            await self.resolve(bridge=bridge, state=ConsumptionState())
        self.receipts = [dict(self.receipts[0], quantity_milli=1000, amount=1000),
                         dict(self.receipts[0], id="R-SECOND", quantity_milli=1000, amount=1000)]
        bridge = self.bridge((HistoricalDemand(key, 1000, (Evidence("history", "OLD"),)),))
        with self.assertRaisesRegex(ValueError, "unknown historical receipts"):
            await self.resolve(bridge=bridge, state=ConsumptionState((ReceiptUsage(key, "R-NEW", 1000),)))

    async def test_cache_request_changes_with_receipt_cutoff_state_and_source_catalogue(self):
        first = await self.resolve()
        second = await self.resolve(receipt_as_of="2031-11-10")
        self.assertNotEqual(first.request_sha256, second.request_sha256)
        key = OrderKey("1100", "V-NEW", "EUR", "PO-NEW", 10)
        third = await self.resolve(state=ConsumptionState((ReceiptUsage(key, "R-NEW", 1000),)))
        self.assertNotEqual(first.request_sha256, third.request_sha256)
        self.orders[0]["items"][0]["unit_price"] = 1100
        self.receipts[0]["amount"] = 2200
        fourth = await self.resolve()
        self.assertNotEqual(first.request_sha256, fourth.request_sha256)

    async def test_shared_fixture_replay_reproduces_match_without_provider_and_stays_synthetic(self):
        first = await self.resolve()
        request, = self.resolver.requests
        cfg = RecordingConfig("fixture", "fixture-model", "extract-fixture-v1", "resolve-fixture-v1",
                              "a" * 64, "schema-v1", "b" * 64, {"max_selections": 1})
        with TemporaryDirectory() as directory:
            store = RecordingStore(directory)
            store.save("resolve", request, cfg, ResolutionCapture(first.semantic_result, {}, {}), origin="synthetic")
            resolver = RecordedResolver(store, cfg, mode="fixture")
            repeated = await self.resolve(resolver=resolver)
            self.assertEqual(first, repeated)
            self.assertEqual((resolver.cache_hits, resolver.capture_calls), (1, 0))
            with self.assertRaises(ReplayError):
                await self.resolve(resolver=RecordedResolver(store, cfg, mode="replay"))

    async def test_phase_bridge_checks_source_hashes_and_receipt_scope_before_reusing_baseline(self):
        with TemporaryDirectory() as directory:
            phase = Path(directory)
            (phase / "tasks").mkdir()
            (phase / "erp").mkdir()
            (phase / "tasks" / "close.json").write_text(json.dumps(dict(month="2031-11")))
            tables = dict(purchase_orders=self.orders, goods_receipts=self.receipts,
                          vendors=[dict(id="V-NEW")], journal_entries=[], ap_invoices=[], ap_document_log=[])
            for name, rows in tables.items():
                (phase / "erp" / (name + ".jsonl")).write_text("".join(json.dumps(r) + "\n" for r in rows))
            baseline = load_ap_erp_baseline(phase, grir_account="40090000")
            match = await self.resolve(bridge=APOrderBridge.from_phase(phase, baseline))
            self.assertEqual(match.quantity_status, "AVAILABLE")
            (phase / "erp" / "purchase_orders.jsonl").write_text("[]\n")
            with self.assertRaisesRegex(ValueError, "differs from the active phase"):
                APOrderBridge.from_phase(phase, baseline)
        bridge = self.bridge()
        with self.assertRaisesRegex(ValueError, "different receipt catalogue"):
            APOrderBridge(orders=self.orders, receipts=[dict(self.receipts[0], id="WRONG")], history=bridge.history)

    def exact(self, **changes):
        return replace(self.query, description=None, po_reference="PO-NEW", po_item=10, **changes)

    async def test_observed_multi_po_portions_become_one_conserved_quantity_line(self):
        self.orders.append(dict(self.orders[0], id="PO-SECOND"))
        self.receipts.append(dict(self.receipts[0], id="R-SECOND", po="PO-SECOND"))
        bridge = self.bridge()
        queries = (self.exact(quantity_milli=750), replace(self.exact(quantity_milli=1250),
                   po_reference="PO-SECOND", portion_id="2"))
        result = await bridge.resolve_lines((POQueryLine("L-NEW", 2000, "hours", queries),),
            invoice_id="INVOICE-NEW", invoice_date="2031-11-01", receipt_as_of="2031-11-09", resolver=self.resolver)
        self.assertEqual((result.reference_status, result.quantity_status), ("RESOLVED", "AVAILABLE"))
        self.assertEqual([(p.order.po, p.quantity_milli, p.receipt_ids) for p in result.quantity_lines[0].portions],
            [("PO-NEW", 750, ("R-NEW",)), ("PO-SECOND", 1250, ("R-SECOND",))])
        self.assertEqual((bridge.history.consumption.usages, self.resolver.requests), ((), []))

    async def test_joint_competition_never_publishes_partial_state_or_available_invoice(self):
        bridge = self.bridge()
        lines = tuple(POQueryLine(line, 1500, "hours", (self.exact(line_id=line, quantity_milli=1500),))
                      for line in ("L-A", "L-B"))
        result = await bridge.resolve_lines(lines, invoice_id="NEW", invoice_date="2031-11-01",
                                           receipt_as_of="2031-11-09")
        self.assertTrue(all(m.quantity_status == "AVAILABLE" for m in result.matches))
        self.assertEqual(result.quantity_status, "INSUFFICIENT")
        self.assertIn("BATCH:INSUFFICIENT_RECEIPTS", result.diagnostics)
        self.assertFalse(hasattr(result, "state"))
        self.assertEqual(bridge.history.consumption.usages, ())

    async def test_batch_preserves_historical_usage_and_missing_portion_blocks_entire_invoice(self):
        key = OrderKey("1100", "V-NEW", "EUR", "PO-NEW", 10)
        bridge = self.bridge((HistoricalDemand(key, 1000, (Evidence("history", "OLD"),)),))
        before = bridge.history.consumption
        lines = (POQueryLine("L-NEW", 1500, "hours", (self.exact(quantity_milli=1500),)),)
        result = await bridge.resolve_lines(lines, invoice_id="NEW", invoice_date="2031-11-01", receipt_as_of="2031-11-09")
        self.assertEqual(result.quantity_status, "INSUFFICIENT")
        self.assertEqual(bridge.history.consumption, before)
        unresolved = POQueryLine("L-OTHER", 1000, "hours", (self.exact(line_id="L-OTHER", material="MISSING"),))
        result = await bridge.resolve_lines((*lines, unresolved), invoice_id="NEW", invoice_date="2031-11-01", receipt_as_of="2031-11-09")
        self.assertEqual((result.reference_status, result.quantity_status, result.quantity_lines), ("UNKNOWN", "UNKNOWN", ()))
        self.assertEqual(bridge.history.consumption, before)

    async def test_nonconserving_or_cross_scope_portions_fail_before_semantic_calls(self):
        for portions in ((self.exact(quantity_milli=500),),
                         (self.exact(), replace(self.exact(), portion_id="2", vendor="OTHER"))):
            with self.assertRaises(ValueError):
                await self.bridge().resolve_lines((POQueryLine("L-NEW", 1000, "hours", portions),),
                    invoice_id="NEW", invoice_date="2031-11-01", resolver=self.resolver)
        self.assertEqual(self.resolver.requests, [])

    async def test_fact_bridge_confirms_exact_order_and_keeps_invoice_date_distinct_from_cutoff(self):
        values = dict(document_date="2031-11-01", currency="EUR", lines=[dict(
            quantity="1", uom="hours", po_reference="PO-NEW", po_item=10)])
        facts = DocumentFacts(self.doc.source_sha256, "fixture", {k: [Fact(v, Evidence(self.path, k))]
                              for k, v in values.items()})
        before_receipt = await self.bridge().resolve_facts(facts, company="1100", vendor="V-NEW", currency="EUR",
            invoice_id="NEW", document=self.doc, resolver=self.resolver)
        later = await self.bridge().resolve_facts(facts, company="1100", vendor="V-NEW", currency="EUR",
            invoice_id="NEW", receipt_as_of="2031-11-09", document=self.doc, resolver=self.resolver)
        self.assertEqual((before_receipt.quantity_status, later.quantity_status), ("INSUFFICIENT", "AVAILABLE"))
        self.assertEqual(self.resolver.requests, [])
        with self.assertRaisesRegex(ValueError, "fingerprints disagree"):
            await self.bridge().resolve_facts(replace(facts, source_sha256="b" * 64), company="1100", vendor="V-NEW",
                currency="EUR", invoice_id="NEW", document=self.doc)

    async def test_known_out_of_scope_order_never_reaches_semantic_replacement(self):
        self.orders.append(dict(self.orders[0], id="FOREIGN", currency="USD"))
        match = await self.resolve(replace(self.query, po_reference="FOREIGN"))
        self.assertEqual((match.reference.status, match.semantic_called, match.quantity_line), ("CONFLICT", False, None))
        self.assertEqual(self.resolver.requests, [])

    async def test_joint_deficit_with_other_unknown_receipt_capacity_stays_unknown(self):
        bridge = self.bridge()
        known = bridge.history.certainties[0]
        row = dict(self.receipts[0], id="R-UNKNOWN", quantity_milli=1000, amount=1000)
        uncertain = ReceiptCertainty(replace(known.receipt, receipt_id="R-UNKNOWN", quantity_milli=1000),
            "UNKNOWN", None, 0, 1000, (Evidence("history", "unresolved carrying quantity"),))
        history = HistoricalReceiptSnapshot((known, uncertain), bridge.history.consumption)
        bridge = APOrderBridge(orders=self.orders, receipts=(*self.receipts, row), history=history)
        lines = tuple(POQueryLine(line, 1500, "hours", (self.exact(line_id=line, quantity_milli=1500),))
                      for line in ("L-A", "L-B"))
        result = await bridge.resolve_lines(lines, invoice_id="NEW", invoice_date="2031-11-01", receipt_as_of="2031-11-09")
        self.assertTrue(all(match.quantity_status == "AVAILABLE" for match in result.matches))
        self.assertEqual((result.quantity_status, result.quantity_lines), ("UNKNOWN", ()))
        self.assertIn("HISTORICAL_RECEIPT_CAPACITY_UNKNOWN", result.diagnostics)
        self.assertEqual(history.consumption.usages, ())

    async def test_batch_already_allocated_identity_does_not_authorize_another_consumption(self):
        bridge = self.bridge()
        state = ConsumptionState(invoices=(("1100", "V-NEW", "EUR", "NEW"),))
        lines = (POQueryLine("L-NEW", 1000, "hours", (self.exact(),)),)
        result = await bridge.resolve_lines(lines, invoice_id="NEW", invoice_date="2031-11-01",
                                           receipt_as_of="2031-11-09", state=state)
        self.assertEqual((result.quantity_status, result.quantity_lines), ("UNKNOWN", ()))
        self.assertIn("BATCH:ALREADY_ALLOCATED", result.diagnostics)
        self.assertEqual(state.usages, ())


if __name__ == "__main__":
    unittest.main()
