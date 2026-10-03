import unittest
from datetime import date
from decimal import Decimal

from kalmora.ledger import Ledger
from kalmora.money import RateTable
from kalmora.ic.positions import Directory, snapshot
from kalmora.ic.calculation import actual_360, monthly_interest


def entry(id, company, account, partner, amount, *, assignment=None, reference="DOC", currency="EUR", doc=None, source="TEST"):
    return {"id": id, "company": company, "currency": "MXN" if company == "3100" else "EUR",
            "posting_date": "2028-02-29", "document_date": "2028-02-29", "reference": reference, "source": source,
            "lines": [{"account": account, "debit": max(amount, 0), "credit": max(-amount, 0),
                       "partner": partner, "assignment": assignment, "currency": currency,
                       "amount_doc": abs(amount) if doc is None else doc}]}


class PositionsTests(unittest.TestCase):
    def setUp(self):
        self.directory = Directory([{"code": c, "currency": "MXN" if c == "3100" else "EUR"}
                                    for c in ("1000", "1100", "1200", "1910", "3100")],
                                   [{"id": "V-HOLDING", "intercompany": "1000"}],
                                   [{"id": "C-OTHER", "group": "1100"}])
        self.rates = RateTable([{"currency": "MXN", "date": "2028-02-28", "rate": Decimal("20.125")}])

    def snap(self, entries):
        return snapshot(Ledger.from_entries(entries), self.directory, self.rates,
                        accounts=["43300000", "40300000", "55200000", "24230000", "16330000", "55210000", "55220000"],
                        pairs=[("1000", "1100"), ("1000", "1200"), ("1000", "3100"), ("1100", "1910")],
                        as_of="2028-02-29")

    def test_four_dimensions_aliases_and_sources_are_not_collapsed(self):
        es = [entry("A", "1000", "43300000", "C-OTHER", 121, assignment="I1"),
              entry("B", "1100", "40300000", "V-HOLDING", -121, assignment="I1"),
              entry("C", "1100", "40300000", "1000", -7, assignment="I2"),
              entry("D", "1200", "40300000", "V-HOLDING", -121, assignment="I1")]
        original = Ledger.from_entries(es).entries
        result = self.snap(es)
        self.assertEqual(len(result["positions"]), 4)
        p = next(p for p in result["positions"] if p["company"] == "1100" and p["partner"] == "V-HOLDING")
        self.assertEqual(p["counterparty_company"], "1000")
        self.assertEqual(p["source_lines"][0]["book_line"], "B#1")
        self.assertEqual(result["comparisons"][0]["difference_cents"], 0)
        self.assertEqual(Ledger.from_entries(es).entries, original)
        self.assertIsNone(self.directory.resolve("V-IC1100"))  # no string guessing

    def test_principal_document_eur_and_local_only_fx_are_distinct(self):
        es = [entry("L", "1000", "24230000", "3100", 10000, reference="LOAN"),
              entry("B", "3100", "16330000", "1000", -201250, reference="LOAN", doc=10000),
              entry("FX", "3100", "16330000", "1000", -750, assignment="LOAN", currency="MXN", source="CLOSE_FX")]
        result = self.snap(es)
        self.assertEqual(result["comparisons"][0]["difference_cents"], 0)
        foreign = [p for p in result["positions"] if p["company"] == "3100"]
        self.assertEqual(sum(p["local_cents"] for p in foreign), -202000)
        self.assertEqual(sum(p["eur_cents"] for p in foreign), -10000)
        self.assertEqual(sum(p["valuation_local_cents"] for p in foreign), -750)

    def test_pooling_and_ute_have_separate_families_external_partner_excluded(self):
        result = self.snap([entry("P", "1000", "55200000", "1100", 250, reference="POOL"),
                            entry("Q", "1100", "55200000", "1000", -250, reference="POOL"),
                            entry("U", "1100", "55210000", "1910", 500, reference="UTE"),
                            entry("V", "1910", "55220000", "1100", -500, reference="UTE"),
                            entry("X", "1910", "55220000", "EXT", -500, reference="UTE")])
        self.assertEqual({c["family"] for c in result["comparisons"]}, {"current_account", "ute"})
        self.assertTrue(all(c["difference_cents"] == 0 for c in result["comparisons"]))
        self.assertEqual(len(result["excluded"]), 1)
        self.assertEqual(sum(p["local_cents"] for p in result["positions"]), 0)

    def test_no_future_entries(self):
        e = entry("X", "1000", "55200000", "1100", 123)
        e["posting_date"] = "2028-03-01"
        self.assertEqual(self.snap([e])["positions"], [])

    def test_fx_last_available_and_rounding(self):
        self.assertEqual(self.rates.convert_cents(3, "EUR", "MXN", "2028-02-29"), 60)
        self.assertEqual(self.rates.convert_cents(-3, "EUR", "MXN", "2028-02-29"), -60)
        with self.assertRaises(ValueError):
            self.rates.convert_cents(1, "EUR", "MXN", "2028-02-27")
        with self.assertRaises(TypeError):
            self.rates.convert_cents(True, "EUR", "MXN", "2028-02-29")


