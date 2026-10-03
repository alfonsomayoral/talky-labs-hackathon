import unittest

from kalmora.bankrec.model import Category, Shape
from kalmora.bankrec.match import match_account
from bankrec_support import ACCOUNT, USD, bank, book


def run(bank_lines, book_lines, account=ACCOUNT):
    return match_account(account, bank_lines, book_lines)


class ReferenceGroupTests(unittest.TestCase):
    def test_remittance_matches_all_payments_with_equal_total(self):
        state = run([bank("B1", "2026-07-10", -300, "ORDEN TRANSFERENCIAS SEPA REMESA 20260710-433")],
                    [book("E1#2", "2026-07-10", -100, "F110", "F110-1100-20260710-433"),
                     book("E2#2", "2026-07-10", -200, "F110", "F110-1100-20260710-433"),
                     book("E3#2", "2026-07-10", -200, "F110", "F110-1100-20260710-999")])
        (match,) = state.matches
        self.assertEqual((match.shape, match.tier, sorted(match.book_lines)), (Shape.ONE_TO_MANY, "reference-group", ["E1#2", "E2#2"]))
        self.assertEqual(list(state.book), ["E3#2"])

    def test_remittance_with_a_different_total_is_left_alone_with_a_diagnostic(self):
        state = run([bank("B1", "2026-07-10", -300, "REMESA 20260710-433")],
                    [book("E1#2", "2026-07-10", -100, "F110", "F110-1100-20260710-433")])
        self.assertEqual((state.matches, list(state.bank)), ([], ["B1"]))
        self.assertTrue(any("totals differ" in d for d in state.diagnostics))

    def test_payroll_paid_in_two_lots_is_many_to_one(self):
        state = run([bank("B1", "2026-07-31", -60, "ORDEN NOMINAS 07/2026 LOTE 1"),
                     bank("B2", "2026-07-31", -40, "ORDEN NOMINAS 07/2026 LOTE 2")],
                    [book("P#2", "2026-07-31", -100, "PAYROLL", "NOM202607")])
        (match,) = state.matches
        self.assertEqual((match.shape, sorted(match.bank_lines)), (Shape.MANY_TO_ONE, ["B1", "B2"]))

    def test_group_book_lines_must_be_near_the_statement_date(self):
        state = run([bank("B1", "2026-04-07", -50, "ABONO ANTICIPO FACTORING REMESA FAC26040794")],
                    [book("F1#1", "2026-04-07", -50, "FACTORING", "FAC26040794"),
                     book("F2#1", "2026-06-11", -9, "FACTORING", "FAC26040794")])
        self.assertEqual([m.book_lines for m in state.matches], [("F1#1",)])

    def test_pooling_with_equal_amounts_uses_the_company_suffix(self):
        lines = [bank("B1", "2026-06-26", -30, "TRASPASO CASH POOLING BIN-1200"), bank("B2", "2026-06-26", -30, "TRASPASO CASH POOLING BIN-1100")]
        books = [book("P1#1", "2026-06-26", -30, "POOL", "CP2606261100"), book("P2#1", "2026-06-26", -30, "POOL", "CP2606261200")]
        pairs = {m.bank_lines[0]: m.book_lines[0] for m in run(lines, books).matches}
        self.assertEqual(pairs, {"B1": "P2#1", "B2": "P1#1"})


class OneToOneTests(unittest.TestCase):
    def test_direct_debit_matches_by_invoice_even_when_booked_after_the_bank(self):
        state = run([bank("B1", "2026-06-30", -182300, "RECIBO ENERGIA", mandate="V100029-1100", invoice="F2631632")],
                    [book("D#2", "2026-07-15", -182300, "DD", "F2631632"), book("D2#2", "2026-07-02", -182300, "DD", "F9")])
        self.assertEqual([m.book_lines for m in state.matches], [("D#2",)])

    def test_direct_debit_with_the_same_invoice_but_another_amount_is_a_book_amount_error(self):
        state = run([bank("B1", "2026-07-08", -1100, "RECIBO X", mandate="V1-1100", invoice="F1")],
                    [book("D#2", "2026-07-08", -1000, "DD", "F1")])
        (match,) = state.matches
        self.assertEqual((match.difference.category, match.difference.amount), (Category.BOOK_AMOUNT_ERROR, -100))

    def test_month_end_fee_is_not_taken_by_the_next_months_statement(self):
        june, july = bank("B6", "2026-06-10", -3200, "COMISION"), bank("B7", "2026-07-10", -3200, "COMISION")
        state = run([july, june], [book("F#2", "2026-06-30", -3200, "BANKFEE", "COMISION")])
        self.assertEqual([m.bank_lines for m in state.matches], [("B6",)])
        self.assertEqual(list(state.bank), ["B7"])

    def test_book_fee_posted_before_the_bank_date_does_not_match(self):
        state = run([bank("B1", "2026-07-20", -3000, "COMISION MANTENIMIENTO")], [book("F#2", "2026-07-10", -3000, "BANKFEE", "X")])
        self.assertEqual(state.matches, [])

    def test_equal_candidates_pair_in_id_order_with_a_diagnostic(self):
        state = run([bank("B2", "2026-07-10", -50, "X"), bank("B1", "2026-07-10", -50, "X")],
                    [book("E2#1", "2026-07-10", -50), book("E1#1", "2026-07-10", -50)])
        self.assertEqual(sorted(m.bank_lines + m.book_lines for m in state.matches), [("B1", "E1#1"), ("B2", "E2#1")])
        self.assertTrue(any(d.startswith("ambiguous") for d in state.diagnostics))

    def test_recurring_amount_is_paired_chronologically(self):
        state = run([bank("A", "2026-05-07", -9, "RECIBO R"), bank("B", "2026-06-08", -9, "RECIBO R")],
                    [book("K1#1", "2026-06-01", -9, "DD", "I1"), book("K2#1", "2026-06-09", -9, "DD", "I2")])
        self.assertEqual({m.bank_lines[0]: m.book_lines[0] for m in state.matches}, {"A": "K1#1", "B": "K2#1"})

    def test_a_line_is_used_once(self):
        state = run([bank("B1", "2026-07-10", -50, "X"), bank("B2", "2026-07-10", -50, "X")], [book("E1#1", "2026-07-10", -50)])
        self.assertEqual((len(state.matches), len(state.bank)), (1, 1))

    def test_foreign_currency_account_compares_document_amounts(self):
        usd = bank("B1", "2026-07-10", -1450000, "COMISION", account=USD.id)
        state = run([usd], [book("S#2", "2026-07-10", -22324761, "SWIFT", "F1", doc=-1450000, currency="USD", company="3100")], USD)
        self.assertEqual(len(state.matches), 1)


class DifferenceTests(unittest.TestCase):
    def test_foreign_transfer_matches_by_beneficiary_with_an_fx_difference(self):
        state = run([bank("B1", "2026-07-10", -195243, "TRANSF. EXTERIOR USD 2,400.00 CLOUDVANE SYSTEMS, INC")],
                    [book("S#2", "2026-07-10", -194426, "SWIFT", "0035252", text="Transferencia internacional Cloudvane Systems, Inc")])
        (match,) = state.matches
        self.assertEqual((match.tier, match.difference.category, match.difference.amount), ("foreign-transfer", Category.FX_RATE_DIFFERENCE, -817))

    def test_foreign_transfer_with_equal_amount_is_a_plain_match(self):
        state = run([bank("B1", "2026-06-10", -192023, "TRANSF. EXTERIOR USD 2,400.00 CLOUDVANE SYSTEMS, INC")],
                    [book("S#2", "2026-06-10", -192023, "SWIFT", "0035251", text="Transferencia internacional Cloudvane Systems, Inc")])
        self.assertIsNone(state.matches[0].difference)

    def test_foreign_transfer_far_from_the_book_amount_is_not_paired(self):
        state = run([bank("B1", "2026-07-10", -400000, "TRANSF. EXTERIOR USD 2,400.00 CLOUDVANE SYSTEMS, INC")],
                    [book("S#2", "2026-07-10", -194426, "SWIFT", "x", text="Transferencia internacional Cloudvane Systems, Inc")])
        self.assertEqual(state.matches, [])

    def test_loan_instalment_larger_than_the_principal_is_a_loan_interest_difference(self):
        state = run([bank("B1", "2026-07-06", -11511250, "CUOTA PRESTAMO 0182-445 RECIBO 07/2026")],
                    [book("L#2", "2026-07-06", -10000000, "LOAN", "PRE202607")])
        (match,) = state.matches
        self.assertEqual((match.difference.category, match.difference.amount), (Category.LOAN_INTEREST_NOT_BOOKED, -1511250))


if __name__ == "__main__":
    unittest.main()
