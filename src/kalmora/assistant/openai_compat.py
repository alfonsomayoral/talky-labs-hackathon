"""Adapter for OpenAI and any server that speaks Chat Completions (``/chat/completions``) with tools and streaming.

Chat Completions is used, not the Responses API, because the reasoning of reasoning models is not part of the
messages here, so nothing has to be carried across tool turns. The key is read from the environment by the caller
and never stored."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .model import Finished, ModelError, ModelEvent, TextDelta, ToolCall, ToolSpec, Usage, new_call_id


class OpenAICompatModel:
    def __init__(self, model: str, api_key: str, base_url: str = "https://api.openai.com/v1", *,
                 timeout: float = 120.0, store: bool = False, client: httpx.AsyncClient | None = None) -> None:
        self.model, self.base_url, self.store = model, base_url.rstrip("/"), store
        self.name = f"openai:{model}"
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0))

    @staticmethod
    def convert(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "assistant" and m.get("tool_calls"):
                out.append({"role": "assistant", "content": m.get("content") or None,
                            "tool_calls": [{"id": c["id"], "type": "function",
                                            "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                                           for c in m["tool_calls"]]})
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        return out

    async def stream(self, system: str, messages: list[dict[str, Any]], tools: list[ToolSpec], *,
                     max_tokens: int) -> AsyncIterator[ModelEvent]:
        body: dict[str, Any] = {
            "model": self.model, "stream": True, "stream_options": {"include_usage": True},
            "store": self.store, "max_completion_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, *self.convert(messages)]}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                              "parameters": t.input_schema}} for t in tools]
        text: list[str] = []
        partial: dict[int, dict[str, Any]] = {}
        usage, reason = Usage(), "stop"
        try:
            async with self._client.stream("POST", f"{self.base_url}/chat/completions", json=body,
                                           headers=self._headers) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", "replace")[:500]
                    raise ModelError(f"The model API answered {response.status_code}: {detail}")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if chunk.get("usage"):
                        u = chunk["usage"]
                        usage = Usage(u.get("prompt_tokens") or 0, u.get("completion_tokens") or 0,
                                      (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            text.append(delta["content"])
                            yield TextDelta(delta["content"])
                        for call in delta.get("tool_calls") or []:
                            slot = partial.setdefault(call.get("index", 0), {"id": None, "name": "", "arguments": ""})
                            slot["id"] = call.get("id") or slot["id"]
                            function = call.get("function") or {}
                            slot["name"] += function.get("name") or ""
                            slot["arguments"] += function.get("arguments") or ""
                        reason = choice.get("finish_reason") or reason
        except httpx.HTTPError as exc:
            raise ModelError(f"Cannot reach the model API at {self.base_url}: {type(exc).__name__}: {exc}") from None
        except json.JSONDecodeError as exc:
            raise ModelError(f"The model API sent a malformed stream: {exc}") from None
        calls = []
        for _, slot in sorted(partial.items()):
            try:
                arguments = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError:
                raise ModelError(f"Tool call {slot['name']} had malformed arguments.") from None
            calls.append(ToolCall(slot["id"] or new_call_id(), slot["name"], arguments))
        yield Finished("".join(text), calls, usage, "tool_calls" if calls else reason)
