from copy import deepcopy
import unittest
from kalmora.billing import BillingType, build_ar_billing
from kalmora.billing.compute import invoice_amounts
from kalmora.billing.inputs import ServiceFacts
from kalmora.data import PhaseData
from billing_support import BillingCase, HistoryCase, REAL


class AmountTests(unittest.TestCase):
    def test_country_rates_and_reverse_charge(self):
        for code, rate, tax in (("R21", 2100, 2100), ("R10", 1000, 1000), ("RISP", 0, 0),
                                ("PR06", 600, 600), ("PR23", 2300, 2300), ("PRAUT", 0, 0), ("MR16", 1600, 1600)):
            with self.subTest(code=code):
                a = invoice_amounts(net=10000, tax_rate_bp=rate)
                self.assertEqual((a.tax, a.gross, a.payable), (tax, 10000 + tax, 10000 + tax))

    def test_guarantee_levy_and_capped_advance_have_distinct_bases(self):
        a = invoice_amounts(net=10000, tax_rate_bp=1600, retention_bp=500, mx_levy=True,
                            advance_bp=3000, advance_available=99999)
        self.assertEqual((a.tax, a.retention, a.levy, a.advance, a.payable), (1600, 500, 50, 3480, 7570))
        b = invoice_amounts(net=10000, tax_rate_bp=1600, mx_levy=True, advance_bp=3000, advance_available=200)
        self.assertEqual((b.advance, b.payable), (200, 11350))


class AdvanceStateTests(BillingCase):
    def test_pr23_is_exercised_through_portuguese_contract(self):
        self.tables["companies"] = [{"code": "2100", "country": "PT"}]
        self.tables["tax_codes"] = {"tax_codes": {"PR23": {"kind": "output", "country": "PT", "rate": 2300}}}
        self.tables["customers"][0].update(country="PT", kind="private")
        self.tables["sales_contracts"][0].update(company="2100", tax="PR23")
        self.tables["cost_centers"][0]["company"] = "2100"
        run = self.run_item(ServiceFacts("2026-07", 10000), self.item(BillingType.SERVICE_MONTHLY, company="2100"))
        self.assertEqual(run.unresolved, ())
        self.assertEqual((run.results[0].invoice.tax_code, run.results[0].invoice.tax), ("PR23", 2300))

    def test_rejected_invoice_does_not_consume_available_advance(self):
        bad = self.tables["sales_contracts"][0]
        bad.update(id="A", cc="UNKNOWN", advance_bp=3000)
        good = deepcopy(bad)
        good.update(id="Z", cc="CC-1100-SVC")
        self.tables["sales_contracts"].append(good)
        self.tables["ar_invoices"] = [dict(id="ADV1", contract="OTHER", company="1100", customer="C1",
                                         kind="advance", date="2026-01-01", gross=1000, deductions=[])]
        items = [self.item(BillingType.SERVICE_MONTHLY, "BAD", contract="A"),
                 self.item(BillingType.SERVICE_MONTHLY, "GOOD", contract="Z")]
        run = build_ar_billing(self.data(), items, {i.id: ServiceFacts("2026-07", 10000) for i in items})
        self.assertEqual([u.item.id for u in run.unresolved], ["BAD"])
        self.assertEqual(run.results[0].invoice.deductions[0].amount, 1000)


@unittest.skipUnless((REAL / "erp").is_dir(), "development source package unavailable")
class AmountHistoryTests(HistoryCase):
    def test_all_types_reproduce_historical_taxes_and_deductions(self):
        for kind in BillingType:
            with self.subTest(kind=kind):
                self.assert_history(kind)
        data = PhaseData(REAL)
        self.assertEqual({r["tax_code"] for r in data.table("ar_invoices")},
                         {"R21", "R10", "RISP", "PR06", "PRAUT", "MR16"})
