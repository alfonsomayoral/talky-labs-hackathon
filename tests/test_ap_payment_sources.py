"""Synthetic notice/invoice facts bound to the payment engine; no golden, no network."""
import json
from pathlib import Path
import tempfile
import unittest

from kalmora.ap_payment import ACTIONS
from kalmora.ap_payment_sources import resolve_invoice_payment, resolve_notice
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
    return DocumentFacts("a" * 64, "test", {name: [Fact(value, Evidence("doc.pdf", name))]
                                            for name, value in fields.items()})


def register(state, kind, doc_id, received_at="2026-07-02T09:00:00", **overrides):
    result = resolve_notice(kind, facts({**FACTS[kind], **overrides}), doc_id=doc_id,
                            received_at=received_at, scope=SCOPE, state=state)
    return result.state


class PaymentSourcesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        (root / "erp").mkdir()
        (root / "tasks").mkdir()
        (root / "tasks/close.json").write_text('{"month":"2026-07"}')
        (root / "erp/vendors.json").write_text(json.dumps([
            {"id": "V1", "companies": ["1100"], "currency": "EUR", "default_tax_code": "SISP"}]))
        (root / "erp/contractor_certificates.json").write_text(json.dumps([
            {"reference": "CERT-OLD", "vendor": "V1", "issued_on": "2025-06-01", "valid_until": "2026-06-30"}]))
        self.data = PhaseData(root)

    def tearDown(self):
        self.directory.cleanup()

    def pay(self, notices=ApTimelineState(), complete=True):
        return resolve_invoice_payment(
            data=self.data, scope=SCOPE, invoice_date="2026-07-10", received_at="2026-07-10T12:00:00",
            notices=notices, notices_complete=complete,
            duplicate_status="CLEAR", rejection_status="CLEAR", hold_status="CLEAR")

    def test_document_types_map_to_policy_actions(self):
        for kind in ("CONTRACTOR_TAX_CERTIFICATE", "FACTORING_NOTICE", "TAX_GARNISHMENT_ORDER",
                     "PROFORMA", "VENDOR_STATEMENT"):
            with self.subTest(kind=kind):
                result = resolve_notice(kind, facts(FACTS[kind]), doc_id="D1",
                                        received_at="2026-07-02T09:00:00", scope=SCOPE)
                self.assertEqual((result.decision, result.action), ("NOT_INVOICE", ACTIONS[kind]))

    def test_unverified_bank_letter_and_missing_facts_stay_unknown(self):
        bank = resolve_notice("BANK_DETAILS_CHANGE", facts(FACTS["BANK_DETAILS_CHANGE"]), doc_id="D1",
                              received_at="2026-07-02T09:00:00", scope=SCOPE)
        self.assertEqual((bank.decision, bank.diagnostics), ("UNKNOWN", ("BANK_CHANGE_NOT_VERIFIED",)))
        self.assertEqual(bank.state, ApTimelineState())
        conflicting = facts(FACTS["CONTRACTOR_TAX_CERTIFICATE"])
        conflicting.fields["certificate_expiry_date"] = [Fact("2026-12-31", Evidence("doc.pdf", "expiry"))]
        result = resolve_notice("CONTRACTOR_TAX_CERTIFICATE", conflicting, doc_id="D1",
                                received_at="2026-07-02T09:00:00", scope=SCOPE)
        self.assertEqual(result.diagnostics, ("CERTIFICATE_EXPIRY_UNKNOWN",))
        self.assertEqual(resolve_notice("FACTORING_NOTICE", facts({}), doc_id="D1",
                                        received_at="2026-07-02T09:00:00", scope=None).decision, "UNKNOWN")

    def test_expired_certificate_blocks_until_a_received_renewal(self):
        result = self.pay()
        self.assertEqual((result.decision, result.payment_block),
                         ("POST_PAYMENT_BLOCK", "CONTRACTOR_CERTIFICATE_EXPIRED"))
        renewed = register(ApTimelineState(), "CONTRACTOR_TAX_CERTIFICATE", "D1")
        self.assertEqual(self.pay(renewed).decision, "POST")
        late = register(ApTimelineState(), "CONTRACTOR_TAX_CERTIFICATE", "D1", received_at="2026-07-20T09:00:00")
        self.assertEqual(self.pay(late).decision, "POST_PAYMENT_BLOCK")

    def test_active_assignment_pays_factor(self):
        state = register(register(ApTimelineState(), "CONTRACTOR_TAX_CERTIFICATE", "C1"), "FACTORING_NOTICE", "F1")
        result = self.pay(state)
        self.assertEqual((result.decision, result.payee), ("POST", "FACTOR"))
        self.assertIn(Evidence("doc.pdf", "iban"), result.evidence)

    def test_embargo_received_before_invoice_pays_tax_authority(self):
        state = register(register(ApTimelineState(), "CONTRACTOR_TAX_CERTIFICATE", "C1"), "TAX_GARNISHMENT_ORDER", "E1")
        self.assertEqual(self.pay(state).payee, "AEAT_EMBARGO")
        later = register(ApTimelineState(), "TAX_GARNISHMENT_ORDER", "E1", received_at="2026-07-11T09:00:00")
        self.assertIsNone(self.pay(register(later, "CONTRACTOR_TAX_CERTIFICATE", "C1")).payee)

    def test_competing_claims_and_incomplete_inbox_abstain(self):
        certified = register(ApTimelineState(), "CONTRACTOR_TAX_CERTIFICATE", "C1")
        both = register(register(certified, "FACTORING_NOTICE", "F1"), "TAX_GARNISHMENT_ORDER", "E1")
        self.assertIn("PAYEE_CONFLICT", self.pay(both).diagnostics)
        factors = register(register(certified, "FACTORING_NOTICE", "F1"), "FACTORING_NOTICE", "F2", iban="ESFACTOR2")
        result = self.pay(factors)
        self.assertEqual((result.decision, result.payee), ("UNKNOWN", None))
        self.assertEqual(self.pay(certified, complete=False).decision, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
