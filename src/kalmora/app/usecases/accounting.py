"""Journal, balances and open items."""
from ..errors import DomainError
from ..paging import fingerprint, paginate
from ..params import compact, iso_date, one_of
from ..ports import PhaseRepository
from ..types import Envelope
from . import phase_envelope

JOURNAL = "erp/journal_entries.jsonl"


class QueryJournalEntries:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, *, company: str | None = None, account: str | None = None,
                 partner: str | None = None, doc_type: str | None = None, source: str | None = None,
                 reference: str | None = None, date_from: str | None = None, date_to: str | None = None,
                 include: str | None = None, limit: int | None = None, cursor: str | None = None) -> Envelope:
        include = one_of("include", include, ("lines", "header")) or "lines"
        filters = compact(company=company, account=account, partner=partner, doc_type=doc_type, source=source,
                          reference=reference, date_from=iso_date("from", date_from), date_to=iso_date("to", date_to))
        rows = self._repo.journal_entries(phase, filters)
        page = paginate(rows, limit, cursor, fingerprint(phase, "journal", filters, include))
        if include == "header":
            page["items"] = [{**{k: v for k, v in e.items() if k != "lines"}, "line_count": len(e["lines"])}
                             for e in page["items"]]
        return phase_envelope(self._repo, phase, page, [JOURNAL])


class GetJournalEntry:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, entry_id: str) -> Envelope:
        return phase_envelope(self._repo, phase, self._repo.journal_entry(phase, entry_id), [JOURNAL])


class QueryJournalLines:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, *, company: str | None = None, account: str | None = None,
                 partner: str | None = None, doc_type: str | None = None, date_from: str | None = None,
                 date_to: str | None = None, limit: int | None = None, cursor: str | None = None) -> Envelope:
        filters = compact(company=company, account=account, partner=partner, doc_type=doc_type,
                          date_from=iso_date("from", date_from), date_to=iso_date("to", date_to))
        rows = self._repo.journal_lines(phase, filters)
        return phase_envelope(self._repo, phase, paginate(rows, limit, cursor, fingerprint(phase, "lines", filters)), [JOURNAL])


class GetBalances:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, *, company: str | None = None, account: str | None = None,
                 account_prefix: str | None = None, nonzero: bool | None = None,
                 limit: int | None = None, cursor: str | None = None) -> Envelope:
        filters = compact(company=company, account=account, account_prefix=account_prefix, nonzero=nonzero)
        rows = self._repo.balances(phase, filters)
        return phase_envelope(self._repo, phase, paginate(rows, limit, cursor, fingerprint(phase, "balances", filters)), [JOURNAL])


class GetBalanceSummary:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, *, company: str | None = None) -> Envelope:
        rows = self._repo.balance_summary(phase, company)
        if company is not None:
            if not rows:
                raise DomainError("record.not_found", f"No entries for company '{company}'.")
            return phase_envelope(self._repo, phase, rows[0], [JOURNAL])
        return phase_envelope(self._repo, phase, {"companies": rows}, [JOURNAL])


class GetOpenItems:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, *, company: str | None = None, account: str | None = None,
                 partner: str | None = None, assignment: str | None = None, only_open: bool = True,
                 source: str | None = None, limit: int | None = None, cursor: str | None = None) -> Envelope:
        source = one_of("source", source, ("ledger", "master")) or "ledger"
        filters = compact(company=company, account=account, partner=partner, assignment=assignment)
        filters.update(only_open=only_open, source=source)
        rows = self._repo.open_items(phase, filters)
        files = [JOURNAL] if source == "ledger" else ["erp/open_items.jsonl"]
        return phase_envelope(self._repo, phase, paginate(rows, limit, cursor, fingerprint(phase, "open", filters)), files)
