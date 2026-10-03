"""Small independent ERP phase and optional source-package regression support."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from kalmora.billing import BillingItem, BillingType, build_ar_billing
from kalmora.billing.history import facts_from_history, item_from_history
from kalmora.billing.inputs import CertificationFacts, Chapter
from kalmora.data import PhaseData

REAL = Path(os.environ.get("KALMORA_PHASE_DEV", Path(__file__).resolve().parents[1] / "participant/phase_dev"))


class BillingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "erp").mkdir()
        (self.root / "tasks").mkdir()
        (self.root / "tasks/close.json").write_text('{"month":"2026-07"}')
        self.tables = {
            "companies": [{"code": "1100", "country": "ES"}],
            "tax_codes": {"tax_codes": {"R21": {"kind": "output", "country": "ES", "rate": 2100}}},
            "customers": [{"id": "C1", "name": "Municipio", "kind": "public", "country": "ES",
                           "dir3": {"oficina_contable": "L1", "organo_gestor": "L2", "unidad_tramitadora": "L3"}}],
            "cost_centers": [{"id": "CC-1100-SVC", "company": "1100", "desc": "Servicio"},
                             {"id": "CC-1100-ADM", "company": "1100", "desc": "Administración"}],
            "projects": [{"id": "P1", "company": "1100", "wbs": [{"id": "P1.01"}, {"id": "P1.02"}]}],
            "sales_contracts": [{"id": "CV1", "company": "1100", "customer": "C1", "name": "Contrato",
                                 "project": "P1", "cc": "CC-1100-SVC", "tax": "R21", "terms_days": 30}],
            "ar_invoices": [], "billing_history": [],
        }

    def data(self):
        for name, rows in self.tables.items():
            (self.root / f"erp/{name}.json").write_text(json.dumps(rows), encoding="utf-8")
        return PhaseData(self.root)

    def item(self, kind=BillingType.OBRA_CERTIFICATION, id="B1", **changes):
        return BillingItem(id, kind, changes.get("company", "1100"), changes.get("contract", "CV1"),
                           changes.get("customer", "C1"), changes.get("month", "2026-07"))

    def cert(self, **changes):
        fields = dict(month="2026-07", chapters=(Chapter(1, "Capítulo 1", 10000), Chapter(2, "Capítulo 2", 20000)),
                      cumulative=130000, previous=100000, current=30000, approved=True)
        fields.update(changes)
        return CertificationFacts(**fields)

    def run_item(self, facts, item=None, **options):
        item = item or self.item()
        return build_ar_billing(self.data(), [item], {item.id: facts}, **options)


class HistoryCase(unittest.TestCase):
    def assert_history(self, kind):
        data = PhaseData(REAL)
        rows = data.find("billing_history", type=kind.value)
        self.assertTrue(rows)
        items = [item_from_history(row) for row in rows]
        run = build_ar_billing(data, items, {row["id"]: facts_from_history(row) for row in rows}, strict_duplicates=False)
        self.assertEqual(run.unresolved, ())
        for result in run.results:
            if result.invoice is None:
                self.assertFalse(next(r for r in rows if r["id"] == result.item.id)["cert"]["approved"])
                continue
            invoice = result.invoice
            originals = [r for r in data.find("ar_invoices", contract=result.item.contract)
                         if r["date"] == invoice.date and r["kind"] == "invoice"]
            self.assertEqual(len(originals), 1, result.item.id)
            for field in ("date", "due_date", "tax_code", "net", "tax", "gross", "retention", "payable", "currency"):
                self.assertEqual(getattr(invoice, field), originals[0][field], (result.item.id, field))
            self.assertEqual([dict(code=d.code, amount=d.amount, account=d.account) for d in invoice.deductions], originals[0]["deductions"])
