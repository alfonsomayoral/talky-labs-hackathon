"""Assistant configuration from the environment.

Precedence, highest first: command-line flag, real environment variable, ``.env`` file, built-in default. Secrets
(the OpenAI key) come only from the environment or the ``.env`` file, never from a flag, so they do not land in shell
history or process listings.

====================================  ====================================================================
Variable                              Meaning
====================================  ====================================================================
KALMORA_AI_PROVIDER                   ``ollama`` (default) or ``openai``
KALMORA_AI_MODEL                      model for mode deep
KALMORA_AI_FAST_MODEL                 model for mode fast (default: the deep model)
OPENAI_API_KEY                        OpenAI key (required for the ``openai`` provider)
OPENAI_BASE_URL                       default ``https://api.openai.com/v1``; any OpenAI-compatible server
OLLAMA_HOST / KALMORA_OLLAMA_URL      Ollama address (``host:port`` or URL); default ``http://127.0.0.1:11434``
KALMORA_OLLAMA_NUM_CTX                context window requested from Ollama (default 32768)
KALMORA_OLLAMA_THINK                  ``true`` lets the model think before answering (slower)
KALMORA_AI_INPUT_USD_PER_MTOK         explicit prices; all three enable USD caps and cost in the traces
KALMORA_AI_OUTPUT_USD_PER_MTOK
KALMORA_AI_PRICE_SOURCE               where the prices come from (URL and date)
KALMORA_AI_DEEP_TIMEOUT / _FAST_TIMEOUT  seconds per question
KALMORA_MCP_URL                       MCP endpoint of ``kalmora serve --mcp``
KALMORA_CHAT_TRACE_DIR                turn traces folder (default outputs/chat)
KALMORA_CHAT_STORE_TEXT               ``false`` keeps conversation text out of the traces
====================================  ====================================================================
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .loop import Rates
from .service import ChatSettings

PROVIDERS = ("ollama", "openai")
TRUE = {"1", "true", "yes", "on"}
FALSE = {"0", "false", "no", "off", ""}


class ConfigError(Exception):
    """A setting is missing or malformed. The message names the variable and never contains a secret."""


def parse_env_file(path: Path) -> dict[str, str]:
    """``KEY=value`` lines; ``#`` comments, optional ``export``, optional single or double quotes. No interpolation."""
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigError(f"{path}:{number}: expected KEY=value")
        key, _, value = line.partition("=")
        value = value.strip()
        if value[:1] in ("'", '"') and value.find(value[0], 1) > 0:
            value = value[1:value.find(value[0], 1)]          # quoted: up to the closing quote, a trailing comment is dropped
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key.strip()] = value
    return values


def load_environment(environ: Mapping[str, str] | None = None, env_file: Path | None = None) -> dict[str, str]:
    """The real environment over the ``.env`` file (a file never overrides a variable that is already set)."""
    merged: dict[str, str] = {}
    candidate = env_file if env_file is not None else Path(".env")
    if candidate.is_file():
        merged.update(parse_env_file(candidate))
    merged.update(os.environ if environ is None else environ)
    return merged


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in TRUE:
        return True
    if value in FALSE:
        return False
    raise ConfigError(f"{name} must be true or false")


def _number(env: Mapping[str, str], name: str, cast: Any, default: Any) -> Any:
    raw = env.get(name)
    if raw in (None, ""):
        return default
    try:
        return cast(raw)
    except (ValueError, InvalidOperation):
        raise ConfigError(f"{name} must be a number") from None


def _ollama_url(env: Mapping[str, str]) -> str:
    """``host``, ``host:port`` or a full URL (Ollama's own OLLAMA_HOST accepts all three)."""
    from urllib.parse import urlsplit
    raw = (env.get("KALMORA_OLLAMA_URL") or env.get("OLLAMA_HOST") or "").strip()
    if not raw:
        return "http://127.0.0.1:11434"
    parts = urlsplit(raw if "://" in raw else "http://" + raw)
    host = parts.hostname or "127.0.0.1"
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"            # OLLAMA_HOST=0.0.0.0 is a bind address; connect locally
    return f"{parts.scheme}://{host}:{parts.port or 11434}"


