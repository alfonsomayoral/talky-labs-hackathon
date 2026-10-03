from dataclasses import replace
import unittest

from kalmora.ap_allocation import (
    InvoiceQuantityLine, OrderKey, OrderLine, OrderPortion, Receipt, allocate_receipts,
)
from kalmora.ap_valuation import CostAssignment, OrderPrice, ValuationLine, value_ap_lines
from kalmora.money import RateTable
from kalmora.validation import validate_entry


class ValuationTests(unittest.TestCase):
    def setUp(self):
        self.key = OrderKey("1100", "V1", "EUR", "PO1", 10)
        self.cost = CostAssignment("1100", "60700000", wbs="WBS1")

    def allocation(self, qty, receipts=None):
        return allocate_receipts(company="1100", vendor="V1", currency="EUR", invoice_id="I1",
            lines=[InvoiceQuantityLine("L1", qty, "ud", (OrderPortion(self.key, qty),))],
            orders=[OrderLine(self.key, "ud")],
            receipts=receipts or [Receipt("R1", self.key, qty, "ud", "2026-07-01")])

    def value(self, lines, **kwargs):
        params = dict(company="1100", vendor="V1", currency="EUR", invoice_id="I1",
                      invoice_date="2026-07-31", decision="POST", lines=lines,
                      gr_ir_account="40090000")
        params.update(kwargs)
        return value_ap_lines(**params)

    def assert_net_entry(self, result):
        # Compose only the net fixture. Taxes/final supplier settlement are external.
        components = [dict(account=c.account, debit=max(c.amount_local, 0),
                           credit=max(-c.amount_local, 0), partner=c.partner,
                           cost_center=c.cost_center, wbs=c.wbs) for c in result.components]
        components.append(dict(account="40000000", partner="V1", debit=0, credit=result.net_local))
        self.assertEqual(validate_entry(dict(company=result.company, lines=components)), [])
        self.assertEqual(sum(c.amount_doc for c in result.components), result.net_doc)

    def test_gr_ir_variance_and_cost_object(self):
        result = self.value([ValuationLine("L1", 103, self.cost, 1005)],
                            prices=[OrderPrice(self.key, 100)], allocation=self.allocation(1005))
        gr, variance = result.components
        self.assertEqual((gr.account, gr.partner, gr.amount_doc, gr.wbs), ("40090000", "V1", 101, None))
        self.assertEqual((variance.account, variance.partner, variance.amount_doc, variance.wbs),
                         ("60700000", None, 2, "WBS1"))
        self.assert_net_entry(result)

    def test_receipt_fragmentation_does_not_change_rounding(self):
        receipts = [Receipt("A", self.key, 5, "ud", "2026-07-01"),
                    Receipt("B", self.key, 5, "ud", "2026-07-02")]
        fragmented = self.value([ValuationLine("L1", 1, self.cost, 10)],
            prices=[OrderPrice(self.key, 100)], allocation=self.allocation(10, receipts))
        whole = self.value([ValuationLine("L1", 1, self.cost, 10)],
            prices=[OrderPrice(self.key, 100)], allocation=self.allocation(10))
        self.assertEqual(fragmented, whole)
        self.assertEqual(fragmented.components[0].amount_doc, 1)

    def test_favorable_variance_and_direct_asset_or_expense(self):
        lines = [ValuationLine("L1", 98, self.cost, 1000),
                 ValuationLine("L2", 200, CostAssignment("1100", "21300000", cost_center="CC1")),
                 ValuationLine("L3", 300, CostAssignment("1100", "62900000", cost_center="CC2"))]
        result = self.value(lines, allocation=self.allocation(1000), prices=[OrderPrice(self.key, 100)])
        self.assertEqual([c.amount_doc for c in result.components], [100, -2, 200, 300])
        self.assertEqual([c.cost_center for c in result.components[-2:]], ["CC1", "CC2"])
        self.assert_net_entry(result)

    def test_multi_po_prices(self):
        other = replace(self.key, po="PO2")
        allocation = allocate_receipts(company="1100", vendor="V1", currency="EUR", invoice_id="I1",
            lines=[InvoiceQuantityLine("L1", 3000, "ud", (OrderPortion(self.key, 1000), OrderPortion(other, 2000)))],
            orders=[OrderLine(self.key, "ud"), OrderLine(other, "ud")],
            receipts=[Receipt("R1", self.key, 1000, "ud", "2026-07-01"), Receipt("R2", other, 2000, "ud", "2026-07-01")])
        result = self.value([ValuationLine("L1", 510, self.cost, 3000)], allocation=allocation,
                            prices=[OrderPrice(self.key, 100), OrderPrice(other, 200)])
        self.assertEqual([c.amount_doc for c in result.components], [100, 400, 10])
        self.assert_net_entry(result)

    def test_explicit_eligibility_and_incomplete_allocation(self):
        for decision in ("HOLD", "REJECT", "DUPLICATE", "NOT_INVOICE"):
            result = self.value([], decision=decision)
            self.assertEqual((result.status, result.components), ("INELIGIBLE", ()))
        direct = self.value([ValuationLine("L1", 100, self.cost)], decision="POST_PAYMENT_BLOCK")
        self.assertEqual(direct.status, "VALUED")
        missing = self.value([ValuationLine("L1", 100, self.cost, 1000)])
        self.assertEqual(missing.status, "UNALLOCATED")
        with self.assertRaises(ValueError):
            self.value([ValuationLine("L1", 100, self.cost, 999)], allocation=self.allocation(1000))

    def test_line_fx_and_supplier_rounding_absorption(self):
        rates = RateTable([dict(currency="USD", date="2026-07-30", rate="2")])
        result = self.value([ValuationLine("L1", 1, self.cost), ValuationLine("L2", 1, self.cost)],
                            currency="USD", rates=rates)
        self.assertEqual([c.amount_local for c in result.components], [1, 1])
        self.assertEqual((result.net_doc, result.net_local), (2, 2))
        self.assert_net_entry(result)
        mx = self.value([ValuationLine("L1", 100, replace(self.cost, company="3100"))],
                        company="3100", currency="MXN")
        self.assertEqual(mx.local_currency, "MXN")
        with self.assertRaises(ValueError):
            self.value([ValuationLine("L1", 1, self.cost)], currency="USD")

    def test_invalid_imputation_price_and_scope(self):
        for cost in (replace(self.cost, company="2100"), replace(self.cost, cost_center="CC"),
                     replace(self.cost, wbs=None), replace(self.cost, account="40000000")):
            with self.assertRaises(ValueError):
                self.value([ValuationLine("L1", 100, cost)])
        for price in (-1, 1.0, True, "NaN"):
            with self.assertRaises((ValueError, TypeError)):
                self.value([ValuationLine("L1", 100, self.cost, 1000)],
                           allocation=self.allocation(1000), prices=[OrderPrice(self.key, price)])
        for scope in (dict(company="2100"), dict(vendor="V2"), dict(currency="USD"), dict(invoice_id="I2")):
            cost = replace(self.cost, company=scope.get("company", "1100"))
            with self.assertRaises(ValueError):
                self.value([ValuationLine("L1", 100, cost, 1000)], allocation=self.allocation(1000),
                           rates=RateTable([]), **scope)


if __name__ == "__main__":
    unittest.main()
