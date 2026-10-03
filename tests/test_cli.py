import contextlib
import io
import json
import unittest

from kalmora.cli import main


class CliTests(unittest.TestCase):
    def test_doctor_reports_supported_runtime(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["doctor"])
        self.assertEqual(status, 0)
        self.assertTrue(json.loads(output.getvalue())["supported"])