class InterestMathTests(unittest.TestCase):
    def test_leap_february_and_short_month(self):
        terms = {"basis": "act/360", "principal": 360000, "rate_bp": 600, "start": "2020-01-01"}
        for month, days in [("2028-02", 29), ("2027-02", 28), ("2028-04", 30), ("2028-12", 31)]:
            with self.subTest(month=month):
                calc = monthly_interest(terms, month)
                self.assertEqual(calc["days"], days)
                self.assertEqual(calc["rounded_cents"], days * 60)

    def test_midmonth_start_and_end(self):
        terms = {"basis": "act/360", "principal": 360000, "rate_bp": 600, "start": "2028-02-15",
                 "end_exclusive": "2028-02-20"}
        self.assertEqual(monthly_interest(terms, "2028-02")["rounded_cents"], 300)
        self.assertEqual(monthly_interest(terms, "2028-01")["rounded_cents"], 0)
        self.assertEqual(monthly_interest(terms, "2028-03")["rounded_cents"], 0)

    def test_half_cent_and_invalid_inputs(self):
        self.assertEqual(actual_360(180, 10000, date(2028, 1, 1), date(2028, 1, 2))["rounded_cents"], 1)
        for p in [True, 180.0]:
            with self.assertRaises(TypeError):
                actual_360(p, 10000, date(2028, 1, 1), date(2028, 1, 2))
        with self.assertRaises(ValueError):
            actual_360(180, 10000, date(2028, 1, 2), date(2028, 1, 1))


if __name__ == "__main__":
    unittest.main()


class SerializationContractTests(unittest.TestCase):
    def test_all_source_dimensions_survive_without_mutating_entry(self):
        from copy import deepcopy
        from kalmora.ic.context import delivery_lines
        entry = {"company": "3100", "lines": [{
            "account": "55200000", "debit": 0, "credit": 1943,
            "partner": "1000", "assignment": "INDEPENDENT-SYNTHETIC-REF",
            "tax_code": "EX", "currency": "EUR", "amount_doc": 101,
            "source_book_line": "original#2", "line": 2}]}
        before = deepcopy(entry)
        result = delivery_lines(entry)[0]
        for field in ("assignment", "tax_code", "currency", "amount_doc"):
            self.assertEqual(result[field], entry["lines"][0][field])
        self.assertNotIn("source_book_line", result)
        self.assertNotIn("line", result)
        self.assertEqual(entry, before)

    def test_absent_dimensions_not_fabricated(self):
        from kalmora.ic.context import delivery_lines
        entry = {"company": "1100", "lines": [{"account": "66210000", "debit": 17, "credit": 0}]}
        result = delivery_lines(entry)[0]
        for field in ("assignment", "tax_code", "currency", "amount_doc"):
            self.assertNotIn(field, result)
