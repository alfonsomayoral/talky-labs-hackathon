"""One phase in, one run folder out: the six tasks in dependency order, each fed by the previous outputs.

AP -> AR billing -> bank rec (with AP) -> AR cash (with billing) -> intercompany (recorded book).
Close is produced by the M6 engine (#197) once it is integrated; until then its file is absent.
Writes ``deliverables/<task>.jsonl`` and ``manifest.json`` (timing per task, no model calls) under ``out``.
"""
from __future__ import annotations

import json
import shutil
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..ar_cash import build_ar_cash
from ..ar_cash.io import write_ar_cash
from ..bankrec import build_bank_rec
from ..bankrec.io import write_bank_rec
from ..data import PhaseData
from .solve import solve_ap, solve_billing, write_jsonl


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_chain(phase: Path, out: Path, *, backend_commit: str = "unknown") -> dict[str, Any]:
    phase, out = phase.resolve(), out.resolve()
    if out.is_relative_to(phase):
        raise ValueError("outputs must be outside the read-only phase directory")
    deliverables = out / "deliverables"
    deliverables.mkdir(parents=True, exist_ok=True)
    data = PhaseData(phase)
    tasks: dict[str, dict[str, Any]] = {}
    shared: dict[str, Any] = {}
    began = time.monotonic()
    started_at = _now()

    def step(name: str, work: Callable[[], str]) -> None:
        record: dict[str, Any] = {"started_at": _now()}
        try:
            record["result"] = work()
        except Exception as exc:  # noqa: BLE001 - one task failing must not stop the others
            record["error"] = f"{type(exc).__name__}: {exc}"
            (out / f"{name}.error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        record["finished_at"] = _now()
        tasks[name] = record

    def ap() -> str:
        rows, errors = solve_ap(phase)
        shared["ap"] = rows
        write_jsonl(deliverables / "ap.jsonl", rows)
        return f"{len(rows)} rows, {errors} coding errors"

    def billing() -> str:
        rows, pending = solve_billing(phase)
        shared["billing"] = rows
        write_jsonl(deliverables / "ar_billing.jsonl", rows)
        write_jsonl(out / "work" / "pending_wip.jsonl", pending)
        return f"{len(rows)} rows, {len(pending)} pending certifications"

    def bank() -> str:
        result = build_bank_rec(data, ap_rows=shared.get("ap"))
        if result.unresolved:
            raise ValueError(f"unresolved accounts: {[item.account for item in result.unresolved]}")
        write_bank_rec(result, deliverables / "bank_rec.jsonl")
        return f"{len(result.results)} accounts"

    def cash() -> str:
        result = build_ar_cash(data, billing=shared.get("billing", []))
        write_ar_cash(result, deliverables / "ar_cash.jsonl")
        return f"{len(result.results)} receipts"

    def intercompany() -> str:
        from ..ic.__main__ import main as ic_main
        code = ic_main(["--phase", str(phase), "--out", str(out / "work" / "ic"), "--recorded-only",
                        "--backend-commit", backend_commit])
        shutil.copyfile(out / "work" / "ic" / "ic.jsonl", deliverables / "ic.jsonl")
        return f"exit {code} (3 = recorded book only, without AP/bank upstream)"

    for name, work in (("ap", ap), ("ar_billing", billing), ("bank_rec", bank), ("ar_cash", cash), ("ic", intercompany)):
        step(name, work)
    manifest = {"dataset": phase.name, "month": data.month, "started_at": started_at, "finished_at": _now(),
                "runtime_s": round(time.monotonic() - began, 3), "models": [], "cost_usd_total": 0,
                "agent_version": f"kalmora v0 chain @ {backend_commit}", "human_overrides": 0, "tasks": tasks}
    existing = out / "manifest.json"
    if existing.is_file():  # launched by the API: keep its identity fields
        manifest = {**json.loads(existing.read_text(encoding="utf-8")), **manifest}
    existing.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest
