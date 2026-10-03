"""Provider-neutral model port. A turn is: system text, neutral messages, tool specs -> streamed events.

Neutral messages are plain dicts::

    {"role": "user", "content": "..."}
    {"role": "assistant", "content": "...", "tool_calls": [{"id", "name", "arguments"}]}
    {"role": "tool", "tool_call_id": "...", "name": "...", "content": "<json text>"}
"""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    def __iadd__(self, other: "Usage") -> "Usage":
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        return self


@dataclass
class TextDelta:
    text: str


@dataclass
class Finished:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    stop_reason: str = "stop"


ModelEvent = TextDelta | Finished


class ModelError(Exception):
    """The provider failed (network, status, malformed stream). The turn ends with an ``error`` event."""


class AgentModel(Protocol):
    name: str

    def stream(self, system: str, messages: list[dict[str, Any]], tools: list[ToolSpec], *,
               max_tokens: int) -> AsyncIterator[ModelEvent]: ...


def new_call_id() -> str:
    return "call_" + uuid.uuid4().hex[:12]


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class Step:
    """One scripted model turn: optional text and optional tool calls ``[(name, arguments)]``."""

    text: str = ""
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


class FakeModel:
    """Scripted model for tests and T1 evals. ``script`` items are ``Step`` or ``callable(system, messages, tools)``.

    The last script item repeats when the script runs out. Every request is kept in ``requests``.
    """

    def __init__(self, script: list[Step | Callable[..., Step]], name: str = "fake") -> None:
        self.script, self.name = list(script), name
        self.requests: list[dict[str, Any]] = []
        self._position = 0

    async def stream(self, system: str, messages: list[dict[str, Any]], tools: list[ToolSpec], *,
                     max_tokens: int) -> AsyncIterator[ModelEvent]:
        self.requests.append({"system": system, "messages": json.loads(json.dumps(messages)),
                              "tools": [t.name for t in tools], "max_tokens": max_tokens})
        item = self.script[min(self._position, len(self.script) - 1)]
        self._position += 1
        step = item(system, messages, tools) if callable(item) else item
        if step.text:
            yield TextDelta(step.text)
        calls = [ToolCall(new_call_id(), name, dict(arguments)) for name, arguments in step.calls]
        size = sum(estimate_tokens(json.dumps(m, default=str)) for m in messages) + estimate_tokens(system)
        yield Finished(step.text, calls, Usage(size, estimate_tokens(step.text) + 20 * len(calls)),
                       "tool_calls" if calls else "stop")
