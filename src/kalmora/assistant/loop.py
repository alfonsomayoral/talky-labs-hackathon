"""The agent loop: model <-> tools, with caps, the ``present`` card tool, the answer guards and one trace per turn.

``Assistant.answer`` yields events ready for SSE: ``status`` during tool rounds, then ``delta`` (only after the guards
pass), ``card``, ``citation`` and ``done``; ``error`` if the model or the tools are unreachable.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from .cards import PresentError, build_card
from .guard import GuardResult, check_answer, check_numbers
from .model import AgentModel, Finished, ModelError, ToolSpec, Usage
from .prompt import KnowledgePack, build_pack, read_optional, repo_root, scope_block, stable_prefix, with_scope
from .tools import ITEM_ID, PRESENT, Outcome, encode_result, ToolSource
from .trace import TurnTrace

MAX_ROUNDS = 16
MAX_CARDS = 6


@dataclass
class Limits:
    max_calls: int = 12
    max_result_tokens: int = 40_000
    max_output_tokens: int = 2_000
    usd_cap: Decimal | None = Decimal("0.25")
    history_turns: int = 10
    history_tokens: int = 4_000
    timeout_s: float = 120.0
    repairs: int = 1


FAST = Limits(max_calls=4, max_result_tokens=15_000, max_output_tokens=800, usd_cap=Decimal("0.05"), history_turns=4,
              timeout_s=60.0)
DEEP = Limits()


@dataclass
class Rates:
    """Explicit price per million tokens, with where it comes from (as ``kalmora.llm`` requires)."""

    input_per_mtok: Decimal
    output_per_mtok: Decimal
    provenance: str

    def cost(self, usage: Usage) -> Decimal:
        return (Decimal(usage.input_tokens) * self.input_per_mtok + Decimal(usage.output_tokens) * self.output_per_mtok) / Decimal(1_000_000)


@dataclass
class ChatRequest:
    messages: list[dict[str, Any]]
    mode: str = "deep"
    run_id: str | None = None
    dataset_id: str | None = None


@dataclass
class _Turn:
    results: dict[str, Any] = field(default_factory=dict)
    by_tool: dict[str, str] = field(default_factory=dict)
    cards: list[dict[str, Any]] = field(default_factory=list)
    calls: int = 0
    result_chars: int = 0
    repairs: int = 0
    usage: Usage = field(default_factory=Usage)
    capped: bool = False
    offered: set[str] = field(default_factory=set)


@dataclass
class Scope:
    phase: str | None
    text: str
    run_known: bool = False


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class Assistant:
    def __init__(self, *, models: dict[str, AgentModel], source: ToolSource, limits: dict[str, Limits] | None = None,
                 rates: Rates | None = None, trace_dir: Path | None = None, store_text: bool = True,
                 allow_evaluation: bool = False, glossary: str | None = None, workflows: str | None = None,
                 compact: bool = False, today: Callable[[], str] | None = None) -> None:
        self.models, self.source = models, source
        self.limits = limits or {"fast": FAST, "deep": DEEP}
        self.rates, self.trace_dir, self.store_text = rates, trace_dir, store_text
        self.allow_evaluation, self.compact = allow_evaluation, compact
        root = repo_root()
        self.glossary = glossary if glossary is not None else read_optional(root / "CONTEXT.md")
        self.workflows = workflows if workflows is not None else read_optional(root / "knowledge/workflows/kalmora-close-workflows.md")
        self.today = today or (lambda: date.today().isoformat())
        self._packs: dict[tuple[str, str], KnowledgePack] = {}

    async def warm(self, mode: str = "deep") -> dict[str, Any]:
        """Prefill the model's prompt cache with the stable prefix (policies, glossary, rules) of the first loaded phase.
        Only models that expose ``warm`` (Ollama) do anything; the first real question is then not the one that pays."""
        model = self.models[mode]
        if not hasattr(model, "warm"):
            return {"warmed": False, "reason": "the provider caches server-side"}
        async with self.source.open() as session:
            phases = await session.call("list_phases", {})
            names = [p["phase"] for p in (phases.payload or {}).get("data", [])] if phases.ok else []
            pack = await self._pack(session, names[0] if names else None, TurnTrace())
            specs = [*await session.tools(self.allow_evaluation), PRESENT]
        seconds = await model.warm(stable_prefix(pack), specs)
        return {"warmed": True, "seconds": round(seconds, 1), "phase": names[0] if names else None}

    # ------------------------------------------------------------------ context
    async def _scope(self, session: Any, req: ChatRequest, limits: Limits, mode: str, trace: TurnTrace) -> Scope:
        phases_out = await session.call("list_phases", {})
        phases = (phases_out.payload or {}).get("data", []) if phases_out.ok else []
        by_name = {p["phase"]: p for p in phases}
        phase = req.dataset_id if req.dataset_id in by_name else (phases[0]["phase"] if len(phases) == 1 and not req.dataset_id else None)
        if phase:
            note = f"loaded on the server; golden: not available to you"
            month = by_name[phase]["month"]
        else:
            note = f"dataset '{req.dataset_id}' is not loaded on the server" if req.dataset_id else "no phase selected; loaded: " + ", ".join(by_name) 
            month = None
        run_note = "none"
        if req.run_id:
            run = await session.call("get_run", {"run_id": req.run_id})
            if run.ok:
                data = (run.payload or {}).get("data", {})
                files = ", ".join(m for m, v in (data.get("deliverables") or {}).items() if v.get("present")) or "none"
                events = await session.call("list_run_events", {"run_id": req.run_id, "limit": 1})
                has_trace = events.ok and (events.payload or {}).get("data", {}).get("total", 0) > 0
                run_note = f"{req.run_id} ({data.get('status', 'unknown status')}), deliverables: {files}, trace: {'present' if has_trace else 'absent'}"
                if not has_trace:
                    run_note += " - this run left no trace: when you explain an item say it is derived from the delivered row and the policy"
            else:
                run_note = ("NOT ON THE SERVER (imported in the browser): tell the user you cannot see this run on the server, "
                            "and answer only about the phase")
        currencies = ""
        if phase:
            companies = await session.call("list_records", {"table": "companies", "phase": phase, "limit": 100})
            if companies.ok:
                currencies = ", ".join(f"{c['code']} {c['currency']}" for c in (companies.payload or {}).get("data", {}).get("items", []))
        usd = None if self.rates is None or limits.usd_cap is None else str(limits.usd_cap)
        text = scope_block(phase=phase, month=month, phase_note=note, run_note=run_note, mode=mode,
                           max_calls=limits.max_calls, max_tokens=limits.max_result_tokens, usd_cap=usd, today=self.today(),
                           currencies=currencies)
        trace.data["scope"] = {"phase": phase, "run": run_note, "mode": mode}
        return Scope(phase, text, run_known=bool(req.run_id) and run_note.startswith(req.run_id))

    async def _pack(self, session: Any, phase: str | None, trace: TurnTrace) -> KnowledgePack:
        policy: dict[str, Any] | None = None
        if phase:
            out = await session.call("get_policies", {"phase": phase})
            if out.ok:
                policy = {**(out.payload or {}).get("data", {})}
        if policy is None:
            policy = {"sha256": "unavailable", "text": "(The accounting policies are not available for this scope. "
                      "Say so when a question depends on them.)", "anchors": []}
        key = (phase or "", policy["sha256"])
        if key not in self._packs:
            self._packs[key] = build_pack(policy, glossary=self.glossary, workflows=self.workflows, compact=self.compact)
        trace.data["policy_sha256"] = policy["sha256"]
        return self._packs[key]

    @staticmethod
    def _history(messages: list[dict[str, Any]], limits: Limits) -> list[dict[str, Any]]:
        kept = [{"role": m["role"], "content": str(m["content"])[:2000]} for m in messages
                if m.get("role") in ("user", "assistant") and str(m.get("content", "")).strip()]
        kept = kept[-(limits.history_turns * 2):]
        total, out = 0, []
        for m in reversed(kept):
            total += len(m["content"]) // 4
            if total > limits.history_tokens and out:
                break
            out.append(m)
        out.reverse()
        while out and out[0]["role"] != "user":
            out.pop(0)
        return out

    # -------------------------------------------------------------------- tools
    async def _run_tool(self, session: Any, call: Any, state: _Turn, limits: Limits, trace: TurnTrace) -> str:
        started = time.monotonic()
        if call.name == "present":
            if len(state.cards) >= MAX_CARDS:
                outcome = Outcome(False, None, {"code": "present.limit", "detail": f"At most {MAX_CARDS} cards per answer."})
            else:
                args = dict(call.arguments)
                source = args.get("source_call")
                if source not in state.results and source in state.by_tool:     # the model named the tool, not the id
                    args["source_call"] = state.by_tool[source]
                try:
                    state.cards.append(build_card(args, state.results))
                    outcome = Outcome(True, {"card": "queued", "type": args.get("type")})
                except PresentError as exc:
                    outcome = Outcome(False, None, {"code": "present.invalid", "detail": str(exc)})
                except (KeyError, TypeError, ValueError) as exc:
                    outcome = Outcome(False, None, {"code": "present.invalid", "detail": f"Bad arguments: {type(exc).__name__}: {exc}"})
            text = _json({"id": call.id, "tool": "present", **({"result": outcome.payload} if outcome.ok else {"error": outcome.error})})
            trace.tool("present", call.arguments, time.monotonic() - started, outcome.ok, (outcome.error or {}).get("code"), len(text), local=True)
            return text
        budget = limits.max_result_tokens * 4 - state.result_chars
        if call.name not in state.offered:
            outcome = Outcome(False, None, {"code": "tool.unavailable", "detail": f"'{call.name}' is not one of your tools."})
            text = _json({"id": call.id, "tool": call.name, "error": outcome.error})
            trace.tool(call.name, call.arguments, 0.0, False, "tool.unavailable", len(text))
            return text
        if state.calls >= limits.max_calls or budget <= 0:
            state.capped = True
            reason = "tool calls" if state.calls >= limits.max_calls else "tool-result budget"
            outcome = Outcome(False, None, {"code": "limit.reached", "detail": f"The {reason} limit of this turn is reached. "
                                            "Answer with what you already have and say the answer is partial."})
        else:
            state.calls += 1
            try:
                outcome = await session.call(call.name, call.arguments)
            except Exception as exc:  # noqa: BLE001 - a tool failure becomes a tool error for the model
                outcome = Outcome(False, None, {"code": "tool.failed", "detail": f"{type(exc).__name__}: {exc}"})
        text = encode_result(call.name, call.id, outcome, max(2_000, min(limits.max_result_tokens * 2, budget)))
        state.result_chars += len(text)
        if outcome.ok:
            state.results[call.id] = {"result": outcome.payload}
            state.by_tool[call.name] = call.id
        trace.tool(call.name, call.arguments, time.monotonic() - started, outcome.ok, (outcome.error or {}).get("code"), len(text))
        return text

    # ------------------------------------------------------------------- answer
    def _safe_answer(self, text: str, tool_results: list[Any], tool_text: str, trusted: list[Any]) -> str:
        from .guard import allowed_numbers
        allowed = allowed_numbers(*tool_results, *trusted)
        kept = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip() and not check_numbers(s, allowed)
                and all(i in tool_text or i in " ".join(str(t) for t in trusted) for i in ITEM_ID.findall(s))]
        head = "No puedo verificar con los datos una de las cifras de mi respuesta."
        return head + (" Esto es lo que sí consta: " + " ".join(kept) if kept else " No tengo datos verificados para responderla; reformula la pregunta o acota el filtro.")

    def _cost(self, usage: Usage) -> Decimal | None:
        return None if self.rates is None else self.rates.cost(usage)

    async def answer(self, req: ChatRequest) -> AsyncIterator[dict[str, Any]]:
        mode = req.mode if req.mode in self.models else "deep"
        model, limits = self.models[mode], self.limits[mode]
        trace = TurnTrace()
        trace.data.update({"model": model.name, "mode": mode, "messages": len(req.messages)})
        status, final = "ok", ""
        state = _Turn()
        try:
            async with asyncio.timeout(limits.timeout_s):
                async with self.source.open() as session:
                    specs: list[ToolSpec] = [*await session.tools(self.allow_evaluation), PRESENT]
                    state.offered = {t.name for t in specs}
                    scope = await self._scope(session, req, limits, mode, trace)
                    pack = await self._pack(session, scope.phase, trace)
                    system = stable_prefix(pack)
                    messages = self._history(req.messages, limits)
                    messages[-1] = {**messages[-1], "content": with_scope(messages[-1]["content"], scope.text)}
                    user_text = " ".join(m["content"] for m in messages if m["role"] == "user")
                    yield {"event": "status", "data": {"phase": "start", "model": model.name}}
                    result: GuardResult | None = None
                    for _ in range(MAX_ROUNDS):
                        finished = await self._round(model, system, messages, specs, limits, trace, state)
                        if finished.tool_calls:
                            messages.append({"role": "assistant", "content": finished.text, "tool_calls": [
                                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in finished.tool_calls]})
                            for call in finished.tool_calls:
                                yield {"event": "status", "data": {"phase": "tool", "tool": call.name}}
                                messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name,
                                                 "content": await self._run_tool(session, call, state, limits, trace)})
                            if limits.usd_cap is not None and (cost := self._cost(state.usage)) is not None and cost > limits.usd_cap:
                                state.capped = True
                                break
                            continue
                        tool_results = list(state.results.values())
                        tool_text = _json(tool_results)
                        result = check_answer(finished.text, tool_results=tool_results, tool_text=tool_text,
                                              trusted=[pack.text, user_text], valid_refs=pack.refs, user_text=user_text)
                        trace.guard({"ungrounded_numbers": result.ungrounded_numbers, "ungrounded_items": result.ungrounded_items,
                                     "removed_policy_refs": result.removed_policy_refs, "repair": state.repairs})
                        if result.ok and result.text and not (state.repairs < limits.repairs and _too_long(result.text, user_text)):
                            break
                        if state.repairs < limits.repairs:
                            state.repairs += 1
                            problem = ("Tu respuesta estaba vacía. Responde con texto plano." if not result.text else
                                       "Resume tu respuesta en como máximo seis frases." if result.ok else
                                       "Estas cifras o ids de tu respuesta no constan en los resultados de las herramientas: "
                                       + ", ".join(result.ungrounded_numbers + result.ungrounded_items)
                                       + ". Corrige la respuesta usando solo datos de las herramientas; si necesitas un porcentaje, una suma o una diferencia, llama a `calculate` en vez de calcularlo; o di que no tienes el dato.")
                            messages += [{"role": "assistant", "content": finished.text}, {"role": "user", "content": problem}]
                            continue
                        status = "safe_answer"
                        result.text = self._safe_answer(result.text, tool_results, tool_text, [pack.text, user_text])
                        break
                    else:
                        status = "safe_answer"
                    if result is None:
                        tool_text = _json(list(state.results.values()))
                        result = GuardResult(text="He alcanzado el límite de la consulta antes de poder responder con datos verificados; "
                                                  "acota la pregunta (sociedad, cuenta, periodo).")
                        status = "capped"
                    final = result.text
                    if state.capped and status == "ok":
                        status = "partial"
                    for chunk in _chunks(final):
                        yield {"event": "delta", "data": {"text": chunk}}
                    for card in state.cards:
                        yield {"event": "card", "data": card}
                    for item in result.items:
                        yield {"event": "citation", "data": {"item": item}}
                    for ref in result.policy_refs:
                        yield {"event": "citation", "data": {"policy_ref": ref}}
        except (ModelError, TimeoutError, OSError, ExceptionGroup) as exc:
            status = "error"
            leaves = _leaves(exc)
            message = "; ".join(dict.fromkeys(str(e) for e in leaves))
            if any(isinstance(e, TimeoutError) for e in leaves):
                message = f"La consulta superó el tiempo máximo de {limits.timeout_s:.0f} s."
            trace.data["error"] = message
            yield {"event": "error", "data": message}
        cost = self._cost(state.usage)
        trace.finish(status=status, answer=final, cost=cost, store_text=self.store_text)
        trace.data["calls"] = state.calls
        trace.write(self.trace_dir)
        if status != "error":
            yield {"event": "done", "data": {"turn_id": trace.turn_id, "status": status,
                                              "usage": {"input_tokens": state.usage.input_tokens, "output_tokens": state.usage.output_tokens},
                                              "cost_usd": None if cost is None else str(cost)}}
        self.last_trace = trace.data

    async def _round(self, model: AgentModel, system: str, messages: list[dict[str, Any]], specs: list[ToolSpec],
                     limits: Limits, trace: TurnTrace, state: _Turn) -> Finished:
        started = time.monotonic()
        finished: Finished | None = None
        async for event in model.stream(system, messages, specs, max_tokens=limits.max_output_tokens):
            if isinstance(event, Finished):
                finished = event
        if finished is None:
            raise ModelError("The model ended its stream without a final message.")
        state.usage += finished.usage
        trace.step(finished.usage, finished.stop_reason, time.monotonic() - started)
        return finished


def _leaves(exc: BaseException) -> list[BaseException]:
    """The real errors inside the (possibly nested) exception groups the MCP client's task groups raise."""
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for inner in exc.exceptions for leaf in _leaves(inner)]
    return [exc]


DETAIL = re.compile(r"detall|en profundidad|complet|paso a paso|todos|todas|lista|explica", re.I)


def _too_long(text: str, user_text: str) -> bool:
    """More than six sentences when the user did not ask for detail."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    return len(sentences) > 6 and not DETAIL.search(user_text)


def _chunks(text: str, size: int = 6) -> list[str]:
    words = re.findall(r"\S+\s*", text)
    return ["".join(words[i:i + size]) for i in range(0, len(words), size)] or [text]