def chat_settings(env: Mapping[str, str], **flags: Any) -> ChatSettings:
    """Build ``ChatSettings``. ``flags`` are the command-line values (``None`` or absent = not given)."""
    given = {k: v for k, v in flags.items() if v is not None}
    provider = (given.get("provider") or env.get("KALMORA_AI_PROVIDER") or "ollama").strip().lower()
    if provider not in PROVIDERS:
        raise ConfigError(f"KALMORA_AI_PROVIDER must be one of: {', '.join(PROVIDERS)} (got '{provider}')")
    model = given.get("model") or env.get("KALMORA_AI_MODEL") or ("qwen3:14b" if provider == "ollama" else "")
    if not model:
        raise ConfigError("KALMORA_AI_MODEL is required for the openai provider (the model that answers mode deep)")
    key = env.get("OPENAI_API_KEY") or None
    if provider == "openai" and not key:
        raise ConfigError("OPENAI_API_KEY is required for the openai provider (set it in the environment or in .env)")
    prices = [env.get("KALMORA_AI_INPUT_USD_PER_MTOK"), env.get("KALMORA_AI_OUTPUT_USD_PER_MTOK"), env.get("KALMORA_AI_PRICE_SOURCE")]
    rates = None
    if any(prices):
        if not all(prices):
            raise ConfigError("KALMORA_AI_INPUT_USD_PER_MTOK, KALMORA_AI_OUTPUT_USD_PER_MTOK and KALMORA_AI_PRICE_SOURCE go together")
        rates = Rates(_number(env, "KALMORA_AI_INPUT_USD_PER_MTOK", Decimal, None),
                      _number(env, "KALMORA_AI_OUTPUT_USD_PER_MTOK", Decimal, None), prices[2])
    defaults = ChatSettings()
    return ChatSettings(
        provider=provider, model=model, fast_model=given.get("fast_model") or env.get("KALMORA_AI_FAST_MODEL") or None,
        ollama_url=given.get("ollama_url") or _ollama_url(env),
        num_ctx=given.get("num_ctx") or _number(env, "KALMORA_OLLAMA_NUM_CTX", int, defaults.num_ctx),
        think=given.get("think") if given.get("think") else _flag(env, "KALMORA_OLLAMA_THINK", False),
        openai_base_url=given.get("openai_base_url") or env.get("OPENAI_BASE_URL") or defaults.openai_base_url,
        openai_api_key=key,
        mcp_url=given.get("mcp_url") or env.get("KALMORA_MCP_URL") or defaults.mcp_url,
        trace_dir=given.get("trace_dir") or Path(env.get("KALMORA_CHAT_TRACE_DIR") or "outputs/chat"),
        store_text=False if given.get("no_store_text") else _flag(env, "KALMORA_CHAT_STORE_TEXT", True),
        allow_evaluation=bool(given.get("allow_evaluation")), compact=bool(given.get("compact")), rates=rates,
        cors_origins=tuple(given.get("cors_origins") or ()),
        deep_timeout_s=given.get("deep_timeout") or _number(env, "KALMORA_AI_DEEP_TIMEOUT", float, None),
        fast_timeout_s=given.get("fast_timeout") or _number(env, "KALMORA_AI_FAST_TIMEOUT", float, None),
        warm_up=not given.get("no_warm_up"))


def describe(settings: ChatSettings) -> dict[str, Any]:
    """What the service reports about itself. Never includes the key."""
    return {"provider": settings.provider, "model": settings.model, "fast_model": settings.fast_model or settings.model,
            "endpoint": settings.ollama_url if settings.provider == "ollama" else settings.openai_base_url,
            "api_key": "set" if settings.openai_api_key else "not set", "prices": "set" if settings.rates else "not set",
            "mcp": settings.mcp_url}
