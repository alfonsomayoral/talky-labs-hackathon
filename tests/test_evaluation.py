import json
import os
from pathlib import Path
import tempfile
import unittest

from kalmora.cli import main
from kalmora.evaluation.diagnostics import check_submission
from kalmora.evaluation.report import _load_rows, evaluate
from kalmora.evaluation.scorer import load_scorer
from kalmora.evaluation.structure import check_structure
from kalmora.package import register_package


class EvaluationFormatTests(unittest.TestCase):
    def test_invalid_enum_and_malformed_entry_are_diagnostics(self):
        row = {"doc_id": "API1", "document_type": "INVOICE", "decision": "INVALID", "reasons": []}
        errors = check_structure({"ap": [row]})
        self.assertTrue(any("decision" in error["message"] for error in errors))
        row.update(decision="POST", journal_entry={"company": "1100", "lines": None})
        errors = check_structure({"ap": [row]})
        self.assertTrue(any("lines" in error["message"] for error in errors))

    def test_nested_cents_and_explicit_adjustment_company(self):
        row = {"bank_line": "BL1", "customer": None,
               "applications": [{"invoice": "INV1", "amount": True}], "residuals": [],
               "adjustment": [{"account": "57200001", "debit": 1, "credit": 0}]}
        errors = check_structure({"ar_cash": [row]})
        self.assertTrue(any("amount" in error["message"] for error in errors))
        row["applications"][0]["amount"] = 1
        errors = check_structure({"ar_cash": [row]})
        self.assertTrue(any("explicit company" in error["message"] for error in errors))
        row["adjustment"][0]["company"] = "1100"
        self.assertEqual(check_structure({"ar_cash": [row]}), [])

    def test_conditional_fields_and_valid_non_invoice(self):
        row = {"doc_id": "API1", "document_type": "PROFORMA", "decision": "NOT_INVOICE",
               "reasons": [], "invoice_number": None, "action": "NONE"}
        self.assertEqual(check_structure({"ap": [row]}), [])
        row["journal_entry"] = {"company": "1100", "lines": []}
        self.assertTrue(check_structure({"ap": [row]}))
        self.assertTrue(check_structure({"ar_billing": [{"billing_item": "B1", "expected": "INVOICE"}]}))
        self.assertTrue(check_structure({"close": [{"type": "FX_REVAL", "company": "1100", "amount": 1,
                                                   "journal_entry": {"company": "1100", "lines": []}}]}))

    def test_jsonl_error_names_file_and_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ap.jsonl"
            path.write_text('\n[]\n')
            with self.assertRaisesRegex(ValueError, r"ap.jsonl:2: JSONL row must be an object"):
                _load_rows(path)

    def test_structure_cli_rejects_bad_enum_and_preserves_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            phase = root / "phase"; (phase / "tasks").mkdir(parents=True)
            (phase / "tasks/close.json").write_text('{"month":"2026-07"}')
            (phase / "erp").mkdir()
            (phase / "erp/journal_entries.jsonl").write_text('')
            submission = root / "submission"; submission.mkdir()
            (submission / "ap.jsonl").write_text(json.dumps({"doc_id": "API1", "document_type": "INVOICE",
                                                           "decision": "INVALID", "reasons": []}) + '\n')
            reports = root / "reports"
            result = main(["--run-dir", str(root / "runs"), "evaluate", str(phase), str(submission),
                           "--structure-only", "--report-dir", str(reports)])
            self.assertEqual(result, 1)
            report = json.loads(next(reports.glob('*.json')).read_text())
            self.assertIn("INVALID_STRUCTURE", report["diagnostic_counts"])
            self.assertNotIn("headline", report)

    def test_requested_manifest_is_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); scorer = root / 'score.py'
            scorer.write_text('raise RuntimeError("must not execute")')
            with self.assertRaisesRegex(FileNotFoundError, 'Package manifest not found'):
                load_scorer(scorer, root / 'manifest.json')
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'files': [{'path': 'participant/score.py', 'sha256': 'wrong'}]}))
            with self.assertRaisesRegex(ValueError, 'does not match manifest'):
                load_scorer(scorer, manifest)

    def test_known_exception_does_not_hide_an_unbalanced_entry(self):
        row = {"doc_id": "API004469", "journal_entry": {"company": "1100", "lines": [
            {"account": "40700000", "debit": 100, "credit": 0},
            {"account": "57200001", "debit": 0, "credit": 99}]}}
        errors = check_submission({"ap": [row]}, "2026-07", {"ap": {"API004469"}})
        self.assertTrue(any(item["code"] == "KNOWN_EXCEPTION" for item in errors))
        self.assertTrue(any(item["code"] == "ENTRY_RULE" and "unbalanced" in item["message"] for item in errors))

    def test_golden_from_another_month_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, month in (("solver", "2026-09"), ("evaluator", "2026-07")):
                phase = root / name
                (phase / "tasks").mkdir(parents=True)
                (phase / "tasks/close.json").write_text(json.dumps({"month": month}))
                (phase / "erp").mkdir()
                (phase / "erp/journal_entries.jsonl").write_text('')
            (root / "evaluator/golden").mkdir()
            (root / "submission").mkdir()
            with self.assertRaisesRegex(ValueError, 'Evaluator month does not match'):
                evaluate(root / "solver", root / "submission", root / "evaluator")


@unittest.skipUnless(os.environ.get('KALMORA_PARTICIPANT_ZIP'), 'set KALMORA_PARTICIPANT_ZIP for organizer evaluation')
class OrganizerComparatorTests(unittest.TestCase):
    def test_official_ceiling_floor_partial_and_wrong_company(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            register_package(Path(os.environ['KALMORA_PARTICIPANT_ZIP']), root / 'package')
            phase = root / 'package/participant/phase_dev'
            golden = evaluate(phase, phase / 'golden', phase)
            self.assertEqual(golden['headline']['total'], 100.0)
            self.assertTrue(golden['reconciliation_ok'])
            self.assertEqual(golden['separation']['violations'], [])
            empty = root / 'empty'; empty.mkdir()
            floor = evaluate(phase, empty, phase)
            self.assertEqual(floor['headline']['total'], 3.54)
            self.assertTrue(floor['reconciliation_ok'])
            partial = root / 'partial'; partial.mkdir()
            rows = _load_rows(phase / 'golden/ap.jsonl')
            (partial / 'ap.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            result = evaluate(phase, partial, phase)
            self.assertEqual(result['headline']['total'], 36.38)
            self.assertTrue(result['reconciliation_ok'])
            posted = next(row for row in rows if row.get('journal_entry'))
            posted['journal_entry']['company'] = '3100' if posted['company'] != '3100' else '1100'
            (partial / 'ap.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            result = evaluate(phase, partial, phase)
            self.assertIn('COMPANY_MISMATCH', result['diagnostic_counts'])
            self.assertTrue(result['reconciliation_ok'])
