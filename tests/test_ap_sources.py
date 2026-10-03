"""AP inbox source recording/replay with an injected provider; no network."""
import asyncio
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from kalmora.documents.ap_sources import CONFIG_FILE, load_ap_sources, record_ap_sources
from kalmora.llm.client import AsyncLLMClient, LLMConfig, ProviderResponse
from kalmora.runlog import RunRecorder

try:
    from kalmora.documents.extractor import output_models
    output_models()
except ImportError:
    output_models = None

TEXT = 'FACTURA {number} Total 12.34'
FACTURAE = ('<fe:Facturae xmlns:fe="urn:facturae"><FileHeader><SchemaVersion>3.2.2</SchemaVersion></FileHeader>'
            '<Invoices><Invoice><InvoiceHeader><InvoiceNumber>X-1</InvoiceNumber></InvoiceHeader></Invoice></Invoices></fe:Facturae>')


class Provider:
    """Answers from the prompt's own text block; refuses one source."""
    def __init__(self):
        self.calls = []

    async def invoke(self, request):
        document = json.loads(request.prompt)['untrusted_document']
        self.calls.append(document['path'])
        if 'T2' in document['path']:
            return ProviderResponse({'status': 'completed', 'output': [{'content': [{'type': 'refusal'}]}]})
        [block] = document['blocks']
        ExtractionOutput, _ = output_models()
        title, number, _, total = block['text'].split()
        observations = [{'field': field, 'value': value, 'kind': 'OBSERVED', 'block_id': block['id'],
                         'quote': value, 'image_page': None, 'image_sha256': None}
                        for field, value in (('document_type_hint', title), ('document_number', number),
                                             ('gross', total))]
        output = ExtractionOutput.model_validate({'observations': observations, 'unknowns': []})
        return ProviderResponse({'status': 'completed', 'output': [],
                                 'usage': {'input_tokens': 100, 'output_tokens': 10}}, output)


@unittest.skipUnless(output_models is not None, 'optional llm extra')
class APSourcesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.phase, self.state = root / 'phase_dev', root / 'state'
        (self.phase / 'tasks').mkdir(parents=True)
        (self.phase / 'tasks/close.json').write_text('{"month": "2026-07"}')
        (self.phase / 'tasks/ap_documents.json').write_text('["T1", "T2"]')
        for doc_id in ('T1', 'T2'):
            folder = self.phase / 'inbox/ap' / doc_id
            folder.mkdir(parents=True)
            (folder / 'invoice.txt').write_text(TEXT.format(number='F-' + doc_id))
            (folder / 'message.json').write_text(json.dumps({
                'doc_id': doc_id, 'channel': 'email', 'received_at': '2026-07-02T08:36:00',
                'from': 'billing@vendor.example', 'to': 'ap@kalmora.example', 'subject': 'Factura',
                'body': '', 'attachments': ['invoice.txt']}))
        (self.phase / 'inbox/ap/T1/facturae.xml').write_text(FACTURAE)
        self.provider = Provider()

    def record(self):
        config = LLMConfig('gpt-6-luna', Decimal('1'), Decimal('0.0000001'), Decimal('0.0000005'), 'test rates')
        with RunRecorder(self.state / 'runs', ['test']) as run:
            return asyncio.run(record_ap_sources(self.phase, self.state, AsyncLLMClient(config, run, provider=self.provider)))

    def test_replay_returns_message_and_normalized_facts_without_provider(self):
        summary = self.record()
        self.assertEqual((summary['attachments'], summary['accepted']), (2, 1))
        self.assertEqual(summary['failed'], [{'path': 'inbox/ap/T2/invoice.txt', 'error': 'refusal'}])
        calls = len(self.provider.calls)
        sources = load_ap_sources(self.phase, self.state)
        self.assertEqual(len(self.provider.calls), calls)
        self.assertEqual(sorted(sources), ['T1', 'T2'])
        task = sources['T1']
        self.assertEqual((task.message.received_at, task.message.channel, task.message.sender),
                         ('2026-07-02T08:36:00', 'email', 'billing@vendor.example'))
        self.assertEqual(task.message.attachments, ('invoice.txt',))
        xml, attachment = task.attachments
        self.assertEqual(xml.facts.fields['document_number'][0].value, 'X-1')
        self.assertIsNone(attachment.error)
        self.assertEqual(attachment.facts.fields['document_number'][0].value, 'F-T1')
        self.assertEqual(attachment.normalized.facts.fields['gross_cents'][0].value, 1234)
        self.assertEqual(attachment.classification.document_type, 'INVOICE')
        [refused] = sources['T2'].attachments
        self.assertEqual((refused.facts, refused.error), (None, 'refusal'))
        # Rerunning record reuses accepted captures and retries only the failure.
        self.record()
        self.assertEqual(self.provider.calls[calls:], ['inbox/ap/T2/invoice.txt'])

    def test_missing_recordings_are_explicit_errors(self):
        self.record()
        (self.state / 'recordings').rename(self.state / 'moved')
        sources = load_ap_sources(self.phase, self.state)
        self.assertEqual([a.error for task in sources.values() for a in task.attachments], [None, 'missing', 'missing'])
        (self.state / CONFIG_FILE).unlink()
        with self.assertRaises(FileNotFoundError):
            load_ap_sources(self.phase, self.state)


if __name__ == '__main__':
    unittest.main()
