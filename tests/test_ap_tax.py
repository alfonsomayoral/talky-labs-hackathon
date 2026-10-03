import json
import os
from pathlib import Path
import unittest

from kalmora.ap_tax import TaxCatalog, TaxLine, calculate_ap_tax, select_tax_code
from kalmora.money import RateTable
from kalmora.validation import validate_entry


def source_catalog():
    groups = {
        ("ES", "input"): {"S21": 2100, "S10": 1000, "S04": 400},
        ("ES", "reverse"): {"SISP": 2100, "SIC": 2100, "SIS": 2100},
        ("ES", "exempt"): {"SEX": 0, "SREAV": 0},
        ("ES", "nondeductible"): {"SND": 2100},
        ("ES", "import"): {"SIMP": 2100},
        ("PT", "input"): {"P23": 2300, "P13": 1300, "P06": 600},
        ("PT", "reverse"): {"PAUT": 2300, "PSIS": 2300},
        ("MX", "input"): {"M16": 1600},
        ("MX", "exempt"): {"M00": 0},
        ("ES", "output"): {"R21": 2100},
    }
    return {"tax_codes": {code: {"country": country, "kind": kind, "rate": rate}
                          for (country, kind), codes in groups.items() for code, rate in codes.items()}}


class APTaxTests(unittest.TestCase):
    def calculate(self, *lines, **overrides):
        kwargs = dict(company="1100", country="ES", currency="EUR", invoice_date="2026-07-31",
                      decision="POST", lines=lines, catalog=TaxCatalog(source_catalog()))
        kwargs.update(overrides)
        return calculate_ap_tax(**kwargs)

    def test_every_catalogue_ap_code_and_country(self):
        source = source_catalog()
        for code, row in source["tax_codes"].items():
            if row["kind"] == "output":
                continue
            with self.subTest(code=code):
                country = row["country"]
                kwargs = dict(company={"ES": "1100", "PT": "2100", "MX": "3100"}[country],
                              country=country, currency="MXN" if country == "MX" else "EUR")
                line = TaxLine("L", 0 if code == "SIMP" else 10005, code,
                               account="62900000", cost_center="CC-1100-ADM",
                               tax_doc=98765 if code == "SIMP" else None,
                               dua_reference="DUA-1" if code == "SIMP" else None)
                result = self.calculate(line, **kwargs)
                expected_tax = 98765 if code == "SIMP" else (10005 * row["rate"] + 5000) // 10000
                expected_charged = 0 if row["kind"] in {"exempt", "reverse"} else expected_tax
                self.assertEqual(result.tax_doc, expected_charged)
                self.assertEqual(result.gross_doc, line.base_doc + expected_charged)
                postings = result.components[0].journal_lines
                accounts = [p["account"] for p in postings]
                expected = (["47210000", "47710000"] if row["kind"] == "reverse" else
                            ["62900000"] if row["kind"] == "nondeductible" else
                            [] if row["kind"] == "exempt" else ["47200000"])
                self.assertEqual(accounts, expected)
                self.assertEqual(result.tax_local, expected_tax)

    def test_precedence_and_missing_treatment(self):
        self.assertEqual(select_tax_code(document="S10", order="S04", vendor="S21").source, "document")
        self.assertEqual(select_tax_code(order="S04", vendor="S21").code, "S04")
        self.assertEqual(select_tax_code(vendor="S21").source, "vendor")
        for kwargs in ({}, {"document": "", "vendor": "S21"}):
            with self.assertRaises(ValueError):
                select_tax_code(**kwargs)

    def test_mixed_bases_and_rounding_per_component(self):
        result = self.calculate(TaxLine("1", 5, "S10"), TaxLine("2", 5, "S10"),
                                TaxLine("3", 10000, "SISP"), TaxLine("4", 100, "SEX"))
        self.assertEqual((result.net_doc, result.tax_doc, result.gross_doc), (10110, 2, 10112))
        self.assertEqual(result.tax_local, 2102)

    def test_foreign_currency_rounding_each_posting_and_fallback_rate(self):
        rates = RateTable([{"date": "2026-07-30", "currency": "USD", "rate": "1.2"}])
        result = self.calculate(TaxLine("1", 101, "S21"), currency="USD", rates=rates)
        item = result.components[0]
        self.assertEqual((item.base_local, item.tax_doc, item.tax_local), (84, 21, 18))
        self.assertEqual(item.journal_lines[0]["amount_doc"], 21)
        self.assertEqual(item.journal_lines[0]["currency"], "USD")
        # The supplier balances the individually converted posting components.
        entry = {"company": "1100", "lines": [
            {"account": "62900000", "debit": item.base_local, "credit": 0, "cost_center": "CC"},
            *item.journal_lines,
            {"account": "41000000", "debit": 0, "credit": 102, "partner": "V1"}]}
        self.assertEqual(validate_entry(entry), [])

    def test_non_deductible_preserves_asset_or_expense_allocation(self):
        result = self.calculate(TaxLine("1", 10000, "SND", account="21300000", wbs="OB-1"))
        line = result.components[0].journal_lines[0]
        self.assertEqual((line["account"], line["debit"], line["wbs"], line["partner"]),
                         ("21300000", 2100, "OB-1", None))
        self.assertNotIn("47200000", [p["account"] for p in result.components[0].journal_lines])

    def test_import_uses_dua_quota_not_freight_base(self):
        result = self.calculate(TaxLine("freight", 442500, "SEX"),
                                TaxLine("customs", 567460, "SEX"),
                                TaxLine("dua", 0, "SIMP", tax_doc=4532744, dua_reference="25ES888199362719"))
        self.assertEqual((result.net_doc, result.tax_doc, result.gross_doc), (1009960, 4532744, 5542704))
        self.assertEqual(result.components[-1].journal_lines[0]["assignment"], "25ES888199362719")

    def test_invalid_inputs_never_generate_postings(self):
        good = TaxLine("1", 10000, "S21")
        for override in ({"decision": "HOLD"}, {"decision": "REJECT"}, {"country": "MX"},
                         {"currency": "USD"}, {"company": "9999"}, {"invoice_date": "20260731"}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.calculate(good, **override)
        for line in [TaxLine("1", 100, "R21"), TaxLine("1", 100, "UNKNOWN"),
                     TaxLine("1", -1, "S21"), TaxLine("1", 100, "S21", tax_doc=22),
                     TaxLine("1", 100, "SISP", tax_doc=21), TaxLine("1", 100, "SIMP", tax_doc=21),
                     TaxLine("1", 0, "SIMP", tax_doc=21), TaxLine("1", 100, "SND"),
                     TaxLine("1", 100, "SND", account="62900000", cost_center="CC", wbs="OB")]:
            with self.subTest(line=line), self.assertRaises(ValueError):
                self.calculate(line)
        with self.assertRaises(ValueError):
            self.calculate(good, good)
        with self.assertRaises(ValueError):
            self.calculate()
        for value in (True, 1.0):
            with self.assertRaises(TypeError):
                self.calculate(TaxLine("1", value, "S21"))

    def test_payment_block_is_postable(self):
        result = self.calculate(TaxLine("1", 10000, "S21"), decision="POST_PAYMENT_BLOCK")
        self.assertEqual(result.tax_doc, 2100)

    @unittest.skipUnless(os.environ.get("KALMORA_PHASE_ERP"), "original ERP not configured")
    def test_original_package_catalogue_and_dua_evidence(self):
        erp = Path(os.environ["KALMORA_PHASE_ERP"])
        catalog = TaxCatalog(json.loads((erp / "tax_codes.json").read_text()))
        result = self.calculate(TaxLine("dua", 0, "SIMP", tax_doc=4532744,
                                       dua_reference="25ES888199362719"), catalog=catalog)
        entries = [json.loads(s) for s in (erp / "journal_entries.jsonl").read_text().splitlines()]
        original = next(e for e in entries if e["id"] == "1100-2025-5100000441")
        dua = next(l for l in original["lines"] if l["tax_code"] == "SIMP")
        self.assertEqual(result.components[0].journal_lines[0]["debit"], dua["debit"])


if __name__ == "__main__":
    unittest.main()
