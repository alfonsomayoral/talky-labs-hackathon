import unittest
from kalmora.ledger import Ledger


class LedgerTests(unittest.TestCase):
    def test_invalid_line_does_not_mutate_ledger(self):
        ledger = Ledger()
        with self.assertRaisesRegex(ValueError, 'expected object'):
            ledger.add_entry({'company': '1100', 'lines': [None]}, event_id='BL1', stage='bank_import')
        self.assertEqual(ledger.entries, [])
        valid = {'company': '1100', 'lines': [{'account': '57200001', 'debit': 1, 'credit': 0}, {'account': '55500000', 'debit': 0, 'credit': 1}]}
        ledger.add_entry(valid, event_id='BL1', stage='bank_import')
        self.assertEqual(len(ledger.entries), 1)

    def test_restored_provenance_retains_duplicate_protection(self):
        entry={'company':'1100','lines':[{'account':'57200001','debit':100,'credit':0},{'account':'55500000','debit':0,'credit':100}]}
        ledger=Ledger();ledger.add_entry(entry,event_id='BL1',stage='bank_import')
        restored=Ledger.from_entries(ledger.entries)
        with self.assertRaises(ValueError):restored.add_entry(entry,event_id='BL1',stage='bank_import')
        restored.add_entry(entry,event_id='BL1',stage='cash_application')
        self.assertEqual(len(restored.entries),2)
        with self.assertRaises(ValueError):Ledger.from_entries(ledger.entries+ledger.entries)
        for malformed in (None,{'event_id':['BL1'],'stage':'bank_import'},{'event_id':'BL1'}):
            with self.assertRaises(ValueError):Ledger.from_entries([{**entry,'provenance':malformed}])

    def test_reference_balance_open_items_and_projection(self):
        original={"id":"1100-2026-1","company":"1100","lines":[{"line":3,"account":"43000000","partner":"C1","assignment":"INV1","debit":100,"credit":0,"amount_doc":125},{"line":4,"account":"57200001","debit":0,"credit":100}]}
        ledger=Ledger.from_entries([original]); projected=ledger.project()
        self.assertEqual(ledger.entries[0]["lines"][0]["book_line"],"1100-2026-1#3")
        self.assertEqual(ledger.balances()["1100","43000000"],100)
        self.assertEqual(ledger.open_items()["1100","43000000","C1","INV1"],100)
        projected._entries[0]["lines"][0]["debit"]=200
        self.assertEqual(ledger.balances()["1100","43000000"],100)
        self.assertNotIn("book_line",original["lines"][0])
        self.assertEqual(ledger.entries[0]["lines"][0]["amount_doc"],125)

    def test_company_separation_and_duplicate_ids(self):
        def entry(company):return {"id":company,"company":company,"lines":[{"account":"57200001","debit":3,"credit":0}]}
        ledger=Ledger.from_entries([entry("1100"),entry("3100")])
        self.assertEqual(len(ledger.balances()),2)
        with self.assertRaises(ValueError): Ledger.from_entries([entry("1100"),entry("1100")])
