from dataclasses import replace
from decimal import Decimal
import unittest

from kalmora.energy import (EnergyScope, PlantMeasurement, PlantSettlement,
                            calculate_market, calculate_ppa)


class EnergyTests(unittest.TestCase):
    def setUp(self):
        self.scope = EnergyScope("1300", "EUR", "PPA1", "2026-06")

    def ppa(self, qty, **kwargs):
        params = dict(scope=self.scope, measurements=[PlantMeasurement(self.scope, "P1", qty)],
                      share_bp=7000, price_mwh_cents=4150)
        params.update(kwargs)
        return calculate_ppa(**params)

    def test_ppa_independent_exact_arithmetic(self):
        # 1.234 MWh × 70% × 41.50 EUR = 35.8477 EUR -> 3584 cents.
        self.assertEqual(self.ppa(1234).net_cents, 3584)
        self.assertEqual(self.ppa(0).net_cents, 0)
        self.assertEqual(self.ppa(1000, share_bp=0).net_cents, 0)
        self.assertEqual(self.ppa(1000, share_bp=10000).net_cents, 4150)

    def test_cent_truncation_boundaries_and_plant_isolation(self):
        # 0.010 MWh × 1.00 EUR = 1 cent. A fraction just below is zero.
        self.assertEqual(self.ppa(9, share_bp=10000, price_mwh_cents=100).net_cents, 0)
        self.assertEqual(self.ppa(10, share_bp=10000, price_mwh_cents=100).net_cents, 1)
        self.assertEqual(self.ppa(19, share_bp=10000, price_mwh_cents=100).net_cents, 1)
        rows = [PlantMeasurement(self.scope, "P2", 9), PlantMeasurement(self.scope, "P1", 9)]
        result = self.ppa(0, measurements=rows, share_bp=10000, price_mwh_cents=100)
        self.assertEqual(result.net_cents, 0)  # Do not truncate the combined 1.8 cents.
        self.assertEqual([l.plant for l in result.lines], ["P1", "P2"])
        self.assertEqual(result, self.ppa(0, measurements=reversed(rows), share_bp=10000, price_mwh_cents=100))
        self.assertEqual(self.ppa(1000, share_bp=10000, price_mwh_cents=Decimal("100.999")).net_cents, 100)

    def test_market_conservation_and_no_representative_double_cost(self):
        rows = [PlantSettlement(self.scope, "P1", 10000, 250, 300),
                PlantSettlement(self.scope, "P2", 8000, 100, 400)]
        result = calculate_market(scope=self.scope, settlements=rows)
        self.assertEqual([l.amount_cents for l in result.lines], [9750, 7900])
        self.assertEqual(result.net_cents, 17650)
        self.assertEqual(sum(l.excluded_representative_fee_cents for l in result.lines), 700)
        without_fees = calculate_market(scope=self.scope,
            settlements=[replace(r, representative_fee_cents=0) for r in rows])
        self.assertEqual(result.net_cents, without_fees.net_cents)
        self.assertEqual(sum(l.gross_cents - l.deviation_cost_cents for l in result.lines), result.net_cents)

    def test_deviation_cost_can_exceed_settlement(self):
        result = calculate_market(scope=self.scope,
            settlements=[PlantSettlement(self.scope, "P1", 10, 20)])
        self.assertEqual(result.net_cents, -10)

    def test_cross_scope_and_duplicate_plant_rejected(self):
        for field, value in (("company", "1100"), ("currency", "USD"),
                             ("contract", "PPA2"), ("period", "2026-07")):
            other = replace(self.scope, **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.ppa(0, measurements=[PlantMeasurement(other, "P1", 1)])
            with self.assertRaises(ValueError):
                calculate_market(scope=self.scope, settlements=[PlantSettlement(other, "P1", 1, 0)])
        with self.assertRaises(ValueError):
            self.ppa(0, measurements=[PlantMeasurement(self.scope, "P1", 1)] * 2)
        with self.assertRaises(ValueError):
            calculate_market(scope=self.scope, settlements=[PlantSettlement(self.scope, "P1", 1, 0)] * 2)

    def test_invalid_numbers_and_unresolved_inputs(self):
        for qty in (-1, 1.0, True, "1"):
            with self.assertRaises((TypeError, ValueError)):
                self.ppa(qty)
        for share in (-1, 10001, True, 7000.0):
            with self.assertRaises((TypeError, ValueError)):
                self.ppa(1000, share_bp=share)
        for price in (-1, 41.50, True, "NaN"):
            with self.assertRaises((TypeError, ValueError)):
                self.ppa(1000, price_mwh_cents=price)
        with self.assertRaises(ValueError):
            self.ppa(0, measurements=[])
        with self.assertRaises(ValueError):
            calculate_market(scope=self.scope, settlements=[PlantSettlement(self.scope, "P1", 100, -1)])


if __name__ == "__main__":
    unittest.main()
