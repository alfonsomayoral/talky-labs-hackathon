"""Catalogue treatment audit from original ERP, never golden answers."""
import os
from pathlib import Path
import unittest

from kalmora.ap_tax import TaxCatalog, TaxLine, calculate_ap_tax
from kalmora.data import PhaseData
from kalmora.money import RateTable


@unittest.skipUnless(os.environ.get("KALMORA_PHASE_ERP"), "original ERP not configured")
class APTaxHistoryTests(unittest.TestCase):
    def test_each_observed_ap_treatment_matches_original_fiscal_postings(self):
        data = PhaseData(Path(os.environ["KALMORA_PHASE_ERP"]).parent)
        source = data.table("tax_codes")
        catalog = TaxCatalog(source)
        ap_codes = {code for code, row in source["tax_codes"].items()
                    if row["kind"] in {"input", "reverse", "exempt", "nondeductible", "import"}}
        countries = {row["code"]: row["country"] for row in data.companies}
        invoices = {row["journal_entry"]: row for row in data.table("ap_invoices")
                    if row.get("journal_entry")}
        rates = RateTable(data.table("fx_rates"))
        observed, verified = set(), set()
        for entry in data.iter_journal():
            if entry.get("source") != "AP" or entry.get("doc_type") != "KR":
                continue
            codes = {line.get("tax_code") for line in entry["lines"]} & ap_codes
            observed.update(codes)
            invoice = invoices.get(entry["id"])
            if invoice is None:
                continue
            for code in sorted(codes - verified):
                treatment = catalog.get(code, countries[entry["company"]])
                if treatment.kind != "import" and codes != {code}:
                    continue  # A summary net cannot establish mixed taxable bases.
                original = [line for line in entry["lines"]
                            if line.get("tax_code") == code and line["account"].startswith(("472", "477"))]
                quota = sum(line["amount_doc"] for line in original if line["account"] == "47200000")
                if treatment.kind == "import":
                    # ERP's summary net includes customs disbursements in this
                    # case; only the observed DUA quota is its fiscal input.
                    reference = next(line["text"] for line in original if "DUA" in line.get("text", ""))
                    item = TaxLine("DUA", 0, code, tax_doc=quota, dua_reference=reference)
                else:
                    item = TaxLine("BASE", invoice["net"], code)
                with self.subTest(code=code, entry=entry["id"]):
                    result = calculate_ap_tax(company=entry["company"], country=countries[entry["company"]],
                        vendor=invoice["vendor"], invoice_id=invoice["doc_id"],
                        currency=invoice["currency"], invoice_date=invoice["issue_date"],
                        decision=invoice["decision"], lines=[item], catalog=catalog, rates=rates)
                    fields = ("account", "partner", "cost_center", "wbs", "currency", "amount_doc", "debit", "credit", "tax_code")
                    signature = lambda lines: [tuple(line.get(field) for field in fields) for line in lines]
                    self.assertEqual(signature(result.components[0].journal_lines), signature(original))
                    if treatment.kind != "import":
                        self.assertEqual(result.tax_doc, invoice["tax"])
                        self.assertEqual(result.gross_doc, invoice["gross"])
                verified.add(code)
        self.assertTrue(observed)
        self.assertEqual(verified, observed, "Every observed treatment needs source-justified fiscal bases")


if __name__ == "__main__":
    unittest.main()
