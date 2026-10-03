import json
import os
from pathlib import Path
import unittest

from kalmora.ap_tax import TaxCatalog, TaxLine, calculate_ap_tax
from kalmora.ap_withholding import (
    ContractGuarantee, WithholdingBase, WithholdingCatalog,
    calculate_ap_withholdings, select_withholdings,
)
from kalmora.money import RateTable
from kalmora.validation import validate_entry
from test_ap_tax import source_catalog


def withholding_source():
    return {"withholdings": {c: {"rate": rate, "account": "47510000"} for c, rate in {
        "IRPF15": 1500, "IRPF7": 700, "IRPF19": 1900, "MXISR10": 1000,
        "MXIVAR": 1067, "MXFLETE": 400, "PTIRS25": 2500,
    }.items()}}


class APWithholdingTests(unittest.TestCase):
    def calculate(self, *bases, **overrides):
        kwargs = dict(company="1100", country="ES", vendor="V1", currency="EUR",
                      invoice_date="2026-07-31", invoice_number="INV-1", decision="POST",
                      bases=bases, catalog=WithholdingCatalog(withholding_source()))
        kwargs.update(overrides)
        return calculate_ap_withholdings(**kwargs)

    def test_all_seven_rates_from_catalogue(self):
        for code, row in withholding_source()["withholdings"].items():
            country = "MX" if code.startswith("MX") else "PT" if code.startswith("PT") else "ES"
            with self.subTest(code=code):
                result = self.calculate(WithholdingBase("L", 10005, (code,)), country=country,
                                        company={"ES": "1100", "PT": "2100", "MX": "3100"}[country],
                                        currency="MXN" if country == "MX" else "EUR")
                expected = (10005 * row["rate"] + 5000) // 10000
                self.assertEqual((result.withholding_doc, result.withholding_local), (expected, expected))
                line = result.components[0].journal_line
                self.assertEqual((line["account"], line["credit"], line["debit"], line["partner"], line["tax_code"]),
                                 ("47510000", expected, 0, "V1", code))

    def test_mexican_professional_two_components_and_exact_mxivar(self):
        result = self.calculate(WithholdingBase("L", 2485484, ("MXISR10", "MXIVAR")),
                                company="3100", country="MX", currency="MXN")
        self.assertEqual([c.amount_doc for c in result.components], [248548, 265201])
        self.assertEqual(result.withholding_doc, 513749)
        # Two thirds of rounded M16 VAT would produce 265118 instead.
        self.assertNotEqual(result.components[1].amount_doc, (397677 * 2 + 1) // 3)

    def test_document_order_vendor_and_confirmed_empty_selection(self):
        selected = select_withholdings(vendor="MXISR10+MXIVAR")
        self.assertEqual(selected.codes, ("MXISR10", "MXIVAR"))
        self.assertEqual(selected.source, "vendor")
        self.assertEqual(select_withholdings(document=("IRPF7",), vendor="IRPF15").source, "document")
        self.assertEqual(select_withholdings(order=("IRPF19",), vendor="IRPF15").codes, ("IRPF19",))
        self.assertEqual(select_withholdings(document=(), vendor="IRPF15").codes, ())
        self.assertEqual(select_withholdings(vendor=None).codes, ())
        with self.assertRaises(ValueError):
            select_withholdings()
        for vendor in ("", "IRPF15+", "IRPF15+IRPF15", "IRPF15+IRPF7"):
            with self.assertRaises(ValueError):
                select_withholdings(vendor=vendor)

    def test_contract_guarantee_on_base_not_gross_and_partner_assignment(self):
        result = self.calculate(WithholdingBase("L", 10000, ()),
                                guarantee=ContractGuarantee(10000, "CONTRACT-1"))
        self.assertEqual((result.retention_doc, result.deduction_local), (500, 500))
        item = result.components[0]
        self.assertEqual(item.kind, "GUARANTEE")
        self.assertEqual(item.contract_reference, "CONTRACT-1")
        self.assertEqual(item.journal_line["account"], "40000900")
        self.assertEqual(item.journal_line["partner"], "V1")
        self.assertEqual(item.journal_line["assignment"], "INV-1")
        self.assertIsNone(item.journal_line["cost_center"])
        self.assertEqual(self.calculate(WithholdingBase("L", 10000, ())).retention_doc, 0)

    def test_rounding_per_base_and_invoice_date_fx(self):
        result = self.calculate(WithholdingBase("1", 10, ("IRPF15",)),
                                WithholdingBase("2", 10, ("IRPF15",)),
                                currency="USD", rates=RateTable([
                                    {"currency": "USD", "date": "2026-07-30", "rate": "1.2"}]))
        self.assertEqual([c.amount_doc for c in result.components], [2, 2])
        self.assertEqual((result.withholding_doc, result.withholding_local), (4, 4))
        self.assertEqual(result.components[0].journal_line["currency"], "USD")
        self.assertEqual(result.components[0].journal_line["amount_doc"], 2)

    def test_notary_disbursements_do_not_increase_professional_irpf_base(self):
        result = self.calculate(WithholdingBase("honorarios", 204698, ("IRPF15",)),
                                WithholdingBase("suplidos", 13523, ()))
        self.assertEqual(result.withholding_doc, 30705)
        self.assertNotEqual(result.withholding_doc, (218221 * 1500 + 5000) // 10000)
        self.assertEqual([c.line_id for c in result.components], ["honorarios"])

    def test_full_tax_withholding_guarantee_composition_and_reversal(self):
        for company, country, currency, tax_code, codes in [
            ("1100", "ES", "EUR", "S21", ("IRPF15",)),
            ("1100", "ES", "EUR", "SISP", ()),
            ("2100", "PT", "EUR", "P23", ("PTIRS25",)),
            ("3100", "MX", "MXN", "M16", ("MXISR10", "MXIVAR")),
            ("3100", "MX", "MXN", "M16", ("MXFLETE",)),
        ]:
            with self.subTest(country=country, codes=codes):
                tax = calculate_ap_tax(company=company, country=country, currency=currency,
                                       invoice_date="2026-07-31", decision="POST",
                                       lines=[TaxLine("L", 10005, tax_code)], catalog=TaxCatalog(source_catalog()))
                retention = self.calculate(WithholdingBase("L", 10005, codes), company=company,
                                           country=country, currency=currency,
                                           guarantee=ContractGuarantee(10005, "CONTRACT-1"))
                lines = [{"account": "62300000", "debit": tax.net_local, "credit": 0, "cost_center": "CC"},
                         *tax.components[0].journal_lines, *[c.journal_line for c in retention.components]]
                supplier = sum(l["debit"] - l["credit"] for l in lines)
                lines.append({"account": "41000000", "debit": 0, "credit": supplier, "partner": "V1"})
                self.assertEqual(supplier, tax.gross_doc - retention.deduction_doc)
                self.assertEqual(validate_entry({"company": company, "lines": lines}), [])
                reversed_lines = [{**l, "debit": l["credit"], "credit": l["debit"]} for l in lines]
                self.assertEqual(validate_entry({"company": company, "lines": reversed_lines}), [])

    def test_no_retention_or_zero_base_emits_no_empty_lines(self):
        self.assertEqual(self.calculate().components, ())
        self.assertEqual(self.calculate(WithholdingBase("L", 0, ("IRPF15",)),
                                        guarantee=ContractGuarantee(0, "CONTRACT-1")).components, ())
        self.assertEqual(self.calculate(WithholdingBase("L", 10000, ("IRPF7",)),
                                        decision="POST_PAYMENT_BLOCK").withholding_doc, 700)

    def test_invalid_or_unresolved_input(self):
        good = WithholdingBase("L", 10000, ("IRPF15",))
        for kwargs in ({"country": "MX"}, {"decision": "HOLD"}, {"decision": "REJECT"},
                       {"vendor": ""}, {"invoice_number": ""}, {"currency": "USD"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.calculate(good, **kwargs)
        for base in [WithholdingBase("", 100, ("IRPF15",)), WithholdingBase("L", -1, ("IRPF15",)),
                     WithholdingBase("L", 100, ("UNKNOWN",)), WithholdingBase("L", 100, ("PTIRS25",)),
                     WithholdingBase("L", 100, ("IRPF15", "IRPF15")),
                     WithholdingBase("L", 100, ("IRPF15", "IRPF19"))]:
            with self.subTest(base=base), self.assertRaises(ValueError):
                self.calculate(base)
        for guarantee in (ContractGuarantee(100, ""), ContractGuarantee(-100, "C"), ContractGuarantee(100, "C", 600)):
            with self.assertRaises(ValueError):
                self.calculate(good, guarantee=guarantee)
        with self.assertRaises(ValueError):
            self.calculate(good, good)
        with self.assertRaises(TypeError):
            self.calculate(WithholdingBase("L", True, ("IRPF15",)))
        with self.assertRaises(TypeError):
            select_withholdings(document=["IRPF15"])

    @unittest.skipUnless(os.environ.get("KALMORA_PHASE_ERP"), "original ERP not configured")
    def test_all_167_original_withholding_quotas(self):
        erp = Path(os.environ["KALMORA_PHASE_ERP"])
        catalog = WithholdingCatalog(json.loads((erp / "tax_codes.json").read_text()))
        counts = {}
        for text in (erp / "journal_entries.jsonl").read_text().splitlines():
            entry = json.loads(text)
            recorded = [l for l in entry["lines"] if l["account"] == "47510000" and l.get("tax_code")]
            if not recorded:
                continue
            # Observed taxable expense lines are explicit separate bases;
            # SEX disbursements (e.g. notary fees) are not professional income.
            base = sum(l["debit"] - l["credit"] for l in entry["lines"]
                       if l["account"][0] in "26" and l.get("tax_code") in {"S21", "P23", "M16"})
            self.assertNotEqual(base, 0, entry["id"])
            for line in recorded:
                code = line["tax_code"]
                country = "MX" if code.startswith("MX") else "PT" if code.startswith("PT") else "ES"
                result = self.calculate(WithholdingBase("taxable", abs(base), (code,)), catalog=catalog,
                                        company=entry["company"], country=country,
                                        currency="MXN" if country == "MX" else "EUR",
                                        invoice_date=entry["document_date"], invoice_number=entry["reference"])
                expected = result.withholding_doc * (1 if base > 0 else -1)
                self.assertEqual(expected, line["credit"] - line["debit"], entry["id"])
                counts[code] = counts.get(code, 0) + 1
        self.assertEqual(counts, {"IRPF19": 64, "MXFLETE": 27, "IRPF15": 23,
                                  "MXISR10": 15, "MXIVAR": 15, "IRPF7": 12, "PTIRS25": 11})

    @unittest.skipUnless(os.environ.get("KALMORA_PHASE_ERP"), "original ERP not configured")
    def test_all_original_mxivar_entries_disambiguate_catalogue_rounding(self):
        erp = Path(os.environ["KALMORA_PHASE_ERP"])
        catalog = WithholdingCatalog(json.loads((erp / "tax_codes.json").read_text()))
        count = 0
        for text in (erp / "journal_entries.jsonl").read_text().splitlines():
            entry = json.loads(text)
            mxivar = [l for l in entry["lines"] if l.get("tax_code") == "MXIVAR"]
            if not mxivar:
                continue
            base = sum(l["debit"] - l["credit"] for l in entry["lines"]
                       if l.get("tax_code") == "M16" and l["account"] != "47200000")
            result = self.calculate(WithholdingBase("L", base, ("MXISR10", "MXIVAR")),
                                    catalog=catalog, company="3100", country="MX", currency="MXN",
                                    invoice_date=entry["document_date"], invoice_number=entry["reference"])
            actual = next(c.amount_doc for c in result.components if c.code == "MXIVAR")
            self.assertEqual(actual, sum(l["credit"] - l["debit"] for l in mxivar), entry["id"])
            vat = sum(l["debit"] for l in entry["lines"] if l["account"] == "47200000")
            self.assertNotEqual(actual, (2 * vat + 1) // 3, entry["id"])
            count += 1
        self.assertEqual(count, 15)


if __name__ == "__main__":
    unittest.main()
