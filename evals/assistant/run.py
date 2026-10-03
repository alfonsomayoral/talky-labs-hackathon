"""Runner and report for the assistant evals.

    python -m evals.assistant list
    python -m evals.assistant selfcheck                 # every case against its reference trajectory (no model)
    python -m evals.assistant t0t1                      # the deterministic suites (unit tests), reported by case id
    python -m evals.assistant run --provider ollama --model qwen3:14b --k 3 --star
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import tempfile
import time
import unittest
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from kalmora.assistant.loop import Assistant, ChatRequest, DEEP, FAST, Rates
from kalmora.assistant.model import AgentModel, FakeModel, Step

from . import fixtures
from . import graders as g
from .cases import Case, Params, build_cases, world_inject
from .harness import Answer, World, collect_async
from .oracles import Data

SYNTHETIC_RUNS = "synthetic"


@dataclass
class Trial:
    case: str
    index: int
    passed: bool
    checks: list[dict[str, Any]]
    answer: str
    status: str | None
    seconds: float
    tools: list[str]
    usage: dict[str, int]
    cost_usd: str | None
    error: str | None = None
    cards: int = 0


@dataclass
class Environment:
    """What cases run against: in-process worlds over the synthetic fixture, or one live MCP endpoint."""
    data: Data
    params: Params
    runs: dict[str, str]
    run_dir: Path | None
    worlds: dict[str, World] = field(default_factory=dict)
    live_url: str | None = None
    valid_refs: set[str] | None = None
    _tmp: Any = None

    def world(self, key: str) -> World:
        if key not in self.worlds:
            if key == "base":
                self.worlds[key] = World()
            elif key == "test":
                self.worlds[key] = World(phase="phase_test")
            elif key == "two":
                self.worlds[key] = World(archive=fixtures.build_two_phase_zip())
            elif key.startswith("inj:"):
                self.worlds[key] = World(inject=world_inject(key))
            else:
                raise KeyError(key)
        return self.worlds[key]

    def close(self) -> None:
        for w in self.worlds.values():
            w.close()
        if self._tmp is not None:
            self._tmp.cleanup()


def synthetic_environment() -> Environment:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for name, text in fixtures.phase_files().items():
        target = root / "phase" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    base = World()      # the base world owns the run bundles the oracles read
    env = Environment(Data(root / "phase"), Params(), base.runs, base.run_dir, {"base": base}, _tmp=tmp)
    return env


def run_id_of(case: Case, env: Environment, world: World | None) -> str | None:
    if case.run is None:
        return None
    ids = world.runs if world is not None and world.runs else env.runs
    return ids.get(case.run, case.run)


async def play(case: Case, env: Environment, model: AgentModel, fast: AgentModel | None, *, rates: Rates | None, compact: bool,
               judge: Any = None, limits: dict[str, Any] | None = None) -> tuple[Answer, dict[str, Any], list[Answer]]:
    world = None if env.live_url else env.world(case.world)
    if env.live_url:
        from kalmora.assistant.tools import McpHttpSource
        assistant = Assistant(models={"deep": model, "fast": fast or model}, source=McpHttpSource(env.live_url), rates=rates, compact=compact,
                              limits=limits or {"fast": FAST, "deep": DEEP})
    else:
        assistant = world.assistant(model, fast, rates=rates, compact=compact, **({"limits": limits} if limits else {}))
    history = list(case.history)
    answers: list[Answer] = []
    for question in case.turns:
        request = ChatRequest(messages=[*history, {"role": "user", "content": question}], mode=case.mode,
                              run_id=run_id_of(case, env, world), dataset_id=case.dataset)
        answer = await collect_async(assistant, request)
        answers.append(answer)
        history += [{"role": "user", "content": question}, {"role": "assistant", "content": answer.text or (answer.error or "")}]
    return answers[-1], assistant.last_trace, answers


def grade(case: Case, env: Environment, answer: Answer, trace: dict[str, Any], answers: list[Answer], judge: Any = None) -> tuple[bool, list[dict[str, Any]]]:
    ctx = g.Ctx(answer, trace, env.data, answers, judge=judge)
    if env.valid_refs is not None:
        ctx.valid_refs = env.valid_refs
    results = []
    for check in case.checks:
        ok, detail = check(ctx)
        results.append({"check": check.name, "passed": ok, "detail": "" if ok else detail})
    return all(r["passed"] for r in results), results


def run_trial(case: Case, index: int, env: Environment, make_model: Any, *, rates: Rates | None, compact: bool, judge: Any, limits: Any = None) -> Trial:
    model, fast = make_model(case)
    started = time.monotonic()
    try:
        answer, trace, answers = asyncio.run(play(case, env, model, fast, rates=rates, compact=compact, judge=judge, limits=limits))
    except Exception as exc:  # noqa: BLE001 - a crashed trial is a failed trial, with the reason
        return Trial(case.id, index, False, [{"check": "run", "passed": False, "detail": f"{type(exc).__name__}: {exc}"}], "", None,
                     time.monotonic() - started, [], {}, None, error=f"{type(exc).__name__}: {exc}")
    passed, checks = grade(case, env, answer, trace, answers, judge)
    return Trial(case.id, index, passed, checks, answer.text or (answer.error or ""), (answer.done or {}).get("status") or ("error" if answer.error else None),
                 time.monotonic() - started, [c["name"] for c in trace.get("tool_calls", []) if not c.get("local")], trace.get("usage", {}),
                 trace.get("cost_usd"), answer.error, len(answer.cards))


def summarize(trials: list[Trial], k: int) -> dict[str, Any]:
    by_case: dict[str, list[Trial]] = defaultdict(list)
    for t in trials:
        by_case[t.case].append(t)
    cases = {cid: {"trials": len(ts), "passed": sum(t.passed for t in ts), "pass_hat_k": all(t.passed for t in ts), "pass_at_k": any(t.passed for t in ts)} for cid, ts in by_case.items()}
    suites: dict[str, dict[str, Any]] = defaultdict(lambda: {"cases": 0, "pass_hat_k": 0, "pass_at_k": 0, "trials": 0, "trials_passed": 0})
    for cid, c in cases.items():
        s = suites[cid[0]]
        s["cases"] += 1
        s["pass_hat_k"] += c["pass_hat_k"]
        s["pass_at_k"] += c["pass_at_k"]
        s["trials"] += c["trials"]
        s["trials_passed"] += c["passed"]
    seconds = sorted(t.seconds for t in trials)
    tools = [len(t.tools) for t in trials]
    return {"k": k, "cases": cases, "suites": dict(suites),
            "latency_s": {"p50": round(statistics.median(seconds), 2) if seconds else None, "p95": round(seconds[int(0.95 * (len(seconds) - 1))], 2) if seconds else None},
            "tool_calls": {"median": statistics.median(tools) if tools else None, "max": max(tools) if tools else None},
            "tokens": {"input": sum(t.usage.get("input_tokens", 0) for t in trials), "output": sum(t.usage.get("output_tokens", 0) for t in trials)},
            "cost_usd": str(sum((Decimal(t.cost_usd) for t in trials if t.cost_usd), Decimal(0)))}


def markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [f"# Assistant evals · {report['meta']['mode']} · {report['meta']['model']}", "",
             f"{report['meta']['when']} · k={s['k']} · {len(s['cases'])} cases · latency p50 {s['latency_s']['p50']} s, p95 {s['latency_s']['p95']} s · "
             f"tool calls median {s['tool_calls']['median']} · tokens in/out {s['tokens']['input']}/{s['tokens']['output']} · cost {s['cost_usd']}", "",
             "| suite | cases | pass^k | pass@k | trials passed |", "|---|---|---|---|---|"]
    for name, v in sorted(s["suites"].items()):
        lines.append(f"| {name} | {v['cases']} | {v['pass_hat_k']}/{v['cases']} | {v['pass_at_k']}/{v['cases']} | {v['trials_passed']}/{v['trials']} |")
    failed = [t for t in report["trials"] if not t["passed"]]
    if failed:
        lines += ["", "## Failures", ""]
        for t in failed:
            bad = "; ".join(f"{c['check']}: {c['detail']}" for c in t["checks"] if not c["passed"])
            lines.append(f"- **{t['case']}** (trial {t['index']}, {t['status']}): {bad}\n  > {t['answer'][:240].replace(chr(10), ' ')}")
    return "\n".join(lines) + "\n"


def select(cases: list[Case], args: argparse.Namespace) -> list[Case]:
    chosen = cases
    if getattr(args, "suite", None):
        chosen = [c for c in chosen if c.suite in args.suite.split(",")]
    if getattr(args, "ids", None):
        wanted = set(args.ids.split(","))
        chosen = [c for c in chosen if c.id in wanted]
    if getattr(args, "star", False):
        chosen = [c for c in chosen if c.star]
    if getattr(args, "split", None):
        chosen = [c for c in chosen if c.split == args.split]
    if getattr(args, "limit", None):
        chosen = chosen[: args.limit]
    return chosen


SECRET = re.compile(r"sk-[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._-]{20,}|api[_-]?key[\"']?\s*[:=]\s*[\"'][^\"']{12,}", re.I)


def secrets_scan(report: dict[str, Any], trace_dir: Path | None) -> list[str]:
    """K06: no key, token or credential in the report or in the turn traces."""
    found = [f"report: {m.group(0)[:20]}..." for m in SECRET.finditer(json.dumps(report, default=str))]
    if trace_dir and trace_dir.is_dir():
        for path in trace_dir.rglob("*.json"):
            found += [f"{path.name}: {m.group(0)[:20]}..." for m in SECRET.finditer(path.read_text(encoding="utf-8", errors="replace"))]
    return found


def write_report(report: dict[str, Any], out: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = out / stamp
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (folder / "report.md").write_text(markdown(report), encoding="utf-8")
    return folder


def build_model_factory(args: argparse.Namespace):
    if args.provider == "reference":
        return lambda case: (FakeModel(list(case.ref) or [Step(text="")], name="reference"), None)
    if args.provider == "negative":      # content-free answer with no tool: graders that accept it are not discriminating
        return lambda case: (FakeModel([Step(text="Todo está en orden.")], name="negative"), None)
    from kalmora.assistant.config import chat_settings, load_environment
    from kalmora.assistant.service import make_models
    settings = chat_settings(load_environment(env_file=getattr(args, "env_file", None)), provider=args.provider, model=args.model,
                             fast_model=args.fast_model, ollama_url=args.ollama_url, num_ctx=args.num_ctx, think=args.think)
    args.settings = settings
    def fresh(case: Case) -> tuple[AgentModel, AgentModel]:
        models = make_models(settings)     # one HTTP client per trial: each trial runs in its own event loop
        return models["deep"], models["fast"]
    return fresh


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.assistant")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "selfcheck", "negcheck", "run", "t0t1"):
        p = sub.add_parser(name)
        p.add_argument("--suite")
        p.add_argument("--ids")
        p.add_argument("--star", action="store_true")
        p.add_argument("--split", choices=("dev", "test"))
        p.add_argument("--limit", type=int)
        if name == "run":
            p.add_argument("--provider", choices=("ollama", "openai"), help="Overrides KALMORA_AI_PROVIDER")
            p.add_argument("--model", help="Overrides KALMORA_AI_MODEL")
            p.add_argument("--fast-model", help="Overrides KALMORA_AI_FAST_MODEL")
            p.add_argument("--env-file", type=Path)
            p.add_argument("--ollama-url")
            p.add_argument("--num-ctx", type=int)
            p.add_argument("--think", action="store_true")
            p.add_argument("--timeout", type=float, default=600.0, help="Seconds per turn (a local model needs minutes for a cold prompt)")
            p.add_argument("--k", type=int, default=1)
            p.add_argument("--live-mcp", help="Run against a live MCP endpoint (real data) instead of the synthetic worlds")
            p.add_argument("--private", type=Path, help="Real phase directory: generate the real-data cases from it (use with --live-mcp)")
            p.add_argument("--run-dir", type=Path, help="Run folder of the real data (for the B cases)")
            p.add_argument("--compact-knowledge", action="store_true")
            p.add_argument("--budget-usd", type=Decimal, help="Stop when the estimated spend passes this (needs prices)")
            p.add_argument("--out", type=Path, default=Path("outputs/evals/assistant"))
    args = parser.parse_args(argv)
    if args.command == "t0t1":
        suite = unittest.defaultTestLoader.discover("tests", pattern="test_assistant*.py")
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        return 0 if result.wasSuccessful() else 1
    env = synthetic_environment()
    try:
        cases = build_cases(env.data, env.params, env.run_dir, env.runs)
        if args.command == "run" and args.private:
            from .private import private_environment
            env.close()
            env, cases = private_environment(args.private, args.run_dir, args.live_mcp)
        cases = select(cases, args)
        if args.command == "list":
            for c in cases:
                print(json.dumps({"id": c.id, "suite": c.suite, "tier": c.tier, "split": c.split, "star": c.star, "needs": c.needs, "world": c.world,
                                  "turns": c.turns, "checks": [ch.name for ch in c.checks]}, ensure_ascii=False))
            print(f"{len(cases)} cases", file=sys.stderr)
            return 0
        rates = None
        if args.command == "run":
            if args.live_mcp:
                env.live_url = args.live_mcp
        args.provider = {"selfcheck": "reference", "negcheck": "negative"}.get(args.command, getattr(args, "provider", None))
        make_model = build_model_factory(args)
        if args.command == "run":
            rates = args.settings.rates
            args.model = args.settings.model
            args.provider = args.settings.provider
        k = 1 if args.command in ("selfcheck", "negcheck") else args.k
        trials, spent = [], Decimal(0)
        for case in cases:
            if args.command == "run" and args.provider == "ollama" and "judge" in case.needs:
                pass
            for index in range(k):
                from dataclasses import replace as _replace
                limits = {"fast": _replace(FAST, timeout_s=getattr(args, "timeout", FAST.timeout_s)), "deep": _replace(DEEP, timeout_s=getattr(args, "timeout", DEEP.timeout_s))}
                trial = run_trial(case, index, env, make_model, rates=rates, compact=getattr(args, "compact_knowledge", False), judge=None, limits=limits)
                trials.append(trial)
                mark = "ok  " if trial.passed else "FAIL"
                print(f"{mark} {case.id:<6} {trial.seconds:6.1f}s calls={len(trial.tools)} {trial.status or ''}", flush=True)
                if trial.cost_usd:
                    spent += Decimal(trial.cost_usd)
            if getattr(args, "budget_usd", None) is not None and spent > args.budget_usd:
                print(f"budget of {args.budget_usd} USD reached after {case.id}", file=sys.stderr)
                break
        report = {"meta": {"mode": args.command, "model": args.settings.model if args.command == "run" else "reference",
                           "provider": args.provider, "when": datetime.now(timezone.utc).isoformat(timespec="seconds"), "live": env.live_url},
                  "summary": summarize(trials, k), "trials": [t.__dict__ for t in trials]}
        if args.command == "run":
            report["summary"]["k06_secrets"] = secrets_scan(report, Path("outputs/chat"))
        print(markdown(report))
        if args.command == "run":
            print("K06 secrets in reports and traces:", report["summary"]["k06_secrets"] or "none")
            print("report:", write_report(report, args.out))
        if args.command == "negcheck":
            lenient = [t.case for t in trials if t.passed]
            print(f"graders that accept a content-free answer ({len(lenient)}): {', '.join(lenient) or 'none'}")
            return 0
        return 0 if all(t.passed for t in trials) else 1
    finally:
        env.close()


if __name__ == "__main__":
    sys.exit(main())
