from pathlib import Path
from decimal import Decimal
import tempfile
import unittest
from kalmora.data import PhaseData, load_json, read_jsonl


class DataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for area in ['erp', 'tasks', 'golden', 'bank/B1']: (self.root/area).mkdir(parents=True)
        (self.root/'tasks/close.json').write_text('{"month":"2026-07"}')
        (self.root/'erp/companies.json').write_text('[{"code":"1000"}]')
        (self.root/'erp/ap_invoices.jsonl').write_text('{"doc_id":"API1","company":"1000"}\n')
        (self.root/'erp/tax_codes.json').write_text('{"tax_codes":{"S21":{"rate":2100}}}')
        (self.root/'bank/B1/2026-07.lines.jsonl').write_text('{"bank_line":"BL1"}\n')
        self.data = PhaseData(self.root)

    def test_entities_tasks_and_bank(self):
        self.assertEqual(self.data.month, '2026-07')
        self.assertEqual(self.data.get('companies', '1000')['code'], '1000')
        self.assertEqual(self.data.get('ap_invoices', 'API1')['doc_id'], 'API1')
        self.assertEqual(self.data.get('tax_codes', 'S21')['rate'], 2100)
        self.assertEqual(len(self.data.find('ap_invoices', company='1000')), 1)
        self.assertEqual(self.data.tasks['close']['month'], '2026-07')
        self.assertEqual(list(self.data.bank_lines('B1', '2026-07'))[0]['bank_line'], 'BL1')
        self.assertEqual(list(self.data.bank_lines('B1', '2026-06')), [])

    def test_golden_and_indirect_escape(self):
        (self.root/'golden/secret.json').write_text('{}')
        (self.root/'erp/leak.json').symlink_to(self.root/'golden/secret.json')
        for name in ['golden/secret', '../golden/secret', 'erp/leak', '/tmp/secret']:
            with self.subTest(name=name), self.assertRaises(ValueError): self.data.table(name)
        with self.assertRaises(ValueError): load_json(self.root/'golden/secret.json')

    def test_malformed_and_ambiguous_rows(self):
        path = self.root/'erp/bad.jsonl'
        path.write_text('{"id":"same"}\n{"id":"same"}\n')
        with self.assertRaises(ValueError): self.data.get('bad', 'same')
        path.write_text('{}\n[1]\n')
        with self.assertRaisesRegex(ValueError, ':2:'): list(read_jsonl(path))
        path.write_text('{')
        with self.assertRaises(ValueError): load_json(path)

    def test_exact_fractional_values_and_integer_amounts(self):
        path = self.root/'erp/rates.json'
        path.write_text('{"rate":0.923456789,"amount":123456}')
        row = load_json(path)
        self.assertEqual(row['rate'], Decimal('0.923456789'))
        self.assertIsInstance(row['rate'], Decimal)
        self.assertIs(type(row['amount']), int)
        path = self.root/'erp/rates.jsonl'
        path.write_text('{"rate":0.923456789,"amount":123456}\n')
        row = list(read_jsonl(path))[0]
        self.assertEqual(row['rate'], Decimal('0.923456789'))
        self.assertIs(type(row['amount']), int)
        for constant in ['NaN', 'Infinity', '-Infinity']:
            path.write_text('{"rate":' + constant + '}')
            with self.subTest(constant=constant):
                with self.assertRaises(ValueError): load_json(path)
                with self.assertRaises(ValueError): list(read_jsonl(path))
