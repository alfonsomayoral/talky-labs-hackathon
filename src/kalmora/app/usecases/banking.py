"""Bank accounts, statement lines and FX rates."""
from ..errors import DomainError
from ..paging import fingerprint, paginate
from ..params import compact, iso_date, month
from ..ports import PhaseRepository
from ..types import Envelope
from . import phase_envelope


class ListBankAccounts:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, *, company: str | None = None, limit: int | None = None,
                 cursor: str | None = None) -> Envelope:
        rows = self._repo.bank_accounts(phase, company)
        return phase_envelope(self._repo, phase, paginate(rows, limit, cursor, fingerprint(phase, "banks", company)),
                              ["erp/bank_accounts.jsonl"])


class GetBankLines:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, account: str, *, month_: str | None = None, date_from: str | None = None,
                 date_to: str | None = None, min_amount: int | None = None, max_amount: int | None = None,
                 q: str | None = None, limit: int | None = None, cursor: str | None = None) -> Envelope:
        filters = compact(month=month("month", month_), date_from=iso_date("from", date_from),
                          date_to=iso_date("to", date_to), min_amount=min_amount, max_amount=max_amount, q=q)
        rows = self._repo.bank_lines(phase, account, filters)
        return phase_envelope(self._repo, phase,
                              paginate(rows, limit, cursor, fingerprint(phase, "bank", account, filters)), [])


class GetFxRates:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, *, currency: str | None = None, date: str | None = None,
                 date_from: str | None = None, date_to: str | None = None,
                 limit: int | None = None, cursor: str | None = None) -> Envelope:
        date = iso_date("date", date)
        if date is not None:
            if currency is None:
                raise DomainError("request.invalid", "date requires currency.")
            row = self._repo.fx_rate_at(phase, currency, date)
            return phase_envelope(self._repo, phase, paginate([row], limit, cursor, fingerprint(phase, "fx", currency, date)),
                                  ["erp/fx_rates.jsonl"])
        filters = compact(currency=currency, date_from=iso_date("from", date_from), date_to=iso_date("to", date_to))
        rows = self._repo.fx_rates(phase, filters)
        return phase_envelope(self._repo, phase, paginate(rows, limit, cursor, fingerprint(phase, "fx", filters)),
                              ["erp/fx_rates.jsonl"])
