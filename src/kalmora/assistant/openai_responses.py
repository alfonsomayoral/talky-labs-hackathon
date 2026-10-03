"""Adapter for the OpenAI Responses API (``/responses``) with tools and streaming.

For keys restricted to the Responses API, where ``/chat/completions`` answers 401 ``missing_scope``. Stateless like
the Chat Completions adapter: ``store`` is off and each turn sends the whole conversation, so no reasoning items are
carried across tool turns. The key is read from the environment by the caller and never stored."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .model import Finished, ModelError, ModelEvent, TextDelta, ToolCall, ToolSpec, Usage, new_call_id


class OpenAIResponsesModel:
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
            if m["role"] == "tool":
                out.append({"type": "function_call_output", "call_id": m["tool_call_id"], "output": m["content"]})
                continue
            if m.get("content"):
                out.append({"role": m["role"], "content": m["content"]})
            for c in m.get("tool_calls") or []:
                out.append({"type": "function_call", "call_id": c["id"], "name": c["name"],
                            "arguments": json.dumps(c["arguments"])})
        return out

    async def stream(self, system: str, messages: list[dict[str, Any]], tools: list[ToolSpec], *,
                     max_tokens: int) -> AsyncIterator[ModelEvent]:
        body: dict[str, Any] = {"model": self.model, "stream": True, "store": self.store,
                                "max_output_tokens": max_tokens, "instructions": system,
                                "input": self.convert(messages)}
        if tools:
            body["tools"] = [{"type": "function", "name": t.name, "description": t.description,
                              "parameters": t.input_schema, "strict": False} for t in tools]
        text: list[str] = []
        calls: list[ToolCall] = []
        usage, reason = Usage(), "stop"
        try:
            async with self._client.stream("POST", f"{self.base_url}/responses", json=body,
                                           headers=self._headers) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", "replace")[:500]
                    raise ModelError(f"The model API answered {response.status_code}: {detail}")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    event = json.loads(line[5:].strip())
                    kind = event.get("type")
                    if kind == "response.output_text.delta" and event.get("delta"):
                        text.append(event["delta"])
                        yield TextDelta(event["delta"])
                    elif kind == "response.output_item.done" and (event.get("item") or {}).get("type") == "function_call":
                        item = event["item"]
                        try:
                            arguments = json.loads(item.get("arguments") or "{}")
                        except json.JSONDecodeError:
                            raise ModelError(f"Tool call {item.get('name')} had malformed arguments.") from None
                        calls.append(ToolCall(item.get("call_id") or new_call_id(), item.get("name") or "", arguments))
                    elif kind in ("response.completed", "response.incomplete"):
                        result = event.get("response") or {}
                        u = result.get("usage") or {}
                        usage = Usage(u.get("input_tokens") or 0, u.get("output_tokens") or 0,
                                      (u.get("input_tokens_details") or {}).get("cached_tokens") or 0)
                        if kind == "response.incomplete":
                            reason = (result.get("incomplete_details") or {}).get("reason") or "incomplete"
                    elif kind in ("response.failed", "error"):
                        error = (event.get("response") or {}).get("error") or event.get("error") or event
                        raise ModelError(f"The model API failed: {json.dumps(error)[:500]}")
        except httpx.HTTPError as exc:
            raise ModelError(f"Cannot reach the model API at {self.base_url}: {type(exc).__name__}: {exc}") from None
        except json.JSONDecodeError as exc:
            raise ModelError(f"The model API sent a malformed stream: {exc}") from None
        yield Finished("".join(text), calls, usage, "tool_calls" if calls else reason)
