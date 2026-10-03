"""Independent boundary/contract tests for the authorized dependency adapter.

Tiny archives here are synthetic test fixtures, never the organizer's IC answer.
"""
from copy import deepcopy
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from kalmora.data import PhaseData
from kalmora.ic.context import Context
from kalmora.ic.model import Upstream
from kalmora.ledger import Ledger
from tools.m5_fixture import (REFERENCE_MEMBERS, Sources, _already_recorded, _pool_link,
                              ap_delivery, build, receipt_coverage, rows)
from test_ic_engine import SyntheticFixture, issued, received, entry, line, E


class AdapterTests(SyntheticFixture):
    def source(self, documents, tasks=None, extra=None):
        """Actual input files plus independently constructed AP/mock records."""
        self.put('tasks/ap_documents', tasks if tasks is not None else [r['doc_id'] for r in documents])
        self.put('tasks/bank_accounts', [])
        history = self.phase / 'erp/ap_document_log.jsonl'
        if not history.exists():
            history.write_text('')
        for row in documents:
            folder = self.phase / 'inbox/ap' / row['doc_id']
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'message.json').write_text(json.dumps({'doc_id': row['doc_id'], 'received_at': '2028-02-29T23:50:00'}))
        for relative, value in (extra or {}).items():
            (self.phase / relative).write_text(json.dumps(value))
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, 'w') as archive:
            for path in self.phase.rglob('*'):
                if path.is_file():
                    archive.writestr('participant/phase_dev/' + path.relative_to(self.phase).as_posix(), path.read_bytes())
            archive.writestr(REFERENCE_MEMBERS['ap'], '\n'.join(json.dumps(r) for r in documents))
            archive.writestr(REFERENCE_MEMBERS['bank_rec'], '')
            archive.writestr('participant/phase_dev/golden/ic.jsonl', 'FORBIDDEN ANSWER')
        mem.seek(0)
        archive = zipfile.ZipFile(mem)
        self.addCleanup(archive.close)
        return Sources(archive, self.phase)

    def document(self, ident='DOC', **kw):
        return {'doc_id': ident, 'document_type': 'INVOICE', 'decision': 'HOLD',
                'company': '1100', 'vendor_id': 'V-HOLD', 'invoice_number': ident, **kw}

    def context(self, entries=()):
        return Context(PhaseData(self.phase), Ledger.from_entries(entries), Upstream.missing())

    def test_every_decision_counts_as_received_even_without_a_posting(self):
        documents = [self.document(str(n), decision=decision) for n, decision in enumerate(
                     ('POST', 'HOLD', 'REJECT', 'DUPLICATE', 'POST_PAYMENT_BLOCK'))]
        source = self.source(documents)
        coverage, audit = receipt_coverage(documents, self.context(), source)
        self.assertTrue(coverage['complete'])
        self.assertEqual(len(coverage['receipts']), len(documents))
        self.assertEqual(audit['task_count'], audit['message_count'])
        self.assertTrue(audit['task_result_message_ids_exact'])

    def test_missing_or_extra_result_does_not_certify_absence(self):
        docs = [self.document('A'), self.document('B')]
        source = self.source(docs)
        for actual in (docs[:1], docs + [self.document('C')]):
            with self.assertRaisesRegex(ValueError, 'Incomplete AP coverage'):
                receipt_coverage(actual, self.context(), source)

    def test_duplicate_result_ids_rejected(self):
        doc = self.document()
        source = self.source([doc])
        with self.assertRaisesRegex(ValueError, 'duplicate IDs'):
            receipt_coverage([doc, doc], self.context(), source)

    def test_partial_inbox_rejected_not_empty(self):
        docs = [self.document('A'), self.document('B')]
        source = self.source(docs)
        (self.phase / 'inbox/ap/B/message.json').unlink()
        with self.assertRaisesRegex(ValueError, 'inbox/task'):
            receipt_coverage(docs, self.context(), source)

    def test_missing_and_invalid_dates_never_fall_back_to_invoice_date(self):
        for raw in (None, '', 'not-a-date', '2028-02-29'):
            with self.subTest(raw=raw):
                docs = [self.document()]
                source = self.source(docs, extra={'inbox/ap/DOC/message.json': {'doc_id': 'DOC', 'received_at': raw}})
                with self.assertRaisesRegex(ValueError, 'received_at'):
                    receipt_coverage(docs, self.context(), source)

    def test_offset_receipt_keeps_its_source_local_date(self):
        docs = [self.document()]
        source = self.source(docs, extra={'inbox/ap/DOC/message.json': {'doc_id': 'DOC', 'received_at': '2028-02-29T23:50:00-06:00'}})
        coverage, _ = receipt_coverage(docs, self.context(), source)
        self.assertEqual(coverage['receipts'][0]['received_on'], '2028-02-29')

    def test_changed_source_message_fails_original_package_hash_check(self):
        docs = [self.document()]
        source = self.source(docs)
        (self.phase / 'inbox/ap/DOC/message.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'differs from the original'):
            receipt_coverage(docs, self.context(), source)

    def test_history_held_document_counts_without_posting_or_current_task(self):
        doc = {'doc_id': 'OLD', 'company': '1100', 'vendor': 'V-HOLD', 'number': 'EARLIER',
               'kind': 'invoice', 'received_on': '2027-12-31', 'decision': 'HOLD'}
        (self.phase / 'erp/ap_document_log.jsonl').write_text(json.dumps(doc) + '\n')
        source = self.source([])
        coverage, audit = receipt_coverage([], self.context(), source)
        self.assertEqual(audit['historical_ic_receipts'], 1)
        self.assertEqual(coverage['receipts'][0]['reference'], 'EARLIER')

    def test_unknown_issuer_is_not_silently_classified_external(self):
        docs = [self.document(vendor_id=None)]
        source = self.source(docs)
        coverage, audit = receipt_coverage(docs, self.context(), source)
        self.assertIsNone(coverage['receipts'][0]['issuer'])
        self.assertEqual(audit['unknown_issuer_receipts'], 1)

    def test_unknown_invoice_reference_cannot_certify_complete(self):
        docs = [self.document(invoice_number=None)]
        source = self.source(docs)
        with self.assertRaisesRegex(ValueError, 'receipt identity'):
            receipt_coverage(docs, self.context(), source)

    def test_authorized_fixture_reads_never_include_ic(self):
        source = self.source([self.document()])
        source.fixture('ap')
        source.fixture('bank_rec')
        for name in ('ic', 'close', '../ic'):
            with self.assertRaises(ValueError):
                source.fixture(name)
        with self.assertRaises(ValueError):
            source._read('participant/phase_dev/golden/ic.jsonl')
        self.assertEqual(set(source.access_log), set(REFERENCE_MEMBERS.values()))

    def test_guarded_zip_open_sees_only_allowlisted_reference_members(self):
        source = self.source([self.document()])
        original = zipfile.ZipFile.open
        calls = []
        def guarded(archive, name, *a, **kw):
            member = name.filename if isinstance(name, zipfile.ZipInfo) else name
            calls.append(member)
            if '/golden/' in member and member not in REFERENCE_MEMBERS.values():
                self.fail('Adapter tried to read a forbidden expected answer')
            return original(archive, name, *a, **kw)
        with patch.object(zipfile.ZipFile, 'open', guarded):
            source.fixture('ap'); source.fixture('bank_rec')
        self.assertEqual(set(calls), set(REFERENCE_MEMBERS.values()))

    def test_posted_entry_is_copied_with_all_dimensions(self):
        e = received('REALREF')
        e['lines'][0].update(currency='EUR', amount_doc=100, tax_code='S21')
        row = self.document(decision='POST', journal_entry=e)
        before = deepcopy(row)
        deliveries, audit = ap_delivery([row], self.context(), 'intercompany')
        self.assertEqual(deliveries[0]['entry'], e)
        self.assertEqual((deliveries[0]['event_id'], deliveries[0]['stage']), ('DOC', 'ap_invoice'))
        self.assertEqual(row, before)
        self.assertEqual(audit['delivered_entries'], 1)

    def test_recorded_entry_is_not_posted_again(self):
        e = received()
        row = self.document(decision='POST', journal_entry=e)
        deliveries, audit = ap_delivery([row], self.context([e]), 'intercompany')
        self.assertEqual(deliveries, [])
        self.assertEqual(len(audit['already_recorded']), 1)

    def test_recorded_id_conflict_is_not_hidden(self):
        e = received()
        changed = deepcopy(e); changed['reference'] = 'OTHER'
        with self.assertRaisesRegex(ValueError, 'ID conflict'):
            ap_delivery([self.document(decision='POST', journal_entry=changed)], self.context([e]), 'full')

    def test_scope_exclusion_is_declared_but_does_not_hide_validation_failures(self):
        self.put('chart_of_accounts', [{'account': a} for a in ('62940000', '40000000')])
        e = entry('OTHER', '1100', [line('62940000', 10, cc='CC-1100'), line('40000000', -10)])
        row = self.document(decision='POST', journal_entry=e)
        delivered, audit = ap_delivery([row], self.context(), 'intercompany')
        self.assertEqual(delivered, [])
        self.assertTrue(audit['excluded_entries'][0]['validation_diagnostics'])
        with self.assertRaisesRegex(ValueError, 'Invalid AP delivery'):
            ap_delivery([row], self.context(), 'full')

    def test_pooling_link_uses_statement_and_erp_not_ic_fixture(self):
        entries, upstream = self.setup_pool()
        ctx = self.context(entries)
        statement = {'bank_line': 'BANK-MISSING', 'booking_date': '2028-02-22', 'currency': 'EUR', 'amount': -777}
        adjustment = {'category': 'POOLING_NOT_BOOKED', 'ref': 'BANK-SOURCE-REF',
                      'lines': upstream.banks.entries[0].entry['lines']}
        bank = {'account': 'B-1200', 'unmatched_bank': [{'bank_line': 'BANK-MISSING', 'category': 'POOLING_NOT_BOOKED', 'amount': -777}]}
        ident, proof = _pool_link(bank, adjustment, ctx, {ident: statement for ident in ('BANK-MISSING',)})
        self.assertEqual(ident, 'BANK-MISSING')
        self.assertEqual(proof['original_mirror_reference'], 'POOL-MISSING')
        self.assertEqual(proof['original_mirror_entry'], 'POOL-H')

    def test_pooling_missing_or_ambiguous_bank_link_fails(self):
        entries, upstream = self.setup_pool()
        ctx = self.context(entries)
        a = {'category': 'POOLING_NOT_BOOKED', 'ref': 'X', 'lines': upstream.banks.entries[0].entry['lines']}
        bank = {'account': 'B-1200', 'unmatched_bank': []}
        with self.assertRaisesRegex(ValueError, 'not unique'):
            _pool_link(bank, a, ctx, {})
        bank['unmatched_bank'] = [{'bank_line': 'ABSENT', 'category': 'POOLING_NOT_BOOKED', 'amount': -777}]
        with self.assertRaisesRegex(ValueError, 'absent statement'):
            _pool_link(bank, a, ctx, {})


class PolicyCompletenessTests(SyntheticFixture):
    def test_every_supported_unreceived_invoice_is_reported_without_a_fixed_row_count(self):
        from kalmora.ic import Allocation
        invoices = [issued('REF-' + company, receiver=company) for company in ('1100', '1200', '2100', '3100')]
        allocations = {('1000', c, 'REF-' + c): Allocation('62940000', 'CC-' + c, None, E)
                       for c in ('1100', '1200', '2100', '3100')}
        result = self.solve(invoices, replace(self.upstream, invoice_allocations=allocations))
        self.assertTrue(result.complete)
        self.assertEqual({f.responsible for f in result.findings}, {'1100', '1200', '2100', '3100'})
        self.assertTrue(all(f.cause == 'INVOICE_IN_TRANSIT' for f in result.findings))
