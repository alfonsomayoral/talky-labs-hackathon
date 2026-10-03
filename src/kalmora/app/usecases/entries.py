"""Pure entry checks: nothing is stored."""
from typing import Any

from ..errors import DomainError
from ..ports import PhaseRepository
from ...validation import validate_entry
from ..types import Envelope
from . import phase_envelope


def _entry(body: Any) -> dict[str, Any]:
    entry = body.get("entry") if isinstance(body, dict) else None
    if not isinstance(entry, dict):
        raise DomainError("entry.invalid", "Body must be an object with an 'entry' object.")
    return entry


class ValidateEntry:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, body: Any) -> Envelope:
        entry = _entry(body)
        with_masters = body.get("with_masters", True)
        if not isinstance(with_masters, bool):
            raise DomainError("request.invalid", "with_masters must be a boolean.")
        context = self._repo.validation_context(phase) if with_masters else None
        diagnostics = validate_entry(entry, context)  # type: ignore[arg-type]
        return phase_envelope(self._repo, phase, {"valid": not diagnostics, "diagnostics": diagnostics}, [])


class SimulateEntry:
    """Post the entry on a copy of the recorded book and report what would change."""

    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, body: Any) -> Envelope:
        entry = _entry(body)
        provenance = body.get("provenance")
        if not isinstance(provenance, dict) or not all(isinstance(provenance.get(k), str) and provenance[k]
                                                       for k in ("event_id", "stage")):
            raise DomainError("request.invalid", "provenance requires non-empty event_id and stage.")
        projection = self._repo.ledger_projection(phase)
        before_balances, before_items = projection.balances(), projection.open_items()
        diagnostics = validate_entry(entry, self._repo.validation_context(phase))  # type: ignore[arg-type]
        result: dict[str, Any] = {"valid": False, "diagnostics": diagnostics, "balance_delta": [], "open_item_delta": []}
        if not diagnostics:
            try:
                projection.add_entry(entry, event_id=provenance["event_id"], stage=provenance["stage"])  # type: ignore[arg-type]
            except (ValueError, TypeError) as exc:
                result["diagnostics"] = str(exc).split("; ")
            else:
                result["valid"] = True
                after_balances, after_items = projection.balances(), projection.open_items()
                for key in sorted(set(after_balances) | set(before_balances)):
                    if after_balances.get(key, 0) != before_balances.get(key, 0):
                        before, after = before_balances.get(key, 0), after_balances.get(key, 0)
                        result["balance_delta"].append({"company": key.company, "account": key.account,
                                                        "before": before, "delta": after - before, "after": after})
                for key in sorted(set(after_items) | set(before_items), key=lambda k: tuple(x or "" for x in k)):
                    if after_items.get(key, 0) != before_items.get(key, 0):
                        result["open_item_delta"].append({"key": key._asdict(), "before": before_items.get(key, 0),
                                                          "after": after_items.get(key, 0)})
        return phase_envelope(self._repo, phase, result, [])
