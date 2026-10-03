from dataclasses import replace
import unittest
from kalmora.bankrec import Adjustment, AdjustmentLine, Category
from kalmora.bankrec.model import Side
from kalmora.data import PhaseData
from test_bankrec_run import SyntheticPhase, DD, entry, line


class ExceptionOwnershipTests(SyntheticPhase):
    def test_wrong_bank_has_one_adjustment_for_both_accounts(self):
        results, _ = self.run_july()
        wrong = [a for r in results.values() for a in r.adjustments if a.category is Category.WRONG_BANK_ACCOUNT]
        self.assertEqual(len(wrong), 1)
        self.assertEqual(wrong[0].owner[1], "bank_rec")
        self.assertEqual(wrong[0].owner, replace(wrong[0], causes=tuple(reversed(wrong[0].causes))).owner)

    def test_book_amount_error_both_directions_is_single_vendor_correction(self):
        for bank_amount, expected in ((-1100, 100), (-900, -100)):
            with self.subTest(bank_amount=bank_amount):
                detail = [("01", "RECIBO ENERGIA PENINSULAR", "REF. MANDATO V100029-1100"), ("02", "FRA DIFF1", "")]
                self.statement("BIN-1100", "2026-07", 818, [("2026-07-03", bank_amount, "", "", detail, "RECIBO ENERGIA PENINSULAR")])
                journal = list(PhaseData(self.root).iter_journal())
                journal = [r for r in journal if r["id"] != "ERR"]
                journal.append(entry("ERR", "2026-07-03", "DD", "DIFF1", [line("41000000", 1000, partner="V100029", assignment="DIFF1"), line("57200001", credit=1000)]))
                self.write_journal(journal)
                results, _ = self.run_july()
                matches = [m for m in results["BIN-1100"].matches if "ERR#2" in m.book_lines]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].difference.category, Category.BOOK_AMOUNT_ERROR)
                adjustments = [a for a in results["BIN-1100"].adjustments if a.category is Category.BOOK_AMOUNT_ERROR]
                self.assertEqual(len(adjustments), 1)
                vendor = next(x for x in adjustments[0].lines if x.account == "41000000")
                self.assertEqual((vendor.debit - vendor.credit, vendor.partner, vendor.assignment), (expected, "V100029", "DIFF1"))


class OwnerContractTests(unittest.TestCase):
    def test_pooling_and_duplicate_owners_are_reproducible(self):
        lines = (AdjustmentLine("1100", "55200000", 100, 0, "1000"), AdjustmentLine("1100", "57200001", 0, 100))
        for category in (Category.POOLING_NOT_BOOKED, Category.BOOK_DUPLICATE):
            a = Adjustment(category, lines, ("B1",))
            self.assertEqual(a.owner, ("B1", "bank_rec"))

    def test_owners_reject_invalid_causes_companies_and_unadjusted_category(self):
        lines = (AdjustmentLine("1100", "41000000", 100, 0), AdjustmentLine("1100", "57200001", 0, 100))
        for category, rows, causes in ((Category.BOOK_DUPLICATE, lines, ()),
                                       (Category.BOOK_DUPLICATE, lines, ("B1", "B1")),
                                       (Category.BANK_ERROR, lines, ("B1",)),
                                       (Category.BOOK_DUPLICATE, (lines[0], replace(lines[1], company="1200")), ("B1",))):
            with self.assertRaises(ValueError):
                Adjustment(category, rows, causes)
