"""The assistant's HTTP service: ``POST /api/chat`` (SSE), the route the web app builds from ``VITE_CHAT_URL``."""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .loop import Assistant, ChatRequest, FAST, DEEP, Rates
from .model import AgentModel
from .ollama import OllamaModel
from .openai_compat import OpenAICompatModel
from .tools import McpHttpSource

ORIGIN_REGEX = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"


@dataclass
class ChatSettings:
    provider: str = "ollama"                       # ollama | openai
    model: str = "qwen3:14b"                       # deep
    fast_model: str | None = None                  # default: same as deep
    ollama_url: str = "http://127.0.0.1:11434"
    num_ctx: int = 32768
    think: bool = False
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = field(default=None, repr=False)
    mcp_url: str = "http://127.0.0.1:8000/mcp/"
    trace_dir: Path | None = Path("outputs/chat")
    store_text: bool = True
    allow_evaluation: bool = False
    compact: bool = False
    rates: Rates | None = None
    cors_origins: tuple[str, ...] = ()
    rate_per_minute: int = 20
    max_concurrent: int = 2
    deep_timeout_s: float | None = None            # default: 120 s remote, 600 s for a local model
    fast_timeout_s: float | None = None
    warm_up: bool = True


def make_models(settings: ChatSettings) -> dict[str, AgentModel]:
    def one(name: str) -> AgentModel:
        if settings.provider == "ollama":
            return OllamaModel(name, settings.ollama_url, num_ctx=settings.num_ctx, think=settings.think)
        if settings.provider == "openai":
            if not settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY is not set (environment or .env).")
            return OpenAICompatModel(name, settings.openai_api_key, settings.openai_base_url)
        raise RuntimeError(f"Unknown provider '{settings.provider}'.")

    return {"deep": one(settings.model), "fast": one(settings.fast_model or settings.model)}


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@dataclass
class _Bucket:
    stamps: list[float] = field(default_factory=list)


def create_app(assistant: Assistant, settings: ChatSettings) -> FastAPI:
    warm: dict[str, Any] = {"state": "off"}

    async def warm_up() -> None:
        warm["state"] = "warming"
        try:
            warm.update(await assistant.warm("deep"), state="warm")
        except Exception as exc:  # noqa: BLE001 - a failed warm-up only means the first question is slow
            warm.update(state="failed", error=f"{type(exc).__name__}: {exc}")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(warm_up()) if settings.warm_up else None
        yield
        if task is not None and not task.done():
            task.cancel()

    app = FastAPI(title="Kalmora assistant", version="1", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    origins = list(settings.cors_origins)
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_origin_regex=None if origins else ORIGIN_REGEX,
                       allow_methods=["GET", "POST"], allow_headers=["*"])
    gate = asyncio.Semaphore(settings.max_concurrent)
    buckets: dict[str, _Bucket] = defaultdict(_Bucket)

    def problem(status: int, code: str, detail: str) -> JSONResponse:
        return JSONResponse({"code": code, "detail": detail, "status": status}, status_code=status,
                            media_type="application/problem+json")

    @app.get("/api/chat/status")
    def status() -> dict[str, Any]:
        return {"enabled": True, "model": assistant.models["deep"].name, "fast_model": assistant.models["fast"].name,
                "provider": settings.provider, "mcp": settings.mcp_url, "warm": warm,
                "endpoint": settings.ollama_url if settings.provider == "ollama" else settings.openai_base_url}

    @app.get("/api/chat/health")
    async def health() -> Any:
        try:
            async with asyncio.timeout(5):
                async with assistant.source.open() as session:
                    tools = await session.tools(assistant.allow_evaluation)
            return {"ok": True, "tools": len(tools)}
        except Exception as exc:  # noqa: BLE001
            return problem(503, "mcp.unreachable", f"{type(exc).__name__}: {exc}")

    @app.post("/api/chat")
    async def chat(request: Request) -> Any:
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        bucket = buckets[client]
        bucket.stamps = [t for t in bucket.stamps if now - t < 60]
        if len(bucket.stamps) >= settings.rate_per_minute:
            return problem(429, "rate.limited", f"At most {settings.rate_per_minute} questions per minute.")
        bucket.stamps.append(now)
        try:
            body = await request.json()
        except ValueError:
            return problem(400, "request.invalid", "Body must be JSON.")
        messages = body.get("messages") if isinstance(body, dict) else None
        if (not isinstance(messages, list) or not messages or len(messages) > 60
                or not all(isinstance(m, dict) and isinstance(m.get("content"), str) and m.get("role") in ("user", "assistant") for m in messages)
                or messages[-1]["role"] != "user" or len(messages[-1]["content"]) > 8000):
            return problem(400, "request.invalid", "messages must be a non-empty list of {role, content}, ending with the user's question (max 8000 characters).")
        req = ChatRequest(messages=messages, mode=body.get("mode") if body.get("mode") in ("fast", "deep") else "deep",
                          run_id=body.get("run_id") if isinstance(body.get("run_id"), str) else None,
                          dataset_id=body.get("dataset_id") if isinstance(body.get("dataset_id"), str) else None)

        async def stream() -> AsyncIterator[str]:
            async with gate:
                async for event in assistant.answer(req):
                    yield sse(event["event"], event["data"])

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


def build_assistant(settings: ChatSettings, source: Any = None) -> Assistant:
    local = settings.provider == "ollama"
    limits = {"fast": replace(FAST, timeout_s=settings.fast_timeout_s or (240.0 if local else FAST.timeout_s)),
              "deep": replace(DEEP, timeout_s=settings.deep_timeout_s or (600.0 if local else DEEP.timeout_s))}
    return Assistant(models=make_models(settings), source=source or McpHttpSource(settings.mcp_url),
                     limits=limits, rates=settings.rates, trace_dir=settings.trace_dir,
                     store_text=settings.store_text, allow_evaluation=settings.allow_evaluation, compact=settings.compact)
