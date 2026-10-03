"""Opt-in integration with actual solver inputs, never with the reference set."""
from calendar import monthrange
from fractions import Fraction
import os
from pathlib import Path
import unittest

from kalmora.data import PhaseData
from kalmora.ledger import Ledger
from kalmora.ic import Upstream, reconcile
from kalmora.ic.model import digest
from kalmora.validation import validate_entry


@unittest.skipUnless(os.environ.get("KALMORA_IC_PHASE"), "set KALMORA_IC_PHASE to the solver-only phase directory")
class RealInputIntegrationTests(unittest.TestCase):
    def test_recorded_only_run_conserves_source_and_proves_actionable_facts(self):
        data = PhaseData(Path(os.environ["KALMORA_IC_PHASE"]))
        source = Ledger.from_entries(data.iter_journal())
        original = digest(source.entries)
        result = reconcile(data, recorded=source, upstream=Upstream.missing())
        self.assertEqual(original, digest(source.entries))
        self.assertFalse(result.complete)
        self.assertTrue(result.findings)
        codes = {d.code for d in result.diagnostics}
        self.assertTrue({"AP_ENTRY_DELIVERY_PENDING", "AP_RECEIPT_COVERAGE_PENDING", "BANK_DELIVERY_PENDING"} <= codes)
        by_id = {e["id"]: e for e in source.iter_entries()}
        for finding in result.findings:
            if finding.proposed:
                self.assertEqual(validate_entry(finding.proposed), [])
                self.assertEqual(sum(l["debit"] - l["credit"] for l in finding.emitted_adjustment), 0)
            if finding.cause == "POOLING_NOT_BOOKED":
                self.assertFalse(finding.emitted_adjustment)
                self.assertEqual(finding.status, "pending_bank")
                self.assertIn("bank_line", finding.details)  # Real statement matching, not a synthetic bank correction.
            if finding.cause == "DUPLICATE_POSTING":
                original_entry = by_id[finding.details["duplicate_entry"]]
                self.assertEqual(len(finding.proposed["lines"]), len(original_entry["lines"]))
                for a, b in zip(original_entry["lines"], finding.proposed["lines"]):
                    self.assertEqual((a["debit"], a["credit"]), (b["credit"], b["debit"]))
                    self.assertEqual(a.get("tax_code"), b.get("tax_code"))
                    self.assertEqual(a.get("wbs"), b.get("wbs"))
                    self.assertEqual(a.get("cost_center"), b.get("cost_center"))
            if finding.cause == "INTEREST_DAY_COUNT":
                agreement = data.table("intercompany_agreements")["loan"]
                year, month = map(int, data.month.split("-"))
                # Independent exact rational calculation for this package's active full month.
                self.assertLessEqual(agreement["start"], data.month + "-01")
                exact = Fraction(agreement["principal"] * agreement["rate_bp"] * monthrange(year, month)[1], 10000 * 360)
                independently_rounded = (2 * exact.numerator + exact.denominator) // (2 * exact.denominator)
                self.assertEqual(finding.details["calculation"]["rounded_cents"], independently_rounded)
        # Re-importing the produced projection must not generate a second adjustment.
        replay = reconcile(data, recorded=source, upstream=Upstream(result.projection, None, None, None))
        self.assertTrue(all(not f.emitted_adjustment for f in replay.findings))
        self.assertEqual(replay.projection.entries, result.projection.entries)
