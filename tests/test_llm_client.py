import asyncio
from dataclasses import replace
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from kalmora.llm.client import (AsyncLLMClient, ImageInput, LLMConfig, LLMError,
                                OpenAIResponsesProvider, ProviderResponse, sanitize)
from kalmora.runlog import RunRecorder

try:
    from pydantic import BaseModel, ConfigDict
    import httpx2
    from pydantic_ai import Agent
except ImportError:
    BaseModel = None

if BaseModel is not None:
    class Extracted(BaseModel):
        model_config = ConfigDict(strict=True, extra="forbid")
        amount_cents: int
        currency: str


def config(**changes):
    return replace(LLMConfig("gpt-6-luna", Decimal("1"), Decimal("0.000001"),
                             Decimal("0.000002"), "offline fixture tariff", max_attempts=1,
                             retry_base_seconds=0.001), **changes)


def body(text='{"amount_cents":123,"currency":"EUR"}', **changes):
    return {"id": "resp_fixture", "object": "response", "created_at": 0,
            "model": "gpt-6-luna", "status": "completed", "error": None,
            "incomplete_details": None, "instructions": None,
            "metadata": {}, "tools": [], "tool_choice": "auto", "parallel_tool_calls": False,
            "temperature": 1, "top_p": 1,
            "output": [{"id": "msg_fixture", "type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
            **changes}


class LazyImportTests(unittest.TestCase):
    def test_nested_credentials_are_sanitized_inside_text(self):
        raw = {'output': [{'text': 'prefixsk-proj-fake-secret suffix Bearer fake-token'}],
               'metadata': {'OPENAI_API_KEY': 'not-a-real-key', 'x-api-key': 'fixture'}}
        cleaned = sanitize(raw)
        serialized = json.dumps(cleaned)
        for secret in ('sk-proj-fake-secret', 'fake-token', 'not-a-real-key', 'fixture'):
            self.assertNotIn(secret, serialized)
        self.assertIn('[redacted]', serialized)
        self.assertIn('sk-proj-fake-secret', raw['output'][0]['text'])

    def test_client_import_has_no_optional_dependency_or_key_access(self):
        code = "import sys; from kalmora.llm.client import AsyncLLMClient; assert 'openai' not in sys.modules; assert 'pydantic_ai' not in sys.modules"
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_pricing_and_model(self):
        for change in ({"model": "gpt-6-astra"}, {"input_rate": None}, {"input_rate": 0.1},
                       {"budget_usd": Decimal("NaN")}, {"max_attempts": True}):
            with self.assertRaises(ValueError):
                config(**change)


@unittest.skipIf(BaseModel is None, "install the optional llm extra for provider tests")
class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_price_fetch_or_external_observability(self):
        from genai_prices import UpdatePrices
        from pydantic_ai.models.instrumented import InstrumentedModel

        async def handler(request):
            return httpx2.Response(200, json=body())

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'OPENAI_API_KEY':'offline-fixture'}):
            with (patch.object(Agent, '_instrument_default', True),
                  patch.object(UpdatePrices, 'start', side_effect=AssertionError('no updater')) as updater,
                  patch.object(httpx2, 'get', side_effect=AssertionError('no price download')) as price_get,
                  patch('socket.socket.connect', side_effect=AssertionError('no unmocked network')),
                  patch.object(InstrumentedModel, 'request', side_effect=AssertionError('no document export'))):
                with RunRecorder(directory, []) as recorder:
                    client = AsyncLLMClient(config(), recorder, provider=OpenAIResponsesProvider(transport=httpx2.MockTransport(handler)))
                    result = await client.complete(Extracted, 'instructions', 'invoice')
                self.assertEqual(result.output.amount_cents, 123)
                updater.assert_not_called()
                price_get.assert_not_called()

    async def test_real_framework_native_output_and_image_without_network(self):
        captured = []

        async def handler(request):
            captured.append(json.loads(request.content))
            return httpx2.Response(200, json=body())

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-fixture"}):
            with RunRecorder(directory, ["offline-client-test"]) as recorder:
                client = AsyncLLMClient(config(), recorder, provider=OpenAIResponsesProvider(transport=httpx2.MockTransport(handler)))
                result = await client.complete(Extracted, "Extract cents exactly", "invoice", images=(ImageInput(b"x" * 139_974, "image/jpeg"),))
            self.assertIsInstance(result.output, Extracted)
            self.assertEqual(result.output.amount_cents, 123)
            self.assertEqual(len(captured), 1)
            payload = captured[0]
            self.assertEqual(payload["max_output_tokens"], 2048)
            self.assertEqual(payload["text"]["format"]["type"], "json_schema")
            self.assertEqual(payload.get("tools", []), [])
            self.assertIn("data:image/jpeg;base64,", json.dumps(payload))
            self.assertEqual(len(recorder.report["calls"]), 1)
            self.assertEqual(recorder.report["cost"]["estimated_by_currency"], {"USD": "0.000020"})

    async def test_native_error_categories_no_hidden_retries(self):
        cases = [(200, body(output=[{"type":"message", "content":[{"type":"refusal", "refusal":"no"}]}]), "refusal"),
                 (200, body(status="incomplete", incomplete_details={"reason":"max_output_tokens"}), "incomplete"),
                 (200, body(text='{"amount_cents":true,"currency":"EUR"}'), "schema"),
                 (200, body(text='{"amount_cents":1.25,"currency":"EUR"}'), "schema"),
                 (200, body(text='{"amount_cents":"123","currency":"EUR"}'), "schema"),
                 (401, {"error":{"code":"invalid_api_key", "message":"sk-fixture-secret"}}, "authentication"),
                 (429, {"error":{"code":"insufficient_quota"}}, "quota"),
                 (429, {"error":{"code":"rate_limit_exceeded"}}, "rate_limit")]
        for status, response, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY":"offline-fixture"}):
                hits = []

                async def handler(request):
                    hits.append(request)
                    return httpx2.Response(status, json=response)

                with RunRecorder(directory, []) as recorder:
                    client = AsyncLLMClient(config(), recorder, provider=OpenAIResponsesProvider(transport=httpx2.MockTransport(handler)))
                    with self.assertRaises(LLMError) as caught:
                        await client.complete(Extracted, "instructions", "invoice")
                self.assertEqual(caught.exception.category, expected)
                self.assertEqual(len(hits), 1)
                self.assertEqual(len(recorder.report["calls"]), 1)
                self.assertNotIn("sk-fixture-secret", Path(recorder.path).read_text())

    async def test_network_timeout_and_bounded_retry_records_every_attempt(self):
        for failure, expected in ((httpx2.ConnectError("offline"), "network"), (httpx2.ReadTimeout("offline"), "timeout")):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY":"offline-fixture"}):
                hits = []

                async def handler(request):
                    hits.append(1)
                    raise failure

                with RunRecorder(directory, []) as recorder:
                    client = AsyncLLMClient(config(max_attempts=2), recorder, provider=OpenAIResponsesProvider(transport=httpx2.MockTransport(handler)))
                    with self.assertRaises(LLMError) as caught:
                        await client.complete(Extracted, "instructions", "invoice")
                self.assertEqual(caught.exception.category, expected)
                self.assertEqual(len(hits), 2)
                self.assertEqual(len(recorder.report["calls"]), 2)
                self.assertEqual(recorder.report["cost"]["unknown_calls"], 2)
                self.assertEqual(Decimal(recorder.report["llm_budget"]["unknown_reservations"]), config().reservation * 2)

    async def test_budget_retains_unknown_cost_and_rejects_next_attempt(self):
        class UnknownProvider:
            async def invoke(self, request):
                raise LLMError("network")

        cfg = config(max_attempts=2)
        cfg = replace(cfg, budget_usd=cfg.reservation)
        with tempfile.TemporaryDirectory() as directory:
            with RunRecorder(directory, []) as recorder:
                client = AsyncLLMClient(cfg, recorder, provider=UnknownProvider())
                with self.assertRaises(LLMError) as caught:
                    await client.complete(Extracted, "instructions", "invoice")
            self.assertEqual(caught.exception.category, "budget")
            self.assertEqual(len(recorder.report["calls"]), 1)
            self.assertEqual(recorder.report["llm_budget"]["available"], "0.000000")

    async def test_concurrency_and_pending_budget(self):
        class SlowProvider:
            active = 0
            maximum = 0

            async def invoke(self, request):
                self.active += 1
                self.maximum = max(self.maximum, self.active)
                await asyncio.sleep(0.02)
                self.active -= 1
                return ProviderResponse(body())

        provider = SlowProvider()
        with tempfile.TemporaryDirectory() as directory:
            with RunRecorder(directory, []) as recorder:
                client = AsyncLLMClient(config(concurrency=1), recorder, provider=provider)
                results = await asyncio.gather(*(client.complete(Extracted, "instructions", "invoice") for _ in range(3)))
            self.assertEqual(provider.maximum, 1)
            self.assertEqual(len(results), 3)
            self.assertEqual(len(recorder.report["calls"]), 3)
            self.assertEqual(Decimal(recorder.report["llm_budget"]["pending_reservations"]), 0)

    async def test_input_limit_before_attempt(self):
        class NeverProvider:
            async def invoke(self, request):
                raise AssertionError("must not dispatch")

        with tempfile.TemporaryDirectory() as directory:
            with RunRecorder(directory, []) as recorder:
                client = AsyncLLMClient(config(max_input_tokens=100), recorder, provider=NeverProvider())
                with self.assertRaises(LLMError) as caught:
                    await client.complete(Extracted, "instructions", "invoice")
            self.assertEqual(caught.exception.category, "input_limit")
            self.assertEqual(recorder.report["calls"], [])

    async def test_image_bytes_have_separate_cap_and_text_data_urls_stay_text(self):
        class NeverProvider:
            async def invoke(self, request):
                raise AssertionError('must not dispatch')

        with tempfile.TemporaryDirectory() as directory:
            with RunRecorder(directory, []) as recorder:
                client = AsyncLLMClient(config(max_image_bytes=100), recorder, provider=NeverProvider())
                with self.assertRaises(LLMError) as caught:
                    await client.complete(Extracted, 'instructions', 'invoice', (ImageInput(b'x' * 101),))
                self.assertEqual(caught.exception.category, 'image_limit')
                text_client = AsyncLLMClient(config(max_input_tokens=5000), recorder, provider=NeverProvider())
                with self.assertRaises(LLMError) as caught:
                    await text_client.complete(Extracted, 'instructions', 'data:image/png;base64,' + 'x' * 6000)
                self.assertEqual(caught.exception.category, 'input_limit')
            self.assertEqual(recorder.report['calls'], [])

    async def test_pending_reservation_blocks_concurrent_request(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        class PendingProvider:
            calls = 0

            async def invoke(self, request):
                self.calls += 1
                entered.set()
                await release.wait()
                return ProviderResponse(body())

        provider = PendingProvider()
        cfg = config(concurrency=2)
        cfg = replace(cfg, budget_usd=cfg.reservation)
        with tempfile.TemporaryDirectory() as directory:
            with RunRecorder(directory, []) as recorder:
                client = AsyncLLMClient(cfg, recorder, provider=provider)
                first = asyncio.create_task(client.complete(Extracted, "instructions", "invoice"))
                await entered.wait()
                with self.assertRaises(LLMError) as caught:
                    await client.complete(Extracted, "instructions", "invoice")
                self.assertEqual(caught.exception.category, "budget")
                self.assertEqual(Decimal(recorder.report["llm_budget"]["pending_reservations"]), cfg.reservation)
                release.set()
                await first
            self.assertEqual(provider.calls, 1)
            self.assertEqual(len(recorder.report["calls"]), 1)

    async def test_rate_limit_retry_succeeds_and_counts_both_attempts(self):
        hits = []

        async def handler(request):
            hits.append(1)
            if len(hits) == 1:
                return httpx2.Response(429, json={"error": {"code": "rate_limit_exceeded"}}, headers={"retry-after":"0"})
            return httpx2.Response(200, json=body())

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"OPENAI_API_KEY":"offline-fixture"}):
            with RunRecorder(directory, []) as recorder:
                client = AsyncLLMClient(config(max_attempts=2), recorder, provider=OpenAIResponsesProvider(transport=httpx2.MockTransport(handler)))
                result = await client.complete(Extracted, "instructions", "invoice")
            self.assertEqual(result.attempt, 2)
            self.assertEqual(len(recorder.report["calls"]), 2)
            self.assertEqual(recorder.report["cost"]["status"], "unknown")
            self.assertEqual(recorder.report["cost"]["unknown_calls"], 1)

    async def test_timeout_records_attempt_and_holds_unknown_reservation(self):
        class HangingProvider:
            async def invoke(self, request):
                await asyncio.sleep(1)

        with tempfile.TemporaryDirectory() as directory:
            with RunRecorder(directory, []) as recorder:
                cfg = config(timeout_seconds=0.01)
                client = AsyncLLMClient(cfg, recorder, provider=HangingProvider())
                with self.assertRaises(LLMError) as caught:
                    await client.complete(Extracted, "instructions", "invoice")
            self.assertEqual(caught.exception.category, "timeout")
            self.assertEqual(len(recorder.report["calls"]), 1)
            self.assertEqual(Decimal(recorder.report["llm_budget"]["unknown_reservations"]), cfg.reservation)
