import json
from pathlib import Path
import tempfile
import unittest

from kalmora.ap_allocation import ConsumptionState
from kalmora.ap_hold_sources import resolve_hold_sources
from kalmora.data import PhaseData
from kalmora.facts import DocumentFacts, Evidence, Fact
from kalmora.model.ap_event import ApEvent
from kalmora.model.ap_scope import ApScope

IBAN = "ES9121000418450200051332"
OTHER_IBAN = "ES7921000813610123456789"


class HoldSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "tasks").mkdir()
        (root / "erp").mkdir()
        (root / "tasks/close.json").write_text('{"month": "2026-07"}')
        vendor = dict(tax_id="B11111111", country="ES", currency="EUR", po_required=True,
                      companies=["1100"], bank={"iban": IBAN}, email="facturas@acme-hierros.es")
        rows = {
            "companies.json": [dict(code="1100", tax_id="A22222222", country="ES", currency="EUR")],
            "vendors.jsonl": [dict(vendor, id="V1"),
                              dict(vendor, id="V2", tax_id="B33333333", currency="USD", country="US",
                                   email="billing@acme.us"),
                              dict(vendor, id="V3", tax_id="B44444444", po_required=False,
                                   email="ventas@ferreteria.es")],
            "purchase_orders.jsonl": [
                dict(id="PO1", company="1100", vendor="V1", currency="EUR", created_on="2026-06-01",
                     items=[dict(item=10, uom="ud", unit_price=10000)]),
                dict(id="PO2", company="1100", vendor="V2", currency="USD", created_on="2026-06-01",
                     items=[dict(item=10, uom="ud", unit_price=100000)]),
                dict(id="PO3", company="1100", vendor="V1", currency="EUR", created_on="2026-06-01",
                     items=[dict(item=10, uom="t", unit_price=1000, description="Arena 0/4"),
                            dict(item=20, uom="t", unit_price=2000, description="Grava 6/20")])],
            "goods_receipts.jsonl": [
                dict(id="R1", type="GR", company="1100", po="PO1", po_item=10, vendor="V1",
                     posting_date="2026-07-05", quantity_milli=200000, reference="AL-1"),
                dict(id="R2", type="GR", company="1100", po="PO2", po_item=10, vendor="V2",
                     posting_date="2026-07-05", quantity_milli=100000, reference="AL-2"),
                dict(id="R3", type="GR", company="1100", po="PO1", po_item=10, vendor="V1",
                     posting_date="2026-08-02", quantity_milli=1000, reference="AL-LATE"),
                dict(id="R4", type="GR", company="1100", po="PO3", po_item=20, vendor="V1",
                     posting_date="2026-07-05", quantity_milli=5000, reference="AL-3")],
            "contractor_certificates.jsonl": [],
            "fx_rates.jsonl": [dict(date="2026-07-01", base="EUR", currency="USD", rate="1.2")],
        }
        for name, value in rows.items():
            text = json.dumps(value) if name.endswith(".json") else "\n".join(map(json.dumps, value))
            (root / "erp" / name).write_text(text)
        cls.data = PhaseData(root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_holds(self, *, tax_id="B11111111", iban=IBAN, sender="facturas@acme-hierros.es",
                  qty=1000, price="1000000", po="PO1", delivery="AL-1", currency="EUR", notices=(),
                  state=ConsumptionState(), uom="Ud.", description=None, document="factura.pdf"):
        values = {"supplier_tax_id": tax_id, "recipient_tax_id": "A22222222",
                  "document_date": "2026-07-10", "currency": currency, "iban": iban,
                  "line.1.quantity_milli": qty, "line.1.uom": uom, "line.1.unit_price_e4": int(price),
                  "line.1.po_reference": po, "line.1.po_item": None if description else "10",
                  "line.1.delivery_reference": delivery, "line.1.description": description}
        facts = DocumentFacts("0" * 64, "test", {
            name: [Fact(value, Evidence(document, name))] for name, value in values.items()
            if value is not None or name in {"iban", "line.1.delivery_reference"}})
        message = {"channel": "email", "received_at": "2026-07-20T09:00:00", "from": sender}
        return resolve_hold_sources(doc_id="API1", documents=[facts], message=message, data=self.data,
                                    notices=notices, state=state)

    def reason(self, **kwargs):
        stage = self.run_holds(**kwargs).stage
        return stage.reason if stage.status == "HOLD" else stage.status

    def test_clear_invoice(self):
        self.assertEqual(self.reason(), "CLEAR")

    def test_vendor_not_in_master(self):
        self.assertEqual(self.reason(tax_id="B99999999"), "VENDOR_NOT_IN_MASTER")

    def test_iban_change_holds_unless_a_verified_month_letter_supports_it(self):
        self.assertEqual(self.reason(iban=OTHER_IBAN), "BANK_DETAILS_CHANGED")
        letter = ApEvent("API0/carta.pdf", ApScope("1100", "V1", "EUR"), "BANK_DETAILS_CHANGE",
                         (Evidence("carta.pdf", "new_iban"),), received_at="2026-07-03T10:00:00",
                         verified=True, value=OTHER_IBAN)
        self.assertEqual(self.reason(iban=OTHER_IBAN, notices=(letter,)), "CLEAR")
        self.assertEqual(self.reason(iban=None), "CLEAR")

    def test_xml_e_invoice_without_payment_details_states_no_account(self):
        self.assertEqual(self.reason(iban=None, document="facturae.xml"), "CLEAR")
        absent = self.run_holds(iban=None, document="factura.pdf").stage.checks[1]
        self.assertFalse(absent.violation)  # explicit absence fact
        missing = resolve_hold_sources(doc_id="API1", documents=[DocumentFacts("0" * 64, "t", {
            "supplier_tax_id": [Fact("B11111111", Evidence("factura.pdf", "supplier_tax_id"))]})],
            message={"channel": "portal", "received_at": "2026-07-20T09:00:00"}, data=self.data)
        self.assertIsNone(missing.stage.checks[1].violation)

    def test_look_alike_sender_domain_is_fraud_but_unrelated_domain_is_not(self):
        self.assertEqual(self.reason(sender="facturas@acme-hierros-es.es"), "BANK_DETAILS_CHANGED")
        self.assertEqual(self.reason(sender="Admin <facturas@acme-hierros.com>"), "BANK_DETAILS_CHANGED")
        self.assertEqual(self.reason(sender="gestoria@contaplus.es"), "CLEAR")

    def test_invoiced_delivery_without_receipt_by_close_and_state_untouched(self):
        self.assertEqual(self.reason(delivery="AL-404"), "QTY_NOT_RECEIVED")
        self.assertEqual(self.reason(delivery="AL-LATE"), "QTY_NOT_RECEIVED")  # posted after the close
        state = ConsumptionState()
        result = self.run_holds(qty=201000, delivery=None, state=state)
        self.assertEqual(result.stage.reason, "QTY_NOT_RECEIVED")
        self.assertIs(result.allocation.state, state)

    def test_albaran_of_vendor_without_po_requirement_is_not_a_receipt_gap(self):
        self.assertEqual(self.reason(tax_id="B44444444", sender="ventas@ferreteria.es", po=None,
                                     delivery="AL-404"), "CLEAR")

    def test_printed_concept_selects_among_same_unit_po_items(self):
        line = dict(po="PO3", uom="t", qty=5000, price="20000", delivery=None)
        self.assertEqual(self.reason(description="Grava 6/20 – AL-3 (05/06)", **line), "CLEAR")
        self.assertEqual(self.reason(description="Material vario", **line), "UNKNOWN")

    def test_eur_price_thresholds_are_strict(self):
        self.assertEqual(self.reason(price="1020000"), "CLEAR")  # exactly 2%
        self.assertEqual(self.reason(price="1020100"), "PRICE_VARIANCE")
        self.assertEqual(self.reason(price="1010000", qty=150000), "CLEAR")  # exactly EUR 150
        self.assertEqual(self.reason(price="1010000", qty=151000), "PRICE_VARIANCE")

    def test_non_eur_line_uses_invoice_date_rate(self):
        usd = dict(tax_id="B33333333", po="PO2", delivery="AL-2", currency="USD", sender="billing@acme.us")
        self.assertEqual(self.reason(price="10100000", qty=18000, **usd), "CLEAR")  # USD 180 = EUR 150
        self.assertEqual(self.reason(price="10100000", qty=19000, **usd), "PRICE_VARIANCE")

    def test_precedence_when_several_apply(self):
        self.assertEqual(self.reason(sender="facturas@acme-hierros-es.es", delivery="AL-404",
                                     price="2000000"), "BANK_DETAILS_CHANGED")
        self.assertEqual(self.reason(delivery="AL-404", price="2000000"), "QTY_NOT_RECEIVED")


if __name__ == "__main__":
    unittest.main()
