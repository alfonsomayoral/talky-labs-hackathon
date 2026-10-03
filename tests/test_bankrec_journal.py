from dataclasses import replace
import os
from pathlib import Path
import unittest
from kalmora.bankrec import build_bank_rec, journal_entries
from kalmora.data import PhaseData
from kalmora.ledger import Ledger
from kalmora.validation import validate_entry
from test_bankrec_run import SyntheticPhase

REAL = Path(os.environ.get("KALMORA_PHASE_DEV", Path(__file__).resolve().parents[1] / "participant/phase_dev"))


class JournalTests(SyntheticPhase):
    def test_exposes_valid_entries_with_explicit_company_and_stable_owner(self):
        _, run = self.run_july()
        entries = journal_entries(run)
        self.assertTrue(entries)
        for entry in entries:
            self.assertEqual(validate_entry(entry), [])
            self.assertEqual({x["company"] for x in entry["lines"]}, {entry["company"]})
        self.assertEqual(entries, journal_entries(run))
        ledger = Ledger.from_entries(entries)
        for entry in entries:
            with self.assertRaises(ValueError):
                ledger.add_entry(entry, **entry["provenance"])

    def test_receipt_import_and_cash_application_are_distinct_without_second_bank_leg(self):
        _, run = self.run_july()
        imported = next(e for e in journal_entries(run) if e["provenance"]["stage"] == "bank_import")
        ledger = Ledger.from_entries([imported])
        amount = next(x["credit"] for x in imported["lines"] if x["account"] == "55500000")
        before = ledger.balances()[("1100", "57200001")]
        application = dict(company="1100", lines=[dict(account="55500000", debit=amount, credit=0),
                                                   dict(account="43000000", debit=0, credit=amount, partner="C1", assignment="INV1")])
        ledger.add_entry(application, event_id=imported["provenance"]["event_id"], stage="cash_application")
        self.assertEqual(ledger.balances()[("1100", "55500000")], 0)
        self.assertEqual(ledger.balances()[("1100", "57200001")], before)
        with self.assertRaises(ValueError):
            ledger.add_entry(application, event_id=imported["provenance"]["event_id"], stage="cash_application")

    def test_unresolved_and_diagnostics_cannot_enter_close_projection(self):
        _, run = self.run_july()
        bad = replace(run, results=(replace(run.results[0], diagnostics=("identity: mismatch",)),))
        with self.assertRaises(ValueError):
            journal_entries(bad)


@unittest.skipUnless((REAL / "bank").is_dir(), "development source package unavailable")
class JulyJournalTests(unittest.TestCase):
    def test_book_references_preserve_original_entry_and_line_numbers(self):
        data = PhaseData(REAL)
        originals = {f"{e['id']}#{x['line']}" for e in data.iter_journal() for x in e["lines"]}
        run = build_bank_rec(data)
        for result in run.results:
            refs = {key for m in result.matches for key in m.book_lines} | {u.line_id for u in result.unmatched_book}
            self.assertTrue(refs <= originals, result.account.id)

    def test_all_adjustments_and_bl0000706_are_available_to_close_once(self):
        run = build_bank_rec(PhaseData(REAL))
        entries = journal_entries(run)
        self.assertEqual(len(entries), 59)
        self.assertEqual(len({tuple(e["provenance"].values()) for e in entries}), 59)
        receipt = next(e for e in entries if e["provenance"]["event_id"] == "BL0000706")
        self.assertEqual(receipt["provenance"]["stage"], "bank_import")
        self.assertEqual({x["account"] for x in receipt["lines"]}, {"57200001", "55500000"})
        pooling = [e for e in entries if e["header_text"] == "POOLING_NOT_BOOKED"]
        self.assertEqual(len(pooling), 1)
        self.assertEqual(pooling[0]["provenance"]["stage"], "bank_rec")
        ledger = Ledger.from_entries(entries)
        with self.assertRaises(ValueError):
            ledger.add_entry(pooling[0], **pooling[0]["provenance"])
