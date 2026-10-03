"""Run bundles: deliverables, trace events, attention items and human overrides of one run."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, get_args

from ...model.trace import AttentionKind, EventKind, EventResult, Priority, TASKS
from ..errors import DomainError
from ..paging import fingerprint, paginate
from ..params import compact, one_of
from ..ports import EvaluationGateway, PhaseRepository, RunStore, SubmissionChecker, SubmissionStore
from ..types import Envelope
from . import phase_envelope, plain_envelope

CLOSE_KEYS = {"ACCRUAL": "vendor", "PREPAID": "invoice", "FX_REVAL": "item", "BAD_DEBT": "customer",
              "WIP_REVENUE": "billing_item"}
ROW_KEY = {"ap": "doc_id", "ar_billing": "billing_item", "ar_cash": "bank_line"}


def split_item(item: str) -> tuple[str, str]:
    task, _, key = item.partition(":")
    if task not in TASKS or not key:
        raise DomainError("request.invalid", f"item must be '<task>:<key>' with task in {', '.join(TASKS)}.")
    return task, key


def row_for_item(task: str, key: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The delivered row an item id points at (see ``TraceEvent.item`` for the key of each task)."""
    if task in ROW_KEY:
        return next((r for r in rows if r.get(ROW_KEY[task]) == key), None)
    if task == "bank_rec":
        account = key.split("/", 1)[0]
        return next((r for r in rows if r.get("account") == account), None)
    if task == "ic":
        pair, _, cause = key.partition("/")
        wanted = sorted(pair.split("-"))
        return next((r for r in rows if sorted(r.get("pair", [])) == wanted and r.get("cause") == cause), None)
    kind, _, rest = key.partition("/")
    company, _, identity = rest.partition("/")
    field = CLOSE_KEYS.get(kind)
    return next((r for r in rows if r.get("type") == kind and r.get("company") == company
                 and field and r.get(field) == identity), None)


class GetRunSubmission:
    def __init__(self, runs: RunStore, store: SubmissionStore) -> None:
        self._runs, self._store = runs, store

    def __call__(self, run_id: str) -> Envelope:
        self._runs.files_root(run_id)
        return plain_envelope({"run_id": run_id, "files": self._store.files(run_id)})


class ListRunSubmissionRows:
    def __init__(self, runs: RunStore, store: SubmissionStore) -> None:
        self._runs, self._store = runs, store

    def __call__(self, run_id: str, module: str, limit: int | None, cursor: str | None) -> Envelope:
        self._runs.files_root(run_id)
        rows = self._store.rows(run_id, module)
        return plain_envelope(paginate(rows, limit, cursor, fingerprint(run_id, "deliverable", module)))


class CheckRunSubmission:
    def __init__(self, runs: RunStore, store: SubmissionStore, checker: SubmissionChecker) -> None:
        self._runs, self._store, self._checker = runs, store, checker

    def __call__(self, run_id: str) -> Envelope:
        self._runs.files_root(run_id)
        present = [m for m, info in self._store.files(run_id).items() if info["present"]]
        diagnostics = self._checker.check({m: self._store.rows(run_id, m) for m in present})
        problems = [{"module": d["module"], "ref": f"{d['module']}.jsonl:{d['entity']}", "problem": d["message"]}
                    for d in diagnostics]
        return plain_envelope({"ok": not problems, "checked": present, "problems": problems})


