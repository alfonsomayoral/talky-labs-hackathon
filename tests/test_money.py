import unittest
from decimal import Decimal
from kalmora.money import RateTable, integer, line_amount, quantity_milli, round_cents


class MoneyTests(unittest.TestCase):
    def test_exact_and_rounding(self):
        for bad in (True, 1.0, "1"):
            with self.assertRaises(TypeError): integer(bad)
        self.assertEqual(quantity_milli("1.234"), 1234)
        with self.assertRaises(ValueError): quantity_milli("1.2345")
        self.assertEqual(round_cents("-1.5"), -2)
        self.assertEqual(line_amount(1005, 100), 101)
        self.assertEqual(line_amount(1005, 100, truncate=True), 100)

    def test_rates_and_cross_conversion(self):
        rates = RateTable([{"date": "2026-07-01", "currency": "USD", "rate": "1.25"}, {"date": "2026-07-01", "currency": "MXN", "rate": Decimal(20)}, {"date": "2026-07-03", "currency": "USD", "rate": "1.5"}])
        self.assertEqual(rates.as_of("2026-07-02", "USD"), Decimal("1.25"))
        self.assertEqual(rates.to_local(125, "USD", "3100", "2026-07-02"), 2000)
        self.assertEqual(rates.to_local(125, "USD", "1100", "2026-07-02"), 100)
        with self.assertRaises(ValueError): rates.as_of("2026-06-30", "USD")
        with self.assertRaises(ValueError): rates.as_of("2026-07-02", "GBP")
        with self.assertRaises(TypeError): RateTable([{"date":"2026-07-01","currency":"USD","rate":1.2}])
