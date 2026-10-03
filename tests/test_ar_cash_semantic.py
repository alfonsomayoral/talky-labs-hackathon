import unittest
import test_ar_cash as fixtures
from kalmora.ar_cash.semantic import review_ar_cash
from kalmora.data import PhaseData
from kalmora.documents.contracts import ResolutionResult


class SemanticCashTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.ArCashTests.setUp
    _json = fixtures.ArCashTests._json
    _jsonl = fixtures.ArCashTests._jsonl
    invoice = staticmethod(fixtures.ArCashTests.invoice)
    line = staticmethod(fixtures.ArCashTests.line)
    entry = fixtures.ArCashTests.entry

    def ambiguous(self):
        self._jsonl('erp/ar_invoices.jsonl', [self.invoice('INV-1', 10000), self.invoice('INV-2', 10000),
            self.invoice('FUTURE', 10000, date='2026-07-03'), self.invoice('USD', 10000, currency='USD'),
            self.invoice('OTHERCO', 10000, company='1200')])
        self._jsonl('erp/journal_entries.jsonl', [self.entry('POST', '2026-06-01', [
            self.line('43000000', 10000, 0, 'C1', name) for name in ['INV-1','INV-2','FUTURE','USD','OTHERCO']])])

    async def test_abstention_is_audited_with_bounded_source_candidates(self):
        self.ambiguous()
        requests = []
        class Resolver:
            async def resolve(self, request):
                requests.append(request)
                return ResolutionResult('AMBIGUOUS', (), (), 'No invoice reference in bank row')
        result = await review_ar_cash(PhaseData(self.phase), resolver=Resolver())
        self.assertEqual([c.id for c in requests[0].candidates], ['INV-1', 'INV-2'])
        self.assertEqual(result.reviews[0]['status'], 'AMBIGUOUS')
        self.assertEqual(result.reviews[0]['request_sha256'], requests[0].sha256)
        self.assertEqual(result.run.results[0].row['adjustment'], [])

    async def test_semantic_selection_never_authorizes_an_accounting_application(self):
        self.ambiguous()
        class Resolver:
            async def resolve(self, request):
                return ResolutionResult('SELECTED', ('INV-1',), ({
                    'source_sha256': request.document.source_sha256, 'block_id': 'BL1',
                    'quote': 'CLIENTE ALFA', 'source_value': 'CLIENTE ALFA',
                    'candidate_id': 'INV-1', 'candidate_attribute': 'name',
                    'candidate_value': 'Cliente Alfa, S.A.',
                },), 'Name association only')
        result = await review_ar_cash(PhaseData(self.phase), resolver=Resolver())
        self.assertEqual(result.reviews[0]['status'], 'SELECTED')
        self.assertFalse(result.reviews[0]['accounting_applied'])
        self.assertEqual(result.run.results[0].row['applications'], [])

    async def test_invented_ids_and_mutation_are_rejected(self):
        self.ambiguous()
        class Invalid:
            async def resolve(self, request):
                return ResolutionResult('SELECTED', ('MADE-UP',), (), 'guess')
        with self.assertRaises(ValueError):
            await review_ar_cash(PhaseData(self.phase), resolver=Invalid())
        class Mutation:
            async def resolve(self, request):
                request.candidates[0].attributes['balance'] = 1
                return ResolutionResult('NO_MATCH', (), (), 'changed')
        with self.assertRaises(ValueError):
            await review_ar_cash(PhaseData(self.phase), resolver=Mutation())

    async def test_limit_and_missing_resolver_produce_explicit_abstention(self):
        self.ambiguous()
        result = await review_ar_cash(PhaseData(self.phase))
        self.assertEqual(result.reviews[0]['status'], 'RESOLVER_UNAVAILABLE')
        result = await review_ar_cash(PhaseData(self.phase), max_candidates=1)
        self.assertEqual(result.reviews[0]['status'], 'CANDIDATE_LIMIT')

    async def test_prior_application_reduces_later_semantic_availability(self):
        import json
        self._jsonl('erp/ar_invoices.jsonl', [self.invoice('INV-1', 10000),
            self.invoice('INV-2', 3000, date='2026-07-03', due='2026-07-03')])
        journal = [json.loads(s) for s in (self.phase/'erp/journal_entries.jsonl').read_text().splitlines()]
        journal.append(self.entry('POST2', '2026-07-03', [self.line('43000000', 3000, 0, 'C1', 'INV-2')]))
        self._jsonl('erp/journal_entries.jsonl', journal)
        first = json.loads((self.phase/'bank/BIN-1100/2026-07.lines.jsonl').read_text())
        self._jsonl('bank/BIN-1100/2026-07.lines.jsonl', [first, dict(first, bank_line='BL2',
            amount=1000, value_date='2026-07-04', booking_date='2026-07-04')])
        self._json('tasks/ar_receipts.json', ['BL2','BL1'])
        result = await review_ar_cash(PhaseData(self.phase))
        self.assertEqual(len(result.reviews), 1)
        self.assertEqual(result.reviews[0]['bank_line'], 'BL2')
        self.assertEqual({c['id']: c['balance'] for c in result.reviews[0]['candidates']},
                         {'INV-1': 2000, 'INV-2': 3000})

    async def test_deterministic_result_does_not_call_resolver(self):
        class Unexpected:
            async def resolve(self, request):
                raise AssertionError('resolved receipt should not need semantic review')
        result = await review_ar_cash(PhaseData(self.phase), resolver=Unexpected())
        self.assertEqual(result.reviews, ())
        self.assertEqual(result.run.results[0].row['applications'], [{'invoice':'INV-1','amount':8000}])
