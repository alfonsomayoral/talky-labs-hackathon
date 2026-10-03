"""The normalized landing tables of a phase (documents, bank statements, parse issues)."""
from typing import Any

from ..paging import fingerprint, paginate
from ..ports import LandingCatalog, PhaseRepository
from ..types import Envelope
from . import phase_envelope


class GetLanding:
    def __init__(self, repo: PhaseRepository, catalog: LandingCatalog) -> None:
        self._repo, self._catalog = repo, catalog

    def __call__(self, phase: str) -> Envelope:
        summary = self._repo.phase(phase)
        counts = self._catalog.counts(summary["package_id"], phase, self._repo.location(phase))
        return phase_envelope(self._repo, phase, {"tables": self._catalog.tables(), "counts": counts}, [])


class QueryLanding:
    """Equality filters on the table's own columns, e.g. ``?bank_line=BL0000650`` on ``bank_line``."""

    def __init__(self, repo: PhaseRepository, catalog: LandingCatalog) -> None:
        self._repo, self._catalog = repo, catalog

    def __call__(self, phase: str, table: str, criteria: dict[str, Any], limit: int | None,
                 cursor: str | None) -> Envelope:
        summary = self._repo.phase(phase)
        wanted = {k: (None if v == "null" else v) for k, v in criteria.items()}
        rows = self._catalog.rows(summary["package_id"], phase, self._repo.location(phase), table, wanted)
        return phase_envelope(self._repo, phase, paginate(rows, limit, cursor, fingerprint(phase, "landing", table, wanted)), [])
