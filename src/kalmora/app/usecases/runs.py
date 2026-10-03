"""Execution reports, submissions and the evaluator side."""
from typing import Any

from ..errors import DomainError
from ..paging import fingerprint, paginate
from ..ports import EvaluationGateway, PhaseRepository, RunStore, SubmissionChecker, SubmissionStore
from ..types import Envelope
from . import phase_envelope, plain_envelope

RUN_FIELDS = ("run_id", "command", "status", "started_at", "ended_at", "elapsed_seconds", "cost", "has_files", "dataset", "month")


class ListRuns:
    def __init__(self, runs: RunStore) -> None:
        self._runs = runs

    def __call__(self, limit: int | None, cursor: str | None) -> Envelope:
        rows = [{k: r.get(k) for k in RUN_FIELDS} for r in self._runs.list()]
        return plain_envelope(paginate(rows, limit, cursor, "runs"))


class GetRun:
    """A run's report or manifest; a bundle adds ``deliverables`` (``{module: {present, rows}}``)."""

    def __init__(self, runs: RunStore, store: SubmissionStore | None = None) -> None:
        self._runs, self._store = runs, store

    def __call__(self, run_id: str) -> Envelope:
        run = self._runs.get(run_id)
        if self._store is not None and (self._runs.files_root(run_id) / "deliverables").is_dir():
            run = {**run, "deliverables": self._store.files(run_id)}
        return plain_envelope(run)


class StartRun:
    """Launches the configured close command on a loaded phase; the run is followed with ``GetRun``."""

    def __init__(self, repo: PhaseRepository, closer: Any) -> None:
        self._repo, self._closer = repo, closer

    def __call__(self, phase: str) -> Envelope:
        if self._closer is None:
            raise DomainError("run.unavailable", "No close command is configured (kalmora serve --close-command).")
        location = self._repo.location(phase)
        month = self._repo.meta(phase, [])["month"]
        return plain_envelope({"run_id": self._closer.start(phase, location, month)})


class GetSubmission:
    def __init__(self, repo: PhaseRepository, submissions: SubmissionStore) -> None:
        self._repo, self._submissions = repo, submissions

    def __call__(self, phase: str) -> Envelope:
        self._repo.location(phase)
        return phase_envelope(self._repo, phase, {"files": self._submissions.files(phase)}, [])


class ListSubmissionRows:
    def __init__(self, repo: PhaseRepository, submissions: SubmissionStore) -> None:
        self._repo, self._submissions = repo, submissions

    def __call__(self, phase: str, module: str, limit: int | None, cursor: str | None) -> Envelope:
        self._repo.location(phase)
        rows = self._submissions.rows(phase, module)
        return phase_envelope(self._repo, phase, paginate(rows, limit, cursor, fingerprint(phase, "submission", module)), [])


class CheckSubmission:
    def __init__(self, repo: PhaseRepository, submissions: SubmissionStore, checker: SubmissionChecker) -> None:
        self._repo, self._submissions, self._checker = repo, submissions, checker

    def __call__(self, phase: str) -> Envelope:
        self._repo.location(phase)
        present = [m for m, info in self._submissions.files(phase).items() if info["present"]]
        diagnostics = self._checker.check({m: self._submissions.rows(phase, m) for m in present})
        problems = [{"module": d["module"], "ref": f"{d['module']}.jsonl:{d['entity']}", "problem": d["message"]}
                    for d in diagnostics]
        return phase_envelope(self._repo, phase, {"ok": not problems, "checked": present, "problems": problems}, [])


class GetEvaluation:
    """Compare the submission with the golden. Only answers when the evaluator is enabled."""

    def __init__(self, repo: PhaseRepository, submissions: SubmissionStore, gateway: EvaluationGateway) -> None:
        self._repo, self._submissions, self._gateway = repo, submissions, gateway

    def _report(self, phase: str) -> dict[str, Any]:
        if not self._gateway.enabled:
            raise DomainError("evaluation.unavailable", "The evaluator is not enabled in this process.")
        location = self._repo.location(phase)
        return self._gateway.evaluate(phase, location, self._submissions.directory(phase))

    def __call__(self, phase: str, module: str | None = None) -> Envelope:
        report = self._report(phase)
        if module is not None:
            if module not in report["modules"]:
                raise DomainError("request.invalid", f"module must be one of: {', '.join(report['modules'])}.")
            return phase_envelope(self._repo, phase, report["modules"][module], [])
        data = {"total": report["total"], "modules": report["module_scores"],
                "reconciliation_ok": report["reconciliation_ok"], "separation": report["separation"],
                "report_id": report["report_id"]}
        return phase_envelope(self._repo, phase, data, [])
