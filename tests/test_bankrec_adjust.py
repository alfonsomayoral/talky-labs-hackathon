import unittest

from kalmora.bankrec import adjust as adj
from kalmora.bankrec import classify
from kalmora.bankrec.model import Category, Difference
from kalmora.money import RateTable
from bankrec_support import ACCOUNT, OTHER, USD, bank, book

RATES = RateTable([{"date": "2026-07-10", "base": "EUR", "currency": "USD", "rate": "1.2344"},
                   {"date": "2026-07-10", "base": "EUR", "currency": "MXN", "rate": "19.0053"}])


def builder(account=ACCOUNT, entries=None, factoring=None, receipts=None):
    return adj.Builder(account, adj.AdjustContext(RATES, entries or {}, factoring or {}, (receipts or {}).get))


def totals(adjustment):
    return sum(x.debit for x in adjustment.lines), sum(x.credit for x in adjustment.lines)


def shape(adjustment):
    return [(x.account, x.debit, x.credit, x.partner, x.assignment, x.cost_center) for x in adjustment.lines]


class BankCategoryTests(unittest.TestCase):
    def test_text_rules(self):
        cases = {"COMISION MANTENIMIENTO CUENTA": Category.BANK_FEE_NOT_BOOKED, "GASTOS SWIFT": Category.BANK_FEE_NOT_BOOKED,
                 "DEVOLUCION RECIBO MD06 X": Category.RETURNED_DIRECT_DEBIT, "COMISION DEVOLUCION RECIBO": Category.RETURNED_DIRECT_DEBIT,
                 "ABONO LIQUIDACION INTERESES": Category.INTEREST_NOT_BOOKED, "RETENCION 19% S/ INTERESES": Category.INTEREST_NOT_BOOKED,
                 "LIQUIDACION TARJETA VISA": Category.CARD_SETTLEMENT_NOT_BOOKED, "TRASPASO CASH POOLING SALDO CERO": Category.POOLING_NOT_BOOKED,
                 "SOMETHING ELSE": None}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(classify.bank_category(bank("B", "2026-07-01", -1, text)), expected)

    def test_direct_debit_needs_mandate_and_invoice(self):
        self.assertEqual(classify.bank_category(bank("B", "2026-07-01", -1, "RECIBO X", mandate="V1-1100", invoice="F1")),
                         Category.DIRECT_DEBIT_NOT_BOOKED)
        self.assertIsNone(classify.bank_category(bank("B", "2026-07-01", -1, "RECIBO X")))

    def test_credit_from_a_customer_without_a_book_line_is_an_unrecorded_receipt(self):
        self.assertEqual(classify.bank_category(bank("B", "2026-07-07", 5, "TRANSFERENCIA DE DIPUTACION")), Category.UNRECORDED_RECEIPT)
        self.assertIsNone(classify.bank_category(bank("B", "2026-07-07", -5, "TRANSFERENCIA DE DIPUTACION")))

    def test_second_identical_charge_is_a_bank_error(self):
        first = bank("B1", "2026-07-13", -526544, "RECIBO ONDANET", mandate="V100030-1000", invoice="GM26/21893")
        second = bank("B2", "2026-07-14", -526544, "RECIBO ONDANET", mandate="V100030-1000", invoice="GM26/21893")
        self.assertEqual(classify.duplicate_bank_lines([second, first]), {"B2"})

    def test_book_duplicate_is_a_later_posting_of_the_same_reference_within_days(self):
        lines = [book("A#4", "2026-07-30", -9, "CONFIRMING", "CF1"), book("B#4", "2026-07-31", -9, "CONFIRMING", "CF1"),
                 book("C#4", "2026-07-02", -9, "CONFIRMING", "CF1"), book("F1#2", "2026-06-30", -3, "BANKFEE", "COMISION"),
                 book("F2#2", "2026-06-30", -3, "BANKFEE", "COMISION")]
        self.assertEqual(classify.duplicate_book_lines(lines), {"B#4"})

    def test_book_side_rules(self):
        end = "2026-07-31"
        self.assertEqual(classify.book_category(book("A#1", "2026-07-01", 5, "CLOSE_FX:reversal"), end), Category.FX_REVALUATION)
        self.assertEqual(classify.book_category(book("A#1", "2026-07-31", 5, "TREASURY"), end), Category.TRANSFER_IN_TRANSIT)
        self.assertEqual(classify.book_category(book("A#1", "2026-07-31", -5, "MANUAL_PAYMENT"), end), Category.OUTSTANDING_PAYMENT)
        self.assertIsNone(classify.book_category(book("A#1", "2026-07-02", -5, "MANUAL_PAYMENT"), end))


