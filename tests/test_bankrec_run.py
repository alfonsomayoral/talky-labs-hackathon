from collections import Counter
import json
import os
from pathlib import Path
import tempfile
import unittest

from kalmora.bankrec import Category, build_bank_rec, to_row
from kalmora.data import PhaseData
from bankrec_support import write_n43, write_twin

DD = [("01", "RECIBO ENERGIA PENINSULAR", "REF. MANDATO V100029-1100"), ("02", "FRA INV9", "")]


def entry(id, date, source, reference, lines):
    return {"id": id, "company": "1100", "posting_date": date, "document_date": date, "reference": reference,
            "source": source, "currency": "EUR", "lines": [dict(line=i + 1, currency="EUR", **x) for i, x in enumerate(lines)]}


def line(account, debit=0, credit=0, **extra):
    return dict(account=account, debit=debit, credit=credit, **extra)


class SyntheticPhase(unittest.TestCase):
    """Two accounts of company 1100, June and July, covering the main categories."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for area in ("erp", "tasks", "bank/BIN-1100", "bank/CMA-1100"):
            (self.root / area).mkdir(parents=True)
        (self.root / "tasks/close.json").write_text('{"month":"2026-07"}')
        (self.root / "tasks/bank_accounts.json").write_text('["BIN-1100","CMA-1100"]')
        accounts = [dict(id="BIN-1100", company="1100", gl_account="57200001", currency="EUR", statement_format="n43"),
                    dict(id="CMA-1100", company="1100", gl_account="57200002", currency="EUR", statement_format="n43")]
        (self.root / "erp/bank_accounts.jsonl").write_text("".join(json.dumps(a) + "\n" for a in accounts))
        for name in ("fx_rates", "factoring_assignments", "ar_invoices"):
            (self.root / f"erp/{name}.jsonl").write_text("")
        self.statement("BIN-1100", "2026-06", 1000, [("2026-06-30", -182, "", "", DD, "RECIBO ENERGIA PENINSULAR")])
        self.statement("BIN-1100", "2026-07", 818, [
            ("2026-07-02", -100, "", "", [], "TRANSFERENCIA A PROVEEDOR"),
            ("2026-07-07", 500, "", "", [], "TRANSFERENCIA DE CLIENTE SA"),
            ("2026-07-10", -3000, "", "", [], "COMISION MANTENIMIENTO CUENTA"),
            ("2026-07-31", -700, "", "", [], "ORDEN NOMINAS 07/2026")])
        self.statement("CMA-1100", "2026-06", 2000, [])
        self.statement("CMA-1100", "2026-07", 2000, [])
        self.write_journal([
            entry("1100-2026-1", "2026-05-31", "OPENING", "APERTURA", [line("57200001", 1000), line("10000000", credit=1000)]),
            entry("1100-2026-2", "2026-05-31", "OPENING", "APERTURA", [line("57200002", 2000), line("10000000", credit=2000)]),
            entry("1100-2026-3", "2026-07-02", "F110", "F110-1100-20260702-1", [line("40000000", 100, partner="V1"), line("57200001", credit=100)]),
            entry("1100-2026-4", "2026-07-15", "DD", "INV9", [line("41000000", 182, partner="V100029", assignment="INV9"), line("57200001", credit=182)]),
            entry("1100-2026-5", "2026-07-31", "MANUAL_PAYMENT", "URG07", [line("40700000", 55, partner="V2"), line("57200001", credit=55)]),
            entry("1100-2026-6", "2026-07-31", "PAYROLL", "NOM202607", [line("46500000", 700), line("57200002", credit=700)])])

    def statement(self, account, month, opening, moves):
        write_n43(self.root / f"bank/{account}/{month}.n43", opening, [m[:5] for m in moves])
        write_twin(self.root / f"bank/{account}/{month}.lines.jsonl", [
            {"bank_line": f"BL{account[:3]}{month[-2:]}{i}", "booking_date": m[0], "value_date": m[0], "amount": m[1],
             "currency": "EUR", "text": m[5]} for i, m in enumerate(moves)])

    def write_journal(self, entries):
        (self.root / "erp/journal_entries.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries))

    def run_july(self):
        run = build_bank_rec(PhaseData(self.root))
        return {r.account.id: r for r in run.results}, run


class EndToEndTests(SyntheticPhase):
    def test_july_view_of_each_account(self):
        results, run = self.run_july()
        self.assertEqual((len(results), run.unresolved), (2, ()))
        bin_ = results["BIN-1100"]
        self.assertEqual([m.book_lines for m in bin_.matches], [("1100-2026-3#2",)])
        self.assertEqual(Counter(u.category for u in bin_.unmatched_bank), Counter({
            Category.UNRECORDED_RECEIPT: 1, Category.BANK_FEE_NOT_BOOKED: 1, Category.WRONG_BANK_ACCOUNT: 1}))
        self.assertEqual({u.line_id: u.category for u in bin_.unmatched_book}, {
            "1100-2026-4#2": Category.PRIOR_PERIOD_BANK_ITEM, "1100-2026-5#2": Category.OUTSTANDING_PAYMENT})
        cma = results["CMA-1100"]
        self.assertEqual({u.line_id: u.category for u in cma.unmatched_book}, {"1100-2026-6#2": Category.WRONG_BANK_ACCOUNT})

    def test_adjustments_and_identities(self):
        results, _ = self.run_july()
        bin_ = results["BIN-1100"]
        self.assertEqual(sorted(a.category.value for a in bin_.adjustments),
                         ["BANK_FEE_NOT_BOOKED", "UNRECORDED_RECEIPT", "WRONG_BANK_ACCOUNT"])
        self.assertEqual([r.diagnostics for r in results.values()], [(), ()])
        self.assertEqual((bin_.statement_opening, bin_.statement_closing, bin_.book_balance), (818, -2482, 663))

    def test_row_follows_the_delivery_format(self):
        results, _ = self.run_july()
        row = to_row(results["BIN-1100"])
        self.assertEqual(set(row), {"account", "company", "matches", "unmatched_bank", "unmatched_book", "adjustments"})
        self.assertEqual(row["matches"], [{"bank_lines": ["BLBIN070"], "book_lines": ["1100-2026-3#2"]}])
        wrong = next(a for a in row["adjustments"] if a["category"] == "WRONG_BANK_ACCOUNT")
        self.assertEqual([(x["company"], x["account"], x["debit"], x["credit"]) for x in wrong["lines"]],
                         [("1100", "57200002", 700, 0), ("1100", "57200001", 0, 700)])
        json.dumps(row)

    def test_account_with_an_inconsistent_statement_is_unresolved_and_the_rest_continue(self):
        write_twin(self.root / "bank/CMA-1100/2026-07.lines.jsonl", [{"bank_line": "X", "booking_date": "2026-07-01",
                   "value_date": "2026-07-01", "amount": 5, "currency": "EUR", "text": "?"}])
        results, run = self.run_july()
        self.assertEqual([u.account for u in run.unresolved], ["CMA-1100"])
        self.assertIn("BIN-1100", results)

    def test_text_no_rule_recognises_is_reported_and_left_out(self):
        self.statement("BIN-1100", "2026-07", 818, [("2026-07-02", -100, "", "", [], "TRANSFERENCIA A PROVEEDOR"),
                                                    ("2026-07-07", 500, "", "", [], "TRANSFERENCIA DE CLIENTE SA"),
                                                    ("2026-07-10", -3000, "", "", [], "COMISION MANTENIMIENTO CUENTA"),
                                                    ("2026-07-31", -700, "", "", [], "ORDEN NOMINAS 07/2026"),
                                                    ("2026-07-20", -9, "", "", [], "CONCEPTO RARO")])
        results, _ = self.run_july()
        self.assertTrue(any("CONCEPTO RARO" in d for d in results["BIN-1100"].diagnostics))
        self.assertNotIn("BLBIN074", [u.line_id for u in results["BIN-1100"].unmatched_bank])

    def test_earlier_month_is_reconciled_as_of_its_end(self):
        run = build_bank_rec(PhaseData(self.root), "2026-06")
        bin_ = {r.account.id: r for r in run.results}["BIN-1100"]
        self.assertEqual([(u.line_id, u.category) for u in bin_.unmatched_bank], [("BLBIN060", Category.DIRECT_DEBIT_NOT_BOOKED)])
        self.assertEqual(bin_.diagnostics, ())


REAL = Path(os.environ.get("KALMORA_PHASE_DEV", Path(__file__).resolve().parent.parent / "participant/phase_dev"))


@unittest.skipUnless((REAL / "bank").is_dir(), "development phase not available")
class DevelopmentPhaseTests(unittest.TestCase):
    """Structure reported by the milestone issues for July; no golden is read."""

    @classmethod
    def setUpClass(cls):
        cls.data = PhaseData(REAL)
        cls.result = build_bank_rec(cls.data)

    def test_all_accounts_resolve_without_unexplained_differences(self):
        self.assertEqual((len(self.result.results), self.result.unresolved), (12, ()))
        for result in self.result.results:
            self.assertEqual([d for d in result.diagnostics if d.startswith(("identity", "no rule"))], [], result.account.id)

    def test_milestone_reference_structure(self):
        results = self.result.results
        self.assertEqual(sum(len(r.matches) for r in results), 224)
        self.assertEqual(sum(len(r.unmatched_bank) for r in results), 61)
        self.assertEqual(sum(len(r.unmatched_book) for r in results), 9)
        shapes = Counter(m.shape.value for r in results for m in r.matches)
        self.assertEqual(shapes, Counter({"ONE_TO_ONE": 216, "ONE_TO_MANY": 7, "MANY_TO_ONE": 1}))
        self.assertEqual(sum(1 for r in results for m in r.matches if m.difference), 8)  # 5 FX + 1 loan + 2 factoring

    def test_categories_of_unmatched_lines(self):
        bank = Counter(u.category.value for r in self.result.results for u in r.unmatched_bank)
        self.assertEqual(bank, Counter({"BANK_FEE_NOT_BOOKED": 31, "DIRECT_DEBIT_NOT_BOOKED": 17, "RETURNED_DIRECT_DEBIT": 4,
                                        "INTEREST_NOT_BOOKED": 4, "CARD_SETTLEMENT_NOT_BOOKED": 1, "POOLING_NOT_BOOKED": 1,
                                        "UNRECORDED_RECEIPT": 1, "BANK_ERROR": 1, "WRONG_BANK_ACCOUNT": 1}))
        book = Counter(u.category.value for r in self.result.results for u in r.unmatched_book)
        self.assertEqual(book, Counter({"PRIOR_PERIOD_BANK_ITEM": 4, "BOOK_DUPLICATE": 1, "OUTSTANDING_PAYMENT": 1,
                                        "TRANSFER_IN_TRANSIT": 1, "FX_REVALUATION": 1, "WRONG_BANK_ACCOUNT": 1}))

    def test_reference_examples(self):
        by = {r.account.id: r for r in self.result.results}
        usd_fee = next(a for a in by["BANH-3100-USD"].adjustments if a.causes == ("BL0001840",))
        self.assertEqual([(x.account, x.debit, x.credit) for x in usd_fee.lines], [("62600000", 27713, 0), ("57200006", 0, 27713)])
        interest = next(a for a in by["CMA-1000"].adjustments if a.category is Category.INTEREST_NOT_BOOKED)
        self.assertEqual([(x.account, x.debit, x.credit) for x in interest.lines],
                         [("57200002", 326430, 0), ("47300000", 76570, 0), ("76200000", 0, 403000)])
        duplicate = next(a for a in by["BAE-1100"].adjustments if a.category is Category.BOOK_DUPLICATE)
        self.assertEqual(sorted((x.account, x.debit, x.credit, x.partner) for x in duplicate.lines),
                         [("40000000", 0, 2265829, "V100078"), ("40000000", 0, 3004872, "V100009"),
                          ("40000000", 0, 12504802, "V100004"), ("57200003", 17775503, 0, None)])

    def test_each_month_closes_its_prior_period_items_in_the_next(self):
        previous = None
        for month in ("2026-04", "2026-05", "2026-06", "2026-07"):
            run = build_bank_rec(self.data, month)
            self.assertEqual([d for r in run.results for d in r.diagnostics if d.startswith(("identity", "no rule"))], [], month)
            prior = sum(1 for r in run.results for u in r.unmatched_book if u.category is Category.PRIOR_PERIOD_BANK_ITEM)
            debits = sum(1 for r in run.results for u in r.unmatched_bank if u.category is Category.DIRECT_DEBIT_NOT_BOOKED)
            if previous is not None:
                self.assertEqual(prior, previous, month)
            previous = debits if month != "2026-07" else None

    def test_every_adjustment_balances_and_names_its_company(self):
        for r in self.result.results:
            for a in r.adjustments:
                self.assertEqual(sum(x.debit for x in a.lines), sum(x.credit for x in a.lines))
                self.assertEqual({x.company for x in a.lines}, {r.account.company})

    def test_rows_serialise(self):
        rows = [to_row(r) for r in self.result.results]
        self.assertEqual([row["account"] for row in rows], self.data.table("tasks/bank_accounts"))
        json.dumps(rows)


if __name__ == "__main__":
    unittest.main()
