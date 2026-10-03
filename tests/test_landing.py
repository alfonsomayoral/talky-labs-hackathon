"""Loader acceptance checks run with the optional landing extra installed."""
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from kalmora.data import PhaseData
from kalmora.facts import DocumentFacts, Evidence, Fact
from kalmora.landing import LandingStore

HAS_DUCKDB = importlib.util.find_spec('duckdb') is not None


@unittest.skipUnless(HAS_DUCKDB, 'Install the landing extra to run DuckDB acceptance checks')
class LandingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.phase = self.root/'phase_custom'
        for area in ['tasks', 'erp', 'inbox/ap/D1', 'bank/ACCOUNT', 'golden']:
            (self.phase/area).mkdir(parents=True)
        self.write('tasks/close.json', {'month': '2027-02', 'steps': ['ACCRUAL']})
        self.write('tasks/ap_documents.json', ['D1'])
        self.write('erp/companies.json', [{'code': '0001', 'currency': 'EUR'}])
        (self.phase/'erp/fx_rates.jsonl').write_text('{"date":"2027-02-01","base":"EUR","currency":"USD","rate":0.923456789}\n')
        self.write('inbox/ap/D1/message.json', {'doc_id': 'D1', 'attachments': ['invoice.pdf', 'invoice.xml'], 'received_at': '2027-02-03'})
        (self.phase/'inbox/ap/D1/invoice.pdf').write_bytes(b'%PDF fixture original')
        (self.phase/'inbox/ap/D1/invoice.xml').write_text('<Invoice/>')
        self.write('golden/secret.json', {'never': 'load'})
        self.db = self.root/'landing.duckdb'

    def write(self, name, value):
        (self.phase/name).write_text(json.dumps(value), encoding='utf-8')

    def facts(self, name='invoice.pdf', **fields):
        path = self.phase/'inbox/ap/D1'/name
        return DocumentFacts(hashlib.sha256(path.read_bytes()).hexdigest(), 'test@1', {
            key: [Fact(value, Evidence(name, key))] for key, value in fields.items()})

    def test_idempotent_rebuild_and_exact_erp_adapter(self):
        with LandingStore(self.db) as store:
            counts = store.import_phase(self.phase)
            self.assertEqual(counts['source_file'], 7)
            self.assertEqual(counts['document'], 2)
            self.assertEqual(store.import_phase(self.phase), counts)
            self.assertEqual(store.table('fx_rates')[0]['rate'], Decimal('0.923456789'))
            self.assertEqual(store.get('companies', '0001')['code'], '0001')
            self.assertEqual(store.table('tasks/ap_documents'), ['D1'])
            self.assertFalse(any('golden' in row['rel_path'] for row in store.rows('source_file')))
            for name in ['golden/secret', '../golden/secret', 'inbox/ap/D1/message', 'erp/unknown']:
                with self.subTest(name=name), self.assertRaises((ValueError, KeyError)):
                    store.table(name)
            with self.assertRaises(KeyError): store.rows('read_json')
            with self.assertRaises(ValueError): store.rows('source_file', **{'rel_path) OR 1=1--': 'x'})
        with LandingStore(self.root/'rebuilt.duckdb') as rebuilt:
            self.assertEqual(rebuilt.import_phase(self.phase), counts)
        shutil.rmtree(self.phase/'golden')
        with LandingStore(self.db) as reopened:
            self.assertEqual(reopened.import_phase(self.phase), counts)
            self.assertEqual(reopened.find('companies', code='0001'), [{'code': '0001', 'currency': 'EUR'}])

    def test_parsing_failure_does_not_discard_valid_files(self):
        (self.phase/'erp/bad.jsonl').write_text('{broken\n')
        (self.phase/'inbox/ap/D1/invoice.xml').write_text('<broken')
        with LandingStore(self.db) as store:
            counts = store.import_phase(self.phase)
            self.assertEqual(counts['parse_issue'], 2)
            self.assertEqual(len(store.rows('source_file', status='FAILED')), 2)
            self.assertEqual(store.get('companies', '0001')['code'], '0001')
            self.assertEqual(store.import_phase(self.phase), counts)

    def test_unreadable_source_records_issue_without_invented_hash(self):
        original_read = Path.read_bytes
        def selective_read(path):
            if path.name == 'invoice.pdf':
                raise PermissionError('fixture cannot read source')
            return original_read(path)
        with LandingStore(self.db) as store, patch.object(Path, 'read_bytes', selective_read):
            store.import_phase(self.phase)
            failed = store.rows('source_file', status='FAILED')[0]
            self.assertIsNone(failed['sha256'])
            self.assertEqual(store.rows('parse_issue')[0]['code'], 'READ_ERROR')
            self.assertEqual(store.get('companies', '0001')['code'], '0001')
            with self.assertRaisesRegex(ValueError, 'unreadable'):
                store.import_phase(self.phase)

    def test_tampering_and_symlinks_are_rejected(self):
        with LandingStore(self.db) as store:
            store.import_phase(self.phase)
            self.write('erp/companies.json', [{'code': 'tampered'}])
            with self.assertRaises(ValueError): store.import_phase(self.phase)
            with self.assertRaises(ValueError): store.get('companies', '0001')
        (self.phase/'erp/leak.json').symlink_to(self.phase/'golden/secret.json')
        with LandingStore(self.root/'other.duckdb') as store:
            with self.assertRaises(ValueError): store.import_phase(self.phase)
            self.assertEqual(store.counts()['source_file'], 0)

    def test_facts_remain_separate_exact_and_transactional(self):
        original = (self.phase/'inbox/ap/D1/invoice.pdf').read_bytes()
        with LandingStore(self.db) as store:
            store.import_phase(self.phase)
            pdf = self.facts(net='12.34', rate=Decimal('0.923456789'), net_cents=1234,
                             lines=[{'kind': 'ITEM', 'quantity_milli': 2000, 'amount_cents': 1234}])
            store.store_facts('inbox/ap/D1/invoice.pdf', pdf)
            store.store_facts('inbox/ap/D1/invoice.pdf', pdf)
            xml = self.facts('invoice.xml', net_cents=9999)
            store.store_facts('inbox/ap/D1/invoice.xml', xml)
            docs = store.rows('document')
            self.assertEqual({doc['net_cents'] for doc in docs}, {1234, 9999})
            parsed = DocumentFacts.from_dict(json.loads(next(doc['facts_json'] for doc in docs if doc['filename'] == 'invoice.pdf')))
            self.assertEqual(parsed.fields['rate'][0].value, Decimal('0.923456789'))
            self.assertEqual(parsed.fields['net'][0].value, '12.34')
            self.assertEqual(len(store.rows('document_line')), 1)
            self.assertIs(type(store.rows('document_line')[0]['amount_cents']), int)
            with self.assertRaises(ValueError): store.store_facts('inbox/ap/D1/invoice.pdf', self.facts(net_cents=1235))
        self.assertEqual((self.phase/'inbox/ap/D1/invoice.pdf').read_bytes(), original)

    def test_conflicting_facts_and_float_rejection(self):
        with LandingStore(self.db) as store:
            store.import_phase(self.phase)
            facts = self.facts(net_cents=100)
            facts.fields['net_cents'].append(Fact(200, Evidence('invoice.pdf', 'other-total')))
            store.store_facts('inbox/ap/D1/invoice.pdf', facts)
            self.assertIsNone(store.rows('document', filename='invoice.pdf')[0]['net_cents'])
            self.assertEqual(store.rows('parse_issue')[0]['code'], 'FIELD_CONFLICT')
            with self.assertRaises(ValueError): store.store_facts('inbox/ap/D1/invoice.xml', self.facts('invoice.xml', net_cents=1.25))
            with self.assertRaises(ValueError): store.store_facts('inbox/ap/D1/invoice.xml', self.facts('invoice.xml', net_cents='125'))
            self.assertIsNone(store.rows('document', filename='invoice.xml')[0]['facts_json'])

    def test_owner_thread_and_second_writer(self):
        with LandingStore(self.db) as store:
            with self.assertRaises(RuntimeError): LandingStore(self.db)
            errors = []
            def other_thread():
                try: store.import_phase(self.phase)
                except RuntimeError as exc: errors.append(str(exc))
            thread = threading.Thread(target=other_thread)
            thread.start()
            thread.join()
            self.assertEqual(len(errors), 1)

    def test_missing_attachment_and_schema_version(self):
        self.write('inbox/ap/D1/message.json', {'doc_id': 'D1', 'attachments': ['missing.pdf']})
        self.write('tasks/ap_documents.json', 'D1')
        with LandingStore(self.db) as store:
            store.import_phase(self.phase)
            self.assertEqual({row['code'] for row in store.rows('parse_issue')}, {'ATTACHMENT_MISSING', 'PARSE_ERROR'})
            self.assertEqual(store.counts()['document'], 0)
        import duckdb
        with duckdb.connect(str(self.db)) as connection:
            connection.execute("UPDATE landing_meta SET value='99' WHERE key='schema_version'")
        with self.assertRaisesRegex(ValueError, 'schema version'):
            LandingStore(self.db)

    def test_bank_original_and_twin_with_mismatch(self):
        payload = 'Cuenta,00001,Moneda,EUR,Periodo,01/02/2027 al 28/02/2027,Saldo inicial,10.00\nFecha,Concepto,Referencia,Clave de rastreo,Cargo,Abono,Saldo\n03/02/2027,Original full text,REF-0001,key,0.00,1.23,11.23\n'
        (self.phase/'bank/ACCOUNT/2027-02.csv').write_text(payload)
        (self.phase/'bank/ACCOUNT/2027-02.lines.jsonl').write_text('{"bank_line":"B001","booking_date":"2027-02-03","value_date":"2027-02-03","amount":123,"currency":"EUR","text":"truncated"}\n')
        with LandingStore(self.db) as store:
            store.import_phase(self.phase)
            line = store.rows('bank_line')[0]
            self.assertEqual(line['amount_cents'], 123)
            self.assertEqual(line['reference'], 'REF-0001')
            self.assertEqual(line['text_full'], 'Original full text')
            self.assertTrue(store.rows('bank_statement')[0]['chain_ok'])
        twin = self.phase/'bank/ACCOUNT/2027-02.lines.jsonl'
        twin.write_text(twin.read_text().replace('123', '124'))
        with LandingStore(self.root/'badbank.duckdb') as store:
            store.import_phase(self.phase)
            self.assertEqual(store.counts()['bank_line'], 0)
            self.assertEqual(store.rows('parse_issue')[0]['code'], 'TWIN_MISMATCH')

    def test_malformed_bank_amount_is_a_parse_issue(self):
        payload = 'Cuenta,00001,Moneda,EUR,Periodo,01/02/2027 al 28/02/2027,Saldo inicial,broken\nFecha,Concepto,Referencia,Clave de rastreo,Cargo,Abono,Saldo\n'
        (self.phase/'bank/ACCOUNT/2027-02.csv').write_text(payload)
        (self.phase/'bank/ACCOUNT/2027-02.lines.jsonl').write_text('')
        with LandingStore(self.db) as store:
            store.import_phase(self.phase)
            self.assertEqual(store.rows('parse_issue')[0]['code'], 'PARSE_ERROR')
            self.assertEqual(store.counts()['bank_statement'], 0)
            self.assertEqual(store.get('companies', '0001')['code'], '0001')

    def test_fact_write_rolls_back_invalid_line(self):
        with LandingStore(self.db) as store:
            store.import_phase(self.phase)
            bad = self.facts(net_cents=100, lines=[{'kind': 'WRONG', 'amount_cents': 100}])
            with self.assertRaises(Exception): store.store_facts('inbox/ap/D1/invoice.pdf', bad)
            self.assertIsNone(store.rows('document', filename='invoice.pdf')[0]['facts_json'])
            self.assertEqual(store.counts()['document_line'], 0)
            store.store_facts('inbox/ap/D1/invoice.pdf', self.facts(net_cents=100))


