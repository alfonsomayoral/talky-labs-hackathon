import unittest
import os
import json
import zipfile
from kalmora.validation import validate_entry
from kalmora.ledger import Ledger

def balanced():
    return {"company":"1100","posting_date":"2026-07-31","lines":[{"account":"57200001","debit":100,"credit":0},{"account":"55500000","debit":0,"credit":100}]}

class ValidationTests(unittest.TestCase):
    def test_unhashable_references_return_errors_with_master_context(self):
        entry=balanced()
        entry['company']=['1100']
        entry['lines'][0].update(partner=['V1'],cost_center=['CC1'],wbs={'id':'W1'})
        context={'companies':{'1100'},'partners':{'V1'},'cost_centers':{'CC1'},'wbs':{'W1'}}
        errors=validate_entry(entry,context)
        for field in ('company','partner','cost_center','wbs'):
            self.assertTrue(any(field in error for error in errors),field)

    def test_balance_and_context(self):
        e=balanced();self.assertEqual(validate_entry(e),[])
        e['lines'][0]['debit']=101;self.assertTrue(any('unbalanced' in x for x in validate_entry(e)))
        e['lines'][0]['debit']=True;self.assertTrue(any('integer' in x for x in validate_entry(e)))
        self.assertTrue(validate_entry(balanced(),{'companies':{'3100'},'max_date':'2026-07-30'}))
        e=balanced();e['posting_date']='2026-02-30';self.assertTrue(validate_entry(e))

    def test_partner_cost_and_exceptions(self):
        e=balanced();e['lines'][0].update(account='60000000',cost_center='CC1',wbs='W1');self.assertTrue(any('exclusive' in x for x in validate_entry(e)))
        e['lines'][0].pop('wbs');self.assertTrue(validate_entry(e,{'cost_centers':{'CC1':{'company':'3100'}}}))
        e['lines'][1]['account']='40000000';self.assertTrue(any('partner' in x for x in validate_entry(e)))
        e['lines'][1]['partner']='V1';self.assertEqual(validate_entry(e),[])
        e['lines'][1]['partner']=True;self.assertTrue(validate_entry(e))
        e['lines'][1]['partner']='V1'
        e['lines'][0]={'account':'69400000','debit':100,'credit':0};self.assertEqual(validate_entry(e),[])

    def test_same_event_different_stage_and_repeated_stage(self):
        ledger=Ledger();entry=balanced()
        ledger.add_entry(entry,event_id='BL1',stage='bank_import')
        ledger.add_entry(entry,event_id='BL1',stage='cash_application')
        with self.assertRaises(ValueError):ledger.add_entry(entry,event_id='BL1',stage='cash_application')
        bad=balanced();bad['lines'][0]['debit']=101
        with self.assertRaises(ValueError):ledger.add_entry(bad,event_id='BL2',stage='bank_import')
        self.assertEqual(len(ledger.entries),2)


@unittest.skipUnless(os.environ.get('KALMORA_PARTICIPANT_ZIP'), 'set KALMORA_PARTICIPANT_ZIP for read-only organizer evaluation')
class OrganizerEvaluationTests(unittest.TestCase):
    def test_recorded_balance_and_all_golden_groups(self):
        with zipfile.ZipFile(os.environ['KALMORA_PARTICIPANT_ZIP']) as source:
            def rows(path):
                return [json.loads(line) for line in source.read('participant/phase_dev/'+path).decode().splitlines()]
            ledger=Ledger.from_entries(rows('erp/journal_entries.jsonl'))
            actual=ledger.balances()
            expected={(row['company'],row['account']):row['balance'] for row in rows('golden/trial_balance_recorded.jsonl')}
            self.assertEqual({key:value for key,value in actual.items() if value},{key:value for key,value in expected.items() if value})
            groups=[]
            for kind in ('ap','ar_billing','ar_cash','bank_rec','ic','close'):
                for row in rows('golden/'+kind+'.jsonl'):
                    if row.get('journal_entry'):groups.append(row['journal_entry'])
                    if row.get('adjustment'):groups.append({'company':row['adjustment'][0]['company'],'lines':row['adjustment']})
                    for adjustment in row.get('adjustments',[]):groups.append({'company':adjustment['lines'][0]['company'],'lines':adjustment['lines']})
            self.assertEqual(len(groups),435)
            for group in groups:
                self.assertEqual(sum(line['debit']-line['credit'] for line in group['lines']),0)
            # Real source inconsistency: API004469's 407 advance lacks its vendor
            # partner, required by policy §1. Keep the validator strict.
            invalid=[(group.get('id'),validate_entry(group)) for group in groups if validate_entry(group)]
            self.assertEqual(invalid,[('1100-2026-5100000822',['lines[1].partner: required for open-item account'])])
