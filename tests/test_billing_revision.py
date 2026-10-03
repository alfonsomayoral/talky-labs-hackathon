import unittest
from kalmora.billing import BillingType
from kalmora.billing.inputs import RevisionFacts
from billing_support import BillingCase, HistoryCase, REAL


class RevisionTests(BillingCase):
    def facts(self, **changes):
        args = dict(old_fee=10000, new_fee=11000, effective="2026-01-01", approved_on="2026-07-02",
                    months=tuple(f"2026-{m:02d}" for m in range(1, 7)), decree="2026/17")
        args.update(changes)
        return RevisionFacts(**args)

    def test_one_difference_per_month_and_revision_income(self):
        run = self.run_item(self.facts(), self.item(BillingType.PRICE_REVISION))
        self.assertEqual(run.unresolved, ())
        invoice = run.results[0].invoice
        self.assertEqual((invoice.net, len(invoice.lines)), (6000, 6))
        self.assertEqual({(x.amount, x.account, x.cost_center) for x in invoice.lines}, {(1000, "70520000", "CC-1100-SVC")})
        for month, line in zip(self.facts().months, invoice.lines):
            self.assertIn(month, line.description)

    def test_wrong_months_effects_approval_and_credit_are_blocked(self):
        for facts in (self.facts(months=("2026-01",)), self.facts(effective="2026-02-01"),
                      self.facts(approved_on="2026-06-30"), self.facts(new_fee=9000)):
            with self.subTest(facts=facts):
                self.assertEqual(len(self.run_item(facts, self.item(BillingType.PRICE_REVISION)).unresolved), 1)

    def test_months_already_revised_cannot_be_billed_again(self):
        self.tables["billing_history"] = [dict(contract="CV1", type="PRICE_REVISION", revision=dict(months=["2026-02"]))]
        self.assertEqual(len(self.run_item(self.facts(), self.item(BillingType.PRICE_REVISION)).unresolved), 1)


@unittest.skipUnless((REAL / "erp").is_dir(), "development source package unavailable")
class RevisionHistoryTests(HistoryCase):
    def test_original_revisions_reproduce_original_invoices(self):
        self.assert_history(BillingType.PRICE_REVISION)
