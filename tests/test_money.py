import unittest
from decimal import Decimal
from kalmora.money import RateTable, integer, line_amount, quantity_milli, round_cents, company_local_currency


class MoneyTests(unittest.TestCase):
    def test_local_currency_rejects_unknown_company(self):
        for company in ('1000','1100','1200','1300','1910','2100'):
            self.assertEqual(company_local_currency(company),'EUR')
        self.assertEqual(company_local_currency('3100'),'MXN')
        for invalid in ('9999','1400',1100,['1100']):
            with self.assertRaises(ValueError):company_local_currency(invalid)

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