class AdjustmentTests(unittest.TestCase):
    def test_equal_fees_are_one_aggregated_entry(self):
        b = builder()
        adj.fees(b, [bank(f"B{i}", "2026-07-10", -3200, "COMISION TRANSFERENCIA EXTERIOR OUR") for i in range(4)]
                 + [bank("B9", "2026-07-10", -950, "GASTOS SWIFT")])
        self.assertEqual(sorted(shape(a)[0][1] for a in b.out), [950, 12800])
        self.assertEqual(shape(b.out[-1] if b.out[-1].causes != ("B9",) else b.out[0]), [("62600000", 12800, 0, None, None, None), ("57200001", 0, 12800, None, None, None)])

    def test_guarantee_fee_goes_to_66900000(self):
        b = builder()
        adj.fees(b, [bank("B1", "2026-07-10", -500, "COMISION AVAL")])
        self.assertEqual(b.out[0].lines[0].account, "66900000")

    def test_direct_debit_clears_the_vendor_item_with_the_invoice_as_assignment(self):
        b = builder()
        adj.direct_debits(b, [bank("B1", "2026-07-01", -90596, "RECIBO X", mandate="V100028-1100", invoice="2026-037541")])
        self.assertEqual(shape(b.out[0]), [("41000000", 90596, 0, "V100028", "2026-037541", None), ("57200001", 0, 90596, None, None, None)])

    def test_direct_debit_of_an_unknown_invoice_is_categorised_without_adjustment(self):
        b = adj.Builder(ACCOUNT, adj.AdjustContext(RATES, {}, {}, {}.get, invoice_known=lambda vendor, invoice: False))
        adj.direct_debits(b, [bank("B1", "2026-07-01", -107141, "RECIBO X", mandate="V100028-1100", invoice="2026-037563")])
        self.assertEqual((b.out, b.skipped_debits), ([], {"B1"}))
        self.assertTrue(any("2026-037563" in d for d in b.diagnostics))

    def test_returned_receipt_is_one_entry_with_the_commission(self):
        b = builder(receipts={"RC26-00280": "C200041"})
        adj.returned(b, [bank("B1", "2026-07-14", -49869, "DEVOLUCION RECIBO AM04", receipt="RC26-00280"),
                         bank("B2", "2026-07-14", -450, "COMISION DEVOLUCION RECIBO")])
        self.assertEqual(shape(b.out[0]), [("43000000", 49869, 0, "C200041", "RC26-00280", None), ("62600000", 450, 0, None, None, None),
                                           ("57200001", 0, 50319, None, None, None)])

    def test_returned_receipt_without_a_customer_builds_nothing(self):
        b = builder()
        adj.returned(b, [bank("B1", "2026-07-14", -5, "DEVOLUCION RECIBO AM04", receipt="RC26-00280")])
        self.assertEqual((b.out, len(b.diagnostics)), ([], 1))

    def test_interest_with_retention_is_one_entry(self):
        b = builder()
        adj.interest(b, [bank("B1", "2026-07-31", 403000, "ABONO LIQUIDACION INTERESES"), bank("B2", "2026-07-31", -76570, "RETENCION 19% S/ INTERESES")])
        self.assertEqual(shape(b.out[0]), [("57200001", 326430, 0, None, None, None), ("47300000", 76570, 0, None, None, None),
                                           ("76200000", 0, 403000, None, None, None)])
        self.assertEqual(b.diagnostics, [])

    def test_wrong_retention_rate_is_reported(self):
        b = builder()
        adj.interest(b, [bank("B1", "2026-07-31", 1000, "ABONO LIQUIDACION INTERESES"), bank("B2", "2026-07-31", -100, "RETENCION 19% S/ INTERESES")])
        self.assertEqual(len(b.diagnostics), 1)

    def test_card_pooling_and_unrecorded_receipt_templates(self):
        b = builder()
        adj.card(b, [bank("C", "2026-07-06", -1180600, "LIQUIDACION TARJETA VISA")])
        adj.pooling(b, [bank("P", "2026-07-22", -27053177, "TRASPASO CASH POOLING SALDO CERO")])
        adj.unrecorded_receipts(b, [bank("R", "2026-07-07", 51496121, "TRANSFERENCIA DE DIPUTACION")])
        self.assertEqual(shape(b.out[0])[0], ("62910000", 1180600, 0, None, None, "CC-1000-DIR"))
        self.assertEqual(shape(b.out[1]), [("57200001", 0, 27053177, None, None, None), ("55200000", 27053177, 0, "1000", None, None)])
        self.assertEqual(shape(b.out[2]), [("57200001", 51496121, 0, None, None, None), ("55500000", 0, 51496121, None, None, None)])

    def test_head_company_pooling_takes_the_partner_from_the_text(self):
        head = type(ACCOUNT)("BIN-1000", "1000", "57200001", "EUR", "n43")
        b = builder(head)
        adj.pooling(b, [bank("P", "2026-06-26", -30, "TRASPASO CASH POOLING BIN-1100", account="BIN-1000")])
        self.assertEqual(b.out[0].lines[1].partner, "1100")

    def test_usd_fee_is_converted_at_the_booking_date_rate(self):
        b = builder(USD)
        adj.fees(b, [bank("B", "2026-07-10", -1800, "COMISION TRANSFERENCIA EXTERIOR OUR", account=USD.id)])
        self.assertEqual(shape(b.out[0]), [("62600000", 27713, 0, None, None, None), ("57200006", 0, 27713, None, None, None)])

    def test_fx_difference_uses_the_fx_account_of_the_payment_entry(self):
        entries = {"S": {"company": "1100", "lines": [{"account": "76800000", "debit": 0, "credit": 35174}]}}
        b = builder(entries=entries)
        adj.differences(b, [(bank("B", "2026-07-10", -5743000, "T"), book("S#2", "2026-07-10", -5718981, "SWIFT", entry="S"),
                             Difference(Category.FX_RATE_DIFFERENCE, -24019))])
        self.assertEqual(shape(b.out[0]), [("76800000", 24019, 0, None, None, None), ("57200001", 0, 24019, None, None, None)])

    def test_fx_difference_without_a_payment_line_follows_the_direction(self):
        b = builder()
        adj.differences(b, [(bank("B", "2026-07-10", -10, "T"), book("S#2", "2026-07-10", -9, "SWIFT"), Difference(Category.FX_RATE_DIFFERENCE, -1)),
                            (bank("C", "2026-07-10", -9, "T"), book("S2#2", "2026-07-10", -10, "SWIFT"), Difference(Category.FX_RATE_DIFFERENCE, 1))])
        self.assertEqual((b.out[0].lines[0].account, b.out[1].lines[1].account), ("66800000", "76800000"))
        self.assertEqual(shape(b.out[1])[0], ("57200001", 1, 0, None, None, None))

    def test_loan_interest_and_book_amount_error(self):
        b = builder()
        adj.differences(b, [(bank("B", "2026-07-06", -11511250, "CUOTA"), book("L#2", "2026-07-06", -10000000, "LOAN"),
                             Difference(Category.LOAN_INTEREST_NOT_BOOKED, -1511250)),
                            (bank("D", "2026-07-08", -1100, "RECIBO", mandate="V1-1100", invoice="F1"), book("DD#2", "2026-07-08", -1000, "DD"),
                             Difference(Category.BOOK_AMOUNT_ERROR, -100))])
        self.assertEqual(shape(b.out[0])[0], ("66200000", 1511250, 0, None, None, None))
        self.assertEqual(shape(b.out[1]), [("41000000", 100, 0, "V1", "F1", None), ("57200001", 0, 100, None, None, None)])

    def test_factoring_charges_credit_the_factor_account_with_the_ceded_invoice(self):
        b = builder(factoring={"FAC1": {"interest": 442963, "fee": 107830, "invoice": "OB26-00048"}})
        adj.differences(b, [(bank("B", "2026-07-06", 38267830, "ABONO ANTICIPO"), book("F#1", "2026-07-06", 38267830, "FACTORING", "FAC1"),
                             Difference(Category.FACTORING_CHARGES_NOT_BOOKED, 0))])
        self.assertEqual(shape(b.out[0]), [("66500000", 550793, 0, None, None, None), ("55300000", 0, 550793, "FACTOR-BAE", "OB26-00048", None)])

    def test_duplicate_book_entry_is_cancelled_line_by_line(self):
        entry = {"company": "1100", "lines": [
            {"account": "40000000", "debit": 12, "credit": 0, "partner": "V1", "assignment": "I1"},
            {"account": "40000000", "debit": 8, "credit": 0, "partner": "V2", "assignment": "I2"},
            {"account": "57200003", "debit": 0, "credit": 20}]}
        b = builder(entries={"E": entry})
        adj.book_duplicates(b, [book("E#3", "2026-07-31", -20, "CONFIRMING", "CF1", entry="E")])
        self.assertEqual(shape(b.out[0]), [("40000000", 0, 12, "V1", "I1", None), ("40000000", 0, 8, "V2", "I2", None),
                                           ("57200003", 20, 0, None, None, None)])

    def test_wrong_bank_account_moves_the_booking_between_accounts(self):
        b = builder()
        adj.wrong_bank(b, [(bank("B", "2026-07-31", -100, "ORDEN NOMINAS"), book("P#2", "2026-07-31", -100, "PAYROLL"), OTHER)])
        self.assertEqual(shape(b.out[0]), [("57200002", 100, 0, None, None, None), ("57200001", 0, 100, None, None, None)])
        self.assertTrue(all(x.company == "1100" for x in b.out[0].lines))

    def test_every_adjustment_balances(self):
        b = builder(receipts={"RC1": "C1"})
        adj.fees(b, [bank("F", "2026-07-10", -3, "COMISION X")])
        adj.card(b, [bank("C", "2026-07-06", -7, "LIQUIDACION TARJETA")])
        adj.returned(b, [bank("R", "2026-07-14", -5, "DEVOLUCION RECIBO", receipt="RC1"), bank("K", "2026-07-14", -1, "COMISION DEVOLUCION RECIBO")])
        for a in b.out:
            self.assertEqual(*totals(a))


if __name__ == "__main__":
    unittest.main()
