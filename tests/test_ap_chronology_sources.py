"""Synthetic notices bound to the chronology; never read golden data."""
import json
from pathlib import Path
import tempfile
import unittest

from kalmora.ap_chronology import KINDS
from kalmora.ap_chronology_sources import invoice_events, notice_events
from kalmora.data import PhaseData
from kalmora.facts import DocumentFacts, Evidence, Fact
from kalmora.model.ap_scope import ApScope

SCOPE = ApScope("1100", "V1", "EUR")
VENDOR = {"id": "V1", "tax_id": "A11111111", "companies": ["1100"], "currency": "EUR",
          "email": "admin@v1.example", "bank": {"iban": "ESOLD"}}


def facts(name, **fields):
    return DocumentFacts("0" * 64, "test", {key: [Fact(value, Evidence(name, key))]
                                            for key, value in fields.items()})


class ChronologySourcesTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "erp").mkdir()
        (root / "tasks").mkdir()
        (root / "tasks/close.json").write_text('{"month":"2026-07"}')
        (root / "erp/companies.json").write_text(json.dumps([{"code": "1100", "tax_id": "A00000000"}]))
        (root / "erp/vendors.json").write_text(json.dumps([VENDOR]))
        (root / "erp/contractor_certificates.json").write_text(json.dumps([
            {"vendor": "V1", "reference": "CERT-OLD", "issued_on": "2025-06-22", "valid_until": "2026-06-22"}]))
        self.data = PhaseData(root)

    def bind(self, doc_id, received_at, kind, sender="admin@v1.example", **fields):
        message = {"doc_id": doc_id, "received_at": received_at, "from": sender}
        binding = notice_events(message, [(facts(f"{doc_id}.pdf", **fields), kind)], self.data)
        return binding.events

    def state(self, events, invoice_date, received_at, **kwargs):
        return invoice_events(self.data, SCOPE, events, invoice_date, received_at,
                              complete_kinds=KINDS, **kwargs)

    def test_factoring_reception_is_not_vigency(self):
        notice = self.bind("N1", "2026-07-14T12:32:00", "FACTORING_NOTICE", supplier_tax_id="A11111111",
                           notice_date="2026-07-12", factoring_effective_date="2026-07-20", iban="ESFACTOR")
        self.assertEqual((notice[0].received_at, notice[0].valid_from), ("2026-07-14T12:32:00", "2026-07-20"))
        self.assertFalse(self.state(notice, "2026-07-16", "2026-07-18T09:00:00").factoring_active)
        active = self.state(notice, "2026-07-20", "2026-07-21T09:00:00", bank_iban="ESFACTOR")
        self.assertTrue(active.factoring_active and active.factoring_bank_supported)
        self.assertEqual(active.factoring.event_id, "N1/N1.pdf")

    def test_certificate_valid_or_expired_at_invoice_date_over_erp_history(self):
        notice = self.bind("C1", "2026-07-01T10:52:00", "CONTRACTOR_TAX_CERTIFICATE",
                           certificate_tax_id="A11111111", certificate_valid_from="27/06/2026",
                           certificate_valid_until="27/06/2027")
        self.assertFalse(self.state(notice, "2026-06-25", "2026-07-02T09:00:00").certificate_valid)
        valid = self.state(notice, "2026-07-01", "2026-07-02T09:00:00")
        self.assertTrue(valid.certificate_valid)
        self.assertEqual(valid.certificate.evidence[0], Evidence("inbox/ap/C1/message.json", "received_at",
                                                                 quote="2026-07-01T10:52:00"))

    def test_embargo_must_be_received_before_invoice(self):
        notice = self.bind("E1", "2026-07-10T09:00:00", "TAX_GARNISHMENT_ORDER",
                           supplier_tax_id="A11111111", embargo_date="2026-07-01")
        self.assertTrue(self.state(notice, "2026-07-01", "2026-07-10T10:00:00").embargo_active)
        self.assertFalse(self.state(notice, "2026-07-01", "2026-07-10T08:00:00").embargo_active)

    def test_bank_change_received_in_month_supports_iban_before_effective_date(self):
        letter = self.bind("B1", "2026-07-20T08:11:00", "BANK_DETAILS_CHANGE", old_iban="ESOLD",
                           iban="ESNEW", bank_details_effective_date="15/08/2026")
        self.assertTrue(self.state(letter, "2026-07-22", "2026-07-25T09:00:00",
                                   bank_iban="ESNEW").bank_change_supported)
        other_sender = self.bind("B2", "2026-07-20T08:11:00", "BANK_DETAILS_CHANGE",
                                 sender="admin@v1-example.es", old_iban="ESOLD", iban="ESNEW")
        self.assertIsNone(other_sender[0].verified)
        self.assertIsNone(self.state(other_sender, "2026-07-22", "2026-07-25T09:00:00",
                                     bank_iban="ESNEW").bank_change_supported)

    def test_same_reception_tie_break_is_validity_then_event_id(self):
        def certificate(doc_id, start):
            return self.bind(doc_id, "2026-07-05T10:00:00", "CONTRACTOR_TAX_CERTIFICATE",
                             certificate_tax_id="A11111111", certificate_valid_from=start,
                             certificate_valid_until="2027-07-01")
        a, b, c = certificate("A", "2026-07-02"), certificate("B", "2026-07-01"), certificate("C", "2026-07-02")
        for events in ((*a, *b, *c), (*c, *b, *a)):
            self.assertEqual(self.state(events, "2026-07-10", "2026-07-11T09:00:00").certificate.event_id, "C/C.pdf")


if __name__ == "__main__":
    unittest.main()
