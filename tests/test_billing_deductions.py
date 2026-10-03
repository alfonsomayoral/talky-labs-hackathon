from dataclasses import replace
import unittest

from kalmora.billing_deductions import (
    AdvanceApplication, AdvanceState, BillingBaseLine, BillingScope, BillingTerms,
    advance_from_history, calculate_billing_amounts,
)
from kalmora.validation import validate_entry


class BillingDeductionTests(unittest.TestCase):
    def setUp(self):
        self.scope = BillingScope("1100", "EUR", "CT1", "C1")
        self.mx = BillingScope("3100", "MXN", "MX1", "C2")

    def calculate(self, amounts=(10000,), **kwargs):
        scope = kwargs.pop("scope", self.scope)
        params = dict(scope=scope, invoice_id="I1", invoice_date="2026-07-31",
                      lines=[BillingBaseLine(scope, f"L{i}", amount) for i, amount in enumerate(amounts)],
                      terms=BillingTerms("R21", 0, False, 0))
        params.update(kwargs)
        return calculate_billing_amounts(**params)

    def assert_conserved(self, result):
        self.assertEqual(result.payable_cents + result.guarantee_cents + result.mx_levy_cents
                         + result.advance_cents, result.base_cents + result.tax_cents)
        lines = [dict(account="43000000", partner=result.scope.customer, debit=result.payable_cents, credit=0)]
        lines.extend(dict(account=d.debit_account, partner=d.partner, debit=d.amount_cents, credit=0)
                     for d in result.deductions)
        lines += [dict(account="70510000", wbs="W1", debit=0, credit=result.base_cents),
                  dict(account="47700000", debit=0, credit=result.tax_cents)]
        self.assertEqual(validate_entry(dict(company=result.scope.company, lines=lines)), [])

    def test_all_tax_codes_and_zero_output_reverse_tax(self):
        cases = [("R21", "1100", 2100), ("R10", "1200", 1000), ("RISP", "1100", 0),
                 ("PR06", "2100", 600), ("PR23", "2100", 2300), ("PRAUT", "2100", 0),
                 ("MR16", "3100", 1600)]
        for code, company, expected in cases:
            scope = replace(self.scope, company=company, currency="MXN" if company == "3100" else "EUR")
            result = self.calculate(scope=scope, terms=BillingTerms(code, 0, False, 0))
            self.assertEqual(result.tax_cents, expected)
            self.assert_conserved(result)
            if code == "RISP":
                self.assertIn("84.Uno.2º f", result.tax_legend)

    def test_vat_rounds_per_line_and_guarantee_on_total_base(self):
        split = self.calculate((2, 2))
        whole = self.calculate((4,))
        self.assertEqual((split.tax_cents, whole.tax_cents), (0, 1))
        result = self.calculate((10010,), terms=BillingTerms("R21", 500, False, 0))
        self.assertEqual((result.tax_cents, result.guarantee_cents, result.payable_cents), (2102, 501, 11611))
        self.assert_conserved(result)

    def test_mexican_levy_and_advance_use_different_bases(self):
        state = AdvanceState(self.mx, 10000)
        result = self.calculate((10000,), scope=self.mx,
            terms=BillingTerms("MR16", 0, True, 3000), advance_state=state)
        self.assertEqual((result.tax_cents, result.gross_cents, result.mx_levy_cents,
                          result.advance_cents, result.payable_cents), (1600, 11600, 50, 3480, 8070))
        self.assertEqual(result.advance_state.available_cents, 6520)
        self.assertEqual(state.available_cents, 10000)
        self.assertEqual([(d.kind, d.debit_account) for d in result.deductions],
                         [("MX5MILL", "63100000"), ("ADVANCE", "43800000")])
        self.assert_conserved(result)

    def test_half_cent_boundaries(self):
        # Levy: 100 × 0.5% = 0.5 -> 1; advance: (100+16) × 30% = 34.8 -> 35.
        result = self.calculate((100,), scope=self.mx, terms=BillingTerms("MR16", 0, True, 3000),
                                advance_state=AdvanceState(self.mx, 100))
        self.assertEqual((result.mx_levy_cents, result.advance_cents, result.payable_cents), (1, 35, 80))
        below = self.calculate((99,), scope=self.mx, terms=BillingTerms("MR16", 0, True, 0))
        self.assertEqual(below.mx_levy_cents, 0)
        half = self.calculate((4,), scope=self.mx, terms=BillingTerms("MR16", 0, False, 3000),
                              advance_state=AdvanceState(self.mx, 100))
        self.assertEqual((half.tax_cents, half.gross_cents, half.advance_cents), (1, 5, 2))

    def test_historical_balance_exhaustion_replay_and_chronology(self):
        state = advance_from_history(scope=self.mx, received_cents=100,
                                     applications=[AdvanceApplication("OLD", "2026-06-30", 20)])
        self.assertEqual(state.available_cents, 80)
        applied = []
        for number in range(1, 5):
            result = self.calculate((100,), scope=self.mx, invoice_id=f"I{number}",
                terms=BillingTerms("MR16", 0, False, 3000), advance_state=state)
            applied.append(result.advance_cents)
            self.assertEqual(state.available_cents - result.advance_cents, result.advance_state.available_cents)
            self.assert_conserved(result)
            state = result.advance_state
        self.assertEqual(applied, [35, 35, 10, 0])
        self.assertEqual(state.available_cents, 0)
        self.assertEqual(sum(a.amount_cents for a in state.history), 100)
        with self.assertRaises(ValueError):
            self.calculate((100,), scope=self.mx, invoice_id="I4", terms=BillingTerms("MR16", 0, False, 3000), advance_state=state)
        with self.assertRaises(ValueError):
            self.calculate((100,), scope=self.mx, invoice_date="2026-06-01", terms=BillingTerms("MR16", 0, False, 3000), advance_state=state)

    def test_scope_isolation(self):
        for field, value in (("company", "1100"), ("currency", "USD"),
                             ("contract", "MX2"), ("customer", "C3")):
            foreign = replace(self.mx, **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.calculate(scope=self.mx, terms=BillingTerms("MR16", 0, False, 3000),
                               advance_state=AdvanceState(foreign, 100))
            with self.assertRaises(ValueError):
                self.calculate(scope=self.mx, terms=BillingTerms("MR16", 0, False, 0),
                               lines=[BillingBaseLine(foreign, "L", 100)])

    def test_invalid_or_unknown_inputs(self):
        for value in (-1, True, 100.0, "100"):
            with self.assertRaises((TypeError, ValueError)):
                self.calculate((value,))
        for terms in (BillingTerms("unknown", 0, False, 0), BillingTerms("MR16", 0, False, 0),
                      BillingTerms("R21", -1, False, 0), BillingTerms("R21", 0, True, 0),
                      BillingTerms("R21", 0, False, 3000), BillingTerms("R21", 0, False, 1000)):
            with self.assertRaises(ValueError):
                self.calculate(terms=terms)
        with self.assertRaises(ValueError):
            self.calculate(scope=self.mx, terms=BillingTerms("MR16", 0, False, 3000))
        with self.assertRaises(ValueError):
            advance_from_history(scope=self.mx, received_cents=10,
                                 applications=[AdvanceApplication("OLD", "2026-06-30", 11)])
        with self.assertRaises(ValueError):
            self.calculate(scope=self.mx, terms=BillingTerms("MR16", 0, False, 3000),
                           advance_state=AdvanceState(self.mx, -1))


if __name__ == "__main__":
    unittest.main()
