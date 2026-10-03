"""Bounded typed Responses calls; API libraries are imported only for live use."""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import math
import os
import re
import time
from typing import Any, Generic, Protocol, TypeVar

from kalmora.runlog import RunRecorder

Output = TypeVar("Output")
RETRYABLE = {"rate_limit", "network", "timeout", "server"}
SECRET_KEYS = {"authorization", "api_key", "x_api_key", "openai_api_key", "access_token",
               "refresh_token", "headers", "password", "client_secret"}


def sanitize(value: Any) -> Any:
    """Keep JSON evidence while removing credential fields and bearer/key strings."""
    if isinstance(value, dict):
        return {key: ("[redacted]" if key.lower().replace("-", "_") in SECRET_KEYS else sanitize(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted]", value)
        return re.sub(r"(?i)bearer\s+[^\s\"']+", "Bearer [redacted]", value)
    return value


@dataclass(frozen=True)
class LLMConfig:
    model: str
    budget_usd: Decimal
    input_rate: Decimal
    output_rate: Decimal
    pricing_provenance: str
    reasoning_effort: str = "low"
    timeout_seconds: float | None = None
    max_attempts: int = 2
    concurrency: int = 2
    max_input_tokens: int = 200_000
    max_output_tokens: int | None = None
    model_output_capacity_tokens: int = 128_000
    image_token_reserve: int = 100_000
    max_image_bytes: int = 10_000_000
    image_detail: str = "auto"
    retry_base_seconds: float = 1.0
    retry_max_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model or "astra" in self.model.lower():
            raise ValueError("an explicit non-Astra model is required")
        for name in ("budget_usd", "input_rate", "output_rate"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be a finite nonnegative Decimal")
        if not isinstance(self.pricing_provenance, str) or not self.pricing_provenance:
            raise ValueError("known USD rates and their provenance are required")
        for name in ("max_attempts", "concurrency", "max_input_tokens", "model_output_capacity_tokens", "image_token_reserve", "max_image_bytes"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_output_tokens is not None and (type(self.max_output_tokens) is not int or self.max_output_tokens < 1):
            raise ValueError("max_output_tokens must be a positive integer or None")
        if self.max_output_tokens is not None and self.max_output_tokens > self.model_output_capacity_tokens:
            raise ValueError("Explicit output limit exceeds declared model capacity")
        for name in ("timeout_seconds", "retry_base_seconds", "retry_max_seconds"):
            value = getattr(self, name)
            if name == 'timeout_seconds' and value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if not isinstance(self.reasoning_effort, str) or self.reasoning_effort not in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("unsupported reasoning effort")
        if self.image_detail not in {"auto", "low", "high"}:
            raise ValueError("image_detail must be auto, low or high")

    @property
    def reservation(self) -> Decimal:
        output_bound = self.max_output_tokens if self.max_output_tokens is not None else self.model_output_capacity_tokens
        return self.input_rate * self.max_input_tokens + self.output_rate * output_bound

    @property
    def pricing(self) -> dict[str, Any]:
        return {"unit": "per_token", "currency": "USD", "input_rate": self.input_rate,
                "output_rate": self.output_rate, "provenance": self.pricing_provenance}


@dataclass(frozen=True)
class ImageInput:
    data: bytes
    media_type: str = "image/png"

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("image requires nonempty bytes")
        if self.media_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise ValueError("unsupported image media type")


@dataclass(frozen=True)
class ProviderRequest:
    output_type: type[Any]
    instructions: str
    prompt: str
    images: tuple[ImageInput, ...]
    config: LLMConfig


@dataclass(frozen=True)
class ProviderResponse:
    raw: dict[str, Any]
    output: Any = None


class Provider(Protocol):
    async def invoke(self, request: ProviderRequest) -> ProviderResponse: ...


class LLMError(Exception):
    """Operational failure, never a guessed fact or accounting decision."""
    def __init__(self, category: str, *, raw: dict[str, Any] | None = None,
                 attempted: bool = True, retry_after: float | None = None) -> None:
        super().__init__(category)
        self.category = category
        self.raw = sanitize(raw or {})
        self.attempted = attempted
        self.retry_after = retry_after


@dataclass(frozen=True)
class Completion(Generic[Output]):
    output: Output
    raw_response: dict[str, Any]
    request_metadata: dict[str, Any]
    attempt: int


def response_error(raw: dict[str, Any]) -> str | None:
    for item in raw.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "refusal":
                return "refusal"
    if raw.get("status") == "incomplete":
        return "incomplete"
    if raw.get("status") != "completed":
        return "provider_response"
    return None


def token_usage(raw: dict[str, Any]) -> tuple[int | None, int | None]:
    usage = raw.get("usage") or {}
    counts = tuple(usage.get(key) for key in ("input_tokens", "output_tokens"))
    return tuple(value if type(value) is int and value >= 0 else None for value in counts)


class AsyncLLMClient:
    """One budget shared by concurrent calls; every dispatched attempt is recorded."""
    def __init__(self, config: LLMConfig, recorder: RunRecorder, *, provider: Provider | None = None) -> None:
        self.config = config
        self.recorder = recorder
        self.provider = provider
        self._semaphore = asyncio.Semaphore(config.concurrency)
        self._lock = asyncio.Lock()
        self._committed = Decimal(0)
        self._pending = Decimal(0)
        self._unknown = Decimal(0)
        self._publish_budget()

    def _publish_budget(self) -> None:
        self.recorder.report["llm_budget"] = {
            "currency": "USD", "limit": str(self.config.budget_usd),
            "known_cost": str(self._committed), "pending_reservations": str(self._pending),
            "unknown_reservations": str(self._unknown),
            "available": str(self.config.budget_usd - self._committed - self._pending - self._unknown),
        }

    async def _reserve(self) -> None:
        async with self._lock:
            total = self._committed + self._pending + self._unknown + self.config.reservation
            if total > self.config.budget_usd:
                raise LLMError("budget", attempted=False)
            self._pending += self.config.reservation
            self._publish_budget()

    async def _settle(self, raw: dict[str, Any], attempted: bool) -> None:
        inputs, outputs = token_usage(raw)
        async with self._lock:
            self._pending -= self.config.reservation
            if attempted:
                if inputs is None or outputs is None:
                    self._unknown += self.config.reservation
                else:
                    self._committed += inputs * self.config.input_rate + outputs * self.config.output_rate
            self._publish_budget()

    async def complete(self, output_type: type[Output], instructions: str, prompt: str,
                       images: tuple[ImageInput, ...] = ()) -> Completion[Output]:
        if not callable(getattr(output_type, "model_validate_json", None)):
            raise ValueError("output_type must be a Pydantic model class")
        if not isinstance(instructions, str) or not isinstance(prompt, str):
            raise ValueError("instructions and prompt must be strings")
        images = tuple(images)
        if any(not isinstance(image, ImageInput) for image in images):
            raise ValueError("images must contain ImageInput")
        if any(len(image.data) > self.config.max_image_bytes for image in images):
            raise LLMError("image_limit", attempted=False)
        schema = output_type.model_json_schema()
        size_bound = (len(instructions.encode()) + len(prompt.encode()) +
                      len(json.dumps(schema).encode()) + 4096 +
                      len(images) * (128 + self.config.image_token_reserve))
        if size_bound > self.config.max_input_tokens:
            raise LLMError("input_limit", attempted=False)
        metadata = {"model": self.config.model, "reasoning_effort": self.config.reasoning_effort,
                    "max_input_tokens": self.config.max_input_tokens,
                    "max_output_tokens": self.config.max_output_tokens,
                    "timeout_seconds": self.config.timeout_seconds,
                    "model_output_capacity_tokens": self.config.model_output_capacity_tokens,
                    "image_token_reserve": self.config.image_token_reserve,
                    "max_image_bytes": self.config.max_image_bytes,
                    "instructions_sha256": hashlib.sha256(instructions.encode()).hexdigest(),
                    "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "output_schema_sha256": hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(),
                    "images": [{"sha256": hashlib.sha256(image.data).hexdigest(), "media_type": image.media_type,
                                "detail": self.config.image_detail}
                               for image in images]}
        request = ProviderRequest(output_type, instructions, prompt, images, self.config)
        attempt_metrics = []
        for attempt in range(1, self.config.max_attempts + 1):
            error = None
            async with self._semaphore:
                await self._reserve()
                start = time.perf_counter()
                raw: dict[str, Any] = {}
                attempted = True
                try:
                    if self.provider is None:
                        self.provider = OpenAIResponsesProvider()
                    async with asyncio.timeout(self.config.timeout_seconds):
                        response = await self.provider.invoke(request)
                    raw = sanitize(response.raw)
                    category = response_error(raw)
                    if category:
                        raise LLMError(category, raw=raw)
                    inputs, outputs = token_usage(raw)
                    if ((inputs is not None and inputs > self.config.max_input_tokens) or
                            (self.config.max_output_tokens is not None and outputs is not None and outputs > self.config.max_output_tokens)):
                        raise LLMError("usage_limit", raw=raw)
                    try:
                        output = response.output
                        if output is None:
                            text = "".join(content["text"] for item in raw.get("output", [])
                                           for content in item.get("content", []) if content.get("type") == "output_text")
                            output = output_type.model_validate_json(text)
                        elif not isinstance(output, output_type):
                            raise ValueError("provider returned a different output type")
                    except Exception:
                        raise LLMError("schema", raw=raw) from None
                except LLMError as failure:
                    error = failure
                    raw = failure.raw
                    attempted = failure.attempted
                except TimeoutError:
                    error = LLMError("timeout")
                except asyncio.CancelledError:
                    error = LLMError("cancelled")
                    raise
                except Exception:
                    error = LLMError("provider_error")
                finally:
                    await self._settle(raw, attempted)
                    if attempted:
                        inputs, outputs = token_usage(raw)
                        cost = (inputs * self.config.input_rate + outputs * self.config.output_rate
                                if inputs is not None and outputs is not None else None)
                        attempt_metrics.append({"attempt": attempt,
                                                "elapsed_seconds": time.perf_counter() - start,
                                                "estimated_cost_usd": str(cost) if cost is not None else None,
                                                "error": error.category if error else None})
                        self.recorder.record_call("openai" if isinstance(self.provider, OpenAIResponsesProvider) else "injected",
                                                  self.config.model, inputs, outputs, self.config.pricing,
                                                  {"provider_usage": raw.get("usage"), "raw_response": raw,
                                                   "request": metadata, "attempt": attempt,
                                                   "elapsed_seconds": time.perf_counter() - start,
                                                   "error": error.category if error else None})
            if error is None:
                known = all(m["estimated_cost_usd"] is not None for m in attempt_metrics)
                capture_cost = (sum((Decimal(m["estimated_cost_usd"]) for m in attempt_metrics), Decimal(0))
                                if known else None)
                return Completion(output, raw,
                                  {**metadata, "attempt_metrics": attempt_metrics,
                                   "capture_cost_usd": str(capture_cost) if capture_cost is not None else None}, attempt)
            if not attempted or error.category not in RETRYABLE or attempt == self.config.max_attempts:
                costs = [metric['estimated_cost_usd'] for metric in attempt_metrics]
                error.request_metadata = {**metadata, 'attempt_metrics': attempt_metrics,
                    'capture_cost_usd': str(sum((Decimal(c) for c in costs), Decimal(0))) if costs and all(c is not None for c in costs) else None}
                raise error
            delay = error.retry_after if error.retry_after is not None else self.config.retry_base_seconds * 2 ** (attempt - 1)
            await asyncio.sleep(min(max(delay, 0), self.config.retry_max_seconds))
        raise AssertionError("attempt loop exhausted")


class OpenAIResponsesProvider:
    """NativeOutput adapter with HTTP capture and both SDK/agent retries disabled."""
    def __init__(self, *, transport: Any = None) -> None:
        self.transport = transport

    async def invoke(self, request: ProviderRequest) -> ProviderResponse:
        attempted = False
        raw: dict[str, Any] = {}
        try:
            os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
            from openai import AsyncOpenAI
            import httpx2 as httpx
            from pydantic_ai import Agent, BinaryContent, NativeOutput
            from pydantic_ai.models.openai import OpenAIResponsesModel
            from pydantic_ai.providers.openai import OpenAIProvider
            from pydantic_ai.usage import UsageLimits

            async def before_send(http_request: Any) -> None:
                nonlocal attempted
                if attempted:
                    raise LLMError("hidden_retry", raw=raw)
                payload = json.loads(http_request.content)
                expected_urls = [f"data:{image.media_type};base64,{base64.b64encode(image.data).decode('ascii')}"
                                 for image in request.images]

                def bound_image_content(value: Any) -> Any:
                    if isinstance(value, list):
                        return [bound_image_content(item) for item in value]
                    if not isinstance(value, dict):
                        # Text remains untouched, including any data URL mentioned in prose.
                        return value
                    if value.get("type") == "input_image":
                        image_url = value.get("image_url")
                        if not isinstance(image_url, str) or image_url not in expected_urls:
                            raise LLMError("unexpected_image", attempted=False)
                        expected_urls.remove(image_url)
                        return {**value, "image_url": "[authorized inline image]"}
                    return {key: bound_image_content(item) for key, item in value.items()}

                payload["input"] = bound_image_content(payload.get("input", []))
                if expected_urls:
                    raise LLMError("unexpected_image", attempted=False)
                bound = (len(json.dumps(payload, ensure_ascii=False).encode()) + 4096
                         + len(request.images) * request.config.image_token_reserve)
                if bound > request.config.max_input_tokens:
                    raise LLMError("input_limit", attempted=False)
                attempted = True

            async def capture(http_response: Any) -> None:
                nonlocal raw
                await http_response.aread()
                try:
                    raw = sanitize(http_response.json())
                except ValueError:
                    raw = {"status": "invalid_json"}
                status = http_response.status_code
                if status >= 400:
                    code = (raw.get("error") or {}).get("code")
                    if status in (401, 403):
                        category = "authentication"
                    elif code in ("insufficient_quota", "billing_hard_limit_reached"):
                        category = "quota"
                    elif status == 429:
                        category = "rate_limit"
                    elif status >= 500:
                        category = "server"
                    else:
                        category = "request"
                    try:
                        retry_after = float(http_response.headers.get("retry-after", "nan"))
                        retry_after = retry_after if math.isfinite(retry_after) and retry_after >= 0 else None
                    except ValueError:
                        retry_after = None
                    raise LLMError(category, raw=raw, retry_after=retry_after)
                category = response_error(raw)
                if category:
                    raise LLMError(category, raw=raw)

            async with httpx.AsyncClient(transport=self.transport, event_hooks={"request": [before_send], "response": [capture]}) as http_client:
                async with AsyncOpenAI(http_client=http_client, max_retries=0, timeout=request.config.timeout_seconds) as sdk:
                    model = OpenAIResponsesModel(request.config.model, provider=OpenAIProvider(openai_client=sdk))
                    settings = {"openai_reasoning_effort": request.config.reasoning_effort,
                                "openai_store": False, "timeout": request.config.timeout_seconds}
                    if request.config.max_output_tokens is not None:
                        settings["max_tokens"] = request.config.max_output_tokens
                    agent = Agent(model, output_type=NativeOutput(request.output_type), instructions=request.instructions,
                                  retries=0, tools=(), model_settings=settings)
                    # Override process-global instrumentation settings; only M0 records audit.
                    agent.instrument = False
                    prompt = [request.prompt] + [BinaryContent(image.data, media_type=image.media_type,
                                                               vendor_metadata={"detail": request.config.image_detail})
                                               for image in request.images]
                    result = await agent.run(prompt, usage_limits=UsageLimits(request_limit=1), infer_name=False)
                    return ProviderResponse(raw, result.output)
        except LLMError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as error:
            names = []
            cause: BaseException | None = error
            seen = set()
            while cause is not None and id(cause) not in seen:
                seen.add(id(cause))
                names.append(type(cause).__name__)
                cause = cause.__cause__ or cause.__context__
            if not attempted:
                category = "configuration"
            elif any("Timeout" in name for name in names):
                category = "timeout"
            elif any("Connection" in name or "Connect" in name for name in names):
                category = "network"
            elif raw:
                category = "schema"
            else:
                category = "provider_error"
            raise LLMError(category, raw=raw, attempted=attempted) from None