class GetRunEvaluation:
    """Score a run's deliverables against the golden, which never leaves the server."""

    def __init__(self, runs: RunStore, repo: PhaseRepository, store: SubmissionStore,
                 gateway: EvaluationGateway) -> None:
        self._runs, self._repo, self._store, self._gateway = runs, repo, store, gateway

    def __call__(self, run_id: str, module: str | None = None) -> Envelope:
        manifest = self._runs.get(run_id)
        if not self._gateway.enabled:
            raise DomainError("evaluation.unavailable", "The evaluator is not enabled in this process.")
        phase = manifest.get("dataset")
        if not phase:
            raise DomainError("run.phase_unknown", "The run's manifest does not name the phase it closed.")
        report = self._gateway.evaluate(phase, self._repo.location(phase), self._store.directory(run_id))
        if module is not None:
            if module not in report["modules"]:
                raise DomainError("request.invalid", f"module must be one of: {', '.join(report['modules'])}.")
            return phase_envelope(self._repo, phase, report["modules"][module], [])
        return phase_envelope(self._repo, phase, {
            "run_id": run_id, "total": report["total"], "modules": report["module_scores"],
            "reconciliation_ok": report["reconciliation_ok"], "separation": report["separation"],
            "report_id": report["report_id"]}, [])


class ListRunEvents:
    def __init__(self, runs: RunStore) -> None:
        self._runs = runs

    def __call__(self, run_id: str, *, item: str | None = None, kind: str | None = None,
                 result: str | None = None, step: str | None = None, limit: int | None = None,
                 cursor: str | None = None) -> Envelope:
        kind = one_of("kind", kind, get_args(EventKind))
        result = one_of("result", result, get_args(EventResult))
        filters = compact(item=item, kind=kind, result=result, step=step)
        rows = [e for e in self._runs.events(run_id) if all(e.get(k) == v for k, v in filters.items())]
        return plain_envelope(paginate(rows, limit, cursor, fingerprint(run_id, "events", filters)))


class ListRunAttention:
    def __init__(self, runs: RunStore) -> None:
        self._runs = runs

    def __call__(self, run_id: str, *, item: str | None = None, kind: str | None = None,
                 priority: str | None = None, limit: int | None = None, cursor: str | None = None) -> Envelope:
        kind = one_of("kind", kind, get_args(AttentionKind))
        priority = one_of("priority", priority, get_args(Priority))
        filters = compact(item=item, kind=kind, priority=priority)
        rows = [a for a in self._runs.attention(run_id) if all(a.get(k) == v for k, v in filters.items())]
        rows.sort(key=lambda a: a.get("priority", "P9"))
        return plain_envelope(paginate(rows, limit, cursor, fingerprint(run_id, "attention", filters)))


class GetRunItem:
    """Everything a run knows about one item: its delivered row, its trace, its attention items and overrides."""

    def __init__(self, runs: RunStore, store: SubmissionStore) -> None:
        self._runs, self._store = runs, store

    def __call__(self, run_id: str, item: str) -> Envelope:
        task, key = split_item(item)
        self._runs.files_root(run_id)
        try:
            row = row_for_item(task, key, self._store.rows(run_id, task))
        except DomainError as exc:
            if exc.code != "submission.not_found":
                raise
            row = None
        events = [e for e in self._runs.events(run_id) if e.get("item") == item]
        attention = [a for a in self._runs.attention(run_id) if a.get("item") == item]
        ids = {a.get("attention_id") for a in attention}
        overrides = [o for o in self._runs.overrides(run_id) if o.get("item") == item or o.get("attention_id") in ids]
        if row is None and not events and not attention:
            raise DomainError("item.not_found", f"Run {run_id} has nothing about '{item}'.")
        return plain_envelope({"item": item, "task": task, "key": key, "row": row, "events": events,
                               "attention": attention, "overrides": overrides})


