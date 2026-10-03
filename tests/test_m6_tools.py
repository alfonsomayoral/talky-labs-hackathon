"""M6 negative paths and adapter/evaluation boundary tests; invented data only."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from test_m6_close import (EV, D, engine, facts, handoff, journal, l, posting, prepaid, service)
from kalmora.close.contracts import digest, file_hash

TOOLS = Path(__file__).resolve().parents[1] / 'tools'


def tool(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReviewTests(unittest.TestCase):
    def test_mutated_handoff_rejected_at_engine_boundary(self):
        h = handoff()
        h.payload['facts']['prepaids'].append(prepaid())
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            engine(h=h)

    def test_zero_prepaid_rejected(self):
        with self.assertRaisesRegex(ValueError, 'positive original cost'):
            engine(f=facts(prepaids=[prepaid(total=0)])).run()

    def test_zero_pending_certificate_does_not_divide(self):
        cert = {'billing_item': 'empty', 'company': '1000', 'customer': 'C-test', 'project': 'OB-test',
                'billing_status': 'SKIP_PENDING_APPROVAL', 'evidence': EV,
                'certification': {'month': '2026-07', 'cumulative': 100, 'previous': 100, 'current': 0,
                                 'approved': False, 'chapters': [{'number': 1, 'description': 'zero', 'amount': 0}]}}
        self.assertFalse(engine(f=facts(pending_certifications=[cert])).run().rows)

    def test_collections_before_bad_debt(self):
        original = journal([l('43000000', 1000, partner='C-test', assignment='invoice'), l('10000000', -1000)])
        collection = journal([l('43000000', -600, partner='C-test', assignment='invoice'), l('57200000', 600)],
                             when='2026-07-10', id='receipt', reference='receipt')
        result = engine([original], h=handoff(postings=[posting(collection, stage='cash.apply')]),
                        customers=[{'id': 'C-test', 'kind': 'private'}],
                        invoices=[{'id': 'invoice', 'company': '1000', 'due_date': '2025-12-31'}]).run()
        self.assertEqual(result.rows[0]['amount'], 200)

    def test_fully_collected_provision_is_released(self):
        original = journal([l('43000000', 1000, partner='C-test', assignment='invoice'),
                            l('49000000', -500, partner='C-test'), l('10000000', -500)])
        collection = journal([l('43000000', -1000, partner='C-test', assignment='invoice'), l('57200000', 1000)],
                             when='2026-07-10', id='receipt', reference='receipt')
        result = engine([original], h=handoff(postings=[posting(collection, stage='cash.apply')]),
                        customers=[{'id': 'C-test', 'kind': 'private'}]).run()
        self.assertEqual(result.rows[0]['amount'], -500)
        self.assertEqual(result.rows[0]['journal_entry']['lines'][0]['account'], '79400000')

    def test_half_cent_mode_explicit(self):
        original = journal([l('43000000', 101, partner='C-test', assignment='invoice'), l('10000000', -101)])
        result = engine([original], f=facts(impairment_rounding='half_up'),
                        customers=[{'id': 'C-test', 'kind': 'private'}],
                        invoices=[{'id': 'invoice', 'company': '1000', 'due_date': '2025-12-31'}]).run()
        self.assertEqual(result.rows[0]['amount'], 51)

    def test_foreign_credit_position_is_not_dropped(self):
        original = journal([l('41000000', 600, partner='V-test', assignment='credit'), l('10000000', -600)])
        f = facts(fx_positions=[{'company': '1000', 'account': '41000000', 'partner': 'V-test',
            'assignment': 'credit', 'item': 'AP:credit', 'currency': 'USD', 'document_signed': 1000, 'evidence': EV}])
        result = engine([original], f=f, rates=[{'currency': 'USD', 'date': '2026-07-31', 'rate': '2'}]).run()
        self.assertEqual(result.rows[0]['amount'], -100)
        self.assertEqual(result.rows[0]['journal_entry']['lines'][0]['credit'], 100)
        self.assertEqual(result.rows[0]['journal_entry']['lines'][1]['account'], '66800000')

    def test_nonfinite_payload_rejected(self):
        with self.assertRaises(ValueError):
            digest({'amount': float('nan')})


class ToolBoundaryTests(unittest.TestCase):
    def test_fixture_allowlist_rejects_targets_before_io(self):
        adapter = tool('m6_fixture')
        for name in ('close', 'trial_balance_truth', '../close'):
            with self.assertRaises(ValueError):
                adapter.load_upstream(Path('/does-not-exist'), name)

    def test_explicit_period_parser(self):
        parser = tool('m6_sources')
        self.assertEqual(parser.period('01/07/2026–31/07/2026')[:2], (D.replace(day=1), D))
        span = parser.period('20/12–10/01/2026')
        self.assertEqual(span[0].isoformat(), '2025-12-20')
        self.assertIsNone(parser.period('issued July; period unknown'))

    def test_evaluation_rejects_mutated_freeze_before_targets(self):
        evaluator = tool('m6_evaluate')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'output'; out.mkdir()
            (out / 'close.jsonl').write_text('frozen\n')
            (out / 'freeze.json').write_text(json.dumps({'frozen_before_evaluation': True,
                'files': {'close.jsonl': file_hash(out / 'close.jsonl')}}))
            (out / 'close.jsonl').write_text('tampered\n')
            with self.assertRaisesRegex(ValueError, 'frozen output changed'):
                evaluator.evaluate(Path(tmp) / 'missing-targets', out, Path(tmp) / 'evaluation')

    def test_no_target_import_in_close_package(self):
        from kalmora.evaluation.boundary import check_boundary
        report = check_boundary(Path(__file__).resolve().parents[1] / 'src/kalmora/close')
        self.assertFalse(report['violations'])


if __name__ == '__main__':
    unittest.main()
