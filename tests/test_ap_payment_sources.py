"""Synthetic notice/invoice facts bound to the payment engine; no golden, no network."""
import json
from pathlib import Path
import tempfile
import unittest

from kalmora.ap_chronology import KINDS
from kalmora.ap_chronology_sources import notice_events
from kalmora.ap_payment import ACTIONS
from kalmora.ap_payment_sources import (invoice_date_candidates, possible_notice_kinds,
                                        resolve_invoice_payment, resolve_notice)
from kalmora.documents.normalization import normalize_document_facts
from kalmora.data import PhaseData
from kalmora.facts import DocumentFacts, Evidence, Fact
from kalmora.model.ap_scope import ApScope
from kalmora.model.ap_timeline_state import ApTimelineState

SCOPE = ApScope("1100", "V1", "EUR")
FACTS = {
    "CONTRACTOR_TAX_CERTIFICATE": {"certificate_valid_from": "2026-07-01", "certificate_valid_until": "2027-07-01"},
    "FACTORING_NOTICE": {"factoring_effective_date": "2026-07-01", "iban": "ESFACTOR1"},
    "TAX_GARNISHMENT_ORDER": {"embargo_reference": "AEAT-1"},
    "BANK_DETAILS_CHANGE": {"bank_details_effective_date": "2026-07-01", "iban": "ESNEW"},
    "PROFORMA": {}, "VENDOR_STATEMENT": {},
}


def facts(fields):
    fields = {"supplier_tax_id": "A11111111", **fields}
    return DocumentFacts("a" * 64, "test", {name: [Fact(value, Evidence("doc.pdf", name))]
                                            for name, value in fields.items()})


class PaymentSourcesTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "erp").mkdir()
        (root / "tasks").mkdir()
        (root / "tasks/close.json").write_text('{"month":"2026-07"}')
        (root / "erp/companies.json").write_text(json.dumps([{"code": "1100", "tax_id": "A00000000"}]))
        (root / "erp/vendors.json").write_text(json.dumps([
            {"id": "V1", "tax_id": "A11111111", "companies": ["1100"], "currency": "EUR",
             "email": "admin@v1.example", "default_tax_code": "SISP", "bank": {"iban": "ESOLD"}}]))
        (root / "erp/contractor_certificates.json").write_text(json.dumps([
            {"reference": "CERT-OLD", "vendor": "V1", "issued_on": "2025-06-01", "valid_until": "2026-06-30"}]))
        self.data = PhaseData(root)

    def notice(self, kind, doc_id, received_at="2026-07-02T09:00:00", state=ApTimelineState(),
               sender="admin@v1.example", **overrides):
        message = {"doc_id": doc_id, "received_at": received_at, "from": sender}
        events = notice_events(message, [(facts({**FACTS[kind], **overrides}), kind)], self.data).events
        return resolve_notice(kind, events, state)

    def register(self, *notices, state=ApTimelineState()):
        for kind, doc_id, *received in notices:
            state = self.notice(kind, doc_id, *received, state=state).state
        return state

    def pay(self, state=ApTimelineState(), complete=KINDS, dates=("2026-07-10",)):
        return resolve_invoice_payment(
            data=self.data, scope=SCOPE, invoice_dates=dates, received_at="2026-07-10T12:00:00",
            notices=state.events, complete_kinds=complete,
            duplicate_status="CLEAR", rejection_status="CLEAR", hold_status="CLEAR")

    def test_document_types_map_to_policy_actions(self):
        for kind in FACTS:
            with self.subTest(kind=kind):
                result = self.notice(kind, "D1")
                self.assertEqual((result.decision, result.action), ("NOT_INVOICE", ACTIONS[kind]))

    def test_unverified_bank_letter_keeps_action_but_not_state(self):
        result = self.notice("BANK_DETAILS_CHANGE", "D1", sender="admin@lookalike.example")
        self.assertEqual((result.decision, result.action), ("NOT_INVOICE", "UPDATE_BANK_DETAILS"))
        self.assertEqual(result.state, ApTimelineState())
        self.assertEqual(len(self.notice("BANK_DETAILS_CHANGE", "D1").state.events), 1)

    def test_expired_certificate_blocks_until_a_received_renewal(self):
        result = self.pay()
        self.assertEqual((result.decision, result.payment_block),
                         ("POST_PAYMENT_BLOCK", "CONTRACTOR_CERTIFICATE_EXPIRED"))
        self.assertEqual(self.pay(self.register(("CONTRACTOR_TAX_CERTIFICATE", "C1"))).decision, "POST")
        late = self.register(("CONTRACTOR_TAX_CERTIFICATE", "C1", "2026-07-20T09:00:00"))
        self.assertEqual(self.pay(late).decision, "POST_PAYMENT_BLOCK")

    def test_active_assignment_pays_factor(self):
        result = self.pay(self.register(("CONTRACTOR_TAX_CERTIFICATE", "C1"), ("FACTORING_NOTICE", "F1")))
        self.assertEqual((result.decision, result.payee), ("POST", "FACTOR"))
        self.assertIn(Evidence("doc.pdf", "iban"), result.evidence)

    def test_embargo_received_before_invoice_pays_tax_authority(self):
        prior = self.register(("CONTRACTOR_TAX_CERTIFICATE", "C1"), ("TAX_GARNISHMENT_ORDER", "E1"))
        self.assertEqual(self.pay(prior).payee, "AEAT_EMBARGO")
        later = self.register(("CONTRACTOR_TAX_CERTIFICATE", "C1"), ("TAX_GARNISHMENT_ORDER", "E1", "2026-07-11T09:00:00"))
        self.assertIsNone(self.pay(later).payee)

    def test_competing_claims_and_unproved_absence_abstain(self):
        both = self.register(("CONTRACTOR_TAX_CERTIFICATE", "C1"), ("FACTORING_NOTICE", "F1"), ("TAX_GARNISHMENT_ORDER", "E1"))
        self.assertIn("PAYEE_CONFLICT", self.pay(both).diagnostics)
        factors = self.register(("CONTRACTOR_TAX_CERTIFICATE", "C1"), ("FACTORING_NOTICE", "F1"))
        factors = self.notice("FACTORING_NOTICE", "F2", state=factors, iban="ESFACTOR2").state
        self.assertEqual((self.pay(factors).decision, self.pay(factors).payee), ("UNKNOWN", None))
        certified = self.register(("CONTRACTOR_TAX_CERTIFICATE", "C1"))
        self.assertEqual(self.pay(certified, complete=KINDS[:1]).decision, "UNKNOWN")

    def test_unclassified_document_hides_only_its_subject_kind(self):
        self.assertEqual(possible_notice_kinds("Envío de factura nº 1"), ())
        self.assertEqual(possible_notice_kinds("Cambio de cuenta bancaria"), ("BANK_DETAILS_CHANGE",))
        self.assertEqual(possible_notice_kinds("FRA 0008000 KALMORA"), ())
        self.assertEqual(possible_notice_kinds(None), KINDS)

    def test_ambiguous_invoice_date_counts_only_when_irrelevant(self):
        dates = invoice_date_candidates([normalize_document_facts(facts({"invoice_date": "06/07/2026"}))])
        self.assertEqual(dates, {"2026-06-07", "2026-07-06"})
        self.assertEqual(self.pay(dates=dates).diagnostics, ("INVOICE_DATE_UNKNOWN",))
        renewed = self.register(("CONTRACTOR_TAX_CERTIFICATE", "C1"))
        self.assertEqual(self.pay(renewed, dates=dates).decision, "POST")


if __name__ == "__main__":
    unittest.main()
