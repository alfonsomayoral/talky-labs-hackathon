"""Provider-independent execution accounting, with explicitly supplied prices."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Self, cast
import time
import uuid
from .facts import atomic_json
from .model import RunCall, RunReport, PricingInput


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunRecorder:
    """Context manager that writes a ``RunReport`` on exit, even when the body raises."""

    def __init__(self, output_dir: str | Path, command: list[str],
                 input_metadata: dict[str, object] | None = None) -> None:
        self.run_id: str = str(uuid.uuid4())
        self.path: Path = Path(output_dir) / (self.run_id + ".json")
        # Filled incrementally; started_at/status/cost are added on enter/exit.
        self.report: dict[str, Any] = {"schema_version": 1, "run_id": self.run_id, "command": list(command),
                       "input_metadata": input_metadata or {}, "calls": [], "cache_hits": 0}

    def __enter__(self) -> Self:
        self.report["started_at"] = utc_now()
        self._start = time.perf_counter()
        return self

    def record_cache_hit(self) -> None:
        """Count a reused result instead of a provider call."""
        self.report["cache_hits"] += 1

    def record_call(self, provider: str, model: str, input_tokens: int | None = None,
                    output_tokens: int | None = None, pricing: PricingInput | None = None,
                    usage: object | None = None) -> RunCall:
        """Record one real provider call. Unknown usage or pricing leaves its cost unknown."""
        for count in (input_tokens, output_tokens):
            if count is not None and (not isinstance(count, int) or isinstance(count, bool) or count < 0):
                raise ValueError("Token counts must be nonnegative integers or unknown")
        call: dict[str, Any] = {"provider": provider, "model": model, "input_tokens": input_tokens,
                "output_tokens": output_tokens, "usage": usage, "pricing": None,
                "estimated_cost": None, "assumptions": []}
        if pricing is not None:
            if pricing.get("unit") != "per_token" or not pricing.get("currency") or not pricing.get("provenance"):
                raise ValueError("Pricing requires per_token unit, currency and provenance")
            rates = [Decimal(str(pricing["input_rate"])), Decimal(str(pricing["output_rate"]))]
            if any(not rate.is_finite() or rate < 0 for rate in rates):
                raise ValueError("Prices must be finite and nonnegative")
            call["pricing"] = {**pricing, "input_rate": str(rates[0]), "output_rate": str(rates[1])}
            call["assumptions"] = ["Caller-supplied rates; input and output token charges only; excludes taxes and discounts"]
            if input_tokens is not None and output_tokens is not None:
                call["estimated_cost"] = str(rates[0] * input_tokens + rates[1] * output_tokens)
        self.report["calls"].append(call)
        return cast(RunCall, call)

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 traceback: TracebackType | None) -> Literal[False]:
        self.report.update(ended_at=utc_now(), elapsed_seconds=time.perf_counter() - self._start,
                           status="failed" if exc_type or self.report.get("exit_code", 0) else "completed",
                           error_type=exc_type.__name__ if exc_type else None)
        calls = self.report["calls"]
        totals: dict[str, Decimal] = {}
        for call in calls:
            if call["estimated_cost"] is not None:
                currency = call["pricing"]["currency"]
                totals[currency] = totals.get(currency, Decimal(0)) + Decimal(call["estimated_cost"])
        self.report["cost"] = {"status": "no_llm" if not calls else (
            "estimated" if all(c["estimated_cost"] is not None for c in calls) else "unknown"),
            "total": "0" if not calls else None,
            "estimated_by_currency": {key: str(value) for key, value in totals.items()},
            "unknown_calls": sum(c["estimated_cost"] is None for c in calls)}
        atomic_json(self.path, self.report)
        return False
