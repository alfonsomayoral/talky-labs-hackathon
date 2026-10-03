from dataclasses import replace
from decimal import Decimal
import unittest

from kalmora.ap_allocation import (
    ConsumptionState, InvoiceQuantityLine, OrderKey, OrderLine, OrderPortion,
    Receipt, allocate_receipts,
)
from kalmora.ap_holds import (
    HOLD_CODES, HoldScope, PriceLine, PricePortion, bank_safety_check, evaluate_holds,
    price_variance_check, receipt_quantity_check,
)
from kalmora.ap_rejections import RuleCheck
from kalmora.facts import Evidence, Fact
from kalmora.money import RateTable


def fact(value, field="source"):
    return (Fact(value, Evidence("synthetic", field)),)


def clear_fields():
    return {name: fact(value, name) for name, value in {
        "vendor_in_master": True, "bank_differs": False, "similar_domain": False,
        "signed_change_supported": False, "factoring_supported": False,
        "quantity_check_applicable": False, "price_check_applicable": False,
    }.items()}


class HoldTests(unittest.TestCase):
    def setUp(self):
        self.scope = HoldScope("1100", "V1", "EUR", "I1")
        self.key = OrderKey("1100", "V1", "EUR", "PO1", 10)
        self.evidence = (Evidence("erp.receipts", "catalog"),)
        self.day = fact("2026-07-31", "invoice_date")[0]

    def allocation(self, qty=1000, available=None, *, key=None, state=ConsumptionState()):
        key = self.key if key is None else key
        scope = replace(self.scope, company=key.company, vendor=key.vendor, currency=key.currency)
        return allocate_receipts(company=scope.company, vendor=scope.vendor, currency=scope.currency,
            invoice_id=scope.invoice_id, lines=(InvoiceQuantityLine("L1", qty, "ud",
                (OrderPortion(key, qty),)),), orders=(OrderLine(key, "ud"),),
            receipts=(Receipt("R1", key, qty if available is None else available, "ud", "2026-07-01"),),
            state=state)

    def price(self, po, invoiced, qty=1000, currency="EUR", rates=None, rate_evidence=()):
        key = replace(self.key, currency=currency)
        scope = replace(self.scope, currency=currency)
        line = PriceLine("L1", fact(invoiced, "invoice_price"),
                         (PricePortion(key, qty, fact(po, "po_price")),))
        return price_variance_check(scope, self.day, (line,), allocation=self.allocation(qty, key=key),
                                    rates=rates, rate_evidence=rate_evidence)

    def test_four_hold_reasons_and_precedence(self):
        true = lambda code: RuleCheck(code, True, self.evidence)
        cases = (
            ({"vendor_in_master": fact(False)}, None, None),
            ({"bank_differs": fact(True)}, None, None),
            ({"quantity_check_applicable": fact(True)}, true(HOLD_CODES[2]), None),
            ({"price_check_applicable": fact(True)}, None, true(HOLD_CODES[3])),
        )
        for index, (changes, qty, price) in enumerate(cases):
            stage = evaluate_holds(clear_fields() | changes, quantity_check=qty, price_check=price)
            self.assertEqual((stage.status, stage.reason), ("HOLD", HOLD_CODES[index]))
        stage = evaluate_holds(clear_fields() | {"vendor_in_master": fact(False),
            "bank_differs": fact(True), "quantity_check_applicable": fact(True),
            "price_check_applicable": fact(True)}, quantity_check=true(HOLD_CODES[2]),
            price_check=true(HOLD_CODES[3]))
        self.assertEqual(stage.reason, HOLD_CODES[0])
        self.assertEqual(evaluate_holds(clear_fields() | {"vendor_in_master": (),
                         "similar_domain": fact(True)}).status, "UNKNOWN")

    def test_bank_safety_three_valued_truth_table(self):
        values = (False, True, None)
        for differs in values:
            for letter in values:
                for factor in values:
                    for domain in values:
                        fields = {name: () if value is None else fact(value, name) for name, value in
                            zip(("bank_differs", "signed_change_supported", "factoring_supported", "similar_domain"),
                                (differs, letter, factor, domain))}
                        possible = set()
                        for d in (False, True) if differs is None else (differs,):
                            for l in (False, True) if letter is None else (letter,):
                                for f in (False, True) if factor is None else (factor,):
                                    for s in (False, True) if domain is None else (domain,):
                                        possible.add(s or (d and not (l or f)))
                        expected = next(iter(possible)) if len(possible) == 1 else None
                        self.assertIs(bank_safety_check(fields).violation, expected)
        fields = clear_fields() | {"bank_differs": fact(True), "factoring_supported": fact(True),
                                   "similar_domain": fact(True)}
        self.assertEqual(evaluate_holds(fields).reason, "BANK_DETAILS_CHANGED")

    def test_quantity_shortage_is_atomic_and_unknown_reference_is_not_shortage(self):
        prior = ConsumptionState()
        blocked = self.allocation(1001, available=1000, state=prior)
        result = receipt_quantity_check(self.scope, blocked, evidence=self.evidence,
                                        catalog_complete=fact(True)[0])
        self.assertTrue(result.violation)
        self.assertIs(blocked.state, prior)
        self.assertEqual(blocked.allocations, ())
        self.assertIsNone(receipt_quantity_check(self.scope, blocked, evidence=self.evidence,
                                              catalog_complete=None).violation)
        allocated = self.allocation()
        self.assertFalse(receipt_quantity_check(self.scope, allocated, evidence=self.evidence,
                                               catalog_complete=None).violation)
        bad = replace(blocked, diagnostics=(replace(blocked.diagnostics[0], code="AMBIGUOUS_REFERENCE"),))
        self.assertIsNone(receipt_quantity_check(self.scope, bad, evidence=self.evidence,
                                              catalog_complete=fact(True)[0]).violation)
        with self.assertRaises(ValueError):
            receipt_quantity_check(replace(self.scope, vendor="V2"), allocated,
                                   evidence=self.evidence, catalog_complete=None)

    def test_percent_and_eur_limits_are_strict_and_or(self):
        # Small line, percentage alone; exact 2% remains permitted.
        self.assertFalse(self.price("10000", "10200").violation)
        self.assertTrue(self.price("10000", "10200.000001").violation)
        # 1% on a large line: EUR amount alone decides.
        self.assertFalse(self.price("1000000", "1010000", 1500).violation)
        self.assertTrue(self.price("1000000", "1010000", 1501).violation)
        self.assertFalse(self.price("1000000", "999999", 10000000).violation)
        self.assertTrue(self.price("0", "0.01").violation)

    def test_foreign_eur_boundary_exact_and_invoice_date_fallback(self):
        rates = RateTable([{"date": "2026-07-30", "currency": "USD", "rate": Decimal("1.2")},
                           {"date": "2026-08-01", "currency": "USD", "rate": Decimal("9")},
                           {"date": "2026-07-30", "currency": "MXN", "rate": Decimal("20")}])
        fx = (Evidence("fx_rates", "SYN-BCE:2026-07-30"),)
        self.assertFalse(self.price("1000000", "1010000", 1800, "USD", rates, fx).violation)
        self.assertTrue(self.price("1000000", "1010000", 1801, "USD", rates, fx).violation)
        # €150.0000001 must not be rounded back down to €150.00.
        self.assertTrue(self.price("1000000", "1010000.0000001", 1800, "USD", rates, fx).violation)
        self.assertFalse(self.price("1000000", "1010000", 30000, "MXN", rates, fx).violation)
        self.assertTrue(self.price("1000000", "1010000", 30001, "MXN", rates, fx).violation)
        self.assertIsNone(self.price("1000000", "1010000", 1800, "USD", rates).violation)
        future_only = RateTable([{"date": "2026-08-01", "currency": "USD", "rate": "1.2"}])
        self.assertIsNone(self.price("1000000", "1010000", 1800, "USD", future_only, fx).violation)
        # A percentage breach is already proved; missing FX cannot erase it.
        self.assertTrue(self.price("10000", "10201", currency="USD").violation)

    def test_no_cross_line_aggregation_and_allocation_coverage(self):
        allocated = self.allocation(2000)
        a = allocated.allocations[0]
        split = replace(allocated, allocations=(replace(a, line_id="L1", quantity_milli=1000),
                                                replace(a, line_id="L2", quantity_milli=1000)))
        lines = tuple(PriceLine(line_id, fact("1010000"),
                 (PricePortion(self.key, 1000, fact("1000000")),)) for line_id in ("L1", "L2"))
        self.assertFalse(price_variance_check(self.scope, self.day, lines, allocation=split).violation)
        # Each €100 line is below €150 even though invoice total increase is €200.
        with self.assertRaises(ValueError):
            price_variance_check(self.scope, self.day, lines[:1], allocation=split)
        with self.assertRaises(ValueError):
            price_variance_check(replace(self.scope, company="2100"), self.day, lines, allocation=split)
        before = allocated.state
        bad = (replace(lines[0], invoice_unit_price_cents=fact("1040000")),)
        self.assertTrue(price_variance_check(self.scope, self.day, bad, allocation=self.allocation()).violation)
        self.assertIs(allocated.state, before)

    def test_missing_conflicting_prices_and_required_applicability(self):
        allocated = self.allocation()
        line = PriceLine("L1", fact("10000"), (PricePortion(self.key, 1000, ()),))
        self.assertIsNone(price_variance_check(self.scope, self.day, (line,), allocation=allocated).violation)
        line = replace(line, portions=(PricePortion(self.key, 1000, fact("10000") + fact("9999")),))
        self.assertIsNone(price_variance_check(self.scope, self.day, (line,), allocation=allocated).violation)
        self.assertEqual(evaluate_holds(clear_fields() | {"price_check_applicable": ()}).status, "UNKNOWN")
        self.assertEqual(evaluate_holds(clear_fields() | {"quantity_check_applicable": fact(True)}).status, "UNKNOWN")
        self.assertEqual(evaluate_holds(clear_fields()).status, "CLEAR")

    def test_multi_po_line_and_receipt_fragmentation(self):
        key2 = replace(self.key, po="PO2", item=20)
        qty_line = InvoiceQuantityLine("L1", 3000, "ud", (
            OrderPortion(self.key, 1000), OrderPortion(key2, 2000)))
        def allocate(receipts):
            return allocate_receipts(company="1100", vendor="V1", currency="EUR", invoice_id="I1",
                lines=(qty_line,), orders=(OrderLine(self.key, "ud"), OrderLine(key2, "ud")),
                receipts=receipts)
        one = allocate((Receipt("R1", self.key, 1000, "ud", "2026-07-01"),
                        Receipt("R2", key2, 2000, "ud", "2026-07-01")))
        fragmented = allocate((Receipt("R1", self.key, 1000, "ud", "2026-07-01"),
                              Receipt("R2", key2, 999, "ud", "2026-07-01"),
                              Receipt("R3", key2, 1001, "ud", "2026-07-01")))
        line = PriceLine("L1", fact("1010000"), (
            PricePortion(self.key, 1000, fact("1000000")),
            PricePortion(key2, 2000, fact("1005000"))))
        # €100 + €100 on one original invoice line breaches the €150 test.
        for allocated in (one, fragmented):
            self.assertTrue(price_variance_check(self.scope, self.day, (line,), allocation=allocated).violation)
        self.assertEqual(one.state.invoices, fragmented.state.invoices)
        self.assertEqual(sum(u.quantity_milli for u in one.state.usages),
                         sum(u.quantity_milli for u in fragmented.state.usages))
        for field, value in (("company", "2100"), ("vendor", "V2"), ("currency", "USD")):
            with self.assertRaises(ValueError):
                price_variance_check(replace(self.scope, **{field: value}), self.day,
                                     (line,), allocation=one)


if __name__ == "__main__":
    unittest.main()
