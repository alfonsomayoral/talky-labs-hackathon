"""Month-end close command: runs the engines that exist and writes a run bundle for the web app.

``kalmora close PHASE --out OUT`` writes ``OUT/deliverables/<module>.jsonl``, ``OUT/trace/events.jsonl``
and merges ``tasks`` into ``OUT/manifest.json``. It is what ``kalmora serve --close-command`` launches.
The manifest is rewritten as each module starts and ends, so a poller sees the run advance. An engine's own
working files (IC audit, close handoff, decisions and balance snapshots, their run reports) are kept as
``OUT/trace/<module>.zip``: the web app downloads every JSON of a bundle, and the IC audit alone is ~20 MB.

Modules run in dependency order and feed each other: bank rec reads this run's AP, AR cash reads this run's
billing and AP, and close (the M6 engine, when integrated) reads every delivery. AP uses the v0 rule
engine; AR billing uses recorded source observations and the typed billing engine.
A module is *delivered* by its engine, by ``--from-submissions`` (a ``<module>.jsonl``
produced elsewhere), or it is *unavailable*. Unavailable is not a failure: the web app scores a
missing file as absent.

Events are appended once a module succeeds: first the findings its engine reports (AR cash and bank rec
diagnostics, IC findings and blocking diagnostics, close decisions, AP rows that could not be coded), then one event per
delivered row. An engine does not grade its diagnostics, so they are ``INFO`` unless the engine itself marks
them blocking or the row shows the failure. No engine reports a policy reference or confidence, so those stay
``null``. Findings without an item go to ``manifest.tasks.<module>.diagnostics``.
"""
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .facts import atomic_json
from .runlog import RunRecorder

