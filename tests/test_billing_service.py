import unittest
from kalmora.billing import BillingType, build_ar_billing
from kalmora.billing.inputs import ExtraService, RevisionFacts, ServiceFacts
from billing_support import BillingCase, HistoryCase, REAL


class ServiceTests(BillingCase):
    def test_month_end_current_fee_and_only_conforming_extras(self):
        facts = ServiceFacts("2026-07", 11000, (ExtraService("E1", "Conforme", 2000, True), ExtraService("E2", "Pendiente", 5000, False)))
        result = self.run_item(facts, self.item(BillingType.SERVICE_MONTHLY)).results[0]
        self.assertEqual((result.invoice.net, result.invoice.date), (13000, "2026-07-31"))
        self.assertEqual({(x.account, x.cost_center) for x in result.invoice.lines}, {("70500000", "CC-1100-SVC")})
        self.assertIn("E2", result.diagnostics[0])

    def test_approved_canon_is_checked_before_service_regardless_of_input_order(self):
        service, revision = self.item(BillingType.SERVICE_MONTHLY, "S"), self.item(BillingType.PRICE_REVISION, "R")
        decree = RevisionFacts(10000, 11000, "2026-06-01", "2026-07-02", ("2026-06",), "D1")
        for items in ([service, revision], [revision, service]):
            for canon in (10000, 11000):
                with self.subTest(order=[i.id for i in items], canon=canon):
                    run = build_ar_billing(self.data(), items, {"S": ServiceFacts("2026-07", canon), "R": decree})
                    self.assertEqual([u.item.id for u in run.unresolved], ["S"] if canon == 10000 else [])
                    self.assertEqual([r.item.id for r in run.results], [i.id for i in items if canon == 11000 or i.id == "R"])


@unittest.skipUnless((REAL / "erp").is_dir(), "development source package unavailable")
class ServiceHistoryTests(HistoryCase):
    def test_original_services_reproduce_original_invoices(self):
        self.assert_history(BillingType.SERVICE_MONTHLY)
