"""An explicit invoice observation; missing log amounts/currency stay unknown."""
from dataclasses import dataclass
from kalmora.facts import Evidence


@dataclass(frozen=True)
class DuplicateRecord:
    doc_id: str
    company: str
    vendor: str
    currency: str | None
    number: str
    received_at: str
    amount_cents: int | None
    evidence: tuple[Evidence, ...]
    status: str | None = None
    corrected_by: str | None = None
    duplicate_of: str | None = None
    service_period: str | None = None
    document_type: str = "INVOICE"