# Dependency order: bank rec needs AP, AR cash needs billing, close needs all of them.
MODULES = ("ap", "ar_billing", "bank_rec", "ar_cash", "ic", "close")
Row = dict[str, Any]
Engine = Callable[[Path, Path, Path, list[Row]], dict[str, Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_rows(path: Path) -> list[Row]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def note(item: str, kind: str, step: str, result: str, summary: str, evidence: list[Row] | None = None) -> Row:
    """An event without its id, sequence and time, which are stamped when the module's events are written."""
    return {"item": item, "kind": kind, "step": step, "result": result, "policy_ref": None, "summary": summary,
            "evidence": evidence or [], "model": None, "confidence": None}


# ---------------------------------------------------------------- engines
def _delivered(target: Path, module: str) -> list[Row] | None:
    """Rows this run already delivered for ``module`` (an upstream input), or None."""
    path = target.parent / f"{module}.jsonl"
    return read_rows(path) if path.is_file() else None


def _ap(phase: Path, target: Path, _work: Path, notes: list[Row]) -> dict[str, Any]:
    from .v0.solve import POSTING, solve_ap, write_jsonl
    rows, errors = solve_ap(phase)
    write_jsonl(target, rows)
    for row in rows:
        if row.get("decision") in POSTING and not row.get("journal_entry"):
            notes.append(note(f"ap:{row['doc_id']}", "POST", "coding", "FAIL",
                              f"Decisión {row['decision']}, pero el motor no pudo codificar el asiento"))
    return {"coding_errors": errors}


def _ar_billing(phase: Path, target: Path, work: Path, notes: list[Row]) -> dict[str, Any]:
    import asyncio
    from dataclasses import asdict
    from .billing.source_runner import build_billing_from_sources
    from .billing.io import write_billing_files
    from .data import PhaseData
    for destination in (target, target.with_name("pending_wip.jsonl")):
        resolved = destination.resolve()
        if resolved.is_relative_to(phase.resolve()) or any(part.lower() == "golden" for part in resolved.parts):
            raise ValueError("AR delivery must be outside original phase data and golden")
    source = asyncio.run(build_billing_from_sources(PhaseData(phase), work_dir=work))
    if not source.complete:
        raise ValueError("unresolved AR billing sources; see the archived source report")
    write_billing_files(source.billing, target)
    for result in source.billing.results:
        finding = note(f"ar_billing:{result.item.id}", "CHECK", "source_evidence", "INFO",
                       f"Facturación sustentada en {len(result.evidence)} referencias originales",
                       [asdict(evidence) for evidence in result.evidence])
        finding["policy_ref"] = "POLITICAS_CONTABLES.md §3.1"
        notes.append(finding)
    return {"engine": "sources", "pending_wip": len(source.billing.pending_wip),
            "source_output_sha256": source.stable_sha256, "source_coverage": source.report["coverage"]}


def _ar_cash(phase: Path, target: Path, _work: Path, notes: list[Row]) -> dict[str, Any]:
    from .ar_cash import build_ar_cash
    from .ar_cash.io import write_ar_cash
    from .data import PhaseData
    billing, ap = _delivered(target, "ar_billing"), _delivered(target, "ap")
    run = build_ar_cash(PhaseData(phase), billing=billing or [], ap=ap or [])
    write_ar_cash(run, target)
    for result in run.results:
        notes.extend(note(f"ar_cash:{result.row['bank_line']}", "CHECK", "diagnostic", "INFO", text)
                     for text in result.diagnostics)
    return {"billing_input": billing is not None, "ap_input": ap is not None, "diagnostics": list(run.diagnostics)}


def _bank_rec(phase: Path, target: Path, _work: Path, notes: list[Row]) -> dict[str, Any]:
    from .bankrec import build_bank_rec
    from .bankrec.io import write_bank_rec
    from .data import PhaseData
    data = PhaseData(phase)
    ap_rows = _delivered(target, "ap")
    run = build_bank_rec(data, ap_rows=ap_rows)
    if run.unresolved:
        raise ValueError("unresolved accounts: " + "; ".join(f"{i.account}: {', '.join(i.reasons)}" for i in run.unresolved))
    if [r.account.id for r in run.results] != list(data.table("tasks/bank_accounts")):
        raise ValueError("did not resolve every task account")
    write_bank_rec(run, target)
    rows = {str(row.get("account")): row for row in read_rows(target)}
    for result in run.results:
        account = str(result.account.id)
        keys = {key for group in _bank_keys(rows.get(account, {})) for key in group}
        for text in result.diagnostics:
            # A diagnostic reads "<path>: <problem>"; a path that names a line of the row is that line's item.
            ref = text.partition(": ")[0]
            item = f"bank_rec:{account}/{ref}" if ref in keys else f"bank_rec:{account}"
            notes.append(note(item, "CHECK", "diagnostic", "INFO", text))
    return {"ap_input": ap_rows is not None}


def _commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True,
                                       cwd=Path(__file__).parent).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _ic(phase: Path, target: Path, work: Path, notes: list[Row]) -> dict[str, Any]:
    """Runs ``python -m kalmora.ic --recorded-only``: AP and bank deliveries are not fed in, and exit 3 says so."""
    done = subprocess.run([sys.executable, "-m", "kalmora.ic", "--phase", str(phase), "--out", str(work),
                           "--recorded-only", "--backend-commit", _commit()],
                          capture_output=True, text=True, check=False)
    if done.returncode not in (0, 3):
        raise RuntimeError((done.stderr or done.stdout).strip().splitlines()[-1] if (done.stderr or done.stdout).strip()
                           else f"exit code {done.returncode}")
    shutil.copyfile(work / "ic.jsonl", target)
    audit = json.loads((work / "audit.json").read_text(encoding="utf-8"))
    items = {}
    for finding in audit["findings"]:
        items[finding["event_id"]] = item = _ic_item(finding)
        notes.append(note(item, "CHECK", "finding", "INFO", f"Diferencia {finding['cause']} detectada ({finding['status']})",
                          [_evidence(e) for e in finding["evidence"]]))
    loose = []
    for diagnostic in audit["diagnostics"]:
        text = f"{diagnostic['code']}: {diagnostic['message']}"
        if diagnostic.get("event_id") in items:
            notes.append(note(items[diagnostic["event_id"]], "CHECK", "diagnostic",
                              "FAIL" if diagnostic["blocking"] else "INFO", text,
                              [_evidence(e) for e in diagnostic["evidence"]]))
        else:
            loose.append(text)
    return {"integration": "recorded_only", "complete": done.returncode == 0, "diagnostics": loose}


def _close(phase: Path, target: Path, work: Path, notes: list[Row]) -> dict[str, Any]:
    from .v0.close_handoff import run_close as close_from_deliveries
    shutil.copyfile(close_from_deliveries(phase, target.parent, work), target)
    delivered = {_close_key(row) for row in read_rows(target)}
    # A decision with no delivered row (e.g. no adjustment needed) stays in trace/close.zip only.
    for decision in read_rows(work / "frozen" / "close_decisions.jsonl"):
        if (key := _close_key(decision)) in delivered:
            notes.append(note(f"close:{key}", "DECIDE", "decision", "INFO", f"{decision['type']}: {decision['action']}",
                              [_evidence(e) for e in decision.get("evidence", [])]))
    return {"integration": "real_upstream"}


ENGINES: dict[str, Engine] = {
    "ap": _ap, "ar_billing": _ar_billing, "ar_cash": _ar_cash, "bank_rec": _bank_rec, "ic": _ic}
if importlib.util.find_spec("kalmora.close") is not None:  # the M6 engine (PR #197), once integrated
    ENGINES["close"] = _close


# ---------------------------------------------------------------- events
def _bank_keys(row: Row) -> tuple[list[str], list[str], list[str]]:
    """Item keys inside a bank_rec row, as ``app/src/engine/ids.ts::bankRowKeys`` derives them."""
    used: set[str] = set()

    def claim(preferred: str | None, fallback: str) -> str:
        key, n = (preferred if preferred and preferred not in used else fallback), 2
        while key in used:
            key, n = f"{fallback}~{n}", n + 1
        used.add(key)
        return key

    matches = [claim((m.get("bank_lines") or [None])[0], f"match-{i}") for i, m in enumerate(row.get("matches", []), 1)]
    bank = [claim(str(x.get("bank_line")), f"bank-{i}") for i, x in enumerate(row.get("unmatched_bank", []), 1)]
    book = [claim(str(x.get("book_line")), f"book-{i}") for i, x in enumerate(row.get("unmatched_book", []), 1)]
    return matches, bank, book


def _close_key(row: Row) -> str:
    for field in ("vendor", "invoice", "item", "customer", "billing_item"):
        if row.get(field) is not None:
            return f"{row['type']}/{row['company']}/{row[field]}"
    return f"{row.get('type')}/{row.get('company')}/"


def _ic_item(row: Row) -> str:
    return f"ic:{'-'.join(sorted(row.get('pair', [])))}/{row.get('cause')}"


def _evidence(evidence: Row) -> Row:
    """An engine's ``kalmora.facts.Evidence`` as a trace reference: a journal line, an ERP record or a document."""
    source, field = evidence["document"], evidence["field"]
    if source == "erp/journal_entries.jsonl" and "#" in field:
        return {"kind": "journal", "book_line": field}
    if source.startswith("erp/"):
        return {"kind": "erp", "file": source, "key": field}
    return {"kind": "doc", "path": source, "locator": field}


def _facts(module: str, row: Row) -> tuple[str, str, str, str]:
    """(item, kind, result, summary) of a delivered row, from what the row itself says."""
    if module == "ap":
        reasons = f" ({', '.join(row['reasons'])})" if row.get("reasons") else ""
        return f"ap:{row['doc_id']}", "DECIDE", "INFO", f"{row.get('document_type')}: {row.get('decision')}{reasons}"
    if module == "ar_billing":
        return f"ar_billing:{row['billing_item']}", "POST", "INFO", f"Resultado de facturación de {row['billing_item']}"
    if module == "ar_cash":
        applied, residual = len(row.get("applications", [])), len(row.get("residuals", []))
        return (f"ar_cash:{row['bank_line']}", "DECIDE", "INFO" if applied or residual else "FAIL",
                f"{applied} aplicaciones, {residual} residuales" if applied or residual else "Cobro sin resolver")
    if module == "ic":
        return _ic_item(row), "DECIDE", "INFO", f"Diferencia intragrupo por {row.get('cause')}"
    return f"close:{_close_key(row)}", "POST", "INFO", f"Asiento de cierre {row.get('type')} de {row.get('company')}"


def events(module: str, rows: list[Row]) -> Iterator[Row]:
    """One event per delivered row (bank rec: per account and per line), without id, sequence or time."""
    for row in rows:
        if module != "bank_rec":
            item, kind, result, summary = _facts(module, row)
            yield note(item, kind, "deliverable_row", result, summary)
            continue
        account = str(row.get("account"))
        matches, bank, book = _bank_keys(row)
        yield note(f"bank_rec:{account}", "DECIDE", "account", "INFO",
                   f"{len(matches)} casados, {len(bank)} banco sin casar, {len(book)} libro sin casar, "
                   f"{len(row.get('adjustments', []))} ajustes")
        for key in matches:
            yield note(f"bank_rec:{account}/{key}", "MATCH", "match", "INFO", "Línea de banco casada con el libro")
        for key in bank:
            yield note(f"bank_rec:{account}/{key}", "CHECK", "unmatched_bank", "INFO", "Línea de banco sin casar")
        for key in book:
            yield note(f"bank_rec:{account}/{key}", "CHECK", "unmatched_book", "INFO", "Línea de libro sin casar")


def _usage(recorder: RunRecorder) -> Row:
    """Models and cost of the run's provider calls, in the manifest's terms; an unknown cost is ``None``."""
    models: dict[tuple[str, str], Row] = {}
    for call in recorder.report["calls"]:
        model = models.setdefault((call["provider"], call["model"]), {
            "provider": call["provider"], "name": call["model"], "calls": 0, "input_tokens": 0, "output_tokens": 0,
            "cost_usd": 0.0})
        model["calls"] += 1
        model["input_tokens"] += call["input_tokens"] or 0
        model["output_tokens"] += call["output_tokens"] or 0
        if call["estimated_cost"] is not None and call["pricing"]["currency"] == "USD":
            model["cost_usd"] += float(call["estimated_cost"])
    cost = recorder.cost()
    total = (0 if cost["status"] == "no_llm" else float(cost["estimated_by_currency"]["USD"])
             if cost["status"] == "estimated" and set(cost["estimated_by_currency"]) == {"USD"} else None)
    return {"models": list(models.values()), "cost_usd_total": total, "cost": cost}


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


# ---------------------------------------------------------------- command
def run_close(phase: Path, out: Path, modules: list[str] | None = None, submissions: Path | None = None,
              recorder: RunRecorder | None = None) -> dict[str, Any]:
    """Run the close. Returns ``{"ok", "tasks"}``; ``ok`` is False when any engine that ran failed.

    With a ``recorder``, the manifest takes its run id and its models and cost."""
    phase, out = phase.resolve(), out.resolve()
    if out.is_relative_to(phase) or "golden" in out.parts:
        raise ValueError("close output must be outside the read-only phase directory")
    selected = list(modules or MODULES)
    if unknown := [m for m in selected if m not in MODULES]:
        raise ValueError(f"unknown module(s): {', '.join(unknown)}")
    (out / "deliverables").mkdir(parents=True, exist_ok=True)
    trace = out / "trace" / "events.jsonl"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text("", encoding="utf-8")
    written = 0
    began = time.monotonic()
    tasks: dict[str, dict[str, Any]] = {}
    manifest_path = out / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    if recorder is not None:
        manifest.setdefault("run_id", recorder.run_id)
    manifest.setdefault("dataset", phase.name)
    manifest.setdefault("started_at", _now())
    manifest.update(agent_version=__version__, commit=_commit(), tasks=tasks,
                    policies_sha256=_sha256(phase.parent / "POLITICAS_CONTABLES.md"))
    for module in selected:
        task: dict[str, Any] = {"state": "running", "started_at": _now()}
        tasks[module] = task
        atomic_json(manifest_path, manifest)
        target = out / "deliverables" / f"{module}.jsonl"
        source = submissions / f"{module}.jsonl" if submissions else None
        notes: list[Row] = []
        work = Path(tempfile.mkdtemp(prefix=f"kalmora-{module}-"))
        try:
            if module in ENGINES:
                task.update(ENGINES[module](phase, target, work, notes), source="engine")
            elif source is not None and source.is_file():
                shutil.copyfile(source, target)
                task["source"] = "submission"
            else:
                task.update(state="unavailable", reason="no engine in this build and no submission supplied")
                continue
            rows = read_rows(target)
            stamped = [{"event_id": f"e-{written + n:06d}", "seq": written + n, "ts": _now(), **event}
                       for n, event in enumerate([*notes, *events(module, rows)], 1)]
            with trace.open("a", encoding="utf-8") as handle:
                handle.writelines(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n" for e in stamped)
            written += len(stamped)
            task.update(state="done", rows=len(rows), events=len(stamped))
        except Exception as exc:  # noqa: BLE001 - one module failing must not hide the others
            target.unlink(missing_ok=True)
            task.update(state="failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            # Kept on failure too: what the engine wrote before failing is the evidence of why.
            if any(work.iterdir()):
                shutil.make_archive(str(trace.parent / module), "zip", work)
            shutil.rmtree(work, ignore_errors=True)
            task["finished_at"] = _now()
    manifest.setdefault("finished_at", _now())
    manifest["runtime_s"] = manifest.get("runtime_s") or round(time.monotonic() - began, 3)
    if recorder is not None:
        manifest.update(_usage(recorder))
    atomic_json(manifest_path, manifest)
    return {"ok": not any(t.get("state") == "failed" for t in tasks.values()), "tasks": tasks}
