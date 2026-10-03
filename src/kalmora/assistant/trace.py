"""One JSON trace per turn: scope, model, per-step usage, cost, tool calls, guard outcomes, answer, latency."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .model import Usage


@dataclass
class TurnTrace:
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    started: float = field(default_factory=time.monotonic)
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.data.update({"turn_id": self.turn_id, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "steps": [], "tool_calls": [], "guards": []})

    def step(self, usage: Usage, stop_reason: str, seconds: float) -> None:
        self.data["steps"].append({"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                                   "cache_read_tokens": usage.cache_read_tokens, "stop_reason": stop_reason,
                                   "seconds": round(seconds, 2)})

    def tool(self, name: str, arguments: dict[str, Any], seconds: float, ok: bool, error_code: str | None,
             size: int, local: bool = False) -> None:
        self.data["tool_calls"].append({"name": name, "arguments": arguments, "seconds": round(seconds, 3), "ok": ok,
                                        "error_code": error_code, "result_chars": size, "local": local})

    def guard(self, outcome: dict[str, Any]) -> None:
        self.data["guards"].append(outcome)

    def finish(self, *, status: str, answer: str, cost: Decimal | None, store_text: bool = True) -> dict[str, Any]:
        usage = self.data["steps"]
        self.data.update({
            "status": status, "seconds": round(time.monotonic() - self.started, 2),
            "usage": {"input_tokens": sum(s["input_tokens"] for s in usage), "output_tokens": sum(s["output_tokens"] for s in usage),
                      "cache_read_tokens": sum(s["cache_read_tokens"] for s in usage)},
            "cost_usd": None if cost is None else str(cost), "answer": answer if store_text else None})
        return self.data

    def write(self, directory: Path | None) -> Path | None:
        if directory is None:
            return None
        day = Path(directory) / datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day.mkdir(parents=True, exist_ok=True)
        path = day / f"{self.turn_id}.json"
        path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return path
