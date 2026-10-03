import json
from pathlib import Path
import tempfile
import unittest

from kalmora.ap_allocation import ConsumptionState
from kalmora.ap_hold_sources import resolve_hold_sources
from kalmora.data import PhaseData
from kalmora.facts import DocumentFacts, Evidence, Fact

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
                              dict(vendor, id="V2", tax_id="B33333333", currency="USD", country="US")],
            "purchase_orders.jsonl": [
                dict(id="PO1", company="1100", vendor="V1", currency="EUR", created_on="2026-06-01",
                     items=[dict(item=10, uom="ud", unit_price=10000)]),
                dict(id="PO2", company="1100", vendor="V2", currency="USD", created_on="2026-06-01",
                     items=[dict(item=10, uom="ud", unit_price=100000)])],
            "goods_receipts.jsonl": [
                dict(id="R1", type="GR", company="1100", po="PO1", po_item=10, vendor="V1",
                     posting_date="2026-07-05", quantity_milli=200000, reference="AL-1"),
                dict(id="R2", type="GR", company="1100", po="PO2", po_item=10, vendor="V2",
                     posting_date="2026-07-05", quantity_milli=100000, reference="AL-2"),
                dict(id="R3", type="GR", company="1100", po="PO1", po_item=10, vendor="V1",
                     posting_date="2026-07-25", quantity_milli=1000, reference="AL-LATE")],
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
                  qty=1000, price="1000000", po="PO1", delivery="AL-1", currency="EUR", support=None,
                  state=ConsumptionState()):
        values = {"supplier_tax_id": tax_id, "recipient_tax_id": "A22222222",
                  "document_date": "2026-07-10", "currency": currency, "iban": iban,
                  "line.1.quantity_milli": qty, "line.1.uom": "Ud.", "line.1.unit_price_e4": int(price),
                  "line.1.po_reference": po, "line.1.po_item": "10", "line.1.delivery_reference": delivery}
        facts = DocumentFacts("0" * 64, "test", {
            name: [Fact(value, Evidence("factura.pdf", name))] for name, value in values.items()})
        message = {"channel": "email", "received_at": "2026-07-20T09:00:00", "from": sender}
        return resolve_hold_sources(doc_id="API1", facts=facts, message=message, data=self.data,
                                    support=support, state=state)

    def reason(self, **kwargs):
        stage = self.run_holds(**kwargs).stage
        return stage.reason if stage.status == "HOLD" else stage.status

    def test_clear_invoice(self):
        self.assertEqual(self.reason(), "CLEAR")

    def test_vendor_not_in_master(self):
        self.assertEqual(self.reason(tax_id="B99999999"), "VENDOR_NOT_IN_MASTER")

    def test_iban_change_holds_only_without_support(self):
        letter = {name: (Fact(False, Evidence("erp", "inventory")),)
                  for name in ("signed_change_supported", "factoring_supported")}
        self.assertEqual(self.reason(iban=OTHER_IBAN, support=letter), "BANK_DETAILS_CHANGED")
        self.assertEqual(self.reason(iban=OTHER_IBAN), "UNKNOWN")
        supported = dict(letter, signed_change_supported=(Fact(True, Evidence("carta.pdf", "iban")),))
        self.assertEqual(self.reason(iban=OTHER_IBAN, support=supported), "CLEAR")
        self.assertEqual(self.reason(iban=None), "CLEAR")

    def test_look_alike_sender_domain_is_fraud_but_unrelated_domain_is_not(self):
        self.assertEqual(self.reason(sender="facturas@acme-hierros-es.es"), "BANK_DETAILS_CHANGED")
        self.assertEqual(self.reason(sender="Admin <facturas@acme-hierros.com>"), "BANK_DETAILS_CHANGED")
        self.assertEqual(self.reason(sender="gestoria@contaplus.es"), "CLEAR")

    def test_invoiced_delivery_without_receipt_by_cutoff_and_state_untouched(self):
        state = ConsumptionState()
        result = self.run_holds(delivery="AL-404", state=state)
        self.assertEqual(result.stage.reason, "QTY_NOT_RECEIVED")
        self.assertIs(result.allocation.state, state)
        self.assertEqual(self.reason(delivery="AL-LATE"), "QTY_NOT_RECEIVED")  # posted after arrival
        self.assertEqual(self.reason(qty=201000, delivery=None), "QTY_NOT_RECEIVED")

    def test_eur_price_thresholds_are_strict(self):
        self.assertEqual(self.reason(price="1020000"), "CLEAR")  # exactly 2%
        self.assertEqual(self.reason(price="1020100"), "PRICE_VARIANCE")
        self.assertEqual(self.reason(price="1010000", qty=150000), "CLEAR")  # exactly EUR 150
        self.assertEqual(self.reason(price="1010000", qty=151000), "PRICE_VARIANCE")

    def test_non_eur_line_uses_invoice_date_rate(self):
        usd = dict(tax_id="B33333333", po="PO2", delivery="AL-2", currency="USD")
        self.assertEqual(self.reason(price="10100000", qty=18000, **usd), "CLEAR")  # USD 180 = EUR 150
        self.assertEqual(self.reason(price="10100000", qty=19000, **usd), "PRICE_VARIANCE")

    def test_precedence_when_several_apply(self):
        self.assertEqual(self.reason(sender="facturas@acme-hierros-es.es", delivery="AL-404",
                                     price="2000000"), "BANK_DETAILS_CHANGED")
        self.assertEqual(self.reason(delivery="AL-404", price="2000000"), "QTY_NOT_RECEIVED")


if __name__ == "__main__":
    unittest.main()
