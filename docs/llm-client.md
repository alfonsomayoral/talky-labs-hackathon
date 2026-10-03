# Typed Responses client (#135)

`kalmora.llm.client` imports only the standard library and M0 `RunRecorder`.
Installing the optional provider dependencies or setting a key is unnecessary
for M0, replay and deterministic accounting. The replay layer consumes the same
output DTO outside this client; it must not initialize a provider or call
`complete` for replayed facts.

The tested provider versions are `pydantic-ai-slim[openai]==2.54.0`,
`openai==3.24.0` and `pydantic==2.13.5` on Python 3.12. The dependency extra is
maintained by the integration branch. Live use reads `OPENAI_API_KEY` through
the OpenAI SDK; application code never copies credentials into configuration,
prompts or reports. No real API call was performed for this implementation.

```python
from decimal import Decimal
from pydantic import BaseModel, ConfigDict
from kalmora.llm.client import AsyncLLMClient, ImageInput, LLMConfig
from kalmora.runlog import RunRecorder

class ExtractedAmount(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    amount_cents: int
    currency: str

# Rates are supplied explicitly from the applicable tariff, not built into code.
config = LLMConfig(
    model="gpt-6-luna", reasoning_effort="low",
    budget_usd=Decimal("1"), input_rate=input_rate_usd_per_token,
    output_rate=output_rate_usd_per_token, pricing_provenance=tariff_url_and_date,
    max_input_tokens=200_000, max_output_tokens=2048,
    concurrency=2, max_attempts=2, timeout_seconds=60,
)
with RunRecorder("outputs/runs", ["extract"]) as run:
    client = AsyncLLMClient(config, run)
    result = await client.complete(
        ExtractedAmount, instructions="Extract literal facts, never guess.",
        prompt="Read the attached invoice.",
        images=(ImageInput(page_png_bytes, media_type="image/png"),),
    )
    facts = result.output  # Actual ExtractedAmount, not an unvalidated dictionary.
```

The caller selects a supported model explicitly; Astra is rejected. Images are
nonempty local bytes with a PNG/JPEG/WebP/GIF MIME type, converted to PydanticAI
`BinaryContent` and inline Responses image input. No upload or tool permission
is needed. The client neither performs OCR nor verifies quote fidelity; the
document layer must validate page/hash/location against the original and review
image-only quotes against that image. Accounting remains deterministic: strict
DTOs must preserve integer cents and explicit currency/evidence, and the caller
must validate extracted facts before applying accounting rules.

`complete(output_type, instructions, prompt, images=())` returns
`Completion(output, raw_response, request_metadata, attempt)`. `output_type`
must be a Pydantic model. The provider uses `OpenAIResponsesModel` and
`NativeOutput`, no tools, no agent correction loop, `retries=0`, one agent
request, SDK `max_retries=0` and `store=False`. It never falls back to Chat
Completions. The caller can inject any asynchronous `Provider.invoke(request)`
returning `ProviderResponse(raw, output=None)` to test the same boundary without
a provider. A provider must perform exactly one external attempt and report
`LLMError(..., attempted=False)` for failures before dispatch.

Pinned PydanticAI/genai-prices source uses a bundled local price snapshot by
default; background price downloads require explicit `UpdatePrices.start()` or
`prices.update_in_background()`, neither of which this client calls. Framework
costs are never used for this client's reservations or M0 report. Every created
agent sets `instrument=False`, overriding a process-global instrumentation
default. Logfire/OpenTelemetry exporters are not configured here. An offline
regression forbids price updates/downloads, socket connections outside mocked
Responses transport and instrumented model requests, even with a global
instrumentation default enabled.

Each attempt first reserves `max_input_tokens * input_rate + max_output_tokens *
output_rate` under a shared asynchronous lock. One client owns the run budget;
do not construct multiple independent clients against the same run cap. A
semaphore bounds calls and releases while retry delays run. Known token usage
settles to exact Decimal cost. Missing/invalid usage holds the entire reservation
as unknown, including after timeout/network failure; it never becomes zero. A
new attempt cannot begin when known costs, unknown reservations and concurrent
pending reservations exhaust the cap. Rates must be known USD Decimal values;
include relevant input premiums/cache writes in the conservative supplied rate.

The input guard uses UTF-8 text/schema byte counts plus overhead and a
configurable image token envelope (`image_token_reserve`, default 100,000 per
image). Image bytes have a separate cap (`max_image_bytes`, default 10,000,000
per image); base64 bytes are not counted as text tokens. Before transmission the
generated HTTP JSON is checked again: only authorized `input_image.image_url`
values are replaced with a placeholder for text byte counting, and image
envelopes are added separately. Unexpected or missing images fail preflight.
Text prompts remain unchanged even if they contain data URLs. The image
envelope is a caller-selected conservative bound
for its chosen model and image dimensions; downsample pages or increase
`max_input_tokens` within the selected model's tariff/context limit. A 32,768
input cap cannot admit an image with the default 100,000 image envelope. Never
lower the envelope merely to bypass a rejected payload without validating the
model's image accounting. Actual reported usage over either cap produces
`usage_limit`, retains actual cost and prevents further budgeted work when
the run cap is exhausted. Output is provider-limited by `max_output_tokens`.
There is no server-side max-input-token setting: the input envelope is an
explicit conservative assumption, with actual usage checked after the response.

`LLMError.category` distinguishes `refusal`, `incomplete`, `schema`,
`authentication`, `quota`, `rate_limit`, `timeout`, `network`, `server`,
`request`, `provider_response`, `provider_error`, `configuration`, `input_limit`,
`image_limit`, `unexpected_image`, `usage_limit`, `hidden_retry` and `budget`. Only rate limits, network failures,
timeouts and server errors retry, bounded by `max_attempts` and capped
exponential delay or numeric `Retry-After`. No failure is an accounting decision.

Every dispatched attempt calls `RunRecorder.record_call`, including failures;
preflight/configuration/budget failures never pretend to be paid calls. The
call's `usage` contains provider usage, sanitized original JSON response,
request hashes/schema/image hashes, attempt, duration and category. Headers and
credential fields/strings are removed. No exception text or image bytes enter
the report. `report["llm_budget"]` shows known cost, pending and unknown
reservations and available USD; provider-reported unknown cost remains unknown
in the existing M0 cost summary. The enclosing recorder persists the report on
exit even when an exception propagates.

Offline validation:

```bash
PYTHONPATH=src PYDANTIC_AI_NO_BANNER=1 python -m unittest discover -s tests -p test_llm_client.py -v
```

These tests run a real PydanticAI native-output agent over a mocked HTTP
transport: text/image payload, typed strict cents, refusal, incomplete output,
schema, authentication, quota, rate limits, bounded recovery, SDK network/timeout
classification, unknown costs, concurrent reservations, concurrency and input
caps. Optional dependencies absent: provider tests skip, lazy-import/config
tests still run. Fixtures are invented and contain no golden data. Real text
and image acceptance is a separate opt-in integration smoke with an explicitly
approved tariff/budget; this module does not run it automatically.

References consulted: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[PydanticAI OpenAI](https://pydantic.dev/docs/ai/models/openai/),
[Native Output](https://pydantic.dev/docs/ai/core-concepts/output/),
[retry control](https://pydantic.dev/docs/ai/core-concepts/retries/).
