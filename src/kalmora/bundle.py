"""Writer for a run bundle: what an engine or the future orchestrator calls to leave its work readable.

Layout (see ``docs/api-contracts.md`` section 10)::

    <root>/manifest.json
    <root>/deliverables/<task>.jsonl
    <root>/trace/events.jsonl      append-only
    <root>/trace/attention.jsonl   append-only
"""
import json
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, get_args

from .facts import atomic_json
from .model.trace import (AttentionKind, AttentionItem, EventKind, EventResult, EvidenceKind, Priority, TASKS,
                          TraceEvent)

TASK_KEYS = {"ap", "ar_billing", "ar_cash", "bank_rec", "ic", "close"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _check(name: str, value: object, allowed: tuple[Any, ...]) -> None:
    if value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(map(str, allowed))}; got {value!r}")


class RunBundle:
    """Append-only trace plus atomic deliverables. Thread-safe."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        (self.root / "deliverables").mkdir(parents=True, exist_ok=True)
        (self.root / "trace").mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self._seq: dict[str, int] = defaultdict(int)
        self._events = self._count(self.root / "trace" / "events.jsonl")
        self._attention = self._count(self.root / "trace" / "attention.jsonl")

    @staticmethod
    def _count(path: Path) -> int:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()) if path.is_file() else 0

    def write_deliverable(self, task: str, rows: list[dict[str, Any]]) -> Path:
        _check("task", task, TASKS)
        path = self.root / "deliverables" / f"{task}.jsonl"
        temp = path.with_suffix(".tmp")
        temp.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        temp.replace(path)
        return path

    def _append(self, name: str, row: dict[str, Any]) -> None:
        with (self.root / "trace" / name).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def event(self, item: str, kind: EventKind, *, step: str | None = None, result: EventResult | None = None,
              summary: str | None = None, policy_ref: str | None = None, evidence: list[dict[str, Any]] | None = None,
              model: dict[str, Any] | None = None, confidence: float | None = None,
              duration_ms: int | None = None) -> TraceEvent:
        _check("kind", kind, get_args(EventKind))
        if result is not None:
            _check("result", result, get_args(EventResult))
        if not isinstance(item, str) or ":" not in item or item.split(":", 1)[0] not in TASK_KEYS or not item.split(":", 1)[1]:
            raise ValueError(f"item must be '<task>:<key>' with task in {sorted(TASK_KEYS)}; got {item!r}")
        for ref in evidence or []:
            _check("evidence.kind", ref.get("kind"), get_args(EvidenceKind))
        if confidence is not None and not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        with self._lock:
            self._events += 1
            self._seq[item] += 1
            event: dict[str, Any] = {"event_id": f"e-{self._events:06d}", "item": item, "seq": self._seq[item],
                                     "ts": now(), "kind": kind}
            for key, value in (("step", step), ("result", result), ("policy_ref", policy_ref), ("summary", summary),
                               ("evidence", evidence), ("model", model), ("confidence", confidence),
                               ("duration_ms", duration_ms)):
                if value is not None:
                    event[key] = value
            self._append("events.jsonl", event)
        return event  # type: ignore[return-value]

    def attention(self, item: str, kind: AttentionKind, priority: Priority, title: str, *, impact: int | None = None,
                  affects_tb: bool | None = None, policy_ref: str | None = None,
                  recommendation: dict[str, Any] | None = None, alternatives: list[dict[str, Any]] | None = None,
                  suggested_action: str | None = None) -> AttentionItem:
        _check("kind", kind, get_args(AttentionKind))
        _check("priority", priority, get_args(Priority))
        if impact is not None and (isinstance(impact, bool) or not isinstance(impact, int)):
            raise ValueError("impact must be integer cents")
        with self._lock:
            self._attention += 1
            row: dict[str, Any] = {"attention_id": f"att-{self._attention:04d}", "item": item, "kind": kind,
                                   "priority": priority, "title": title}
            for key, value in (("impact", impact), ("affects_tb", affects_tb), ("policy_ref", policy_ref),
                               ("recommendation", recommendation), ("alternatives", alternatives),
                               ("suggested_action", suggested_action)):
                if value is not None:
                    row[key] = value
            self._append("attention.jsonl", row)
        return row  # type: ignore[return-value]

    def manifest(self, **fields: Any) -> None:
        """Merge ``fields`` into ``manifest.json`` (kept if the closer already wrote its status)."""
        path = self.root / "manifest.json"
        current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        atomic_json(path, {**current, **fields})
