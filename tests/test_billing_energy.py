from decimal import Decimal
import unittest
from kalmora.billing import BillingType
from kalmora.billing.compute import ppa_net
from kalmora.billing.inputs import PlantMwh, PlantSettlement, PpaFacts, SettlementFacts
from billing_support import BillingCase, HistoryCase, REAL


class EnergyTests(BillingCase):
    def setUp(self):
        super().setUp()
        self.tables["sales_contracts"][0].update(plants=["CC-1100-SVC"], share_bp=7000, price_mwh="4150.00")

    def test_ppa_truncates_energy_then_cents_without_float(self):
        self.assertEqual(ppa_net(mwh_milli=(8652582, 5783133), share_bp=7000,
                                 price_mwh_cents=Decimal("4150.00")), 41935750)
        self.assertEqual(ppa_net(mwh_milli=(1001,), share_bp=7000, price_mwh_cents=Decimal("1.99")), 1)

    def test_period_price_share_and_plants_are_cross_checked(self):
        base = dict(period="2026-06", plants=(PlantMwh("CC-1100-SVC", 1001),), share_bp=7000, price_mwh_cents=Decimal("4150.00"))
        self.assertEqual(self.run_item(PpaFacts(**base), self.item(BillingType.PPA)).unresolved, ())
        for changes in (dict(period="2026-05"), dict(share_bp=6000), dict(price_mwh_cents=Decimal("4000")),
                        dict(plants=(PlantMwh("UNKNOWN", 1001),)),
                        dict(plants=(PlantMwh("CC-1100-SVC", 1001), PlantMwh("CC-1100-SVC", 1001)))):
            with self.subTest(changes=changes):
                self.assertEqual(len(self.run_item(PpaFacts(**(base | changes)), self.item(BillingType.PPA)).unresolved), 1)

    def test_market_keeps_plant_income_and_signed_deviations_only(self):
        facts = SettlementFacts("2026-06", (PlantSettlement("CC-1100-SVC", 10000),), -250)
        run = self.run_item(facts, self.item(BillingType.MARKET_SETTLEMENT))
        self.assertEqual(run.unresolved, ())
        invoice = run.results[0].invoice
        self.assertEqual(invoice.net, 9750)
        self.assertEqual([(x.amount, x.account, x.cost_center) for x in invoice.lines],
                         [(10000, "70530000", "CC-1100-SVC"), (-250, "70530000", "CC-1100-ADM")])
        self.assertFalse(any(x["account"] == "62300000" for x in run.results[0].journal_entry["lines"]))


@unittest.skipUnless((REAL / "erp").is_dir(), "development source package unavailable")
class EnergyHistoryTests(HistoryCase):
    def test_original_ppa_reproduces_original_invoices(self):
        self.assert_history(BillingType.PPA)

    def test_original_market_reproduces_original_invoices(self):
        self.assert_history(BillingType.MARKET_SETTLEMENT)
