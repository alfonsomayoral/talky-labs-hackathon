"""Synthetic policy variations; never read golden data."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from kalmora.ap_chronology import (KINDS, event_support_facts, invoice_state,
                                  registered_events, replay_events)
from kalmora.data import PhaseData
from kalmora.facts import Evidence
from kalmora.model.ap_event import ApEvent
from kalmora.model.ap_scope import ApScope

SCOPE = ApScope("1100", "V1", "EUR")
PROOF = (Evidence("synthetic-notice", "observed"),)


def event(id, kind, **kwargs):
    return ApEvent(id, SCOPE, kind, PROOF, **kwargs)


def observe(events=(), **kwargs):
    return invoice_state(events, kwargs.pop("scope", SCOPE),
                         kwargs.pop("invoice_date", "2026-07-15"),
                         kwargs.pop("received_at", "2026-07-16T10:00:00"),
                         "2026-07", **kwargs)


class ChronologyTests(unittest.TestCase):
    def test_certificate_inclusive_invoice_date_not_reception(self):
        cert = event("certificate", KINDS[0], valid_from="2026-07-01", valid_until="2026-07-15")
        self.assertTrue(observe([cert]).certificate_valid)
        self.assertFalse(observe([cert], invoice_date="2026-07-16", complete_kinds=KINDS).certificate_valid)
        self.assertTrue(observe([cert], invoice_date="2026-07-01").certificate_valid)
        self.assertFalse(observe([cert], invoice_date="2026-06-30", complete_kinds=KINDS).certificate_valid)

    def test_factoring_validity_is_distinct_from_received_at(self):
        factor = event("factor", KINDS[1], received_at="2026-07-10T00:00:00", valid_from="2026-07-20")
        self.assertFalse(observe([factor], complete_kinds=KINDS).factoring_active)
        self.assertTrue(observe([factor], invoice_date="2026-07-20").factoring_active)
        late = replace(factor, valid_from="2026-07-01", received_at="2026-07-20T00:00:00")
        self.assertFalse(observe([late], complete_kinds=KINDS).factoring_active)
        self.assertIsNone(observe([replace(late, received_at="2026-07-16")], complete_kinds=KINDS).factoring_active)

    def test_factoring_authorizes_only_its_evidenced_bank(self):
        factor = event("factor", KINDS[1], valid_from="2026-01-01", value="ESFACTOR")
        state = observe([factor], bank_iban="ESFACTOR")
        self.assertTrue(state.factoring_active)
        self.assertTrue(event_support_facts(state)["factoring_supported"][0].value)
        wrong = observe([factor], bank_iban="ESSUSPICIOUS")
        self.assertTrue(wrong.factoring_active)
        self.assertFalse(event_support_facts(wrong)["factoring_supported"][0].value)
        self.assertEqual(event_support_facts(observe([factor]))["factoring_supported"], ())

    def test_active_factor_conflicts_are_not_resolved_by_document_id(self):
        first = event("a", KINDS[1], received_at="2026-07-01T10:00:00", valid_from="2026-07-01", value="ESFACTOR1")
        for value in ("ESFACTOR2", None):
            other = replace(first, event_id="z", value=value)
            state = observe([first, other], bank_iban="ESFACTOR1")
            self.assertTrue(state.factoring_active)
            self.assertIsNone(state.factoring_bank_supported)
            self.assertIsNone(state.factoring)
            self.assertEqual(state, observe([other, first], bank_iban="ESFACTOR1"))
            self.assertIn("FACTORING_NOTICE:CONFLICT:a,z", state.diagnostics)
            self.assertEqual(event_support_facts(state)["factoring_supported"], ())
        same_factor = replace(first, event_id="z")
        equivalent = observe([first, same_factor], bank_iban="ESFACTOR1")
        self.assertTrue(equivalent.factoring_bank_supported)
        self.assertEqual(equivalent.factoring.event_id, "z")

    def test_verified_conflicting_bank_letters_do_not_authorize_arbitrary_bank(self):
        first = event("a", KINDS[3], received_at="2026-07-01T10:00:00", verified=True, value="ESBANK1")
        for value in ("ESBANK2", None):
            other = replace(first, event_id="z", value=value)
            state = observe([first, other], bank_iban="ESBANK1")
            self.assertIsNone(state.bank_change_supported)
            self.assertIsNone(state.bank_change)
            self.assertEqual(state, observe([other, first], bank_iban="ESBANK1"))
            self.assertIn("BANK_DETAILS_CHANGE:CONFLICT:a,z", state.diagnostics)
        self.assertTrue(observe([first, replace(first, event_id="z")], bank_iban="ESBANK1").bank_change_supported)

    def test_embargo_strictly_before_receipt_and_unknown_same_day(self):
        before = event("aeat", KINDS[2], received_at="2026-07-16T09:59:59")
        self.assertTrue(observe([before]).embargo_active)
        for timestamp in ("2026-07-16T10:00:00", "2026-07-16T10:00:01"):
            self.assertFalse(observe([replace(before, received_at=timestamp)], complete_kinds=KINDS).embargo_active)
        self.assertIsNone(observe([replace(before, received_at="2026-07-16")], complete_kinds=KINDS).embargo_active)
        self.assertIsNone(observe([replace(before, received_at=None, valid_from="2026-01-01")], complete_kinds=KINDS).embargo_active)

    def test_verified_bank_notice_received_later_in_month(self):
        bank = event("bank", KINDS[3], received_at="2026-07-31T23:59:59", verified=True, value="ESNEW")
        self.assertTrue(observe([bank], bank_iban="ESNEW").bank_change_supported)
        self.assertFalse(observe([bank], bank_iban="ESOTHER", complete_kinds=KINDS).bank_change_supported)
        self.assertFalse(observe([replace(bank, received_at="2026-08-01T00:00:00")], bank_iban="ESNEW", complete_kinds=KINDS).bank_change_supported)
        self.assertFalse(observe([replace(bank, verified=False)], bank_iban="ESNEW", complete_kinds=KINDS).bank_change_supported)
        self.assertIsNone(observe([replace(bank, verified=None)], bank_iban="ESNEW", complete_kinds=KINDS).bank_change_supported)
        self.assertTrue(observe([replace(bank, received_at="2026-06-30T23:59:59")], bank_iban="ESNEW").bank_change_supported)

    def test_unknown_is_not_absence_and_bridge_requires_inventory_proof(self):
        unknown = observe()
        self.assertIsNone(unknown.certificate_valid)
        self.assertEqual(event_support_facts(unknown)["signed_change_supported"], ())
        complete = observe(complete_kinds=KINDS)
        self.assertFalse(complete.certificate_valid)
        with self.assertRaises(ValueError):
            event_support_facts(complete)
        facts = event_support_facts(complete, {kind: PROOF for kind in KINDS})
        self.assertFalse(facts["signed_change_supported"][0].value)
        self.assertEqual(facts["factoring_supported"][0].evidence, PROOF[0])

    def test_replay_stable_idempotent_and_input_immutable(self):
        a = event("a", KINDS[0], valid_from="2026-07-01", valid_until="2027-07-01")
        b = replace(a, event_id="b")
        original = [b, a]
        state = replay_events(original)
        self.assertEqual(original, [b, a])
        self.assertEqual(state, replay_events(reversed(original)))
        self.assertEqual(state, replay_events([a], state))
        self.assertEqual(observe(state).certificate.event_id, "b")
        with self.assertRaises(ValueError):
            replay_events([replace(a, valid_until="2028-07-01")], state)
        self.assertEqual(state.events, (a, b))

    def test_scope_and_invoice_reference_isolation(self):
        factor = event("factor", KINDS[1], valid_from="2026-01-01", invoice_number="INV-1")
        self.assertTrue(observe([factor], invoice_number="INV-1").factoring_active)
        self.assertFalse(observe([factor], invoice_number="INV-2", complete_kinds=KINDS).factoring_active)
        self.assertIsNone(observe([factor], complete_kinds=KINDS).factoring_active)
        for scope in (ApScope("1910", "V1", "EUR"), ApScope("1100", "V2", "EUR"), ApScope("1100", "V1", "USD")):
            self.assertFalse(observe([factor], scope=scope, invoice_number="INV-1", complete_kinds=KINDS).factoring_active)

    def test_unknown_and_invalid_values(self):
        missing_expiry = event("certificate", KINDS[0], valid_from="2026-01-01")
        self.assertIsNone(observe([missing_expiry], complete_kinds=KINDS).certificate_valid)
        for candidate in (replace(missing_expiry, valid_until="2025-01-01"),
                          replace(missing_expiry, valid_from="2026-02-30"),
                          replace(missing_expiry, evidence=()),
                          replace(missing_expiry, verified="yes"),
                          replace(missing_expiry, kind="UNKNOWN")):
            with self.assertRaises((ValueError, TypeError)):
                replay_events([candidate])
        with self.assertRaises(ValueError):
            observe(received_at="2026-08-01T00:00:00")

    def test_time_zone_equivalent_instants(self):
        embargo = event("aeat", KINDS[2], received_at="2026-07-16T11:59:59+02:00")
        self.assertTrue(observe([embargo], received_at="2026-07-16T10:00:00Z").embargo_active)
        self.assertFalse(observe([replace(embargo, received_at="2026-07-16T12:00:00+02:00")], received_at="2026-07-16T10:00:00Z", complete_kinds=KINDS).embargo_active)

    def test_phase_adapter_preserves_receipt_unknown_and_original_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "erp").mkdir()
            (root / "tasks").mkdir()
            (root / "tasks/close.json").write_text('{"month":"2026-07"}')
            vendor = {"id":"V1", "companies":["1100"], "currency":"EUR",
                      "alternative_payee":{"type":"FACTOR", "from_date":"2026-01-01", "iban":"ESFACTOR"},
                      "garnishments":[{"ref":"AEAT1", "from_date":"2026-01-01"}]}
            (root / "erp/vendors.json").write_text(json.dumps([vendor]))
            (root / "erp/contractor_certificates.json").write_text(json.dumps([
                {"reference":"CERT1", "vendor":"V1", "issued_on":"2026-01-01", "valid_until":"2026-12-31"}]))
            data = PhaseData(root)
            state = registered_events(data, SCOPE)
            self.assertTrue(observe(state).certificate_valid)
            self.assertTrue(observe(state).factoring_active)
            self.assertIsNone(observe(state).embargo_active)
            self.assertEqual(data.table("vendors"), [vendor])
            with self.assertRaises(ValueError):
                registered_events(data, ApScope("1910", "V1", "EUR"))
