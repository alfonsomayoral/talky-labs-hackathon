"""Observed fact quantities and MULTI_PO relations, with no extraction calls."""
from dataclasses import replace
import json
import os
from pathlib import Path
from hashlib import sha256
from zipfile import ZipFile
import unittest

from kalmora.ap_order_sources import order_queries_from_facts
from kalmora.ap_orders import POCatalog
from kalmora.documents.normalization import normalize_document_facts
from kalmora.facts import DocumentFacts, Evidence, Fact


class OrderSourceTests(unittest.TestCase):
    def facts(self, fields=None):
        values = dict(document_date="2031-11-01", currency="EUR", line_count=1,
                      **{"line.1.quantity": "2", "line.1.uom": "hours", "line.1.po_reference": "PO-A"})
        values.update(fields or {})
        return DocumentFacts("a" * 64, "fixture", {k: [Fact(v, Evidence("invoice.pdf", k))]
                                                   for k, v in values.items()})

    def resolve(self, facts):
        return order_queries_from_facts(facts, company="1100", vendor="V-NEW", currency="EUR")

    def test_flat_and_normalized_document_facts_preserve_scope_quantity_and_proof(self):
        raw = self.facts({"line.1.po_item": "10", "line.1.delivery_reference": "DELIVERY-NEW"})
        for facts in (raw, normalize_document_facts(raw).facts):
            result = self.resolve(facts)
            self.assertEqual((result.status, result.invoice_date), ("READY", "2031-11-01"))
            q = result.lines[0].portions[0]
            self.assertEqual((q.company, q.vendor, q.currency, q.quantity_milli, q.po_item),
                             ("1100", "V-NEW", "EUR", 2000, 10))
            self.assertEqual(q.receipt_references, ("DELIVERY-NEW",))
            self.assertIn(raw.fields["line.1.quantity"][0].evidence, q.evidence)

    def test_observed_nested_multi_po_portions_conserve_source_quantity(self):
        raw = self.facts({"lines": [dict(quantity="2", uom="hours", po_reference="MULTI_PO",
            po_portions=[dict(po_reference="PO-A", po_item=10, quantity="0,75"),
                         dict(po_reference="PO-B", po_item=20, quantity_milli=1250)])]})
        raw = replace(raw, fields={k: v for k, v in raw.fields.items() if not k.startswith("line.")})
        result = self.resolve(raw)
        self.assertEqual(result.status, "READY")
        self.assertEqual([(q.po_reference, q.quantity_milli) for q in result.lines[0].portions],
                         [("PO-A", 750), ("PO-B", 1250)])
        self.assertEqual(result.lines[0].quantity_milli, 2000)

    def test_split_unknown_zero_or_nonconserving_never_exports_partial_lines(self):
        for portions in ([dict(po_reference="PO-A"), dict(po_reference="PO-B")],
                         [dict(po_reference="PO-A", quantity="0")],
                         [dict(po_reference="PO-A", quantity="1")]):
            result = self.resolve(self.facts({"line.1.po_portions": portions}))
            self.assertEqual((result.status, result.lines), ("UNKNOWN", ()))
        result = self.resolve(self.facts({"line.1.po_reference": "MULTI_PO"}))
        self.assertIn("line.1:MULTI_PO_PORTIONS_UNKNOWN", result.diagnostics)

    def test_missing_quantity_cannot_be_recovered_from_amount_price_or_capacity(self):
        raw = self.facts({"line.1.quantity": None, "line.1.amount": "200", "line.1.unit_price": "100"})
        self.assertEqual(self.resolve(raw).status, "UNKNOWN")

    def test_conflicting_quantity_scope_currency_and_incomplete_rows_abstain(self):
        raw = self.facts()
        raw.fields["line.1.quantity"].append(Fact("3", Evidence("invoice.pdf", "other_quantity")))
        self.assertEqual(self.resolve(raw).lines, ())
        for changes in ({"currency": "USD"}, {"line_count": 2}, {"line.1.quantity": "1,234"}):
            self.assertEqual(self.resolve(self.facts(changes)).status, "UNKNOWN")

    def test_xml_delivery_fields_and_observed_dates_are_not_interpreted_as_receipts(self):
        raw = self.facts({"line.1.delivery.1.document_number": "D1",
                          "line.1.delivery.2.document_number": "D2"})
        result = self.resolve(raw)
        self.assertEqual(result.lines[0].portions[0].receipt_references, ("D1", "D2"))
        self.assertEqual(result.invoice_date, "2031-11-01")

    def test_existing_extractor_project_and_receipt_vocabulary_is_preserved(self):
        result = self.resolve(self.facts({"project_reference": "PROJECT-NEW", "receipt_reference": "D1"}))
        self.assertEqual((result.lines[0].portions[0].project, result.lines[0].portions[0].receipt_references),
                         ("PROJECT-NEW", ("D1",)))
        self.assertEqual(self.resolve(self.facts({"line.1.currency": "USD"})).status, "UNKNOWN")

    def test_header_receipt_for_multiple_rows_needs_observed_row_bindings(self):
        facts = self.facts({"line_count": 2, "receipt_reference": "D1", "line.2.quantity": "1",
                            "line.2.uom": "hours", "line.2.po_reference": "PO-A"})
        self.assertEqual(self.resolve(facts).status, "UNKNOWN")
        facts.fields["line.1.delivery_reference"] = [Fact("D1", Evidence("invoice.pdf", "delivery"))]
        self.assertEqual(self.resolve(facts).status, "READY")

    def test_header_po_can_be_inherited_but_aggregate_delivery_cannot_be_assigned_to_split(self):
        raw = self.facts({"line.1.po_reference": None, "po_reference": "PO-A"})
        # A source null is unknown; it must not silently borrow a different field.
        self.assertIsNone(self.resolve(raw).lines[0].portions[0].po_reference)
        raw.fields.pop("line.1.po_reference")
        self.assertEqual(self.resolve(raw).lines[0].portions[0].po_reference, "PO-A")
        raw = self.facts({"line.1.delivery_reference": "D1", "line.1.po_portions": [
            dict(po_reference="PO-A", quantity="1"), dict(po_reference="PO-B", quantity="1")]})
        self.assertEqual((self.resolve(raw).status, self.resolve(raw).lines), ("UNKNOWN", ()))

    @unittest.skipUnless(os.environ.get("KALMORA_ORDER_PHASE") or os.environ.get("KALMORA_ORDER_ZIP"),
                         "set original phase path or test ZIP for source-only PO audit")
    def test_all_original_received_positions_confirm_their_actual_receipt_association(self):
        names = ("purchase_orders", "goods_receipts")
        if archive := os.environ.get("KALMORA_ORDER_ZIP"):
            with ZipFile(archive) as source:
                # Exact original table members only; no extraction or golden.
                content = {name: source.read("participant/phase_test/erp/" + name + ".jsonl") for name in names}
        else:
            phase = Path(os.environ["KALMORA_ORDER_PHASE"])
            self.assertNotIn("golden", phase.resolve().parts)
            content = {name: (phase / "erp" / (name + ".jsonl")).read_bytes() for name in names}
        orders = [json.loads(line) for line in content["purchase_orders"].splitlines()]
        receipts = [json.loads(line) for line in content["goods_receipts"].splitlines()]
        catalog = POCatalog(orders=orders, receipts=receipts)
        items = {(r["company"], r["id"], i["item"]): (r, i) for r in orders for i in r["items"]}
        # All receipt rows are validated by catalog construction. Audit one
        # observed receipt ID per actual position, not 21k identical monthly
        # references for the same few hundred recurring-service positions.
        positions = {(r["company"], r["po"], r["po_item"]): r for r in receipts}
        for receipt in positions.values():
            order, item = items[receipt["company"], receipt["po"], receipt["po_item"]]
            values = dict(document_date=max(order["created_on"], receipt["posting_date"]), currency=order["currency"],
                lines=[dict(quantity_milli=receipt["quantity_milli"], uom=item["uom"],
                            delivery_reference=receipt["id"])])
            facts = DocumentFacts("a" * 64, "source-audit", {k: [Fact(v, Evidence("erp/goods_receipts.jsonl", receipt["id"]))]
                                                          for k, v in values.items()})
            observed = order_queries_from_facts(facts, company=order["company"], vendor=order["vendor"], currency=order["currency"])
            self.assertEqual(observed.status, "READY")
            result = catalog.resolve(observed.lines[0].portions[0], invoice_date=observed.invoice_date)
            self.assertEqual((result.status, result.selected.order.po, result.selected.order.item),
                             ("RESOLVED", receipt["po"], receipt["po_item"]))
        self.assertTrue(receipts)
        print(json.dumps(dict(order_source_audit=dict(orders=len(orders), receipts=len(receipts),
            positions=len(positions), sha256={name: sha256(data).hexdigest() for name, data in content.items()})),
            sort_keys=True))
