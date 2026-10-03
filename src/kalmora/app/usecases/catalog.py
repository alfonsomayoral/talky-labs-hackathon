"""Phases, master data, task queues and inbox documents."""
from ..errors import DomainError
from ..paging import fingerprint, paginate
from ..params import compact, one_of
from ..ports import PhaseRepository
from ..types import Envelope
from . import phase_envelope, plain_envelope

TASK_KEYS = {"ap_documents": "doc_ids", "ar_billing_items": "billing_items",
             "ar_receipts": "bank_lines", "bank_accounts": "accounts"}
SOURCES = {"companies": "erp/companies.json", "accounts": "erp/chart_of_accounts.jsonl",
           "cost-centers": "erp/cost_centers.jsonl", "vendors": "erp/vendors.jsonl",
           "customers": "erp/customers.jsonl", "projects": "erp/projects.jsonl",
           "tax-codes": "erp/tax_codes.json"}


class ListPhases:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self) -> Envelope:
        return plain_envelope(self._repo.phases())


class GetPhase:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str) -> Envelope:
        return phase_envelope(self._repo, phase, self._repo.phase(phase), [])


class ListRecords:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, collection: str, *, company: str | None = None, q: str | None = None,
                 type: str | None = None, open_items: bool | None = None, prefix: str | None = None,
                 limit: int | None = None, cursor: str | None = None) -> Envelope:
        allowed = {"companies": (), "accounts": ("type", "open_items", "prefix"), "cost-centers": ("company",),
                   "vendors": ("company", "q"), "customers": ("company", "q"), "projects": ("company",),
                   "tax-codes": ()}[collection]
        supplied = compact(company=company, q=q, type=one_of("type", type, ("BS", "PL")),
                           open_items=open_items, prefix=prefix)
        unsupported = sorted(set(supplied) - set(allowed))
        if unsupported:
            raise DomainError("request.invalid", f"{collection} does not support: {', '.join(unsupported)}.")
        rows = self._repo.records(phase, collection, supplied)
        page = paginate(rows, limit, cursor, fingerprint(phase, collection, supplied))
        return phase_envelope(self._repo, phase, page, [SOURCES[collection]])


class GetRecord:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, collection: str, record_id: str) -> Envelope:
        return phase_envelope(self._repo, phase, self._repo.record(phase, collection, record_id),
                              [SOURCES[collection]])


class ListTasks:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str) -> Envelope:
        return phase_envelope(self._repo, phase, {"tasks": sorted(self._repo.tasks(phase))}, [])


class GetTask:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, task: str) -> Envelope:
        tasks = self._repo.tasks(phase)
        if task not in tasks:
            raise DomainError("task.not_found", f"No task '{task}'. Available: {', '.join(sorted(tasks))}.")
        value = tasks[task]
        data = {TASK_KEYS[task]: value} if task in TASK_KEYS else value
        return phase_envelope(self._repo, phase, data, [f"tasks/{task}.json"])


class ListDocuments:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, *, kind: str | None = None, limit: int | None = None,
                 cursor: str | None = None) -> Envelope:
        kind = one_of("kind", kind, ("ap", "ar"))
        rows = self._repo.documents(phase, kind)
        return phase_envelope(self._repo, phase, paginate(rows, limit, cursor, fingerprint(phase, "documents", kind)), [])


class GetDocument:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, doc_id: str) -> Envelope:
        for row in self._repo.documents(phase, None):
            if row.get("doc_id") == doc_id:
                return phase_envelope(self._repo, phase, row, [])
        raise DomainError("document.not_found", f"No inbox document '{doc_id}'.")
