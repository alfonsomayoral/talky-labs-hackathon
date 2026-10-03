import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from kalmora.ar_cash.remittances import read_applications, read_face_application
from kalmora.data import PhaseData


class StubRouter:
    def __init__(self, text):
        self.text = text

    def parse(self, relative):
        return SimpleNamespace(blocks=(SimpleNamespace(text=self.text),), warnings=(),
                               source_sha256="a" * 64)


class RemittanceReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.phase = Path(self.temp.name) / "phase_dev"
        (self.phase / "erp").mkdir(parents=True)
        (self.phase / "tasks").mkdir()
        (self.phase / "inbox/ar/remittances").mkdir(parents=True)
        (self.phase / "erp/companies.jsonl").write_text(
            json.dumps({"code": "1100", "name": "Kalmora Test, S.A."}) + "\n", encoding="utf-8")
        (self.phase / "tasks/close.json").write_text(json.dumps({"month": "2026-07"}), encoding="utf-8")
        (self.phase / "inbox/ar/remittances/notice.json").write_text(
            json.dumps({"file": "notice.pdf"}), encoding="utf-8")
        self.text = ("Beneficiario: Kalmora Test, S.A. · Fecha valor: 10/07/2026\n"
                     "Factura                      Importe\n"
                     "INV-1                        100,00 EUR\n"
                     "Importe total transferido: 100,00 EUR")
        (self.phase / "erp/ar_invoices.jsonl").write_text(
            json.dumps({"id": "INV-1", "company": "1100", "customer": "C1",
                        "currency": "EUR", "payable": 10000}) + "\n", encoding="utf-8")

    def test_accepts_unique_matching_table_with_exact_total(self):
        result, diagnostics = read_applications(
            PhaseData(self.phase), StubRouter(self.text), "notice.json", "1100",
            "2026-07-10", 10000, "EUR")
        self.assertEqual(result, [("INV-1", 10000)])
        self.assertIn("sha256=" + "a" * 64, diagnostics[0])

    def test_rejects_total_or_currency_conflicts(self):
        result, diagnostics = read_applications(
            PhaseData(self.phase), StubRouter(self.text), "notice.json", "1100",
            "2026-07-10", 10001, "EUR")
        self.assertIsNone(result)
        self.assertIn("mismatch", diagnostics[0])

    def test_accepts_only_exact_paid_face_invoice_for_date_and_company(self):
        path = self.phase / "inbox/ar/remittances/FACe_customer.csv"
        path.write_text("normalized source fixture", encoding="utf-8")
        router = StubRouter("numero_factura;importe_pagado;estado;fecha_estado\n"
                            "INV-1;100,00;PAGADA;10/07/2026\n")
        result, diagnostics = read_face_application(
            PhaseData(self.phase), router, "1100", "2026-07-10", 10000, "EUR", "C1")
        self.assertEqual(result, [("INV-1", 10000)])
        self.assertTrue(any("FACe paid-invoice match" in item for item in diagnostics))

    def test_face_date_or_customer_conflicts_do_not_select_invoice(self):
        (self.phase / "inbox/ar/remittances/FACe_customer.csv").write_text(
            "normalized source fixture", encoding="utf-8")
        router = StubRouter("numero_factura;importe_pagado;estado;fecha_estado\n"
                            "INV-1;100,00;PAGADA;09/07/2026\n")
        result, _ = read_face_application(
            PhaseData(self.phase), router, "1100", "2026-07-10", 10000, "EUR", "C1")
        self.assertIsNone(result)