@unittest.skipUnless(HAS_DUCKDB and os.environ.get('KALMORA_LANDING_PHASE'), 'Set KALMORA_LANDING_PHASE for real-source validation')
class RealPhaseLandingTests(unittest.TestCase):
    def test_real_phase_catalog_reload_and_rebuild(self):
        phase = Path(os.environ['KALMORA_LANDING_PHASE'])
        source = PhaseData(phase)
        expected_paths = {p.relative_to(phase).as_posix() for p in phase.rglob('*') if p.is_file()
                          and p.relative_to(phase).parts[0] in {'erp', 'tasks', 'bank', 'inbox'}
                          and 'golden' not in p.relative_to(phase).parts and '__MACOSX' not in p.relative_to(phase).parts}
        with tempfile.TemporaryDirectory() as tmp:
            counts = []
            for filename in ['first.duckdb', 'rebuild.duckdb']:
                with LandingStore(Path(tmp)/filename) as store:
                    result = store.import_phase(phase)
                    counts.append(result)
                    self.assertEqual({row['rel_path'] for row in store.rows('source_file')}, expected_paths)
                    self.assertEqual(store.import_phase(phase), result)
                    self.assertEqual(store.table('companies'), source.companies)
                    self.assertEqual(store.table('tasks/ap_documents'), source.tasks['ap_documents'])
                    self.assertEqual(store.table('fx_rates'), source.table('fx_rates'))
                    self.assertEqual(store.table('journal_entries'), list(source.iter_journal()))
                    mirrors = {row['bank_line']: row for row in source.table('bank_lines')}
                    self.assertEqual(len(store.rows('bank_line')), len(mirrors))
                    for row in store.rows('bank_line'):
                        self.assertEqual(row['amount_cents'], mirrors[row['bank_line']]['amount'])
                        self.assertEqual(row['currency'], mirrors[row['bank_line']]['currency'])
                    self.assertTrue(all(row['chain_ok'] and row['twin_ok'] for row in store.rows('bank_statement')))
                    self.assertEqual(store.counts()['parse_issue'], 0)
            self.assertEqual(counts[0], counts[1])
            clean_phase = Path(tmp)/phase.name
            clean_phase.mkdir()
            for area in ['erp', 'tasks', 'bank', 'inbox']:
                shutil.copytree(phase/area, clean_phase/area)
            self.assertFalse((clean_phase/'golden').exists())
            with LandingStore(Path(tmp)/'without-golden.duckdb') as store:
                self.assertEqual(store.import_phase(clean_phase), counts[0])
