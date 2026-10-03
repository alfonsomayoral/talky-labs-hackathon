"""Evaluation-only synthetic checks; no golden is read or imported here."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools.m5_evaluate import required_field_audit
from tools.m5_prepare_inputs import prepare


def fixture():
    return {"pair": ["A", "B"], "cause": "WRONG_TRADING_PARTNER", "amount": -17,
            "responsible": "B", "adjustment": [
                {"company": "B", "account": "552", "debit": 17, "credit": 0, "partner": "A"},
                {"company": "B", "account": "552", "debit": 0, "credit": 17, "partner": "C"}]}


class EvaluationTests(unittest.TestCase):
    def audit(self, row):
        return required_field_audit([fixture()], [row])

    def test_signed_cents_exact(self):
        result = self.audit(fixture())
        self.assertTrue(result['all_required_fields_exact'])
        self.assertEqual(result['required_plus_reference_line_fields_exact_rows'], 1)

    def test_amount_sign_is_not_ignored(self):
        row = fixture(); row['amount'] *= -1
        result = self.audit(row)
        self.assertFalse(result['all_required_fields_exact'])
        self.assertEqual(result['rows'][0]['amount_delta_cents'], 34)
        self.assertTrue(result['rows'][0]['checks']['adjustment_required_fields'])

    def test_responsible_is_compared_even_if_valid_pair_member(self):
        row = fixture(); row['responsible'] = 'A'
        self.assertFalse(self.audit(row)['rows'][0]['checks']['responsible'])

    def test_pair_order_not_silently_normalized(self):
        row = fixture(); row['pair'].reverse()
        result = self.audit(row)
        self.assertEqual(result['matched_keys'], 1)
        self.assertFalse(result['rows'][0]['checks']['pair'])

    def test_company_and_cost_objects_are_compared(self):
        for field, value in [('company', 'A'), ('cost_center', 'different'), ('wbs', 'project')]:
            with self.subTest(field=field):
                row = fixture(); row['adjustment'][0][field] = value
                self.assertFalse(self.audit(row)['rows'][0]['checks']['adjustment_required_fields'])

    def test_additional_assignment_gap_is_not_hidden(self):
        reference = fixture(); reference['adjustment'][0]['assignment'] = 'LOAN-X'
        result = required_field_audit([reference], [fixture()])
        self.assertEqual(result['required_fields_exact_rows'], 1)
        self.assertEqual(result['required_plus_reference_line_fields_exact_rows'], 0)
        self.assertEqual(result['rows'][0]['additional_reference_line_fields'][0]['field'], 'assignment')

    def test_duplicate_rows_fail(self):
        result = required_field_audit([fixture()], [fixture(), fixture()])
        self.assertFalse(result['all_required_fields_exact'])
        self.assertEqual(result['duplicate_submission_keys'][0]['rows'], 2)

    def test_missing_and_unexpected_rows(self):
        row = fixture(); row['cause'] = 'INTEREST_DAY_COUNT'
        result = self.audit(row)
        self.assertEqual(result['rows'][0]['status'], 'missing')
        self.assertEqual(len(result['unexpected_rows']), 1)

    def test_bool_amount_fails_integer_contract(self):
        row = fixture(); row['amount'] = True
        self.assertFalse(self.audit(row)['all_required_fields_exact'])

    def test_pooling_cannot_emit_second_journal(self):
        reference = fixture(); reference['cause'] = 'POOLING_NOT_BOOKED'; reference['adjustment'] = []
        row = deepcopy(reference); row['adjustment'] = fixture()['adjustment']
        result = required_field_audit([reference], [row])
        self.assertTrue(any('pooling' in error.get('error', '') for error in result['structural_errors']))

    def test_malformed_pair_and_lines_are_reported(self):
        for field, value in [('pair', None), ('pair', [['A'], 'B']), ('cause', []),
                             ('adjustment', None), ('adjustment', [None])]:
            with self.subTest(field=field, value=value):
                row = fixture(); row[field] = value
                result = self.audit(row)
                self.assertFalse(result['all_required_fields_exact'])
                self.assertTrue(result['structural_errors'])
        self.assertFalse(required_field_audit([fixture()], [None])['all_required_fields_exact'])


class PreparationTests(unittest.TestCase):
    def test_reference_bytes_never_opened_and_original_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); archive = root / 'participant.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('participant/phase_dev/tasks/close.json', '{"month":"2030-02"}')
                z.writestr('participant/phase_dev/golden/ic.jsonl', 'DO NOT READ')
                z.writestr('participant/score.py', 'DO NOT READ')
            before = archive.read_bytes(); opened = []
            original = zipfile.ZipFile.open
            def guarded(obj, name, *args, **kwargs):
                path = name.filename if isinstance(name, zipfile.ZipInfo) else name
                opened.append(path)
                if '/golden/' in path or path.endswith('/score.py'):
                    self.fail('Preparation opened reference bytes')
                return original(obj, name, *args, **kwargs)
            with patch.object(zipfile.ZipFile, 'open', guarded):
                manifest = prepare(archive, root / 'inputs')
            self.assertEqual(archive.read_bytes(), before)
            self.assertEqual(manifest['archive_sha256'], hashlib.sha256(before).hexdigest())
            self.assertEqual(len(opened), 1)
            self.assertFalse((root / 'inputs/participant/phase_dev/golden').exists())

    def test_refuses_overwrite_and_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); archive = root / 'participant.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('participant/../../escape', 'bad')
            with self.assertRaises(ValueError):
                prepare(archive, root / 'inputs')
            self.assertFalse((root / 'inputs').exists())
            with self.assertRaises(FileExistsError):
                prepare(archive, root)
