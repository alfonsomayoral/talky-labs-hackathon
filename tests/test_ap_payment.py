"""Synthetic policy variants for payment metadata and notice actions."""
from dataclasses import replace
import unittest

from kalmora.ap_chronology import KINDS, invoice_state, replay_events
from kalmora.ap_payment import ACTIONS, apply_notice, resolve_payment
from kalmora.facts import Evidence
from kalmora.model.ap_event import ApEvent
from kalmora.model.ap_scope import ApScope
from kalmora.model.ap_timeline_state import ApTimelineState

SCOPE = ApScope("1100", "V1", "EUR")
PROOF = (Evidence("synthetic-notice", "observed"),)


def event(id, kind, **kwargs):
    return ApEvent(id, SCOPE, kind, PROOF, **kwargs)


def observe(events=()):
    return invoice_state(events, SCOPE, "2026-07-15", "2026-07-16T10:00:00", "2026-07", complete_kinds=KINDS)


def payment(state=None, **kwargs):
    values = dict(duplicate_status="CLEAR", rejection_status="CLEAR", hold_status="CLEAR",
                  construction_subcontractor=True, events=state or observe())
    values.update(kwargs)
    return resolve_payment(**values)


class PaymentTests(unittest.TestCase):
    def test_expired_or_absent_certificate_blocks_only_construction(self):
        expired = event("cert", KINDS[0], valid_from="2025-07-01", valid_until="2026-07-14")
        result = payment(observe([expired]))
        self.assertEqual(result.decision, "POST_PAYMENT_BLOCK")
        self.assertEqual(result.payment_block, "CONTRACTOR_CERTIFICATE_EXPIRED")
        self.assertEqual(payment().decision, "POST_PAYMENT_BLOCK")
        self.assertEqual(payment(construction_subcontractor=False).decision, "POST")

    def test_valid_certificate_boundary_releases_payment(self):
        cert = event("cert", KINDS[0], valid_from="2025-07-15", valid_until="2026-07-15")
        result = payment(observe([cert]))
        self.assertEqual(result.decision, "POST")
        self.assertEqual(result.evidence, PROOF)
        self.assertIsNone(result.payment_block)

    def test_factor_and_prior_embargo_independent_policy_paths(self):
        factor = event("factor", KINDS[1], valid_from="2026-07-01")
        result = payment(observe([factor]), construction_subcontractor=False)
        self.assertEqual(result.decision, "POST")
        self.assertEqual(result.payee, "FACTOR")
        embargo = event("aeat", KINDS[2], received_at="2026-07-16T09:59:59")
        result = payment(observe([embargo]))
        self.assertEqual(result.decision, "POST_PAYMENT_BLOCK")
        self.assertEqual(result.payee, "AEAT_EMBARGO")
        later = replace(embargo, received_at="2026-07-16T10:00:00")
        self.assertIsNone(payment(observe([later])).payee)

    def test_payee_conflict_is_not_an_invented_policy_precedence(self):
        events = [event("factor", KINDS[1], valid_from="2026-01-01"),
                  event("aeat", KINDS[2], received_at="2026-07-01T00:00:00")]
        result = payment(observe(events))
        self.assertEqual(result.decision, "UNKNOWN")
        self.assertIn("PAYEE_CONFLICT", result.diagnostics)

    def test_earlier_rule_stages_always_win_before_payment_metadata(self):
        unknown_events = invoice_state([], SCOPE, "2026-07-15", "2026-07-16T10:00:00", "2026-07")
        self.assertEqual(payment(unknown_events, duplicate_status="DUPLICATE", rejection_status="REJECT", hold_status="HOLD").decision, "DUPLICATE")
        self.assertEqual(payment(unknown_events, rejection_status="REJECT", hold_status="HOLD").decision, "REJECT")
        self.assertEqual(payment(unknown_events, hold_status="HOLD").decision, "HOLD")
        self.assertEqual(payment(unknown_events, duplicate_status="UNKNOWN", rejection_status="REJECT").decision, "UNKNOWN")
        self.assertEqual(payment(unknown_events, rejection_status="UNKNOWN", hold_status="HOLD").decision, "UNKNOWN")
        self.assertEqual(payment(duplicate_status="REISSUE").decision, "POST_PAYMENT_BLOCK")

    def test_unknown_certificate_scope_and_payee_never_become_post(self):
        state = invoice_state([], SCOPE, "2026-07-15", "2026-07-16T10:00:00", "2026-07")
        self.assertEqual(payment(state).decision, "UNKNOWN")
        self.assertEqual(payment(construction_subcontractor=None).decision, "UNKNOWN")
        cert = event("cert", KINDS[0], valid_from="2026-01-01", valid_until="2026-12-31")
        self.assertEqual(payment(observe([cert]), construction_subcontractor=None).decision, "POST")
        with self.assertRaises(ValueError):
            payment(construction_subcontractor="yes")
        with self.assertRaises(ValueError):
            payment(hold_status="POST")

    def test_notice_types_actions_and_immutable_replay(self):
        state = ApTimelineState()
        notices = [event("factor", KINDS[1], received_at="2026-07-01T00:00:00", valid_from="2026-07-01"),
                   event("aeat", KINDS[2], received_at="2026-07-02T00:00:00"),
                   event("bank", KINDS[3], received_at="2026-07-03T00:00:00", verified=True, value="ESNEW"),
                   event("cert", KINDS[0], received_at="2026-07-04T00:00:00", valid_from="2026-07-01", valid_until="2027-07-01")]
        for notice in notices:
            prior = state
            result = apply_notice(notice.kind, notice, state)
            self.assertEqual(result.decision, "NOT_INVOICE")
            self.assertEqual(result.action, ACTIONS[notice.kind])
            self.assertEqual(len(result.state.events), len(prior.events) + 1)
            self.assertEqual(len(prior.events), len(state.events))
            self.assertEqual(apply_notice(notice.kind, notice, result.state), result)
            state = result.state
        for kind in ("PROFORMA", "VENDOR_STATEMENT"):
            result = apply_notice(kind, state=state)
            self.assertEqual(result.action, "NONE")
            self.assertIs(result.state, state)

    def test_unknown_or_unverified_notice_never_updates_state(self):
        state = replay_events([event("registered-cert", KINDS[0], valid_from="2026-01-01", valid_until="2026-12-31")])
        for notice in (event("bank", KINDS[3], received_at="2026-07-01T00:00:00", value="ESNEW", verified=False),
                       event("cert", KINDS[0], received_at="2026-07-01T00:00:00", valid_from="2026-01-01"),
                       event("aeat", KINDS[2]),
                       event("factor", KINDS[1], received_at="2026-07-01T00:00:00")):
            result = apply_notice(notice.kind, notice, state)
            self.assertEqual(result.decision, "UNKNOWN")
            self.assertIs(result.state, state)
            self.assertIsNone(result.action)
        self.assertEqual(apply_notice("FACTORING_NOTICE", state=state).decision, "UNKNOWN")

    def test_notice_type_mismatch_and_conflicting_identity_fail(self):
        cert = event("cert", KINDS[0], received_at="2026-07-01T00:00:00", valid_from="2026-01-01", valid_until="2026-12-31")
        with self.assertRaises(ValueError):
            apply_notice("INVOICE", cert)
        with self.assertRaises(ValueError):
            apply_notice("BANK_DETAILS_CHANGE", cert)
        with self.assertRaises(ValueError):
            apply_notice("PROFORMA", cert)
        state = apply_notice(cert.kind, cert).state
        with self.assertRaises(ValueError):
            apply_notice(cert.kind, replace(cert, valid_until="2027-12-31"), state)

    def test_notice_isolation_keeps_other_scope_state_unchanged(self):
        cert = event("cert", KINDS[0], received_at="2026-07-01T00:00:00", valid_from="2026-01-01", valid_until="2026-12-31")
        other = replace(cert, scope=ApScope("1910", "V1", "EUR"))
        state = apply_notice(other.kind, other).state
        self.assertEqual(payment(observe(state)).decision, "POST_PAYMENT_BLOCK")
        updated = apply_notice(cert.kind, cert, state).state
        self.assertEqual(payment(observe(updated)).decision, "POST")
        self.assertEqual(state.events, (other,))