class AddOverride:
    """Record a human correction next to the run it corrects. Append-only; ``user`` is as declared by the client."""

    def __init__(self, runs: RunStore) -> None:
        self._runs = runs

    def __call__(self, run_id: str, body: Any) -> Envelope:
        self._runs.files_root(run_id)
        if not isinstance(body, dict):
            raise DomainError("request.invalid", "Body must be an object.")
        allowed = {"attention_id", "item", "decision", "note", "user"}
        extra = sorted(set(body) - allowed)
        if extra:
            raise DomainError("request.invalid", f"Unknown field(s): {', '.join(extra)}.")
        if not isinstance(body.get("decision"), str) or not body["decision"].strip():
            raise DomainError("request.invalid", "decision is required.")
        if bool(body.get("attention_id")) == bool(body.get("item")):
            raise DomainError("request.invalid", "Give exactly one of attention_id or item.")
        for field in ("attention_id", "item", "note", "user"):
            if field in body and not isinstance(body[field], str):
                raise DomainError("request.invalid", f"{field} must be a string.")
        if body.get("item"):
            split_item(body["item"])
        if body.get("attention_id") and body["attention_id"] not in {a.get("attention_id") for a in self._runs.attention(run_id)}:
            raise DomainError("attention.not_found", f"Run {run_id} has no attention item '{body['attention_id']}'.")
        row = {**{k: body[k] for k in ("attention_id", "item", "decision", "note", "user") if k in body},
               "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
        self._runs.add_override(run_id, row)
        return plain_envelope(row)


class ListOverrides:
    def __init__(self, runs: RunStore) -> None:
        self._runs = runs

    def __call__(self, run_id: str, limit: int | None, cursor: str | None) -> Envelope:
        return plain_envelope(paginate(self._runs.overrides(run_id), limit, cursor, fingerprint(run_id, "overrides")))


def _company_of(row: dict[str, Any]) -> str:
    """Company a delivered row belongs to: its own field, its entry's, or its first adjustment line's."""
    if row.get("company"):
        return str(row["company"])
    entry = row.get("journal_entry")
    if isinstance(entry, dict) and entry.get("company"):
        return str(entry["company"])
    lines = row.get("adjustment") or [l for a in row.get("adjustments", []) for l in a.get("lines", [])]
    return str(lines[0].get("company", "unknown")) if lines else "unknown"


class SummarizeRun:
    """Counts and totals over a run's delivered files and trace, so nobody has to page rows to see the shape of a close.

    Totals are in cents of each company's own currency and are kept **per company**: they are never added
    across companies.
    """

    def __init__(self, runs: RunStore, store: SubmissionStore) -> None:
        self._runs, self._store = runs, store

    def _rows(self, run_id: str, task: str) -> list[dict[str, Any]] | None:
        try:
            return self._store.rows(run_id, task)
        except DomainError as exc:
            if exc.code == "submission.not_found":
                return None
            raise

    def __call__(self, run_id: str) -> Envelope:
        manifest = self._runs.get(run_id)
        files = self._store.files(run_id) if (self._runs.files_root(run_id) / "deliverables").is_dir() else {}
        out: dict[str, Any] = {"run_id": run_id, "dataset": manifest.get("dataset"), "month": manifest.get("month"),
                               "status": manifest.get("status"), "deliverables": files}
        ap = self._rows(run_id, "ap")
        if ap is not None:
            out["ap"] = {"rows": len(ap), "by_decision": dict(Counter(r.get("decision") for r in ap)),
                         "by_document_type": dict(Counter(r.get("document_type") for r in ap)),
                         "reasons": dict(Counter(code for r in ap for code in r.get("reasons") or []))}
        billing = self._rows(run_id, "ar_billing")
        if billing is not None:
            payable: dict[str, int] = defaultdict(int)
            for r in billing:
                if r.get("expected") == "INVOICE":
                    payable[_company_of(r)] += int((r.get("invoice") or {}).get("payable") or 0)
            out["ar_billing"] = {"rows": len(billing), "by_expected": dict(Counter(r.get("expected") for r in billing)),
                                 "payable_cents_by_company": dict(payable)}
        cash = self._rows(run_id, "ar_cash")
        if cash is not None:
            applied: dict[str, int] = defaultdict(int)
            for r in cash:
                applied[_company_of(r)] += sum(int(a.get("amount") or 0) for a in r.get("applications") or [])
            out["ar_cash"] = {"rows": len(cash), "residual_count_by_type": dict(Counter(
                x.get("type") for r in cash for x in r.get("residuals") or [])), "applied_cents_by_company": dict(applied)}
        bank = self._rows(run_id, "bank_rec")
        if bank is not None:
            out["bank_rec"] = {"accounts": len(bank), "account_ids": [r.get("account") for r in bank[:50]],
                               "unmatched_bank_by_category": dict(Counter(x.get("category") for r in bank for x in r.get("unmatched_bank") or [])),
                               "unmatched_book_by_category": dict(Counter(x.get("category") for r in bank for x in r.get("unmatched_book") or [])),
                               "adjustments_by_category": dict(Counter(x.get("category") for r in bank for x in r.get("adjustments") or []))}
        ic = self._rows(run_id, "ic")
        if ic is not None:
            out["ic"] = {"rows": len(ic), "by_cause": dict(Counter(r.get("cause") for r in ic)),
                         "items": [{"pair": r.get("pair"), "cause": r.get("cause"), "responsible": r.get("responsible")} for r in ic[:50]]}
        close = self._rows(run_id, "close")
        if close is not None:
            amounts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
            for r in close:
                amounts[str(r.get("type"))][_company_of(r)] += int(r.get("amount") or 0)
            out["close"] = {"rows": len(close), "by_type": dict(Counter(r.get("type") for r in close)),
                            "amount_cents_by_type_and_company": {t: dict(c) for t, c in amounts.items()}}
        attention, events = self._runs.attention(run_id), self._runs.events(run_id)
        out["attention"] = {"count": len(attention), "by_priority": dict(sorted(Counter(a.get("priority") for a in attention).items()))}
        out["trace"] = {"present": bool(events), "events": len(events), "by_result": dict(Counter(e.get("result") for e in events))}
        out["overrides"] = {"count": len(self._runs.overrides(run_id))}
        return plain_envelope(out)


class Calculate:
    """Exact integer arithmetic for the few derivations an answer needs, so a model never does money math.

    ``sum`` and ``count`` take any number of values; ``difference`` takes two (first minus second);
    ``percent_bp`` returns ``part / whole`` in basis points (half up); ``apply_rate_bp`` returns
    ``amount * bp / 10000`` with ``rounding`` ``half_up`` or ``truncate`` (toward zero).
    """

    OPS = ("sum", "difference", "percent_bp", "apply_rate_bp", "count")

    def __call__(self, op: str, values: list[int], rounding: str = "half_up") -> Envelope:
        if op not in self.OPS:
            raise DomainError("request.invalid", f"op must be one of: {', '.join(self.OPS)}.")
        if not isinstance(values, list) or not 1 <= len(values) <= 1000 or any(
                isinstance(v, bool) or not isinstance(v, int) for v in values):
            raise DomainError("request.invalid", "values must be 1 to 1000 integers (cents or counts); no decimals.")
        if rounding not in ("half_up", "truncate"):
            raise DomainError("request.invalid", "rounding must be half_up or truncate.")

        def divide(numerator: int, denominator: int) -> int:
            sign = -1 if (numerator < 0) != (denominator < 0) else 1
            q, r = divmod(abs(numerator), abs(denominator))
            if rounding == "half_up" and 2 * r >= abs(denominator):
                q += 1
            return sign * q

        if op == "sum":
            result, unit = sum(values), "same as the inputs"
        elif op == "count":
            result, unit = len(values), "count"
        elif op == "difference":
            if len(values) != 2:
                raise DomainError("request.invalid", "difference needs exactly two values: first minus second.")
            result, unit = values[0] - values[1], "same as the inputs"
        elif op == "percent_bp":
            if len(values) != 2 or values[1] == 0:
                raise DomainError("request.invalid", "percent_bp needs [part, whole] with whole not zero.")
            result, unit = divide(values[0] * 10000, values[1]), "basis points (100 = 1 %)"
        else:
            if len(values) != 2:
                raise DomainError("request.invalid", "apply_rate_bp needs [amount, basis_points].")
            result, unit = divide(values[0] * values[1], 10000), "same as the amount"
        return plain_envelope({"op": op, "result": result, "unit": unit, "rounding": rounding})
