"""Phase notice inventories require source roles, exact scope and original clocks."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kalmora.ap_chronology import KINDS
from kalmora.ap_notice_bridge import strict_invoice_events
from kalmora.ap_phase_notice_context import resolve_phase_notice_context
from kalmora.ap_sources import APPreparedSources
from kalmora.data import PhaseData
from kalmora.documents.ap_sources import APAttachment, APMessage, APTaskSources
from kalmora.documents.classification import classify_document
from kalmora.documents.contracts import ParsedBlock, ParsedDocument
from kalmora.documents.normalization import normalize_document_facts
from kalmora.facts import DocumentFacts, Evidence, Fact
from kalmora.model.ap_scope import ApScope


class APPhaseNoticeContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.phase = Path(self.tmp.name) / "phase"
        (self.phase / "tasks").mkdir(parents=True)
        (self.phase / "erp").mkdir()
        (self.phase / "tasks/close.json").write_text(json.dumps({"month": "2031-11"}))
        self.vendor = dict(id="V-B", tax_id="TAX-B", currency="EUR", companies=["CO-A"],
            email="usual@vendor.invalid", alternative_payee=None, garnishments=[],
            bank_history=[dict(iban="ESOLD", valid_from="2030-01-01")])
        self.other = dict(self.vendor, id="V-C", tax_id="TAX-C")
        self.write("vendors", [self.vendor, self.other])
        self.write("companies", [dict(code="CO-A", tax_id="BUYER-A"),
                                  dict(code="CO-C", tax_id="BUYER-C")])
        self.write("contractor_certificates", [])
        self.scope = ApScope("CO-A", "V-B", "EUR")

    def write(self, name, rows):
        (self.phase / "erp" / (name + ".jsonl")).write_text(
            "".join(json.dumps(row) + "\n" for row in rows))

    def task(self, doc_id="LETTER-X", *, kind="BANK_DETAILS_CHANGE", values=None,
             received="2031-11-15T09:00:00Z", path=None):
        path = path or f"inbox/ap/{doc_id}/notice.pdf"
        defaults = dict(document_type_hint=kind, supplier_tax_id="TAX-B",
            recipient_tax_id="BUYER-A", currency="EUR", new_iban="ES NEW",
            signed=True, bank_certificate_present=True, document_date="2030-02-01")
        if values is not None:
            defaults = dict(document_type_hint=kind, **values)
        raw = DocumentFacts("a" * 64, "synthetic-notice-v1", {
            name: value if isinstance(value, list) else [Fact(value, Evidence(path, name))]
            for name, value in defaults.items()})
        document = ParsedDocument(path, raw.source_sha256, "application/pdf", "synthetic-parser-v1",
            (ParsedBlock("B1", "Observed literal notice", 1),))
        attachment = APAttachment(path, document, raw, normalized=normalize_document_facts(raw),
                                  classification=classify_document(raw))
        message_path = f"inbox/ap/{doc_id}/message.json"
        message = APMessage(message_path, "b" * 64, received, "EMAIL", "usual@vendor.invalid",
            "ap@buyer.invalid", "Observed notice", "Observed body", (path,),
            {"doc_id": doc_id, "received_at": received})
        return APTaskSources(doc_id, message, (attachment,))

    def prepared(self, *tasks, inventory=None):
        ids = [task.doc_id for task in tasks] if inventory is None else inventory
        (self.phase / "tasks/ap_documents.json").write_text(json.dumps(ids))
        prepared = APPreparedSources(manifest=dict(mode="fixture", stable_source_sha256="c" * 64))
        prepared.update((task.doc_id, task) for task in tasks)
        return prepared

    def resolve(self, prepared, **options):
        return resolve_phase_notice_context(prepared, data=PhaseData(self.phase),
                                           scope=options.pop("scope", self.scope), **options)

    def observe(self, snapshot, **options):
        return strict_invoice_events(snapshot.timeline, self.scope, "2031-11-01",
            "2031-11-20T10:00:00Z", "2031-11", bank_iban="ESNEW",
            complete_kinds=tuple(snapshot.event_inventory_evidence),
            inventory_evidence=snapshot.event_inventory_evidence,
            uncertain_kinds=snapshot.unknown_event_kinds,
            incomplete_sources=snapshot.incomplete_sources,
            bank_fields=snapshot.bank_event_fields, **options)

    def test_signed_letter_connects_observed_account_and_preserves_distinct_clocks(self):
        snapshot = self.resolve(self.prepared(self.task()))
        event, = snapshot.timeline.events
        self.assertEqual((event.scope, event.value, event.received_at, event.valid_from),
            (self.scope, "ESNEW", "2031-11-15T09:00:00Z", None))
        self.assertTrue(self.observe(snapshot).state.bank_change_supported)
        self.assertEqual(snapshot.unknown_event_kinds, ())
        self.assertNotIn("BANK_DETAILS_CHANGE", snapshot.event_inventory_evidence)
        self.assertTrue(any(proof.field == "document_date" for proof in event.evidence))
        self.assertEqual(snapshot.notice_results[0].resolution.action, "UPDATE_BANK_DETAILS")

    def test_domain_or_verified_flag_does_not_supply_missing_signature_or_certificate(self):
        task = self.task(values=dict(supplier_tax_id="TAX-B", recipient_tax_id="BUYER-A",
            currency="EUR", new_iban="ESNEW", verified=True, signed=True))
        snapshot = self.resolve(self.prepared(task))
        self.assertEqual(snapshot.timeline.events, ())
        self.assertEqual(snapshot.unknown_event_kinds, ("BANK_DETAILS_CHANGE",))
        self.assertEqual(snapshot.incomplete_sources, ())
        self.assertEqual(snapshot.notice_results[0].resolution.decision, "UNKNOWN")
        self.assertIn("FACTORING_NOTICE", snapshot.event_inventory_evidence)
        self.assertIsNone(self.observe(snapshot).state.bank_change_supported)

    def test_failed_and_unclassified_sources_remove_all_negative_inventory_claims(self):
        task = self.task()
        failed = APAttachment("inbox/ap/LETTER-X/unread.pdf", None, error="NO_CAPTURE")
        untyped = self.task(values={"description": "unidentified"},
                            path="inbox/ap/LETTER-X/untyped.pdf").attachments[0]
        task = replace(task, attachments=(*task.attachments, failed, untyped))
        snapshot = self.resolve(self.prepared(task))
        self.assertEqual(set(snapshot.unknown_event_kinds), set(KINDS))
        self.assertEqual(set(snapshot.incomplete_sources), {failed.path, untyped.path})
        self.assertEqual(dict(snapshot.event_inventory_evidence), {})
        self.assertIsNone(self.observe(snapshot).state.bank_change_supported)
        self.assertTrue(any(proof.document == failed.path for proof in snapshot.evidence))

    def test_observably_foreign_notice_is_excluded_with_evidence(self):
        task = self.task(values=dict(supplier_tax_id="TAX-C", recipient_tax_id="BUYER-A",
            currency="USD", new_iban="FOREIGN", signed=True, bank_certificate_present=True))
        snapshot = self.resolve(self.prepared(task))
        self.assertEqual(snapshot.timeline.events, ())
        self.assertEqual(snapshot.unknown_event_kinds, ())
        self.assertEqual(snapshot.incomplete_sources, ())
        self.assertIn("FACTORING_NOTICE", snapshot.event_inventory_evidence)
        self.assertTrue(any("NOTICE_SCOPE_FOREIGN:vendor:V-C" in note for note in snapshot.diagnostics))
        self.assertIn(task.attachments[0].facts.fields["supplier_tax_id"][0].evidence, snapshot.evidence)

    def test_scope_conflicts_and_missing_currency_never_use_vendor_defaults(self):
        for fields in (dict(supplier_tax_id="TAX-C", vendor_id="V-B", recipient_tax_id="BUYER-A", currency="EUR"),
                       dict(supplier_tax_id="TAX-B", recipient_tax_id="BUYER-A"),
                       dict(supplier_tax_id="TAX-B", recipient_tax_id="BUYER-A", currency=None)):
            snapshot = self.resolve(self.prepared(self.task(values=fields)))
            self.assertEqual(snapshot.timeline.events, ())
            self.assertEqual(set(snapshot.unknown_event_kinds), set(KINDS))
            self.assertEqual(dict(snapshot.event_inventory_evidence), {})
            self.assertEqual(snapshot.notice_results[0].resolution.decision, "UNKNOWN")

    def test_certificate_uses_subject_not_issuer_and_projects_nonmonetary_scope(self):
        authority = dict(self.vendor, id="TAX-AUTHORITY", tax_id="AUTHORITY-TAX")
        self.write("vendors", [self.vendor, self.other, authority])
        task = self.task(kind="CONTRACTOR_TAX_CERTIFICATE", values=dict(
            supplier_tax_id="AUTHORITY-TAX", certificate_tax_id="TAX-B",
            certificate_issue_date="2031-10-01", certificate_valid_until="2032-10-01"))
        requested = replace(self.scope, currency="USD")
        snapshot = self.resolve(self.prepared(task), scope=requested)
        event, = snapshot.timeline.events
        self.assertEqual(event.scope, requested)
        self.assertEqual((event.received_at, event.valid_from),
                         ("2031-11-15T09:00:00Z", "2031-10-01"))
        self.assertTrue(any("§2.2.4" in proof.field for proof in event.evidence))
        issuer_only = self.task(kind="CONTRACTOR_TAX_CERTIFICATE", values=dict(
            supplier_tax_id="TAX-B", certificate_issue_date="2031-10-01",
            certificate_valid_until="2032-10-01"))
        unknown = self.resolve(self.prepared(issuer_only))
        self.assertEqual(unknown.timeline.events, ())
        self.assertEqual(set(unknown.unknown_event_kinds), set(KINDS))

    def test_registered_facts_retain_receipt_uncertainty_restriction_and_expiry(self):
        self.write("vendors", [dict(self.vendor, alternative_payee=dict(type="FACTOR",
            from_date="2031-10-01", iban="FACTOR-BANK", invoice_number="ONLY-ONE",
            valid_until="2031-11-10"), garnishments=[dict(ref="G-7", from_date="2031-11-01")]), self.other])
        self.write("contractor_certificates", [dict(vendor="V-B", reference="CERT-7",
            issued_on="2031-10-01", valid_until="2032-10-01")])
        source = (self.phase / "erp/vendors.jsonl").read_bytes()
        snapshot = self.resolve(self.prepared(self.task(kind="INVOICE", values={})))
        factor = next(event for event in snapshot.timeline.events if event.kind == "FACTORING_NOTICE")
        embargo = next(event for event in snapshot.timeline.events if event.kind == "TAX_GARNISHMENT_ORDER")
        self.assertEqual((factor.invoice_number, factor.valid_until, factor.received_at),
                         ("ONLY-ONE", "2031-11-10", None))
        self.assertEqual((embargo.valid_from, embargo.received_at), ("2031-11-01", None))
        observed = self.observe(snapshot, invoice_number="ONLY-ONE")
        self.assertIsNone(observed.state.embargo_active)
        self.assertIsNone(next(event for event in observed.events
                               if event.kind == "TAX_GARNISHMENT_ORDER").valid_from)
        self.assertEqual(embargo.valid_from, "2031-11-01")
        self.assertEqual((self.phase / "erp/vendors.jsonl").read_bytes(), source)
        self.assertTrue(any(name == "erp/contractor_certificates.jsonl" for name, _ in snapshot.source_hashes))

    def test_informational_types_have_none_action_and_never_register_events(self):
        for kind in ("PROFORMA", "VENDOR_STATEMENT"):
            snapshot = self.resolve(self.prepared(self.task(kind=kind, values={})))
            self.assertEqual(snapshot.timeline.events, ())
            self.assertEqual(snapshot.unknown_event_kinds, ())
            self.assertEqual((snapshot.notice_results[0].resolution.decision,
                snapshot.notice_results[0].resolution.action), ("NOT_INVOICE", "NONE"))
            self.assertIn("CONTRACTOR_TAX_CERTIFICATE", snapshot.event_inventory_evidence)

    def test_replay_is_order_independent_and_returned_fields_do_not_mutate_inputs(self):
        first = self.task("OPAQUE-Z")
        second = self.task("OPAQUE-A", kind="CONTRACTOR_TAX_CERTIFICATE", values=dict(
            certificate_tax_id="TAX-B", certificate_valid_from="2031-10-01",
            certificate_valid_until="2032-10-01"))
        prepared = self.prepared(first, second)
        original = deepcopy(first.attachments[0].facts.to_dict())
        with patch("socket.create_connection", side_effect=AssertionError("network disabled")) as network:
            left = self.resolve(prepared)
            right_prepared = APPreparedSources(manifest=dict(mode="fixture", stable_source_sha256="c" * 64))
            right_prepared.update(reversed(tuple(prepared.items())))
            right = self.resolve(right_prepared)
            network.assert_not_called()
        self.assertEqual(left, right)
        self.assertEqual(first.attachments[0].facts.to_dict(), original)
        key = next(iter(left.bank_event_fields))
        with self.assertRaises(TypeError):
            left.bank_event_fields[key]["new_iban"] = ()
        with self.assertRaises(TypeError):
            left.event_inventory_evidence["FACTORING_NOTICE"] = ()

    def test_missing_task_or_catalogue_stays_unknown_and_changed_erp_fails_snapshot(self):
        prepared = self.prepared(self.task(), inventory=["LETTER-X", "MISSING-TASK"])
        missing = self.resolve(prepared)
        self.assertEqual(dict(missing.event_inventory_evidence), {})
        self.assertIn("tasks/ap_documents.json", missing.incomplete_sources)
        prepared = self.prepared(self.task())
        (self.phase / "erp/contractor_certificates.jsonl").unlink()
        no_catalogue = self.resolve(prepared)
        self.assertNotIn("CONTRACTOR_TAX_CERTIFICATE", no_catalogue.event_inventory_evidence)
        self.assertTrue(self.observe(no_catalogue).state.bank_change_supported)
        self.write("contractor_certificates", [])
        from kalmora.ap_chronology import registered_events
        def change_after_read(data, scope):
            result = registered_events(data, scope)
            self.write("contractor_certificates", [dict(vendor="V-B", reference="LATER",
                issued_on="2031-01-01", valid_until="2032-01-01")])
            return result
        with patch("kalmora.ap_phase_notice_context.registered_events", side_effect=change_after_read):
            with self.assertRaisesRegex(ValueError, "sources changed"):
                self.resolve(prepared)
        self.write("contractor_certificates", [dict(reference="UNKNOWN-SUBJECT",
            issued_on="2031-01-01", valid_until="2032-01-01")])
        unknown_subject = self.resolve(prepared)
        self.assertNotIn("CONTRACTOR_TAX_CERTIFICATE", unknown_subject.event_inventory_evidence)
        self.assertIn("CONTRACTOR_TAX_CERTIFICATE", unknown_subject.unknown_event_kinds)

    def test_master_and_clock_symlinks_fail_before_opening_forbidden_bytes(self):
        prepared = self.prepared(self.task())
        open_path = Path.open
        for relative in ("erp/vendors.jsonl", "tasks/close.json"):
            for destination in (self.phase / "golden", Path(self.tmp.name) / "outside-phase"):
                for stage in ("before-context", "before-final-verification"):
                    with self.subTest(relative=relative, destination=destination.name, stage=stage):
                        original = self.phase / relative
                        payload = original.read_bytes()
                        destination.mkdir(exist_ok=True)
                        forbidden = destination / original.name
                        forbidden.write_bytes(payload)  # synthetic stand-in, never actual Golden data
                        data = PhaseData(self.phase)  # create before replacing the phase clock
                        attempted = []
                        def guarded_open(path, *args, **kwargs):
                            if path.resolve() == forbidden.resolve():
                                attempted.append(path)
                                raise AssertionError("forbidden source bytes must not be opened")
                            return open_path(path, *args, **kwargs)
                        def substitute():
                            original.unlink()
                            original.symlink_to(forbidden)
                        from kalmora.ap_chronology import registered_events
                        def substitute_after_registered(view, scope):
                            result = registered_events(view, scope)
                            substitute()
                            return result
                        try:
                            if stage == "before-context":
                                substitute()
                            with patch.object(Path, "open", guarded_open):
                                with patch("kalmora.ap_phase_notice_context.registered_events",
                                    side_effect=registered_events if stage == "before-context"
                                    else substitute_after_registered):
                                    with self.assertRaises(ValueError):
                                        resolve_phase_notice_context(prepared, data=data, scope=self.scope)
                            self.assertEqual(attempted, [])
                        finally:
                            if original.is_symlink():
                                original.unlink()
                            original.write_bytes(payload)


if __name__ == "__main__":
    unittest.main()
