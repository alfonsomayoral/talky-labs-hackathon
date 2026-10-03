"""Ollama adapter over the native ``/api/chat`` (not the OpenAI-compatible route), because only the native one lets
the request set ``num_ctx``: Ollama's default context (2,048 to 4,096 tokens) is smaller than this assistant's prompt."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .model import Finished, ModelError, ModelEvent, TextDelta, ToolCall, ToolSpec, Usage, new_call_id


class OllamaModel:
    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434", *, num_ctx: int = 32768,
                 think: bool = False, temperature: float = 0.2, keep_alive: str = "60m", timeout: float = 600.0,
                 client: httpx.AsyncClient | None = None) -> None:
        self.model, self.base_url, self.num_ctx, self.think = model, base_url.rstrip("/"), num_ctx, think
        self.temperature, self.keep_alive = temperature, keep_alive
        self.name = f"ollama:{model}"
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0))

    @staticmethod
    def convert(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "assistant" and m.get("tool_calls"):
                out.append({"role": "assistant", "content": m.get("content", ""),
                            "tool_calls": [{"function": {"name": c["name"], "arguments": c["arguments"]}}
                                           for c in m["tool_calls"]]})
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_name": m["name"], "content": m["content"]})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        return out

    async def warm(self, system: str, tools: list[ToolSpec] | None = None) -> float:
        """Load the model and prefill ``system`` so Ollama's prompt cache holds the stable prefix. Returns seconds."""
        import time
        started = time.monotonic()
        body = {"model": self.model, "stream": False, "think": False, "keep_alive": self.keep_alive,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": "ok"}],
                "options": {"num_ctx": self.num_ctx, "num_predict": 1, "temperature": 0}}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                              "parameters": t.input_schema}} for t in tools]
        try:
            response = await self._client.post(f"{self.base_url}/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise ModelError(f"Cannot reach Ollama at {self.base_url}: {type(exc).__name__}: {exc}") from None
        if response.status_code >= 400:
            raise ModelError(f"Ollama answered {response.status_code}: {response.text[:300]}")
        return time.monotonic() - started

    async def stream(self, system: str, messages: list[dict[str, Any]], tools: list[ToolSpec], *,
                     max_tokens: int) -> AsyncIterator[ModelEvent]:
        body: dict[str, Any] = {
            "model": self.model, "stream": True, "think": self.think, "keep_alive": self.keep_alive,
            "messages": [{"role": "system", "content": system}, *self.convert(messages)],
            "options": {"num_ctx": self.num_ctx, "temperature": self.temperature, "num_predict": max_tokens}}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                              "parameters": t.input_schema}} for t in tools]
        text, calls, usage, reason = [], [], Usage(), "stop"
        try:
            async with self._client.stream("POST", f"{self.base_url}/api/chat", json=body) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", "replace")[:500]
                    raise ModelError(f"Ollama answered {response.status_code}: {detail}")
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise ModelError(f"Ollama error: {chunk['error']}")
                    message = chunk.get("message") or {}
                    if message.get("content"):
                        text.append(message["content"])
                        yield TextDelta(message["content"])
                    for call in message.get("tool_calls") or []:
                        function = call.get("function") or {}
                        arguments = function.get("arguments") or {}
                        if isinstance(arguments, str):
                            arguments = json.loads(arguments or "{}")
                        calls.append(ToolCall(call.get("id") or new_call_id(), function.get("name", ""), dict(arguments)))
                    if chunk.get("done"):
                        usage = Usage(chunk.get("prompt_eval_count") or 0, chunk.get("eval_count") or 0)
                        reason = chunk.get("done_reason") or "stop"
        except httpx.HTTPError as exc:
            raise ModelError(f"Cannot reach Ollama at {self.base_url}: {type(exc).__name__}: {exc}") from None
        except json.JSONDecodeError as exc:
            raise ModelError(f"Ollama sent a malformed stream: {exc}") from None
        yield Finished("".join(text), calls, usage, "tool_calls" if calls else reason)
