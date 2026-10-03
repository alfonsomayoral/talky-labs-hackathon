import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from kalmora.cli import main


class CliTests(unittest.TestCase):
    def test_failed_inspection_records_failed_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            reports = Path(directory) / "reports"
            with contextlib.redirect_stderr(io.StringIO()):
                status = main(["--run-dir", str(reports), "inspect", str(Path(directory) / "missing")])
            self.assertEqual(status, 1)
            report = json.loads(next(reports.glob("*.json")).read_text())
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["exit_code"], 1)
            self.assertEqual(report["cost"]["status"], "no_llm")
            self.assertTrue(report["run_id"])

    def test_doctor_reports_supported_runtime(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["doctor"])
        self.assertEqual(status, 0)
        self.assertTrue(json.loads(output.getvalue())["supported"])
