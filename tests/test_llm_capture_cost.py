import asyncio
from decimal import Decimal
import tempfile
import unittest

from kalmora.llm.client import AsyncLLMClient, LLMConfig, LLMError, ProviderResponse
from kalmora.runlog import RunRecorder


try:
    from pydantic import BaseModel, StrictInt
except ImportError:
    BaseModel = StrictInt = None


@unittest.skipUnless(BaseModel is not None, 'optional llm extra')
class CaptureCostTests(unittest.TestCase):
    def test_cost_covers_every_attempt_and_preserves_unknown(self):
        class Result(BaseModel):
            value: StrictInt

        for unknown in (False, True):
            with self.subTest(unknown=unknown), tempfile.TemporaryDirectory() as root:
                class Provider:
                    attempts = 0

                    async def invoke(self, request):
                        self.attempts += 1
                        if self.attempts == 1:
                            raw = {} if unknown else {'usage': {'input_tokens': 10, 'output_tokens': 1}}
                            raise LLMError('rate_limit', raw=raw)
                        return ProviderResponse({'status': 'completed', 'output': [],
                                                 'usage': {'input_tokens': 20, 'output_tokens': 2}}, Result(value=1))

                config = LLMConfig('gpt-6-luna', Decimal('1'), Decimal('0.0000001'),
                                   Decimal('0.0000005'), 'test rates', retry_base_seconds=0.001)
                with RunRecorder(root, ['capture-cost-test']) as recorder:
                    completion = asyncio.run(AsyncLLMClient(config, recorder, provider=Provider()).complete(Result, 'Typed result', 'Return value1'))
                    self.assertEqual(len(recorder.report['calls']), 2)
                    self.assertEqual(len(completion.request_metadata['attempt_metrics']), 2)
                    expected = None if unknown else '0.0000045'
                    self.assertEqual(completion.request_metadata['capture_cost_usd'], expected)
                    self.assertEqual(completion.request_metadata['attempt_metrics'][0]['error'], 'rate_limit')
                    self.assertIsNone(completion.request_metadata['attempt_metrics'][1]['error'])
