import json
import tempfile
import unittest
from kalmora.runlog import RunRecorder


class RunTests(unittest.TestCase):
    def test_unknown_usage_cost_and_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            with RunRecorder(directory, ["solve"], {"sha256": "abc"}) as run:
                run.record_call("provider", "model")
                run.record_cache_hit()
            report = json.loads(run.path.read_text())
            self.assertEqual(report["cost"]["status"], "unknown")
            self.assertIsNone(report["cost"]["total"])
            self.assertEqual(report["cache_hits"], 1)
            self.assertGreaterEqual(report["elapsed_seconds"], 0)

    def test_decimal_and_failure_report(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                with RunRecorder(directory, []) as run:
                    run.record_call("p", "m", 3, 2, {"input_rate": "0.1", "output_rate": "0.2",
                        "currency": "EUR", "unit": "per_token", "provenance": "supplied tariff"})
                    raise RuntimeError("failure")
            self.assertEqual(run.report["cost"]["estimated_by_currency"], {"EUR": "0.7"})
            self.assertEqual(run.report["status"], "failed")

    def test_no_llm_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            with RunRecorder(directory, []) as run:
                pass
            self.assertEqual(run.report["cost"]["total"], "0")
            self.assertEqual(run.report["cost"]["status"], "no_llm")
