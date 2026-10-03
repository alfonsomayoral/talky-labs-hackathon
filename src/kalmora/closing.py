"""Month-end close command: runs the engines that exist and writes a run bundle for the web app.

``kalmora close PHASE --out OUT`` writes ``OUT/deliverables/<module>.jsonl``, ``OUT/trace/events.jsonl``
and merges ``tasks`` into ``OUT/manifest.json``. It is what ``kalmora serve --close-command`` launches.

A module is *delivered* by its engine, by ``--from-submissions`` (a ``<module>.jsonl`` produced elsewhere,
for example by AP tooling), or it is *unavailable*. Unavailable is not a failure: the web app scores a
missing file as absent. Events are one per delivered row with ``result: INFO``; no engine reports a policy
reference, evidence or confidence, so those stay ``null``.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .facts import atomic_json

MODULES = ("ap", "ar_billing", "ar_cash", "bank_rec", "ic", "close")
Row = dict[str, Any]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_rows(path: Path) -> list[Row]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------- engines
def _ar_cash(phase: Path, target: Path, _work: Path) -> dict[str, Any]:
    from .ar_cash import build_ar_cash
    from .ar_cash.io import write_ar_cash
    from .data import PhaseData
    write_ar_cash(build_ar_cash(PhaseData(phase)), target)
    return {}


def _bank_rec(phase: Path, target: Path, _work: Path) -> dict[str, Any]:
    from .bankrec import build_bank_rec
    from .bankrec.io import write_bank_rec
    from .data import PhaseData
    data = PhaseData(phase)
    run = build_bank_rec(data)
    if run.unresolved:
        raise ValueError("unresolved accounts: " + "; ".join(f"{i.account}: {', '.join(i.reasons)}" for i in run.unresolved))
    if [r.account.id for r in run.results] != list(data.table("tasks/bank_accounts")):
        raise ValueError("did not resolve every task account")
    write_bank_rec(run, target)
    return {}


def _commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True,
                                       cwd=Path(__file__).parent).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _ic(phase: Path, target: Path, work: Path) -> dict[str, Any]:
    """Runs ``python -m kalmora.ic --recorded-only``: AP and bank deliveries are not fed in, and exit 3 says so."""
    out = work / "ic"
    done = subprocess.run([sys.executable, "-m", "kalmora.ic", "--phase", str(phase), "--out", str(out),
                           "--recorded-only", "--backend-commit", _commit()],
                          capture_output=True, text=True, check=False)
    if done.returncode not in (0, 3):
        raise RuntimeError((done.stderr or done.stdout).strip().splitlines()[-1] if (done.stderr or done.stdout).strip()
                           else f"exit code {done.returncode}")
    shutil.copyfile(out / "ic.jsonl", target)
    return {"integration": "recorded_only", "complete": done.returncode == 0}


ENGINES: dict[str, Callable[[Path, Path, Path], dict[str, Any]]] = {"ar_cash": _ar_cash, "bank_rec": _bank_rec, "ic": _ic}


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


def _facts(module: str, row: Row) -> tuple[str, str, str]:
    """(item, kind, summary) of a delivered row, from what the row itself says."""
    if module == "ap":
        reasons = f" ({', '.join(row['reasons'])})" if row.get("reasons") else ""
        return f"ap:{row['doc_id']}", "DECIDE", f"{row.get('document_type')}: {row.get('decision')}{reasons}"
    if module == "ar_billing":
        return f"ar_billing:{row['billing_item']}", "POST", f"Resultado de facturación de {row['billing_item']}"
    if module == "ar_cash":
        return (f"ar_cash:{row['bank_line']}", "DECIDE",
                f"{len(row.get('applications', []))} aplicaciones, {len(row.get('residuals', []))} residuales")
    if module == "ic":
        return f"ic:{'-'.join(sorted(row.get('pair', [])))}/{row.get('cause')}", "DECIDE", f"Diferencia intragrupo por {row.get('cause')}"
    return f"close:{_close_key(row)}", "POST", f"Asiento de cierre {row.get('type')} de {row.get('company')}"


def events(module: str, rows: list[Row], seq: Callable[[], int]) -> Iterator[Row]:
    def event(item: str, kind: str, step: str, summary: str) -> Row:
        n = seq()
        return {"event_id": f"e-{n:06d}", "item": item, "seq": n, "ts": _now(), "kind": kind, "step": step,
                "result": "INFO", "policy_ref": None, "summary": summary, "evidence": [], "model": None,
                "confidence": None}

    for row in rows:
        if module != "bank_rec":
            item, kind, summary = _facts(module, row)
            yield event(item, kind, "deliverable_row", summary)
            continue
        account = str(row.get("account"))
        matches, bank, book = _bank_keys(row)
        yield event(f"bank_rec:{account}", "DECIDE", "account",
                    f"{len(matches)} casados, {len(bank)} banco sin casar, {len(book)} libro sin casar, "
                    f"{len(row.get('adjustments', []))} ajustes")
        for key in matches:
            yield event(f"bank_rec:{account}/{key}", "MATCH", "match", "Línea de banco casada con el libro")
        for key in bank:
            yield event(f"bank_rec:{account}/{key}", "CHECK", "unmatched_bank", "Línea de banco sin casar")
        for key in book:
            yield event(f"bank_rec:{account}/{key}", "CHECK", "unmatched_book", "Línea de libro sin casar")


# ---------------------------------------------------------------- command
def run_close(phase: Path, out: Path, modules: list[str] | None = None, submissions: Path | None = None) -> dict[str, Any]:
    """Run the close. Returns ``{"ok", "tasks"}``; ``ok`` is False when any engine that ran failed."""
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
    counter = iter(range(1, 10**9))
    tasks: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="kalmora-close-") as scratch:
        for module in selected:
            task: dict[str, Any] = {"started_at": _now()}
            tasks[module] = task
            target = out / "deliverables" / f"{module}.jsonl"
            source = submissions / f"{module}.jsonl" if submissions else None
            try:
                if module in ENGINES:
                    task.update(ENGINES[module](phase, target, Path(scratch)), source="engine")
                elif source is not None and source.is_file():
                    shutil.copyfile(source, target)
                    task["source"] = "submission"
                else:
                    task.update(state="unavailable", reason="no engine in this build and no submission supplied")
                    continue
                rows = read_rows(target)
                with trace.open("a", encoding="utf-8") as handle:
                    for event in events(module, rows, lambda: next(counter)):
                        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
                task.update(state="done", rows=len(rows))
            except Exception as exc:  # noqa: BLE001 - one module failing must not hide the others
                target.unlink(missing_ok=True)
                task.update(state="failed", error=f"{type(exc).__name__}: {exc}")
            finally:
                task["finished_at"] = _now()
    manifest_path = out / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    manifest.update(agent_version=__version__, tasks=tasks, models=manifest.get("models", []), human_overrides=0)
    atomic_json(manifest_path, manifest)
    return {"ok": not any(t.get("state") == "failed" for t in tasks.values()), "tasks": tasks}
