"""One class per use case. Each returns the ``{data, meta}`` envelope of the contract."""
from typing import Any

from ..ports import PhaseRepository
from ..types import Envelope, SCHEMA_VERSION


def phase_envelope(repo: PhaseRepository, phase: str, data: Any, sources: list[str]) -> Envelope:
    return {"data": data, "meta": repo.meta(phase, sources)}


def plain_envelope(data: Any) -> Envelope:
    return {"data": data, "meta": {"schema_version": SCHEMA_VERSION}}
