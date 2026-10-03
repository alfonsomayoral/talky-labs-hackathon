"""Observed AP notice: receipt time and validity are independent facts."""
from dataclasses import dataclass

from kalmora.facts import Evidence
from .ap_scope import ApScope


@dataclass(frozen=True)
class ApEvent:
    event_id: str
    scope: ApScope
    kind: str
    evidence: tuple[Evidence, ...]
    # None means an explicitly registered baseline, not an inferred receipt date.
    received_at: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    verified: bool | None = None
    value: str | None = None
    invoice_number: str | None = None
