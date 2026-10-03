from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path
import unittest

from kalmora.ar_cash import build_ar_cash, journal_entries
from kalmora.ar_cash.projection import project_cash
from kalmora.bankrec import build_bank_rec
from kalmora.data import PhaseData
from kalmora.ledger import Ledger
import test_ar_cash as fixtures


class ProjectionTests(unittest.TestCase):
    setUp = fixtures.ArCashTests.setUp
    _json = fixtures.ArCashTests._json
    _jsonl = fixtures.ArCashTests._jsonl
    _run = fixtures.ArCashTests._run
    invoice = staticmethod(fixtures.ArCashTests.invoice)
    line = staticmethod(fixtures.ArCashTests.line)
    entry = fixtures.ArCashTests.entry
    def test_partial_projection_preserves_recorded_and_remaining_balance(self):
        data = PhaseData(self.phase)
        recorded = Ledger.from_entries(data.iter_journal())
        projected = recorded.project()
        entry, = journal_entries(data, self._run())
        projected.add_entry(entry, **entry['provenance'])
        self.assertEqual(recorded.balances()[('1100', '43000000')], 10000)
        self.assertEqual(projected.open_items()[('1100', '43000000', 'C1', 'INV-1')], 2000)
        self.assertEqual(projected.balances()[('1100', '55500000')], 0)
        self.assertEqual(projected.balances()[('1100', '57200001')], 8000)
        with self.assertRaises(ValueError):
            projected.add_entry(entry, **entry['provenance'])

    def test_journal_rejects_duplicate_owners_and_noninteger_money(self):
        data = PhaseData(self.phase)
        run = self._run()
        with self.assertRaises(ValueError):
            journal_entries(data, replace(run, results=run.results * 2))
        row = deepcopy(run.results[0].row)
        row['adjustment'][0]['debit'] = 8000.0
        with self.assertRaises(TypeError):
            journal_entries(data, replace(run, results=(replace(run.results[0], row=row),)))

    def test_missing_task_result_cannot_be_published_as_complete(self):
        with self.assertRaisesRegex(ValueError, "exactly one result"):
            project_cash(PhaseData(self.phase), replace(self._run(), results=()), None)

    def test_journal_preserves_notes_advances_factoring_and_guarantees(self):
        data = PhaseData(self.phase)
        run = self._run()
        for account, assignment in [('43100000', 'PAG123'), ('43800000', 'INV-1'),
                                    ('55300000', 'INV-1'), ('56500000', None)]:
            with self.subTest(account=account):
                row = deepcopy(run.results[0].row)
                row['adjustment'][1].update(account=account, assignment=assignment)
                entry, = journal_entries(data, replace(run, results=(replace(run.results[0], row=row),)))
                ledger = Ledger.from_entries([entry])
                self.assertEqual(ledger.balances()[('1100', account)], -8000)
                if account != '56500000':
                    self.assertEqual(ledger.open_items()[('1100', account, 'C1', assignment)], -8000)

    def test_foreign_currency_is_not_silently_published_as_local(self):
        run = self._run()
        self._jsonl('erp/bank_accounts.jsonl', [{'id':'BIN-1100', 'company':'1100',
                                               'currency':'USD', 'gl_account':'57200001'}])
        with self.assertRaises(ValueError):
            journal_entries(PhaseData(self.phase), run)


REAL = Path(os.environ.get('KALMORA_PHASE_DEV', '/nonexistent'))

@unittest.skipUnless(REAL.is_dir(), 'development source package unavailable')
class RealProjectionTests(unittest.TestCase):
    def test_real_projection_preserves_history_and_separates_import_application(self):
        data = PhaseData(REAL)
        cash = build_ar_cash(data, use_preparsed=True, normalized_dir=REAL.parent/'normalized_sources')
        projection = project_cash(data, cash, build_bank_rec(data))
        self.assertFalse(projection.complete)
        self.assertEqual(set(projection.unresolved),
                         {'BL0000201','BL0000276','BL0000544','BL0000567','BL0000707'})
        self.assertEqual(projection.recorded.entries, Ledger.from_entries(data.iter_journal()).entries)
        additions = projection.projected.entries[len(projection.recorded.entries):]
        receipt = [e for e in additions if e['provenance']['event_id'] == 'BL0000706']
        self.assertEqual({e['provenance']['stage'] for e in receipt}, {'bank_import','cash_application'})
        self.assertEqual(sum(l['debit']-l['credit'] for e in receipt for l in e['lines']
                             if l['account']=='55500000'), 0)
        self.assertEqual(sum(l['debit']-l['credit'] for e in receipt for l in e['lines']
                             if l['account']=='57200001'), 51496121)
        restored = Ledger.from_entries(projection.projected.entries)
        for entry in additions:
            with self.assertRaises(ValueError):
                restored.add_entry(entry, **entry['provenance'])
        self.assertEqual(sum(projection.projected.balances().values()),
                         sum(projection.recorded.balances().values()))
