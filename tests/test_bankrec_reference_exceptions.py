from decimal import Decimal
import os
from pathlib import Path
import unittest

from kalmora.bankrec import Category, build_bank_rec, journal_entries
from kalmora.bankrec.statements import read_statements
from kalmora.data import PhaseData
from kalmora.documents.contracts import ParsedDocument, digest
from kalmora.money import RateTable

REAL = Path(os.environ.get("KALMORA_PHASE_DEV", Path(__file__).resolve().parents[1] / "participant/phase_dev"))


@unittest.skipUnless((REAL / "bank").is_dir(), "development source package unavailable")
class SourceExceptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = PhaseData(REAL)
        cls.reconciliation = build_bank_rec(cls.data)

    def test_swift_api004253_original_rates_and_gain_reduction(self):
        invoice = self.data.get("ap_invoices", "API004253")
        rates = RateTable(self.data.table("fx_rates"))
        invoice_value = rates.convert_cents(invoice["payable"], "GBP", "EUR", invoice["issue_date"])
        payment_value = rates.convert_cents(invoice["payable"], "GBP", "EUR", "2026-07-10")
        self.assertEqual((invoice_value, payment_value), (5754155, 5718979))
        result = next(r for r in self.reconciliation.results if r.account.id == "BIN-1000")
        match = next(m for m in result.matches if "BL0001816" in m.bank_lines)
        self.assertEqual((match.difference.category, match.difference.amount), (Category.FX_RATE_DIFFERENCE, -24019))
        payment = self.data.get("journal_entries", match.book_lines[0].split("#")[0])
        self.assertEqual((payment["source"], payment["reference"]), ("SWIFT", invoice["number"]))
        original_gain = next(x["credit"] for x in payment["lines"] if x["account"] == "76800000")
        book_payment = next(x["credit"] for x in payment["lines"] if x["account"] == "57200001")
        # Four-decimal published rate differs by two cents from the recorded
        # historical payment. Correct against the recorded book, preserving it.
        self.assertEqual(book_payment - payment_value, 2)
        self.assertEqual(original_gain, invoice_value - book_payment)
        adjustment = next(a for a in result.adjustments if "BL0001816" in a.causes)
        self.assertEqual([(x.account, x.debit, x.credit) for x in adjustment.lines],
                         [("76800000", 24019, 0), ("57200001", 0, 24019)])
        actual_payment = 5743000
        self.assertEqual(original_gain - 24019, invoice_value - actual_payment)
        self.assertEqual(original_gain - 24019, 11155)
        # June valuation was explicitly reversed on July 1: it is not another
        # realized FX difference to post again at payment.
        valuation = [e for e in self.data.iter_journal() if e.get("reference") == "FXV-API004253"]
        self.assertEqual({e["source"] for e in valuation}, {"CLOSE_FX", "CLOSE_FX:reversal"})
        self.assertEqual(sum(x["debit"] - x["credit"] for e in valuation for x in e["lines"] if x["account"] == "76800000"), 0)

    def test_three_reference_omissions_are_distinct_unbooked_original_charges(self):
        expected = [("CMA-1100", "BL0001846", "2026-07-27", "2026-037563", 107141),
                    ("CMA-1100", "BL0001847", "2026-07-29", "2026-037570", 215748),
                    ("CMA-1200", "BL0001835", "2026-07-23", "26020907", 264496)]
        entries = list(self.data.iter_journal())
        for account, id, day, reference, amount in expected:
            result = next(r for r in self.reconciliation.results if r.account.id == account)
            bank = next(x for s in read_statements(self.data, result.account, "2026-07") for x in s.lines if x.id == id)
            self.assertEqual((bank.booking_date, bank.invoice, bank.amount), (day, reference, -amount))
            self.assertEqual(self.data.find("ap_invoices", number=reference), [])
            self.assertFalse(any(e.get("reference") == reference or any(x.get("assignment") == reference for x in e["lines"]) for e in entries))
            adjustment = next(a for a in result.adjustments if a.causes == (id,))
            self.assertEqual(adjustment.category, Category.DIRECT_DEBIT_NOT_BOOKED)
            self.assertEqual([(x.account, x.debit, x.credit) for x in adjustment.lines],
                             [("41000000", amount, 0), ("57200002", 0, amount)])
        self.assertEqual(len(journal_entries(self.reconciliation)), 59)

    def test_related_problematic_ap_sources_do_not_erase_executed_bank_payments(self):
        normalized = Path(os.environ.get("KALMORA_NORMALIZED_SOURCES", REAL.parent / "normalized_sources"))
        import json
        cases = [("inbox/ap/API005227/factura_2026-037570.pdf", ("2026-037570", "UTE Kalmora Construcción", "2.157,48")),
                 ("inbox/ap/API005221/factura_26020907.pdf", ("26020907", "2.404,51", "240,45", "3.088,02"))]
        for relative, fragments in cases:
            doc = ParsedDocument.from_dict(json.loads((normalized / REAL.name / (relative + ".json")).read_text()))
            self.assertEqual(doc.source_sha256, digest((REAL / relative).read_bytes()))
            text = "\n".join(x.text for x in doc.blocks)
            for fragment in fragments:
                self.assertIn(fragment, text)
        # Water source has inconsistent printed gross. Executed debit equals
        # base + VAT; M3 records actual payment, never a new AP expense invoice.
        self.assertEqual(240451 + 24045, 264496)
        self.assertNotEqual(240451 + 24045, 308802)
