"""Pure payment eligibility metadata, not a serialized AP output."""
from dataclasses import dataclass
from kalmora.facts import Evidence


@dataclass(frozen=True)
class PaymentResolution:
    decision: str
    payment_block: str | None = None
    payee: str | None = None
    evidence: tuple[Evidence, ...] = ()
    diagnostics: tuple[str, ...] = ()
