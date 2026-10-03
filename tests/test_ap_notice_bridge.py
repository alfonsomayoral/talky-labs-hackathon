"""Strict source-to-policy integration, with opaque IDs and a synthetic month."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from kalmora.ap_chronology import KINDS, event_support_facts, invoice_state
from kalmora.ap_notice_bridge import resolve_ap_notice, strict_invoice_events
from kalmora.ap_payment import resolve_payment
from kalmora.facts import DocumentFacts, Evidence, Fact
from kalmora.model.ap_event import ApEvent
from kalmora.model.ap_scope import ApScope
from kalmora.model.ap_timeline_state import ApTimelineState


SCOPE = ApScope("OTHER-COMPANY", "OTHER-VENDOR", "USD")
INVENTORY = {kind: (Evidence("synthetic-inventory", kind),) for kind in KINDS}


def fields(**values):
    return {key: [Fact(value, Evidence("inbox/ap/opaque-task/notice.pdf", key, 1,
                                      str(value)))] for key, value in values.items()}


def metadata(*, received="2031-11-05T10:00:00Z", doc_id="opaque-task"):
    return DocumentFacts("a" * 64, "ap-message-source-v1", {
        "doc_id": [Fact(doc_id, Evidence(f"inbox/ap/{doc_id}/message.json", "/doc_id"))],
        "received_at": [Fact(received, Evidence(f"inbox/ap/{doc_id}/message.json", "/received_at"))],
        "from": [Fact("admin@trusted.example", Evidence(f"inbox/ap/{doc_id}/message.json", "/from"))],
    })


def resolve(kind, observations, **options):
    return resolve_ap_notice(kind, fields=observations, company=SCOPE.company,
        vendor=SCOPE.vendor, currency=SCOPE.currency,
        metadata=options.pop("metadata", metadata()), **options)


def observe(events=(), **options):
    return strict_invoice_events(events, options.pop("scope", SCOPE),
        options.pop("invoice_date", "2031-11-20"),
        options.pop("received_at", "2031-11-21T10:00:00Z"), "2031-11",
        complete_kinds=options.pop("complete_kinds", KINDS),
        inventory_evidence=options.pop("inventory_evidence", INVENTORY), **options)


class APNoticeBridgeTests(unittest.TestCase):
    def test_signed_bank_letter_requires_its_bank_certificate_and_message_receipt(self):
        observations = fields(new_iban="US 1234", signed=True, bank_certificate_present=True,
                              document_date="2031-10-28", bank_details_effective_date="2031-12-01")
        resolved = resolve("BANK_DETAILS_CHANGE", observations)
        self.assertEqual((resolved.decision, resolved.action), ("NOT_INVOICE", "UPDATE_BANK_DETAILS"))
        event, = resolved.state.events
        self.assertEqual((event.received_at, event.valid_from, event.value),
                         ("2031-11-05T10:00:00Z", "2031-12-01", "US1234"))
        snapshot = observe(resolved.state, bank_iban="US1234",
                           bank_fields={(SCOPE, event.event_id): observations})
        self.assertTrue(snapshot.state.bank_change_supported)
        self.assertTrue(event_support_facts(snapshot.state, snapshot.inventory_evidence)
                        ["signed_change_supported"][0].value)
        self.assertTrue(any(proof.field == "signed" for proof in snapshot.state.bank_change.evidence))

    def test_trusted_sender_verified_flag_and_title_never_replace_both_bank_proofs(self):
        for extra in (dict(verified=True, document_type_hint="Signed bank details change"),
                      dict(signed=True), dict(bank_certificate_present=True),
                      dict(signed=False, bank_certificate_present=True),
                      dict(signed=True, bank_certificate_present=False),
                      dict(signed="true", bank_certificate_present=True)):
            prior = ApTimelineState()
            result = resolve("BANK_DETAILS_CHANGE", fields(new_iban="USNEW", **extra), state=prior)
            self.assertEqual(result.decision, "UNKNOWN")
            self.assertIsNone(result.action)
            self.assertIs(result.state, prior)
        legacy = ApEvent("legacy-bank", SCOPE, "BANK_DETAILS_CHANGE",
            (Evidence("inbox/ap/legacy/message.json", "from", quote="admin@trusted.example"),),
            received_at="2031-11-05T10:00:00Z", verified=True, value="USNEW")
        snapshot = observe((legacy,), bank_iban="USNEW")
        self.assertIsNone(snapshot.state.bank_change_supported)
        self.assertIsNone(snapshot.events[0].verified)
        self.assertTrue(legacy.verified)
        self.assertNotIn("BANK_DETAILS_CHANGE", snapshot.complete_kinds)

    def test_bank_verification_is_bound_to_its_account_and_retains_conflicting_evidence(self):
        observations = fields(new_iban="USREAL", signed=True, bank_certificate_present=True)
        resolved = resolve("BANK_DETAILS_CHANGE", observations)
        original, = resolved.state.events
        changed = replace(original, value="USWRONG")
        snapshot = observe((changed,), bank_iban="USWRONG",
                           bank_fields={(SCOPE, changed.event_id): observations})
        self.assertIsNone(snapshot.state.bank_change_supported)
        self.assertIsNone(snapshot.events[0].verified)
        self.assertEqual(snapshot.events[0].value, "USWRONG")
        self.assertIn(observations["new_iban"][0].evidence, snapshot.events[0].evidence)
        self.assertTrue(any("BANK_EVENT_VALUE_CONFLICT" in note for note in snapshot.diagnostics))
        for change in ({}, {"iban": [Fact(None, Evidence("other-proof.pdf", "iban-absent"))]},
                       {"iban": fields(iban="USWRONG")["iban"]}):
            bank_facts = dict(observations, **change)
            if not change:
                del bank_facts["new_iban"]
            snapshot = observe((original,), bank_iban="USREAL",
                               bank_fields={(SCOPE, original.event_id): bank_facts})
            self.assertIsNone(snapshot.state.bank_change_supported)
            self.assertNotIn("BANK_DETAILS_CHANGE", snapshot.complete_kinds)
        unverified = observe((replace(original, verified=False),), bank_iban="USREAL",
                             bank_fields={(SCOPE, original.event_id): observations})
        self.assertIsNone(unverified.state.bank_change_supported)
        self.assertTrue(any("BANK_EVENT_NOT_VERIFIED" in note for note in unverified.diagnostics))

    def test_bank_direct_scope_observations_cannot_authorize_another_scope(self):
        observations = fields(new_iban="USREAL", signed=True, bank_certificate_present=True)
        original, = resolve("BANK_DETAILS_CHANGE", observations).state.events
        for wrong in (dict(company="OTHER-LEGAL-ENTITY"), dict(vendor_id="OTHER-PARTNER"),
                      dict(currency="EUR")):
            bank_facts = dict(observations, **fields(**wrong))
            self.assertEqual(resolve("BANK_DETAILS_CHANGE", bank_facts).decision, "UNKNOWN")
            snapshot = observe((original,), bank_iban="USREAL",
                               bank_fields={(SCOPE, original.event_id): bank_facts})
            self.assertIsNone(snapshot.state.bank_change_supported)
            self.assertEqual(snapshot.events[0].scope, SCOPE)
            self.assertTrue(any("NOTICE_SCOPE_CONFLICT" in note for note in snapshot.diagnostics))

    def test_unclocked_bank_event_requires_explicit_registration_without_inventing_receipt(self):
        observations = fields(new_iban="USREAL", signed=True, bank_certificate_present=True)
        original, = resolve("BANK_DETAILS_CHANGE", observations).state.events
        unclocked = replace(original, received_at=None)
        snapshot = observe((unclocked,), bank_iban="USREAL",
                           bank_fields={(SCOPE, unclocked.event_id): observations})
        self.assertIsNone(snapshot.state.bank_change_supported)
        self.assertIsNone(snapshot.events[0].received_at)
        registered = dict(observations, bank_change_registered=[Fact(True,
            Evidence("erp/registered_bank_changes.jsonl", "registration", quote="registered"))])
        supported = observe((unclocked,), bank_iban="USREAL",
                            bank_fields={(SCOPE, unclocked.event_id): registered})
        self.assertTrue(supported.state.bank_change_supported)
        self.assertIsNone(supported.events[0].received_at)
        self.assertIn(registered["bank_change_registered"][0].evidence, supported.state.bank_change.evidence)

    def test_bank_validity_is_preserved_bound_and_cannot_authorize_after_explicit_expiry(self):
        observations = fields(new_iban="USREAL", signed=True, bank_certificate_present=True,
                              bank_details_effective_date="2031-11-01", valid_until="2031-11-20")
        original, = resolve("BANK_DETAILS_CHANGE", observations).state.events
        snapshot = observe((original,), bank_iban="USREAL",
                           bank_fields={(SCOPE, original.event_id): observations})
        self.assertTrue(snapshot.state.bank_change_supported)
        self.assertEqual((snapshot.events[0].valid_from, snapshot.events[0].valid_until),
                         (original.valid_from, original.valid_until))
        for changed in (replace(original, valid_until=None), replace(original, valid_until="2032-11-20"),
                        replace(original, valid_from="2031-11-02")):
            unsupported = observe((changed,), bank_iban="USREAL",
                                  bank_fields={(SCOPE, changed.event_id): observations})
            self.assertIsNone(unsupported.state.bank_change_supported)
            self.assertEqual(unsupported.events[0].valid_until, changed.valid_until)
        expired = observe((original,), invoice_date="2031-11-21", bank_iban="USREAL",
                          bank_fields={(SCOPE, original.event_id): observations})
        self.assertIsNone(expired.state.bank_change_supported)
        self.assertTrue(any("BANK_EVENT_AUTHORIZATION_EXPIRED" in note for note in expired.diagnostics))

    def test_explicit_absence_and_other_candidates_are_a_conflict_with_original_proof(self):
        observations = fields(certificate_valid_from="2031-11-01", certificate_valid_until="2032-11-01")
        missing = Fact(None, Evidence("inbox/ap/opaque-task/notice.pdf", "expiry-not-observed", 2))
        observations["certificate_valid_until"].append(missing)
        result = resolve("CONTRACTOR_TAX_CERTIFICATE", observations)
        self.assertEqual(result.decision, "UNKNOWN")
        self.assertEqual(result.state.events, ())
        self.assertIn("CONFLICT:valid_until", result.diagnostics)
        self.assertIn(missing.evidence, result.evidence)
        self.assertIn(observations["certificate_valid_until"][0].evidence, result.evidence)

    def test_factor_reference_and_expiry_bound_the_real_chronology(self):
        observations = fields(factoring_effective_date="2031-11-01", valid_until="2031-11-10",
                              assigned_invoice_number="INV-ALPHA", factor_iban="USFACTOR")
        result = resolve("FACTORING_NOTICE", observations)
        event, = result.state.events
        self.assertEqual((event.invoice_number, event.valid_until), ("INV-ALPHA", "2031-11-10"))
        active = observe(result.state, invoice_date="2031-11-09", received_at="2031-11-09T12:00:00Z",
                         invoice_number="INV-ALPHA", bank_iban="USFACTOR")
        self.assertTrue(active.state.factoring_active)
        for kwargs in (dict(invoice_number="INV-BETA", invoice_date="2031-11-09"),
                       dict(invoice_number="INV-ALPHA", invoice_date="2031-11-11")):
            self.assertFalse(observe(result.state, **kwargs).state.factoring_active)
        self.assertIsNone(observe(result.state).state.factoring_active)

    def test_notice_number_is_not_an_assignment_invoice_reference(self):
        result = resolve("FACTORING_NOTICE", fields(factoring_effective_date="2031-11-01",
                                                    document_number="NOTICE-ONLY"))
        self.assertIsNone(result.state.events[0].invoice_number)
        conflict = fields(factoring_effective_date="2031-11-01", assigned_invoice_number="INV-ALPHA",
                          original_invoice_reference="INV-BETA")
        self.assertEqual(resolve("FACTORING_NOTICE", conflict).decision, "UNKNOWN")

    def test_certificate_issue_date_never_becomes_arrival_and_validity_uses_invoice_date(self):
        result = resolve("CONTRACTOR_TAX_CERTIFICATE", fields(certificate_issue_date="2031-10-01",
                         certificate_expiry_date="2031-11-10"),
                         metadata=metadata(received="2031-11-08T10:00:00Z"))
        event, = result.state.events
        self.assertEqual((event.valid_from, event.received_at), ("2031-10-01", "2031-11-08T10:00:00Z"))
        self.assertFalse(observe(result.state, invoice_date="2031-11-09",
            received_at="2031-11-07T10:00:00Z").state.certificate_valid)
        valid = observe(result.state, invoice_date="2031-11-10",
                        received_at="2031-11-11T10:00:00Z")
        self.assertTrue(valid.state.certificate_valid)
        expired = observe(result.state, invoice_date="2031-11-11",
                          received_at="2031-11-12T10:00:00Z")
        payment = resolve_payment("CLEAR", "CLEAR", "CLEAR", True, expired.state,
                                  inventory_evidence=expired.inventory_evidence)
        self.assertEqual((payment.decision, payment.payment_block),
                         ("POST_PAYMENT_BLOCK", "CONTRACTOR_CERTIFICATE_EXPIRED"))

    def test_missing_or_conflicting_message_receipt_never_falls_back_to_issued_date(self):
        observations = fields(certificate_issue_date="2031-10-01", certificate_expiry_date="2032-10-01")
        for message in (DocumentFacts("a" * 64, "message", {"doc_id": metadata().fields["doc_id"]}),
                        metadata(received=None)):
            result = resolve("CONTRACTOR_TAX_CERTIFICATE", observations, metadata=message)
            self.assertEqual(result.decision, "UNKNOWN")
            self.assertEqual(result.state.events, ())
        message = metadata()
        message.fields["received_at"].append(Fact("2031-11-06T10:00:00Z", Evidence("message.json", "other")))
        self.assertIn("CONFLICT:received_at", resolve("CONTRACTOR_TAX_CERTIFICATE", observations,
                                                     metadata=message).diagnostics)

    def test_embargo_without_receipt_stays_unknown_without_mutating_registered_event(self):
        event = ApEvent("ERP-GARNISHMENT", SCOPE, "TAX_GARNISHMENT_ORDER",
                        (Evidence("erp/vendors.jsonl", "garnishments.from_date", quote="2031-11-01"),),
                        valid_from="2031-11-01")
        self.assertTrue(invoice_state((event,), SCOPE, "2031-11-20", "2031-11-21", "2031-11",
                                      complete_kinds=KINDS).embargo_active)
        snapshot = observe((event,))
        self.assertIsNone(snapshot.state.embargo_active)
        self.assertIsNone(snapshot.events[0].valid_from)
        self.assertEqual(snapshot.events[0].evidence, event.evidence)
        self.assertEqual(event.valid_from, "2031-11-01")
        self.assertIsNone(event.received_at)
        self.assertNotIn("TAX_GARNISHMENT_ORDER", snapshot.complete_kinds)

    def test_embargo_uses_receipt_order_and_keeps_explicit_invoice_reference(self):
        resolved = resolve("TAX_GARNISHMENT_ORDER", fields(embargo_date="2031-10-01",
                            referenced_invoice_number="INV-TARGET"),
                            metadata=metadata(received="2031-11-21T09:00:00Z"))
        self.assertTrue(observe(resolved.state, invoice_number="INV-TARGET").state.embargo_active)
        self.assertFalse(observe(resolved.state, invoice_number="INV-OTHER").state.embargo_active)
        self.assertFalse(observe(resolved.state, invoice_number="INV-TARGET",
                                received_at="2031-11-21T08:00:00Z").state.embargo_active)

    def test_actions_none_do_not_create_or_change_events(self):
        prior = ApTimelineState()
        for kind in ("PROFORMA", "VENDOR_STATEMENT"):
            result = resolve(kind, fields(new_iban="USNEW", signed=True, bank_certificate_present=True),
                             state=prior)
            self.assertEqual((result.decision, result.action), ("NOT_INVOICE", "NONE"))
            self.assertIs(result.state, prior)
            self.assertEqual(result.state.events, ())

    def test_replay_is_idempotent_and_conflicting_reinterpretation_abstains(self):
        observations = fields(certificate_valid_from="2031-11-01", certificate_valid_until="2032-11-01")
        observations["certificate_valid_until"].append(Fact("2032-11-01",
            Evidence("inbox/ap/opaque-task/notice.pdf", "other-expiry-proof", 2)))
        first = resolve("CONTRACTOR_TAX_CERTIFICATE", observations)
        repeated = resolve("CONTRACTOR_TAX_CERTIFICATE", observations, state=first.state)
        self.assertEqual(first, repeated)
        reordered = {name: list(reversed(candidates)) for name, candidates in reversed(list(observations.items()))}
        self.assertEqual(first, resolve("CONTRACTOR_TAX_CERTIFICATE", reordered, state=first.state))
        changed = dict(observations, certificate_valid_until=fields(certificate_valid_until="2033-11-01")
                       ["certificate_valid_until"])
        failed = resolve("CONTRACTOR_TAX_CERTIFICATE", changed, state=first.state)
        self.assertEqual(failed.decision, "UNKNOWN")
        self.assertIs(failed.state, first.state)
        self.assertIn("NOTICE_EVENT_INVALID:conflicting event identity", failed.diagnostics)
        self.assertEqual(first.state.events[0].valid_until, "2032-11-01")

    def test_inventory_completeness_requires_proof_and_every_failed_source_keeps_unknown(self):
        missing_proof = observe(inventory_evidence={})
        self.assertEqual(missing_proof.complete_kinds, ())
        self.assertIsNone(missing_proof.state.factoring_active)
        failed = observe(incomplete_sources=("opaque-unparsed-source",))
        self.assertEqual(failed.complete_kinds, ())
        self.assertEqual(dict(failed.inventory_evidence), {})
        self.assertIsNone(failed.state.certificate_valid)
        self.assertIsNone(failed.state.embargo_active)
        clean = observe()
        self.assertFalse(clean.state.factoring_active)
        self.assertFalse(event_support_facts(clean.state, clean.inventory_evidence)["embargo_active"][0].value)
        with self.assertRaises(TypeError):
            clean.inventory_evidence["FACTORING_NOTICE"] = ()

    def test_unseen_competing_notices_keep_operative_factor_and_bank_unknown(self):
        factor = resolve("FACTORING_NOTICE", fields(factoring_effective_date="2031-11-01", iban="USFACTOR"))
        snapshot = observe(factor.state, bank_iban="USFACTOR", uncertain_kinds=("FACTORING_NOTICE",))
        self.assertTrue(snapshot.state.factoring_active)
        self.assertIsNone(snapshot.state.factoring)
        self.assertIsNone(snapshot.state.factoring_bank_supported)
        observations = fields(new_iban="USNEW", signed=True, bank_certificate_present=True)
        bank = resolve("BANK_DETAILS_CHANGE", observations)
        event, = bank.state.events
        snapshot = observe(bank.state, bank_iban="USNEW", uncertain_kinds=("BANK_DETAILS_CHANGE",),
                           bank_fields={(SCOPE, event.event_id): observations})
        self.assertIsNone(snapshot.state.bank_change)
        self.assertIsNone(snapshot.state.bank_change_supported)

    def test_invalid_dates_scope_and_input_contracts_cannot_publish_an_event(self):
        for observations in (fields(certificate_valid_from="2031-02-30", certificate_valid_until="2032-11-01"),
                             fields(certificate_valid_from="2032-11-01", certificate_valid_until="2031-11-01"),
                             fields(certificate_valid_from="05/06/2031", certificate_valid_until="2032-11-01")):
            result = resolve("CONTRACTOR_TAX_CERTIFICATE", observations)
            self.assertEqual(result.decision, "UNKNOWN")
            self.assertEqual(result.state.events, ())
        with self.assertRaises(ValueError):
            resolve("INVOICE", {})
        with self.assertRaises(ValueError):
            strict_invoice_events((), ApScope("", "V", "EUR"), "2031-11-01", "2031-11-02", "2031-11")
        with self.assertRaises(ValueError):
            observe(complete_kinds=("UNSUPPORTED",))
        with self.assertRaises(TypeError):
            resolve("FACTORING_NOTICE", {"valid_from": ["2031-11-01"]})

    def test_scope_isolation_and_replay_need_no_network_or_gold_reference(self):
        with patch("socket.create_connection", side_effect=AssertionError("network unavailable")) as network:
            resolved = resolve("FACTORING_NOTICE", fields(factoring_effective_date="2031-11-01", factor_iban="USFACTOR"))
            for scope in (replace(SCOPE, company="OTHER-ENTITY"), replace(SCOPE, vendor="OTHER-PARTNER"),
                          replace(SCOPE, currency="EUR")):
                self.assertFalse(observe(resolved.state, scope=scope).state.factoring_active)
            repeated = resolve("FACTORING_NOTICE", fields(factoring_effective_date="2031-11-01", factor_iban="USFACTOR"),
                               state=resolved.state)
            self.assertEqual(repeated, resolved)
            network.assert_not_called()
