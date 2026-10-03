import unittest
from kalmora.billing import BillingType
from billing_support import BillingCase, HistoryCase, REAL


class CertificationTests(BillingCase):
    def test_current_chapters_wbs_and_month_end(self):
        run = self.run_item(self.cert())
        self.assertEqual(run.unresolved, ())
        invoice = run.results[0].invoice
        self.assertEqual((invoice.net, invoice.date), (30000, "2026-07-31"))
        self.assertEqual([(x.amount, x.wbs, x.account) for x in invoice.lines],
                         [(10000, "P1.01", "70510000"), (20000, "P1.02", "70510000")])

    def test_inconsistent_cumulative_and_chapters_are_blocked(self):
        for facts in (self.cert(cumulative=130001), self.cert(current=30001)):
            with self.subTest(facts=facts):
                self.assertEqual(len(self.run_item(facts).unresolved), 1)

    def test_previous_is_last_approved_not_last_pending(self):
        self.tables["billing_history"] = [
            dict(contract="CV1", type="OBRA_CERTIFICATION", cert=dict(month="2026-05", cumulative=100000, approved=True)),
            dict(contract="CV1", type="OBRA_CERTIFICATION", cert=dict(month="2026-06", cumulative=120000, approved=False))]
        self.assertEqual(self.run_item(self.cert()).unresolved, ())
        self.assertEqual(len(self.run_item(self.cert(previous=120000, cumulative=150000)).unresolved), 1)


@unittest.skipUnless((REAL / "erp").is_dir(), "development source package unavailable")
class CertificationHistoryTests(HistoryCase):
    def test_original_certifications_reproduce_original_invoices(self):
        self.assert_history(BillingType.OBRA_CERTIFICATION)
