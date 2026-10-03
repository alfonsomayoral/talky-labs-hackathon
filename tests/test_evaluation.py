import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from kalmora.cli import main
from kalmora.evaluation.diagnostics import check_submission
from kalmora.evaluation.compare import compare_ar_cash
from kalmora.evaluation.report import _load_rows, evaluate
from kalmora.evaluation.scorer import load_scorer
from kalmora.evaluation.structure import check_structure
from kalmora.package import register_package


class EvaluationFormatTests(unittest.TestCase):
    @staticmethod
    def ar_cash_scorer(score):
        def score_ar_cash(gold, submission):
            return (score,)

        def je_lines(entry, company=None):
            lines = entry.get("lines", entry) if isinstance(entry, dict) else entry
            return [(line.get("company") or company, str(line["account"]),
                     int(line.get("debit") or 0) - int(line.get("credit") or 0),
                     line.get("partner"), line.get("cost_center"), line.get("wbs"))
                    for line in lines
                    if int(line.get("debit") or 0) != int(line.get("credit") or 0)]

        return SimpleNamespace(score_ar_cash=score_ar_cash, je_lines=je_lines,
                               norm_line=lambda account, amount, partner, cc, wbs:
                               (account, amount, partner, cc, wbs))

    @staticmethod
    def cash_row(*, invoice="INV1", customer="C1", app_amount=100,
                 residual_invoice="INV1", cash_amount=90):
        return {"bank_line": "BL1", "company": "1100", "customer": customer,
                "applications": [{"invoice": invoice, "amount": app_amount}],
                "residuals": [{"type": "PENALTY", "invoice": residual_invoice,
                               "amount": 10}],
                "adjustment": [
                    {"company": "1100", "account": "55500000", "debit": cash_amount, "credit": 0},
                    {"company": "1100", "account": "70590000", "debit": 10, "credit": 0},
                    {"company": "1100", "account": "43000000", "debit": 0,
                     "credit": app_amount, "partner": "C1", "assignment": "INV1"},
                ]}

    def test_ar_cash_comparator_reports_unscored_residual_invoice(self):
        gold = [self.cash_row()]
        submission = [self.cash_row(residual_invoice="INV2")]
        result = compare_ar_cash(self.ar_cash_scorer(1.0), gold, submission)
        entity = result["entities"][0]
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(entity["diffs"], [])
        self.assertEqual(entity["unscored"], [{
            "field": "residuals.invoice", "expected": [("PENALTY", "INV1", 10)],
            "actual": [("PENALTY", "INV2", 10)], "kind": "unscored",
        }])

    def test_residual_invoice_amount_binding_survives_swapped_assignments(self):
        from copy import deepcopy
        gold = self.cash_row()
        gold['residuals'] = [dict(type='PENALTY', invoice='INV1', amount=10),
                             dict(type='PENALTY', invoice='INV2', amount=20)]
        submission = deepcopy(gold)
        submission['residuals'][0]['invoice'] = 'INV2'
        submission['residuals'][1]['invoice'] = 'INV1'
        result = compare_ar_cash(self.ar_cash_scorer(1.0), [gold], [submission])
        self.assertEqual(result['entities'][0]['diffs'], [])
        self.assertEqual(result['entities'][0]['unscored'][0]['field'], 'residuals.invoice')

    @unittest.skipUnless(os.environ.get('KALMORA_SCORER'), 'official scorer path unavailable')
    def test_official_scorer_ignores_residual_invoice_but_comparator_exposes_it(self):
        scorer, _ = load_scorer(Path(os.environ['KALMORA_SCORER']))
        result = compare_ar_cash(scorer, [self.cash_row()], [self.cash_row(residual_invoice='INV2')])
        self.assertEqual(result['score'], 1.0)
        self.assertTrue(result['reconciliation']['ok'])
        self.assertEqual(result['entities'][0]['unscored'][0]['field'], 'residuals.invoice')
        gold = self.cash_row()
        gold['applications'] = [{'pagare': '123', 'amount': 100}]
        result = compare_ar_cash(scorer, [gold], [self.cash_row()])
        self.assertIn('applications', {d['field'] for d in result['entities'][0]['diffs']})
        self.assertLess(result['score'], 1.0)

    def test_ar_cash_comparator_reports_application_customer_and_entry_differences(self):
        gold = [self.cash_row(invoice="PAG123")]
        submission = [self.cash_row(invoice="INV2", customer="C2", app_amount=90,
                                   cash_amount=80)]
        result = compare_ar_cash(self.ar_cash_scorer(0.5), gold, submission)
        fields = {item["field"] for item in result["entities"][0]["diffs"]}
        self.assertEqual(fields, {"customer", "applications", "adjustment.lines"})
        self.assertTrue(result["reconciliation"]["ok"])

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

    def test_reused_identifier_does_not_exempt_an_unbalanced_entry(self):
        row = {"doc_id": "API004469", "journal_entry": {"company": "1100", "lines": [
            {"account": "40700000", "debit": 100, "credit": 0},
            {"account": "57200001", "debit": 0, "credit": 99}]}}
        errors = check_submission({"ap": [row]}, "2026-09", {"ap": {"API004469"}})
        self.assertTrue(any(item["code"] == "ENTRY_RULE" and "partner" in item["message"] for item in errors))
        self.assertTrue(any(item["code"] == "ENTRY_RULE" and "unbalanced" in item["message"] for item in errors))
        self.assertTrue(all(item["code"] != "KNOWN_EXCEPTION" for item in errors))

    def test_partner_detection_is_independent_of_identifier_month_and_line_position(self):
        for ident, month in (("NEW-1", "2026-07"), ("NEW-2", "2026-09"), ("NEW-3", "2027-02")):
            for lines in ([{"account": "40700000", "debit": 100, "credit": 0},
                           {"account": "57200001", "debit": 0, "credit": 100}],
                          [{"account": "57200001", "debit": 0, "credit": 100},
                           {"account": "40700000", "debit": 100, "credit": 0}]):
                with self.subTest(ident=ident, month=month, lines=lines):
                    row = {"doc_id": ident, "journal_entry": {"company": "1100", "lines": lines}}
                    errors = check_submission({"ap": [row]}, month, {"ap": {ident}})
                    self.assertEqual([item["code"] for item in errors], ["ENTRY_RULE"])
                    self.assertIn("partner", errors[0]["message"])

    def test_reference_defect_is_detected_from_content_even_without_submitted_row(self):
        reference = {"doc_id": "UNSEEN-REF", "journal_entry": {"company": "1100", "lines": [
            {"account": "40700000", "debit": 100, "credit": 0},
            {"account": "40000000", "debit": 0, "credit": 100, "partner": "V9"}]}}
        ids = {"ap": {"UNSEEN-REF"}}
        for subs in ({"ap": []}, {"ap": [reference]}):
            errors = check_submission(subs, "2026-09", ids, {"ap": [reference]})
            ref_errors = [item for item in errors if item["code"] == "REFERENCE_ENTRY_RULE"]
            self.assertEqual(len(ref_errors), 1)
            self.assertEqual(ref_errors[0]["entity"], "UNSEEN-REF")
            self.assertIn("partner", ref_errors[0]["message"])
            if subs["ap"]:
                self.assertTrue(any(item["code"] == "ENTRY_RULE" for item in errors))

    def test_correct_submission_keeps_reference_problem_separate(self):
        reference = {"doc_id": "ARBITRARY", "journal_entry": {"company": "1100", "lines": [
            {"account": "40700000", "debit": 100, "credit": 0},
            {"account": "40000000", "debit": 0, "credit": 100, "partner": "V9"}]}}
        corrected = json.loads(json.dumps(reference))
        corrected["journal_entry"]["lines"][0]["partner"] = "V9"
        ids = {"ap": {"ARBITRARY"}}
        errors = check_submission({"ap": [corrected]}, "2026-09", ids, {"ap": [reference]})
        self.assertEqual([item["code"] for item in errors], ["REFERENCE_ENTRY_RULE"])
        self.assertEqual(check_submission({"ap": [corrected]}, "2026-09", ids), [])
        errors = check_submission({"ap": [reference]}, "2026-09", ids, {"ap": [corrected]})
        self.assertEqual([item["code"] for item in errors], ["ENTRY_RULE"])

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
            self.assertEqual(golden['diagnostic_counts'].get('REFERENCE_ENTRY_RULE'), 1)
            self.assertEqual(golden['diagnostic_counts'].get('ENTRY_RULE'), 1)
            self.assertNotIn('KNOWN_EXCEPTION', golden['diagnostic_counts'])
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
